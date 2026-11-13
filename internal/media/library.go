// Package media manages the media library: discovery, metadata, thumbnails,
// display renditions, blurred backgrounds and video transcodes.
//
// Derived files are produced once (at import, or lazily on first request) and
// cached on disk, so the display only ever loads screen-sized assets.
package media

import (
	"context"
	"crypto/rand"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/olkham/DigitalCanvas/internal/imaging"
)

// Kind of media.
type Kind string

const (
	KindImage Kind = "image"
	KindVideo Kind = "video"
	KindGIF   Kind = "gif"
)

var (
	imageExts = map[string]bool{".png": true, ".jpg": true, ".jpeg": true, ".bmp": true, ".webp": true}
	videoExts = map[string]bool{".mp4": true, ".mov": true, ".avi": true, ".webm": true, ".mkv": true, ".m4v": true}
	uuidRe    = regexp.MustCompile(`^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$`)
)

const (
	thumbMinSide = 320
	thumbVersion = 2
	bgLongSide   = 256
)

// KindOf classifies a file name by extension.
func KindOf(name string) (Kind, bool) {
	ext := strings.ToLower(filepath.Ext(name))
	switch {
	case ext == ".gif":
		return KindGIF, true
	case imageExts[ext]:
		return KindImage, true
	case videoExts[ext]:
		return KindVideo, true
	}
	return "", false
}

// Item describes one media file. Values handed out by the library are copies.
type Item struct {
	Name        string  `json:"name"`
	Title       string  `json:"title,omitempty"` // original file name, when known
	Kind        Kind    `json:"kind"`
	Width       int     `json:"width"`
	Height      int     `json:"height"`
	Orientation string  `json:"orientation"`
	Duration    float64 `json:"duration,omitempty"`
	Size        int64   `json:"size"`
	Added       int64   `json:"added"`  // unix ms
	Version     int64   `json:"v"`      // changes whenever derived assets change
	Status      string  `json:"status"` // ready | processing | error
	Error       string  `json:"error,omitempty"`
	Playable    bool    `json:"playable"`
	Optimized   bool    `json:"optimized,omitempty"`
	HasThumb    bool    `json:"has_thumb"`

	rec record
}

// Stem is the file name without extension.
func (it Item) Stem() string { return strings.TrimSuffix(it.Name, filepath.Ext(it.Name)) }

// record is the persisted metadata cache entry (cache/library.json).
type record struct {
	Size      int64   `json:"size"`
	MTime     int64   `json:"mtime"`
	Kind      Kind    `json:"kind"`
	W         int     `json:"w"`
	H         int     `json:"h"`
	Exif      int     `json:"exif,omitempty"`
	Format    string  `json:"format,omitempty"`
	Duration  float64 `json:"duration,omitempty"`
	Codec     string  `json:"codec,omitempty"`
	PixFmt    string  `json:"pix_fmt,omitempty"`
	Probed    bool    `json:"probed,omitempty"`
	ThumbV    int     `json:"thumb_v,omitempty"`
	NoThumb   bool    `json:"no_thumb,omitempty"`
	Transcode string  `json:"transcode,omitempty"` // "", "done", "failed"
	Bad       bool    `json:"bad,omitempty"`       // unreadable video
	Title     string  `json:"title,omitempty"`
}

// Event is emitted on library changes.
type Event struct {
	Type string // add | update | remove
	Item Item
}

// Options configure a Library.
type Options struct {
	MediaDir, ThumbDir, CacheDir string
	// Transcode reports whether automatic video transcoding is enabled.
	Transcode func() bool
}

// Library is the media collection.
type Library struct {
	opts Options
	ff   *FFmpeg

	mu      sync.RWMutex
	items   map[string]*Item
	screen  atomic.Uint64    // w<<32 | h, read without locks
	pending map[string]int64 // name -> size seen on last watch tick

	listenMu  sync.RWMutex
	listeners []func(Event)

	fmu    sync.Mutex
	flight map[string]*call

	prepQ  chan string
	transQ chan string
	saveT  *time.Timer
	ctx    context.Context
	cancel context.CancelFunc
}

type call struct {
	done chan struct{}
	err  error
}

// Open creates the directories and starts the background workers.
func Open(opts Options) (*Library, error) {
	for _, d := range []string{opts.MediaDir, opts.ThumbDir, opts.CacheDir,
		filepath.Join(opts.CacheDir, "display"), filepath.Join(opts.CacheDir, "bg"),
		filepath.Join(opts.CacheDir, "poster"), filepath.Join(opts.CacheDir, "video")} {
		if err := os.MkdirAll(d, 0o755); err != nil {
			return nil, err
		}
	}
	if opts.Transcode == nil {
		opts.Transcode = func() bool { return true }
	}
	ctx, cancel := context.WithCancel(context.Background())
	l := &Library{
		opts: opts, ff: NewFFmpeg(),
		items: map[string]*Item{}, pending: map[string]int64{},
		flight: map[string]*call{},
		prepQ:  make(chan string, 1<<14), transQ: make(chan string, 1<<12),
		ctx: ctx, cancel: cancel,
	}
	l.screen.Store(1920<<32 | 1080)
	workers := max(1, min(2, runtime.NumCPU()/2))
	for i := 0; i < workers; i++ {
		go l.prepWorker()
	}
	go l.transcodeWorker()
	return l, nil
}

// Close stops background work.
func (l *Library) Close() {
	l.cancel()
	l.saveNow()
}

// FFmpegAvailable reports whether video tooling is present.
func (l *Library) FFmpegAvailable() bool { return l.ff.Available() }

// Subscribe registers a change listener.
func (l *Library) Subscribe(fn func(Event)) {
	l.listenMu.Lock()
	l.listeners = append(l.listeners, fn)
	l.listenMu.Unlock()
}

func (l *Library) emit(typ string, it Item) {
	l.listenMu.RLock()
	ls := append([]func(Event){}, l.listeners...)
	l.listenMu.RUnlock()
	for _, fn := range ls {
		fn(Event{Type: typ, Item: it})
	}
}

// SetScreen records the display resolution used for renditions.
func (l *Library) SetScreen(w, h int) {
	if w < 320 || h < 240 {
		return
	}
	l.screen.Store(uint64(w)<<32 | uint64(h))
}

// Screen returns the display resolution.
func (l *Library) Screen() (int, int) {
	v := l.screen.Load()
	return int(v >> 32), int(v & 0xffffffff)
}

// Limit is the "max useful size": renditions are scaled so their shorter
// side is no larger than the longer side of the screen (any rotation fits).
func (l *Library) Limit() int {
	w, h := l.Screen()
	return max(w, h)
}

// Items returns a snapshot sorted by date added (oldest first).
func (l *Library) Items() []Item {
	l.mu.RLock()
	out := make([]Item, 0, len(l.items))
	for _, it := range l.items {
		out = append(out, *it)
	}
	l.mu.RUnlock()
	sort.Slice(out, func(i, j int) bool {
		if out[i].Added != out[j].Added {
			return out[i].Added < out[j].Added
		}
		return out[i].Name < out[j].Name
	})
	return out
}

// Get returns one item.
func (l *Library) Get(name string) (Item, bool) {
	l.mu.RLock()
	defer l.mu.RUnlock()
	it, ok := l.items[name]
	if !ok {
		return Item{}, false
	}
	return *it, true
}

// Count returns the number of items.
func (l *Library) Count() int {
	l.mu.RLock()
	defer l.mu.RUnlock()
	return len(l.items)
}

// ---- paths ----

// OriginalPath is the path of the original file.
func (l *Library) OriginalPath(name string) string { return filepath.Join(l.opts.MediaDir, name) }

func (l *Library) thumbPath(stem string) string { return filepath.Join(l.opts.ThumbDir, stem+".jpg") }
func (l *Library) bgPath(stem string) string {
	return filepath.Join(l.opts.CacheDir, "bg", stem+".jpg")
}
func (l *Library) posterPath(stem string) string {
	return filepath.Join(l.opts.CacheDir, "poster", stem+".jpg")
}
func (l *Library) videoPath(stem string) string {
	return filepath.Join(l.opts.CacheDir, "video", stem+".mp4")
}
func (l *Library) renditionPath(stem string, limit int) string {
	return filepath.Join(l.opts.CacheDir, "display", fmt.Sprintf("%s.r%d.jpg", stem, limit))
}

// SafeName validates a client supplied file name.
func SafeName(name string) (string, bool) {
	if name == "" || name != filepath.Base(name) || strings.ContainsAny(name, `/\`) || strings.HasPrefix(name, ".") {
		return "", false
	}
	return name, true
}

// ---- scanning ----

// Scan discovers media at startup: renames files to UUIDs (as the original
// app did), loads cached metadata, removes orphaned thumbnails and queues
// any missing derived assets.
func (l *Library) Scan() error {
	start := time.Now()
	recs := l.loadRecords()
	entries, err := os.ReadDir(l.opts.MediaDir)
	if err != nil {
		return err
	}
	stems := map[string]bool{}
	var queue []string
	for _, e := range entries {
		if e.IsDir() || strings.HasPrefix(e.Name(), ".") {
			continue
		}
		name := e.Name()
		if _, ok := KindOf(name); !ok {
			continue
		}
		if !uuidRe.MatchString(strings.TrimSuffix(name, filepath.Ext(name))) {
			if renamed, err := l.renameToUUID(name); err == nil {
				name = renamed
			} else {
				log.Printf("media: could not rename %s: %v", name, err)
			}
		}
		it, needsWork := l.loadItem(name, recs[name])
		if it == nil {
			continue
		}
		stems[it.Stem()] = true
		l.mu.Lock()
		l.items[name] = it
		l.mu.Unlock()
		if needsWork {
			queue = append(queue, name)
		}
	}
	l.cleanOrphans(stems)
	l.scheduleSave()
	for _, n := range queue {
		l.enqueue(n)
	}
	log.Printf("media: %d items scanned in %s (%d queued for processing)", len(stems), time.Since(start).Round(time.Millisecond), len(queue))
	return nil
}

func (l *Library) renameToUUID(name string) (string, error) {
	ext := strings.ToLower(filepath.Ext(name))
	for i := 0; i < 5; i++ {
		n := NewUUID() + ext
		dst := l.OriginalPath(n)
		if _, err := os.Stat(dst); err == nil {
			continue
		}
		if err := os.Rename(l.OriginalPath(name), dst); err != nil {
			return "", err
		}
		log.Printf("media: renamed %s -> %s", name, n)
		return n, nil
	}
	return "", errors.New("could not allocate a unique name")
}

// loadItem builds an Item from disk, reusing the cached record when the file
// is unchanged. It reports whether background work is needed.
func (l *Library) loadItem(name string, rec *record) (*Item, bool) {
	st, err := os.Stat(l.OriginalPath(name))
	if err != nil {
		return nil, false
	}
	kind, _ := KindOf(name)
	mtime := st.ModTime().UnixMilli()
	var r record
	if rec != nil && rec.Size == st.Size() && rec.MTime == mtime && rec.Kind == kind {
		r = *rec
	} else {
		r = record{Size: st.Size(), MTime: mtime, Kind: kind}
		switch kind {
		case KindImage:
			info, err := imaging.ReadInfo(l.OriginalPath(name))
			if err != nil {
				log.Printf("media: skipping unreadable image %s: %v", name, err)
				return nil, false
			}
			r.W, r.H, r.Exif, r.Format = info.Width, info.Height, info.Orientation, info.Format
		case KindGIF:
			if info, err := imaging.ReadInfo(l.OriginalPath(name)); err == nil {
				r.W, r.H = info.Width, info.Height
			}
			_, r.Duration, _ = imaging.GIFInfo(l.OriginalPath(name))
		}
	}
	it := &Item{Name: name, Kind: kind, Size: r.Size, Added: r.MTime, rec: r}
	l.refreshDerived(it)
	return it, it.Status != "ready" || l.needsPrep(it)
}

// refreshDerived recomputes the client visible fields from the record.
func (l *Library) refreshDerived(it *Item) {
	r := it.rec
	it.Width, it.Height, it.Duration, it.Title = r.W, r.H, r.Duration, r.Title
	it.Orientation = "landscape"
	if r.H > r.W {
		it.Orientation = "portrait"
	}
	it.Version = r.MTime
	it.HasThumb = fileExists(l.thumbPath(it.Stem()))
	it.Playable, it.Optimized = true, false
	it.Status, it.Error = "ready", ""
	switch it.Kind {
	case KindVideo:
		if r.Bad {
			it.Status, it.Error, it.Playable = "error", "this file can't be read as a video", false
			return
		}
		if fileExists(l.videoPath(it.Stem())) {
			it.Optimized = true
			if st, err := os.Stat(l.videoPath(it.Stem())); err == nil {
				it.Version = st.ModTime().UnixMilli()
			}
		} else if l.ff.Available() && !r.Probed {
			it.Status = "processing"
		} else if need, playable := l.videoNeedsTranscode(it); need && r.Transcode == "" {
			it.Status = "processing"
			it.Playable = playable
		} else if r.Transcode == "failed" {
			it.Error = "could not optimise this video for playback"
		}
	}
	if !it.HasThumb && !r.NoThumb && it.Status == "ready" && (it.Kind != KindVideo || l.ff.Available()) {
		it.Status = "processing"
	}
}

func (l *Library) needsPrep(it *Item) bool {
	if it.rec.NoThumb {
		return false
	}
	if !it.HasThumb || it.rec.ThumbV < thumbVersion {
		return true
	}
	return !fileExists(l.bgPath(it.Stem()))
}

// videoNeedsTranscode decides whether a browser/hardware friendly copy is
// needed (H.264 4:2:0 in MP4, no larger than the screen) and whether the
// original is likely to play in the meantime.
func (l *Library) videoNeedsTranscode(it *Item) (needs, playableMeanwhile bool) {
	r := it.rec
	ext := strings.ToLower(filepath.Ext(it.Name))
	playableMeanwhile = ext != ".avi" && (r.Codec == "" || r.Codec == "h264" || r.Codec == "vp8" || r.Codec == "vp9" || r.Codec == "av1")
	if !l.opts.Transcode() || !l.ff.Available() || !r.Probed {
		return false, true
	}
	codecOK := r.Codec == "h264" && (r.PixFmt == "yuv420p" || r.PixFmt == "yuvj420p")
	containerOK := ext == ".mp4" || ext == ".m4v" || ext == ".mov"
	sw, sh := l.Screen()
	tooBig := max(r.W, r.H) > max(sw, sh)*6/5 || min(r.W, r.H) > min(sw, sh)*6/5
	return !(codecOK && containerOK) || tooBig, playableMeanwhile
}

func (l *Library) cleanOrphans(stems map[string]bool) {
	clean := func(dir string, stemOf func(string) string) {
		entries, err := os.ReadDir(dir)
		if err != nil {
			return
		}
		for _, e := range entries {
			if e.IsDir() {
				continue
			}
			if !stems[stemOf(e.Name())] {
				_ = os.Remove(filepath.Join(dir, e.Name()))
			}
		}
	}
	plain := func(n string) string { return strings.TrimSuffix(n, filepath.Ext(n)) }
	clean(l.opts.ThumbDir, plain)
	clean(filepath.Join(l.opts.CacheDir, "bg"), plain)
	clean(filepath.Join(l.opts.CacheDir, "poster"), plain)
	clean(filepath.Join(l.opts.CacheDir, "video"), plain)
	clean(filepath.Join(l.opts.CacheDir, "display"), func(n string) string {
		n = plain(n)
		if i := strings.LastIndex(n, ".r"); i > 0 {
			n = n[:i]
		}
		return n
	})
}

// Watch rescans the media folder periodically so files copied in by other
// means (network share, scp) are picked up without a restart.
func (l *Library) Watch(interval time.Duration) {
	t := time.NewTicker(interval)
	defer t.Stop()
	for {
		select {
		case <-l.ctx.Done():
			return
		case <-t.C:
			l.watchTick()
		}
	}
}

func (l *Library) watchTick() {
	entries, err := os.ReadDir(l.opts.MediaDir)
	if err != nil {
		return
	}
	seen := map[string]bool{}
	for _, e := range entries {
		name := e.Name()
		if e.IsDir() || strings.HasPrefix(name, ".") || strings.HasSuffix(name, ".tmp") {
			continue
		}
		if _, ok := KindOf(name); !ok {
			continue
		}
		seen[name] = true
		l.mu.RLock()
		_, known := l.items[name]
		l.mu.RUnlock()
		if known {
			continue
		}
		info, err := e.Info()
		if err != nil {
			continue
		}
		// Only import once the size is stable (copy finished).
		l.mu.Lock()
		prev, ok := l.pending[name]
		l.pending[name] = info.Size()
		l.mu.Unlock()
		if !ok || prev != info.Size() || time.Since(info.ModTime()) < 5*time.Second {
			continue
		}
		l.mu.Lock()
		delete(l.pending, name)
		l.mu.Unlock()
		if !uuidRe.MatchString(strings.TrimSuffix(name, filepath.Ext(name))) {
			renamed, err := l.renameToUUID(name)
			if err != nil {
				continue
			}
			seen[renamed] = true
			name = renamed
		}
		if it, _ := l.loadItem(name, nil); it != nil {
			l.mu.Lock()
			l.items[name] = it
			l.mu.Unlock()
			l.scheduleSave()
			l.emit("add", *it)
			l.enqueue(name)
		}
	}
	l.mu.RLock()
	var gone []string
	for name := range l.items {
		if !seen[name] {
			gone = append(gone, name)
		}
	}
	l.mu.RUnlock()
	for _, name := range gone {
		if !fileExists(l.OriginalPath(name)) {
			_ = l.Remove(name)
		}
	}
}

// ---- import ----

// ImportOptions tune Import.
type ImportOptions struct {
	// OriginalName is the client supplied file name (used for the extension).
	OriginalName string
	// ContentType is an optional MIME type hint.
	ContentType string
}

// ErrUnsupported is returned for files that are not media.
var ErrUnsupported = errors.New("unsupported file type")

// Import moves an uploaded temp file into the library. Images larger than the
// screen are downscaled (the original app's max_usful_size), WebP/BMP are
// converted to JPEG, and thumbnails are generated before returning.
func (l *Library) Import(tmp string, o ImportOptions) (Item, error) {
	defer os.Remove(tmp)
	ext := strings.ToLower(filepath.Ext(o.OriginalName))
	if ext == ".jpeg" {
		ext = ".jpg"
	}
	if _, ok := KindOf("x" + ext); !ok {
		ext = sniffExt(tmp, o.ContentType)
		if ext == "" {
			return Item{}, ErrUnsupported
		}
	}
	kind, _ := KindOf("x" + ext)
	name := NewUUID() + ext
	var decoded *imaging.Decoded
	if kind == KindImage {
		info, err := imaging.ReadInfo(tmp)
		if err != nil {
			return Item{}, fmt.Errorf("not a readable image: %w", err)
		}
		limit := l.Limit()
		convert := ext == ".webp" || ext == ".bmp"
		big := min(info.Width, info.Height) > limit || max(info.Width, info.Height) > 8192
		if convert || big {
			d, err := imaging.DecodeFile(tmp)
			if err != nil {
				return Item{}, err
			}
			w, h := d.Size()
			nw, nh := imaging.MinSideSize(w, h, limit, 8192)
			img := d.ScaleTo(nw, nh)
			var data []byte
			if ext == ".png" {
				data, err = imaging.EncodePNG(img)
			} else {
				ext = ".jpg"
				name = strings.TrimSuffix(name, filepath.Ext(name)) + ext
				data, err = imaging.EncodeJPEG(imaging.Flatten(img), 90)
			}
			if err != nil {
				return Item{}, err
			}
			if err := os.WriteFile(l.OriginalPath(name), data, 0o644); err != nil {
				return Item{}, err
			}
			decoded = &imaging.Decoded{Img: img, Format: strings.TrimPrefix(ext, "."), Orientation: 1}
		}
	}
	if decoded == nil {
		if err := moveFile(tmp, l.OriginalPath(name)); err != nil {
			return Item{}, err
		}
	}
	it, _ := l.loadItem(name, nil)
	if it == nil {
		_ = os.Remove(l.OriginalPath(name))
		return Item{}, fmt.Errorf("could not read imported file")
	}
	it.rec.Title = cleanTitle(o.OriginalName)
	it.Title = it.rec.Title
	l.mu.Lock()
	l.items[name] = it
	l.mu.Unlock()
	if kind == KindVideo {
		l.emit("add", *it)
		l.enqueue(name)
	} else {
		// Generate thumbnail and backdrop now so the gallery updates at once.
		if err := l.prepareImage(name, decoded); err != nil {
			log.Printf("media: preparing %s: %v", name, err)
		}
		l.mu.RLock()
		cp := *l.items[name]
		l.mu.RUnlock()
		l.emit("add", cp)
	}
	l.scheduleSave()
	return l.mustGet(name), nil
}

func (l *Library) mustGet(name string) Item {
	it, _ := l.Get(name)
	return it
}

// cleanTitle turns an uploaded file name into a display title.
func cleanTitle(name string) string {
	name = filepath.Base(strings.ReplaceAll(name, "\\", "/"))
	name = strings.TrimSuffix(name, filepath.Ext(name))
	if strings.HasSuffix(strings.ToLower(name), ".jpg") || strings.HasSuffix(strings.ToLower(name), ".png") {
		name = strings.TrimSuffix(name, filepath.Ext(name)) // "photo.jpg.webp"
	}
	if name == "." || name == "/" || uuidRe.MatchString(name) {
		return ""
	}
	if len(name) > 120 {
		name = name[:120]
	}
	return strings.TrimSpace(name)
}

func sniffExt(path, contentType string) string {
	f, err := os.Open(path)
	if err != nil {
		return ""
	}
	defer f.Close()
	buf := make([]byte, 512)
	n, _ := io.ReadFull(f, buf)
	ct := http.DetectContentType(buf[:n])
	if ct == "application/octet-stream" && contentType != "" {
		ct = contentType
	}
	switch {
	case strings.HasPrefix(ct, "image/jpeg"):
		return ".jpg"
	case strings.HasPrefix(ct, "image/png"):
		return ".png"
	case strings.HasPrefix(ct, "image/gif"):
		return ".gif"
	case strings.HasPrefix(ct, "image/webp"):
		return ".webp"
	case strings.HasPrefix(ct, "image/bmp"):
		return ".bmp"
	case strings.HasPrefix(ct, "video/mp4"), strings.HasPrefix(ct, "video/quicktime"):
		return ".mp4"
	case strings.HasPrefix(ct, "video/webm"):
		return ".webm"
	case strings.HasPrefix(ct, "video/avi"), strings.HasPrefix(ct, "video/x-msvideo"):
		return ".avi"
	}
	if n >= 12 && string(buf[4:8]) == "ftyp" {
		return ".mp4"
	}
	return ""
}

func moveFile(src, dst string) error {
	if err := os.Rename(src, dst); err == nil {
		return nil
	}
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		out.Close()
		os.Remove(dst)
		return err
	}
	return out.Close()
}

// Remove deletes a media file and everything derived from it.
func (l *Library) Remove(name string) error {
	l.mu.Lock()
	it, ok := l.items[name]
	if ok {
		delete(l.items, name)
	}
	l.mu.Unlock()
	if !ok {
		return os.ErrNotExist
	}
	stem := it.Stem()
	var firstErr error
	if err := os.Remove(l.OriginalPath(name)); err != nil && !os.IsNotExist(err) {
		firstErr = err
	}
	for _, p := range []string{l.thumbPath(stem), l.bgPath(stem), l.posterPath(stem), l.videoPath(stem)} {
		_ = os.Remove(p)
	}
	if matches, _ := filepath.Glob(filepath.Join(l.opts.CacheDir, "display", stem+".r*.jpg")); matches != nil {
		for _, m := range matches {
			_ = os.Remove(m)
		}
	}
	l.scheduleSave()
	l.emit("remove", *it)
	return firstErr
}

// ---- derived assets ----

// ThumbPath returns the thumbnail path, generating it if necessary.
func (l *Library) ThumbPath(name string) (string, error) {
	it, ok := l.Get(name)
	if !ok {
		return "", os.ErrNotExist
	}
	p := l.thumbPath(it.Stem())
	if fileExists(p) {
		return p, nil
	}
	if err := l.prepare(name); err != nil {
		return "", err
	}
	if fileExists(p) {
		return p, nil
	}
	return "", os.ErrNotExist
}

// BackgroundPath returns the blurred backdrop, generating it if necessary.
func (l *Library) BackgroundPath(name string) (string, error) {
	it, ok := l.Get(name)
	if !ok {
		return "", os.ErrNotExist
	}
	p := l.bgPath(it.Stem())
	if fileExists(p) {
		return p, nil
	}
	if err := l.prepare(name); err != nil {
		return "", err
	}
	if fileExists(p) {
		return p, nil
	}
	return "", os.ErrNotExist
}

// DisplayPath returns the file the display should load: a screen sized
// rendition for large images, the optimised copy for videos, or the original.
func (l *Library) DisplayPath(name string) (string, error) {
	it, ok := l.Get(name)
	if !ok {
		return "", os.ErrNotExist
	}
	switch it.Kind {
	case KindVideo:
		if p := l.videoPath(it.Stem()); fileExists(p) {
			return p, nil
		}
		return l.OriginalPath(name), nil
	case KindImage:
		limit := l.Limit()
		if !l.needsRendition(it, limit) {
			return l.OriginalPath(name), nil
		}
		p := l.renditionPath(it.Stem(), limit)
		if fileExists(p) {
			return p, nil
		}
		err := l.do("r:"+p, func() error {
			if fileExists(p) {
				return nil
			}
			d, err := imaging.DecodeFile(l.OriginalPath(name))
			if err != nil {
				return err
			}
			w, h := d.Size()
			nw, nh := imaging.MinSideSize(w, h, limit, 4096)
			return imaging.SaveJPEG(p, imaging.Flatten(d.ScaleTo(nw, nh)), 88)
		})
		if err != nil {
			log.Printf("media: rendition for %s failed: %v", name, err)
			return l.OriginalPath(name), nil
		}
		return p, nil
	}
	return l.OriginalPath(name), nil
}

// PosterPath returns a representative still for videos (and the display file
// for images); used by /canvas.
func (l *Library) PosterPath(name string) (string, error) {
	it, ok := l.Get(name)
	if !ok {
		return "", os.ErrNotExist
	}
	if it.Kind == KindVideo {
		p := l.posterPath(it.Stem())
		if !fileExists(p) {
			_ = l.prepare(name)
		}
		if fileExists(p) {
			return p, nil
		}
		return "", os.ErrNotExist
	}
	return l.DisplayPath(name)
}

func (l *Library) needsRendition(it Item, limit int) bool {
	r := it.rec
	return min(r.W, r.H) > limit || max(r.W, r.H) > 4096 || r.Format == "bmp"
}

// Prefetch prepares an item's assets in the background (used to warm up the
// next slide while the current one is showing).
func (l *Library) Prefetch(name string) {
	go func() {
		_ = l.prepare(name)
		_, _ = l.DisplayPath(name)
	}()
}

func (l *Library) enqueue(name string) {
	select {
	case l.prepQ <- name:
	default:
		go func() { _ = l.prepare(name) }()
	}
}

func (l *Library) prepWorker() {
	for {
		select {
		case <-l.ctx.Done():
			return
		case name := <-l.prepQ:
			if err := l.prepare(name); err != nil && !os.IsNotExist(err) {
				log.Printf("media: preparing %s: %v", name, err)
			}
		}
	}
}

func (l *Library) do(key string, fn func() error) error {
	l.fmu.Lock()
	if c, ok := l.flight[key]; ok {
		l.fmu.Unlock()
		<-c.done
		return c.err
	}
	c := &call{done: make(chan struct{})}
	l.flight[key] = c
	l.fmu.Unlock()
	defer func() {
		if r := recover(); r != nil {
			c.err = fmt.Errorf("panic: %v", r)
		}
		l.fmu.Lock()
		delete(l.flight, key)
		l.fmu.Unlock()
		close(c.done)
	}()
	c.err = fn()
	return c.err
}

// prepare makes sure an item's metadata, thumbnail and backdrop exist.
func (l *Library) prepare(name string) error {
	it, ok := l.Get(name)
	if !ok {
		return os.ErrNotExist
	}
	switch it.Kind {
	case KindVideo:
		return l.do("p:"+name, func() error { return l.prepareVideo(name) })
	default:
		return l.do("p:"+name, func() error { return l.prepareImage(name, nil) })
	}
}

// update applies fn to the stored item and emits an update event.
func (l *Library) update(name string, fn func(it *Item)) {
	l.mu.Lock()
	it, ok := l.items[name]
	if !ok {
		l.mu.Unlock()
		return
	}
	before := *it
	fn(it)
	l.refreshDerived(it)
	after := *it
	l.mu.Unlock()
	l.scheduleSave()
	if before != after {
		l.emit("update", after)
	}
}

func (l *Library) prepareImage(name string, d *imaging.Decoded) error {
	it, ok := l.Get(name)
	if !ok {
		return os.ErrNotExist
	}
	stem := it.Stem()
	needThumb := !fileExists(l.thumbPath(stem)) || it.rec.ThumbV < thumbVersion
	needBg := !fileExists(l.bgPath(stem))
	if !needThumb && !needBg {
		if it.Status != "ready" {
			l.update(name, func(it *Item) {})
		}
		return nil
	}
	if d == nil {
		var err error
		if d, err = imaging.DecodeFile(l.OriginalPath(name)); err != nil {
			l.update(name, func(it *Item) { it.rec.NoThumb = true })
			return err
		}
	}
	w, h := d.Size()
	tw, th := imaging.MinSideSize(w, h, thumbMinSide, thumbMinSide*3)
	thumb := imaging.Flatten(d.ScaleTo(tw, th))
	if needThumb {
		if err := imaging.SaveJPEG(l.thumbPath(stem), thumb, 82); err != nil {
			return err
		}
	}
	if needBg {
		if err := imaging.SaveJPEG(l.bgPath(stem), imaging.Background(thumb, bgLongSide), 90); err != nil {
			return err
		}
	}
	l.update(name, func(it *Item) { it.rec.ThumbV = thumbVersion; it.rec.NoThumb = false })
	return nil
}

func (l *Library) prepareVideo(name string) error {
	it, ok := l.Get(name)
	if !ok {
		return os.ErrNotExist
	}
	if !l.ff.Available() {
		l.update(name, func(it *Item) { it.rec.NoThumb = true })
		return nil
	}
	src := l.OriginalPath(name)
	if !it.rec.Probed {
		pr, err := l.ff.Probe(l.ctx, src)
		if err != nil {
			// ffprobe cannot read it, so no browser will either: keep it out
			// of the rotation and flag it in the UI instead of retrying.
			log.Printf("media: %s is not a readable video: %v", name, err)
			l.update(name, func(it *Item) { it.rec.Probed, it.rec.Bad, it.rec.NoThumb = true, true, true })
			return nil
		}
		l.update(name, func(it *Item) {
			it.rec.Probed = true
			it.rec.W, it.rec.H, it.rec.Duration = pr.Width, pr.Height, pr.Duration
			it.rec.Codec, it.rec.PixFmt, it.rec.Format = pr.Codec, pr.PixFmt, pr.Format
		})
		it, _ = l.Get(name)
	}
	stem := it.Stem()
	if err := l.videoStills(it, src); err != nil {
		log.Printf("media: no thumbnail for %s: %v", name, err)
		l.update(name, func(it *Item) { it.rec.NoThumb = true })
	} else {
		l.update(name, func(it *Item) { it.rec.ThumbV = thumbVersion; it.rec.NoThumb = false })
	}
	it, _ = l.Get(name)
	if need, _ := l.videoNeedsTranscode(&it); need && it.rec.Transcode == "" && !fileExists(l.videoPath(stem)) {
		select {
		case l.transQ <- name:
		default:
		}
	}
	return nil
}

// videoStills extracts a poster frame and derives the thumbnail and backdrop.
func (l *Library) videoStills(it Item, src string) error {
	stem := it.Stem()
	poster := l.posterPath(stem)
	if !fileExists(poster) {
		pw, ph := 0, 0
		if it.rec.W > 0 && it.rec.H > 0 {
			pw, ph = imaging.FitSize(it.rec.W, it.rec.H, 1280, 1280)
		}
		if err := l.ff.Frame(l.ctx, src, poster, it.rec.Duration*0.1, pw, ph); err != nil {
			return fmt.Errorf("extracting frame: %w", err)
		}
	}
	if fileExists(l.thumbPath(stem)) && it.rec.ThumbV >= thumbVersion && fileExists(l.bgPath(stem)) {
		return nil
	}
	d, err := imaging.DecodeFile(poster)
	if err != nil {
		return err
	}
	w, h := d.Size()
	tw, th := imaging.MinSideSize(w, h, thumbMinSide, thumbMinSide*3)
	thumb := d.ScaleTo(tw, th)
	if err := imaging.SaveJPEG(l.thumbPath(stem), thumb, 82); err != nil {
		return err
	}
	return imaging.SaveJPEG(l.bgPath(stem), imaging.Background(thumb, bgLongSide), 90)
}

func (l *Library) transcodeWorker() {
	for {
		select {
		case <-l.ctx.Done():
			return
		case name := <-l.transQ:
			it, ok := l.Get(name)
			if !ok || fileExists(l.videoPath(it.Stem())) {
				continue
			}
			sw, sh := l.Screen()
			long, short := max(sw, sh), min(sw, sh)
			bw, bh := long, short
			if it.rec.H > it.rec.W {
				bw, bh = short, long
			}
			w, h := it.rec.W, it.rec.H
			if w == 0 || h == 0 {
				w, h = bw, bh
			}
			w, h = imaging.FitSize(w, h, bw, bh)
			log.Printf("media: optimising %s (%s %dx%d) for playback", name, it.rec.Codec, it.rec.W, it.rec.H)
			err := l.ff.Transcode(l.ctx, l.OriginalPath(name), l.videoPath(it.Stem()), w, h)
			if l.ctx.Err() != nil {
				return
			}
			l.update(name, func(it *Item) {
				if err != nil {
					it.rec.Transcode = "failed"
				} else {
					it.rec.Transcode = "done"
				}
			})
			if err != nil {
				log.Printf("media: optimising %s failed: %v", name, err)
			}
		}
	}
}

// RequeueVideos re-evaluates whether videos need transcoding (after the
// screen size or the transcode setting changes).
func (l *Library) RequeueVideos() {
	for _, it := range l.Items() {
		if it.Kind == KindVideo {
			l.update(it.Name, func(*Item) {})
			cp := it
			if need, _ := l.videoNeedsTranscode(&cp); need && it.rec.Transcode == "" {
				l.enqueue(it.Name)
			}
		}
	}
}

// ---- persistence ----

func (l *Library) recordsPath() string { return filepath.Join(l.opts.CacheDir, "library.json") }

func (l *Library) loadRecords() map[string]*record {
	out := map[string]*record{}
	data, err := os.ReadFile(l.recordsPath())
	if err != nil {
		return out
	}
	var doc struct {
		Version int                `json:"version"`
		Items   map[string]*record `json:"items"`
	}
	if json.Unmarshal(data, &doc) == nil && doc.Items != nil {
		out = doc.Items
	}
	return out
}

func (l *Library) scheduleSave() {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.saveT != nil {
		l.saveT.Stop()
	}
	l.saveT = time.AfterFunc(2*time.Second, l.saveNow)
}

func (l *Library) saveNow() {
	l.mu.RLock()
	doc := struct {
		Version int                `json:"version"`
		Items   map[string]*record `json:"items"`
	}{Version: 1, Items: make(map[string]*record, len(l.items))}
	for n, it := range l.items {
		r := it.rec
		doc.Items[n] = &r
	}
	l.mu.RUnlock()
	data, err := json.Marshal(doc)
	if err != nil {
		return
	}
	tmp := l.recordsPath() + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err == nil {
		_ = os.Rename(tmp, l.recordsPath())
	}
}

// ---- helpers ----

// NewUUID returns a random RFC 4122 version 4 UUID.
func NewUUID() string {
	var b [16]byte
	_, _ = rand.Read(b[:])
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:])
}

func fileExists(p string) bool {
	st, err := os.Stat(p)
	return err == nil && !st.IsDir()
}

// DecodeStill decodes a still image file for /canvas.
func DecodeStill(path string) (*imaging.Decoded, error) { return imaging.DecodeFile(path) }

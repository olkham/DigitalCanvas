// Package player is the slideshow state machine. It decides what is on the
// canvas and when to advance; displays merely render the slides it emits.
package player

import (
	"log"
	"math/rand"
	"net/url"
	"sync"
	"time"

	"github.com/olkham/DigitalCanvas/internal/media"
)

// Library is the subset of the media library the player needs.
type Library interface {
	Items() []media.Item
	Get(name string) (media.Item, bool)
	Prefetch(name string)
}

// Settings are the slideshow parameters, read on every decision.
type Settings struct {
	FrameInterval float64 // seconds an item is held after its transition
	Transition    float64 // crossfade seconds
	Filter        string  // portrait | landscape | both
	Order         string  // sequential | random
}

// Pause reasons. A pause is only lifted automatically by the same reason
// that caused it, so e.g. Plex stopping never resumes a user-paused show.
const (
	ByUser     = "user"
	BySchedule = "schedule"
	ByPlex     = "plex"
)

// Slide is what a display renders.
type Slide struct {
	Seq        int64    `json:"seq"`
	Name       string   `json:"name"`
	Title      string   `json:"title"`
	Kind       string   `json:"kind"` // image | video | gif | idle
	Src        string   `json:"src,omitempty"`
	Bg         string   `json:"bg,omitempty"`
	Thumb      string   `json:"thumb,omitempty"`
	Width      int      `json:"width,omitempty"`
	Height     int      `json:"height,omitempty"`
	Duration   float64  `json:"duration,omitempty"`
	Transient  bool     `json:"transient,omitempty"`
	Source     string   `json:"source"` // library | display_now | plex | idle
	Transition float64  `json:"transition"`
	URLs       []string `json:"urls,omitempty"` // idle screen: where to open the control panel

	shownAt time.Time
}

// Preload hints displays to warm their cache for the next slide.
type Preload struct {
	Kind string `json:"kind"`
	Src  string `json:"src"`
	Bg   string `json:"bg"`
}

// Status describes playback for UIs.
type Status struct {
	Active      bool   `json:"active"`
	PausedBy    string `json:"paused_by,omitempty"`
	Seq         int64  `json:"seq"`
	RemainingMs int64  `json:"remaining_ms"` // -1 when not counting down
	TotalMs     int64  `json:"total_ms"`
	UntilEnd    bool   `json:"until_end,omitempty"` // advancing when the video ends
	Position    int    `json:"position"`            // 1-based position in the queue, 0 if none
	Count       int    `json:"count"`
	Order       string `json:"order"`
}

type event struct {
	name string
	data any
}

// Player is safe for concurrent use.
type Player struct {
	lib      Library
	settings func() Settings
	emit     func(name string, data any)
	idle     func() Slide

	mu          sync.Mutex
	queue       []string
	pos         int
	cur         *Slide
	active      bool
	pausedBy    string
	holdFrom    time.Time
	deadline    time.Time
	timer       *time.Timer
	gen         uint64
	seq         int64
	errStreak   int
	lastShuffle []string
	rng         *rand.Rand
}

// New creates a player. emit is called outside the player's lock; idle builds
// the slide shown when there is nothing to play.
func New(lib Library, settings func() Settings, emit func(string, any), idle func() Slide) *Player {
	return &Player{
		lib: lib, settings: settings, emit: emit, idle: idle,
		pos: -1, active: true,
		rng: rand.New(rand.NewSource(time.Now().UnixNano())),
	}
}

func (p *Player) flush(evs []event) {
	for _, e := range evs {
		p.emit(e.name, e.data)
	}
}

// Start shows the first item and starts the timer.
func (p *Player) Start() {
	p.mu.Lock()
	p.rebuildLocked(true)
	var evs []event
	if len(p.queue) > 0 {
		p.pos = 0
		evs = p.showItemLocked(p.queue[0], p.settings().Transition)
	} else {
		evs = p.showIdleLocked()
	}
	p.mu.Unlock()
	p.flush(evs)
}

// Current returns the slide on screen.
func (p *Player) Current() (Slide, bool) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.cur == nil {
		return Slide{}, false
	}
	return *p.cur, true
}

// Active reports whether the slideshow is advancing.
func (p *Player) Active() bool {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.active
}

// Status returns the playback status.
func (p *Player) Status() Status {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.statusLocked()
}

// Next advances to the next item.
func (p *Player) Next() { p.step(1) }

// Previous goes back one item.
func (p *Player) Previous() { p.step(-1) }

func (p *Player) step(dir int) {
	p.mu.Lock()
	p.errStreak = 0
	evs := p.stepLocked(dir)
	p.mu.Unlock()
	p.flush(evs)
}

// Select shows a specific library item.
func (p *Player) Select(name string) bool {
	p.mu.Lock()
	if _, ok := p.lib.Get(name); !ok {
		p.mu.Unlock()
		return false
	}
	if i := indexOf(p.queue, name); i >= 0 {
		p.pos = i
	}
	p.errStreak = 0
	evs := p.showItemLocked(name, p.settings().Transition)
	p.mu.Unlock()
	p.flush(evs)
	return true
}

// ShowTransient shows an image that is not part of the library. If the show
// is active it continues with the next library item afterwards.
func (p *Player) ShowTransient(t *media.Transient) {
	s := &Slide{
		Name: t.ID, Title: t.Title, Kind: "image", Transient: true, Source: t.Source,
		Src: "/transient/" + t.ID, Bg: "/transient/" + t.ID + "/bg",
		Thumb: "/transient/" + t.ID, Width: t.Width, Height: t.Height,
	}
	p.mu.Lock()
	evs := p.showLocked(s, p.settings().Transition)
	p.mu.Unlock()
	p.flush(evs)
}

// Pause stops advancing.
func (p *Player) Pause(reason string) {
	p.mu.Lock()
	if !p.active {
		if reason == ByUser {
			p.pausedBy = ByUser // an explicit pause takes ownership
		}
		p.mu.Unlock()
		return
	}
	p.active = false
	p.pausedBy = reason
	p.stopTimerLocked()
	st := p.statusLocked()
	p.mu.Unlock()
	p.emit("playback", st)
}

// Resume restarts advancing. Automatic reasons only undo their own pause.
func (p *Player) Resume(reason string) {
	p.mu.Lock()
	if p.active || (reason != ByUser && p.pausedBy != reason) {
		p.mu.Unlock()
		return
	}
	p.active = true
	p.pausedBy = ""
	var evs []event
	if p.cur == nil || p.cur.Kind == "idle" {
		p.rebuildLocked(false)
		if len(p.queue) > 0 {
			evs = p.stepLocked(1)
		}
	} else {
		p.holdFrom = time.Now() // hold for a full interval from now, as before
		p.scheduleLocked()
	}
	evs = append(evs, event{"playback", p.statusLocked()})
	p.mu.Unlock()
	p.flush(evs)
}

// Toggle flips between paused and playing.
func (p *Player) Toggle() {
	if p.Active() {
		p.Pause(ByUser)
	} else {
		p.Resume(ByUser)
	}
}

// Retime re-applies interval/transition changes to the running timer.
func (p *Player) Retime() {
	p.mu.Lock()
	p.scheduleLocked()
	st := p.statusLocked()
	p.mu.Unlock()
	p.emit("playback", st)
}

// Rebuild refreshes the queue after library, filter or order changes.
// reshuffle forces a new random order.
func (p *Player) Rebuild(reshuffle bool) {
	p.mu.Lock()
	p.rebuildLocked(reshuffle)
	var evs []event
	switch {
	case p.cur == nil || p.cur.Kind == "idle":
		if len(p.queue) > 0 {
			p.pos = 0
			evs = p.showItemLocked(p.queue[0], p.settings().Transition)
		} else if p.cur == nil {
			evs = p.showIdleLocked()
		}
	case !p.cur.Transient:
		if _, ok := p.lib.Get(p.cur.Name); !ok { // current item was deleted
			if len(p.queue) > 0 {
				evs = p.stepLocked(1)
			} else if len(p.lib.Items()) == 0 {
				evs = p.showIdleLocked()
			}
		}
	}
	evs = append(evs, event{"playback", p.statusLocked()})
	p.mu.Unlock()
	p.flush(evs)
}

// RefreshIdle re-emits the idle slide (e.g. after the device name changes).
func (p *Player) RefreshIdle() {
	p.mu.Lock()
	var evs []event
	if p.cur != nil && p.cur.Kind == "idle" {
		evs = p.showIdleLocked()
	}
	p.mu.Unlock()
	p.flush(evs)
}

// Ended is reported by a display when a video finished playing.
func (p *Player) Ended(seq int64) {
	p.mu.Lock()
	if p.cur == nil || seq != p.cur.Seq || p.cur.Kind != "video" || !p.active {
		p.mu.Unlock()
		return
	}
	p.errStreak = 0
	evs := p.stepLocked(1)
	p.mu.Unlock()
	p.flush(evs)
}

// Ready is reported by a display once a slide rendered successfully.
func (p *Player) Ready(seq int64) {
	p.mu.Lock()
	if p.cur != nil && seq == p.cur.Seq {
		p.errStreak = 0
	}
	p.mu.Unlock()
}

// Failed is reported by a display when a slide could not be rendered; the
// player skips ahead, giving up once every queued item has failed in a row.
func (p *Player) Failed(seq int64) {
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.cur == nil || seq != p.cur.Seq || !p.active {
		return
	}
	p.errStreak++
	log.Printf("player: display could not show %s (%d in a row)", p.cur.Name, p.errStreak)
	if p.errStreak > max(1, len(p.queue)) {
		return
	}
	p.stopTimerLocked()
	gen := p.gen
	p.timer = time.AfterFunc(1500*time.Millisecond, func() {
		p.mu.Lock()
		if gen != p.gen || !p.active {
			p.mu.Unlock()
			return
		}
		evs := p.stepLocked(1)
		p.mu.Unlock()
		p.flush(evs)
	})
}

// ---- internals (p.mu held) ----

func (p *Player) playlistLocked() []string {
	s := p.settings()
	var out []string
	for _, it := range p.lib.Items() {
		if !it.Playable {
			continue
		}
		if s.Filter == "portrait" || s.Filter == "landscape" {
			if it.Orientation != s.Filter {
				continue
			}
		}
		out = append(out, it.Name)
	}
	return out
}

func (p *Player) rebuildLocked(reshuffle bool) {
	list := p.playlistLocked()
	anchor := ""
	if p.pos >= 0 && p.pos < len(p.queue) {
		anchor = p.queue[p.pos]
	}
	if p.settings().Order == "random" {
		if !reshuffle && sameSet(p.lastShuffle, list) {
			return
		}
		p.lastShuffle = append([]string(nil), list...)
		p.queue = p.shuffle(list, anchor)
		p.pos = indexOf(p.queue, anchor) // 0 when anchor kept, else -1
		return
	}
	p.lastShuffle = nil
	old := p.pos
	p.queue = list
	p.pos = indexOf(list, anchor)
	if p.pos < 0 {
		// The anchor vanished: next() should land on whatever took its slot.
		p.pos = min(old, len(list)) - 1
	}
}

// shuffle returns a random permutation; first (if present) is put up front.
func (p *Player) shuffle(list []string, first string) []string {
	q := append([]string(nil), list...)
	p.rng.Shuffle(len(q), func(i, j int) { q[i], q[j] = q[j], q[i] })
	if i := indexOf(q, first); i > 0 {
		q[0], q[i] = q[i], q[0]
	}
	return q
}

func (p *Player) stepLocked(dir int) []event {
	if len(p.queue) == 0 {
		p.rebuildLocked(false)
	}
	n := len(p.queue)
	if n == 0 {
		if len(p.lib.Items()) == 0 && (p.cur == nil || p.cur.Kind != "idle") {
			return p.showIdleLocked()
		}
		p.scheduleLocked()
		return nil
	}
	tr := p.settings().Transition
	// Going back from a one-off image returns to the item it interrupted.
	if dir < 0 && p.cur != nil && p.cur.Transient && p.pos >= 0 && p.pos < n {
		return p.showItemLocked(p.queue[p.pos], tr)
	}
	np := p.pos + dir
	if np >= n {
		np = 0
		if p.settings().Order == "random" && n > 1 {
			last := p.queue[n-1]
			p.queue = p.shuffle(p.queue, "")
			if p.queue[0] == last { // avoid showing the same item twice in a row
				p.queue[0], p.queue[n-1] = p.queue[n-1], p.queue[0]
			}
		}
	}
	if np < 0 {
		np = n - 1
	}
	p.pos = np
	return p.showItemLocked(p.queue[np], tr)
}

func (p *Player) showItemLocked(name string, transition float64) []event {
	it, ok := p.lib.Get(name)
	if !ok {
		return nil
	}
	return p.showLocked(SlideFor(it), transition)
}

// SlideFor builds the slide for a library item.
func SlideFor(it media.Item) *Slide {
	n := url.PathEscape(it.Name)
	v := "?v=" + itoa(it.Version)
	s := &Slide{
		Name: it.Name, Title: it.Name, Kind: string(it.Kind), Source: "library",
		Src: "/media/" + n + "/display" + v, Bg: "/media/" + n + "/bg" + v,
		Thumb: "/thumbnails/" + n + v, Width: it.Width, Height: it.Height, Duration: it.Duration,
	}
	return s
}

func (p *Player) showIdleLocked() []event {
	s := p.idle()
	s.Kind, s.Source = "idle", "idle"
	return p.showLocked(&s, 1)
}

func (p *Player) showLocked(s *Slide, transition float64) []event {
	p.seq++
	s.Seq = p.seq
	s.Transition = transition
	now := time.Now()
	s.shownAt = now
	p.cur = s
	p.holdFrom = now.Add(time.Duration(transition * float64(time.Second)))
	p.scheduleLocked()
	evs := []event{{"slide", *s}, {"playback", p.statusLocked()}}
	if next := p.peekLocked(); next != "" && next != s.Name {
		p.lib.Prefetch(next)
		if it, ok := p.lib.Get(next); ok {
			ns := SlideFor(it)
			evs = append(evs, event{"preload", Preload{Kind: ns.Kind, Src: ns.Src, Bg: ns.Bg}})
		}
	}
	return evs
}

func (p *Player) peekLocked() string {
	n := len(p.queue)
	if n == 0 {
		return ""
	}
	np := p.pos + 1
	if np >= n {
		if p.settings().Order == "random" {
			return "" // will be reshuffled; unknown yet
		}
		np = 0
	}
	if np < 0 {
		np = 0
	}
	return p.queue[np]
}

func (p *Player) holdLocked() time.Duration {
	s := p.settings()
	interval := time.Duration(s.FrameInterval * float64(time.Second))
	switch p.cur.Kind {
	case "gif":
		if d := time.Duration(p.cur.Duration * float64(time.Second)); d > interval {
			return d
		}
	case "video":
		// The display reports the end of the video; this is only a fallback
		// for when no display is connected.
		if p.cur.Duration > 0 {
			return time.Duration(p.cur.Duration*float64(time.Second)) + 5*time.Second
		}
		return max(interval, 10*time.Minute)
	}
	return interval
}

func (p *Player) stopTimerLocked() {
	p.gen++
	if p.timer != nil {
		p.timer.Stop()
		p.timer = nil
	}
	p.deadline = time.Time{}
}

func (p *Player) scheduleLocked() {
	p.stopTimerLocked()
	if !p.active || p.cur == nil || p.cur.Kind == "idle" {
		return
	}
	p.deadline = p.holdFrom.Add(p.holdLocked())
	d := time.Until(p.deadline)
	if d < 0 {
		d = 0
	}
	gen := p.gen
	p.timer = time.AfterFunc(d, func() {
		p.mu.Lock()
		if gen != p.gen || !p.active {
			p.mu.Unlock()
			return
		}
		evs := p.stepLocked(1)
		p.mu.Unlock()
		p.flush(evs)
	})
}

func (p *Player) statusLocked() Status {
	st := Status{Active: p.active, PausedBy: p.pausedBy, RemainingMs: -1, Count: len(p.queue), Order: p.settings().Order}
	if p.cur != nil {
		st.Seq = p.cur.Seq
		if !p.cur.Transient && p.cur.Kind != "idle" {
			if i := indexOf(p.queue, p.cur.Name); i >= 0 {
				st.Position = i + 1
			}
		}
	}
	if p.active && !p.deadline.IsZero() {
		end := p.deadline
		if p.cur.Kind == "video" && p.cur.Duration > 0 {
			end = p.holdFrom.Add(time.Duration(p.cur.Duration * float64(time.Second)))
			st.UntilEnd = true
		}
		st.RemainingMs = max(0, time.Until(end).Milliseconds())
		st.TotalMs = end.Sub(p.holdFrom).Milliseconds()
	}
	if p.cur != nil && p.cur.Kind == "video" {
		st.UntilEnd = true
	}
	return st
}

func indexOf(list []string, v string) int {
	if v == "" {
		return -1
	}
	for i, s := range list {
		if s == v {
			return i
		}
	}
	return -1
}

func sameSet(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	m := make(map[string]struct{}, len(a))
	for _, s := range a {
		m[s] = struct{}{}
	}
	for _, s := range b {
		if _, ok := m[s]; !ok {
			return false
		}
	}
	return true
}

func itoa(v int64) string {
	if v == 0 {
		return "0"
	}
	neg := v < 0
	if neg {
		v = -v
	}
	var b [20]byte
	i := len(b)
	for v > 0 {
		i--
		b[i] = byte('0' + v%10)
		v /= 10
	}
	if neg {
		i--
		b[i] = '-'
	}
	return string(b[i:])
}

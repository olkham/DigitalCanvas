package media

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"
)

// FFmpeg wraps the ffmpeg/ffprobe command line tools. It is optional: without
// it videos still play, but have no thumbnails, metadata or transcoding.
type FFmpeg struct {
	ffmpeg, ffprobe string

	encOnce  sync.Once
	encoders map[string]bool
}

// NewFFmpeg locates ffmpeg and ffprobe on PATH or next to the executable.
func NewFFmpeg() *FFmpeg {
	f := &FFmpeg{ffmpeg: findTool("ffmpeg"), ffprobe: findTool("ffprobe")}
	if f.Available() {
		log.Printf("media: using %s", f.ffmpeg)
	} else {
		log.Printf("media: ffmpeg/ffprobe not found - video thumbnails and transcoding disabled")
	}
	return f
}

func findTool(name string) string {
	if exe, err := os.Executable(); err == nil {
		cand := filepath.Join(filepath.Dir(exe), name)
		if runtime.GOOS == "windows" {
			cand += ".exe"
		}
		if st, err := os.Stat(cand); err == nil && !st.IsDir() {
			return cand
		}
	}
	if p, err := exec.LookPath(name); err == nil {
		return p
	}
	return ""
}

// Available reports whether both tools were found.
func (f *FFmpeg) Available() bool { return f != nil && f.ffmpeg != "" && f.ffprobe != "" }

func (f *FFmpeg) run(ctx context.Context, lowPriority bool, bin string, args ...string) ([]byte, error) {
	cmd := exec.CommandContext(ctx, bin, args...)
	configureCmd(cmd)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	if lowPriority {
		lowerPriority(cmd.Process.Pid)
	}
	if err := cmd.Wait(); err != nil {
		msg := strings.TrimSpace(stderr.String())
		if len(msg) > 400 {
			msg = msg[len(msg)-400:]
		}
		return stdout.Bytes(), fmt.Errorf("%s: %v: %s", filepath.Base(bin), err, msg)
	}
	return stdout.Bytes(), nil
}

// ProbeResult is the subset of ffprobe output we care about.
type ProbeResult struct {
	Width, Height int // display size (rotation applied)
	Duration      float64
	Codec         string
	PixFmt        string
	Format        string
	FPS           float64
}

// Probe reads stream metadata of a video file.
func (f *FFmpeg) Probe(ctx context.Context, path string) (ProbeResult, error) {
	if !f.Available() {
		return ProbeResult{}, errors.New("ffprobe not available")
	}
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	out, err := f.run(ctx, false, f.ffprobe, "-v", "error", "-print_format", "json",
		"-show_format", "-show_streams", "-select_streams", "v:0", path)
	if err != nil {
		return ProbeResult{}, err
	}
	var doc struct {
		Streams []struct {
			Codec        string            `json:"codec_name"`
			Width        int               `json:"width"`
			Height       int               `json:"height"`
			PixFmt       string            `json:"pix_fmt"`
			Duration     string            `json:"duration"`
			FrameRate    string            `json:"avg_frame_rate"`
			Tags         map[string]string `json:"tags"`
			SideDataList []struct {
				Rotation float64 `json:"rotation"`
			} `json:"side_data_list"`
		} `json:"streams"`
		Format struct {
			Duration string `json:"duration"`
			Name     string `json:"format_name"`
		} `json:"format"`
	}
	if err := json.Unmarshal(out, &doc); err != nil {
		return ProbeResult{}, err
	}
	if len(doc.Streams) == 0 {
		return ProbeResult{}, errors.New("no video stream")
	}
	s := doc.Streams[0]
	r := ProbeResult{Width: s.Width, Height: s.Height, Codec: s.Codec, PixFmt: s.PixFmt, Format: doc.Format.Name}
	r.Duration, _ = strconv.ParseFloat(doc.Format.Duration, 64)
	if r.Duration <= 0 {
		r.Duration, _ = strconv.ParseFloat(s.Duration, 64)
	}
	if num, den, ok := strings.Cut(s.FrameRate, "/"); ok {
		n, _ := strconv.ParseFloat(num, 64)
		d, _ := strconv.ParseFloat(den, 64)
		if d > 0 {
			r.FPS = n / d
		}
	}
	rot := 0.0
	if v, ok := s.Tags["rotate"]; ok {
		rot, _ = strconv.ParseFloat(v, 64)
	}
	for _, sd := range s.SideDataList {
		if sd.Rotation != 0 {
			rot = sd.Rotation
		}
	}
	if int(math.Abs(rot))%180 == 90 {
		r.Width, r.Height = r.Height, r.Width
	}
	return r, nil
}

// Frame extracts a single (auto-rotated) frame at `at` seconds as a JPEG.
func (f *FFmpeg) Frame(ctx context.Context, in, out string, at float64, w, h int) error {
	if !f.Available() {
		return errors.New("ffmpeg not available")
	}
	tmp := strings.TrimSuffix(out, filepath.Ext(out)) + ".tmp.jpg"
	try := func(at float64) error {
		ctx, cancel := context.WithTimeout(ctx, 60*time.Second)
		defer cancel()
		args := []string{"-v", "error", "-y"}
		if at > 0 {
			args = append(args, "-ss", strconv.FormatFloat(at, 'f', 3, 64))
		}
		args = append(args, "-i", in, "-frames:v", "1", "-an", "-sn", "-dn")
		if w > 0 && h > 0 {
			args = append(args, "-vf", fmt.Sprintf("scale=%d:%d", even(w), even(h)))
		}
		args = append(args, "-q:v", "3", "-update", "1", tmp)
		_, err := f.run(ctx, true, f.ffmpeg, args...)
		if err == nil {
			if st, serr := os.Stat(tmp); serr != nil || st.Size() == 0 {
				err = errors.New("no frame produced")
			}
		}
		return err
	}
	err := try(at)
	if err != nil && at > 0 {
		err = try(0)
	}
	if err != nil {
		os.Remove(tmp)
		return err
	}
	return os.Rename(tmp, out)
}

func (f *FFmpeg) encoderList() map[string]bool {
	f.encOnce.Do(func() {
		f.encoders = map[string]bool{}
		ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		defer cancel()
		out, err := f.run(ctx, false, f.ffmpeg, "-hide_banner", "-encoders")
		if err != nil {
			return
		}
		for _, line := range strings.Split(string(out), "\n") {
			fields := strings.Fields(line)
			if len(fields) >= 2 && len(fields[0]) == 6 {
				f.encoders[fields[1]] = true
			}
		}
	})
	return f.encoders
}

// Transcode converts a video to a browser and hardware-decoder friendly
// H.264/yuv420p MP4 scaled to w x h. On Raspberry Pi the V4L2 hardware
// encoder is tried first, falling back to libx264.
func (f *FFmpeg) Transcode(ctx context.Context, in, out string, w, h int) error {
	if !f.Available() {
		return errors.New("ffmpeg not available")
	}
	encs := f.encoderList()
	var candidates []string
	if runtime.GOOS == "linux" && strings.HasPrefix(runtime.GOARCH, "arm") && encs["h264_v4l2m2m"] {
		candidates = append(candidates, "h264_v4l2m2m")
	}
	for _, e := range []string{"libx264", "libopenh264", "h264_mf"} {
		if encs[e] {
			candidates = append(candidates, e)
		}
	}
	if len(candidates) == 0 {
		return errors.New("ffmpeg has no H.264 encoder")
	}
	threads := max(1, runtime.NumCPU()/2)
	tmp := strings.TrimSuffix(out, filepath.Ext(out)) + ".tmp.mp4"
	var lastErr error
	for _, enc := range candidates {
		args := []string{"-v", "error", "-y", "-i", in, "-map", "0:v:0", "-an", "-sn", "-dn",
			"-vf", fmt.Sprintf("scale=%d:%d,format=yuv420p", even(w), even(h)),
			"-c:v", enc}
		bitrate := fmt.Sprintf("%dk", max(1500, min(10000, w*h*4/1000)))
		switch enc {
		case "libx264":
			args = append(args, "-preset", "veryfast", "-crf", "22", "-profile:v", "high", "-threads", strconv.Itoa(threads))
		default:
			args = append(args, "-b:v", bitrate)
		}
		args = append(args, "-movflags", "+faststart", "-f", "mp4", tmp)
		tctx, cancel := context.WithTimeout(ctx, 6*time.Hour)
		start := time.Now()
		_, err := f.run(tctx, true, f.ffmpeg, args...)
		cancel()
		if err == nil {
			log.Printf("media: transcoded %s with %s in %s", filepath.Base(in), enc, time.Since(start).Round(time.Second))
			return os.Rename(tmp, out)
		}
		os.Remove(tmp)
		lastErr = err
		if ctx.Err() != nil {
			return ctx.Err()
		}
		log.Printf("media: %s transcode with %s failed: %v", filepath.Base(in), enc, err)
	}
	return lastErr
}

func even(v int) int {
	if v < 2 {
		return 2
	}
	return v &^ 1
}

package app

import (
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"path"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"

	"github.com/olkham/DigitalCanvas/internal/config"
	"github.com/olkham/DigitalCanvas/internal/imaging"
	"github.com/olkham/DigitalCanvas/internal/media"
	"github.com/olkham/DigitalCanvas/internal/player"
	"github.com/olkham/DigitalCanvas/internal/sysinfo"
)

// ---- state ----

// Status is the live status shown in the UI.
type Status struct {
	MQTT struct {
		Connected bool   `json:"connected"`
		Broker    string `json:"broker"`
		Error     string `json:"error,omitempty"`
	} `json:"mqtt"`
	Displays      int `json:"displays"`
	KioskDisplays int `json:"kiosk_displays"`
	Kiosk         struct {
		Enabled bool   `json:"enabled"`
		Running bool   `json:"running"`
		Browser string `json:"browser,omitempty"`
	} `json:"kiosk"`
	Monitor struct {
		DDC        bool   `json:"ddc"`
		Name       string `json:"name,omitempty"`
		Power      bool   `json:"power"`
		Brightness int    `json:"brightness"`
	} `json:"monitor"`
	Sensors struct {
		Light bool    `json:"light"`
		Lux   float64 `json:"lux"`
		Accel bool    `json:"accel"`
	} `json:"sensors"`
	FFmpeg bool `json:"ffmpeg"`
	Screen struct {
		Width  int `json:"width"`
		Height int `json:"height"`
	} `json:"screen"`
	Simulated bool `json:"simulated,omitempty"`
}

func (a *App) status() Status {
	var st Status
	s := a.cfg.Get()
	st.MQTT.Connected = a.mqtt.Connected()
	st.MQTT.Broker = fmt.Sprintf("%s:%d", s.MQTTBroker, s.MQTTPort)
	st.MQTT.Error = a.mqtt.LastError()
	st.Displays, st.KioskDisplays = a.hub.Displays()
	st.Kiosk.Enabled = a.kiosk != nil
	st.Kiosk.Running = a.kiosk.Running()
	if b := a.kiosk.Browser(); b != "" {
		st.Kiosk.Browser = strings.TrimSuffix(filepath.Base(b), ".exe")
	}
	st.Monitor.DDC = a.mon.Available()
	st.Monitor.Name = a.mon.Name()
	a.mu.Lock()
	st.Monitor.Power = a.powerOn
	st.Monitor.Brightness = a.brightness
	st.Sensors.Lux = a.lux
	a.mu.Unlock()
	st.Sensors.Light = a.sens.LightAvailable()
	st.Sensors.Accel = a.sens.AccelAvailable()
	st.FFmpeg = a.lib.FFmpegAvailable()
	st.Screen.Width, st.Screen.Height = a.lib.Screen()
	st.Simulated = a.opts.Simulate
	return st
}

// Info is static-ish host information.
type Info struct {
	Version      string   `json:"version"`
	Platform     string   `json:"platform"`
	Hostname     string   `json:"hostname"`
	IPs          []string `json:"ips"`
	Port         int      `json:"port"`
	UptimeSec    int64    `json:"uptime_sec"`
	MemoryBytes  uint64   `json:"memory_bytes"`
	CPUTemp      float64  `json:"cpu_temp,omitempty"`
	PowerControl bool     `json:"power_control"`
	MediaCount   int      `json:"media_count"`
	GoVersion    string   `json:"go_version"`
}

func (a *App) info() Info {
	return Info{
		Version: a.opts.Version, Platform: sysinfo.Platform(), Hostname: sysinfo.Hostname(),
		IPs: sysinfo.LocalIPv4s(), Port: a.cfg.Get().WebInterfacePort,
		UptimeSec: int64(time.Since(a.started).Seconds()), MemoryBytes: sysinfo.RSS(),
		CPUTemp: sysinfo.CPUTemp(), PowerControl: sysinfo.PowerControlSupported() && !a.opts.Simulate,
		MediaCount: a.lib.Count(), GoVersion: runtime.Version(),
	}
}

// State is the full snapshot sent to new clients.
type State struct {
	Config   map[string]any `json:"config"`
	Slide    *player.Slide  `json:"slide,omitempty"`
	Playback player.Status  `json:"playback"`
	Status   Status         `json:"status"`
	Power    bool           `json:"power"`
	Media    []media.Item   `json:"media,omitempty"`
	Info     *Info          `json:"info,omitempty"`
}

func (a *App) state(withMedia bool) State {
	st := State{Config: a.cfg.Map(true), Playback: a.player.Status(), Status: a.status()}
	if s, ok := a.player.Current(); ok {
		st.Slide = &s
	}
	a.mu.Lock()
	st.Power = a.powerOn
	a.mu.Unlock()
	if withMedia {
		st.Media = a.lib.Items()
		inf := a.info()
		st.Info = &inf
	}
	return st
}

// ---- configuration ----

// UpdateConfig validates and applies settings from any source.
func (a *App) UpdateConfig(values map[string]any) ([]string, map[string]string) {
	return a.cfg.Update(values)
}

// ---- playback ----

// Command performs a named playback/display action.
func (a *App) Command(action, value string) error {
	switch strings.ToLower(action) {
	case "next":
		a.player.Next()
	case "previous", "prev", "back":
		a.player.Previous()
	case "pause", "stop":
		a.player.Pause(player.ByUser)
	case "resume", "play", "start":
		a.player.Resume(player.ByUser)
	case "toggle", "play_pause":
		a.player.Toggle()
	case "select", "show":
		if !a.player.Select(value) {
			return fmt.Errorf("no such media: %s", value)
		}
	case "rotate":
		return a.cfg.Set("rotation", (a.cfg.Get().Rotation+90)%360)
	case "toggle_scale":
		mode := "fit"
		if a.cfg.Get().ScaleMode == "fit" {
			mode = "fill"
		}
		return a.cfg.Set("scale_mode", mode)
	case "toggle_fullscreen":
		mode := "fullscreen"
		if a.cfg.Get().DisplayMode == "fullscreen" {
			mode = "windowed"
		}
		return a.cfg.Set("display_mode", mode)
	case "reload_display":
		a.hub.Broadcast("reload", map[string]any{})
	case "quit":
		a.Quit()
	default:
		return fmt.Errorf("unknown command %q", action)
	}
	return nil
}

func firstErr(errs map[string]string) error {
	for k, v := range errs {
		return fmt.Errorf("%s: %s", k, v)
	}
	return nil
}

// ShowBytes displays an image immediately without adding it to the library.
func (a *App) ShowBytes(raw []byte, title, source string) error {
	t, err := a.trans.Add(raw, title, source, a.lib.Limit())
	if err != nil {
		return err
	}
	a.player.ShowTransient(t)
	return nil
}

// Transient returns a transient image.
func (a *App) Transient(id string) (*media.Transient, bool) { return a.trans.Get(id) }

// DeleteMedia removes library items.
func (a *App) DeleteMedia(names ...string) (deleted int, err error) {
	for _, n := range names {
		name, ok := media.SafeName(n)
		if !ok {
			continue
		}
		if e := a.lib.Remove(name); e == nil {
			deleted++
		} else if !errors.Is(e, os.ErrNotExist) && err == nil {
			err = e
		}
	}
	return deleted, err
}

// DeleteCurrent removes the item on screen (the original /slideshow/delete).
func (a *App) DeleteCurrent() error {
	s, ok := a.player.Current()
	if !ok || s.Transient || s.Kind == "idle" {
		return errors.New("nothing to delete")
	}
	_, err := a.DeleteMedia(s.Name)
	return err
}

// ImportURL downloads media from a URL into the library.
func (a *App) ImportURL(ctx context.Context, raw string) (media.Item, error) {
	u, err := url.Parse(strings.TrimSpace(raw))
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
		return media.Item{}, errors.New("enter an http(s) URL")
	}
	tmp, ct, err := a.download(ctx, u.String(), 2<<30)
	if err != nil {
		return media.Item{}, err
	}
	return a.lib.Import(tmp, media.ImportOptions{OriginalName: path.Base(u.Path), ContentType: ct})
}

var httpClient = &http.Client{Timeout: 10 * time.Minute}

func (a *App) download(ctx context.Context, u string, limit int64) (tmpPath, contentType string, err error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return "", "", err
	}
	req.Header.Set("User-Agent", "DigitalCanvas/"+a.opts.Version)
	resp, err := httpClient.Do(req)
	if err != nil {
		return "", "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", "", fmt.Errorf("download failed: %s", resp.Status)
	}
	f, err := a.tempFile()
	if err != nil {
		return "", "", err
	}
	n, err := io.Copy(f, io.LimitReader(resp.Body, limit+1))
	f.Close()
	if err == nil && n > limit {
		err = errors.New("file too large")
	}
	if err != nil {
		os.Remove(f.Name())
		return "", "", err
	}
	return f.Name(), resp.Header.Get("Content-Type"), nil
}

func (a *App) fetchBytes(ctx context.Context, u string, limit int64) ([]byte, error) {
	ctx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return nil, err
	}
	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("%s: %s", u, resp.Status)
	}
	return io.ReadAll(io.LimitReader(resp.Body, limit))
}

func (a *App) tempFile() (*os.File, error) {
	dir := a.path(filepath.Join("cache", "upload"))
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, err
	}
	return os.CreateTemp(dir, "upload-*.tmp")
}

// ---- monitor ----

// SetBrightness sets a manual brightness (disabling auto brightness), or
// enables auto brightness when v < 0, mirroring the original API.
func (a *App) SetBrightness(v int) error {
	if v < 0 {
		return a.cfg.Set("auto_brightness", true)
	}
	if err := a.cfg.Set("auto_brightness", false); err != nil {
		return err
	}
	return a.applyBrightness(v)
}

func (a *App) applyBrightness(v int) error {
	v = max(0, min(100, v))
	err := a.mon.SetBrightness(v)
	a.mu.Lock()
	if err == nil || a.opts.Simulate {
		a.brightness = v
	}
	a.mu.Unlock()
	a.statusChanged()
	return err
}

// SetPower turns the screen on or off (DDC/CI, command fallback, and the
// display page blanks itself either way).
func (a *App) SetPower(on bool) error {
	err := a.mon.SetPower(on)
	a.mu.Lock()
	a.powerOn = on
	a.mu.Unlock()
	a.hub.Broadcast("power", map[string]bool{"on": on})
	a.statusChanged()
	if err != nil {
		log.Printf("monitor: %v (display blanked instead)", err)
	}
	return nil
}

// ---- canvas snapshot ----

func (a *App) invalidateCanvas() {
	a.mu.Lock()
	a.canvasKey, a.canvasJPEG = "", nil
	a.mu.Unlock()
}

// CanvasJPEG renders what the display shows (the original /canvas endpoint).
func (a *App) CanvasJPEG() ([]byte, error) {
	sl, ok := a.player.Current()
	if !ok {
		return nil, errors.New("nothing on screen")
	}
	s := a.cfg.Get()
	w, h := a.lib.Screen()
	key := fmt.Sprintf("%d|%s|%s|%d|%d|%s|%d", sl.Seq, sl.Name, sl.Src, w, h, s.ScaleMode, s.Rotation)
	a.mu.Lock()
	if a.canvasKey == key {
		b := a.canvasJPEG
		a.mu.Unlock()
		return b, nil
	}
	a.mu.Unlock()

	var d *imaging.Decoded
	var err error
	switch {
	case sl.Kind == "idle":
		d, err = imaging.Decode(a.web.raw("background.jpg"))
	case sl.Transient:
		t, ok := a.trans.Get(sl.Name)
		if !ok {
			return nil, errors.New("image expired")
		}
		d, err = imaging.Decode(t.Data)
	default:
		var p string
		if p, err = a.lib.PosterPath(sl.Name); err == nil {
			d, err = imaging.DecodeFile(p)
		}
	}
	if err != nil {
		return nil, err
	}
	out, err := imaging.EncodeJPEG(imaging.Canvas(d, w, h, s.ScaleMode, s.Rotation), 85)
	if err != nil {
		return nil, err
	}
	a.mu.Lock()
	a.canvasKey, a.canvasJPEG = key, out
	a.mu.Unlock()
	return out, nil
}

// ---- MQTT ----

func (a *App) handleMQTT(cmd, payload string) {
	lp := strings.ToLower(payload)
	set := func(key string, v any) {
		if err := a.cfg.Set(key, v); err != nil {
			log.Printf("mqtt: %s=%q rejected: %v", key, payload, err)
		}
	}
	switch cmd {
	case "slideshow":
		if err := a.Command(lp, ""); err != nil {
			log.Printf("mqtt: slideshow %q: %v", payload, err)
		}
	case "select":
		if !a.player.Select(payload) {
			log.Printf("mqtt: select %q: no such media", payload)
		}
	case "plex":
		set("allow_plex", payload)
	case "rotation":
		set("rotation", payload)
	case "brightness":
		if lp == "auto" {
			set("auto_brightness", true)
			return
		}
		v, err := strconv.Atoi(payload)
		if err != nil {
			log.Printf("mqtt: brightness %q is not a number", payload)
			return
		}
		_ = a.SetBrightness(v)
	case "power":
		on, err := config.ToBool(payload)
		if err != nil {
			log.Printf("mqtt: power %q: expected on/off", payload)
			return
		}
		_ = a.SetPower(on)
	case "display_now":
		go func() {
			var raw []byte
			var err error
			if strings.HasPrefix(lp, "http://") || strings.HasPrefix(lp, "https://") {
				raw, err = a.fetchBytes(context.Background(), payload, 64<<20)
			} else {
				raw, err = decodeBase64Image(payload)
			}
			if err == nil {
				err = a.ShowBytes(raw, "remote_image", "display_now")
			}
			if err != nil {
				log.Printf("mqtt: display_now: %v", err)
			}
		}()
	case "display_mode", "scale_mode", "theme", "auto_brightness", "auto_rotation",
		"frame_interval", "transition_duration", "media_orientation_filter", "playback_mode",
		"time_on", "time_off", "schedule_enabled", "pause_when_plex_playing", "allow_plex":
		set(cmd, payload)
	default:
		// unknown sub-topics are ignored (they may belong to other tools)
	}
}

func decodeBase64Image(s string) ([]byte, error) {
	s = strings.TrimSpace(s)
	if i := strings.Index(s, ","); strings.HasPrefix(s, "data:") && i > 0 {
		s = s[i+1:]
	}
	s = strings.Map(func(r rune) rune {
		if r == '\n' || r == '\r' || r == ' ' {
			return -1
		}
		return r
	}, s)
	for _, enc := range []*base64.Encoding{base64.StdEncoding, base64.RawStdEncoding, base64.URLEncoding, base64.RawURLEncoding} {
		if b, err := enc.DecodeString(s); err == nil {
			return b, nil
		}
	}
	return nil, errors.New("invalid base64 image data")
}

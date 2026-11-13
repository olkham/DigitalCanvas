// Package app wires the components together and implements every user
// facing action once, so the web UI, the legacy HTTP API, MQTT and the
// display keyboard all behave identically.
package app

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"time"

	"github.com/olkham/DigitalCanvas/internal/config"
	"github.com/olkham/DigitalCanvas/internal/hub"
	"github.com/olkham/DigitalCanvas/internal/kiosk"
	"github.com/olkham/DigitalCanvas/internal/media"
	"github.com/olkham/DigitalCanvas/internal/monitor"
	"github.com/olkham/DigitalCanvas/internal/mqttc"
	"github.com/olkham/DigitalCanvas/internal/player"
	"github.com/olkham/DigitalCanvas/internal/sensors"
	"github.com/olkham/DigitalCanvas/internal/sysinfo"
)

// Options are command line options.
type Options struct {
	ConfigPath string
	Simulate   bool // never touch monitor, sensors or system power
	NoBrowser  bool // do not launch the kiosk browser
	Listen     string
	Version    string
}

// App is the running canvas.
type App struct {
	opts    Options
	baseDir string
	started time.Time

	cfg    *config.Store
	lib    *media.Library
	trans  *media.TransientStore
	player *player.Player
	hub    *hub.Hub
	mon    *monitor.Manager
	sens   *sensors.Reader
	mqtt   *mqttc.Bridge
	kiosk  *kiosk.Kiosk
	web    *webAssets

	quitOnce sync.Once
	quit     chan struct{}

	mu          sync.Mutex
	powerOn     bool
	brightness  int
	lux         float64
	luxAt       time.Time
	accel       [3]float64
	canvasKey   string
	canvasJPEG  []byte
	schedState  int // -1 unknown, 0 off, 1 on
	rebuildT    *time.Timer
	mqttT       *time.Timer
	statusT     *time.Timer
	imagesT     *time.Timer
	screenKnown bool
	restart     bool
}

// New loads configuration and prepares all components.
func New(opts Options) (*App, error) {
	abs, err := filepath.Abs(opts.ConfigPath)
	if err != nil {
		return nil, err
	}
	a := &App{opts: opts, baseDir: filepath.Dir(abs), started: time.Now(), quit: make(chan struct{}), schedState: -1, powerOn: true, brightness: -1}
	if a.cfg, err = config.Open(abs, sysinfo.DeviceID()); err != nil {
		return nil, err
	}
	s := a.cfg.Get()
	cacheDir := a.path("cache")
	a.lib, err = media.Open(media.Options{
		MediaDir: a.path(s.ImageFolder), ThumbDir: a.path(s.ThumbnailFolder), CacheDir: cacheDir,
		Transcode: func() bool { return a.cfg.Get().TranscodeVideos },
	})
	if err != nil {
		return nil, err
	}
	a.loadScreen()
	a.trans = media.NewTransientStore(4)
	a.hub = hub.New()
	a.hub.OnChange = a.statusChanged
	a.player = player.New(a.lib, a.playerSettings, a.onPlayerEvent, a.idleSlide)
	a.mon = monitor.New(opts.Simulate, func() (string, string) {
		s := a.cfg.Get()
		return s.ScreenOnCommand, s.ScreenOffCommand
	})
	a.powerOn = a.mon.PowerOn()
	a.brightness = a.mon.Brightness() // -1 when there is no DDC/CI monitor
	a.sens = sensors.Open(s.I2CBus, opts.Simulate)
	a.mqtt = mqttc.New(a.handleMQTT, a.onMQTTConnect, a.statusChanged)
	if a.web, err = loadWebAssets(); err != nil {
		return nil, err
	}
	a.cfg.Subscribe(a.onConfigChanged)
	a.lib.Subscribe(a.onLibraryEvent)
	return a, nil
}

func (a *App) path(p string) string {
	if filepath.IsAbs(p) {
		return p
	}
	return filepath.Join(a.baseDir, p)
}

// Run serves until ctx is cancelled or a quit command arrives.
func (a *App) Run(ctx context.Context) error {
	s := a.cfg.Get()
	if err := a.lib.Scan(); err != nil {
		return fmt.Errorf("scanning media: %w", err)
	}
	go a.lib.Watch(30 * time.Second)

	addr := a.opts.Listen
	if addr == "" {
		addr = ":" + strconv.Itoa(s.WebInterfacePort)
	}
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		return fmt.Errorf("listening on %s: %w", addr, err)
	}
	srv := &http.Server{Handler: a.routes(), ReadHeaderTimeout: 15 * time.Second, IdleTimeout: 120 * time.Second}
	srv.RegisterOnShutdown(a.hub.Close)
	go func() {
		if err := srv.Serve(ln); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Printf("http: %v", err)
		}
	}()
	port := ln.Addr().(*net.TCPAddr).Port
	log.Printf("web: control panel on http://%s:%d", firstIP(), port)

	a.player.Start()
	a.mqtt.Configure(a.mqttConfig())
	if !a.opts.NoBrowser {
		a.kiosk = kiosk.New(s.DisplayBrowser, fmt.Sprintf("http://127.0.0.1:%d", port), a.path(filepath.Join("cache", "browser-profile")))
		a.kiosk.Start(s.DisplayMode)
	}
	go a.automation(ctx)

	select {
	case <-ctx.Done():
	case <-a.quit:
	}
	log.Printf("shutting down")
	a.kiosk.Stop()
	shutCtx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	_ = srv.Shutdown(shutCtx)
	a.mqtt.Close()
	if err := a.cfg.Flush(); err != nil {
		log.Printf("config: %v", err)
	}
	a.lib.Close()
	a.mon.Close()
	a.sens.Close()
	return nil
}

// Quit stops the application (keyboard q/Esc on the kiosk, MQTT quit).
func (a *App) Quit() { a.quitOnce.Do(func() { close(a.quit) }) }

// Restart stops the application and asks main to start it again.
func (a *App) Restart() {
	a.mu.Lock()
	a.restart = true
	a.mu.Unlock()
	a.Quit()
}

// RestartRequested reports whether Run ended because of Restart.
func (a *App) RestartRequested() bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.restart
}

func firstIP() string {
	if ips := sysinfo.LocalIPv4s(); len(ips) > 0 {
		return ips[0]
	}
	return "localhost"
}

// ---- wiring ----

func (a *App) playerSettings() player.Settings {
	s := a.cfg.Get()
	return player.Settings{FrameInterval: s.FrameInterval, Transition: s.TransitionDuration, Filter: s.MediaOrientationFilter, Order: s.PlaybackMode}
}

func (a *App) idleSlide() player.Slide {
	s := a.cfg.Get()
	port := s.WebInterfacePort
	var urls []string
	for _, ip := range sysinfo.LocalIPv4s() {
		urls = append(urls, fmt.Sprintf("http://%s:%d", ip, port))
		if len(urls) == 2 {
			break
		}
	}
	return player.Slide{Name: "idle", Title: s.DeviceName, Bg: "/assets/background.jpg", URLs: urls}
}

func (a *App) onPlayerEvent(name string, data any) {
	a.hub.Broadcast(name, data)
	if name == "slide" {
		if s, ok := data.(player.Slide); ok && s.Kind != "idle" {
			title := s.Name
			if s.Transient {
				title = s.Title
			}
			a.mqtt.Publish("current_image", title, false)
		}
	}
}

func (a *App) onLibraryEvent(ev media.Event) {
	a.hub.Broadcast("media."+ev.Type, ev.Item)
	a.mu.Lock()
	// Coalesce bursts (initial thumbnail generation, bulk deletes).
	if a.rebuildT != nil {
		a.rebuildT.Stop()
	}
	a.rebuildT = time.AfterFunc(300*time.Millisecond, func() { a.player.Rebuild(false) })
	if ev.Type != "update" {
		if a.imagesT != nil {
			a.imagesT.Stop()
		}
		a.imagesT = time.AfterFunc(time.Second, a.publishAvailableImages)
	}
	a.mu.Unlock()
}

func (a *App) onConfigChanged(changed []string) {
	set := map[string]bool{}
	for _, k := range changed {
		set[k] = true
	}
	s := a.cfg.Get()
	if set["frame_interval"] || set["transition_duration"] {
		a.player.Retime()
	}
	if set["media_orientation_filter"] || set["playback_mode"] {
		a.player.Rebuild(set["playback_mode"])
	}
	if set["display_mode"] {
		a.kiosk.SetMode(s.DisplayMode)
	}
	if set["device_name"] || set["web_interface_port"] {
		a.player.RefreshIdle()
	}
	if set["transcode_videos"] {
		go a.lib.RequeueVideos()
	}
	if set["schedule_enabled"] || set["time_on"] || set["time_off"] {
		go a.checkSchedule(time.Now())
	}
	if set["mqtt_broker"] || set["mqtt_port"] || set["mqtt_topic"] || set["mqtt_username"] || set["mqtt_password"] {
		a.mu.Lock()
		if a.mqttT != nil {
			a.mqttT.Stop()
		}
		a.mqttT = time.AfterFunc(time.Second, func() { a.mqtt.Configure(a.mqttConfig()) })
		a.mu.Unlock()
	}
	if set["rotation"] || set["scale_mode"] {
		a.invalidateCanvas()
	}
	a.hub.Broadcast("config", a.cfg.Map(true))
	a.mqtt.Publish("config", a.cfg.Map(true), false)
	for _, k := range changed {
		if config.RestartKeys[k] {
			log.Printf("config: %s changed - restart to apply", k)
		}
	}
}

func (a *App) mqttConfig() mqttc.Config {
	s := a.cfg.Get()
	return mqttc.Config{
		Broker: s.MQTTBroker, Port: s.MQTTPort, Topic: s.MQTTTopic,
		Username: s.MQTTUsername, Password: s.MQTTPassword,
		ClientID: "digital-canvas-" + sysinfo.DeviceID(),
	}
}

func (a *App) onMQTTConnect() {
	a.mqtt.Publish("config", a.cfg.Map(true), false)
	a.publishAvailableImages()
	if s, ok := a.player.Current(); ok && s.Kind != "idle" {
		title := s.Name
		if s.Transient {
			title = s.Title
		}
		a.mqtt.Publish("current_image", title, false)
	}
}

func (a *App) publishAvailableImages() {
	names := []string{}
	for _, it := range a.lib.Items() {
		names = append(names, it.Name)
	}
	a.mqtt.Publish("available_images", names, true)
}

// statusChanged broadcasts the status, coalescing bursts.
func (a *App) statusChanged() {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.statusT != nil {
		return
	}
	a.statusT = time.AfterFunc(150*time.Millisecond, func() {
		a.mu.Lock()
		a.statusT = nil
		a.mu.Unlock()
		a.hub.Broadcast("status", a.status())
	})
}

// ---- screen size ----

type screenFile struct {
	W int `json:"width"`
	H int `json:"height"`
}

func (a *App) loadScreen() {
	b, err := os.ReadFile(a.path(filepath.Join("cache", "screen.json")))
	if err != nil {
		return
	}
	var s screenFile
	if json.Unmarshal(b, &s) == nil && s.W > 0 && s.H > 0 {
		a.lib.SetScreen(s.W, s.H)
		a.screenKnown = true
	}
}

// setScreen records the resolution reported by the (kiosk) display.
func (a *App) setScreen(w, h int) {
	if w < 320 || h < 240 || w > 16384 || h > 16384 {
		return
	}
	ow, oh := a.lib.Screen()
	a.mu.Lock()
	known := a.screenKnown
	a.screenKnown = true
	a.mu.Unlock()
	if known && ow == w && oh == h {
		return
	}
	a.lib.SetScreen(w, h)
	b, _ := json.Marshal(screenFile{W: w, H: h})
	_ = config.WriteFileAtomic(a.path(filepath.Join("cache", "screen.json")), b, 0o644)
	log.Printf("display: screen is %dx%d", w, h)
	a.invalidateCanvas()
	if ow != w || oh != h {
		go a.lib.RequeueVideos()
	}
	a.statusChanged()
}

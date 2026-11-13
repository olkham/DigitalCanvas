// Package kiosk launches and supervises the browser that renders the display
// page. The browser composites crossfades/rotation on the GPU and decodes
// video in hardware, which is what makes the rewrite cheap on a Raspberry Pi.
package kiosk

import (
	"crypto/rand"
	"encoding/hex"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
	"sync"
	"time"

	"github.com/olkham/DigitalCanvas/internal/sysinfo"
)

// Kiosk supervises one browser process.
type Kiosk struct {
	browser    string
	family     string // chromium | firefox
	baseURL    string
	profileDir string
	token      string

	mu       sync.Mutex
	mode     string
	cmd      *exec.Cmd
	stopping bool
	relaunch chan struct{}
	running  bool
	done     chan struct{}
}

// New prepares a kiosk; choice is the display_browser setting ("auto",
// "none" or a command/path). It returns nil when disabled or not found.
func New(choice, baseURL, profileDir string) *Kiosk {
	choice = strings.TrimSpace(choice)
	if choice == "" || strings.EqualFold(choice, "none") || strings.EqualFold(choice, "off") {
		log.Printf("kiosk: disabled (display_browser=%q); open %s/display in any browser", choice, baseURL)
		return nil
	}
	bin := choice
	if strings.EqualFold(choice, "auto") {
		bin = findBrowser()
		if bin == "" {
			log.Printf("kiosk: no supported browser found; install chromium or open %s/display manually", baseURL)
			return nil
		}
	} else if p, err := exec.LookPath(choice); err == nil {
		bin = p
	}
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	k := &Kiosk{
		browser: bin, baseURL: baseURL, profileDir: profileDir, token: hex.EncodeToString(b),
		family: "chromium", relaunch: make(chan struct{}, 1), done: make(chan struct{}),
	}
	if strings.Contains(strings.ToLower(filepath.Base(bin)), "firefox") {
		k.family = "firefox"
	}
	log.Printf("kiosk: using %s", bin)
	return k
}

// Token authenticates the supervised display (allows it to quit the app).
func (k *Kiosk) Token() string {
	if k == nil {
		return ""
	}
	return k.token
}

// Browser returns the browser executable.
func (k *Kiosk) Browser() string {
	if k == nil {
		return ""
	}
	return k.browser
}

// Running reports whether the browser process is alive.
func (k *Kiosk) Running() bool {
	if k == nil {
		return false
	}
	k.mu.Lock()
	defer k.mu.Unlock()
	return k.running
}

func findBrowser() string {
	var names []string
	switch runtime.GOOS {
	case "windows":
		for _, base := range []string{os.Getenv("ProgramFiles"), os.Getenv("ProgramFiles(x86)"), os.Getenv("LocalAppData")} {
			if base == "" {
				continue
			}
			names = append(names,
				filepath.Join(base, "Google", "Chrome", "Application", "chrome.exe"),
				filepath.Join(base, "Chromium", "Application", "chrome.exe"),
				filepath.Join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
		}
	case "darwin":
		names = []string{"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium"}
	default:
		names = []string{"chromium-browser", "chromium", "google-chrome-stable", "google-chrome", "microsoft-edge", "firefox-esr", "firefox"}
	}
	for _, n := range names {
		if filepath.IsAbs(n) {
			if _, err := os.Stat(n); err == nil {
				return n
			}
			continue
		}
		if p, err := exec.LookPath(n); err == nil {
			return p
		}
	}
	return ""
}

// Start launches the browser and keeps it running until Stop.
func (k *Kiosk) Start(mode string) {
	if k == nil {
		return
	}
	k.mu.Lock()
	k.mode = mode
	k.mu.Unlock()
	go k.supervise()
}

// SetMode switches between fullscreen and windowed by relaunching.
func (k *Kiosk) SetMode(mode string) {
	if k == nil {
		return
	}
	k.mu.Lock()
	if k.mode == mode {
		k.mu.Unlock()
		return
	}
	k.mode = mode
	cmd := k.cmd
	k.mu.Unlock()
	select {
	case k.relaunch <- struct{}{}:
	default:
	}
	if cmd != nil && cmd.Process != nil {
		terminate(cmd)
	}
}

// Stop terminates the browser and waits briefly for it to exit.
func (k *Kiosk) Stop() {
	if k == nil {
		return
	}
	k.mu.Lock()
	k.stopping = true
	cmd := k.cmd
	k.mu.Unlock()
	if cmd != nil && cmd.Process != nil {
		terminate(cmd)
		select {
		case <-k.done:
		case <-time.After(5 * time.Second):
		}
	}
}

func (k *Kiosk) supervise() {
	defer close(k.done)
	backoff := 2 * time.Second
	waitingLogged := false
	for {
		k.mu.Lock()
		stopping, mode := k.stopping, k.mode
		k.mu.Unlock()
		if stopping {
			return
		}
		if !sysinfo.HasDisplay() {
			if !waitingLogged {
				log.Printf("kiosk: waiting for a graphical session (Wayland/X11)...")
				waitingLogged = true
			}
			time.Sleep(3 * time.Second)
			continue
		}
		k.fixProfile()
		cmd := exec.Command(k.browser, k.args(mode)...)
		cmd.Env = sysinfo.DisplayEnv()
		prepare(cmd)
		start := time.Now()
		if err := cmd.Start(); err != nil {
			log.Printf("kiosk: launching browser failed: %v", err)
			time.Sleep(backoff)
			backoff = min(backoff*2, 60*time.Second)
			continue
		}
		k.mu.Lock()
		k.cmd, k.running = cmd, true
		k.mu.Unlock()
		log.Printf("kiosk: browser started (%s, pid %d)", mode, cmd.Process.Pid)
		err := cmd.Wait()
		k.mu.Lock()
		k.cmd, k.running = nil, false
		stopping = k.stopping
		k.mu.Unlock()
		if stopping {
			return
		}
		select {
		case <-k.relaunch:
			backoff = 2 * time.Second
			continue
		default:
		}
		if time.Since(start) > time.Minute {
			backoff = 2 * time.Second
		}
		log.Printf("kiosk: browser exited (%v); restarting in %s", err, backoff)
		time.Sleep(backoff)
		backoff = min(backoff*2, 60*time.Second)
	}
}

func (k *Kiosk) args(mode string) []string {
	url := k.baseURL + "/display?kiosk=" + k.token
	if k.family == "firefox" {
		args := []string{"--profile", k.profileDir, "--no-remote"}
		if mode == "fullscreen" {
			return append(args, "--kiosk", url)
		}
		return append(args, "--new-window", url)
	}
	args := []string{
		"--user-data-dir=" + k.profileDir,
		"--no-first-run", "--no-default-browser-check", "--noerrdialogs",
		"--disable-infobars", "--disable-session-crashed-bubble", "--disable-translate",
		"--disable-features=Translate,TranslateUI,MediaRouter,OptimizationHints,InfiniteSessionRestore",
		"--disable-component-update", "--disable-background-networking", "--disable-sync",
		"--disable-pinch", "--overscroll-history-navigation=0",
		"--autoplay-policy=no-user-gesture-required",
		"--check-for-update-interval=31536000",
		"--password-store=basic",
	}
	if runtime.GOOS == "linux" {
		args = append(args, "--ozone-platform-hint=auto")
	}
	if mode == "fullscreen" {
		args = append(args, "--kiosk", "--start-fullscreen")
		if strings.Contains(strings.ToLower(k.browser), "msedge") {
			args = append(args, "--edge-kiosk-type=fullscreen")
		}
		return append(args, url)
	}
	return append(args, "--app="+url, "--window-size=800,600", "--window-position=60,60")
}

var (
	exitTypeRe = regexp.MustCompile(`"exit_type":\s*"[^"]*"`)
	cleanRe    = regexp.MustCompile(`"exited_cleanly":\s*false`)
)

// fixProfile marks the last session as cleanly closed so Chromium never shows
// a "restore pages?" bubble after a power cut.
func (k *Kiosk) fixProfile() {
	if k.family != "chromium" {
		return
	}
	p := filepath.Join(k.profileDir, "Default", "Preferences")
	b, err := os.ReadFile(p)
	if err != nil {
		return
	}
	s := exitTypeRe.ReplaceAllString(string(b), `"exit_type":"Normal"`)
	s = cleanRe.ReplaceAllString(s, `"exited_cleanly":true`)
	if s != string(b) {
		_ = os.WriteFile(p, []byte(s), 0o600)
	}
}

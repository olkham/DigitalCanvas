// Package monitor controls the physical display: power and brightness over
// DDC/CI (pure Go on Linux and Windows), with command line fallbacks.
package monitor

import (
	"errors"
	"log"
	"os/exec"
	"runtime"
	"strings"
	"sync"

	"github.com/olkham/DigitalCanvas/internal/sysinfo"
)

// VCP codes (MCCS).
const (
	vcpBrightness = 0x10
	vcpContrast   = 0x12
	vcpPower      = 0xD6
	powerOn       = 0x01
	powerOffSoft  = 0x04 // the original mapped "off" to off_soft
)

// ErrUnavailable is returned when no controllable monitor was found.
var ErrUnavailable = errors.New("no DDC/CI capable monitor found")

// ddc is a platform DDC/CI backend.
type ddc interface {
	Name() string
	GetVCP(code byte) (cur, max uint16, err error)
	SetVCP(code byte, value uint16) error
	Close()
}

// Commands returns user configured power commands (may be empty).
type Commands func() (on, off string)

// Manager serialises access to the monitor (DDC/CI is slow and stateful).
type Manager struct {
	mu        sync.Mutex
	dev       ddc
	commands  Commands
	powerOn   bool
	simulated bool
}

// New probes for a DDC/CI monitor. With simulate set, nothing is touched.
func New(simulate bool, cmds Commands) *Manager {
	m := &Manager{commands: cmds, powerOn: true, simulated: simulate}
	if simulate {
		log.Printf("monitor: simulation mode, hardware control disabled")
		return m
	}
	dev, err := openDDC()
	if err != nil {
		log.Printf("monitor: DDC/CI unavailable (%v); power falls back to commands/blanking", err)
		return m
	}
	m.dev = dev
	log.Printf("monitor: DDC/CI monitor %q", dev.Name())
	if cur, _, err := dev.GetVCP(vcpPower); err == nil {
		m.powerOn = cur == powerOn
	}
	return m
}

// Available reports whether DDC/CI control works.
func (m *Manager) Available() bool { return m.dev != nil }

// Name is the monitor model (from EDID) or "".
func (m *Manager) Name() string {
	if m.dev == nil {
		return ""
	}
	return m.dev.Name()
}

// PowerOn reports the last known power state.
func (m *Manager) PowerOn() bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.powerOn
}

// SetPower switches the display on or off via DDC/CI and/or the configured
// (or auto-detected) commands.
func (m *Manager) SetPower(on bool) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.powerOn = on
	if m.simulated {
		return nil
	}
	var ddcErr error
	if m.dev != nil {
		v := uint16(powerOffSoft)
		if on {
			v = powerOn
		}
		ddcErr = m.dev.SetVCP(vcpPower, v)
		if ddcErr == nil {
			return nil
		}
		log.Printf("monitor: DDC power command failed: %v", ddcErr)
	}
	onCmd, offCmd := "", ""
	if m.commands != nil {
		onCmd, offCmd = m.commands()
	}
	cmd := offCmd
	if on {
		cmd = onCmd
	}
	if strings.TrimSpace(cmd) == "" {
		cmd = autoPowerCommand(on)
	}
	if cmd == "" {
		if ddcErr != nil {
			return ddcErr
		}
		return ErrUnavailable
	}
	return runShell(cmd)
}

// Brightness returns the current brightness, or -1 when unavailable.
func (m *Manager) Brightness() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.dev == nil {
		return -1
	}
	cur, _, err := m.dev.GetVCP(vcpBrightness)
	if err != nil {
		return -1
	}
	return int(cur)
}

// SetBrightness sets the luminance (normally 0-100).
func (m *Manager) SetBrightness(v int) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.simulated {
		return nil
	}
	if m.dev == nil {
		return ErrUnavailable
	}
	return m.dev.SetVCP(vcpBrightness, uint16(max(0, min(100, v))))
}

// Contrast returns the current contrast, or -1.
func (m *Manager) Contrast() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.dev == nil {
		return -1
	}
	cur, _, err := m.dev.GetVCP(vcpContrast)
	if err != nil {
		return -1
	}
	return int(cur)
}

// SetContrast sets the contrast (normally 0-100).
func (m *Manager) SetContrast(v int) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.dev == nil {
		return ErrUnavailable
	}
	return m.dev.SetVCP(vcpContrast, uint16(max(0, min(100, v))))
}

// Close releases the device.
func (m *Manager) Close() {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.dev != nil {
		m.dev.Close()
	}
}

func runShell(cmd string) error {
	var c *exec.Cmd
	if runtime.GOOS == "windows" {
		c = exec.Command("cmd", "/C", cmd)
	} else {
		c = exec.Command("/bin/sh", "-c", cmd)
		c.Env = sysinfo.DisplayEnv()
	}
	out, err := c.CombinedOutput()
	if err != nil {
		log.Printf("monitor: %q failed: %v %s", cmd, err, strings.TrimSpace(string(out)))
	}
	return err
}

// autoPowerCommand picks a sensible screen power command on Linux desktops
// when DDC/CI is not available (e.g. official Pi touch screens).
func autoPowerCommand(on bool) string {
	if runtime.GOOS != "linux" {
		return ""
	}
	env := sysinfo.DisplayEnv()
	has := func(k string) bool {
		for _, e := range env {
			if strings.HasPrefix(e, k+"=") && len(e) > len(k)+1 {
				return true
			}
		}
		return false
	}
	if has("WAYLAND_DISPLAY") {
		if _, err := exec.LookPath("wlr-randr"); err == nil {
			c := exec.Command("wlr-randr")
			c.Env = env
			out, err := c.Output()
			if err == nil {
				var parts []string
				for _, line := range strings.Split(string(out), "\n") {
					if line != "" && line[0] != ' ' && line[0] != '\t' {
						name := strings.Fields(line)[0]
						flag := "--off"
						if on {
							flag = "--on"
						}
						parts = append(parts, "wlr-randr --output "+name+" "+flag)
					}
				}
				if len(parts) > 0 {
					return strings.Join(parts, " ; ")
				}
			}
		}
	}
	if has("DISPLAY") {
		if _, err := exec.LookPath("xset"); err == nil {
			if on {
				return "xset dpms force on && xset s reset"
			}
			return "xset dpms force off"
		}
	}
	if _, err := exec.LookPath("vcgencmd"); err == nil {
		if on {
			return "vcgencmd display_power 1"
		}
		return "vcgencmd display_power 0"
	}
	return ""
}

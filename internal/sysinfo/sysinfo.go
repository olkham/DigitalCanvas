// Package sysinfo answers questions about the host: identity, network
// addresses, Raspberry Pi detection, resource use and power actions.
package sysinfo

import (
	"crypto/sha256"
	"encoding/base64"
	"fmt"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"sync"
)

var (
	modelOnce sync.Once
	model     string
)

// Model returns the device tree model (e.g. "Raspberry Pi 4 Model B Rev 1.4").
func Model() string {
	modelOnce.Do(func() {
		if b, err := os.ReadFile("/proc/device-tree/model"); err == nil {
			model = strings.TrimRight(string(b), "\x00\n ")
		}
	})
	return model
}

// IsRaspberryPi reports whether we run on a Raspberry Pi.
func IsRaspberryPi() bool { return strings.Contains(strings.ToLower(Model()), "raspberry pi") }

// Platform is a human readable platform description.
func Platform() string {
	if m := Model(); m != "" {
		return m
	}
	return runtime.GOOS + "/" + runtime.GOARCH
}

var (
	idOnce sync.Once
	id     string
)

// DeviceID is a short, stable identifier derived from the hardware/OS id
// (sha256 -> urlsafe base64 -> 16 chars, as the original implementation).
func DeviceID() string {
	idOnce.Do(func() {
		raw := systemUUID()
		if raw == "" {
			h, _ := os.Hostname()
			raw = h
		}
		sum := sha256.Sum256([]byte(raw))
		id = base64.URLEncoding.EncodeToString(sum[:])[:16]
	})
	return id
}

func systemUUID() string {
	if IsRaspberryPi() {
		if b, err := os.ReadFile("/proc/cpuinfo"); err == nil {
			for _, line := range strings.Split(string(b), "\n") {
				if k, v, ok := strings.Cut(line, ":"); ok && strings.TrimSpace(k) == "Serial" {
					return strings.TrimSpace(v)
				}
			}
		}
	}
	for _, p := range []string{"/sys/class/dmi/id/product_uuid", "/etc/machine-id", "/var/lib/dbus/machine-id"} {
		if b, err := os.ReadFile(p); err == nil {
			if s := strings.TrimSpace(string(b)); s != "" {
				return s
			}
		}
	}
	if runtime.GOOS == "windows" {
		out, err := exec.Command("reg", "query", `HKLM\SOFTWARE\Microsoft\Cryptography`, "/v", "MachineGuid").Output()
		if err == nil {
			f := strings.Fields(string(out))
			if len(f) > 0 {
				return f[len(f)-1]
			}
		}
	}
	return ""
}

// LocalIPv4s returns the non-loopback IPv4 addresses, most likely LAN first.
func LocalIPv4s() []string {
	var out []string
	ifaces, _ := net.Interfaces()
	for _, ifc := range ifaces {
		if ifc.Flags&net.FlagUp == 0 || ifc.Flags&net.FlagLoopback != 0 {
			continue
		}
		n := strings.ToLower(ifc.Name)
		if strings.HasPrefix(n, "docker") || strings.HasPrefix(n, "veth") || strings.HasPrefix(n, "br-") || strings.Contains(n, "vethernet") {
			continue
		}
		addrs, _ := ifc.Addrs()
		for _, a := range addrs {
			ipn, ok := a.(*net.IPNet)
			if !ok {
				continue
			}
			if ip4 := ipn.IP.To4(); ip4 != nil && !ip4.IsLinkLocalUnicast() {
				out = append(out, ip4.String())
			}
		}
	}
	sort.SliceStable(out, func(i, j int) bool { return lanScore(out[i]) > lanScore(out[j]) })
	return out
}

func lanScore(ip string) int {
	switch {
	case strings.HasPrefix(ip, "192.168."):
		return 3
	case strings.HasPrefix(ip, "10."):
		return 2
	case strings.HasPrefix(ip, "172."):
		return 1
	}
	return 0
}

// Hostname returns the host name.
func Hostname() string {
	h, _ := os.Hostname()
	return h
}

// CPUTemp returns the SoC temperature in °C, or 0 when unknown.
func CPUTemp() float64 {
	b, err := os.ReadFile("/sys/class/thermal/thermal_zone0/temp")
	if err != nil {
		return 0
	}
	v, err := strconv.ParseFloat(strings.TrimSpace(string(b)), 64)
	if err != nil {
		return 0
	}
	return v / 1000
}

// RSS returns this process' resident memory in bytes (0 when unknown).
func RSS() uint64 {
	b, err := os.ReadFile("/proc/self/status")
	if err != nil {
		return rssFallback()
	}
	for _, line := range strings.Split(string(b), "\n") {
		if strings.HasPrefix(line, "VmRSS:") {
			f := strings.Fields(line)
			if len(f) >= 2 {
				kb, _ := strconv.ParseUint(f[1], 10, 64)
				return kb * 1024
			}
		}
	}
	return 0
}

// Reboot restarts the machine. As in the original, only on a Raspberry Pi.
func Reboot() error { return power("reboot") }

// Shutdown powers the machine off. As in the original, only on a Raspberry Pi.
func Shutdown() error { return power("shutdown") }

// PowerControlSupported reports whether Reboot/Shutdown do anything.
func PowerControlSupported() bool { return IsRaspberryPi() }

func power(action string) error {
	if !PowerControlSupported() {
		return fmt.Errorf("%s is only supported on a Raspberry Pi", action)
	}
	args := []string{"-n", "shutdown", "-h", "now"}
	if action == "reboot" {
		args = []string{"-n", "reboot"}
	}
	return exec.Command("sudo", args...).Start()
}

// DisplayEnv returns the environment for launching GUI programs. When started
// from a system service the graphical session variables are missing, so the
// Wayland/X11 sockets of the current user are discovered.
func DisplayEnv() []string {
	env := os.Environ()
	if runtime.GOOS != "linux" {
		return env
	}
	get := func(k string) string {
		for _, e := range env {
			if strings.HasPrefix(e, k+"=") {
				return e[len(k)+1:]
			}
		}
		return ""
	}
	if get("WAYLAND_DISPLAY") != "" || get("DISPLAY") != "" {
		return env
	}
	rt := get("XDG_RUNTIME_DIR")
	if rt == "" {
		rt = fmt.Sprintf("/run/user/%d", os.Getuid())
		env = append(env, "XDG_RUNTIME_DIR="+rt)
	}
	if socks, _ := filepath.Glob(filepath.Join(rt, "wayland-[0-9]")); len(socks) > 0 {
		env = append(env, "WAYLAND_DISPLAY="+filepath.Base(socks[0]))
	}
	if _, err := os.Stat("/tmp/.X11-unix/X0"); err == nil {
		env = append(env, "DISPLAY=:0")
		if home, err := os.UserHomeDir(); err == nil {
			if _, err := os.Stat(filepath.Join(home, ".Xauthority")); err == nil && get("XAUTHORITY") == "" {
				env = append(env, "XAUTHORITY="+filepath.Join(home, ".Xauthority"))
			}
		}
	}
	return env
}

// HasDisplay reports whether a graphical session is reachable.
func HasDisplay() bool {
	if runtime.GOOS != "linux" {
		return true
	}
	for _, e := range DisplayEnv() {
		if (strings.HasPrefix(e, "WAYLAND_DISPLAY=") || strings.HasPrefix(e, "DISPLAY=")) && !strings.HasSuffix(e, "=") {
			return true
		}
	}
	return false
}

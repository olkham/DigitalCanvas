//go:build linux

package monitor

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"syscall"
	"time"
)

const (
	i2cSlave  = 0x0703
	ddcAddr   = 0x37
	edidAddr  = 0x50
	hostAddr  = 0x51
	dispWrite = 0x6E
	hostRead  = 0x50
)

// linuxDDC talks DDC/CI over /dev/i2c-N (HDMI DDC buses are exposed as
// i2c adapters by the DRM driver; on a Pi 4/5 these are /dev/i2c-20..22).
type linuxDDC struct {
	mu   sync.Mutex
	f    *os.File
	path string
	name string
	last time.Time
}

func openDDC() (ddc, error) {
	paths, _ := filepath.Glob("/dev/i2c-*")
	sort.Slice(paths, func(i, j int) bool {
		return len(paths[i]) > len(paths[j]) || (len(paths[i]) == len(paths[j]) && paths[i] > paths[j])
	})
	var lastErr error = ErrUnavailable
	for _, p := range paths {
		f, err := os.OpenFile(p, os.O_RDWR, 0)
		if err != nil {
			lastErr = err
			continue
		}
		name, ok := readEDIDName(f)
		if !ok {
			f.Close()
			continue
		}
		d := &linuxDDC{f: f, path: p, name: name}
		if _, _, err := d.GetVCP(vcpBrightness); err != nil {
			if _, _, err2 := d.GetVCP(vcpPower); err2 != nil {
				lastErr = fmt.Errorf("%s: monitor %q does not answer DDC/CI: %v", p, name, err)
				f.Close()
				continue
			}
		}
		return d, nil
	}
	return nil, lastErr
}

func setSlave(f *os.File, addr int) error {
	_, _, e := syscall.Syscall(syscall.SYS_IOCTL, f.Fd(), i2cSlave, uintptr(addr))
	if e != 0 {
		return e
	}
	return nil
}

func readEDIDName(f *os.File) (string, bool) {
	if err := setSlave(f, edidAddr); err != nil {
		return "", false
	}
	if _, err := f.Write([]byte{0}); err != nil {
		return "", false
	}
	edid := make([]byte, 128)
	if _, err := f.Read(edid); err != nil {
		return "", false
	}
	if string(edid[:8]) != "\x00\xff\xff\xff\xff\xff\xff\x00" {
		return "", false
	}
	for _, off := range []int{54, 72, 90, 108} {
		d := edid[off : off+18]
		if d[0] == 0 && d[1] == 0 && d[3] == 0xFC {
			return strings.TrimSpace(strings.SplitN(string(d[5:]), "\n", 2)[0]), true
		}
	}
	return "monitor", true
}

func (d *linuxDDC) Name() string { return d.name }

func (d *linuxDDC) Close() { d.f.Close() }

// pace keeps the 50ms minimum gap between DDC/CI messages.
func (d *linuxDDC) pace() {
	if w := 50*time.Millisecond - time.Since(d.last); w > 0 {
		time.Sleep(w)
	}
}

func (d *linuxDDC) write(data []byte) error {
	msg := make([]byte, 0, len(data)+3)
	msg = append(msg, hostAddr, 0x80|byte(len(data)))
	msg = append(msg, data...)
	chk := byte(dispWrite)
	for _, b := range msg {
		chk ^= b
	}
	msg = append(msg, chk)
	if err := setSlave(d.f, ddcAddr); err != nil {
		return err
	}
	d.pace()
	_, err := d.f.Write(msg)
	d.last = time.Now()
	return err
}

func (d *linuxDDC) GetVCP(code byte) (uint16, uint16, error) {
	d.mu.Lock()
	defer d.mu.Unlock()
	var lastErr error
	for attempt := 0; attempt < 3; attempt++ {
		if err := d.write([]byte{0x01, code}); err != nil {
			lastErr = err
			continue
		}
		time.Sleep(45 * time.Millisecond)
		buf := make([]byte, 11)
		_, err := d.f.Read(buf)
		d.last = time.Now()
		if err != nil {
			lastErr = err
			continue
		}
		chk := byte(hostRead)
		for _, b := range buf[:10] {
			chk ^= b
		}
		if buf[2] != 0x02 || buf[4] != code || chk != buf[10] {
			lastErr = errors.New("invalid DDC/CI reply")
			continue
		}
		if buf[3] != 0 {
			return 0, 0, fmt.Errorf("monitor does not support VCP 0x%02X", code)
		}
		return uint16(buf[8])<<8 | uint16(buf[9]), uint16(buf[6])<<8 | uint16(buf[7]), nil
	}
	return 0, 0, lastErr
}

func (d *linuxDDC) SetVCP(code byte, value uint16) error {
	d.mu.Lock()
	defer d.mu.Unlock()
	var err error
	for attempt := 0; attempt < 3; attempt++ {
		if err = d.write([]byte{0x03, code, byte(value >> 8), byte(value)}); err == nil {
			return nil
		}
		time.Sleep(50 * time.Millisecond)
	}
	return err
}

//go:build linux

package sensors

import (
	"fmt"
	"os"
	"syscall"
	"unsafe"
)

const (
	ioctlI2CRdwr = 0x0707
	i2cMRd       = 0x0001
)

// i2cMsg mirrors struct i2c_msg. buf is a typed pointer so the garbage
// collector and stack copier know about it.
type i2cMsg struct {
	addr  uint16
	flags uint16
	len   uint16
	_     uint16
	buf   *byte
}

type i2cRdwrData struct {
	msgs  *i2cMsg
	nmsgs uint32
}

type linuxBus struct{ f *os.File }

func openBus(n int) (bus, error) {
	f, err := os.OpenFile(fmt.Sprintf("/dev/i2c-%d", n), os.O_RDWR, 0)
	if err != nil {
		return nil, err
	}
	return &linuxBus{f: f}, nil
}

func (b *linuxBus) transfer(msgs []i2cMsg) error {
	data := i2cRdwrData{msgs: &msgs[0], nmsgs: uint32(len(msgs))}
	_, _, e := syscall.Syscall(syscall.SYS_IOCTL, b.f.Fd(), ioctlI2CRdwr, uintptr(unsafe.Pointer(&data)))
	if e != 0 {
		return e
	}
	return nil
}

func (b *linuxBus) WriteRead(addr uint16, w, r []byte) error {
	msgs := []i2cMsg{
		{addr: addr, len: uint16(len(w)), buf: &w[0]},
		{addr: addr, flags: i2cMRd, len: uint16(len(r)), buf: &r[0]},
	}
	return b.transfer(msgs)
}

func (b *linuxBus) Write(addr uint16, w []byte) error {
	return b.transfer([]i2cMsg{{addr: addr, len: uint16(len(w)), buf: &w[0]}})
}

func (b *linuxBus) Close() error { return b.f.Close() }

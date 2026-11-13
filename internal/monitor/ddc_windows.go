//go:build windows

package monitor

import (
	"errors"
	"fmt"
	"syscall"
	"unsafe"
)

var (
	user32  = syscall.NewLazyDLL("user32.dll")
	dxva2   = syscall.NewLazyDLL("dxva2.dll")
	pEnum   = user32.NewProc("EnumDisplayMonitors")
	pNum    = dxva2.NewProc("GetNumberOfPhysicalMonitorsFromHMONITOR")
	pGet    = dxva2.NewProc("GetPhysicalMonitorsFromHMONITOR")
	pDestr  = dxva2.NewProc("DestroyPhysicalMonitors")
	pGetVCP = dxva2.NewProc("GetVCPFeatureAndVCPFeatureReply")
	pSetVCP = dxva2.NewProc("SetVCPFeature")
)

// physicalMonitor mirrors PHYSICAL_MONITOR (declared with pack(1)).
type physicalMonitor struct {
	Handle      syscall.Handle
	Description [128]uint16
}

// winDDC uses the Monitor Configuration API (dxva2), the same API the
// original Python monitorcontrol package used on Windows.
type winDDC struct {
	mons []physicalMonitor
	name string
}

func openDDC() (ddc, error) {
	if err := dxva2.Load(); err != nil {
		return nil, err
	}
	var hmons []uintptr
	cb := syscall.NewCallback(func(hmon, hdc, rect, data uintptr) uintptr {
		hmons = append(hmons, hmon)
		return 1
	})
	if r, _, err := pEnum.Call(0, 0, cb, 0); r == 0 {
		return nil, fmt.Errorf("EnumDisplayMonitors: %v", err)
	}
	d := &winDDC{}
	for _, h := range hmons {
		var n uint32
		if r, _, _ := pNum.Call(h, uintptr(unsafe.Pointer(&n))); r == 0 || n == 0 {
			continue
		}
		arr := make([]physicalMonitor, n)
		if r, _, _ := pGet.Call(h, uintptr(n), uintptr(unsafe.Pointer(&arr[0]))); r == 0 {
			continue
		}
		for _, pm := range arr {
			var cur, mx, typ uint32
			r, _, _ := pGetVCP.Call(uintptr(pm.Handle), vcpBrightness,
				uintptr(unsafe.Pointer(&typ)), uintptr(unsafe.Pointer(&cur)), uintptr(unsafe.Pointer(&mx)))
			if r == 0 {
				pDestr.Call(1, uintptr(unsafe.Pointer(&pm)))
				continue
			}
			d.mons = append(d.mons, pm)
			if d.name == "" {
				d.name = syscall.UTF16ToString(pm.Description[:])
			}
		}
	}
	if len(d.mons) == 0 {
		return nil, ErrUnavailable
	}
	return d, nil
}

func (d *winDDC) Name() string { return d.name }

func (d *winDDC) Close() {
	if len(d.mons) > 0 {
		pDestr.Call(uintptr(len(d.mons)), uintptr(unsafe.Pointer(&d.mons[0])))
		d.mons = nil
	}
}

func (d *winDDC) GetVCP(code byte) (uint16, uint16, error) {
	for _, pm := range d.mons {
		var cur, mx, typ uint32
		r, _, err := pGetVCP.Call(uintptr(pm.Handle), uintptr(code),
			uintptr(unsafe.Pointer(&typ)), uintptr(unsafe.Pointer(&cur)), uintptr(unsafe.Pointer(&mx)))
		if r != 0 {
			return uint16(cur), uint16(mx), nil
		}
		return 0, 0, fmt.Errorf("GetVCPFeature 0x%02X: %v", code, err)
	}
	return 0, 0, ErrUnavailable
}

// SetVCP applies the value to every attached physical monitor.
func (d *winDDC) SetVCP(code byte, value uint16) error {
	var firstErr error
	for _, pm := range d.mons {
		if r, _, err := pSetVCP.Call(uintptr(pm.Handle), uintptr(code), uintptr(value)); r == 0 && firstErr == nil {
			firstErr = fmt.Errorf("SetVCPFeature 0x%02X: %v", code, err)
		}
	}
	if len(d.mons) == 0 {
		return errors.New("no monitors")
	}
	return firstErr
}

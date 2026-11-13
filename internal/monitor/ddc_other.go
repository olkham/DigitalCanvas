//go:build !linux && !windows

package monitor

func openDDC() (ddc, error) { return nil, ErrUnavailable }

//go:build !linux

package sensors

func openBus(n int) (bus, error) { return nil, ErrUnavailable }

//go:build !windows

package main

import (
	"os"
	"syscall"
)

// restartSelf replaces the process image, keeping the PID (systemd friendly).
func restartSelf() error {
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	return syscall.Exec(exe, os.Args, os.Environ())
}

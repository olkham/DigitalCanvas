//go:build !windows

package kiosk

import (
	"os/exec"
	"syscall"
	"time"
)

// prepare puts the browser in its own process group so the whole tree
// (renderer, GPU process, ...) can be signalled at once.
func prepare(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
}

func terminate(cmd *exec.Cmd) {
	pid := cmd.Process.Pid
	_ = syscall.Kill(-pid, syscall.SIGTERM)
	go func() {
		time.Sleep(4 * time.Second)
		_ = syscall.Kill(-pid, syscall.SIGKILL)
	}()
}

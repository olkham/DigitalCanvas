//go:build windows

package kiosk

import (
	"os/exec"
	"strconv"
	"syscall"
)

func prepare(cmd *exec.Cmd) {}

// terminate kills the browser and its child processes.
func terminate(cmd *exec.Cmd) {
	k := exec.Command("taskkill", "/T", "/F", "/PID", strconv.Itoa(cmd.Process.Pid))
	k.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	if err := k.Run(); err != nil {
		_ = cmd.Process.Kill()
	}
}

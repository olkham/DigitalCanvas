//go:build windows

package media

import (
	"os/exec"
	"syscall"
)

const (
	createNoWindow           = 0x08000000
	belowNormalPriorityClass = 0x00004000
)

func configureCmd(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{
		HideWindow:    true,
		CreationFlags: createNoWindow | belowNormalPriorityClass,
	}
}

func lowerPriority(pid int) {}

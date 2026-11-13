//go:build !windows

package media

import (
	"os/exec"
	"syscall"
)

func configureCmd(cmd *exec.Cmd) {}

// lowerPriority renices a helper process so imports never starve the display.
func lowerPriority(pid int) {
	_ = syscall.Setpriority(syscall.PRIO_PROCESS, pid, 15)
}

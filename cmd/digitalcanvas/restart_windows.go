//go:build windows

package main

import (
	"os"
	"os/exec"
)

// restartSelf starts a fresh copy of the program and lets this one exit.
func restartSelf() error {
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	cmd := exec.Command(exe, os.Args[1:]...)
	cmd.Stdout, cmd.Stderr, cmd.Stdin = os.Stdout, os.Stderr, os.Stdin
	return cmd.Start()
}

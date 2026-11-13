//go:build !windows

package sysinfo

func rssFallback() uint64 { return 0 }

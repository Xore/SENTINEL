//go:build !windows

package main

import (
	"os"
	"syscall"
)

// reexec replaces the current process image with the (freshly swapped) binary at
// path, preserving args and environment. On success it never returns.
func reexec(path string) {
	_ = syscall.Exec(path, os.Args, os.Environ())
}

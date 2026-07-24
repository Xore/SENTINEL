//go:build windows

package main

// Windows has no execve; the caller handles the update by exiting so the service
// manager restarts into the swapped binary. This stub should not be reached on
// Windows, but exists so the package builds for GOOS=windows.
func reexec(path string) {}

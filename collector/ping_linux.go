//go:build !windows

package main

import (
	"os/exec"
	"regexp"
	"strconv"
)

// Matches "time=1.23 ms" (Linux/macOS) and "time<1 ms".
var pingRTT = regexp.MustCompile(`time[=<]([0-9.]+)`)

// pingHost sends a single ICMP echo via the system ping - no raw-socket privilege
// required. Unix flags: -c count, -W timeout (seconds). A non-zero exit reliably
// means unreachable, so the exit status is our up/down signal.
func pingHost(addr string) (bool, float64) {
	out, err := exec.Command("ping", "-c", "1", "-W", "2", addr).Output()
	if err != nil {
		return false, 0
	}
	m := pingRTT.FindStringSubmatch(string(out))
	if m == nil {
		return true, 0
	}
	rtt, _ := strconv.ParseFloat(m[1], 64)
	return true, rtt
}

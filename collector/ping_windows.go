//go:build windows

package main

import (
	"os/exec"
	"regexp"
	"strconv"
)

// Windows ping reports "time=1ms" / "time<1ms" (integer milliseconds).
var pingRTT = regexp.MustCompile(`time[=<]([0-9]+)`)

// A genuine echo reply always carries "TTL=". Windows ping exits 0 even for
// "Request timed out" / "Destination host unreachable", so the exit code is NOT
// trustworthy - require the TTL marker to call the host up.
var pingReply = regexp.MustCompile(`TTL=\d+`)

// pingHost sends a single ICMP echo via the system ping. Windows flags: -n count,
// -w timeout (milliseconds).
func pingHost(addr string) (bool, float64) {
	out, _ := exec.Command("ping", "-n", "1", "-w", "2000", addr).Output()
	s := string(out)
	if !pingReply.MatchString(s) {
		return false, 0
	}
	m := pingRTT.FindStringSubmatch(s)
	if m == nil {
		return true, 0
	}
	rtt, _ := strconv.ParseFloat(m[1], 64)
	return true, rtt
}

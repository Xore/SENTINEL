package main

// Operator-configured active checks, run by the collector so a remote node
// exercises the SAME probes a standalone node does - custom hosts, services
// (DNS/HTTP/TCP/NTP health) and custom ports - from the same central config.
//
// The plan is pulled from the aggregator (/api/ingest/checks); only enabled and
// started items are sent. Everything here is stdlib and cross-platform EXCEPT
// host reachability, which shells out to the system ping (its flags differ per
// OS) via pingHost in ping_linux.go / ping_windows.go.

import (
	"context"
	"encoding/binary"
	"fmt"
	"net"
	"net/http"
	"strconv"
	"strings"
	"time"
)

type checkPlan struct {
	Targets  []targetCheck  `json:"targets"`
	Services []serviceCheck `json:"services"`
	Ports    []portCheck    `json:"ports"`
}
type targetCheck struct {
	Name    string `json:"name"`
	Address string `json:"address"`
	Group   string `json:"group"`
}
type serviceCheck struct {
	Name   string `json:"name"`
	Kind   string `json:"kind"`
	Target string `json:"target"`
}
type portCheck struct {
	Name   string `json:"name"`
	Host   string `json:"host"`
	Port   int    `json:"port"`
	Proto  string `json:"proto"`
	Send   string `json:"send"`
	Expect string `json:"expect"`
}

// runTargets pings each reachability target. pingHost is platform-branched.
func runTargets(plan checkPlan, ts float64) []map[string]any {
	rows := []map[string]any{}
	for _, t := range plan.Targets {
		if t.Address == "" {
			continue
		}
		up, rtt := pingHost(t.Address)
		row := map[string]any{"name": t.Name, "address": t.Address,
			"group": t.Group, "up": up, "ts": ts}
		if up {
			row["rtt_ms"] = rtt
		}
		rows = append(rows, row)
	}
	return rows
}

// runServices exercises each configured service and reports ok + a short detail.
func runServices(plan checkPlan, ts float64) []map[string]any {
	rows := []map[string]any{}
	for _, s := range plan.Services {
		var ok bool
		var detail string
		switch s.Kind {
		case "dns":
			ok, detail = checkDNS(s.Target)
		case "http":
			ok, detail = checkHTTP(s.Target)
		case "tcp":
			ok, detail = checkTCP(s.Target)
		case "ntp":
			ok, detail = checkNTP(s.Target)
		default:
			detail = "unknown kind " + s.Kind
		}
		rows = append(rows, map[string]any{"name": s.Name, "kind": s.Kind,
			"target": s.Target, "ok": ok, "detail": detail, "ts": ts})
	}
	return rows
}

// runPorts opens each configured port, optionally sending a probe and matching a
// substring in the reply.
func runPorts(plan checkPlan, ts float64) []map[string]any {
	rows := []map[string]any{}
	for _, p := range plan.Ports {
		proto := strings.ToLower(p.Proto)
		if proto != "udp" {
			proto = "tcp"
		}
		addr := net.JoinHostPort(p.Host, strconv.Itoa(p.Port))
		open, matched := false, false
		if c, err := net.DialTimeout(proto, addr, 5*time.Second); err == nil {
			open = true
			if p.Send != "" {
				c.SetDeadline(time.Now().Add(3 * time.Second))
				_, _ = c.Write([]byte(p.Send))
			}
			if p.Expect != "" {
				c.SetDeadline(time.Now().Add(3 * time.Second))
				buf := make([]byte, 2048)
				n, _ := c.Read(buf)
				matched = strings.Contains(string(buf[:n]), p.Expect)
			}
			_ = c.Close()
		}
		row := map[string]any{"name": p.Name, "host": p.Host, "port": p.Port,
			"proto": proto, "open": open, "ts": ts}
		if p.Expect != "" {
			row["matched"] = matched
		}
		rows = append(rows, row)
	}
	return rows
}

func checkDNS(host string) (bool, string) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	addrs, err := (&net.Resolver{}).LookupHost(ctx, host)
	if err != nil {
		return false, err.Error()
	}
	return true, strings.Join(addrs, ",")
}

func checkHTTP(target string) (bool, string) {
	if !strings.Contains(target, "://") {
		target = "http://" + target
	}
	resp, err := (&http.Client{Timeout: 8 * time.Second}).Get(target)
	if err != nil {
		return false, err.Error()
	}
	defer resp.Body.Close()
	return resp.StatusCode < 400, fmt.Sprintf("HTTP %d", resp.StatusCode)
}

func checkTCP(target string) (bool, string) {
	c, err := net.DialTimeout("tcp", target, 5*time.Second)
	if err != nil {
		return false, err.Error()
	}
	_ = c.Close()
	return true, "connected"
}

// checkNTP sends a minimal SNTP request and reports the server's clock offset.
func checkNTP(target string) (bool, string) {
	if !strings.Contains(target, ":") {
		target += ":123"
	}
	c, err := net.DialTimeout("udp", target, 5*time.Second)
	if err != nil {
		return false, err.Error()
	}
	defer c.Close()
	_ = c.SetDeadline(time.Now().Add(5 * time.Second))
	req := make([]byte, 48)
	req[0] = 0x1B // LI=0, VN=3, Mode=3 (client)
	if _, err := c.Write(req); err != nil {
		return false, err.Error()
	}
	resp := make([]byte, 48)
	if _, err := c.Read(resp); err != nil {
		return false, err.Error()
	}
	// Transmit timestamp seconds live at bytes 40-43, counted from 1900.
	const ntpUnixDelta = 2208988800
	serverUnix := float64(binary.BigEndian.Uint32(resp[40:44])) - ntpUnixDelta
	offset := serverUnix - float64(time.Now().Unix())
	return true, fmt.Sprintf("offset %.1fs", offset)
}

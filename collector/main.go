// Network Probe - collector node agent (Go).
//
// A *collector* is a slim node: no local dashboard or backend, only this agent.
// It periodically gathers a few passive, read-only signals from the box it runs
// on and PUSHES them to a configured aggregator (a standalone node) over HTTP.
// Transport is push, so a collector needs no inbound ports and works from behind
// NAT.
//
// Written in Go with the standard library only, so it compiles to a single
// static binary with no runtime to install. Cross-compiles to Linux and Windows
// (see scripts/build-collector.sh). Interface enumeration uses net.Interfaces()
// which is cross-platform; the neighbour table falls back to the OS tool.
//
// Config ($PROBE_COLLECTOR_CONFIG, else an OS default path):
//
//	{
//	  "aggregator_url": "http://192.168.50.32:8088",
//	  "collector_id":   "col-abcd1234",   // optional; the key identifies us
//	  "ingest_key":     "<key shown once at enrollment>",
//	  "interval":       30,                // seconds between full sample pushes
//	  "ping_interval":  10,                // seconds between lightweight pings
//	  "verify_tls":     true,              // false only for self-signed labs
//	  "update_secret":  "<hex from enrollment>" // HMAC key that authorizes updates
//	}
//
// Self-update is gated on update_secret: the agent installs a new binary only if
// the update instruction carries a valid HMAC over it AND the downloaded bytes
// match the signed SHA-256, so a binary swap cannot be forged by anyone on-path.
//
// Two cadences run independently: a fast PING (a bare heartbeat) tells the
// aggregator the collector is UP within seconds, while the slower sample push
// carries the heavier interface/neighbour payloads. If pings stop arriving the
// aggregator flips the collector to DOWN.
//
// The ingest key travels in the X-Ingest-Key header. The aggregator accepts it
// only while its accept-external-collectors switch is on and the key is enrolled
// and not revoked, so revoking the key stops this agent cold.
package main

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"crypto/tls"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"
)

const version = "0.2.0"

// Agent lifecycle status, self-reported on every ping. DOWN is never sent by the
// agent itself - the aggregator infers it when pings stop arriving (real crash,
// network partition, or a stopped service).
const (
	statusRunning  = "RUNNING"  // healthy: last cycle collected and pushed cleanly
	statusDegraded = "DEGRADED" // alive, but the last sample push errored or panicked
	statusStarting = "STARTING" // process up, no successful cycle yet
)

type config struct {
	AggregatorURL string `json:"aggregator_url"`
	CollectorID   string `json:"collector_id"`
	IngestKey     string `json:"ingest_key"`
	Interval      int    `json:"interval"`
	PingInterval  int    `json:"ping_interval"`
	VerifyTLS     *bool  `json:"verify_tls"`
	// UpdateSecret is the HMAC key shared with the aggregator at enrollment. Every
	// self-update instruction must carry a valid MAC over it, so a binary swap can
	// only ever be authorized by the backend that holds this same secret - not by
	// anyone merely on the network path. Empty => self-update is refused.
	UpdateSecret string `json:"update_secret"`
}

// agentState is the live status the ping loop reports. Guarded by a mutex because
// the sample loop writes it while the ping loop reads it.
type agentState struct {
	mu       sync.Mutex
	status   string
	detail   string
	cycles   int
	lastErr  string
	updated  time.Time
}

func (s *agentState) set(status, detail string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.status, s.detail, s.updated = status, detail, time.Now()
	if status == statusRunning {
		s.cycles++
		s.lastErr = ""
	} else if detail != "" {
		s.lastErr = detail
	}
}

func (s *agentState) snapshot() map[string]any {
	s.mu.Lock()
	defer s.mu.Unlock()
	return map[string]any{
		"status": s.status, "detail": s.detail,
		"cycles": s.cycles, "last_error": s.lastErr,
	}
}

func logf(format string, a ...any) {
	fmt.Printf("[collector] "+format+"\n", a...)
}

func defaultConfigPath() string {
	if p := os.Getenv("PROBE_COLLECTOR_CONFIG"); p != "" {
		return p
	}
	if runtime.GOOS == "windows" {
		base := os.Getenv("ProgramData")
		if base == "" {
			base = `C:\ProgramData`
		}
		return filepath.Join(base, "network-probe", "collector.json")
	}
	return "/etc/network-probe/collector.json"
}

func loadConfig() config {
	path := defaultConfigPath()
	raw, err := os.ReadFile(path)
	if err != nil {
		logf("cannot read config %s: %v", path, err)
		os.Exit(2)
	}
	var cfg config
	if err := json.Unmarshal(raw, &cfg); err != nil {
		logf("cannot parse config %s: %v", path, err)
		os.Exit(2)
	}
	if cfg.AggregatorURL == "" || cfg.IngestKey == "" {
		logf("config must set both 'aggregator_url' and 'ingest_key'")
		os.Exit(2)
	}
	if cfg.Interval <= 0 {
		cfg.Interval = 30
	}
	if cfg.PingInterval <= 0 {
		// Default: ping a few times per sample interval, capped so the DOWN
		// signal is quick, floored so we never hammer the aggregator.
		cfg.PingInterval = cfg.Interval / 3
		if cfg.PingInterval < 5 {
			cfg.PingInterval = 5
		}
		if cfg.PingInterval > cfg.Interval {
			cfg.PingInterval = cfg.Interval
		}
	}
	return cfg
}

func httpClient(cfg config) *http.Client {
	verify := cfg.VerifyTLS == nil || *cfg.VerifyTLS
	tr := &http.Transport{}
	if !verify {
		tr.TLSClientConfig = &tls.Config{InsecureSkipVerify: true}
	}
	return &http.Client{Timeout: 15 * time.Second, Transport: tr}
}

func post(client *http.Client, cfg config, path string, payload any) (map[string]any, bool) {
	body, _ := json.Marshal(payload)
	url := strings.TrimRight(cfg.AggregatorURL, "/") + path
	req, err := http.NewRequest("POST", url, bytes.NewReader(body))
	if err != nil {
		logf("POST %s build error: %v", path, err)
		return nil, false
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Ingest-Key", cfg.IngestKey)
	resp, err := client.Do(req)
	if err != nil {
		logf("POST %s failed: %v", path, err)
		return nil, false
	}
	defer resp.Body.Close()
	var out map[string]any
	json.NewDecoder(resp.Body).Decode(&out)
	if resp.StatusCode >= 300 {
		logf("POST %s -> %d %v", path, resp.StatusCode, out)
		return nil, false
	}
	return out, true
}

// --- passive, read-only collection ------------------------------------------

func nodeIP() string {
	addrs, err := net.InterfaceAddrs()
	if err != nil {
		return ""
	}
	for _, a := range addrs {
		if ipnet, ok := a.(*net.IPNet); ok && !ipnet.IP.IsLoopback() && ipnet.IP.To4() != nil {
			return ipnet.IP.String()
		}
	}
	return ""
}

func collectInterfaces() []map[string]any {
	rows := []map[string]any{}
	ifaces, err := net.Interfaces()
	if err != nil {
		return rows
	}
	for _, in := range ifaces {
		if in.Flags&net.FlagLoopback != 0 {
			continue
		}
		addrs := []string{}
		if aa, err := in.Addrs(); err == nil {
			for _, a := range aa {
				addrs = append(addrs, a.String())
			}
		}
		state := "down"
		if in.Flags&net.FlagUp != 0 {
			state = "up"
		}
		rows = append(rows, map[string]any{
			"name": in.Name, "state": state,
			"mac": in.HardwareAddr.String(), "addresses": addrs,
		})
	}
	return rows
}

// collectNeighbours reads the OS ARP/neighbour table - cheap L2/L3 discovery
// with no active scanning.
func collectNeighbours() []map[string]any {
	rows := []map[string]any{}
	if runtime.GOOS == "windows" {
		out, err := exec.Command("arp", "-a").Output()
		if err != nil {
			return rows
		}
		for _, line := range strings.Split(string(out), "\n") {
			f := strings.Fields(line)
			// 192.168.50.1   aa-bb-cc-dd-ee-ff   dynamic
			if len(f) >= 3 && net.ParseIP(f[0]) != nil && strings.Contains(f[1], "-") {
				rows = append(rows, map[string]any{
					"ip": f[0], "mac": strings.ReplaceAll(f[1], "-", ":"), "state": f[2]})
			}
		}
		return rows
	}
	out, err := exec.Command("ip", "neigh").Output()
	if err != nil {
		return rows
	}
	for _, line := range strings.Split(string(out), "\n") {
		f := strings.Fields(line)
		// 192.168.50.1 dev wlan0 lladdr aa:bb:cc:dd:ee:ff REACHABLE
		if len(f) >= 5 && f[1] == "dev" {
			mac, dev, state := "", f[2], f[len(f)-1]
			for i, tok := range f {
				if tok == "lladdr" && i+1 < len(f) {
					mac = f[i+1]
				}
			}
			if mac != "" {
				rows = append(rows, map[string]any{"ip": f[0], "dev": dev, "mac": mac, "state": state})
			}
		}
	}
	return rows
}

func hostname() string {
	h, _ := os.Hostname()
	return h
}

func withTS(rows []map[string]any, ts float64) []map[string]any {
	for _, r := range rows {
		r["ts"] = ts
	}
	return rows
}

// ping sends a lightweight heartbeat carrying the agent's self-reported status.
// It is cheap on purpose so it can run often, giving the aggregator a fast UP
// signal; missing pings are what the aggregator reads as DOWN. The heartbeat
// response may instruct the agent to self-update.
func ping(client *http.Client, cfg config, st *agentState) {
	hb := map[string]any{
		"hostname": hostname(), "node_ip": nodeIP(), "version": version,
		"status": st.snapshot(),
		"meta": map[string]any{"os": runtime.GOOS, "arch": runtime.GOARCH,
			"ts": float64(time.Now().Unix())},
	}
	resp, ok := post(client, cfg, "/api/ingest/heartbeat", hb)
	if !ok {
		return
	}
	if upd, ok := resp["update"].(map[string]any); ok {
		selfUpdate(client, cfg, st, upd)
	}
}

// versionNewer reports whether dotted-numeric version a is strictly greater than
// b (e.g. "0.2.0" > "0.1.9"). Used to refuse downgrade/rollback: an attacker who
// replays an older but validly-signed instruction still cannot push us backwards.
func versionNewer(a, b string) bool {
	pa, pb := strings.Split(a, "."), strings.Split(b, ".")
	for i := 0; i < len(pa) || i < len(pb); i++ {
		var x, y int
		if i < len(pa) {
			x, _ = strconv.Atoi(pa[i])
		}
		if i < len(pb) {
			y, _ = strconv.Atoi(pb[i])
		}
		if x != y {
			return x > y
		}
	}
	return false
}

// authorizeUpdate is the security core of self-update, split out so it can be
// unit-tested with no network or filesystem. It decides whether an update
// instruction is safe to apply and returns the target version + expected SHA-256
// to fetch, or ok=false with a human reason. goos/goarch/curVersion are passed in
// so tests can drive them; production callers pass runtime.GOOS/GOARCH + version.
// The MAC is checked over a message built from the CALLER's own platform, so a
// tampered os/arch in the response can never be substituted; layout must stay
// byte-identical to the backend's _sign_update().
func authorizeUpdate(secret, goos, goarch, curVersion string, upd map[string]any) (target, wantSHA string, ok bool, reason string) {
	target, _ = upd["version"].(string)
	sig, _ := upd["sig"].(string)
	wantSHA, _ = upd["sha256"].(string)
	if target == "" || target == curVersion {
		return "", "", false, "no newer version offered"
	}
	if secret == "" {
		return "", "", false, "no update_secret configured; re-enroll to enable signed updates"
	}
	if sig == "" || wantSHA == "" {
		return "", "", false, "instruction is unsigned"
	}
	if !versionNewer(target, curVersion) {
		return "", "", false, "not newer than current " + curVersion + " (downgrade blocked)"
	}
	msg := fmt.Sprintf("%s\n%s/%s\n%s", target, goos, goarch, wantSHA)
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(msg))
	expected := hex.EncodeToString(mac.Sum(nil))
	if !hmac.Equal([]byte(expected), []byte(sig)) {
		return "", "", false, "signature mismatch (not from the authorized backend)"
	}
	return target, wantSHA, true, ""
}

// selfUpdate applies an operator-requested update, but ONLY after cryptographically
// proving the instruction is authentic. The chain of trust:
//
//  1. The instruction carries an HMAC ("sig") over {version, os/arch, sha256} keyed
//     by the secret we share solely with the authoring backend. We reconstruct that
//     message from our OWN os/arch (never the response's) and verify the MAC. No
//     valid MAC => refuse. This is what makes a binary swap unforgeable by anyone on
//     the network path, even over plain HTTP or with TLS verification off.
//  2. We refuse anything not strictly newer than us (no downgrade/replay).
//  3. We download the binary and require its SHA-256 to equal the signed digest, so
//     even the key-authenticated download endpoint cannot hand us different bytes.
//
// Only if all three hold do we swap the binary in place and re-exec.
func selfUpdate(client *http.Client, cfg config, st *agentState, upd map[string]any) {
	target, wantSHA, ok, reason := authorizeUpdate(cfg.UpdateSecret, runtime.GOOS, runtime.GOARCH, version, upd)
	if !ok {
		// Stay quiet about the ordinary "nothing newer" case; log real rejections.
		if t, _ := upd["version"].(string); t != "" && t != version {
			logf("update to %s rejected: %s", t, reason)
			if strings.Contains(reason, "signature") {
				st.set(statusDegraded, "rejected forged update to "+t)
			}
		}
		return
	}

	logf("update to %s authenticated; downloading", target)
	st.set(statusDegraded, "updating to "+target)

	url := fmt.Sprintf("%s/api/ingest/binary?os=%s&arch=%s",
		strings.TrimRight(cfg.AggregatorURL, "/"), runtime.GOOS, runtime.GOARCH)
	req, _ := http.NewRequest("GET", url, nil)
	req.Header.Set("X-Ingest-Key", cfg.IngestKey)
	resp, err := client.Do(req)
	if err != nil {
		logf("update download failed: %v", err)
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		logf("update download HTTP %d", resp.StatusCode)
		return
	}
	data, err := io.ReadAll(resp.Body)
	if err != nil {
		logf("update read failed: %v", err)
		return
	}
	// The downloaded bytes must hash to the signed digest, or we install nothing.
	gotSHA := fmt.Sprintf("%x", sha256.Sum256(data))
	if !hmac.Equal([]byte(gotSHA), []byte(wantSHA)) {
		logf("update to %s rejected: downloaded binary sha256 %s != signed %s", target, gotSHA, wantSHA)
		st.set(statusDegraded, "update hash mismatch for "+target)
		return
	}

	exe, err := os.Executable()
	if err != nil {
		logf("cannot locate own executable: %v", err)
		return
	}
	// Write next to the current binary (same filesystem) so the rename is atomic.
	tmp := exe + ".new"
	f, err := os.OpenFile(tmp, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o755)
	if err != nil {
		logf("cannot write update temp: %v", err)
		return
	}
	if _, err := f.Write(data); err != nil {
		f.Close()
		os.Remove(tmp)
		logf("update write failed: %v", err)
		return
	}
	f.Close()

	// Windows cannot replace a running .exe in place; the service manager must
	// swap it on restart. Elsewhere, replace-then-reexec applies the update live.
	if runtime.GOOS == "windows" {
		logf("downloaded update to %s; exit for service manager to swap", tmp)
		os.Exit(0)
	}
	if err := os.Rename(tmp, exe); err != nil {
		os.Remove(tmp)
		logf("update swap failed: %v", err)
		return
	}
	logf("update applied; re-executing %s", exe)
	// reexec replaces this process image with the new binary (unix). If it ever
	// returns it failed; exit so the service manager restarts us fresh.
	reexec(exe)
	logf("re-exec returned unexpectedly; exiting for restart")
	os.Exit(0)
}

// pushSamples gathers and sends the heavier interface/neighbour payloads, and
// records the outcome in agentState so the next ping reports RUNNING or DEGRADED.
func pushSamples(client *http.Client, cfg config, st *agentState) {
	defer func() {
		if r := recover(); r != nil {
			st.set(statusDegraded, fmt.Sprintf("panic: %v", r))
			logf("sample cycle panic: %v", r)
		}
	}()
	now := float64(time.Now().Unix())
	streams := map[string][]map[string]any{
		"interfaces": withTS(collectInterfaces(), now),
		"neighbours": withTS(collectNeighbours(), now),
	}
	// Run the operator-configured checks - the SAME plan a standalone node runs -
	// pulled fresh each cycle so central edits take effect without redeploying.
	if plan, ok := fetchCheckPlan(client, cfg); ok {
		ts := float64(time.Now().Unix())
		streams["host_checks"] = runTargets(plan, ts)
		streams["service_checks"] = runServices(plan, ts)
		streams["port_checks"] = runPorts(plan, ts)
	}
	failed := ""
	for stream, rows := range streams {
		if len(rows) == 0 {
			continue
		}
		if _, ok := post(client, cfg, "/api/ingest/samples",
			map[string]any{"stream": stream, "rows": rows}); !ok {
			failed = stream
		}
	}
	if failed != "" {
		st.set(statusDegraded, "sample push failed: "+failed)
		return
	}
	st.set(statusRunning, "")
}

// fetchCheckPlan pulls this collector's active probe plan from the aggregator.
// A missing/failed fetch just means no checks this cycle (not an error).
func fetchCheckPlan(client *http.Client, cfg config) (checkPlan, bool) {
	var plan checkPlan
	url := strings.TrimRight(cfg.AggregatorURL, "/") + "/api/ingest/checks"
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return plan, false
	}
	req.Header.Set("X-Ingest-Key", cfg.IngestKey)
	resp, err := client.Do(req)
	if err != nil {
		logf("check plan fetch failed: %v", err)
		return plan, false
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return plan, false
	}
	if err := json.NewDecoder(resp.Body).Decode(&plan); err != nil {
		return plan, false
	}
	return plan, true
}

func main() {
	cfg := loadConfig()
	client := httpClient(cfg)
	st := &agentState{status: statusStarting, updated: time.Now()}
	logf("starting %s; aggregator=%s interval=%ds ping=%ds",
		version, cfg.AggregatorURL, cfg.Interval, cfg.PingInterval)

	// Announce ourselves immediately, then run the first sample push, so the
	// aggregator sees us within a ping rather than after a full interval.
	ping(client, cfg, st)
	pushSamples(client, cfg, st)
	ping(client, cfg, st)

	sampleTick := time.NewTicker(time.Duration(cfg.Interval) * time.Second)
	pingTick := time.NewTicker(time.Duration(cfg.PingInterval) * time.Second)
	defer sampleTick.Stop()
	defer pingTick.Stop()
	for {
		select {
		case <-pingTick.C:
			ping(client, cfg, st)
		case <-sampleTick.C:
			pushSamples(client, cfg, st)
		}
	}
}

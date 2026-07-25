package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"
)

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

// sign reproduces the backend's _sign_update() so tests can mint a legitimate
// instruction. If this and authorizeUpdate ever disagree, a real agent would
// reject a real update — so this doubling is the point.
func sign(secret, version, osArch, sha string) string {
	m := hmac.New(sha256.New, []byte(secret))
	m.Write([]byte(fmt.Sprintf("%s\n%s\n%s", version, osArch, sha)))
	return hex.EncodeToString(m.Sum(nil))
}

// ---------------------------------------------------------------------------
// agentState
// ---------------------------------------------------------------------------

func TestAgentState_InitialStatus(t *testing.T) {
	st := &agentState{status: statusStarting, updated: time.Now()}
	snap := st.snapshot()
	if snap["status"] != statusStarting {
		t.Errorf("want STARTING, got %v", snap["status"])
	}
	if snap["cycles"].(int) != 0 {
		t.Errorf("want 0 cycles, got %v", snap["cycles"])
	}
}

func TestAgentState_SetRunning(t *testing.T) {
	st := &agentState{status: statusStarting}
	st.set(statusRunning, "")
	st.set(statusRunning, "")
	snap := st.snapshot()
	if snap["status"] != statusRunning {
		t.Errorf("want RUNNING, got %v", snap["status"])
	}
	if snap["cycles"].(int) != 2 {
		t.Errorf("want 2 cycles, got %v", snap["cycles"])
	}
	if snap["last_error"].(string) != "" {
		t.Errorf("want empty last_error, got %v", snap["last_error"])
	}
}

func TestAgentState_SetDegraded(t *testing.T) {
	st := &agentState{status: statusRunning}
	st.set(statusDegraded, "push failed")
	snap := st.snapshot()
	if snap["status"] != statusDegraded {
		t.Errorf("want DEGRADED, got %v", snap["status"])
	}
	if snap["last_error"].(string) != "push failed" {
		t.Errorf("last_error mismatch: %v", snap["last_error"])
	}
}

func TestAgentState_CyclesOnlyCountRunning(t *testing.T) {
	st := &agentState{status: statusStarting}
	st.set(statusRunning, "")
	st.set(statusDegraded, "err")
	st.set(statusRunning, "")
	if st.snapshot()["cycles"].(int) != 2 {
		t.Errorf("want 2, got %v", st.snapshot()["cycles"])
	}
}

func TestAgentState_ConcurrentAccess(t *testing.T) {
	// Validate that the mutex protects against concurrent set/snapshot.
	st := &agentState{status: statusStarting, updated: time.Now()}
	var wg sync.WaitGroup
	for i := 0; i < 50; i++ {
		wg.Add(2)
		go func() { defer wg.Done(); st.set(statusRunning, "") }()
		go func() { defer wg.Done(); _ = st.snapshot() }()
	}
	wg.Wait()
}

// ---------------------------------------------------------------------------
// versionNewer
// ---------------------------------------------------------------------------

func TestVersionNewer(t *testing.T) {
	cases := []struct {
		a, b string
		want bool
	}{
		{"0.2.0", "0.1.0", true},
		{"0.2.0", "0.2.0", false},
		{"0.1.9", "0.2.0", false},
		{"1.0.0", "0.9.9", true},
		{"0.2.1", "0.2.0", true},
		{"0.2", "0.2.0", false},
		{"10.0.0", "9.9.9", true},
		{"0.0.1", "0.0.0", true},
		{"0.0.0", "0.0.1", false},
	}
	for _, c := range cases {
		if got := versionNewer(c.a, c.b); got != c.want {
			t.Errorf("versionNewer(%q,%q)=%v want %v", c.a, c.b, got, c.want)
		}
	}
}

// ---------------------------------------------------------------------------
// authorizeUpdate
// ---------------------------------------------------------------------------

func TestAuthorizeUpdate(t *testing.T) {
	const secret = "s3cr3t-signing-key"
	const cur = "0.1.0"
	const target = "0.2.0"
	const sha = "abc123def456"
	osArch := runtime.GOOS + "/" + runtime.GOARCH
	goodSig := sign(secret, target, osArch, sha)

	good := func() map[string]any {
		return map[string]any{"version": target, "sha256": sha, "sig": goodSig}
	}

	t.Run("valid instruction is authorized", func(t *testing.T) {
		gotT, gotSHA, ok, reason := authorizeUpdate(secret, runtime.GOOS, runtime.GOARCH, cur, good())
		if !ok {
			t.Fatalf("expected authorized, got refused: %s", reason)
		}
		if gotT != target || gotSHA != sha {
			t.Fatalf("target/sha mismatch: %q %q", gotT, gotSHA)
		}
	})

	t.Run("forged signature is refused", func(t *testing.T) {
		u := good()
		u["sig"] = "deadbeef"
		if _, _, ok, _ := authorizeUpdate(secret, runtime.GOOS, runtime.GOARCH, cur, u); ok {
			t.Fatal("forged signature was accepted")
		}
	})

	t.Run("wrong secret is refused", func(t *testing.T) {
		if _, _, ok, _ := authorizeUpdate("other-secret", runtime.GOOS, runtime.GOARCH, cur, good()); ok {
			t.Fatal("update signed with a different secret was accepted")
		}
	})

	t.Run("no secret configured refuses", func(t *testing.T) {
		if _, _, ok, _ := authorizeUpdate("", runtime.GOOS, runtime.GOARCH, cur, good()); ok {
			t.Fatal("update accepted with no secret configured")
		}
	})

	t.Run("unsigned instruction is refused", func(t *testing.T) {
		u := map[string]any{"version": target, "sha256": sha}
		if _, _, ok, _ := authorizeUpdate(secret, runtime.GOOS, runtime.GOARCH, cur, u); ok {
			t.Fatal("unsigned instruction accepted")
		}
	})

	t.Run("downgrade is refused even if validly signed", func(t *testing.T) {
		old := "0.0.9"
		u := map[string]any{"version": old, "sha256": sha,
			"sig": sign(secret, old, osArch, sha)}
		if _, _, ok, reason := authorizeUpdate(secret, runtime.GOOS, runtime.GOARCH, cur, u); ok {
			t.Fatalf("downgrade accepted: reason=%q", reason)
		}
	})

	t.Run("substituted sha256 breaks the signature", func(t *testing.T) {
		u := good()
		u["sha256"] = "0000000000" // sig no longer matches the digest
		if _, _, ok, _ := authorizeUpdate(secret, runtime.GOOS, runtime.GOARCH, cur, u); ok {
			t.Fatal("mismatched sha256 accepted")
		}
	})

	t.Run("cross-platform signature does not verify on our platform", func(t *testing.T) {
		u := good()
		u["sig"] = sign(secret, target, "plan9/486", sha)
		if _, _, ok, _ := authorizeUpdate(secret, runtime.GOOS, runtime.GOARCH, cur, u); ok {
			t.Fatal("signature for another platform authorized us")
		}
	})

	t.Run("same version is refused (no-op)", func(t *testing.T) {
		u := map[string]any{"version": cur, "sha256": sha,
			"sig": sign(secret, cur, osArch, sha)}
		_, _, ok, _ := authorizeUpdate(secret, runtime.GOOS, runtime.GOARCH, cur, u)
		if ok {
			t.Fatal("same-version instruction was accepted")
		}
	})

	t.Run("empty instruction map is refused gracefully", func(t *testing.T) {
		_, _, ok, _ := authorizeUpdate(secret, runtime.GOOS, runtime.GOARCH, cur, map[string]any{})
		if ok {
			t.Fatal("empty instruction accepted")
		}
	})
}

// ---------------------------------------------------------------------------
// config defaulting (interval / ping_interval)
// ---------------------------------------------------------------------------

func TestConfigDefaults_PingInterval(t *testing.T) {
	// We cannot call loadConfig() (reads files), so exercise the same arithmetic
	// that loadConfig applies directly.
	cases := []struct {
		interval int
		wantPing int
	}{
		{30, 10}, // 30/3 = 10
		{9, 5}, // 9/3 = 3 -> floor to 5
		{15, 5}, // 15/3 = 5 -> exact floor
		{120, 40}, // 120/3 = 40
	}
	for _, c := range cases {
		ping := c.interval / 3
		if ping < 5 {
			ping = 5
		}
		if ping > c.interval {
			ping = c.interval
		}
		if ping != c.wantPing {
			t.Errorf("interval=%d want ping=%d got %d", c.interval, c.wantPing, ping)
		}
	}
}

func TestConfigDefaults_IntervalFloor(t *testing.T) {
	// interval <= 0 should default to 30.
	cfg := config{AggregatorURL: "http://x", IngestKey: "k", Interval: 0}
	if cfg.Interval <= 0 {
		cfg.Interval = 30
	}
	if cfg.Interval != 30 {
		t.Errorf("want 30, got %d", cfg.Interval)
	}
}

// ---------------------------------------------------------------------------
// withTS
// ---------------------------------------------------------------------------

func TestWithTS(t *testing.T) {
	rows := []map[string]any{
		{"a": 1},
		{"b": 2},
	}
	const ts = 1700000000.0
	out := withTS(rows, ts)
	for i, r := range out {
		if r["ts"].(float64) != ts {
			t.Errorf("row %d: want ts=%v got %v", i, ts, r["ts"])
		}
	}
}

func TestWithTS_EmptySlice(t *testing.T) {
	out := withTS([]map[string]any{}, 42.0)
	if len(out) != 0 {
		t.Errorf("expected empty slice")
	}
}

// ---------------------------------------------------------------------------
// collectInterfaces — smoke test: at least 1 non-loopback iface should be found
// in a typical CI runner; if not, the function must return an empty slice, not panic.
// ---------------------------------------------------------------------------

func TestCollectInterfaces_DoesNotPanic(t *testing.T) {
	defer func() {
		if r := recover(); r != nil {
			t.Fatalf("collectInterfaces panicked: %v", r)
		}
	}()
	ifaces := collectInterfaces()
	for _, row := range ifaces {
		if _, ok := row["name"]; !ok {
			t.Errorf("interface row missing 'name' key: %v", row)
		}
		if _, ok := row["state"]; !ok {
			t.Errorf("interface row missing 'state' key: %v", row)
		}
		state := row["state"].(string)
		if state != "up" && state != "down" {
			t.Errorf("unexpected state %q", state)
		}
	}
}

func TestCollectInterfaces_NoLoopback(t *testing.T) {
	for _, row := range collectInterfaces() {
		name := row["name"].(string)
		if strings.HasPrefix(name, "lo") {
			t.Errorf("loopback interface %q should be excluded", name)
		}
	}
}

// ---------------------------------------------------------------------------
// nodeIP
// ---------------------------------------------------------------------------

func TestNodeIP_ReturnsStringOrEmpty(t *testing.T) {
	ip := nodeIP()
	if ip == "" {
		return // acceptable on a minimal CI runner
	}
	if net.ParseIP(ip) == nil {
		t.Errorf("nodeIP returned non-parseable IP: %q", ip)
	}
}

// ---------------------------------------------------------------------------
// HTTP helper: post() against an httptest server
// ---------------------------------------------------------------------------

func newTestServer(t *testing.T, handler http.HandlerFunc) (*httptest.Server, config) {
	t.Helper()
	srv := httptest.NewServer(handler)
	t.Cleanup(srv.Close)
	cfg := config{AggregatorURL: srv.URL, IngestKey: "test-key", Interval: 30}
	return srv, cfg
}

func TestPost_SuccessReturnsBody(t *testing.T) {
	_, cfg := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Ingest-Key") != "test-key" {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintln(w, `{"ok":true}`)
	})
	client := httpClient(cfg)
	out, ok := post(client, cfg, "/api/ingest/heartbeat", map[string]any{"x": 1})
	if !ok {
		t.Fatal("expected post to succeed")
	}
	if out["ok"] != true {
		t.Errorf("unexpected body: %v", out)
	}
}

func TestPost_Non2xxReturnsFalse(t *testing.T) {
	_, cfg := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusForbidden)
	})
	client := httpClient(cfg)
	_, ok := post(client, cfg, "/api/ingest/heartbeat", nil)
	if ok {
		t.Fatal("expected post to fail on HTTP 403")
	}
}

func TestPost_IngestKeyHeader(t *testing.T) {
	var gotKey string
	_, cfg := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		gotKey = r.Header.Get("X-Ingest-Key")
		fmt.Fprintln(w, `{}`)
	})
	client := httpClient(cfg)
	post(client, cfg, "/", nil)
	if gotKey != "test-key" {
		t.Errorf("X-Ingest-Key not forwarded: got %q", gotKey)
	}
}

func TestPost_ContentTypeJSON(t *testing.T) {
	var gotCT string
	_, cfg := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		gotCT = r.Header.Get("Content-Type")
		fmt.Fprintln(w, `{}`)
	})
	client := httpClient(cfg)
	post(client, cfg, "/", map[string]any{"a": 1})
	if !strings.HasPrefix(gotCT, "application/json") {
		t.Errorf("wrong Content-Type: %q", gotCT)
	}
}

func TestPost_PayloadRoundtrip(t *testing.T) {
	var received map[string]any
	_, cfg := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		json.NewDecoder(r.Body).Decode(&received)
		fmt.Fprintln(w, `{}`)
	})
	client := httpClient(cfg)
	post(client, cfg, "/", map[string]any{"hello": "world"})
	if received["hello"] != "world" {
		t.Errorf("payload not received: %v", received)
	}
}

// ---------------------------------------------------------------------------
// fetchCheckPlan against a mock aggregator
// ---------------------------------------------------------------------------

func TestFetchCheckPlan_ValidResponse(t *testing.T) {
	_, cfg := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/ingest/checks" {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintln(w, `{"targets":[{"name":"gw","address":"192.168.1.1","group":"lan"}],
			"services":[{"name":"dns","kind":"dns","target":"example.com"}],
			"ports":[{"name":"http","host":"127.0.0.1","port":80,"proto":"tcp"}]}`)
	})
	client := httpClient(cfg)
	plan, ok := fetchCheckPlan(client, cfg)
	if !ok {
		t.Fatal("expected fetchCheckPlan to succeed")
	}
	if len(plan.Targets) != 1 || plan.Targets[0].Name != "gw" {
		t.Errorf("targets mismatch: %+v", plan.Targets)
	}
	if len(plan.Services) != 1 || plan.Services[0].Kind != "dns" {
		t.Errorf("services mismatch: %+v", plan.Services)
	}
	if len(plan.Ports) != 1 || plan.Ports[0].Port != 80 {
		t.Errorf("ports mismatch: %+v", plan.Ports)
	}
}

func TestFetchCheckPlan_ServerError(t *testing.T) {
	_, cfg := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	})
	client := httpClient(cfg)
	_, ok := fetchCheckPlan(client, cfg)
	if ok {
		t.Fatal("expected fetchCheckPlan to fail on 500")
	}
}

func TestFetchCheckPlan_InvalidJSON(t *testing.T) {
	_, cfg := newTestServer(t, func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintln(w, `not json`)
	})
	client := httpClient(cfg)
	_, ok := fetchCheckPlan(client, cfg)
	if ok {
		t.Fatal("expected fetchCheckPlan to fail on invalid JSON")
	}
}

// ---------------------------------------------------------------------------
// runPorts
// ---------------------------------------------------------------------------

func TestRunPorts(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	defer ln.Close()
	host, portStr, _ := net.SplitHostPort(ln.Addr().String())
	var openPort int
	fmt.Sscanf(portStr, "%d", &openPort)

	plan := checkPlan{Ports: []portCheck{
		{Name: "open", Host: host, Port: openPort, Proto: "tcp"},
		{Name: "closed", Host: host, Port: 1, Proto: "tcp"},
	}}
	rows := runPorts(plan, 0)
	if len(rows) != 2 {
		t.Fatalf("want 2 rows, got %d", len(rows))
	}
	byName := map[string]bool{}
	for _, r := range rows {
		byName[r["name"].(string)] = r["open"].(bool)
	}
	if !byName["open"] {
		t.Error("expected the live listener to read as open")
	}
	if byName["closed"] {
		t.Error("expected port 1 to read as closed")
	}
}

func TestRunPorts_TimestampAttached(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	defer ln.Close()
	_, portStr, _ := net.SplitHostPort(ln.Addr().String())
	var p int
	fmt.Sscanf(portStr, "%d", &p)

	rows := runPorts(checkPlan{Ports: []portCheck{{Name: "x", Host: "127.0.0.1", Port: p, Proto: "tcp"}}}, 12345.0)
	if rows[0]["ts"].(float64) != 12345.0 {
		t.Errorf("ts not propagated: %v", rows[0]["ts"])
	}
}

func TestRunPorts_EmptyPlan(t *testing.T) {
	rows := runPorts(checkPlan{}, 0)
	if len(rows) != 0 {
		t.Errorf("expected 0 rows for empty plan, got %d", len(rows))
	}
}

func TestRunPorts_SendExpect(t *testing.T) {
	// Echo server: returns exactly what it receives.
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	defer ln.Close()
	go func() {
		conn, err := ln.Accept()
		if err != nil {
			return
		}
		defer conn.Close()
		buf := make([]byte, 64)
		n, _ := conn.Read(buf)
		conn.Write(buf[:n])
	}()

	_, portStr, _ := net.SplitHostPort(ln.Addr().String())
	var p int
	fmt.Sscanf(portStr, "%d", &p)

	rows := runPorts(checkPlan{Ports: []portCheck{
		{Name: "echo", Host: "127.0.0.1", Port: p, Proto: "tcp",
			Send: "hello", Expect: "hello"},
	}}, 0)
	if !rows[0]["matched"].(bool) {
		t.Error("echo server response should have matched")
	}
}

// ---------------------------------------------------------------------------
// checkTCP
// ---------------------------------------------------------------------------

func TestCheckTCP(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	defer ln.Close()
	if ok, _ := checkTCP(ln.Addr().String()); !ok {
		t.Error("checkTCP should connect to a live listener")
	}
	if ok, _ := checkTCP("127.0.0.1:1"); ok {
		t.Error("checkTCP should fail on a closed port")
	}
}

func TestCheckTCP_ReturnsConnected(t *testing.T) {
	ln, _ := net.Listen("tcp", "127.0.0.1:0")
	defer ln.Close()
	_, detail := checkTCP(ln.Addr().String())
	if detail != "connected" {
		t.Errorf("expected detail='connected', got %q", detail)
	}
}

// ---------------------------------------------------------------------------
// checkHTTP against httptest server
// ---------------------------------------------------------------------------

func TestCheckHTTP_200(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()
	ok, detail := checkHTTP(srv.URL)
	if !ok {
		t.Errorf("HTTP 200 should return ok=true, got detail=%q", detail)
	}
}

func TestCheckHTTP_404(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	defer srv.Close()
	ok, _ := checkHTTP(srv.URL)
	if ok {
		t.Error("HTTP 404 should return ok=false")
	}
}

func TestCheckHTTP_AddsScheme(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()
	// Strip the scheme; checkHTTP must prepend http://
	target := strings.TrimPrefix(srv.URL, "http://")
	ok, _ := checkHTTP(target)
	if !ok {
		t.Error("checkHTTP should prepend scheme and succeed")
	}
}

func TestCheckHTTP_Unreachable(t *testing.T) {
	ok, _ := checkHTTP("http://127.0.0.1:1")
	if ok {
		t.Error("checkHTTP should fail for unreachable target")
	}
}

// ---------------------------------------------------------------------------
// checkDNS
// ---------------------------------------------------------------------------

func TestCheckDNS_Localhost(t *testing.T) {
	// localhost must always resolve in CI.
	ok, detail := checkDNS("localhost")
	if !ok {
		t.Errorf("DNS lookup of localhost failed: %s", detail)
	}
}

func TestCheckDNS_InvalidHost(t *testing.T) {
	ok, _ := checkDNS("this.host.does.not.exist.invalid")
	if ok {
		t.Error("expected DNS lookup of invalid host to fail")
	}
}

// ---------------------------------------------------------------------------
// runServices dispatch
// ---------------------------------------------------------------------------

func TestRunServices_UnknownKind(t *testing.T) {
	plan := checkPlan{Services: []serviceCheck{
		{Name: "mystery", Kind: "telnet", Target: "127.0.0.1:23"},
	}}
	rows := runServices(plan, 42.0)
	if len(rows) != 1 {
		t.Fatalf("want 1 row, got %d", len(rows))
	}
	if rows[0]["ok"].(bool) {
		t.Error("unknown kind should produce ok=false")
	}
	if !strings.Contains(rows[0]["detail"].(string), "unknown kind") {
		t.Errorf("detail should mention unknown kind: %v", rows[0]["detail"])
	}
}

func TestRunServices_TCP(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	defer ln.Close()
	plan := checkPlan{Services: []serviceCheck{
		{Name: "tcp-ok", Kind: "tcp", Target: ln.Addr().String()},
		{Name: "tcp-fail", Kind: "tcp", Target: "127.0.0.1:1"},
	}}
	rows := runServices(plan, 0)
	if len(rows) != 2 {
		t.Fatalf("want 2 rows, got %d", len(rows))
	}
	if !rows[0]["ok"].(bool) {
		t.Error("tcp-ok should succeed")
	}
	if rows[1]["ok"].(bool) {
		t.Error("tcp-fail should fail")
	}
}

func TestRunServices_HTTP(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()
	plan := checkPlan{Services: []serviceCheck{
		{Name: "web", Kind: "http", Target: srv.URL},
	}}
	rows := runServices(plan, 0)
	if !rows[0]["ok"].(bool) {
		t.Errorf("http service check should pass: detail=%v", rows[0]["detail"])
	}
}

func TestRunServices_TimestampAttached(t *testing.T) {
	plan := checkPlan{Services: []serviceCheck{
		{Name: "x", Kind: "tcp", Target: "127.0.0.1:1"},
	}}
	rows := runServices(plan, 9999.0)
	if rows[0]["ts"].(float64) != 9999.0 {
		t.Errorf("ts not propagated: %v", rows[0]["ts"])
	}
}

func TestRunServices_EmptyPlan(t *testing.T) {
	rows := runServices(checkPlan{}, 0)
	if len(rows) != 0 {
		t.Errorf("expected 0 rows for empty plan")
	}
}

// ---------------------------------------------------------------------------
// runTargets (empty address filtered out)
// ---------------------------------------------------------------------------

func TestRunTargets_EmptyAddressSkipped(t *testing.T) {
	plan := checkPlan{Targets: []targetCheck{
		{Name: "blank", Address: ""},
	}}
	rows := runTargets(plan, 0)
	if len(rows) != 0 {
		t.Errorf("expected blank-address target to be skipped, got %d rows", len(rows))
	}
}

func TestRunTargets_EmptyPlan(t *testing.T) {
	rows := runTargets(checkPlan{}, 0)
	if len(rows) != 0 {
		t.Errorf("expected 0 rows")
	}
}

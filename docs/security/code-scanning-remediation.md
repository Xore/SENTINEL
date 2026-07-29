# Code Scanning Remediation Checklist

> **Generated:** 2026-07-25 (re-exported 2026-07-25 19:10 CEST)  
> **Method:** Manual deep review of all source files (Go collector, Python monitor, GitHub Actions workflows) + live re-audit against current `main` HEAD.  
> **CodeQL status:** Workflow active (`codeql.yml` v4, `security-extended`, covers `actions` / `go` / `python`). First SARIF upload pending — findings below will be supplemented once the scan completes.

---

## Status Legend

| Symbol | Meaning |
|---|---|
| `[ ]` | Not fixed |
| `[~]` | Partially fixed / in progress |
| `[x]` | Fixed and verified |

---

## Finding 1 — No CodeQL / Automated Code Scanning

**Severity:** High  
**Location:** `.github/workflows/`  
**Category:** Missing security control  

### What it is
The repo originally had no CodeQL or SAST workflow. GitHub Advanced Security (free for public repos) was not enabled. All security findings below were found by manual review — automated scanning would catch regressions continuously.

### History

| Date | Action |
|---|---|
| 2026-07-25 (initial) | Workflow added (`codeql-action/init@v3`, Go + Python) |
| 2026-07-25 | Upgraded to `codeql-action/init@v4`; removed `autobuild` step; fixed default-setup conflict |
| 2026-07-25 | Deleted and re-created from GitHub Advanced Setup template (v4) |
| 2026-07-25 19:03 | **Final form committed:** `security-extended` query suite, path scoping (`collector/`, `monitor/`, `dashboard/`, `.github/workflows`), `actions/setup-go@v5`, concurrency group |

### Current codeql.yml

- Actions: `actions/checkout@v4`, `actions/setup-go@v5`, `github/codeql-action/*@v4`
- Languages: `actions`, `go` (autobuild), `python` (none)
- Query suite: `security-extended` (adds CWE-78, CWE-295, CWE-312 coverage)
- Paths: scoped to project source; `docs/`, `tests/`, `scripts/` excluded
- Concurrency: cancel-in-progress on the same ref

### Checklist

- [x] CodeQL workflow added and active on `main` — v4, `security-extended` *(2026-07-25)*
- [x] `codeql.yml` uses `setup-go@v5` so Go autobuild succeeds *(2026-07-25)*
- [ ] First scan SARIF upload completed and visible in Security → Code scanning
- [ ] First scan shows 0 high/critical alerts (or all alerts are tracked below)
- [ ] Default setup disabled in Settings to avoid SARIF upload conflicts

---

## Finding 2 — `InsecureSkipVerify: true` in HTTP Client

**Severity:** High  
**Location:** `collector/main.go` → `httpClient()` function  
**CWE:** CWE-295 Improper Certificate Validation  
**Status (re-audit 2026-07-25):** ❌ **Still present** — no change since initial report.

### What it is

When `verify_tls` is `false` in the collector config, the HTTP client is built with `InsecureSkipVerify: true`, disabling all TLS certificate validation. This is currently gated by a config field but still creates a footgun: any operator who sets `verify_tls: false` for a self-signed lab backend silently opens the collector to full MITM — including forged update instructions.

```go
// collector/main.go — httpClient()
func httpClient(cfg config) *http.Client {
    verify := cfg.VerifyTLS == nil || *cfg.VerifyTLS
    tr := &http.Transport{}
    if !verify {
        tr.TLSClientConfig = &tls.Config{InsecureSkipVerify: true}  // ← CWE-295
    }
    return &http.Client{Timeout: 15 * time.Second, Transport: tr}
}
```

With Phase 9 (backend-generated PKI) this option becomes unnecessary: the collector will always have a valid CA bundle to verify against.

### How to fix

1. Replace `InsecureSkipVerify` with custom CA pool loading:

```go
func httpClient(cfg config) *http.Client {
    tr := &http.Transport{}
    if cfg.CACertFile != "" {
        pool := x509.NewCertPool()
        pem, err := os.ReadFile(cfg.CACertFile)
        if err != nil {
            logf("cannot read CA cert: %v — TLS will use system pool", err)
        } else {
            pool.AppendCertsFromPEM(pem)
            tr.TLSClientConfig = &tls.Config{RootCAs: pool}
        }
    }
    return &http.Client{Timeout: 15 * time.Second, Transport: tr}
}
```

2. Add `ca_cert_file` field to the `config` struct.
3. Remove the `verify_tls` field and all its references.
4. Update `docs/guides/00-setup.md` to remove the `verify_tls` option and document `ca_cert_file` instead.

### Checklist

- [ ] `InsecureSkipVerify` removed from `collector/main.go`
- [ ] `ca_cert_file` config field added and documented
- [ ] `verify_tls` config field removed
- [ ] Unit test: `httpClient()` rejects a self-signed cert when `ca_cert_file` is absent
- [ ] Unit test: `httpClient()` accepts the backend CA cert when `ca_cert_file` is set

---

## Finding 3 — `ingest_key` and `update_secret` logged to stdout on config error

**Severity:** Medium  
**Location:** `collector/main.go` → `loadConfig()`, `logf()` calls  
**CWE:** CWE-312 Cleartext Storage of Sensitive Information  
**Status (re-audit 2026-07-25):** ⚠️ **Partially mitigated** — `main()` logs only `cfg.AggregatorURL`, `cfg.Interval`, `cfg.PingInterval` (no secrets). No `%+v cfg` call exists. However, `config.LogSafe()` / `config.String()` guards are **not yet implemented**, so future log additions remain a risk.

### What it is

The `logf()` function writes to `stdout` with no redaction. If the config struct is ever printed (e.g. in a debug log added during development), the `ingest_key` and `update_secret` fields will appear in plaintext in systemd journal / container logs.

### How to fix

1. Implement `LogSafe()` and `String()` on `config` to redact secrets:

```go
func (c config) LogSafe() string {
    return fmt.Sprintf("{aggregator_url:%q collector_id:%q interval:%d ping_interval:%d ca_cert_file:%q}",
        c.AggregatorURL, c.CollectorID, c.Interval, c.PingInterval, c.CACertFile)
    // ingest_key and update_secret deliberately omitted
}

// String prevents accidental %v / fmt.Println(cfg) leaks
func (c config) String() string { return c.LogSafe() }
```

2. Replace any `logf("%+v", cfg)` patterns with `logf("%s", cfg.LogSafe())`.

### Checklist

- [~] No active `%+v cfg` log call exists *(mitigated by code structure, not by guard)*
- [ ] `config.LogSafe()` method added
- [ ] `config.String()` method added, returns redacted representation
- [ ] `logf` calls in `loadConfig()` and `main()` use `cfg.LogSafe()`
- [ ] `go vet` / `staticcheck` pass with no `fmt.Sprintf` of the full config struct

---

## Finding 4 — Subprocess command injection risk via config-derived strings (Python)

**Severity:** Medium  
**Location:** `monitor/outage_monitor.py` → `PingWorker.build_command()`, `check_dns()`, `route_probe()`  
**CWE:** CWE-78 OS Command Injection  
**Status (re-audit 2026-07-25):** ❌ **Still open** — no change since initial report.

### What it is

Several subprocess calls are built with values read directly from the monitor config JSON (`target["address"]`, `target["interface"]`, resolver IP from `check_dns`). While `subprocess.run` with a list argument does **not** invoke a shell, certain arguments are still passed verbatim as CLI flags:

```python
# PingWorker.build_command() — interface value goes directly into -I argument
command += ["-I", self.target["interface"]]

# check_dns — resolver IP goes directly as @resolver argument
command.append(f"@{resolver}")

# route_probe — address and interface go into mtr command
command += ["-I", interface]
command += ["--", address]
```

If the config file is writable by a lower-privilege process or modified via the dashboard API without sufficient sanitization, an attacker could inject flags into these commands.

### How to fix

1. Validate `address` fields as valid IP addresses or hostnames before use:

```python
import ipaddress, re

HOSTNAME_RE = re.compile(r'^[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$')

def validate_address(value: str) -> str:
    value = value.strip()
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    if HOSTNAME_RE.match(value) and len(value) <= 253:
        return value
    raise ValueError(f"Invalid address: {value!r}")
```

2. Validate `interface` names against `^[a-zA-Z0-9@._-]{1,15}$` (Linux IFNAMSIZ is 16):

```python
IFACE_RE = re.compile(r'^[a-zA-Z0-9@._-]{1,15}$')

def validate_iface(name: str) -> str:
    if IFACE_RE.match(name):
        return name
    raise ValueError(f"Invalid interface name: {name!r}")
```

3. Call these validators in `load_targets()` and `load_services()` before inserting into rows.
4. In `route_probe()` and `build_command()`, assert the `--` separator is always present before the address argument.

### Checklist

- [ ] `validate_address()` added to `monitor/outage_monitor.py` (or a shared `monitor/validation.py`)
- [ ] `validate_iface()` added
- [ ] `load_targets()` validates address and interface fields
- [ ] `load_services()` validates target field
- [ ] `check_dns()` validates `host` and `resolver` before passing to `dig`
- [ ] `route_probe()` validates address and interface
- [ ] Unit tests: `validate_address` rejects newlines, semicolons, spaces, shell metacharacters

---

## Finding 5 — `unicode_escape` deserialization in port `send` field

**Severity:** Medium  
**Location:** `monitor/outage_monitor.py` → `load_ports()` (both JSON and CSV branches)  
**CWE:** CWE-116 Improper Encoding or Escaping of Output  
**Status (re-audit 2026-07-25):** ❌ **Still open** — no change since initial report.

### What it is

The `send` field in port entries goes through a two-step decode that is known to be unsafe for untrusted input:

```python
send.encode("utf-8").decode("unicode_escape").encode("latin-1")
```

`unicode_escape` interprets `\x`, `\u`, `\N{...}` sequences and can produce unexpected byte sequences from attacker-controlled config.

### How to fix

Replace with a strictly controlled escape handler that only allows `\r`, `\n`, `\t`, and `\xNN`:

```python
def decode_send_field(raw: str) -> bytes:
    """Safe alternative to unicode_escape — only \\r \\n \\t \\xNN allowed."""
    result = bytearray()
    i = 0
    while i < len(raw):
        if raw[i] == '\\' and i + 1 < len(raw):
            c = raw[i + 1]
            if c == 'r':   result.append(0x0d); i += 2
            elif c == 'n': result.append(0x0a); i += 2
            elif c == 't': result.append(0x09); i += 2
            elif c == 'x' and i + 3 < len(raw):
                result.append(int(raw[i+2:i+4], 16)); i += 4
            else:
                result.extend(raw[i].encode('utf-8')); i += 1
        else:
            result.extend(raw[i].encode('utf-8')); i += 1
    return bytes(result)
```

Replace all occurrences of `send.encode("utf-8").decode("unicode_escape").encode("latin-1")` with `decode_send_field(send)`.

### Checklist

- [ ] `decode_send_field()` implemented in `monitor/outage_monitor.py` or shared utility
- [ ] Both `load_ports()` branches (JSON and CSV) updated to use `decode_send_field`
- [ ] Unit tests: `\r\n`, `\x00`, `\xFF` decode correctly; `\N{SNOWMAN}` raises/is ignored

---

## Finding 6 — Workflow action version pinning (supply-chain)

**Severity:** Low  
**Location:** `.github/workflows/release-candidate.yml`, `.github/workflows/go.yml`, `.github/workflows/pylint.yml`  
**CWE:** CWE-829 Inclusion of Functionality from Untrusted Control Sphere  
**Status (re-audit 2026-07-25):** ⚠️ **Partially fixed** — Dependabot watches `github-actions` ecosystem (done). Floating tags (`@v4`, `@v7`, `@v8`) remain in `release-candidate.yml`, `go.yml`, `pylint.yml`. `codeql.yml` also uses floating `@v4` / `@v5`.

### What it is

All workflows pin actions to floating major tags rather than immutable commit SHAs. A compromised or typosquatted action maintainer can push a new tag pointing to malicious code, which would then run in CI with `id-token: write` and `contents: write` permissions.

### How to fix

Pin to full commit SHAs:

```yaml
# Replace floating tags with pinned SHAs, e.g.:
- uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683       # v4.2.2
- uses: actions/setup-go@f111f3307d8850f501ac008e886eec1fd1932a34        # v5.3.0
- uses: github/codeql-action/init@v4                                      # pin to SHA
```

Alternatively, let Dependabot propose the SHA-pinned updates (already watching the `actions` ecosystem).

### Checklist

- [ ] `release-candidate.yml` — all `uses:` pinned to commit SHAs
- [ ] `go.yml` — all `uses:` pinned to commit SHAs  
- [ ] `pylint.yml` — all `uses:` pinned to commit SHAs
- [ ] `codeql.yml` — all `uses:` pinned to commit SHAs
- [x] `dependabot.yml` includes `package-ecosystem: github-actions` with security update grouping *(done 2026-07-25)*

---

## Finding 7 — No `go.sum` file committed

**Severity:** Low  
**Location:** `collector/go.sum` (missing)  
**CWE:** CWE-829 Inclusion of Functionality from Untrusted Control Sphere  
**Status (re-audit 2026-07-25):** ⚠️ **Still partially open** — `go.mod` is stdlib-only (`go 1.22`, no external deps), so `go.sum` is legitimately empty. Pattern must be established before Phase 9/10 deps are added.

### What it is

The `collector/go.mod` file declares `module network-probe-collector` with `go 1.22` but there is no `go.sum` file in the repository. Currently the module has zero external dependencies (stdlib only), so `go.sum` is empty. However, once Phase 9/10 dependencies are added (`cilium/ebpf`, `tsenart/go-tsz`, `opentelemetry-go`), `go.sum` must be committed to guarantee reproducible builds and prevent dependency substitution attacks.

### How to fix

1. After adding any external dependency, run `go mod tidy` locally.
2. Commit the resulting `go.sum` alongside `go.mod` in the same PR.
3. Add a CI check that fails if `go.sum` is out of sync:

```yaml
- name: Verify go.sum
  run: |
    go mod tidy
    git diff --exit-code go.sum
```

### Checklist

- [ ] `collector/go.sum` created and committed (even if empty, to establish the pattern)
- [ ] CI step added to `go.yml` to verify `go.sum` is not stale
- [x] `go.sum` included in Dependabot `gomod` ecosystem watch *(done 2026-07-25)*

---

## Finding 8 — `check_http()` accepts HTTP 1xx–4xx as success

**Severity:** Low  
**Location:** `monitor/outage_monitor.py` → `check_http()`  
**CWE:** CWE-252 Unchecked Return Value  
**Status (re-audit 2026-07-25):** ❌ **Still open** — no change since initial report.

### What it is

```python
return response.status < 500, round(total, 1), detail
```

A 401 Unauthorized, 403 Forbidden, or 404 Not Found response is reported as `ok=True`. For security-sensitive monitoring targets (e.g., the backend PKI `/api/pki/enroll` endpoint in Phase 9), this masks auth failures and certificate errors as healthy.

### How to fix

Make the success range configurable per service entry and default to 2xx only:

```python
def check_http(target: str, ok_range: tuple[int,int] = (200, 299)) -> tuple[bool, float | None, str]:
    ...
    ok = ok_range[0] <= response.status <= ok_range[1]
    return ok, round(total, 1), detail
```

### Checklist

- [ ] `check_http()` defaults to `2xx` success range
- [ ] Service entry schema supports optional `expected_status` field
- [ ] Unit test: 401 and 403 responses are reported as `ok=False`

---

## Finding 9 — No `go.mod` module path is a valid import path

**Severity:** Informational  
**Location:** `collector/go.mod`  
**Status (re-audit 2026-07-25):** ❌ **Still open** — module is still `network-probe-collector`.

### What it is

```
module network-probe-collector
```

The module name `network-probe-collector` is not a valid Go import path (not a domain-rooted path). This works for internal builds but prevents the module from being importable as a library, and some tools (`go get`, `staticcheck`) warn about it.

### How to fix

Rename to a proper module path:

```
module github.com/Xore/analyseLaptop/collector
```

Update all internal imports after renaming.

### Checklist

- [ ] `go.mod` module path updated to `github.com/Xore/analyseLaptop/collector`
- [ ] All `import` statements in `collector/` updated
- [ ] Build and tests pass after rename

---

## Summary Table

> Last full re-audit: **2026-07-25 19:10 CEST** against `main` HEAD `e5573a6`.

| # | Finding | Severity | File | Status |
|---|---|---|---|---|
| 1 | No CodeQL / automated scanning | High | `.github/workflows/` | `[x]` workflow active (v4, security-extended) — first scan pending |
| 2 | `InsecureSkipVerify: true` in HTTP client | High | `collector/main.go` | `[ ]` still present |
| 3 | Secrets potentially leaked to stdout | Medium | `collector/main.go` | `[~]` no active leak, guard not yet implemented |
| 4 | Subprocess command injection via config strings | Medium | `monitor/outage_monitor.py` | `[ ]` |
| 5 | `unicode_escape` decode on untrusted `send` field | Medium | `monitor/outage_monitor.py` | `[ ]` |
| 6 | Workflow actions not pinned to commit SHAs | Low | `.github/workflows/*.yml` | `[~]` Dependabot watching; SHAs not yet pinned |
| 7 | `go.sum` not committed | Low | `collector/go.sum` | `[~]` stdlib-only so empty; must add before Phase 9 deps |
| 8 | `check_http()` accepts 4xx as healthy | Low | `monitor/outage_monitor.py` | `[ ]` |
| 9 | Module path not a valid import path | Info | `collector/go.mod` | `[ ]` still `network-probe-collector` |

### Priority order for next sprint

1. **Finding 2** (High) — remove `InsecureSkipVerify`; add `ca_cert_file` support. Blocks Phase 9.
2. **Finding 4** (Medium) — add `validate_address()` / `validate_iface()`. CodeQL `security-extended` will flag CWE-78; fix before first scan upload.
3. **Finding 5** (Medium) — replace `unicode_escape` with `decode_send_field()`.
4. **Finding 3** (Medium) — add `config.LogSafe()` / `config.String()` guard.
5. **Findings 6–7–8–9** (Low/Info) — batch into a single hardening PR.

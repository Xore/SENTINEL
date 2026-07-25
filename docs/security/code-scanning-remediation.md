# Code Scanning Remediation Checklist

> **Generated:** 2026-07-25  
> **Method:** Manual deep review of all source files (Go collector, Python monitor, GitHub Actions workflows).  
> GitHub Advanced Security / CodeQL is **not enabled** on this repo — see Finding 1 to fix that first, then the automated alerts will supplement this list.

---

## Status Legend

| Symbol | Meaning |
|---|---|
| `[ ]` | Not fixed |
| `[x]` | Fixed and verified |

---

## Finding 1 — No CodeQL / Automated Code Scanning

**Severity:** High  
**Location:** `.github/workflows/`  
**Category:** Missing security control  

### What it is
The repo has no CodeQL or SAST workflow. GitHub Advanced Security (free for public repos) is also not enabled. All security findings below were found by manual review — automated scanning would catch regressions continuously.

### How to fix
1. Go to **Settings → Code security and analysis → Code scanning → Set up → Default** and enable CodeQL default setup.
2. Or add a workflow file `.github/workflows/codeql.yml`:

```yaml
name: CodeQL
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: '0 4 * * 1'   # weekly on Monday
jobs:
  analyze:
    name: Analyze
    runs-on: ubuntu-latest
    permissions:
      security-events: write
      actions: read
      contents: read
    strategy:
      matrix:
        language: [go, python]
    steps:
      - uses: actions/checkout@v4
      - uses: github/codeql-action/init@v3
        with:
          languages: ${{ matrix.language }}
      - uses: github/codeql-action/autobuild@v3
      - uses: github/codeql-action/analyze@v3
```

### Checklist

- [ ] CodeQL workflow added to `.github/workflows/codeql.yml`
- [ ] CodeQL default setup enabled in repo Settings
- [ ] First scan completed with 0 high/critical alerts

---

## Finding 2 — `InsecureSkipVerify: true` in HTTP Client

**Severity:** High  
**Location:** `collector/main.go` → `httpClient()` function  
**CWE:** CWE-295 Improper Certificate Validation  

### What it is

When `verify_tls` is `false` in the collector config, the HTTP client is built with `InsecureSkipVerify: true`, disabling all TLS certificate validation. This is currently gated by a config field but still creates a footgun: any operator who sets `verify_tls: false` for a self-signed lab backend silently opens the collector to full MITM — including forged update instructions.

```go
// collector/main.go
if !verify {
    tr.TLSClientConfig = &tls.Config{InsecureSkipVerify: true}  // ← dangerous
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
4. Update `docs/setup/00-setup.md` to remove the `verify_tls` option and document `ca_cert_file` instead.

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

### What it is

The `logf()` function writes to `stdout` with no redaction. If the config struct is ever printed (e.g. in a debug log added during development), the `ingest_key` and `update_secret` fields will appear in plaintext in systemd journal / container logs.

Currently the config is not printed directly, but the risk grows as the codebase evolves — there is no guard preventing it.

### How to fix

1. Implement `MarshalJSON` on `config` to redact secrets:

```go
func (c config) LogSafe() string {
    return fmt.Sprintf("{aggregator_url:%q collector_id:%q interval:%d ping_interval:%d verify_tls:%v ca_cert_file:%q}",
        c.AggregatorURL, c.CollectorID, c.Interval, c.PingInterval, c.VerifyTLS, c.CACertFile)
    // ingest_key and update_secret deliberately omitted
}
```

2. Replace any `logf("%+v", cfg)` patterns with `logf("%s", cfg.LogSafe())`.
3. Add a `String() string` method to `config` that also redacts secrets (prevents accidental `%v` / `fmt.Println(cfg)` leaks).

### Checklist

- [ ] `config.LogSafe()` method added
- [ ] `config.String()` method added, returns redacted representation
- [ ] `logf` calls in `loadConfig()` and `main()` use `cfg.LogSafe()`
- [ ] `go vet` / `staticcheck` pass with no `fmt.Sprintf` of the full config struct

---

## Finding 4 — Subprocess command injection risk via config-derived strings (Python)

**Severity:** Medium  
**Location:** `monitor/outage_monitor.py` → `PingWorker.build_command()`, `check_dns()`, `route_probe()`  
**CWE:** CWE-78 OS Command Injection  

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

If the config file is writable by a lower-privilege process or modified via the dashboard API without sufficient sanitization, an attacker could inject flags into these commands (e.g., `interface = "eth0\n-e malicious_script"`).

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

### What it is

The `send` field in port entries goes through a two-step decode that is known to be unsafe for untrusted input:

```python
send.encode("utf-8").decode("unicode_escape").encode("latin-1")
```

`unicode_escape` interprets `\x`, `\u`, `\N{...}` sequences and can produce unexpected byte sequences from attacker-controlled config. If the config JSON is ever editable by a lower-trust user (e.g., via the dashboard API), this is a vector for injecting arbitrary bytes into the TCP probe payload.

### How to fix

Replace with a strictly controlled escape handler that only allows `\r`, `\n`, `\t`, and `\xNN`:

```python
import re as _re

_ESCAPE_RE = _re.compile(r'\\([rntx][0-9a-fA-F]{0,2})')

def decode_send_field(raw: str) -> bytes:
    """Safe alternative to unicode_escape — only \r \n \t \xNN allowed."""
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

### What it is

All workflows pin actions to floating major tags (`@v4`, `@v7`, `@v8`) rather than immutable commit SHAs. A compromised or typosquatted action maintainer can push a new tag pointing to malicious code, which would then run in CI with `id-token: write` and `contents: write` permissions.

Examples in `release-candidate.yml`:
```yaml
- uses: actions/checkout@v7           # floating
- uses: actions/attest-build-provenance@v4  # floating
- uses: actions/download-artifact@v8  # floating
```

### How to fix

Pin to full commit SHAs:

```yaml
# Replace floating tags with pinned SHAs, e.g.:
- uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683       # v4.2.2
- uses: actions/setup-go@f111f3307d8850f501ac008e886eec1fd1932a34        # v5.3.0
- uses: actions/attest-build-provenance@c074443f1aee8d4aeeae555aebba3282  # v2.2.3
```

Alternatively, enable **Dependabot for Actions** (already in `.github/dependabot.yml` — verify it covers `actions:` ecosystem).

### Checklist

- [ ] `release-candidate.yml` — all `uses:` pinned to commit SHAs
- [ ] `go.yml` — all `uses:` pinned to commit SHAs  
- [ ] `pylint.yml` — all `uses:` pinned to commit SHAs
- [ ] `dependabot.yml` includes `package-ecosystem: github-actions` to keep SHAs updated automatically

---

## Finding 7 — No `go.sum` file committed

**Severity:** Low  
**Location:** `collector/go.sum` (missing)  
**CWE:** CWE-829 Inclusion of Functionality from Untrusted Control Sphere  

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
- [ ] CI step added to verify `go.sum` is not stale
- [ ] `go.sum` included in the `dependabot.yml` `go-modules` ecosystem watch

---

## Finding 8 — `check_http()` accepts HTTP 1xx–4xx as success

**Severity:** Low  
**Location:** `monitor/outage_monitor.py` → `check_http()`  
**CWE:** CWE-252 Unchecked Return Value  

### What it is

```python
return response.status < 500, round(total, 1), detail
```

A 401 Unauthorized, 403 Forbidden, or 404 Not Found response is reported as `ok=True`. For security-sensitive monitoring targets (e.g., the backend PKI `/api/pki/enroll` endpoint in Phase 9), this masks auth failures and certificate errors as healthy.

### How to fix

Make the success range configurable per service entry and default to 2xx only:

```python
# In check_http, accept an optional expected_status_range parameter
def check_http(target: str, ok_range: tuple[int,int] = (200, 299)) -> tuple[bool, float | None, str]:
    ...
    ok = ok_range[0] <= response.status <= ok_range[1]
    return ok, round(total, 1), detail
```

For Phase 9 PKI endpoint monitoring, the expected status is `200` (enrollment) or `204` (revocation) — not a broad `< 500`.

### Checklist

- [ ] `check_http()` defaults to `2xx` success range
- [ ] Service entry schema supports optional `expected_status` field
- [ ] Unit test: 401 and 403 responses are reported as `ok=False`

---

## Finding 9 — No `go.mod` module path is a valid import path

**Severity:** Informational  
**Location:** `collector/go.mod`  

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

| # | Finding | Severity | File | Fixed |
|---|---|---|---|---|
| 1 | No CodeQL / automated scanning | High | `.github/workflows/` | `[ ]` |
| 2 | `InsecureSkipVerify: true` in HTTP client | High | `collector/main.go` | `[ ]` |
| 3 | Secrets potentially leaked to stdout | Medium | `collector/main.go` | `[ ]` |
| 4 | Subprocess command injection via config strings | Medium | `monitor/outage_monitor.py` | `[ ]` |
| 5 | `unicode_escape` decode on untrusted `send` field | Medium | `monitor/outage_monitor.py` | `[ ]` |
| 6 | Workflow actions not pinned to commit SHAs | Low | `.github/workflows/*.yml` | `[ ]` |
| 7 | `go.sum` not committed | Low | `collector/go.sum` | `[ ]` |
| 8 | `check_http()` accepts 4xx as healthy | Low | `monitor/outage_monitor.py` | `[ ]` |
| 9 | Module path not a valid import path | Info | `collector/go.mod` | `[ ]` |

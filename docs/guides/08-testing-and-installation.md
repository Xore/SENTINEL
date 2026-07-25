# 08 — Testing & Installation Phase (step-by-step)

This is the **acceptance checklist** run at the end of the current roadmap push.
It has two halves:

- **Part A — Functional testing** on the *current* deployments (no reinstall).
- **Part B — Installation testing** on *freshly reinstalled* Linux laptops, to
  prove `scripts/setup.sh` / the install scripts work from a clean OS.

Hardware for this phase:

| Role | Host | Address | Notes |
|------|------|---------|-------|
| Windows dev box | (this machine) | — | authoring + unit tests, Git Bash + `.venv` |
| Wi-Fi-only probe | `MGPNetworkAnalayses01` | `192.168.50.32` | **LIVE production**, Wi-Fi-only, **no wired fallback — never destabilise** |
| Lab laptop | `MGPNetworkAnalayses02` | `192.168.50.33` | `adminuser`, SSH key `~/.ssh/analyse_lab`, NOPASSWD sudo, i7-10610U / 15 GiB |

SSH note: `.32`'s sshd is unreliable over the flaky Wi-Fi link (banner-exchange
timeouts) even though it pings — drive `.32` from its own console / the existing
dashboard, not over SSH. `.33` is the safe box to control programmatically.

Legend: `[ ]` = to do, `[x]` = passed. Record the date + who ran it per box.

---

## Part A — Functional testing (current build, no reinstall)

### A0. Pre-flight (all boxes)
- [ ] `git -C <repo> rev-parse --short HEAD` matches the intended release commit.
- [ ] Windows: `./.venv/Scripts/python.exe -W ignore::ResourceWarning -m unittest discover -s tests` → **OK** (expect 6 skipped: the Linux-only tests).
- [ ] Linux (`.33`): same suite in the box's `.venv` → **OK, 0 skipped** (the 6 Windows-skipped tests must actually run here).
- [ ] `bash run-tests.sh` (Go collector + Python) where Go is available.

### A1. Standalone dashboard boots & authenticates (.33)
- [ ] Launch single-process: `waitress-serve --listen=0.0.0.0:8088 dashboard.app:app` with the `PROBE_*` state paths pointed at a writable dir.
- [ ] `ss -ltnp | grep 8088` shows it listening.
- [ ] From another LAN host: `GET http://<ip>:8088/` → **200**.
- [ ] `POST /api/login {admin/admin}` → `{"ok":true,"must_change":true}`.
- [ ] First login **forces a password change**; the new password logs in; the old one is rejected.
- [ ] Restart the process → the session cookie is invalidated (sessions die on restart, by design #30), and the *changed* password still works (persisted to the auth file).

### A2. Every SPA tab loads without console errors (.33, browser)
- [ ] Overview, Interfaces, Discovery, Actions, Health, Wi-Fi, Access Points, Heatmap, Security (IDS), Neighbours, Map, Assets, Collectors, Jobs, Dangerous, Settings — each renders; no uncaught JS errors in devtools.
- [ ] **Dangerous tab is visual-only** — confirm no offensive control is wired (no deauth/inject/exploit/credential-guess/PLC-write). Register renders as excluded-by-default.

### A3. Outage monitor + trends (#50) — needs live data
- [ ] Start the outage monitor pointed at the same `PROBE_MONITOR_DB`; confirm it writes `service_samples`, `events`, and **`tcp_samples`** rows.
- [ ] `GET /api/monitor/tcp?minutes=360` and `/api/monitor/dns?minutes=360` → 200 with buckets; a bad `minutes` → **400** and **does not leak a DB handle** (next request still works).
- [ ] Monitor page "Protocol Trends" panel renders the TCP/DNS charts + verdict badges.
- [ ] `monitor/tcp_stat.read_proc()` on Linux returns real counters (`in_segs > 0`). *(Returns `None` on Windows — that's expected.)*

### A4. Alerting (#53) — the new feature
- [ ] Settings → **Alerting** panel loads current config; secret field shows `· not set` / `· stored`, never a value.
- [ ] Configure a **webhook** to a local sink (e.g. a one-shot `http.server`), Save, **Send test** → sink receives JSON `{source:"network-probe", signal, state, subject, ...}`; delivery row shows `webhook: ok`.
- [ ] Save an **SMTP** config with a password; reload the page → password field blank, shows `· stored`; `GET /api/settings` response contains `password_set:true` and **no cleartext password**.
- [ ] `POST /api/alerts/test` with no channel enabled → **400** ("enable a webhook or email channel first").
- [ ] Force an outage (stop a monitored target) so an `events` row opens; `POST /api/alerts/evaluate` → **fires once** (history gains a `firing` row); call it again while still degraded → **no new alert** (steady state stays silent).
- [ ] Clear the outage; next evaluate → **one `resolved`** alert.
- [ ] Restart the dashboard mid-degradation → evaluate does **not** replay the already-fired alert (persisted edge state survives restart).
- [ ] `deliver_email` against a dead SMTP port returns `{ok:false, error:...}` and **never raises**.

### A5. Metrics / export (#52) & config validation (#49)
- [ ] `GET /metrics` (with the token) returns OpenMetrics text; wrong/absent token → 401/403.
- [ ] PUT an invalid settings section (e.g. `alerting.poll_seconds: 2`) → **400** with a specific message; a valid PUT records an audit-trail entry.

### A6. Live-box smoke (.32, from its own console — read-only, no changes)
- [ ] Existing production dashboard still reachable on `http://192.168.50.32:8088`.
- [ ] Wi-Fi survey + AP-watch still populate. **Make no config changes that could drop the Wi-Fi link.**

### A7. Teardown
- [ ] Stop the throwaway standalone instance on `.33`; remove `~/probe-state` scratch if it was only for testing.

---

## Part B — Installation testing (after the Linux laptops are reinstalled)

Goal: prove the install path works from a **clean OS**, using only the repo +
documented commands — no hand-fixing.

### B0. Clean baseline (each reinstalled laptop)
- [ ] Fresh OS, `adminuser` present, SSH reachable (or drive from console).
- [ ] `git clone https://github.com/Xore/analyseLaptop.git` succeeds.
- [ ] Record OS version + `python3 --version` (expect a `python3-venv` gap on bare Ubuntu — the installer must handle it).

### B1. Unified setup (`scripts/setup.sh`)
- [ ] `scripts/setup.sh` menu appears; `--dry-run` prints the plan without changing the system.
- [ ] Standalone role install runs to completion; it `apt-get install`s the deps (`python3-venv python3-pip tshark nmap ethtool iw jq curl git dnsutils snmp traceroute mtr-tiny chrony`) — note anything missing (e.g. **`curl` was absent on the bare lab box**; confirm the installer pulls it).
- [ ] venv built at `/opt/network-probe-venv`; `dashboard/requirements.txt` (Flask 3.1.3 + waitress 3.0.2) installed.
- [ ] systemd units created and `enabled`; `systemctl is-active` green for the chosen role's services.

### B2. First-boot dashboard
- [ ] Dashboard reachable on the bound address:8088; admin/admin → forced password change.
- [ ] Re-run `scripts/setup.sh` / `install-dashboard-service.sh --apply` after an IP change rebinds cleanly (per the deploy note).

### B3. Role variants
- [ ] **Standalone** role: dashboard + monitor + (optional) IDS all supervised.
- [ ] **Collector** role on the second laptop: push agent registers to the standalone backend; remote neighbours appear as `collector:<id>` nodes on the Map; `/api/map?collector=<id>` scopes to them.
- [ ] SSH key grant/revoke: `scripts/lab-grant-access.sh` / `lab-access-bootstrap.sh` still behave; a revoked key can no longer log in.

### B4. Post-install regression
- [ ] Run **Part A** (A1–A5) against the freshly installed standalone box — everything that passed on the dev clone passes on the real install.
- [ ] `bash run-tests.sh` on the installed box.

### B5. Sign-off
- [ ] Record per-box: commit, OS, date, tester, and any deviations. File follow-up issues for anything the installer couldn't do unattended.

---

### Quick command reference

```bash
# Linux venv + full suite (native, 0 skipped)
python3 -m venv .venv && . .venv/bin/activate
pip install -r dashboard/requirements.txt
python -W ignore::ResourceWarning -m unittest discover -s tests

# Throwaway standalone with isolated state (no root, no systemd)
export PROBE_WEB_DB=~/probe-state/web.db PROBE_SETTINGS_FILE=~/probe-state/settings.json \
       PROBE_MONITOR_DB=~/probe-state/monitor.db PROBE_AUTH_FILE=~/probe-state/dashboard-auth.json \
       PROBE_ALERT_STATE=~/probe-state/alert-state.json
waitress-serve --listen=0.0.0.0:8088 dashboard.app:app
```

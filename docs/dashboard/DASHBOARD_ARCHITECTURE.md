# Dashboard Architecture
## analyseLaptop — Comprehensive Control & Monitoring Interface

> **Date:** 2026-07-25  
> **Scope:** Full dashboard system covering collector remote control, main system configuration, WiFi analysis, and all Phase 1–12 roadmap features.  
> **Basis:** ROADMAP.md (Phases 1–12), docs/collector/ROADMAP.md (Phases 0–7), docs/collector/SUGGESTIONS.md, docs/guides/03-capture-and-wifi.md

---

## 1. Design Rationale & Scratchpad

### 1.1 Feature Categorisation (from both roadmaps)

After analysis of all roadmap phases and guides, all features fall into six functional categories:

| Category | Roadmap Sources | Dashboard Module |
|---|---|---|
| Collector lifecycle & deployment | Collector ROADMAP Ph0–1, SUGGESTIONS §5 | **Module A: Collector Manager** |
| Collector network & VPN control | SUGGESTIONS §6.1–6.5, main ROADMAP Ph9 | **Module A: Collector Manager** |
| Tool install / diagnostics / eBPF | Collector ROADMAP Ph2–3, main ROADMAP Ph2,11 | **Module A: Collector Manager** |
| WiFi monitor mode & analysis | guides/03-capture-and-wifi.md | **Module B: WiFi Analyser** |
| Live telemetry & anomaly detection | main ROADMAP Ph3–4, Ph6 | **Module C: Live Monitor** |
| Historical analysis & reporting | main ROADMAP Ph6 (#48, #47), Ph7 | **Module D: History & Reports** |
| Main system configuration | main ROADMAP Ph5,8,9 settings | **Module E: System Config** |
| PKI / mTLS / cert management | main ROADMAP Ph9 | **Module E: System Config** |
| Dangerous actions governance | main ROADMAP P5 gate | **Module F: Dangerous Actions** |
| Probe scheduling & MDP control | main ROADMAP Ph5,12 | **Module E: System Config** |
| Prometheus/Grafana integration | main ROADMAP Ph7 | **Module C: Live Monitor** |

### 1.2 Core Functional Modules Identified

Six top-level modules with clear separation of concern:

```
A. Collector Manager     — per-collector remote control panel
B. WiFi Analyser         — monitor-mode interface + spectrum/AP view
C. Live Monitor          — topology map, anomaly timeline, RCA panel
D. History & Reports     — time-series browser, export, evidence bundles
E. System Config         — main system settings, PKI, MDP, alert routing
F. Dangerous Actions     — gated governance surface (P5)
```

### 1.3 User Workflow Analysis

**Deployment flow (new collector):**
> System Config → Add Collector → Collector Manager → Enroll PKI → Deploy → Verify → Live Monitor

**Operations flow (daily use):**
> Live Monitor (topology) → anomaly click → RCA panel → Collector Manager (diagnostics) → resolve

**WiFi survey flow:**
> Collector Manager → select collector → WiFi tab → put adapter into monitor mode → channel lock → live scan → History & Reports export

**Incident response flow:**
> Live Monitor alert → Collector Manager (freeze evidence) → History & Reports (export bundle) → Dangerous Actions (audit log review)

### 1.4 Technical Architecture Decisions

**Frontend:** Server-side rendered HTML (Jinja2, extending current `dashboard/frontend.py` pattern) with targeted HTMX for real-time panel updates. No SPA framework — keeps deployment footprint minimal and consistent with existing `dashboard/app.py`.

**Real-time transport:** Server-Sent Events (SSE) from a `/api/stream` endpoint for live telemetry, topology state, and anomaly events. WebSocket reserved for the interactive terminal (collector diagnostics shell). Both are built into Flask/Gunicorn without additional broker.

**Backend API:** RESTful Flask routes grouped by module prefix (`/api/collectors/`, `/api/wifi/`, `/api/monitor/`, `/api/reports/`, `/api/system/`, `/api/dangerous/`). All mutating endpoints require CSRF token + session auth (extending `dashboard/auth.py`).

**Collector-side agent API:** The Go collector exposes a local HTTP API (localhost-only, or WireGuard-tunnelled) for remote control commands: `POST /control/network`, `POST /control/wireguard`, `POST /control/tools`, `POST /control/diagnostic`. The dashboard proxies through to this API.

**Scalability:** The module system is designed so each module is a separate Python file (e.g., `dashboard/collector_manager.py`, `dashboard/wifi_analyser.py`) registered as a Flask Blueprint, enabling independent development and testing.

---

## 2. Navigation & Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  analyseLaptop Dashboard                    [user] [alerts] [logout] │
├──────────┬──────────────────────────────────────────────────────────┤
│          │                                                           │
│  NAV     │  MAIN CONTENT AREA                                       │
│          │                                                           │
│ ● Live   │                                                           │
│   Monitor│                                                           │
│          │                                                           │
│ ● Collec-│                                                           │
│   tors   │                                                           │
│                                                                      │
│ ● WiFi   │                                                           │
│   Analyser                                                           │
│          │                                                           │
│ ● History│                                                           │
│   & Rpts │                                                           │
│          │                                                           │
│ ● System │                                                           │
│   Config │                                                           │
│          │                                                           │
│ ⚠ Danger-│                                                           │
│   ous    │                                                           │
└──────────┴──────────────────────────────────────────────────────────┘
```

The navigation sidebar is persistent. The `Dangerous Actions` entry is visually distinguished (amber/red) and only visible to admin-role users. A persistent alert strip at the top flashes on active anomaly events, linking directly to the relevant collector/target in Live Monitor.

---

## 3. Module A — Collector Manager

### 3.1 Collector List View (`/collectors`)

Table of all registered collectors with inline status:

| Column | Source | Notes |
|---|---|---|
| Name / ID | config | Clickable → detail panel |
| MDP State | monitor/ push | STABLE / SUSPECT / DEGRADED / DOWN badge |
| Last Seen | heartbeat | Age in seconds |
| PKI Cert Expiry | /api/pki | Days remaining; red < 7 |
| WireGuard Tunnel | collector push | Handshake age; red > 3 min |
| Active Checks | check_plan | Count of configured checks |
| eBPF Available | collector capability | Green tick / grey dash |
| Actions | — | [Open] [Re-enroll] [Remove] |

**Add Collector** button opens a wizard:
1. Enter collector ID + description
2. Choose deployment method (systemd / Docker Compose)
3. Download generated install script with embedded config + PKI enrollment command
4. Wait for first heartbeat (live status indicator)

### 3.2 Collector Detail Panel (`/collectors/<id>`)

Tab-based panel per collector. Tabs:

#### Tab: Overview
- Live mini-topology of this collector's monitored targets (D3.js SVG)
- Recent anomaly events (last 10, with RCA verdict)
- Resource gauges: CPU %, Memory %, Disk % (from `os_health` stream)
- Uptime counter
- PKI certificate validity bar

#### Tab: Network Interfaces

Live table of all interfaces reported by the collector:

| Interface | State | IP Address | RX bps | TX bps | Errors/s | Drops/s |
|---|---|---|---|---|---|---|
| eth0 | UP | 192.168.1.50/24 | 124k | 48k | 0 | 0 |
| wlan0 | UP | 10.0.0.5/24 | 8k | 2k | 3 | 0 |
| wlan1mon | MONITOR | — | — | — | — | — |

**Inline edit for IP address:** Click the IP cell → inline form with new IP/prefix → `Apply`. The dashboard sends:
```
POST /api/collectors/<id>/network
{ "interface": "eth0", "address": "192.168.1.51", "prefix": 24 }
```
The collector agent applies `ip addr replace` + persists to netplan/interfaces config. A confirmation dialog warns: *"This will interrupt the connection briefly. The tunnel will reconnect automatically."*

**Route table view:** Expandable section shows `ip route` output, with the default gateway highlighted and its RTT/loss displayed.

#### Tab: WireGuard VPN

Per-tunnel table:

| Interface | Peer (truncated pubkey) | Endpoint | Allowed IPs | Handshake Age | RX/TX delta | Status |
|---|---|---|---|---|---|---|
| wg0 | abc...xyz | 1.2.3.4:51820 | 10.10.0.0/24 | 23s | 8.2k / 1.1k | ✅ UP |

**Actions per tunnel:**
- **Restart peer handshake:** `POST /api/collectors/<id>/wireguard/restart` — triggers `wg set <iface> peer <pubkey>` to force re-handshake
- **Edit config:** Opens modal with WireGuard config fields (endpoint IP/port, allowed IPs, keepalive). Submit applies via `wg setconf` + persists to `/etc/wireguard/<iface>.conf`
- **Add peer / Remove peer:** Full CRUD on WireGuard peer entries
- **Bring interface up/down:** `wg-quick up/down <iface>`

**Tunnel status is polled every 5 seconds via SSE.** A handshake age > 180s triggers an amber badge.

#### Tab: Tools & eBPF

Shows tool inventory for the collector (reported by collector on startup and on-demand scan):

| Tool | Required For | Installed | Version | Action |
|---|---|---|---|---|
| `iw` | WiFi scan | ✅ | 5.19 | — |
| `airmon-ng` | WiFi monitor mode | ❌ | — | [Install] |
| `dumpcap` | WiFi/wired capture | ✅ | 4.2 | — |
| `tshark` | PCAP analysis | ✅ | 4.2 | — |
| `traceroute` | Hop diagnosis | ✅ | 1.3 | — |
| eBPF (`CAP_BPF`) | Passive RTT | ✅ | kernel 6.1 | — |
| `clang` / BPF toolchain | eBPF compile | ❌ | — | [Install] |
| `wg` / wgctrl | WireGuard control | ✅ | 1.0 | — |

**[Install] button** sends:
```
POST /api/collectors/<id>/tools/install
{ "tool": "airmon-ng", "method": "apt" }
```
The collector runs `apt-get install -y aircrack-ng` (or equivalent), streams stdout back via SSE into a live log panel on the dashboard.

**[Detect Missing Tools]** button triggers a full re-scan and refreshes the table.

**eBPF capability check:** Shows kernel version, available capabilities (`CAP_BPF`, `CAP_NET_ADMIN`, `CAP_PERFMON`), BTF availability (`/sys/kernel/btf/vmlinux`). Explains what degrades if missing.

#### Tab: Diagnostics

Interactive diagnostic panel with pre-built command buttons and a freeform terminal:

**Pre-built diagnostics (buttons):**

| Button | Command sent to collector | Output |
|---|---|---|
| Ping GW | `pingWithLoss(gw, 10, 3000)` | RTT p50/p95/p99, loss % |
| Traceroute to target | `traceroute -n <target>` | Per-hop RTT table |
| Interface stats | `/proc/net/dev` dump | Rate table |
| WireGuard status | `wg show all` | Raw output |
| DNS resolution test | Resolve configured DNS targets | Latency ms |
| ARP table | `ip neigh show` | Neighbour table |
| Route table | `ip route show` | Full route dump |
| Listening ports | `ss -tlnp` | Port/process table |
| OS health snapshot | CPU/mem/disk poll | Gauge summary |
| TLS cert check | Re-run all TLS checks | Expiry table |
| Run all checks now | Force a full check cycle | JSON output |

**Freeform terminal:** A constrained shell panel (WebSocket to `/ws/collectors/<id>/terminal`) that executes commands on the collector via the agent's `POST /control/exec` endpoint. The agent's exec endpoint is **allowlist-only** — only diagnostic, read-only commands are permitted. No shell injection. Command output is streamed back.

**Allowed command prefixes (hardcoded allowlist in collector agent):**
```
ping, traceroute, ip, ss, wg, iw, iwconfig, iwlist, dumpcap,
tshark, netstat, cat /proc/*, cat /sys/class/net/*, systemctl status,
dmesg | tail, journalctl -n, uname, df, free, uptime, who
```

#### Tab: Check Plan

Visual editor for the collector's check plan (sent back to collector via `POST /control/check_plan`):

- **Targets (ICMP):** Add/edit/remove target IPs with labels
- **Services (HTTP/TCP/DNS/NTP):** Add/edit/remove
- **SNMP targets:** Add with version, community/auth, OID list
- **Modbus targets:** Add with host, unit_id, register list (safety: FC01/FC03 only enforced)
- **WAN checks:** Toggle, configure public IP URL, latency anchors
- **TLS checks:** Add cert targets with warn threshold
- **OS health:** Toggle, configure disk paths, thresholds
- **WireGuard:** Toggle, configure max handshake age

All changes are validated via `dashboard/config_validation.py` before sending. The collector acknowledges receipt and begins the new plan immediately.

#### Tab: PKI & mTLS

- Current cert subject, issuer, expiry, fingerprint
- **[Re-enroll]:** Triggers collector to generate new keypair + CSR → `POST /api/pki/enroll` → backend signs → cert returned
- **[Revoke]:** `DELETE /api/pki/revoke/<id>` — removes from trusted set immediately
- **[Download CA bundle]:** Downloads the backend CA cert for manual verification
- TLS handshake test: live test of mTLS connection between backend and collector

---

## 4. Module B — WiFi Analyser

### 4.1 Design Basis

Based on `docs/guides/03-capture-and-wifi.md`. The dashboard provides complete control over WiFi monitor-mode setup and passive analysis. **No active injection, no deauthentication frames, no AP impersonation** (all gated in Module F / Dangerous Actions per P5 governance).

### 4.2 WiFi Analyser View (`/wifi`)

Collector selector at the top — only collectors with a compatible WiFi adapter (detected via `iw list` output in Tools tab) are shown.

#### Sub-panel: Adapter Management

| Column | Data |
|---|---|
| Interface | wlan0, wlan1, ... |
| Mode | managed / monitor / AP |
| Driver | ath9k, mt7612u, ... |
| Monitor capable | ✅ / ❌ (from `iw list` parse) |
| Current channel | 1–14 (2.4 GHz), 36–177 (5 GHz) |

**[Enable Monitor Mode]** button:
1. Confirms adapter is not the primary network interface (safety check)
2. Sends `POST /api/collectors/<id>/wifi/monitor-mode` `{ "interface": "wlan1", "action": "enable" }`
3. Collector runs: `sudo ip link set wlan1 down`, `sudo iw dev wlan1 set type monitor`, `sudo ip link set wlan1 up`
4. Dashboard refreshes adapter table

**[Disable Monitor Mode]** restores managed mode.

**Channel Lock:** Dropdown (1–13 for 2.4 GHz, all 5 GHz channels, all 6 GHz channels) → `POST /api/collectors/<id>/wifi/channel` `{ "interface": "wlan0mon", "channel": 6 }`

**Channel Hopping:** Toggle (disabled by default, with warning: *"Channel hopping reduces timing accuracy and causes packet loss across channels."*)

#### Sub-panel: AP / SSID Scanner

Passive beacon/probe-response scan. Collector runs `iw dev wlan0mon scan dump` periodically and streams results:

| SSID | BSSID | Channel | Band | RSSI (dBm) | Encryption | Clients seen | Beacons/s |
|---|---|---|---|---|---|---|---|
| HomeNet | aa:bb:cc:... | 6 | 2.4 GHz | -45 | WPA2-PSK | 3 | 10 |
| Corp-5G | dd:ee:ff:... | 36 | 5 GHz | -62 | WPA2-Enterprise | 7 | 10 |

Table is live-updated via SSE. Sortable by RSSI, channel, client count.

**RSSI chart:** Click an SSID → time-series RSSI chart for that AP (last 10 minutes, polled every 5 s).

**Hidden SSID detection:** Probe requests from clients for hidden SSIDs are surfaced as `[Hidden SSID — probed by <MAC>]`.

#### Sub-panel: Spectrum View

Channel utilisation bar chart — 2.4 GHz and 5 GHz bands — showing signal strength of all detected APs per channel. Overlapping channel ranges visually indicated. Updated every 10 seconds.

Metrics per channel:
- Number of APs
- Strongest RSSI
- Estimated utilisation (beacon density × bandwidth)
- Interference risk (overlapping adjacent channels)

#### Sub-panel: Client Table

Clients observed sending frames (probe requests, data frames, management frames):

| MAC | SSID associated | RSSI | Frame types seen | First seen | Last seen | Probe requests (SSIDs) |
|---|---|---|---|---|---|---|
| aa:bb:... | HomeNet | -52 | Data, Mgmt | 13:45 | 13:52 | HomeNet, OldNet |

**Vendor lookup:** OUI prefix of MAC resolved to manufacturer (local OUI database, no external calls).

**Client RSSI history:** Click a MAC → RSSI time-series chart.

#### Sub-panel: Packet Capture

Passive PCAP capture control (based on `docs/guides/03-capture-and-wifi.md`):

- **Interface selector** (monitor-mode adapters only)
- **Channel** (must be locked first — warning if hopping is on)
- **Rotation:** duration (seconds per file, default 300) + file count (default 24 = 2 hours)
- **Output path** on collector: `/var/capture/wifi-<date>.pcapng`
- **[Start Capture]** → `POST /api/collectors/<id>/wifi/capture/start`
  - Collector runs `dumpcap -i wlan0mon -b duration:300 -b files:24 -w /var/capture/wifi.pcapng`
  - Streams stdout/stderr to live log panel
- **[Stop Capture]** → `POST /api/collectors/<id>/wifi/capture/stop`
- **File list:** Shows completed PCAP files with size, SHA-256 hash, duration
- **[Download]** per file — streams from collector to browser
- **[Analyse]** per file — runs `pcap-summary.sh` on collector, returns text/CSV summary

**Safety enforced by collector agent:**
- Capture refuses an interface that has an assigned IP address
- All capture files are SHA-256 hashed after completion
- Capture is automatically stopped after `max_capture_duration_hours` (configurable, default 4 h)

#### Sub-panel: 802.11 Frame Counters

Real-time counters parsed from the monitor interface, updated every 5 s:

| Frame Type | Count | Rate/s |
|---|---|---|
| Beacons | 14,320 | 10.2 |
| Probe Requests | 234 | 0.8 |
| Probe Responses | 156 | 0.5 |
| Auth frames | 12 | 0.0 |
| Assoc Request | 8 | 0.0 |
| Data frames | 45,230 | 320 |
| Null frames | 1,230 | 8.8 |
| Retransmissions | 2,150 | 15.4 |

High retransmission rate (> 10% of data frames) triggers an amber alert.

#### Sub-panel: Interference & Anomaly Detection

Passive anomaly detection on WiFi frame stream:

| Anomaly | Detection Method | Alert |
|---|---|---|
| Deauthentication flood | deauth frame count > threshold | 🔴 High |
| Beacon flood (AP impersonation) | same SSID, different BSSID rapid appearance | 🔴 High |
| Client probe storm | single MAC probing > N SSIDs/min | 🟡 Medium |
| Rogue AP (new BSSID on known SSID) | BSSID not in known AP list | 🟡 Medium |
| KRACK / PMKID indicators | EAPOL replay counter anomaly | 🟡 Medium |
| Hidden AP activated | SSID length=0 beacon | ℹ️ Info |
| Client roaming event | re-assoc to different BSSID | ℹ️ Info |

All anomalies are written to the audit trail and surfaced in Module C Live Monitor.

---

## 5. Module C — Live Monitor

### 5.1 Topology Map (`/monitor`)

Primary operational view. NetworkX graph rendered as D3.js force-directed SVG, updated via SSE.

**Node types:**
- Collector (laptop icon) — colour by MDP state: green=STABLE, amber=SUSPECT, red=DEGRADED, black=DOWN
- Target (server/device icon) — colour by probe state
- WAN cloud node
- WiFi AP node (from WiFi Analyser data)

**Edge annotations:**
- RTT p95 in ms
- Loss % (shown if > 0)
- WireGuard tunnel edges shown dashed with handshake age

**Interactions:**
- Click node → side panel showing last 5 min RTT chart + active anomalies
- Click edge → RTT history chart
- Click anomaly badge on node → RCA panel (see 5.3)
- Right-click collector → jump to Collector Manager detail
- Zoom/pan (d3-zoom)

**Collector-local topology subgraph:** Each collector can expand to show its own monitored subnet, with WiFi clients from the WiFi Analyser overlaid as leaf nodes.

### 5.2 Anomaly Timeline

Swim-lane chart (one lane per collector + one lane per major metric category). Each anomaly is a marker on the timeline:
- CUSUM+EWMA dual-trigger anomalies (Phase 3)
- PCA Hotelling T² anomalies (Phase 3)
- WiFi anomalies (Module B)
- eBPF high-latency client events (Phase 2c)
- RCA verdicts overlay (Phase 4)

Time window selector: 1h / 6h / 24h / 7d. Click marker → anomaly detail side panel.

### 5.3 RCA Panel

Slides in from the right when an anomaly is clicked. Shows:

- **Most probable cause** (top Naive Bayes posterior, Phase 4)
- **Confidence level** with colour coding: >0.8=red auto-alert, 0.6–0.8=amber probable, <0.6=grey symptoms only
- **Active symptoms** that contributed (with individual probability scores)
- **Decision tree path** (dropped connection decision tree from Phase 4c, visualised as a breadcrumb trail)
- **Suggested remediation** steps (text, per cause type)
- **[Open Collector]** button — links to the relevant collector's Diagnostics tab
- **[Freeze Evidence]** button — triggers evidence bundle snapshot (Phase 6, #47)

### 5.4 High-Latency Client Table

Live table from eBPF kprobe events (Phase 2c). Sortable by RTT ratio:

| Client IP | Subnet | RTT ratio (event/baseline) | srtt_us | Baseline us | Events | First seen |
|---|---|---|---|---|---|---|
| 192.168.1.25 | .0/24 | 4.2× | 21000 | 5000 | 12 | 2 min ago |

### 5.5 Prometheus / Grafana Integration

- **[Open Grafana]** button (links to Grafana instance, configurable URL in System Config)
- Prometheus scrape endpoint status table: shows all active metric series being exported
- Last scrape timestamp per collector

---

## 6. Module D — History & Reports

### 6.1 Time-Series Browser (`/history`)

Metric picker (collector → target → metric) + time range selector. Renders chart (Chart.js) with:
- Raw values
- Holt-Winters smoothed line
- Anomaly event markers
- Control limit bands (±3σ Shewhart)

Gorilla-compressed hot/cold store is queried transparently — user sees a continuous series regardless of whether data comes from hot or cold store (Phase 10).

### 6.2 Session / Acceptance Report (#48)

**[Generate Report]** button → opens report wizard:
1. Select time range
2. Select collectors to include
3. Select metrics to include
4. Choose format: JSON / CSV / HTML
5. Preview summary
6. **[Export]** → downloads file with embedded SHA-256 hash of content

Report content:
- Targets monitored (name, IP, check types)
- Uptime % per target per collector
- Anomaly events with RCA verdicts
- Baseline deviation summary (p50/p95 vs baseline)
- WiFi survey summary (if WiFi data selected)
- Config in effect at report time (snapshot of check plan)
- Tamper-evident content hash (SHA-256 of JSON payload, included in HTML footer)

### 6.3 Evidence Bundles (#47)

**Evidence Freeze** — triggered from RCA Panel or from this view:

```
POST /api/collectors/<id>/evidence/freeze
```

Bundle contents (JSON telemetry only — no full PCAP unless WiFi capture was active):
- Timestamp + collector ID + triggering anomaly ID
- Last 15 minutes of all metric streams (from hot store)
- Active anomaly context + RCA output
- Current check plan
- Interface counters snapshot
- WireGuard peer state snapshot
- If WiFi active: last completed PCAP file SHA-256 + AP/client table snapshot
- SHA-256 of the entire bundle

Bundle list view shows all frozen bundles:
| Timestamp | Collector | Trigger | Size | Hash | Actions |
|---|---|---|---|---|---|
| 2026-07-25 13:44 | homelab-pi4 | RTT_ANOMALY | 2.1 MB | abc...def | [Download] [Verify] |

**[Verify]** recomputes SHA-256 and confirms tamper-evidence.

### 6.4 Disk Reserve Policy

Configurable in System Config but surfaced as status here:
- Current capture partition usage / total
- Reserve floor (default 500 MB) — hard floor: evidence freeze is refused if it would breach this
- Retention policy: auto-delete bundles older than N days (configurable)
- Current retention countdown per bundle

---

## 7. Module E — System Config

### 7.1 Main System Settings (`/config`)

Tabbed settings panel:

#### Tab: General
- System name / description
- Dashboard listen address + port
- Dashboard TLS (enable/disable, cert paths)
- Session timeout
- Log level
- NTP server (for system-wide time sync validation)

#### Tab: Alert Routing

Extends existing `dashboard/settings.py` alerting:
- Webhook URLs (test button sends a test payload)
- SMTP configuration (host, port, TLS, credentials, recipient list)
- Alertmanager endpoint
- Alert confidence thresholds:
  - `>0.8` → auto-alert via all configured channels
  - `0.6–0.8` → flagged probable in dashboard only
  - `<0.6` → raw symptoms only, no notification
- Alert suppression rules: silence by collector/target/time window
- Edge-trigger vs. level-trigger toggle per alert type

#### Tab: PKI & mTLS

- CA certificate details (subject, expiry, fingerprint)
- **[Rotate CA]** (generates new CA, marks old as expired, triggers re-enrollment reminder for all collectors)
- Issued certificates table (collector ID, expiry, revocation status)
- **[Revoke]** per certificate
- Enrollment endpoint URL (shown for operator to use in `scripts/enroll-collector.sh`)
- Auto-renewal window: collectors re-enroll when `days_remaining < N` (default 14)

#### Tab: MDP Scheduler

- Base probe interval (default 30s)
- State transition thresholds:
  - `STABLE → SUSPECT`: loss % threshold + RTT multiplier
  - `SUSPECT → DEGRADED`: consecutive confirm count
  - `DEGRADED → DOWN`: consecutive full-loss count
- Per-collector check plan override (push custom plan)
- MDP state table: shows current state per target across all collectors
- Phase 12 Deep RL toggle (when available): enable/disable DQN scheduler, show shadow mode metrics vs finite-state MDP

#### Tab: Probe Budget

- Total probes/minute budget (Frank-Wolfe allocation, Phase 5)
- Per-collector budget allocation table
- Variance-weighted target list: shows which targets are consuming the most budget and why
- Override: pin specific targets to fixed intervals regardless of budget

#### Tab: Gorilla Store

- Hot window size (default 26h)
- Cold retention (default 14d)
- Compaction job schedule
- Current storage usage: hot bytes / cold bytes / total
- Compression ratio per collector (measured from Phase 10 instrumentation)
- **[Force Compaction]** button

#### Tab: Prometheus & Grafana

- Prometheus scrape target configuration (auto-generated for `monitor/` metrics endpoint)
- Grafana URL (for dashboard link in Module C)
- Metric series enable/disable toggles
- Export current Grafana dashboard JSON

#### Tab: OTLP / gRPC Transport

- Batch size (default 60s window)
- Retry queue depth (default 500 batches)
- Backoff config: base, max, jitter
- Per-collector last export status (success/failure, last batch timestamp)

---

## 8. Module F — Dangerous Actions

**Access:** Admin role only. Amber persistent warning banner when accessed.

This is the P5 governance surface from the main ROADMAP. Each item is **gated and refused by design** — the dashboard surfaces the action, documents its risk, and requires explicit acknowledgement, but the underlying destructive behaviour is not implemented.

### 8.1 Gate Structure

A master switch (`dangerous_actions_enabled: false` in config) must be turned on before any individual action can be acknowledged. Turning on the master switch writes to the audit trail.

Each action requires:
1. Master switch ON
2. Click action → risk description shown
3. Type confirmation phrase
4. Click **[Acknowledge & Attempt]**
5. System responds: **"This action is governed and refused by design."** + writes to audit trail

### 8.2 Governed Actions Table

| Action | Risk Level | Status |
|---|---|---|
| Automatic subnet expansion | High | Gated — refused by design |
| Vulnerability / exploit scanning | Critical | Gated — refused by design |
| Credential guessing / default-password checks | Critical | Gated — refused by design |
| SNMP community sweeps | Medium | Gated — refused by design |
| Wi-Fi deauthentication | High | Gated — refused by design |
| Wi-Fi frame injection | Critical | Gated — refused by design |
| Wi-Fi AP impersonation (rogue/evil-twin) | Critical | Gated — refused by design |
| S7 / OPC UA writes | Critical | Gated — refused by design |
| PLC mode changes / program operations | Critical | Gated — refused by design |
| Arbitrary OPC UA node browsing | High | Gated — refused by design |
| Inline blocking / automatic production changes | Critical | Gated — refused by design |
| Internet dashboard exposure | High | Gated — refused by design |

### 8.3 Audit Trail

All access to this module, all master switch toggles, all action acknowledgement attempts, and all collector control commands (network changes, WireGuard changes, tool installs) are written to an immutable append-only audit log:

```json
{
  "ts": "2026-07-25T13:44:00Z",
  "user": "admin",
  "action": "collector_network_change",
  "collector_id": "homelab-pi4",
  "detail": { "interface": "eth0", "new_address": "192.168.1.51/24" },
  "result": "success"
}
```

Audit log is viewable in this module. Exportable as JSON. SHA-256 chain: each entry includes hash of previous entry.

---

## 9. API Reference Summary

### Collector Control API (proxied by dashboard → collector agent)

```
GET    /api/collectors                          — list all collectors
GET    /api/collectors/<id>                     — collector detail + live state
POST   /api/collectors/<id>/network             — update interface IP
POST   /api/collectors/<id>/wireguard/restart   — force WG re-handshake
POST   /api/collectors/<id>/wireguard/config    — update WG peer config
POST   /api/collectors/<id>/tools/install       — install a tool via apt/apk
POST   /api/collectors/<id>/tools/detect        — re-scan installed tools
POST   /api/collectors/<id>/diagnostic          — run a pre-approved diagnostic
POST   /api/collectors/<id>/check_plan          — push new check plan
POST   /api/collectors/<id>/evidence/freeze     — freeze evidence bundle
GET    /api/collectors/<id>/evidence            — list evidence bundles
GET    /api/collectors/<id>/evidence/<bundle_id> — download bundle
```

### WiFi API

```
GET    /api/collectors/<id>/wifi/adapters        — list WiFi adapters
POST   /api/collectors/<id>/wifi/monitor-mode    — enable/disable monitor mode
POST   /api/collectors/<id>/wifi/channel         — set channel
GET    /api/collectors/<id>/wifi/scan            — AP scan results (SSE)
GET    /api/collectors/<id>/wifi/clients         — client table (SSE)
GET    /api/collectors/<id>/wifi/spectrum        — channel utilisation
POST   /api/collectors/<id>/wifi/capture/start   — start PCAP
POST   /api/collectors/<id>/wifi/capture/stop    — stop PCAP
GET    /api/collectors/<id>/wifi/captures        — list completed files
GET    /api/collectors/<id>/wifi/captures/<file> — download PCAP
GET    /api/collectors/<id>/wifi/anomalies       — WiFi anomaly events (SSE)
```

### Monitor API

```
GET    /api/monitor/topology                     — graph JSON (D3 format)
GET    /api/monitor/stream                       — SSE: live state updates
GET    /api/monitor/anomalies                    — anomaly event list
GET    /api/monitor/rca/<anomaly_id>             — RCA detail
GET    /api/monitor/latency-clients              — eBPF high-latency table
GET    /api/monitor/mdp-states                   — all target MDP states
```

### Reports API

```
POST   /api/reports/generate                     — generate session report
GET    /api/reports/<id>                         — download report
GET    /api/reports/bundles                      — evidence bundle list
GET    /api/reports/storage                      — disk usage / reserve status
```

### System Config API

```
GET    /api/system/config                        — full system config JSON
PUT    /api/system/config                        — update config
GET    /api/pki/ca                               — CA cert
POST   /api/pki/enroll                           — collector enrollment
DELETE /api/pki/revoke/<collector_id>            — revoke cert
GET    /api/pki/certs                            — issued cert list
GET    /api/system/audit                         — audit log
GET    /api/system/gorilla-stats                 — compression stats
```

---

## 10. Frontend File Structure

```
dashboard/
├── app.py                        # Flask app factory, route registration (existing — extend)
├── auth.py                       # Session auth (existing)
├── alerts.py                     # Alert routing (existing — extend for confidence gating)
├── settings.py                   # Settings store (existing — extend)
├── history.py                    # Time-series queries (existing — extend for Gorilla)
├── metrics.py                    # Prometheus metrics (existing)
├── dangerous.py                  # Dangerous actions gate (existing — extend)
├── config_validation.py          # Config schema validation (existing)
│
├── collector_manager.py          # NEW — Module A: per-collector control
├── wifi_analyser.py              # NEW — Module B: WiFi control + analysis
├── live_monitor.py               # NEW — Module C: topology + anomaly + RCA
├── reports.py                    # NEW — Module D: reports + evidence bundles
├── system_config.py              # NEW — Module E: main system config
├── pki_manager.py                # NEW — PKI / cert lifecycle
├── audit_log.py                  # NEW — immutable audit trail
│
├── templates/
│   ├── base.html                 # Layout with sidebar nav + alert strip
│   ├── monitor/
│   │   ├── index.html            # Topology map + anomaly timeline
│   │   ├── rca_panel.html        # RCA side panel (htmx partial)
│   │   └── latency_clients.html  # High-latency client table
│   ├── collectors/
│   │   ├── list.html             # Collector list with status badges
│   │   ├── detail.html           # Tabbed detail panel
│   │   ├── tab_overview.html     # Overview tab
│   │   ├── tab_network.html      # Network interfaces tab
│   │   ├── tab_wireguard.html    # WireGuard tab
│   │   ├── tab_tools.html        # Tools & eBPF tab
│   │   ├── tab_diagnostics.html  # Diagnostics tab with terminal
│   │   ├── tab_checkplan.html    # Check plan editor
│   │   └── tab_pki.html          # PKI tab
│   ├── wifi/
│   │   ├── index.html            # WiFi analyser main view
│   │   ├── adapters.html         # Adapter management
│   │   ├── scanner.html          # AP/SSID scanner table
│   │   ├── spectrum.html         # Channel spectrum chart
│   │   ├── clients.html          # Client table
│   │   └── capture.html          # PCAP control panel
│   ├── history/
│   │   ├── index.html            # Time-series browser
│   │   ├── reports.html          # Report generation wizard
│   │   └── bundles.html          # Evidence bundle list
│   └── config/
│       ├── index.html            # System config tabs
│       ├── pki.html              # PKI management
│       ├── mdp.html              # MDP scheduler config
│       └── dangerous.html        # Dangerous actions governance
│
├── static/
│   ├── js/
│   │   ├── topology.js           # D3.js topology map
│   │   ├── timeline.js           # Anomaly swim-lane chart
│   │   ├── spectrum.js           # WiFi channel spectrum chart
│   │   ├── terminal.js           # WebSocket terminal panel
│   │   └── sse.js                # SSE connection management
│   └── css/
│       └── dashboard.css         # Styling
│
└── requirements.txt              # Flask, Jinja2, httpx (collector proxy), htmx (CDN)
```

---

## 11. Collector-Side Control Agent API

The Go collector exposes a local control HTTP server (bound to `127.0.0.1` or WireGuard tunnel IP only, never public internet):

```go
// collector/control_server.go
// Listens on: cfg.ControlAddr (default "127.0.0.1:9101" or wg tunnel IP)
// Auth: shared HMAC secret (same mechanism as existing self-update HMAC)

POST /control/network        — apply IP address change to interface
POST /control/wireguard      — update WireGuard config / restart peer
POST /control/tools/install  — run apt-get install for allowlisted packages
POST /control/tools/detect   — re-scan and return tool inventory
POST /control/diagnostic     — run allowlisted diagnostic command, stream output
POST /control/check_plan     — replace active check plan
POST /control/wifi/monitor   — set adapter monitor mode
POST /control/wifi/channel   — set channel on monitor interface
POST /control/wifi/capture   — start/stop dumpcap
GET  /control/wifi/scan      — return iw scan dump JSON
GET  /control/wifi/adapters  — return iw list parsed JSON
GET  /control/state          — return full current state snapshot
POST /control/evidence       — freeze evidence bundle
```

**Security model:**
- Control server only binds to loopback or WireGuard tunnel address
- All requests require `X-Control-HMAC` header (SHA-256 HMAC of body + timestamp, same secret as self-update)
- Replay protection: timestamp in request must be within ±30 seconds of collector clock
- All tool installs allowlisted: only `iw`, `aircrack-ng`, `dumpcap`, `tshark`, `traceroute`, `clang` (for eBPF toolchain) are permitted
- All exec commands allowlisted (read-only diagnostic commands only)
- All actions written to collector-local audit log (`/var/log/analyseLaptop-control.log`)

---

## 12. Real-Time Communication Architecture

```
  Browser
    │
    ├─ SSE  GET /api/monitor/stream    → live topology state + anomaly events
    ├─ SSE  GET /api/collectors/<id>/wifi/scan → live AP table
    ├─ SSE  GET /api/collectors/<id>/wifi/anomalies → WiFi anomaly events
    ├─ WS   /ws/collectors/<id>/terminal → interactive diagnostics shell
    │
  Dashboard (Flask)
    │
    ├─ SSE producer: reads from monitor/ event queue (shared memory / Redis-less ring buffer)
    ├─ HTTP proxy: forwards /api/collectors/<id>/... → collector control server
    │
  Collector (Go)
    │
    ├─ Control server: 127.0.0.1:9101 (HMAC-auth REST)
    ├─ Push: OTLP/gRPC → monitor/ aggregator (existing pipeline)
    └─ WiFi: dumpcap + iw scan (subprocess management)
```

**No Redis required.** The SSE producer thread in the dashboard reads from `monitor/`'s SQLite hot store (shared mount or local API call). This keeps the deployment footprint at: Python dashboard process + SQLite — consistent with the existing architecture.

---

## 13. Implementation Phases

The dashboard is implemented incrementally, aligned with the main system roadmap:

| Dashboard Phase | Aligns With | Features |
|---|---|---|
| **D1** (Wk 17–18) | Main Ph6 | Live Monitor topology + anomaly timeline + RCA panel; extends existing `app.py` |
| **D2** (Wk 18–19) | Main Ph6 | Collector Manager: list, overview, network tab, WireGuard tab |
| **D3** (Wk 19–20) | Main Ph6 | Collector Manager: diagnostics tab, check plan editor, tools tab |
| **D4** (Wk 20–21) | Main Ph6–7 | History & Reports: time-series browser, session report (#48), evidence bundles (#47); Prometheus/Grafana links |
| **D5** (Wk 21–22) | Main Ph8 | System Config: general, alert routing, PKI tab, audit log |
| **D6** (Wk 22–23) | WiFi | WiFi Analyser: adapter mgmt, AP scanner, spectrum, client table, PCAP control |
| **D7** (Wk 24–27) | Main Ph9 | PKI Manager: CA lifecycle, cert revocation, mTLS status per collector |
| **D8** (Wk 27–29) | Main Ph10 | Gorilla store UI: storage stats, compression ratio, compaction trigger |
| **D9** (Wk 29–31) | Main Ph11 | eBPF flow telemetry view: flow table, high-latency client table |
| **D10** (Wk 31–35) | Main Ph12 | Deep RL shadow mode panel: DQN vs MDP comparison, training corpus stats |

---

## 14. Key Design Principles

1. **Read-only by default.** All mutating actions require explicit user initiation. No automated changes to collector configuration without dashboard instruction.

2. **Fail-safe collector connectivity.** If the dashboard loses connectivity to a collector, the collector continues operating independently with its last check plan. The dashboard reflects the loss of connectivity as a DEGRADED or DOWN state — it does not attempt to remediate automatically.

3. **WireGuard-first connectivity for remote collectors.** The control server binds to the WireGuard tunnel IP for remote collectors, ensuring all management traffic is encrypted even without mTLS.

4. **Audit everything.** Every state-changing operation from the dashboard — IP changes, WireGuard config, tool installs, check plan pushes, evidence freezes — is written to the immutable audit trail before being executed.

5. **OT safety preserved.** The check plan editor enforces IEC 62443 constraints at the schema level: Modbus targets can only have FC01/FC03 function codes, rate limits are enforced, and no write commands are ever sent to OT devices.

6. **P5 governance is non-negotiable.** The Dangerous Actions module provides the governance surface. None of the gated capabilities (deauth, injection, impersonation, exploit scanning, PLC writes) are implemented in any code path — they are refused at the API layer regardless of UI state.

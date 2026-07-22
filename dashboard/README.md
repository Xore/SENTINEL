# Local dashboard

The dashboard is a thin local control and results surface. It does not contain a general shell endpoint. Targets come only from `config/targets.csv`; interface names and numeric limits are validated; every task has a timeout.

## Development run

On the Ubuntu probe:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r dashboard/requirements.txt
PROBE_CAPTURE_DIR="$PWD/captures" waitress-serve --listen=127.0.0.1:8088 dashboard.app:app
```

Open it through an SSH tunnel:

```bash
ssh -L 8088:127.0.0.1:8088 probe-user@probe-address
```

Then browse to `http://127.0.0.1:8088`. Localhost is the default bind for a
development run. For a real install, the systemd installer can bind to the
management-LAN address behind an access token — see "Dashboard exposure and
access token" in the top-level [README](../README.md). The transport stays
plain HTTP (token-authenticated); acceptable on a trusted management network,
never through a port-forward to the internet.

## First laptop installation

From the repository root, review and run:

```bash
sudo ./scripts/install-dashboard-service.sh --apply
./scripts/verify-probe.sh
```

The installer is intentionally limited to Ubuntu 24.04. It installs the core packages, creates an unprivileged `probe-dashboard` account, configures a private virtual environment and state directories, enables non-root Dumpcap through the Wireshark group, installs the systemd service (localhost by default, or the management-LAN address with a generated access token when run with `PROBE_EXPOSE=lan`), and preserves an existing `/etc/network-probe/targets.csv`.

## Capture permission

The web process must not run as root. On Ubuntu, reconfigure the Wireshark package to allow non-root capture, add the dedicated service account to the `wireshark` group, log out/reboot so membership takes effect, and verify `dumpcap -D` as that account:

```bash
sudo dpkg-reconfigure wireshark-common
sudo usermod -aG wireshark probe-dashboard
getcap /usr/bin/dumpcap
sudo -u probe-dashboard dumpcap -D
```

Grant the account write permission only to the chosen capture directory. Do not grant passwordless general `sudo`.

## Current API jobs

- Status: interfaces, drops/errors, disk, installed tools and approved targets
- Capture: bounded PCAPNG ring on a no-IP interface
- Summary: TShark/capinfos report for a stored capture
- Endpoint: one allow-listed TCP connect check
- Route: tracepath to an allow-listed endpoint
- Wi-Fi: local `iw` interface/link state
- Health sample: short passive Layer-2/protocol report
- Snapshot: hashed local support/configuration bundle
- Monitor: outage series/events, service and port checks, throughput and routes (read-only from the monitor DB)
- Traffic generator: bounded, allow-listed TCP/UDP send with optional expected-response check
- Discovery: broad-view LAN host inventory (IP/MAC/vendor/name) of a connected subnet, discovery-only
- Wi-Fi survey: AP/channel/band/security list plus per-channel occupancy (needs the radio enabled)
- Security (IDS): recent Suricata signature alerts and engine status, read-only from `eve.json` (needs `scripts/install-ids.sh`); alerts are filterable by severity/text/source/destination and every IP is click-to-dossier
- Neighbours (LLDP): switch/port/VLAN the probe is plugged into, from a receive-only lldpd (needs `scripts/install-neighbors.sh`)
- SNMP: read-only single-host `snmpget`/`snmpwalk` probe (system group + interface list) using credentials stored in Settings
- IP dossier: click any IP (in discovery, neighbours, alerts, assets, scope) to open everything the probe knows about it — reverse-DNS, whether it is one of our own interfaces, approved-scope/traffic-allow membership, LLDP neighbour match, outage-monitor ping stats, every Suricata alert with it as source or destination, and its full scan/action history. Trace, SNMP and TCP reachability are explicit buttons inside the dossier (clicking an IP no longer auto-traces)
- Actions: a custom-target console — enter any IP/port (or pick a known IT/OT service, including your own saved custom services) and run TCP reachability, service health, trace, SNMP, add-to-scope or add-to-allow-list against it; plus the traffic generator with an in-page, dashboard-editable allow-list
- Service health: a read-only DNS/clock/TCP/TLS/HTTP profile for one host+port — one resolver query (answers, server, timing), the probe's chrony clock (stratum/offset/leap), a bounded TCP connect, and — only on standard web/TLS ports — the TLS certificate (subject/issuer/SANs/days-to-expiry, version, cipher) and an HTTP status + connection-timing breakdown. Safe active: one connect/handshake/GET, no OT payloads, results saved like any job
- Custom services (Settings): save named ports (name + port + tcp/udp) that persist across restarts and appear in the Actions service picker under “Custom”
- Activity result viewer: every action runs server-side and is saved; open **View result** on any finished job to re-render its result later (discovery host table, Wi-Fi survey, SNMP table, or raw output) without staying on the launching page
- Assets: the persistent inventory of every host the probe has observed or scanned (vendor/MAC/name, sources, first/last seen) and a durable scan/action history log — click a host for its per-host history
- Attention (Overview): live data-freshness chips and an aggregated anomaly feed (stale feeds, open outages, packet loss, high-severity IDS alerts, NIC drops, LLDP topology drift, newly-seen hosts)
- Alert drill-down: click any Suricata alert's **Details** to see every correlated EVE event for its `flow_id` — for HTTP the domain/subdomain, path, method, status, every request/response header and the request/response **body text** (POSTed form fields, JSON payloads) when Suricata buffered it (`install-ids.sh` sets `dump-all-headers: both` plus `http-body`/`http-body-printable`); DNS queries/answers; TLS SNI/subject/issuer/fingerprint; fileinfo; flow counters; plus the raw JSON of all events. Body text appears on alerted transactions (Suricata only reassembles a body when a rule inspects it — passive plain-HTTP events without an alert don't buffer one) and only for cleartext HTTP; HTTPS stays opaque (TLS handshake/SNI only). No on-disk file extraction is used, so the probe stays passive
- ntopng: passive flow analysis with its own web UI, linked from Overview once installed via `scripts/install-ntopng.sh`

### Known IT/OT service catalog

The Actions dropdowns are driven by `dashboard/services.py`: common IT services
(ssh, dns, http/https, snmp, rdp, …) and OT/ICS protocols (S7/102, Modbus/502,
DNP3/20000, EtherNet-IP/44818, PROFINET/34964, OPC UA/4840, BACnet/47808,
FINS/9600, IEC-104/2404, MQTT/1883, …). OT entries are flagged so the UI warns
before touching them — only inside a change window. Reachability stays TCP
connect only (no UDP raw scan, version detection or scripts); UDP is exercised
only through the payload-gated traffic generator.

### History store

The dashboard writes its own SQLite database at
`/var/lib/network-probe/probe-web.db` (`PROBE_WEB_DB`), separate from the
monitor-owned read-only `monitor.db`. It holds the host inventory, scan/action
log, a persistent job copy and the LLDP inventory + change log. A background
poller (`PROBE_LLDP_POLL_SECONDS`, default 120; disable with
`PROBE_DISABLE_POLLER=1`) keeps the neighbour inventory and topology-drift
detection current even when nobody has the page open. All history writes are
best-effort — a failure to record never breaks a request.

## Settings (persistent, dashboard-editable)

The **Settings** view writes to `/var/lib/network-probe/settings.json` (mode
0600, the only web-writable path). Everything there survives restarts:

- **Interface capture overrides** — every interface can be toggled capture-on/off
  from the dashboard, not just no-IP interfaces. Interfaces are auto-enumerated
  every refresh, so hot-plugged USB Wi-Fi/Ethernet adapters appear on their own
  and are labelled by bus (USB/PCI) and kind (wired/wireless).
- **SNMP credentials** — v2c community or v3 user/auth/priv. Secrets are stored
  0600 and never returned to the browser (the API reports only whether each is
  set); submitting a blank secret keeps the stored value.
- **Approved scope** — discovered endpoints can be promoted into the approved
  target scope with one button (or removed), merged with the file-based
  `targets.csv` allow-list.
- **Custom services** — operator-defined named ports (name + port + tcp/udp),
  stored in `custom_services` and merged into the known IT/OT catalogue so they
  show up in the Actions service picker.

## Access-token rotation

The token is rotated on every service (re)start (`ExecStartPre=+` →
`scripts/rotate-dashboard-token.sh`), so restarting the dashboard deauthenticates
any browser still holding the old token. Retrieve the current one with
`sudo cat /etc/network-probe/dashboard-token`.

Deeper 802.11 management-frame capture is an operator sudo tool
(`scripts/wifi-monitor-capture.sh`), not a web job — monitor mode needs
`CAP_NET_ADMIN` and the web process stays unprivileged.

See [../ARCHITECTURE.md](../ARCHITECTURE.md) for the planned scheduler, history/baselines, service profiles and authenticated device adapters.

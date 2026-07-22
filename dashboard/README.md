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
- Security (IDS): recent Suricata signature alerts and engine status, read-only from `eve.json` (needs `scripts/install-ids.sh`)

Deeper 802.11 management-frame capture is an operator sudo tool
(`scripts/wifi-monitor-capture.sh`), not a web job — monitor mode needs
`CAP_NET_ADMIN` and the web process stays unprivileged.

See [../ARCHITECTURE.md](../ARCHITECTURE.md) for the planned scheduler, history/baselines, service profiles and authenticated device adapters.

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

Then browse to `http://127.0.0.1:8088`. Localhost binding is intentional. Do not bind to all interfaces until authenticated HTTPS and management firewall rules are in place.

## First laptop installation

From the repository root, review and run:

```bash
sudo ./scripts/install-dashboard-service.sh --apply
./scripts/verify-probe.sh
```

The installer is intentionally limited to Ubuntu 24.04. It installs the core packages, creates an unprivileged `probe-dashboard` account, configures a private virtual environment and state directories, enables non-root Dumpcap through the Wireshark group, installs the localhost-only systemd service, and preserves an existing `/etc/network-probe/targets.csv`.

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

See [../ARCHITECTURE.md](../ARCHITECTURE.md) for the planned scheduler, history/baselines, service profiles and authenticated device adapters.

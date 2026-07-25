# Unified setup

The front door for installing the Network Probe. One orchestrator,
[`scripts/setup.sh`](../scripts/setup.sh), drives every component installer in the
right order. It changes nothing itself — it previews a plan and then runs the real
per-component scripts (each with its own `--apply`), so you can always see exactly
what will happen first.

> Target OS is **Ubuntu 24.04 LTS**. Most components install a systemd service under
> a shared unprivileged `probe-dashboard` account with state in
> `/var/lib/network-probe` and config in `/etc/network-probe`.

## Node roles

| Role | What it is | Components |
|---|---|---|
| **standalone** | A self-sufficient node: full dashboard + backend + local collection. Also the **aggregator** that remote collectors push to. | base tools, dashboard, outage monitor, reconciler, LLDP neighbours |
| **full** | Standalone plus the passive traffic-analysis add-ons. | standalone + Suricata IDS, IDS adapter, ntopng |
| **collector** | A slim push-only node: collection workers that push to a remote aggregator. No local dashboard. | collector push-agent |

See [[../ROADMAP.md]] and the multi-node design in
[07-network-map-and-monitoring-roadmap.md](07-network-map-and-monitoring-roadmap.md).

## Quick start

Preview a standalone node (safe, no root, nothing applied):

```bash
./scripts/setup.sh --standalone --dry-run
```

Apply it for real (components need root):

```bash
sudo ./scripts/setup.sh --standalone --apply
```

Pick components à la carte, or use the interactive menu:

```bash
sudo ./scripts/setup.sh --component dashboard --component ids --apply
sudo ./scripts/setup.sh            # interactive menu
```

List everything available:

```bash
./scripts/setup.sh --list
```

### LAN exposure & login

By default the dashboard binds to loopback with auth disabled (local desktop use).
To expose it on the LAN and require a login, set `PROBE_EXPOSE=lan` for the
dashboard install:

```bash
sudo PROBE_EXPOSE=lan ./scripts/setup.sh --component dashboard --apply
```

It binds the default-route interface's IPv4 address on port 8088 and turns on the
username/password login (default **admin / admin** — change it under
**Settings → Account** immediately; the salted hash lives in
`/var/lib/network-probe/dashboard-auth.json`). HTTP only: use it on trusted
management networks, never port-forward to the internet. See
[[dashboard-auth-plan]] for the auth model.

### Split frontend / backend (optional)

By default one process serves both the API and the UI on port 8088. Set
`PROBE_SPLIT=1` for the dashboard install to run them as two systemd units: the
**backend** (API + all collection) on loopback `127.0.0.1:8090`, and a thin
**frontend proxy** (`dashboard.frontend`) on the public bind `:8088` that serves
the static shell and reverse-proxies `/api` to the backend.

```bash
sudo PROBE_EXPOSE=lan PROBE_SPLIT=1 ./scripts/setup.sh --component dashboard --apply
```

Auth is unchanged — the backend session login is the single source of truth in
both modes; the proxy adds no auth of its own, it just forwards the `np_session`
cookie. If the backend restarts, the shell keeps rendering and API calls return
`502 {"backend":false}` so the UI can show an offline banner instead of going
blank. Re-running the installer without `PROBE_SPLIT=1` collapses back to the
single-process unit (and removes the backend unit).

## Enrolling a collector

A collector is a separate machine that pushes to a standalone aggregator.

1. On the **aggregator**: open **Collectors → Enroll collector**. Copy the ingest
   key shown **once**, and make sure *accept external collectors* is enabled.
2. On the **collector machine**, run setup with the aggregator URL and that key:

```bash
sudo AGGREGATOR_URL=http://<aggregator-ip>:8088 INGEST_KEY=<key-from-enroll> \
     ./scripts/setup.sh --collector --apply
```

The collector pings the aggregator every few cycles and pushes its interfaces,
neighbours and the operator-configured checks. Its discovered devices then appear
on the aggregator's **Network Map**, tagged to that collector — narrow the map to
one collector with the toolbar's *all collectors / <id>* selector. Revoke or rotate
a collector's key any time from **Collectors** (revoking drops its data from the
map). See [[network-map]] and [[analyse-laptop-deploy]].

## Passwordless access to a lab box

For **trusted lab machines you own**, one command from your workstation sets up
key-based SSH plus passwordless sudo so you can deploy and re-run installers
without retyping a password:

```bash
./scripts/lab-access-bootstrap.sh --host 192.168.50.33 --user adminuser
```

It generates an ed25519 keypair (`~/.ssh/analyse_lab`) if you don't have one,
installs the **public** key on the box, then runs
[`scripts/lab-grant-access.sh`](../scripts/lab-grant-access.sh) there to make the
key install idempotent and drop a validated `/etc/sudoers.d/90-analyse-<user>`
granting NOPASSWD sudo. The **only** step that asks for the box's password is the
one-time `ssh-copy-id` — you type it; once the key is in, everything else is
non-interactive. The private key never leaves your workstation.

To undo it on the box:

```bash
sudo ./scripts/lab-grant-access.sh --user adminuser --revoke
```

> This is a deliberate convenience for disposable lab hosts. Do **not** point it
> at production machines — NOPASSWD sudo removes the password check for that user.

## Components

| id | Installer | Notes |
|---|---|---|
| `lightweight` | [install-lightweight.sh](../scripts/install-lightweight.sh) | base packages & CLI tools (see [02-install-lightweight.md](02-install-lightweight.md)) |
| `dashboard` | [install-dashboard-service.sh](../scripts/install-dashboard-service.sh) | the web dashboard + API systemd service |
| `monitor` | [install-outage-monitor.sh](../scripts/install-outage-monitor.sh) | continuous reachability monitor (shares the dashboard user/venv) |
| `reconciler` | [install-reconciler.sh](../scripts/install-reconciler.sh) | privileged reconciler for safe, auto-rolling-back network changes |
| `neighbours` | [install-neighbors.sh](../scripts/install-neighbors.sh) | lldpd for LLDP/CDP neighbour discovery (receive-only) |
| `ids` | [install-ids.sh](../scripts/install-ids.sh) | Suricata passive IDS (AF_PACKET, never inline) |
| `ids-adapter` | [install-ids-adapter.sh](../scripts/install-ids-adapter.sh) | auto-follows a usable capture NIC for the IDS |
| `ntopng` | [install-ntopng.sh](../scripts/install-ntopng.sh) | passive flow analyser with its own web UI |
| `desktop` | [install-desktop-launcher.sh](../scripts/install-desktop-launcher.sh) | double-click launchers — **run as your normal desktop user** |
| `collector` | [install-collector.sh](../scripts/install-collector.sh) | slim push-agent (needs `AGGREGATOR_URL` + `INGEST_KEY`) |

`setup.sh` runs selected components in the order above (dependencies first — e.g.
the dashboard before the monitor). Every underlying installer is idempotent and
safe to re-run. When `setup.sh` runs the `desktop` launchers under `sudo`, it
installs them for `$SUDO_USER`, not root.

## Verifying

After applying, sanity-check the box and the running services:

```bash
./scripts/preflight.sh        # environment/tooling checks
./scripts/verify-probe.sh     # service + endpoint checks
./scripts/run-tests.sh        # Go + Python + setup.sh test suite (for developers)
```

Operational guidance (captures, Wi-Fi, day-to-day) lives in
[03-capture-and-wifi.md](03-capture-and-wifi.md) and
[04-operations.md](04-operations.md).

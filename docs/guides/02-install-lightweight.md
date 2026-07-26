# Install — v2 Collector Dependencies

This guide covers installing the system-level dependencies required by the v2 Python
collector on a fresh node. All Python package dependencies are handled by
`collector/requirements.txt` and bundled into the PyInstaller binary — only the
system tools listed here need to be installed manually.

> **Full setup walkthrough:** [`00-setup.md`](00-setup.md)

---

## System packages (Linux)

```bash
sudo apt-get update
sudo apt-get install -y \
    python3.12 python3.12-venv python3-pip \
    iw \
    ethtool \
    iproute2 \
    dnsutils \
    snmp \
    mtr-tiny \
    curl \
    git
```

| Package | Used by | Notes |
|---|---|---|
| `python3.12` + `python3.12-venv` | All collector Python code | Required |
| `iw` | `checks/net_wifi_linux.py` | Wi-Fi link stats + AP scan |
| `ethtool` | Interface capability inspection | Needed for NIC offload check |
| `iproute2` | `checks/net_mtr.py`, route table reads | `ip -j route` |
| `dnsutils` | `checks/net_dns.py` test tooling | `dig` for manual validation |
| `snmp` | `checks/net_snmp.py` test tooling | `snmpget` for manual validation |
| `mtr-tiny` | Manual route validation | Not used by collector code itself |
| `curl` | PKI enrolment validation | Manual testing only |
| `git` | Cloning the repo | Build from source only |

---

## Optional: eBPF flow tracking (Phase C13)

`bcc` Python bindings are **not** bundled by PyInstaller and must be installed as a
system package on nodes where eBPF flow tracking is enabled. Requires kernel ≥5.8.

```bash
# Debian / Ubuntu / Raspberry Pi OS (64-bit Bookworm)
sudo apt-get install -y python3-bpfcc

# RHEL / Rocky Linux
sudo dnf install -y python3-bcc
```

If `python3-bpfcc` is absent, the collector skips Phase C13 checks and logs a
structured warning — all other checks continue normally.

> **Research gate:** Before enabling Phase C13 on Raspberry Pi, complete research
> task R2 in [`docs/gap-analysis/research-guide-for-gap-topics.md`](../gap-analysis/research-guide-for-gap-topics.md).

---

## Python venv (development / build from source)

When running from source or building the PyInstaller binary:

```bash
cd analyseLaptop/collector
python3.12 -m venv .venv
source .venv/bin/activate          # Linux/macOS
# .venv\Scripts\activate           # Windows

pip install -r requirements.txt
pip install -r requirements-dev.txt  # adds pytest, mypy, ruff, pyinstaller
```

The production binary produced by PyInstaller bundles all `requirements.txt`
dependencies; the venv is only needed for development and CI builds.

---

## Windows

```powershell
# Python 3.12 from https://python.org (add to PATH during install)
python -m venv .venv
.venv\Scripts\activate
pip install -r collector\requirements.txt
```

Windows-specific checks (`net_wifi_windows.py`, `os_health/windows.py`) use
`netsh` and `psutil` — both available without extra installs. `iw`, `ethtool`,
and `mtr-tiny` are Linux-only and not required on Windows.

---

## Raspberry Pi specific notes

- **64-bit Raspberry Pi OS (Bookworm)** is the recommended image — required for
  Phase C13 (eBPF; kernel ≥5.8).
- **32-bit images** are supported for Phases 1–C12 but eBPF (Phase C13) is
  unavailable; the collector degrades gracefully.
- SD card I/O is the main bottleneck — use a Class 10 / A1-rated card and ensure
  `data_dir` (lmdb + sqlite3 cold store) is on the fastest available storage.
- `python3.12` may need backport installation on older Bookworm images:

```bash
sudo add-apt-repository ppa:deadsnakes/ppa   # Ubuntu only
# On Raspberry Pi OS: python3.12 is in Bookworm main repos
sudo apt-get install -y python3.12 python3.12-venv
```

---

## Verify installation

```bash
# Python version
python3.12 --version           # expect: Python 3.12.x

# iw available
iw --version                   # expect: iw version x.x

# Collector binary help (pre-built)
./analyselaptop-collector --help

# From source: run test suite
pytest collector/tests/ -v
```

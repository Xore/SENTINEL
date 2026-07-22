"""Port probes with expected responses.

A "probe" opens a connection to host:port, optionally sends a small, protocol-
appropriate request, reads the first response bytes, and checks them against an
expected pattern. It returns (ok, duration_ms, detail).

Two design rules:

1. Well-known ports have a built-in probe and an expected response, so a bare
   `name,host,port` line in monitor-ports.csv is enough to get a meaningful
   health check ("does an HTTP server answer with a status line", "does SSH
   present a banner"). See WELL_KNOWN.

2. OT / control-system ports (S7, Modbus, PROFINET, OPC UA, EtherNet/IP) are
   marked connect-only: the probe proves a listener accepts a TCP connection
   and sends NO application bytes. Injecting protocol payloads into a PLC is a
   safety risk and is out of scope by default (see the README safety boundary).
   A custom expect string never overrides connect-only for these ports.

Custom services override everything: give an explicit send/expect (and udp
flag) in the config and this module uses them verbatim.
"""
from __future__ import annotations

import re
import socket
import ssl
import time
from dataclasses import dataclass, field


@dataclass
class ProbeSpec:
    send: bytes = b""            # bytes to send after connect ({host} is substituted)
    expect: str = ""            # regex matched against the decoded response (empty = connect is enough)
    udp: bool = False           # datagram instead of stream
    tls: bool = False           # wrap the stream in TLS before sending
    connect_only: bool = True   # do not send application bytes (OT safety default when no send)
    read_bytes: int = 512
    label: str = ""


# Well-known ports: a bare host:port gets these automatically.
# OT/control ports are connect_only with no send bytes, on purpose.
WELL_KNOWN: dict[int, ProbeSpec] = {
    20: ProbeSpec(expect=r"^220", connect_only=False, label="ftp-data"),
    21: ProbeSpec(expect=r"^220[ -]", connect_only=False, label="ftp"),
    22: ProbeSpec(expect=r"^SSH-\d", connect_only=False, label="ssh"),
    23: ProbeSpec(expect="", connect_only=False, label="telnet"),
    25: ProbeSpec(expect=r"^220[ -]", connect_only=False, label="smtp"),
    53: ProbeSpec(connect_only=False, label="dns-tcp"),  # handled specially below
    80: ProbeSpec(send=b"GET / HTTP/1.0\r\nHost: {host}\r\nUser-Agent: network-probe\r\nConnection: close\r\n\r\n",
                  expect=r"^HTTP/\d", connect_only=False, label="http"),
    110: ProbeSpec(expect=r"^\+OK", connect_only=False, label="pop3"),
    111: ProbeSpec(connect_only=False, label="rpcbind"),
    123: ProbeSpec(udp=True, connect_only=False, label="ntp"),  # handled specially below
    143: ProbeSpec(expect=r"^\* OK", connect_only=False, label="imap"),
    161: ProbeSpec(udp=True, connect_only=True, label="snmp"),  # connect-only: no community sweep
    389: ProbeSpec(connect_only=False, label="ldap"),
    443: ProbeSpec(send=b"GET / HTTP/1.0\r\nHost: {host}\r\nUser-Agent: network-probe\r\nConnection: close\r\n\r\n",
                   expect=r"^HTTP/\d", tls=True, connect_only=False, label="https"),
    445: ProbeSpec(connect_only=False, label="smb"),
    465: ProbeSpec(tls=True, expect=r"^220[ -]", connect_only=False, label="smtps"),
    587: ProbeSpec(expect=r"^220[ -]", connect_only=False, label="submission"),
    993: ProbeSpec(tls=True, expect=r"^\* OK", connect_only=False, label="imaps"),
    995: ProbeSpec(tls=True, expect=r"^\+OK", connect_only=False, label="pop3s"),
    1433: ProbeSpec(connect_only=False, label="mssql"),
    1883: ProbeSpec(connect_only=False, label="mqtt"),
    3306: ProbeSpec(expect=r"mysql|maria", connect_only=False, label="mysql"),
    3389: ProbeSpec(connect_only=False, label="rdp"),
    5432: ProbeSpec(connect_only=False, label="postgresql"),
    5900: ProbeSpec(expect=r"^RFB \d", connect_only=False, label="vnc"),
    6379: ProbeSpec(send=b"PING\r\n", expect=r"\+PONG", connect_only=False, label="redis"),
    8080: ProbeSpec(send=b"GET / HTTP/1.0\r\nHost: {host}\r\nUser-Agent: network-probe\r\nConnection: close\r\n\r\n",
                    expect=r"^HTTP/\d", connect_only=False, label="http-alt"),
    8443: ProbeSpec(send=b"GET / HTTP/1.0\r\nHost: {host}\r\nUser-Agent: network-probe\r\nConnection: close\r\n\r\n",
                    expect=r"^HTTP/\d", tls=True, connect_only=False, label="https-alt"),
    9100: ProbeSpec(connect_only=False, label="jetdirect"),
    # OT / control systems: connect-only, no injected payloads.
    102: ProbeSpec(connect_only=True, label="s7comm/iso-tsap"),
    502: ProbeSpec(connect_only=True, label="modbus"),
    2222: ProbeSpec(connect_only=True, label="ethernet-ip-udp"),
    4840: ProbeSpec(connect_only=True, label="opc-ua"),
    20000: ProbeSpec(connect_only=True, label="dnp3"),
    34962: ProbeSpec(connect_only=True, label="profinet-rt"),
    44818: ProbeSpec(connect_only=True, label="ethernet-ip"),
    47808: ProbeSpec(udp=True, connect_only=True, label="bacnet"),
}

OT_PORTS = {port for port, spec in WELL_KNOWN.items() if spec.connect_only and not spec.udp} | {102, 502, 4840, 44818, 34962, 20000, 2222}


def spec_for(port: int, send: bytes | None, expect: str | None, udp: bool, tls: bool) -> ProbeSpec:
    """Merge an explicit config override onto the well-known default."""
    base = WELL_KNOWN.get(port, ProbeSpec(connect_only=(port in OT_PORTS), label=f"port-{port}"))
    spec = ProbeSpec(send=base.send, expect=base.expect, udp=base.udp, tls=base.tls,
                     connect_only=base.connect_only, read_bytes=base.read_bytes, label=base.label)
    if udp:
        spec.udp = True
    if tls:
        spec.tls = True
    # A custom send/expect is honored EXCEPT on OT connect-only ports.
    if send is not None or expect is not None:
        if port in OT_PORTS:
            spec.label += " (connect-only enforced; custom payload ignored for OT port)"
        else:
            spec.connect_only = False
            if send is not None:
                spec.send = send
            if expect is not None:
                spec.expect = expect
    return spec


def _dns_query(host: str, port: int, timeout: float) -> tuple[bool, float | None, str]:
    # Minimal DNS A query for "localhost." over TCP to prove the resolver answers.
    header = b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"  # id 0x1234, RD set, 1 question
    qname = bytes([len("localhost")]) + b"localhost" + b"\x00"
    payload = header + qname + b"\x00\x01\x00\x01"  # QTYPE A, QCLASS IN
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(len(payload).to_bytes(2, "big") + payload)
            reply = sock.recv(512)
    except OSError as exc:
        return (False, None, str(exc)[:180])
    elapsed = round((time.monotonic() - started) * 1000, 1)
    # A valid DNS reply echoes the transaction id (bytes 2-3 after the 2-byte length prefix).
    matched_id = len(reply) >= 4 and reply[2:4] == b"\x12\x34"
    return (matched_id, elapsed if matched_id else None,
            f"dns responded {len(reply)}B" if matched_id else f"unexpected reply {len(reply)}B")


def _ntp_query(host: str, port: int, timeout: float) -> tuple[bool, float | None, str]:
    packet = b"\x1b" + 47 * b"\0"  # LI=0 VN=3 Mode=3 (client)
    started = time.monotonic()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(packet, (host, port))
        data, _ = sock.recvfrom(48)
        sock.close()
        elapsed = (time.monotonic() - started) * 1000
        stratum = data[1] if len(data) > 1 else 0
        return (len(data) >= 48, round(elapsed, 1), f"ntp stratum={stratum}")
    except OSError as exc:
        return (False, None, str(exc)[:180])


def run_probe(host: str, port: int, spec: ProbeSpec, timeout: float = 5.0) -> tuple[bool, float | None, str]:
    """Execute one probe. Returns (ok, duration_ms, detail)."""
    if port == 53 and not spec.udp and spec.connect_only is False and not spec.send:
        return _dns_query(host, port, timeout)
    if spec.udp and port == 123:
        return _ntp_query(host, port, timeout)

    started = time.monotonic()
    try:
        if spec.udp:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            payload = spec.send.replace(b"{host}", host.encode()) if spec.send else b"\x00"
            sock.sendto(payload, (host, port))
            try:
                data, _ = sock.recvfrom(spec.read_bytes)
            except socket.timeout:
                sock.close()
                # No reply is normal for many UDP services; treat send success as reachable-unknown.
                return (spec.expect == "", round((time.monotonic() - started) * 1000, 1),
                        "udp: sent, no reply (open|filtered)")
            sock.close()
            text = data.decode("latin-1", "replace")
            return _match(spec, text, started, extra=f"udp {len(data)}B")

        sock = socket.create_connection((host, port), timeout=timeout)
        detail_prefix = ""
        if spec.tls:
            tls_started = time.monotonic()
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            sock = context.wrap_socket(sock, server_hostname=host)
            detail_prefix = f"tls={ (time.monotonic() - tls_started) * 1000:.0f}ms "
        sock.settimeout(timeout)

        if spec.connect_only:
            sock.close()
            return (True, round((time.monotonic() - started) * 1000, 1),
                    f"{detail_prefix}connect ok ({spec.label})".strip())

        if spec.send:
            sock.sendall(spec.send.replace(b"{host}", host.encode()))
        data = b""
        try:
            while len(data) < spec.read_bytes:
                chunk = sock.recv(spec.read_bytes - len(data))
                if not chunk:
                    break
                data += chunk
                if spec.expect and re.search(spec.expect, data.decode("latin-1", "replace"), re.MULTILINE):
                    break
        except socket.timeout:
            pass
        sock.close()
        text = data.decode("latin-1", "replace")
        return _match(spec, text, started, extra=detail_prefix.strip())
    except ssl.SSLError as exc:
        return (False, None, f"tls error: {exc}"[:180])
    except OSError as exc:
        return (False, None, str(exc)[:180])


def _match(spec: ProbeSpec, text: str, started: float, extra: str = "") -> tuple[bool, float | None, str]:
    duration = round((time.monotonic() - started) * 1000, 1)
    first_line = text.splitlines()[0][:120] if text.strip() else "(no data)"
    if not spec.expect:
        return (bool(text), duration, f"{extra} recv: {first_line}".strip())
    if re.search(spec.expect, text, re.MULTILINE):
        return (True, duration, f"{extra} matched /{spec.expect}/ -> {first_line}".strip())
    return (False, duration, f"{extra} expected /{spec.expect}/, got: {first_line}".strip())

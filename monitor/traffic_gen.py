"""Bounded traffic generator for custom ports and custom data.

Sends a controlled number of TCP or UDP messages to an allow-listed
host:port, with a payload given as literal text, hex, or a fixed size of
zero/random bytes. Optionally checks each response against an expected
pattern. Built for path/port testing and light load generation - NOT for
fuzzing, flooding, or OT payload injection.

Guard rails (all enforced here, not just in the UI):
- Destinations must appear in the allow-list file (config/traffic-gen-allow.csv,
  "host,port,proto"). OT/control ports are refused outright.
- Hard caps: <= MAX_COUNT messages, <= MAX_RATE per second, payload
  <= MAX_PAYLOAD bytes, total run <= MAX_DURATION seconds.
- One destination per run; no ranges, no sweeps.

CLI (used by the dashboard, args validated again here):
  traffic_gen.py --host H --port P --proto tcp|udp --count N --rate R
                 [--data STR | --hex HEX | --size N [--random]]
                 [--expect REGEX] [--allow FILE] [--timeout S]
Prints a JSON summary on stdout.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import socket
import ssl  # noqa: F401 - imported so probes.py TLS constants resolve if reused
import sys
import time
from pathlib import Path

MAX_COUNT = int(os.environ.get("PROBE_TRAFFIC_MAX_COUNT", "1000"))
MAX_RATE = float(os.environ.get("PROBE_TRAFFIC_MAX_RATE", "100"))
MAX_PAYLOAD = int(os.environ.get("PROBE_TRAFFIC_MAX_PAYLOAD", "65507"))
MAX_DURATION = float(os.environ.get("PROBE_TRAFFIC_MAX_DURATION", "60"))
ALLOW_FILE = Path(os.environ.get("PROBE_TRAFFIC_ALLOW", "/etc/network-probe/traffic-gen-allow.csv"))

# Never generate traffic to these ports even if listed: OT/control safety.
FORBIDDEN_PORTS = {102, 502, 4840, 44818, 34962, 20000, 2222, 47808, 161}


def load_allow(path: Path) -> set[tuple[str, int, str]]:
    allowed: set[tuple[str, int, str]] = set()
    if not path.is_file():
        return allowed
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(line for line in handle if line.strip() and not line.lstrip().startswith("#")):
            if len(row) != 3:
                continue
            host, port_text, proto = (value.strip() for value in row)
            if port_text.isdigit() and proto in {"tcp", "udp"}:
                allowed.add((host, int(port_text), proto))
    return allowed


def build_payload(args: argparse.Namespace) -> bytes:
    if args.hex is not None:
        cleaned = re.sub(r"[^0-9a-fA-F]", "", args.hex)
        if len(cleaned) % 2:
            raise ValueError("hex payload must have an even number of digits")
        return bytes.fromhex(cleaned)
    if args.data is not None:
        # Interpret common escapes so users can send CRLF-terminated commands.
        return args.data.encode("utf-8").decode("unicode_escape").encode("latin-1")
    if args.size is not None:
        if args.random:
            return os.urandom(args.size)
        return b"\x00" * args.size
    return b""


def validate(args: argparse.Namespace, payload: bytes, allowed: set) -> str | None:
    if args.port in FORBIDDEN_PORTS:
        return f"port {args.port} is a control-system port and is refused by policy"
    if (args.host, args.port, args.proto) not in allowed:
        return f"{args.host}:{args.port}/{args.proto} is not in the allow-list ({ALLOW_FILE})"
    if not 1 <= args.count <= MAX_COUNT:
        return f"count must be 1..{MAX_COUNT}"
    if not 0 < args.rate <= MAX_RATE:
        return f"rate must be >0 and <= {MAX_RATE}/s"
    if len(payload) > MAX_PAYLOAD:
        return f"payload {len(payload)}B exceeds {MAX_PAYLOAD}B"
    if args.proto == "udp" and len(payload) > 65507:
        return "UDP payload exceeds datagram limit"
    if args.count / args.rate > MAX_DURATION:
        return f"count/rate would run longer than {MAX_DURATION}s; lower count or raise rate"
    return None


def generate(args: argparse.Namespace, payload: bytes) -> dict:
    interval = 1.0 / args.rate
    sent = 0
    received = 0
    matched = 0
    errors: dict[str, int] = {}
    rtts: list[float] = []
    samples: list[str] = []
    deadline = time.monotonic() + MAX_DURATION
    expect = re.compile(args.expect) if args.expect else None

    def note_error(message: str) -> None:
        key = message[:80]
        errors[key] = errors.get(key, 0) + 1

    for index in range(args.count):
        if time.monotonic() > deadline:
            break
        slot = time.monotonic()
        start = time.monotonic()
        try:
            if args.proto == "tcp":
                with socket.create_connection((args.host, args.port), timeout=args.timeout) as sock:
                    sock.settimeout(args.timeout)
                    if payload:
                        sock.sendall(payload)
                    sent += 1
                    try:
                        reply = sock.recv(2048)
                    except socket.timeout:
                        reply = b""
            else:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(args.timeout)
                sock.sendto(payload, (args.host, args.port))
                sent += 1
                try:
                    reply, _ = sock.recvfrom(2048)
                except socket.timeout:
                    reply = b""
                sock.close()
            if reply:
                received += 1
                rtts.append((time.monotonic() - start) * 1000)
                if len(samples) < 3:
                    samples.append(reply[:120].decode("latin-1", "replace"))
                if expect and expect.search(reply.decode("latin-1", "replace")):
                    matched += 1
        except OSError as exc:
            note_error(str(exc))
        # pace to the requested rate
        wait = interval - (time.monotonic() - slot)
        if wait > 0 and index + 1 < args.count:
            time.sleep(wait)

    result = {
        "host": args.host, "port": args.port, "proto": args.proto,
        "payload_bytes": len(payload), "requested": args.count, "rate": args.rate,
        "sent": sent, "responses": received, "errors": errors,
        "response_samples": samples,
    }
    if rtts:
        result["rtt_ms"] = {"min": round(min(rtts), 2), "avg": round(sum(rtts) / len(rtts), 2), "max": round(max(rtts), 2)}
    if args.expect:
        result["expect"] = args.expect
        result["expect_matched"] = matched
        result["expect_ok"] = matched == received and received > 0
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded, allow-listed traffic generator.")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--proto", choices=("tcp", "udp"), default="tcp")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--rate", type=float, default=1.0)
    parser.add_argument("--data")
    parser.add_argument("--hex")
    parser.add_argument("--size", type=int)
    parser.add_argument("--random", action="store_true")
    parser.add_argument("--expect")
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--allow", default=str(ALLOW_FILE))
    args = parser.parse_args(argv)

    try:
        payload = build_payload(args)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2

    allowed = load_allow(Path(args.allow))
    problem = validate(args, payload, allowed)
    if problem:
        print(json.dumps({"error": problem}))
        return 2

    result = generate(args, payload)
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

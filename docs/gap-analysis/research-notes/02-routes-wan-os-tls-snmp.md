# Topic 2: Route Table, WAN Checks, OS Health, TLS, SNMP (Collector Phase 1)

Status: Research complete per `../research-guide-for-gap-topics.md` §2.

## Standards Reviewed

- RFC 7799 — defines active vs. passive metric terminology used consistently across `docs/collector/ROADMAP.md` and `docs/collector/SUGGESTIONS.md`; confirms route/WAN/OS checks below are all "active" methods requiring explicit rate limiting.
- RFC 1213 (SNMPv2-MIB) — confirms exact OID semantics already targeted in `SUGGESTIONS.md` §6.6: `sysDescr` (1.3.6.1.2.1.1.1.0), `sysUpTime` (1.3.6.1.2.1.1.3.0), `sysName` (1.3.6.1.2.1.1.5.0), `ifOperStatus` (1.3.6.1.2.1.2.2.1.8.N), `ifInErrors`/`ifOutErrors`.

## Platform Compatibility Findings

- `ip -j route` (JSON output) requires iproute2 ≥ v4.12. Older Raspberry Pi OS "Legacy"/Buster-era images may ship an older iproute2 and silently fail JSON parsing — flagged as an open compatibility risk that must be verified against the actual fleet's `iproute2 -V` before relying on `-j` in `net_routes.go`.
- Windows equivalent (`route print -4`) has no JSON mode; text parsing of the `0.0.0.0` default line remains necessary.
- `Get-NetAdapterStatistics` (Windows) and `/proc/net/dev` (Linux) both confirmed to work without elevation.

## WAN Check Safety

- `api.ipify.org` (default public-IP endpoint) publishes no documented hard rate limit for infrequent single-IP lookups, but polling at the default 30s collector interval across many collector nodes should be budgeted or replaced with a self-hosted alternative to avoid being blocklisted.
- Latency anchors (1.1.1.1, 8.8.8.8) are appropriate as absolute WAN baselines per the Wren/CoNEXT active-monitoring literature already cited in `SUGGESTIONS.md` §2.1.

## SNMP / TLS Validation Plan (Not Yet Executed)

- SNMP v2c/v3 credential model should reuse `monitor/snmp_probe.py`'s existing auth handling rather than reinventing it in Go, for consistency across the two systems.
- TLS cert-expiry check should be validated against the user's existing Traefik reverse-proxy endpoints once a live test window is available.

## Exit Criteria Status (per research guide §2)

- [x] Standards reviewed (RFC 7799, RFC 1213).
- [ ] 24-hour soak test against a real Raspberry Pi + Windows Server target — pending, requires live infrastructure access.
- [ ] iproute2 version check across fleet — pending.

## Next Implementation Step

Implement `collector/net_routes.go`, `collector/net_wan.go`, `collector/os_health.go` (+ `_linux`/`_windows` variants), `collector/tls_check.go`, and `collector/ot_snmp.go` per the file layout already defined in `docs/collector/SUGGESTIONS.md` §5, gated on the soak test above before merging to production use.

# Topic 3: OT Protocol Checks (Modbus, S7, BACnet, OPC-UA)


> **Language note (2026-07-30):** this research note predates the 2026-07-25 decision to
> write the v2 collector in Python (`docs/collector/SUGGESTIONS.md` §2). File names below
> are the Python modules; the findings themselves are language-independent.

**Status:** Research literature reviewed. Simulator prototype design ready. Hard safety gate (controls-owner sign-off) not yet obtained — this is a required pre-condition before any live OT query.

---

## Standards & Literature Summary

### IEC 62443-3-3 Key Takeaways
- Availability is the primary security property in OT; confidentiality is secondary.
- Active polling that can cause device state changes (even inadvertently) is **prohibited without explicit authorization**.
- Zone/conduit model: any collector crossing a Purdue-level boundary must be scoped to read-only function codes and must not open persistent TCP sessions to field devices without conduit-level approval.
- Relevant system requirements: SR 2.1 (authorization enforcement), SR 6.1 (audit logging of all active queries), SR 7.1 (DoS protection — polling rate limits are a hard requirement).

### Ollila 2024 (JAMK Thesis) — Protocol Gap Findings
- **Modbus TCP:** Widely monitored; FC01 (coil read) and FC03 (holding register read) are safe read-only codes. FC05/FC06/FC16 are write codes — must be blocked at the application layer, not just policy.
- **S7comm (Siemens):** Active query tools (e.g., s7-scan) can cause CPU load spikes or watchdog resets on older S315/S317 PLCs. Read operations using the SZL (System Status List) diagnostic items are safer but still require vendor confirmation per firmware version.
- **BACnet/IP:** `ReadProperty` (service 12) is safe read-only. `WriteProperty` (service 15) must be refused. Discovery via `WhoIs`/`IAm` is broadcast-based and is often already present on OT segments — passive observation of WhoIs/IAm is lower risk than initiating it.
- **OPC-UA:** `FindServers` and `GetEndpoints` (Part 4 §5.4/§5.5) are pre-session discovery calls that do not modify state and are explicitly designed for monitoring tooling. However, some legacy OPC-UA servers (e.g., older Kepware versions) have been observed to crash or log fault events on unexpected `FindServers` calls — verify with controls owner before use.

### RITICS/NCSC ICS-COI "How to log and monitor in ICS/OT Environments" (2024) — Appendix A
Key indicator classes relevant to this project:
- Unexpected protocol on expected port (Modbus on non-502 port)
- Unexpected function code in Modbus traffic
- OPC-UA session count increase beyond baseline
- BACnet WhoIs flood (> 5/min from a single source)
- S7 CPU STOP command observed

### OPC Foundation OPC-10000-6 §7.6 / Part 2 §7.2
- Well-known discovery endpoint: `opc.tcp://<host>:4840` (default, not guaranteed).
- `GetEndpoints` does not require an open session (anonymous call is valid per spec).
- Part 2 §7.2 security: `None` security mode for discovery is allowed but **production endpoints should require `Sign` or `SignAndEncrypt`** — do not infer that an anonymous-mode endpoint is intentionally open.

---

## Implementation Design (Pre-Approved Simulator Phase)

### Modbus TCP Read-Only Probe
```
Function codes allowed:  FC01 (Read Coils), FC02 (Read Discrete Inputs),
                          FC03 (Read Holding Registers), FC04 (Read Input Registers)
Function codes REFUSED:  FC05, FC06, FC15, FC16, FC22, FC23 (all write/mask codes)
Connection timeout:       2 s (do not hold open TCP sessions)
Max requests/min:         2 per target (well within any PLC connection table)
Error on write attempt:   return error, increment counter, do NOT retry
```

### S7comm Diagnostic Read (SZL only)
```
SZL items allowed:    0x0011 (CPU identification), 0x0131 (communication),
                      0x0232 (module diagnostics — read-only status)
SZL items AVOIDED:   Any item triggering mode change or forcing output
Firmware note:        Test against S7-1200/1500 first; S7-300/400 firmware < v3.3
                      has known SZL read hangs — skip those versions until verified.
```

### BACnet/IP ReadProperty Probe
```
Service allowed:   ReadProperty (12), ReadPropertyMultiple (14)
Service refused:   WriteProperty (15), ReinitializeDevice (20)
Discovery:         Passive WhoIs/IAm observation preferred over active WhoIs broadcast
Port:              UDP/47808 (BAC0)
```

### OPC-UA Discovery (FindServers / GetEndpoints)
```
Endpoint:         opc.tcp://<target>:4840 (configurable)
Calls allowed:    FindServers, GetEndpoints (pre-session, no active session opened)
Calls refused:    Browse, Read, Write, CreateSession (require approval)
Timeout:          3 s connect + 2 s response
Security mode:    None for discovery; log if server only advertises None for data endpoints
```

---

## Multi-Collector Polling Load Model

> This was flagged as **unmodeled** in `research-guide-for-gap-topics.md` §3.4. The following is the required written note.

For a deployment with `C` collectors each polling the same OT device at interval `T` seconds:

```
Requests/min per device = C × (60 / T)
```

Example: 3 collectors × 30s interval = **6 requests/min** per OT device.

Typical PLC connection-table limits:
- Siemens S7-1200: 16 simultaneous TCP connections, no documented request/min limit for diagnostic reads
- Modbus TCP servers (generic): 2–8 simultaneous connections typical; 10 req/min per connection is conservative
- BACnet/IP: UDP-based, effectively stateless — rate limit is device CPU, not connection table

**Conservative constraint:** Keep aggregate Modbus/S7 requests/min per device ≤ 10. With 30s intervals this allows up to 5 simultaneous collectors without risk. Document actual deployment count in `config/assets.csv` OT section.

---

## Simulator Test Plan (pymodbus)

```python
# Test harness outline — see scripts/ot_modbus_simulator_test.py (to be created at impl time)
# 1. Start pymodbus AsyncModbusTcpServer on localhost:5020
# 2. Run collector OT probe against it with FC01/FC03 — verify reads succeed
# 3. Inject a simulated FC06 write attempt — verify probe REFUSES (returns error, no write sent)
# 4. Kill simulator mid-read — verify collector does not crash, logs timeout
# 5. Verify zero write attempts in pymodbus server's request log
```

---

## Exit Criteria Status

- [ ] Simulator tests pass: FC01/FC03 reads succeed, FC05/FC06/FC16 writes blocked at application layer
- [ ] Zero write attempts possible under fault injection (crash, timeout, malformed response)
- [ ] Controls-owner sign-off obtained **in writing** before any query against production OT
- [ ] Multi-collector load calculation (see above) reviewed and accepted by controls owner
- [ ] Documented in `config/assets.csv` OT section: target addresses, approved function codes, max polling rate

## Next Implementation Step

Create `collector/checks/ot_modbus.py`, `collector/checks/ot_s7.py`, `collector/checks/ot_bacnet.py`, `collector/checks/ot_opcua.py` with read-only enforcement as specified above. Gate merge on simulator test pass + controls-owner sign-off.

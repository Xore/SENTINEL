# SNMP sysUpTime Regression Detection Theory
## Research Backlog Topic 9 — Basis for `collector` SNMP health checks (Phase 1e) and `monitor/snmp_probe.py`

> **Status:** Research document. Fills backlog item #9 ("SNMP sysUpTime regression").
> **Scope:** Correctly distinguishing a genuine device reboot from a 32-bit counter rollover or an SNMP-agent-only restart when polling `sysUpTime` for reboot/regression detection.

---

## Part 1 — The Problem

`sysUpTime` (`.1.3.6.1.2.1.1.3.0`, `DISMAN-EVENT-MIB::sysUpTimeInstance`, per RFC 1213) reports "the time since the network management portion of the system was last re-initialized" in hundredths of a second, as a 32-bit unsigned counter. This has two well-documented failure modes that a naive "if new_value < previous_value then reboot" rule will misclassify:

1. **Counter rollover, not a reboot.** A 32-bit counter in centiseconds wraps at \( 2^{32} - 1 \) ticks, i.e. approximately 497.1 days (Netdata, 2026, "SNMP counter rollover: fake traffic spikes from 32-bit counters"; multiple Cisco community and Zabbix forum threads document real operators mistaking this for a reboot alert). A device with 500+ days of genuine uptime will show `sysUpTime` reset to a small value with no reboot having occurred.
2. **SNMP-agent-only restart, not a device reboot.** `sysUpTime` technically measures the uptime of "the network management portion" of the device — i.e., the SNMP agent/daemon — not the underlying OS or hardware. If the SNMP daemon is restarted independently (config reload, agent crash-restart, `snmpEngineID` reconfiguration) `sysUpTime` resets even though the device itself never rebooted (Cisco Community, "SNMP: get the date and time when the router was reinitialized").

### 1.1 Why This Matters for This Project

The collector's roadmapped OS-health/SNMP checks (`SUGGESTIONS.md` §6.6/6.10, `collector/ROADMAP.md` Phase 1e) intend to use uptime regression as a reboot/instability signal feeding into the outage-classification and RCA pipeline (`docs/rca-causal-inference.md`). A false "device rebooted" classification triggered by a rollover, once every ~497 days per monitored device, is a low-frequency but highly misleading false positive that would corrupt the historical events table used for the MDP scheduler's threshold-validation dataset (per `docs/mdp-adaptive-scheduling-theory.md` §4.2's 30-day backtest requirement) if left unhandled.

---

## Part 2 — The Standard Mitigation: A Second, Non-Wrapping Time Source

### 2.1 `snmpEngineTime` (SNMP-FRAMEWORK-MIB)

`snmpEngineTime` (`.1.3.6.1.6.3.10.2.1.3.0`) reports seconds (not centiseconds) since `snmpEngineBoots` last changed, and per Cisco's own documentation will not wrap for approximately 135 years — explicitly designed to outlive the `sysUpTime` rollover problem (Cisco Community thread on CSCdm72652; PacketPushers, "Catch Unexpected Reboots Through Monitoring sysUpTimeInstance"). Cisco's official workaround (bug CSCdm72652) is to poll both `sysUpTime` and `snmpEngineTime` together and use `snmpEngineTime`'s non-wrapping seconds count to disambiguate a genuine long-uptime rollover from a real reboot.

**Caveat (important for a mixed-vendor fleet):** `snmpEngineTime` resets whenever `snmpEngineBoots` changes, which happens on SNMPv3 engine-ID reconfiguration in addition to device reboot — so it has the same "agent vs. device" ambiguity as `sysUpTime`, just not the same rollover period. It also is not universally implemented (community reports of "No Such Object" on some devices, per the Checkmk forum thread), so the collector must treat its absence as expected on some targets, not an error.

### 2.2 `hrSystemUptime` (HOST-RESOURCES-MIB) as a Cross-Check

Where available, `hrSystemUptime` (`.1.3.6.1.2.1.25.1.1.0`) measures actual host/OS uptime rather than SNMP-agent uptime, and is the more semantically correct signal for "did the device reboot." It is also a 32-bit centisecond counter with the same rollover exposure as `sysUpTime`, but comparing the two together resolves the agent-vs-device ambiguity: if `sysUpTime` resets but `hrSystemUptime` does not, the SNMP agent restarted without a device reboot.

### 2.3 Decision Table

| Observation | Interpretation |
|---|---|
| `sysUpTime` decreases, `snmpEngineTime` also decreases by roughly the same wall-clock delta | Genuine device/agent reboot |
| `sysUpTime` decreases, `snmpEngineTime` continues increasing monotonically | `sysUpTime` counter rollover — not a reboot |
| `sysUpTime` decreases, `hrSystemUptime` (if present) does not decrease | SNMP agent-only restart — not a device reboot |
| `sysUpTime` decreases, `hrSystemUptime` (if present) also decreases | Genuine device reboot |
| `snmpEngineTime` or `hrSystemUptime` OID absent (`noSuchObject`) | Fall back to the rollover-arithmetic check in Part 3; do not treat absence as an error |

This table operationalizes the informal Cisco-community guidance into a deterministic classifier suitable for `collector/ot_snmp.go` / the roadmapped Phase 1e SNMP module.

---

## Part 3 — Fallback: Rollover Arithmetic When No Second Time Source Exists

Some SNMP agents genuinely expose only `sysUpTime` (the Checkmk and Zabbix forum threads both confirm this is common on lower-end/embedded devices). In that case the collector cannot disambiguate a reboot from a rollover using a second OID and must instead reason about elapsed wall-clock time between polls:

```go
// previousUptime, currentUptime: raw sysUpTime centisecond values (uint32)
// pollInterval: wall-clock time elapsed since previous poll (measured locally,
// not from the device -- this is the collector's own reliable clock)

const maxUint32Ticks = 4294967295 // 2^32 - 1, ~497.1 days in centiseconds

if currentUptime < previousUptime {
    // Counter decreased. Two explanations: rollover or reboot.
    // A rollover implies the device has been up for the whole poll interval
    // PLUS wrapped past 2^32 ticks -- i.e. previousUptime was already close to
    // the maximum and pollInterval alone could not explain a reset to a small
    // value via a genuine reboot occurring mid-interval.
    ticksElapsedIfNoReboot := (maxUint32Ticks - previousUptime) + currentUptime
    expectedTicksFromWallClock := pollInterval.Seconds() * 100 // centiseconds

    // Allow generous tolerance (SNMP polling jitter, network delay) -- e.g. 20%
    if math.Abs(float64(ticksElapsedIfNoReboot) - expectedTicksFromWallClock) 
        < 0.2 * expectedTicksFromWallClock {
        // The rollover hypothesis's implied elapsed ticks matches the
        // collector's own measured wall-clock interval -- this is a rollover,
        // not a reboot.
        return RegressionRollover
    }
    // Otherwise, the implied ticks-if-no-reboot don't match wall-clock time
    // at all (e.g. currentUptime is small and previousUptime was nowhere near
    // the 32-bit maximum) -- this is a genuine reboot.
    return RegressionReboot
}
```

This fallback is consistent with the Zabbix community's ad hoc "less than 497 days" heuristic but is more rigorous: rather than a fixed day-count cutoff (which produces a brief false-negative/false-positive window right around the 497-day mark), it checks whether the *specific* elapsed-ticks-if-rollover value is consistent with the collector's own independently measured wall-clock polling interval. This avoids the edge case the Zabbix heuristic has near the exact rollover boundary.

---

## Part 4 — Cold-Start Traps as a Complementary, Not Substitute, Signal

SNMP's `coldStart` trap (`.1.3.6.1.6.3.1.1.5.1`) is sent by a device when its SNMP agent reinitializes, and several Cisco community sources note this is "more real time" than uptime polling because it doesn't depend on the polling interval catching the reboot window. However, per RFC 3413 traps are unacknowledged UDP datagrams and are explicitly unreliable — a trap can be lost to network congestion or firewall drop with no retransmission, so `docs/ot-protocol-safety-theory.md`'s and this project's read-only-polling-first posture is consistent with treating polled `sysUpTime`-regression detection as the reliable primary signal and any received `coldStart` trap as a confirming secondary signal, never the sole reboot-detection mechanism.

---

## Part 5 — Implementation Checklist

| Item | File | Status |
|---|---|---|
| Poll `sysUpTime` + `snmpEngineTime` + `hrSystemUptime` together where available, not `sysUpTime` alone | `collector` SNMP module (Phase 1e, unbuilt) | Add when building Phase 1e |
| Implement the Part 2.3 decision table as the primary classifier | same | Add when building Phase 1e |
| Implement the Part 3 wall-clock-consistency fallback for agents lacking a second time source | same | Add when building Phase 1e |
| Treat `coldStart` trap receipt as confirming, not authoritative, evidence | same | Add when building Phase 1e |
| Feed only confirmed-reboot events (not rollover false positives) into the events table used by `docs/mdp-adaptive-scheduling-theory.md` §4.2's outage dataset | `monitor/outage_monitor.py` / aggregator | Cross-check when Phase 1e ships |

---

## References

1. RFC 1213. "Management Information Base for Network Management of TCP/IP-based internets: MIB-II." §6.3 (`sysUpTime`).
2. RFC 3413. "Simple Network Management Protocol (SNMP) Applications." §on Notification/trap delivery being unacknowledged.
3. Netdata. "SNMP counter rollover: fake traffic spikes from 32-bit counters." 2026. https://www.netdata.cloud/guides/network/network-snmp-counter-rollover/
4. PacketPushers. "Catch Unexpected Reboots Through Monitoring sysUpTimeInstance." https://packetpushers.net/blog/catch-unexpected-reboots-through-monitoring-sysuptimeinstance/
5. Cisco Community. "SNMP: get the date and time when the router was reinitialized" (CSCdm72652 discussion). https://community.cisco.com/t5/network-management/snmp-get-the-date-and-time-when-the-router-was-reinitialized/td-p/951993
6. Cisco Community. "Question about show version uptime vs. snmp OID 1.3.6.1..." https://community.cisco.com/t5/network-management/question-about-show-version-uptime-vs-snmp-oid-1-3-6-1-2-1-1-3-0/td-p/1371104
7. Network Engineering Stack Exchange. "Distinguish between router reload and 'sysUpTime' SNMP counter wrap." https://networkengineering.stackexchange.com/questions/19167/
8. Zabbix Forums. "SNMP uptime overflow after 497 days." 2016. https://www.zabbix.com/forum/zabbix-help/47245-snmp-uptime-overflow-after-497-days
9. Checkmk Forum. "Any plan to handle 497+ days of uptime with SNMP?" 2021. https://forum.checkmk.com/t/any-plan-to-handle-497-days-of-uptime-with-snmp/28387
10. Broadcom Knowledge Base. "Understanding the Spectrum Attributes sysUpTime." 2023. https://knowledge.broadcom.com/external/article/116729/

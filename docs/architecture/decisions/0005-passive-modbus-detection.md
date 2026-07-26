# ADR 0005 — Passive Modbus Write Detection

- **Status:** Accepted
- **Date:** 2026-07-26

## Decision

Generic eBPF flow counters remain payload-free. Passive Modbus write detection is
a separate bounded parser attached to allow-listed OT interfaces. It inspects
only the MBAP header and function-code byte needed to classify FC05, FC06, FC15,
and FC16, then emits a metadata event:

- timestamp;
- collector/site identity;
- source/destination IP;
- transaction direction;
- function code;
- interface;
- parser version.

It must not export register values or retain packet payload. Truncated,
fragmented, encrypted, or ambiguous traffic is reported as unclassified rather
than guessed.

Active Modbus operations are read-only, explicitly enabled, rate-limited, and
restricted to the hub-designated OT owner for the target. No code path accepts a
write function code.

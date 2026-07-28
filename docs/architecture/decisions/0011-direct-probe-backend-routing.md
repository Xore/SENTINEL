# ADR 0011 — Direct Probe-to-Backend Routing

- **Status:** Accepted
- **Date:** 2026-07-28

## Context

SENTINEL deploys collectors inside monitored sites and sends telemetry to the
site-local backend. Earlier planning documents also treated an overlay tunnel
as a monitored product capability and, in some examples, as a possible
collector transport dependency. That creates unnecessary credential,
privilege, platform, failure-mode, and operational scope.

The deployment model guarantees that every installed probe has an ordinary IP
route to its configured site backend.

## Decision

Every deployed collector:

- is configured with one site-backend endpoint reachable through the site's
  ordinary routed network;
- sends OTLP/gRPC directly to that endpoint using the existing mTLS identity
  boundary;
- does not require SENTINEL to provision or manage an overlay tunnel;
- does not inspect tunnel peers, handshakes, endpoints, keys, or traffic; and
- fails deployment readiness when the configured backend route cannot be
  established.

SENTINEL has no tunnel-specific probe, metric family, API, alert, ML feature
group, RCA rule, package dependency, capability, or release artifact.

Direct routability is not an assertion of continuous availability. Collectors
retain bounded local storage, retry with backoff, and idempotent replay for
temporary backend, DNS, routing, or link failures. Site services remain
autonomous from the optional global tier.

## Consequences

- Probe-to-backend transport has one supported topology and one mTLS security
  boundary.
- Installation and readiness checks must validate DNS resolution, TCP
  reachability, TLS trust, and authenticated OTLP exchange to the configured
  site backend.
- Network-path monitoring uses general ICMP, TCP, HTTP, DNS, latency, MTR, and
  interface telemetry rather than tunnel-control-plane inspection.
- Operators may use independently managed network technologies beneath the IP
  route, but those technologies are outside SENTINEL's configuration,
  monitoring, credentials, support contract, and threat model.

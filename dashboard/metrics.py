"""Prometheus / OpenMetrics text rendering for the probe (roadmap P4).

Pure formatting: `render(data)` turns an already-collected snapshot dict into the
Prometheus text exposition format (version 0.0.4). The app endpoint gathers the
snapshot from the monitor DB / history / IDS log and hands it here, which keeps
this module trivially unit-testable with synthetic data and free of any I/O.

Everything exported is read-only observability data the dashboard already shows;
nothing here launches a scan or touches a device.
"""
from __future__ import annotations

from typing import Iterable

_METRIC_NAME_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def _label_value(value: object) -> str:
    """Escape a label value per the exposition format (\\, \", newline)."""
    text = "" if value is None else str(value)
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(pairs: Iterable[tuple[str, object]]) -> str:
    inner = ",".join(f'{k}="{_label_value(v)}"' for k, v in pairs if v is not None and str(v) != "")
    return f"{{{inner}}}" if inner else ""


def _num(value: object) -> str | None:
    """Format a number for exposition, or None to skip the sample."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    if f.is_integer():
        return str(int(f))
    return repr(f)


class _Writer:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self._declared: set[str] = set()

    def metric(self, name: str, help_text: str, mtype: str) -> None:
        assert all(c in _METRIC_NAME_OK for c in name), f"bad metric name {name!r}"
        if name in self._declared:
            return
        self._declared.add(name)
        self.lines.append(f"# HELP {name} {help_text}")
        self.lines.append(f"# TYPE {name} {mtype}")

    def sample(self, name: str, value: object, labels: Iterable[tuple[str, object]] = ()) -> None:
        formatted = _num(value)
        if formatted is None:
            return
        self.lines.append(f"{name}{_labels(labels)} {formatted}")

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


def render(data: dict) -> str:
    """Render a snapshot dict to Prometheus text.

    Expected (all optional) keys:
      info      {version, role}
      targets   [{name, group, up, rtt_ms, loss_pct}]
      services  [{name, kind, up, duration_ms}]
      interfaces[{interface, rx_dropped, tx_dropped, rx_errors, tx_errors, multicast}]
      events    {open, total_24h}
      ids       {alerts_24h, alerts_total}
      collectors{count, enabled}
      scrape    {monitor_up: 0|1}
    """
    w = _Writer()

    info = data.get("info") or {}
    w.metric("network_probe_build_info", "Build/role info; constant 1.", "gauge")
    w.sample("network_probe_build_info", 1,
             [("version", info.get("version", "dev")), ("role", info.get("role", "standalone"))])

    scrape = data.get("scrape") or {}
    w.metric("network_probe_monitor_up",
             "1 if the outage-monitor database is present and readable.", "gauge")
    w.sample("network_probe_monitor_up", scrape.get("monitor_up", 0))

    targets = data.get("targets") or []
    if targets:
        w.metric("network_probe_target_up", "1 if the target is currently up.", "gauge")
        for t in targets:
            w.sample("network_probe_target_up", t.get("up"),
                     [("target", t.get("name")), ("group", t.get("group"))])
        w.metric("network_probe_target_rtt_ms", "Recent average RTT in milliseconds.", "gauge")
        for t in targets:
            w.sample("network_probe_target_rtt_ms", t.get("rtt_ms"),
                     [("target", t.get("name")), ("group", t.get("group"))])
        w.metric("network_probe_target_loss_ratio", "Recent packet loss ratio (0..1).", "gauge")
        for t in targets:
            w.sample("network_probe_target_loss_ratio", t.get("loss_pct"),
                     [("target", t.get("name")), ("group", t.get("group"))])

    services = data.get("services") or []
    if services:
        w.metric("network_probe_service_up", "1 if the last service check passed.", "gauge")
        for s in services:
            w.sample("network_probe_service_up", s.get("up"),
                     [("service", s.get("name")), ("kind", s.get("kind"))])
        w.metric("network_probe_service_duration_ms", "Last service check duration (ms).", "gauge")
        for s in services:
            w.sample("network_probe_service_duration_ms", s.get("duration_ms"),
                     [("service", s.get("name")), ("kind", s.get("kind"))])

    interfaces = data.get("interfaces") or []
    if interfaces:
        for field, help_text in (
            ("rx_dropped", "Interface RX dropped packets (cumulative)."),
            ("tx_dropped", "Interface TX dropped packets (cumulative)."),
            ("rx_errors", "Interface RX errors (cumulative)."),
            ("tx_errors", "Interface TX errors (cumulative)."),
            ("multicast", "Interface multicast packets (cumulative)."),
        ):
            metric = f"network_probe_iface_{field}_total"
            w.metric(metric, help_text, "counter")
            for iface in interfaces:
                w.sample(metric, iface.get(field), [("interface", iface.get("interface"))])

    events = data.get("events") or {}
    w.metric("network_probe_events_open", "Currently open outage events.", "gauge")
    w.sample("network_probe_events_open", events.get("open", 0))
    w.metric("network_probe_events_24h", "Outage events started in the last 24h.", "gauge")
    w.sample("network_probe_events_24h", events.get("total_24h", 0))

    ids = data.get("ids") or {}
    if ids:
        w.metric("network_probe_ids_alerts_24h", "IDS alerts in the last 24h.", "gauge")
        w.sample("network_probe_ids_alerts_24h", ids.get("alerts_24h"))

    collectors = data.get("collectors") or {}
    if collectors:
        w.metric("network_probe_collectors", "Enrolled remote collectors.", "gauge")
        w.sample("network_probe_collectors", collectors.get("count"))
        w.metric("network_probe_collectors_enabled", "Enabled remote collectors.", "gauge")
        w.sample("network_probe_collectors_enabled", collectors.get("enabled"))

    return w.text()

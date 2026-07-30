"""Collector configuration — pydantic models + layered loader + SIGHUP reload.

Precedence (highest wins): explicit init kwargs > process env / ``.env`` >
optional YAML config file > model defaults. Env vars use the ``__`` nested
delimiter, so ``WIFI__ENABLED=true`` maps to ``settings.wifi.enabled`` and
``BACKEND__URL=...`` maps to ``settings.backend.url``.

Never read ``os.environ`` directly elsewhere in the collector — always resolve
configuration through :func:`load_settings` so validation, defaults, and test
overrides all flow through one place. Schema mirrors
``docs/collector/COLLECTOR-V2-REFACTOR.md`` §9.
"""

from __future__ import annotations

import ipaddress
import math
import os
import re
import signal
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, Field, ValidationError, ValidationInfo, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from collector.utils.thread_pool import default_worker_count

# Env var naming the YAML config file, if the caller doesn't pass one explicitly.
CONFIG_ENV_VAR = "COLLECTOR_CONFIG"

# ADR 0009 — site_id/collector_id are lower-case RFC 1123 DNS labels
# (1-63 chars). Every database key, API authorization query, metric
# validation path, and federation envelope relies on this same identity
# rule, so it is rejected here rather than silently coerced (e.g. lower-
# cased) — a silent transform would let an operator believe they configured
# "Site-A" when the system actually identifies the node as "site-a".
_DNS_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def _validate_dns_label(value: str, field_name: str) -> str:
    if not _DNS_LABEL_RE.match(value):
        raise ValueError(
            f"{field_name} must be a lowercase RFC 1123 DNS label 1-63 characters "
            f"long, matching [a-z0-9]([a-z0-9-]*[a-z0-9])? (ADR 0009): got {value!r}"
        )
    return value


class ConfigError(Exception):
    """Raised when configuration cannot be loaded or fails validation."""


# docs/contracts/METRICS.md: at most 32 targets per probe family, so the
# operator-assigned target_id label stays within its stated cardinality budget.
_MAX_TARGETS_PER_FAMILY = 32

# A deliberately lenient hostname check (not full RFC 1123): rejects empty,
# whitespace-padded, control-character, or absurdly long values without
# implementing a complete DNS-name grammar.
_HOSTNAME_RE = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$")

# docs/contracts/METRICS.md's DNS record_type allow-list — restricted to this
# set so record_type can safely be a metric label (never arbitrary response
# data).
_ALLOWED_DNS_RECORD_TYPES = frozenset({"A", "AAAA", "CNAME", "MX", "NS", "PTR", "SRV", "TXT"})


def _validate_host(value: str) -> str:
    """A probe target host must be a syntactically valid IPv4/IPv6 address or
    hostname — not empty, not whitespace-padded, no control characters."""
    if not value or value != value.strip():
        raise ValueError(f"host must be a non-empty, non-whitespace-padded value: got {value!r}")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        if len(value) > 253 or not _HOSTNAME_RE.match(value):
            raise ValueError(
                f"host must be a valid IP address or hostname: got {value!r}"
            ) from None
    return value


def _validate_icmp_host(value: str) -> str:
    value = _validate_host(value)
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return value
    if address.version != 4:
        raise ValueError("ICMP and latency probes currently support IPv4 only")
    return value


def _validate_finite_timeout(value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        raise ValueError("timeout_s must be a positive finite number")
    return value


def _validate_target_url(value: str) -> str:
    """An HTTP probe target must be an absolute http(s) URL."""
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"url must be an absolute http:// or https:// URL: got {value!r}")
    return value


def _validate_target_list(targets: list[Any], family: str) -> list[Any]:
    """Shared cap/uniqueness check for every probe family's target list —
    at most `_MAX_TARGETS_PER_FAMILY` entries, unique `target_id` values."""
    if len(targets) > _MAX_TARGETS_PER_FAMILY:
        raise ValueError(
            f"{family} targets: at most {_MAX_TARGETS_PER_FAMILY} allowed, got {len(targets)}"
        )
    seen: set[str] = set()
    for target in targets:
        if target.target_id in seen:
            raise ValueError(f"{family} targets: duplicate target_id {target.target_id!r}")
        seen.add(target.target_id)
    return targets


# --------------------------------------------------------------------------- #
# Sub-configuration models (COLLECTOR-V2-REFACTOR.md §9)
# --------------------------------------------------------------------------- #
class BackendConfig(BaseModel):
    url: str = "https://hub.internal:4317"
    pki_dir: str = "/var/lib/analyselaptop/pki"
    retry_max: int = Field(default=10, ge=0)
    retry_backoff_s: float = Field(default=2.0, gt=0)
    enroll_url: str = "https://hub.internal:8443/api/pki/enroll"
    bootstrap_token: str | None = None


class WifiConfig(BaseModel):
    enabled: bool = True
    interface: str = "wlan0"
    scan_interval_s: int = Field(default=60, gt=0)
    ap_change_alert: bool = True


class MtrConfig(BaseModel):
    enabled: bool = True
    targets: list[str] = Field(default_factory=list)
    max_hops: int = Field(default=30, ge=1, le=255)
    probes_per_hop: int = Field(default=3, ge=1)
    interval_s: int = Field(default=300, gt=0)


class BcastMcastConfig(BaseModel):
    enabled: bool = True
    interface: str = "eth0"
    window_s: int = Field(default=30, gt=0)
    top_n: int = Field(default=10, ge=1)
    interval_s: int = Field(default=300, gt=0)


class EbpfConfig(BaseModel):
    enabled: bool = True  # auto-disabled at runtime if the bcc import fails
    flow_track: bool = True


class IcmpTarget(BaseModel):
    """A single ICMP probe target. `target_id` (not `host`) is the only
    identifier that may ever reach a metric label — see METRICS.md."""

    target_id: str
    host: str

    @field_validator("target_id")
    @classmethod
    def _validate_target_id(cls, value: str) -> str:
        return _validate_dns_label(value, "target_id")

    @field_validator("host")
    @classmethod
    def _validate_host_field(cls, value: str) -> str:
        return _validate_icmp_host(value)


class IcmpConfig(BaseModel):
    enabled: bool = True
    targets: list[IcmpTarget] = Field(default_factory=list)
    interval_s: int = Field(default=10, gt=0)
    timeout_s: float = Field(default=2.0, gt=0)

    @field_validator("targets")
    @classmethod
    def _validate_targets_field(cls, value: list[IcmpTarget]) -> list[IcmpTarget]:
        return _validate_target_list(value, "icmp")

    @field_validator("timeout_s")
    @classmethod
    def _validate_timeout(cls, value: float) -> float:
        return _validate_finite_timeout(value)


class TcpTarget(BaseModel):
    target_id: str
    host: str
    port: int = Field(ge=1, le=65535)

    @field_validator("target_id")
    @classmethod
    def _validate_target_id(cls, value: str) -> str:
        return _validate_dns_label(value, "target_id")

    @field_validator("host")
    @classmethod
    def _validate_host_field(cls, value: str) -> str:
        return _validate_host(value)


class TcpConfig(BaseModel):
    enabled: bool = True
    targets: list[TcpTarget] = Field(default_factory=list)
    interval_s: int = Field(default=30, gt=0)
    timeout_s: float = Field(default=5.0, gt=0)

    @field_validator("targets")
    @classmethod
    def _validate_targets_field(cls, value: list[TcpTarget]) -> list[TcpTarget]:
        return _validate_target_list(value, "tcp")

    @field_validator("timeout_s")
    @classmethod
    def _validate_timeout(cls, value: float) -> float:
        return _validate_finite_timeout(value)


class HttpTarget(BaseModel):
    target_id: str
    url: str

    @field_validator("target_id")
    @classmethod
    def _validate_target_id(cls, value: str) -> str:
        return _validate_dns_label(value, "target_id")

    @field_validator("url")
    @classmethod
    def _validate_url_field(cls, value: str) -> str:
        return _validate_target_url(value)


class HttpConfig(BaseModel):
    enabled: bool = True
    targets: list[HttpTarget] = Field(default_factory=list)
    interval_s: int = Field(default=30, gt=0)
    timeout_s: float = Field(default=10.0, gt=0)
    verify_tls: bool = True

    @field_validator("targets")
    @classmethod
    def _validate_targets_field(cls, value: list[HttpTarget]) -> list[HttpTarget]:
        return _validate_target_list(value, "http")

    @field_validator("timeout_s")
    @classmethod
    def _validate_timeout(cls, value: float) -> float:
        return _validate_finite_timeout(value)


class DnsTarget(BaseModel):
    target_id: str
    hostname: str

    @field_validator("target_id")
    @classmethod
    def _validate_target_id(cls, value: str) -> str:
        return _validate_dns_label(value, "target_id")

    @field_validator("hostname")
    @classmethod
    def _validate_hostname_field(cls, value: str) -> str:
        return _validate_host(value)


class DnsConfig(BaseModel):
    enabled: bool = True
    targets: list[DnsTarget] = Field(default_factory=list)
    record_types: list[str] = Field(default_factory=lambda: ["A"])
    resolvers: list[str] = Field(default_factory=list)  # empty = system default
    interval_s: int = Field(default=30, gt=0)
    timeout_s: float = Field(default=5.0, gt=0)

    @field_validator("targets")
    @classmethod
    def _validate_targets_field(cls, value: list[DnsTarget]) -> list[DnsTarget]:
        return _validate_target_list(value, "dns")

    @field_validator("record_types")
    @classmethod
    def _validate_record_types(cls, value: list[str]) -> list[str]:
        for record_type in value:
            if record_type not in _ALLOWED_DNS_RECORD_TYPES:
                raise ValueError(
                    f"dns record_types: {record_type!r} not in allowed set "
                    f"{sorted(_ALLOWED_DNS_RECORD_TYPES)}"
                )
        return value

    @field_validator("timeout_s")
    @classmethod
    def _validate_timeout(cls, value: float) -> float:
        return _validate_finite_timeout(value)


class LatencyTarget(BaseModel):
    target_id: str
    host: str

    @field_validator("target_id")
    @classmethod
    def _validate_target_id(cls, value: str) -> str:
        return _validate_dns_label(value, "target_id")

    @field_validator("host")
    @classmethod
    def _validate_host_field(cls, value: str) -> str:
        return _validate_icmp_host(value)


class LatencyConfig(BaseModel):
    """RTT/jitter burst probing. Separate from `IcmpConfig` and disabled by
    default (Q-4's resolution, docs/guides/AGENT-COORDINATION.md) — sharing
    ICMP's target list would silently multiply packet volume on every
    enabled ICMP target."""

    enabled: bool = False
    targets: list[LatencyTarget] = Field(default_factory=list)
    sample_count: int = Field(default=5, ge=1)
    interval_s: int = Field(default=10, gt=0)
    timeout_s: float = Field(default=2.0, gt=0)

    @field_validator("targets")
    @classmethod
    def _validate_targets_field(cls, value: list[LatencyTarget]) -> list[LatencyTarget]:
        return _validate_target_list(value, "latency")

    @field_validator("timeout_s")
    @classmethod
    def _validate_timeout(cls, value: float) -> float:
        return _validate_finite_timeout(value)


# --------------------------------------------------------------------------- #
# YAML settings source
# --------------------------------------------------------------------------- #
class _YamlSettingsSource(PydanticBaseSettingsSource):
    """A pydantic-settings source that reads a flat/nested mapping from a YAML
    file. Missing file → empty mapping (the file is optional)."""

    def __init__(self, settings_cls: type[BaseSettings], path: Path | None) -> None:
        super().__init__(settings_cls)
        self._data: dict[str, Any] = {}
        if path and path.is_file():
            try:
                loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as exc:
                raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
            if not isinstance(loaded, dict):
                raise ConfigError(f"{path}: top-level YAML must be a mapping")
            self._data = loaded

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        return self._data.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        return self._data


# The YAML path is stashed at module scope so settings_customise_sources (a
# classmethod pydantic calls with no access to our kwargs) can reach it.
_yaml_path: Path | None = None


class CollectorSettings(BaseSettings):
    """Top-level collector configuration."""

    collector_id: str
    site_id: str = "default"
    scan_level_max: Literal[1, 2, 3] = 2
    backend: BackendConfig = BackendConfig()
    wifi: WifiConfig = WifiConfig()
    mtr: MtrConfig = MtrConfig()
    bcast_mcast: BcastMcastConfig = BcastMcastConfig()
    ebpf: EbpfConfig = EbpfConfig()
    icmp: IcmpConfig = IcmpConfig()
    tcp: TcpConfig = TcpConfig()
    http: HttpConfig = HttpConfig()
    dns: DnsConfig = DnsConfig()
    latency: LatencyConfig = LatencyConfig()
    log_level: str = "INFO"
    data_dir: str = "/var/lib/analyselaptop/data"
    # Shared semaphore size capping total concurrent check network operations
    # (see docs/guides/ASYNCIO-OPTIMIZATION.md §4). The default of 20 was
    # derived from the retired Raspberry Pi 3B baseline and is due to be
    # re-derived for the reference Pi 5 (ADR 0012) — that needs measurement,
    # not a guess, so the value is unchanged here. Raise it per node rather
    # than hardcoding a new one.
    max_concurrent_probes: int = Field(default=20, ge=1)
    # Workers in the shared CPU-bound thread pool (see
    # docs/guides/ASYNCIO-OPTIMIZATION.md §3). Defaults to a count derived
    # from the host's cores rather than a literal — ADR 0012 retired the
    # Raspberry Pi 3B baseline that produced the old hard-coded 2, and the
    # reference Pi 5 is the floor. Set explicitly to override.
    cpu_pool_workers: int = Field(default_factory=default_worker_count, ge=1)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    @field_validator("collector_id", "site_id")
    @classmethod
    def _validate_identity_fields(cls, value: str, info: ValidationInfo) -> str:
        return _validate_dns_label(value, info.field_name or "identity")

    @field_validator("scan_level_max", mode="before")
    @classmethod
    def _coerce_scan_level_max(cls, value: Any) -> Any:
        # Env vars are always strings, and pydantic-settings' env source
        # doesn't coerce them for Literal[int, ...] fields the way it does
        # for plain int fields — Literal validation is an exact-match check,
        # not a coercive type, so e.g. SCAN_LEVEL_MAX=1 arrives as the
        # string "1" and fails Literal[1, 2, 3] outright. Found live on lab
        # host .33 (see docs/guides/AGENT-COORDINATION.md, S1-02 Codex
        # review 1). Only numeric strings are converted; anything else
        # passes through so the Literal check still rejects it with a
        # clear error.
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return value
        return value

    # Signature is fixed by pydantic-settings' BaseSettings override contract;
    # it cannot be reduced without breaking the hook.
    @classmethod
    # pylint: disable-next=too-many-positional-arguments
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Highest priority first: init kwargs > env > .env > YAML > secrets.
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _YamlSettingsSource(settings_cls, _yaml_path),
            file_secret_settings,
        )


def load_settings(
    config_file: str | os.PathLike[str] | None = None, **overrides: Any
) -> CollectorSettings:
    """Load and validate collector settings.

    `config_file` (or the ``COLLECTOR_CONFIG`` env var) points at an optional
    YAML file; env vars still override its values. `overrides` win over
    everything and are intended for tests. Raises :class:`ConfigError` on a
    missing required field or a validation failure so the caller can exit
    cleanly instead of surfacing a raw pydantic traceback.
    """
    global _yaml_path  # pylint: disable=global-statement
    path = config_file or os.environ.get(CONFIG_ENV_VAR)
    _yaml_path = Path(path) if path else None
    try:
        return CollectorSettings(**overrides)
    except ValidationError as exc:
        raise ConfigError(f"invalid collector configuration:\n{exc}") from exc
    finally:
        _yaml_path = None


def install_sighup_reload(on_reload: Callable[[CollectorSettings], None]) -> bool:
    """Reload settings on SIGHUP and hand the fresh object to `on_reload`.

    Returns True if the handler was installed (POSIX with SIGHUP), False on
    platforms without SIGHUP (e.g. Windows) so callers can degrade gracefully.
    The reload reuses whatever ``COLLECTOR_CONFIG`` currently points at.
    """
    if not hasattr(signal, "SIGHUP"):
        return False

    def _handler(_signum: int, _frame: Any) -> None:
        on_reload(load_settings())

    # On a Windows pylint run, typeshed's signal.pyi omits SIGHUP entirely
    # (it's declared under `if sys.platform != "win32"`), and astroid does
    # not narrow that away based on the hasattr() guard above — so pylint
    # reports a no-member false positive on a line that is unreachable on
    # Windows at runtime. mypy's ignore (below) already covers the
    # equivalent type-checker gap.
    # pylint: disable-next=no-member
    signal.signal(signal.SIGHUP, _handler)  # type: ignore[attr-defined]
    return True

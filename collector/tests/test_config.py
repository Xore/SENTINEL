"""Tests for collector.config — pydantic schema, layered loader, SIGHUP."""
from __future__ import annotations

import signal

import pytest

from collector.config import (
    CONFIG_ENV_VAR,
    CollectorSettings,
    ConfigError,
    install_sighup_reload,
    load_settings,
)


class TestDefaults:
    def test_minimal_valid(self, settings):
        assert settings.collector_id == "test-collector"
        assert settings.site_id == "default"
        assert settings.scan_level_max == 2
        assert settings.backend.url.startswith("https://")
        assert settings.wifi.interface == "wlan0"
        assert settings.mtr.max_hops == 30
        assert settings.ebpf.enabled is True
        assert settings.backend.enroll_url.startswith("https://")
        assert settings.backend.bootstrap_token is None
        assert settings.icmp.targets == []
        assert settings.icmp.timeout_s == 2.0
        assert settings.tcp.targets == []
        assert settings.http.verify_tls is True
        assert settings.dns.record_types == ["A"]
        assert settings.max_concurrent_probes == 20
        assert settings.latency.enabled is False
        assert settings.latency.targets == []

    def test_max_concurrent_probes_env_override(self, monkeypatch):
        monkeypatch.setenv("COLLECTOR_ID", "c")
        monkeypatch.setenv("MAX_CONCURRENT_PROBES", "5")
        s = load_settings()
        assert s.max_concurrent_probes == 5

    @pytest.mark.parametrize("scan_level_max", ["1", "2", "3"])
    def test_scan_level_max_env_var_string_is_coerced(self, monkeypatch, scan_level_max):
        # Found live on lab host .33: env vars are always strings, and
        # pydantic-settings' env source doesn't coerce them for
        # Literal[int, ...] fields — SCAN_LEVEL_MAX=1 arrived as "1" and
        # failed Literal[1, 2, 3] validation outright instead of being
        # treated as int 1.
        monkeypatch.setenv("COLLECTOR_ID", "c")
        monkeypatch.setenv("SCAN_LEVEL_MAX", scan_level_max)
        s = load_settings()
        assert s.scan_level_max == int(scan_level_max)

    def test_scan_level_max_env_var_out_of_range_still_rejected(self, monkeypatch):
        monkeypatch.setenv("COLLECTOR_ID", "c")
        monkeypatch.setenv("SCAN_LEVEL_MAX", "9")
        with pytest.raises(ConfigError):
            load_settings()

    def test_scan_level_max_env_var_non_numeric_still_rejected(self, monkeypatch):
        monkeypatch.setenv("COLLECTOR_ID", "c")
        monkeypatch.setenv("SCAN_LEVEL_MAX", "bogus")
        with pytest.raises(ConfigError):
            load_settings()

    def test_max_concurrent_probes_must_be_positive(self):
        with pytest.raises(ConfigError):
            load_settings(collector_id="c", max_concurrent_probes=0)

    def test_missing_required_collector_id_raises_configerror(self):
        with pytest.raises(ConfigError) as exc:
            load_settings()
        assert "collector_id" in str(exc.value)

    def test_invalid_scan_level_rejected(self):
        with pytest.raises(ConfigError):
            load_settings(collector_id="c", scan_level_max=9)

    def test_field_bounds_enforced(self):
        with pytest.raises(ConfigError):
            load_settings(collector_id="c", mtr={"max_hops": 999})

    def test_icmp_targets_accepted(self):
        s = load_settings(
            collector_id="c",
            icmp={
                "targets": [
                    {"target_id": "core-switch", "host": "10.0.0.1"},
                    {"target_id": "upstream-dns", "host": "1.1.1.1"},
                ]
            },
        )
        assert [t.target_id for t in s.icmp.targets] == ["core-switch", "upstream-dns"]
        assert [t.host for t in s.icmp.targets] == ["10.0.0.1", "1.1.1.1"]

    def test_tcp_target_requires_host_and_port(self):
        s = load_settings(
            collector_id="c",
            tcp={"targets": [{"target_id": "web", "host": "10.0.0.1", "port": 443}]},
        )
        assert s.tcp.targets[0].target_id == "web"
        assert s.tcp.targets[0].host == "10.0.0.1"
        assert s.tcp.targets[0].port == 443

    def test_tcp_target_port_out_of_range_rejected(self):
        with pytest.raises(ConfigError):
            load_settings(
                collector_id="c",
                tcp={"targets": [{"target_id": "web", "host": "h", "port": 70000}]},
            )


class TestTargetValidation:
    """S2-02: structured target_id-bearing targets for ICMP/TCP/HTTP/DNS/
    latency, per docs/contracts/METRICS.md's Phase 2 core network families.
    """

    @pytest.mark.parametrize("bad_target_id", ["Core-Switch", "core_switch", "-core", "core-", ""])
    def test_invalid_target_id_rejected(self, bad_target_id):
        with pytest.raises(ConfigError):
            load_settings(
                collector_id="c",
                icmp={"targets": [{"target_id": bad_target_id, "host": "10.0.0.1"}]},
            )

    def test_duplicate_target_id_rejected(self):
        with pytest.raises(ConfigError):
            load_settings(
                collector_id="c",
                icmp={
                    "targets": [
                        {"target_id": "dup", "host": "10.0.0.1"},
                        {"target_id": "dup", "host": "10.0.0.2"},
                    ]
                },
            )

    def test_more_than_32_targets_rejected(self):
        targets = [{"target_id": f"t{i}", "host": "10.0.0.1"} for i in range(33)]
        with pytest.raises(ConfigError):
            load_settings(collector_id="c", icmp={"targets": targets})

    def test_exactly_32_targets_accepted(self):
        targets = [{"target_id": f"t{i}", "host": "10.0.0.1"} for i in range(32)]
        s = load_settings(collector_id="c", icmp={"targets": targets})
        assert len(s.icmp.targets) == 32

    @pytest.mark.parametrize("bad_host", ["", "  ", "host with spaces", "a" * 254])
    def test_invalid_icmp_host_rejected(self, bad_host):
        with pytest.raises(ConfigError):
            load_settings(
                collector_id="c",
                icmp={"targets": [{"target_id": "t", "host": bad_host}]},
            )

    def test_valid_hostname_and_ip_accepted(self):
        s = load_settings(
            collector_id="c",
            icmp={
                "targets": [
                    {"target_id": "by-ip", "host": "10.0.0.1"},
                    {"target_id": "by-name", "host": "core.example.com"},
                    {"target_id": "by-ipv6", "host": "::1"},
                ]
            },
        )
        assert [t.host for t in s.icmp.targets] == ["10.0.0.1", "core.example.com", "::1"]

    @pytest.mark.parametrize("bad_url", ["not-a-url", "ftp://host/path", "http://"])
    def test_invalid_http_url_rejected(self, bad_url):
        with pytest.raises(ConfigError):
            load_settings(
                collector_id="c",
                http={"targets": [{"target_id": "t", "url": bad_url}]},
            )

    def test_valid_http_url_accepted(self):
        s = load_settings(
            collector_id="c",
            http={"targets": [{"target_id": "app", "url": "https://10.0.0.1/health"}]},
        )
        assert s.http.targets[0].url == "https://10.0.0.1/health"

    def test_dns_target_requires_hostname(self):
        s = load_settings(
            collector_id="c",
            dns={"targets": [{"target_id": "app-dns", "hostname": "example.com"}]},
        )
        assert s.dns.targets[0].hostname == "example.com"

    @pytest.mark.parametrize("bad_record_type", ["ANY", "a", "BOGUS"])
    def test_invalid_dns_record_type_rejected(self, bad_record_type):
        with pytest.raises(ConfigError):
            load_settings(collector_id="c", dns={"record_types": [bad_record_type]})

    @pytest.mark.parametrize(
        "record_type", ["A", "AAAA", "CNAME", "MX", "NS", "PTR", "SRV", "TXT"]
    )
    def test_allowed_dns_record_types_accepted(self, record_type):
        s = load_settings(collector_id="c", dns={"record_types": [record_type]})
        assert s.dns.record_types == [record_type]

    def test_latency_disabled_by_default(self):
        s = load_settings(collector_id="c")
        assert s.latency.enabled is False

    def test_latency_target_accepted_when_enabled(self):
        s = load_settings(
            collector_id="c",
            latency={"enabled": True, "targets": [{"target_id": "core", "host": "10.0.0.1"}]},
        )
        assert s.latency.enabled is True
        assert s.latency.targets[0].target_id == "core"


class TestIdentityDnsLabels:
    """ADR 0009: collector_id/site_id are lower-case RFC 1123 DNS labels."""

    @pytest.mark.parametrize(
        "collector_id",
        ["c", "a1", "node-1", "probe-site-a-01", "a" * 63],
    )
    def test_valid_collector_id_accepted(self, collector_id):
        s = load_settings(collector_id=collector_id)
        assert s.collector_id == collector_id

    @pytest.mark.parametrize(
        "site_id",
        ["default", "site-a", "s", "a" * 63],
    )
    def test_valid_site_id_accepted(self, site_id):
        s = load_settings(collector_id="c", site_id=site_id)
        assert s.site_id == site_id

    @pytest.mark.parametrize(
        "collector_id",
        [
            "Node-1",  # uppercase not silently lowercased — must be rejected
            "NODE1",
            "node_1",  # underscore is not a valid DNS-label character
            "-node1",  # cannot start with a hyphen
            "node1-",  # cannot end with a hyphen
            "node 1",  # no whitespace
            "",  # empty
            "a" * 64,  # over the 63-character limit
            "node.1",  # dot is not a DNS-label character (that's a name, not a label)
        ],
    )
    def test_invalid_collector_id_rejected(self, collector_id):
        with pytest.raises(ConfigError) as exc:
            load_settings(collector_id=collector_id)
        assert "collector_id" in str(exc.value)

    def test_invalid_site_id_rejected(self):
        with pytest.raises(ConfigError) as exc:
            load_settings(collector_id="c", site_id="Site-A")
        assert "site_id" in str(exc.value)

    def test_invalid_identity_env_override_rejected(self, monkeypatch):
        monkeypatch.setenv("COLLECTOR_ID", "c")
        monkeypatch.setenv("SITE_ID", "Bad_Site")
        with pytest.raises(ConfigError):
            load_settings()


class TestEnvLayer:
    def test_scalar_env_override(self, monkeypatch):
        monkeypatch.setenv("COLLECTOR_ID", "from-env")
        monkeypatch.setenv("SITE_ID", "site-7")
        s = load_settings()
        assert s.collector_id == "from-env"
        assert s.site_id == "site-7"

    def test_nested_env_override(self, monkeypatch):
        monkeypatch.setenv("COLLECTOR_ID", "c")
        monkeypatch.setenv("WIFI__ENABLED", "false")
        monkeypatch.setenv("BACKEND__URL", "https://other:4317")
        s = load_settings()
        assert s.wifi.enabled is False
        assert s.backend.url == "https://other:4317"

    def test_check_config_env_override(self, monkeypatch):
        monkeypatch.setenv("COLLECTOR_ID", "c")
        monkeypatch.setenv("ICMP__TIMEOUT_S", "5.0")
        monkeypatch.setenv("HTTP__VERIFY_TLS", "false")
        s = load_settings()
        assert s.icmp.timeout_s == 5.0
        assert s.http.verify_tls is False

    def test_bootstrap_token_env_override(self, monkeypatch):
        monkeypatch.setenv("COLLECTOR_ID", "c")
        monkeypatch.setenv("BACKEND__BOOTSTRAP_TOKEN", "s3cr3t")
        s = load_settings()
        assert s.backend.bootstrap_token == "s3cr3t"


class TestYamlLayer:
    def _write(self, tmp_path, text):
        p = tmp_path / "collector.yaml"
        p.write_text(text, encoding="utf-8")
        return p

    def test_yaml_file_loaded(self, tmp_path):
        p = self._write(tmp_path, """
collector_id: yaml-node
site_id: floor-2
scan_level_max: 3
wifi:
  enabled: false
  interface: wlan1
""")
        s = load_settings(p)
        assert s.collector_id == "yaml-node"
        assert s.site_id == "floor-2"
        assert s.scan_level_max == 3
        assert s.wifi.enabled is False
        assert s.wifi.interface == "wlan1"

    def test_yaml_path_via_env_var(self, tmp_path, monkeypatch):
        p = self._write(tmp_path, "collector_id: env-yaml\n")
        monkeypatch.setenv(CONFIG_ENV_VAR, str(p))
        s = load_settings()
        assert s.collector_id == "env-yaml"

    def test_env_overrides_yaml(self, tmp_path, monkeypatch):
        p = self._write(tmp_path, "collector_id: yaml-node\nsite_id: from-yaml\n")
        monkeypatch.setenv("SITE_ID", "from-env")
        s = load_settings(p)
        assert s.collector_id == "yaml-node"   # only in YAML
        assert s.site_id == "from-env"          # env wins over YAML

    def test_init_override_wins_over_all(self, tmp_path, monkeypatch):
        p = self._write(tmp_path, "collector_id: yaml-node\n")
        monkeypatch.setenv("COLLECTOR_ID", "env-node")
        s = load_settings(p, collector_id="explicit")
        assert s.collector_id == "explicit"

    def test_missing_yaml_file_is_ok(self, tmp_path):
        s = load_settings(tmp_path / "nope.yaml", collector_id="c")
        assert s.collector_id == "c"

    def test_bad_yaml_scalar_raises(self, tmp_path):
        p = self._write(tmp_path, "just a bare string, not a mapping")
        with pytest.raises(ConfigError):
            load_settings(p, collector_id="c")

    def test_yaml_path_not_leaked_after_load(self, tmp_path):
        # After a load with a YAML file, a later default load must not still
        # see it (module-level path must be reset).
        p = self._write(tmp_path, "collector_id: yaml-node\n")
        load_settings(p)
        with pytest.raises(ConfigError):
            load_settings()  # no collector_id anywhere now


class TestSighup:
    @pytest.mark.skipif(not hasattr(signal, "SIGHUP"), reason="POSIX only")
    def test_sighup_installs_on_posix(self):
        assert install_sighup_reload(lambda s: None) is True

    @pytest.mark.skipif(hasattr(signal, "SIGHUP"), reason="non-POSIX only")
    def test_sighup_noop_without_signal(self):
        assert install_sighup_reload(lambda s: None) is False


def test_settings_is_basesettings():
    assert issubclass(CollectorSettings, __import__("pydantic_settings").BaseSettings)

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

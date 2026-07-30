"""Tests for collector.checks.host_network — interface throughput check."""

from __future__ import annotations

import asyncio
import os
import time

import pytest
from collector.checks.host_network import (
    MAX_IFNAME_LEN,
    HostNetworkCheck,
    _parse_interface_line,
    _read_interface_counters,
)

_NET_DEV = """\
Inter-|   Receive                                    |  Transmit
 face |bytes  packets errs drop fifo frame comp multi|bytes  packets ...
    lo: 1000       10    0    0    0     0    0     0    1000      10
  eth0: 500000    400    0    0    0     0    0     0  200000     300
"""


class TestInterfaceValidation:
    """`interface` is an allowed METRICS.md label, so it must be bounded before
    it can ever be emitted as one."""

    @pytest.mark.parametrize(
        "interface",
        [
            "",
            " eth0 ",
            "eth0 ",
            "eth 0",
            "nul\x00byte",
            "new\nline",
            "-leading",
            "_leading",
            "eth/0",
            "a" * (MAX_IFNAME_LEN + 1),
        ],
    )
    def test_rejects_invalid_interface(self, settings, interface):
        with pytest.raises(ValueError, match="interface"):
            HostNetworkCheck(settings, meter=None, interface=interface)

    @pytest.mark.parametrize(
        "interface", ["lo", "eth0", "enp0s31f6", "wlp2s0", "br-lan", "eth0.100", "eth0:1", "a" * 15]
    )
    def test_accepts_valid_interface(self, settings, interface):
        assert HostNetworkCheck(settings, meter=None, interface=interface).interface == interface

    async def test_invalid_interface_never_reaches_the_filesystem(self, settings, monkeypatch):
        def _explode(path, interface):  # pragma: no cover — must never run
            raise AssertionError("counters read with an unvalidated interface")

        monkeypatch.setattr("collector.checks.host_network._read_interface_counters", _explode)
        with pytest.raises(ValueError):
            HostNetworkCheck(settings, meter=None, interface="eth0\nreboot")


class TestParseInterfaceLine:
    def test_returns_rx_and_tx_bytes(self):
        rx, tx = _parse_interface_line(_NET_DEV, "eth0")
        assert rx == 500000
        assert tx == 200000

    def test_missing_interface_raises(self):
        with pytest.raises(ValueError, match="not found"):
            _parse_interface_line(_NET_DEV, "eth9")

    def test_malformed_line_raises(self):
        with pytest.raises(ValueError, match="unexpected"):
            _parse_interface_line("  eth0: 1 2 3\n", "eth0")

    def test_non_integer_field_raises(self):
        with pytest.raises(ValueError, match="non-integer"):
            _parse_interface_line("  eth0: x 0 0 0 0 0 0 0 0\n", "eth0")

    @pytest.mark.parametrize(
        "line",
        ["  eth0: -1 0 0 0 0 0 0 0 100\n", "  eth0: 100 0 0 0 0 0 0 0 -1\n"],
    )
    def test_negative_counter_raises(self, line):
        # `/proc/net/dev` counters are unsigned; a negative one means the input
        # is not what it claims to be.
        with pytest.raises(ValueError, match="negative"):
            _parse_interface_line(line, "eth0")

    def test_does_not_match_a_similarly_named_interface(self):
        with pytest.raises(ValueError, match="not found"):
            _parse_interface_line(_NET_DEV, "eth")


class TestReadInterfaceCounters:
    def test_reads_real_file(self, tmp_path):
        path = tmp_path / "net_dev"
        path.write_text(_NET_DEV)
        rx, tx = _read_interface_counters(str(path), "eth0")
        assert rx == 500000
        assert tx == 200000

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            _read_interface_counters(str(tmp_path / "nope"), "eth0")


class TestHostNetworkCheck:
    @pytest.fixture(autouse=True)
    def _linux_platform(self, monkeypatch):
        monkeypatch.setattr("collector.checks.host_network.sys.platform", "linux")

    async def test_first_run_records_baseline_with_no_metrics(self, settings, tmp_path):
        path = tmp_path / "net_dev"
        path.write_text(_NET_DEV)
        check = HostNetworkCheck(settings, meter=None, interface="eth0", net_dev_path=str(path))

        result = await check.run()

        assert result.ok is True
        assert result.metrics == {}

    async def test_second_run_computes_rate_from_delta(self, settings, tmp_path):
        path = tmp_path / "net_dev"
        path.write_text(_NET_DEV)
        check = HostNetworkCheck(settings, meter=None, interface="eth0", net_dev_path=str(path))

        await check.run()
        first_time = check._prev[0]  # pylint: disable=protected-access

        await asyncio.sleep(0.05)
        path.write_text(_NET_DEV.replace("500000", "600000").replace("200000", "250000"))
        result = await check.run()
        second_time = check._prev[0]  # pylint: disable=protected-access

        # Compute the expected rate from the check's own measured elapsed
        # time rather than a fixed wall-clock guess, so the assertion is
        # exact regardless of actual scheduling jitter.
        elapsed_s = second_time - first_time
        assert result.ok is True
        assert result.metrics["network_rx_bytes_per_s"] == pytest.approx(100000.0 / elapsed_s)
        assert result.metrics["network_tx_bytes_per_s"] == pytest.approx(50000.0 / elapsed_s)
        assert result.labels == {"interface": "eth0"}

    async def test_counter_reset_skips_the_interval_instead_of_clamping(self, settings, tmp_path):
        # The interface was recreated or a namespaced /proc was swapped, so the
        # counters went backwards. Clamping the negative delta would publish a
        # 0 B/s "measurement" that never happened.
        path = tmp_path / "net_dev"
        path.write_text(_NET_DEV)
        check = HostNetworkCheck(settings, meter=None, interface="eth0", net_dev_path=str(path))
        await check.run()

        await asyncio.sleep(0.01)
        path.write_text(_NET_DEV.replace("500000", "1000").replace("200000", "500"))
        result = await check.run()

        assert result.ok is True
        assert result.metrics == {}

        # The baseline was refreshed, so the next interval measures normally.
        await asyncio.sleep(0.01)
        path.write_text(_NET_DEV.replace("500000", "2000").replace("200000", "1500"))
        result = await check.run()
        assert set(result.metrics) == {"network_rx_bytes_per_s", "network_tx_bytes_per_s"}

    @pytest.mark.parametrize("direction", ["rx", "tx"])
    async def test_one_direction_going_backwards_skips_the_interval(
        self, settings, tmp_path, direction
    ):
        path = tmp_path / "net_dev"
        path.write_text(_NET_DEV)
        check = HostNetworkCheck(settings, meter=None, interface="eth0", net_dev_path=str(path))
        await check.run()

        await asyncio.sleep(0.01)
        if direction == "rx":
            path.write_text(_NET_DEV.replace("500000", "1000").replace("200000", "300000"))
        else:
            path.write_text(_NET_DEV.replace("500000", "600000").replace("200000", "500"))
        result = await check.run()

        assert result.ok is True
        assert result.metrics == {}

    async def test_non_advancing_clock_skips_the_interval(self, settings, tmp_path):
        path = tmp_path / "net_dev"
        path.write_text(_NET_DEV)
        check = HostNetworkCheck(settings, meter=None, interface="eth0", net_dev_path=str(path))
        await check.run()

        # Backdate nothing but the clock: a zero or negative interval cannot
        # yield a rate, and dividing by it would raise inside `run()`.
        prev_time, prev_rx, prev_tx = check._prev  # pylint: disable=protected-access
        check._prev = (  # pylint: disable=protected-access
            prev_time + 10.0,
            prev_rx,
            prev_tx,
        )
        path.write_text(_NET_DEV.replace("500000", "600000"))
        result = await check.run()

        assert result.ok is True
        assert result.metrics == {}

    async def test_missing_interface_never_raises(self, settings, tmp_path):
        path = tmp_path / "net_dev"
        path.write_text(_NET_DEV)
        check = HostNetworkCheck(settings, meter=None, interface="ppp0", net_dev_path=str(path))

        result = await check.run()

        assert result.ok is False
        # Bounded: the interface plus the exception type. The full message can
        # embed the configured path and raw file content.
        assert result.error == "ppp0: ValueError"

    async def test_missing_file_never_raises(self, settings, tmp_path):
        check = HostNetworkCheck(
            settings, meter=None, interface="eth0", net_dev_path=str(tmp_path / "nope")
        )
        result = await check.run()
        assert result.ok is False
        assert result.error == "eth0: FileNotFoundError"

    async def test_raw_file_content_never_reaches_the_result(self, settings, tmp_path):
        path = tmp_path / "net_dev"
        path.write_text("  eth0: s3cr3t 0 0 0 0 0 0 0 0\n")
        check = HostNetworkCheck(settings, meter=None, interface="eth0", net_dev_path=str(path))

        result = await check.run()

        assert result.ok is False
        assert "s3cr3t" not in result.error

    async def test_negative_counter_fails_the_check(self, settings, tmp_path):
        path = tmp_path / "net_dev"
        path.write_text("  eth0: -1 0 0 0 0 0 0 0 100\n")
        check = HostNetworkCheck(settings, meter=None, interface="eth0", net_dev_path=str(path))

        result = await check.run()

        assert result.ok is False
        assert result.metrics == {}

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics required")
    async def test_permission_denied_never_raises(self, settings, tmp_path):
        path = tmp_path / "net_dev"
        path.write_text(_NET_DEV)
        path.chmod(0o000)
        try:
            check = HostNetworkCheck(settings, meter=None, interface="eth0", net_dev_path=str(path))
            result = await check.run()
            assert result.ok is False
        finally:
            path.chmod(0o644)

    async def test_unsupported_platform_reports_failure(self, settings, tmp_path, monkeypatch):
        monkeypatch.setattr("collector.checks.host_network.sys.platform", "win32")
        check = HostNetworkCheck(settings, meter=None, net_dev_path=str(tmp_path / "net_dev"))
        result = await check.run()
        assert result.ok is False
        assert "win32" in result.error

    async def test_slow_read_is_cancellable(self, settings, monkeypatch):
        check = HostNetworkCheck(settings, meter=None)

        def slow_read(path, interface):  # pylint: disable=unused-argument
            time.sleep(1.5)
            return 0, 0  # pragma: no cover — never reached

        monkeypatch.setattr("collector.checks.host_network._read_interface_counters", slow_read)

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(check.run(), timeout=0.2)

    def test_semaphore_stored(self, settings):
        sem = asyncio.Semaphore(3)
        check = HostNetworkCheck(settings, meter=None, semaphore=sem)
        assert check.semaphore is sem

    def test_default_interface_is_eth0(self, settings):
        check = HostNetworkCheck(settings, meter=None)
        assert check.interface == "eth0"

"""Tests for collector.checks.net_icmp — packet framing and the ICMP check."""
from __future__ import annotations

import struct
from unittest.mock import MagicMock, patch

import pytest
from collector.checks.net_icmp import (
    ICMP_ECHO_REPLY,
    IcmpCheck,
    _build_echo_request,
    _checksum,
    _parse_echo_reply,
    _ping_once_blocking,
    ping,
    target_identifier,
)
from collector.config import load_settings


def _reply_packet(identifier: int, sequence: int, icmp_type: int = ICMP_ECHO_REPLY) -> bytes:
    """A minimal IPv4 datagram (20-byte header, no options) wrapping an ICMP
    echo reply — as `_ping_once_blocking` would receive from a real socket.
    """
    ip_header = bytes([0x45]) + b"\x00" * 19
    icmp_header = struct.pack("!BBHHH", icmp_type, 0, 0, identifier, sequence)
    return ip_header + icmp_header + b"payload"


class TestChecksum:
    def test_built_packet_checksum_is_valid(self):
        packet = _build_echo_request(identifier=1, sequence=1, payload=b"abc")
        # The internet checksum property: recomputing over data that already
        # includes a correct checksum field yields zero.
        assert _checksum(packet) == 0

    def test_checksum_pads_odd_length(self):
        assert _checksum(b"\x01") == _checksum(b"\x01\x00")


class TestParseEchoReply:
    def test_valid_reply_matches(self):
        packet = _reply_packet(identifier=42, sequence=7)
        assert _parse_echo_reply(packet, identifier=42, sequence=7) is True

    def test_wrong_identifier_does_not_match(self):
        packet = _reply_packet(identifier=42, sequence=7)
        assert _parse_echo_reply(packet, identifier=99, sequence=7) is False

    def test_wrong_sequence_does_not_match(self):
        packet = _reply_packet(identifier=42, sequence=7)
        assert _parse_echo_reply(packet, identifier=42, sequence=8) is False

    def test_wrong_type_does_not_match(self):
        packet = _reply_packet(identifier=42, sequence=7, icmp_type=8)  # echo request, not reply
        assert _parse_echo_reply(packet, identifier=42, sequence=7) is False

    def test_short_packet_does_not_match(self):
        assert _parse_echo_reply(b"\x45\x00", identifier=1, sequence=1) is False


def testtarget_identifier_in_range_and_differs_by_target():
    a = target_identifier("10.0.0.1")
    b = target_identifier("10.0.0.2")
    assert 0 <= a <= 0xFFFF
    assert 0 <= b <= 0xFFFF
    assert a != b


class TestPingOnceBlocking:
    def test_returns_rtt_on_matching_reply(self):
        fake_sock = MagicMock()
        fake_sock.recvfrom.return_value = (_reply_packet(5, 1), ("10.0.0.1", 0))
        with patch("collector.checks.net_icmp.socket.socket", return_value=fake_sock):
            rtt_ms = _ping_once_blocking("10.0.0.1", identifier=5, sequence=1, timeout_s=1.0)
        assert rtt_ms >= 0
        fake_sock.sendto.assert_called_once()
        fake_sock.close.assert_called_once()

    def test_skips_non_matching_reply_then_matches(self):
        fake_sock = MagicMock()
        fake_sock.recvfrom.side_effect = [
            (_reply_packet(999, 999), ("10.0.0.1", 0)),  # someone else's reply
            (_reply_packet(5, 1), ("10.0.0.1", 0)),
        ]
        with patch("collector.checks.net_icmp.socket.socket", return_value=fake_sock):
            rtt_ms = _ping_once_blocking("10.0.0.1", identifier=5, sequence=1, timeout_s=1.0)
        assert rtt_ms >= 0
        assert fake_sock.recvfrom.call_count == 2

    def test_raises_timeout_error_when_deadline_exceeded(self):
        fake_sock = MagicMock()
        fake_sock.recvfrom.side_effect = TimeoutError("timed out")
        with (
            patch("collector.checks.net_icmp.socket.socket", return_value=fake_sock),
            pytest.raises(TimeoutError),
        ):
            _ping_once_blocking("10.0.0.1", identifier=5, sequence=1, timeout_s=0.01)
        fake_sock.close.assert_called_once()

    def test_closes_socket_on_send_error(self):
        fake_sock = MagicMock()
        fake_sock.sendto.side_effect = OSError("Operation not permitted")
        with (
            patch("collector.checks.net_icmp.socket.socket", return_value=fake_sock),
            pytest.raises(OSError, match="not permitted"),
        ):
            _ping_once_blocking("10.0.0.1", identifier=5, sequence=1, timeout_s=1.0)
        fake_sock.close.assert_called_once()


async def test_ping_delegates_to_blocking_helper_via_to_thread():
    fake_sock = MagicMock()
    fake_sock.recvfrom.return_value = (_reply_packet(5, 1), ("10.0.0.1", 0))
    with patch("collector.checks.net_icmp.socket.socket", return_value=fake_sock):
        rtt_ms = await ping("10.0.0.1", identifier=5, sequence=1, timeout_s=1.0)
    assert rtt_ms >= 0


class TestIcmpCheck:
    async def test_run_ok_result(self, monkeypatch):
        settings = load_settings(collector_id="c", icmp={"targets": ["10.0.0.1"]})
        check = IcmpCheck(settings, meter=None, target="10.0.0.1")

        async def fake_ping(target, *, identifier, sequence, timeout_s):
            return 12.5

        monkeypatch.setattr("collector.checks.net_icmp.ping", fake_ping)
        result = await check.run()

        assert result.ok is True
        assert result.metrics["icmp_rtt_ms"] == 12.5
        assert result.metrics["icmp_loss_pct"] == 0.0
        assert result.labels == {"target": "10.0.0.1"}
        assert result.error is None

    async def test_run_never_raises_on_failure(self, monkeypatch):
        settings = load_settings(collector_id="c", icmp={"targets": ["10.0.0.1"]})
        check = IcmpCheck(settings, meter=None, target="10.0.0.1")

        async def failing_ping(target, *, identifier, sequence, timeout_s):
            raise TimeoutError("no reply from 10.0.0.1 within 2.0s")

        monkeypatch.setattr("collector.checks.net_icmp.ping", failing_ping)
        result = await check.run()

        assert result.ok is False
        assert result.metrics["icmp_loss_pct"] == 100.0
        assert result.labels == {"target": "10.0.0.1"}
        assert "no reply" in result.error

    async def test_run_increments_sequence_each_call(self, monkeypatch):
        settings = load_settings(collector_id="c")
        check = IcmpCheck(settings, meter=None, target="10.0.0.1")
        seen_sequences = []

        async def fake_ping(target, *, identifier, sequence, timeout_s):
            seen_sequences.append(sequence)
            return 1.0

        monkeypatch.setattr("collector.checks.net_icmp.ping", fake_ping)
        await check.run()
        await check.run()

        assert seen_sequences == [1, 2]

"""Unit tests for the device classifier (dashboard/classify.py, task #39).

Pure function, no app/state/env needed - just assert each signal maps a node to
the right device kind and that a specific graph role is never demoted.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dashboard import classify  # noqa: E402


class ClassifyTest(unittest.TestCase):
    def test_vendor_printer(self):
        r = classify.classify(current_kind="host", vendor="Hewlett Packard")
        self.assertEqual(r["kind"], "printer")
        self.assertEqual(r["source"], "vendor")

    def test_vendor_infra(self):
        self.assertEqual(classify.classify(current_kind="host", vendor="Ubiquiti Inc")["kind"], "ap")
        self.assertEqual(classify.classify(current_kind="host", vendor="Cisco Systems")["kind"], "switch")

    def test_service_beats_vendor(self):
        # A responding printer port outranks a generic workstation vendor.
        r = classify.classify(current_kind="host", vendor="Dell", services=[9100])
        self.assertEqual(r["kind"], "printer")
        self.assertEqual(r["source"], "service")

    def test_generic_web_port_is_server(self):
        r = classify.classify(current_kind="unknown", services=[443])
        self.assertEqual(r["kind"], "server")

    def test_gateway_role_wins(self):
        r = classify.classify(current_kind="host", vendor="Dell", is_gateway=True)
        self.assertEqual(r["kind"], "router")
        self.assertEqual(r["source"], "role")

    def test_snmp_descr(self):
        r = classify.classify(current_kind="host", sys_descr="HP ETHERNET MULTI-ENVIRONMENT JetDirect")
        self.assertEqual(r["kind"], "printer")

    def test_hostname_fallback(self):
        r = classify.classify(current_kind="host", hostname="office-printer-01")
        self.assertEqual(r["kind"], "printer")

    def test_never_demotes_specific_role(self):
        # An already-classified router must not be pulled back to a vendor guess.
        self.assertIsNone(classify.classify(current_kind="router", vendor="Dell"))
        self.assertIsNone(classify.classify(current_kind="self", vendor="Intel"))

    def test_no_signal_returns_none(self):
        self.assertIsNone(classify.classify(current_kind="host"))


if __name__ == "__main__":
    unittest.main()

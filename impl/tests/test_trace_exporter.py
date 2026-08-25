"""Issue #78: the `TraceExporter` adapter contract — a built-in `stderr-json`
exporter plus an `lnpl.exporters` entry-points group for external adapters,
mirroring `_driver_entry_points()` / `open_repository()` (t75, drivers.py) by
shape only. `drivers.py` and the `lnpl.drivers` group are never touched here.
"""

import contextlib
import io
import json
import unittest
from unittest import mock

from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.wsgi import (ExporterError, StderrJsonExporter, TraceExporter,
                       make_wsgi_app, open_exporter)
from tests.test_wsgi_contract import call_wsgi

PAYMENT_SRC = """
capability postgres
entity Payment
    field
        id UUID
        cardNumber Password
        amountCents Integer
service PaymentService
    policy
        retry 0
workflow Approval
    validate payment
    find payment
    update payment
"""

CARD = "4111111111111111"
PATH = "/payment-service/approval"


def _doc():
    return lower(parse(PAYMENT_SRC), "pay").to_document()


def _payload():
    return {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
            "cardNumber": CARD, "amountCents": 500}


class _FakeEntryPoint:
    def __init__(self, name, value, factory):
        self.name = name
        self.value = value
        self._factory = factory

    def load(self):
        return self._factory


class OpenExporterNormalTest(unittest.TestCase):
    def test_normal_the_built_in_stderr_json_exporter_is_selected_by_name(self):
        exporter = open_exporter("stderr-json")

        self.assertIsInstance(exporter, StderrJsonExporter)
        self.assertIsInstance(exporter, TraceExporter)

    def test_normal_none_spec_means_no_exporter_configured(self):
        self.assertIsNone(open_exporter(None))

    def test_normal_a_registered_entry_point_is_loaded_and_instantiated(self):
        received = []

        class FakeExporter(TraceExporter):
            def export(self, trace_dict):
                received.append(trace_dict)

        entry_point = _FakeEntryPoint("fake", "tests.fake:FakeExporter", FakeExporter)
        with mock.patch("lnpl.wsgi._exporter_entry_points",
                        return_value=[entry_point]):
            exporter = open_exporter("fake")

        self.assertIsInstance(exporter, FakeExporter)
        exporter.export({"correlation_id": "req-1", "span": None,
                         "metrics": [], "logs": []})
        self.assertEqual(1, len(received))
        self.assertEqual("req-1", received[0]["correlation_id"])


class OpenExporterErrorTest(unittest.TestCase):
    def test_error_an_unknown_exporter_name_names_the_accepted_set(self):
        with self.assertRaises(ValueError) as ctx:
            open_exporter("otlp")

        message = str(ctx.exception)
        self.assertIn("otlp", message)
        self.assertIn("stderr-json", message)

    def test_error_a_load_failure_is_translated_to_one_error_type(self):
        class _BrokenEntryPoint:
            name = "broken"
            value = "tests.broken:factory"

            def load(self):
                raise ImportError("no module named tests.broken")

        with mock.patch("lnpl.wsgi._exporter_entry_points",
                        return_value=[_BrokenEntryPoint()]):
            with self.assertRaises(ExporterError) as ctx:
                open_exporter("broken")

        self.assertIn("broken", str(ctx.exception))
        self.assertIsInstance(ctx.exception.__cause__, ImportError)


class OpenExporterBoundaryTest(unittest.TestCase):
    def test_boundary_a_registered_entry_point_can_never_shadow_the_built_in_name(self):
        class _ShouldNeverLoad:
            name = "stderr-json"
            value = "evil:factory"

            def load(self):
                raise AssertionError("built-in must be matched before entry-points")

        with mock.patch("lnpl.wsgi._exporter_entry_points",
                        return_value=[_ShouldNeverLoad()]):
            exporter = open_exporter("stderr-json")

        self.assertIsInstance(exporter, StderrJsonExporter)

    def test_boundary_stderr_json_exporter_writes_exactly_one_line(self):
        exporter = StderrJsonExporter()
        buf = io.StringIO()

        with contextlib.redirect_stderr(buf):
            exporter.export({"correlation_id": "req-2", "span": None,
                             "metrics": [], "logs": []})

        lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
        self.assertEqual(1, len(lines))
        self.assertEqual("req-2", json.loads(lines[0])["correlation_id"])


class ExporterWsgiIntegrationTest(unittest.TestCase):
    """DoD: 'TraceExporter 계약 문서화 + fake exporter 계약 테스트' — plugged
    into a real request (default text log-format — exporting is independent
    of --log-format), a fake exporter must receive exactly `Trace.to_dict()`'s
    shape, already masked (no second masking path for the exporter channel)."""

    def test_normal_a_fake_exporter_receives_the_completed_requests_trace(self):
        received = []

        class FakeExporter(TraceExporter):
            def export(self, trace_dict):
                received.append(trace_dict)

        app = make_wsgi_app(_doc(), exporter=FakeExporter())

        status, _headers, body = call_wsgi(
            app, "POST", PATH, body=json.dumps(_payload()).encode("utf-8"))

        self.assertEqual(200, status)
        self.assertEqual(1, len(received))
        trace = received[0]
        self.assertEqual(body["correlation_id"], trace["correlation_id"])
        self.assertIn("span", trace)
        self.assertIn("metrics", trace)
        self.assertIn("logs", trace)
        self.assertNotIn(CARD, json.dumps(trace, default=repr))

    def test_boundary_no_exporter_configured_means_nothing_is_exported(self):
        # Default `exporter=None` — the pre-existing behavior for every
        # caller that never asked for one.
        app = make_wsgi_app(_doc())

        status, _headers, _body = call_wsgi(
            app, "POST", PATH, body=json.dumps(_payload()).encode("utf-8"))

        self.assertEqual(200, status)   # nothing to assert on export: none configured


if __name__ == "__main__":
    unittest.main()

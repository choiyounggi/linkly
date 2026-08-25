"""Outbound `traceparent` injection (issue #107, Task 03).

Reuses `_ServerTestCase`/`_make_handler` from test_network_driver.py per the
plan's D12 (`received_headers` fixture already exists — do not build a new
mock server). D6/D8 are exercised at the `Interpreter` level too, since
those decisions are about what the interpreter builds per call step, not
just what `HttpNetworkDriver` forwards.
"""

import unittest

from lnpl.drivers import FakeNetworkDriver, HttpNetworkDriver
from lnpl.interp import Interpreter
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import default_rows
from lnpl.tracecontext import format_traceparent
from lnpl.wsgi import make_wsgi_app

from tests.test_network_driver import _ServerTestCase, _make_handler
from tests.test_wsgi_contract import call_wsgi

TWO_CALLS_SOURCE = """capability postgres

service Checkout
    policy
        timeout 5s

workflow Ping
    call PaymentGateway as first
    call ShippingApi as second
"""

CALL_PATH = "/checkout/ping"
INBOUND_UNSAMPLED = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-00"


def compile_doc(source, module="m"):
    return lower(parse(source), module).to_document()


def workflow_id(doc):
    return next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")


class HttpDriverTraceHeaderTests(_ServerTestCase):
    def test_trace_headers_are_forwarded_verbatim(self):
        handler = _make_handler(status=200, body={})
        url = self.start(handler)
        driver = HttpNetworkDriver(endpoints={"PaymentGateway": url})
        self.addCleanup(driver.close)
        traceparent = format_traceparent("a" * 32, "b" * 16)

        driver.call("PaymentGateway", {}, 2000,
                   trace_headers={"traceparent": traceparent})

        self.assertEqual(handler.received_headers[0].get("traceparent"), traceparent)

    def test_runtime_trace_header_overrides_a_capability_declared_one(self):
        # D8: a capability that declares its OWN `traceparent` header must
        # still lose to the runtime-supplied value.
        handler = _make_handler(status=200, body={})
        url = self.start(handler)
        driver = HttpNetworkDriver(
            endpoints={"PaymentGateway": url},
            capabilities={"PaymentGateway": {
                "method": "POST",
                "headers": {"traceparent": "00-" + "f" * 32 + "-" + "f" * 16 + "-00"}}})
        self.addCleanup(driver.close)
        runtime_traceparent = format_traceparent("a" * 32, "b" * 16)

        driver.call("PaymentGateway", {}, 2000,
                   trace_headers={"traceparent": runtime_traceparent})

        self.assertEqual(handler.received_headers[0].get("traceparent"),
                         runtime_traceparent)

    def test_trace_headers_none_adds_nothing_byte_identical_to_before(self):
        handler = _make_handler(status=200, body={})
        url = self.start(handler)
        driver = HttpNetworkDriver(endpoints={"PaymentGateway": url})
        self.addCleanup(driver.close)

        driver.call("PaymentGateway", {}, 2000)

        self.assertNotIn("traceparent", handler.received_headers[0])

    def test_empty_trace_headers_adds_nothing_no_exception(self):
        handler = _make_handler(status=200, body={})
        url = self.start(handler)
        driver = HttpNetworkDriver(endpoints={"PaymentGateway": url})
        self.addCleanup(driver.close)

        driver.call("PaymentGateway", {}, 2000, trace_headers={})

        self.assertNotIn("traceparent", handler.received_headers[0])


class FakeNetworkDriverReceivedTests(unittest.TestCase):
    def test_received_records_the_call_return_value_unchanged(self):
        driver = FakeNetworkDriver({"PaymentGateway": (500, {"x": 1})})
        traceparent = format_traceparent("a" * 32, "b" * 16)

        status, body = driver.call("PaymentGateway", {"amount": 1}, 1000,
                                   trace_headers={"traceparent": traceparent})

        self.assertEqual((status, body), (500, {"x": 1}))
        self.assertEqual(driver.received, [{
            "target": "PaymentGateway", "payload": {"amount": 1},
            "trace_headers": {"traceparent": traceparent},
        }])

    def test_received_records_empty_dict_when_trace_headers_omitted(self):
        driver = FakeNetworkDriver({})

        driver.call("PaymentGateway", {}, 1000)

        self.assertEqual(driver.received[0]["trace_headers"], {})


class InterpreterOutboundInjectionTests(unittest.TestCase):
    """D6: the interpreter builds the header per call step; trace-id is
    invariant for the run, parent-id is that step's own span id."""

    def test_two_call_steps_share_trace_id_but_use_distinct_parent_ids(self):
        doc = compile_doc(TWO_CALLS_SOURCE)
        target = workflow_id(doc)
        payload = {}
        driver = FakeNetworkDriver({})
        interp = Interpreter(doc, repo_rows=default_rows(doc, target, payload),
                             network=driver)
        interp.trace.trace_id = "a" * 32  # Task 04 not landed yet in this task

        interp.run_workflow(target, payload)

        self.assertEqual(len(driver.received), 2)
        first_tp = driver.received[0]["trace_headers"]["traceparent"]
        second_tp = driver.received[1]["trace_headers"]["traceparent"]
        self.assertNotEqual(first_tp, second_tp)
        first_trace_id = first_tp.split("-")[1]
        second_trace_id = second_tp.split("-")[1]
        first_parent_id = first_tp.split("-")[2]
        second_parent_id = second_tp.split("-")[2]
        self.assertEqual(first_trace_id, "a" * 32)
        self.assertEqual(second_trace_id, "a" * 32)
        self.assertNotEqual(first_parent_id, second_parent_id)

    def test_no_trace_id_on_trace_means_no_trace_headers_sent(self):
        # Boundary: a direct `Interpreter(...)` construction (the `lnpl run`
        # path) never has `LnplWsgiApp._resolve_trace_context` populate
        # `self.trace.trace_id` -- it stays `None`, so no header is built.
        doc = compile_doc(TWO_CALLS_SOURCE)
        target = workflow_id(doc)
        payload = {}
        driver = FakeNetworkDriver({})
        interp = Interpreter(doc, repo_rows=default_rows(doc, target, payload),
                             network=driver)

        interp.run_workflow(target, payload)

        self.assertEqual(driver.received[0]["trace_headers"], {})


class TraceFlagsPropagationTests(unittest.TestCase):
    """r1-F1 / D6: trace-flags (the sampled bit) must be preserved on
    adoption, never silently forced to sampled. Driven end-to-end through
    `LnplWsgiApp` (not just `Interpreter` directly), since the flags
    decision itself lives in `_resolve_trace_context` (wsgi.py), not here.
    """

    def test_trust_on_inbound_unsampled_flags_propagate_to_the_outbound_header(self):
        driver = FakeNetworkDriver({})
        app = make_wsgi_app(compile_doc(TWO_CALLS_SOURCE), network=driver,
                            trust_incoming_trace=True)

        status, _headers, _body = call_wsgi(
            app, "POST", CALL_PATH, body=b"{}",
            headers={"traceparent": INBOUND_UNSAMPLED})

        self.assertEqual(200, status)
        traceparent = driver.received[0]["trace_headers"]["traceparent"]
        self.assertTrue(traceparent.endswith("-00"),
                        "upstream chose not to sample; we must not overturn that: %r"
                        % traceparent)
        self.assertEqual(traceparent.split("-")[1], "4bf92f3577b34da6a3ce929d0e0e4736")

    def test_trust_off_inbound_unsampled_flags_are_not_inherited_fresh_trace_is_01(self):
        driver = FakeNetworkDriver({})
        app = make_wsgi_app(compile_doc(TWO_CALLS_SOURCE), network=driver)
        # trust_incoming_trace defaults off

        status, _headers, _body = call_wsgi(
            app, "POST", CALL_PATH, body=b"{}",
            headers={"traceparent": INBOUND_UNSAMPLED})

        self.assertEqual(200, status)
        traceparent = driver.received[0]["trace_headers"]["traceparent"]
        self.assertNotEqual(traceparent.split("-")[1], "4bf92f3577b34da6a3ce929d0e0e4736")
        self.assertTrue(traceparent.endswith("-01"),
                        "a trace we minted ourselves gets our own decision: %r"
                        % traceparent)


if __name__ == "__main__":
    unittest.main()

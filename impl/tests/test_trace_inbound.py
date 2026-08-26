"""Inbound `traceparent` adoption (issue #107, Task 02).

`LnplWsgiApp._resolve_trace_context(environ)` is tested directly against a
minimal app instance (no real .lnpl document needed — the method reads only
`environ` and `self.trust_incoming_trace`), returning the 5-tuple
`(trace_id, span_id, link, tracestate, flags)`. CLI-flag registration is
driven through `lnpl.cli.main`, mirroring test_cli_observability.py's
convention.
"""

import contextlib
import io
import os
import unittest

from lnpl.cli import main
from lnpl.wsgi import LnplWsgiApp

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHORTEN = os.path.join(REPO, "examples", "shorten.lnpl")

VALID = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
VALID_UNSAMPLED = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-00"
MALFORMED = "not-a-traceparent"


def app(trust_incoming_trace=False):
    return LnplWsgiApp({"nodes": []}, {}, trust_incoming_trace=trust_incoming_trace)


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = main(argv)
    return rc, out.getvalue(), err.getvalue()


class ResolveTraceContextTests(unittest.TestCase):
    def test_trust_on_valid_traceparent_adopts_trace_id_new_span_id_no_link(self):
        trace_id, span_id, link, tracestate, flags = app(trust_incoming_trace=True)._resolve_trace_context(
            {"HTTP_TRACEPARENT": VALID})
        self.assertEqual(trace_id, "4bf92f3577b34da6a3ce929d0e0e4736")
        self.assertNotEqual(span_id, "00f067aa0ba902b7")
        self.assertIsNone(link)
        self.assertIsNone(tracestate)
        self.assertEqual(flags, "01")

    def test_trust_off_default_valid_traceparent_generates_new_id_records_link(self):
        trace_id, span_id, link, tracestate, flags = app(trust_incoming_trace=False)._resolve_trace_context(
            {"HTTP_TRACEPARENT": VALID})
        self.assertNotEqual(trace_id, "4bf92f3577b34da6a3ce929d0e0e4736")
        self.assertEqual(link, {"trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
                                "parent_id": "00f067aa0ba902b7"})

    def test_malformed_traceparent_generates_new_id_no_link_no_exception(self):
        trace_id, span_id, link, tracestate, flags = app(trust_incoming_trace=True)._resolve_trace_context(
            {"HTTP_TRACEPARENT": MALFORMED})
        self.assertIsNotNone(trace_id)
        self.assertIsNone(link)

    def test_absent_traceparent_generates_new_id(self):
        trace_id, span_id, link, tracestate, flags = app()._resolve_trace_context({})
        self.assertIsNotNone(trace_id)
        self.assertIsNotNone(span_id)
        self.assertIsNone(link)

    def test_tracestate_without_traceparent_is_discarded(self):
        # D5, W3C MUST: tracestate received without an accompanying valid
        # traceparent must not be parsed or forwarded.
        _, _, _, tracestate, _ = app()._resolve_trace_context(
            {"HTTP_TRACESTATE": "vendor1=value1"})
        self.assertIsNone(tracestate)

    def test_tracestate_with_invalid_traceparent_is_discarded(self):
        _, _, _, tracestate, _ = app()._resolve_trace_context(
            {"HTTP_TRACEPARENT": MALFORMED, "HTTP_TRACESTATE": "vendor1=value1"})
        self.assertIsNone(tracestate)

    def test_tracestate_with_valid_traceparent_is_kept_verbatim(self):
        _, _, _, tracestate, _ = app()._resolve_trace_context(
            {"HTTP_TRACEPARENT": VALID, "HTTP_TRACESTATE": "vendor1=value1,vendor2=value2"})
        self.assertEqual(tracestate, "vendor1=value1,vendor2=value2")

    def test_trust_on_span_id_is_always_freshly_generated_not_the_parent_id(self):
        _, span_id_a, _, _, _ = app(trust_incoming_trace=True)._resolve_trace_context(
            {"HTTP_TRACEPARENT": VALID})
        _, span_id_b, _, _, _ = app(trust_incoming_trace=True)._resolve_trace_context(
            {"HTTP_TRACEPARENT": VALID})
        self.assertNotEqual(span_id_a, span_id_b)

    def test_r1_f1_trust_on_unsampled_inbound_flags_are_propagated(self):
        # D6/r1-F1: adopting the inbound trace-id means adopting its
        # sampling decision too -- an upstream that chose NOT to sample
        # must not have that decision silently overturned.
        *_, flags = app(trust_incoming_trace=True)._resolve_trace_context(
            {"HTTP_TRACEPARENT": VALID_UNSAMPLED})
        self.assertEqual(flags, "00")

    def test_r1_f1_trust_off_unsampled_inbound_flags_are_not_inherited(self):
        # A trace-id we mint ourselves gets our own sampling decision
        # ("01"), never the unadopted inbound value -- there is no inbound
        # trace being continued here, so there is nothing to preserve.
        trace_id, _, _, _, flags = app(trust_incoming_trace=False)._resolve_trace_context(
            {"HTTP_TRACEPARENT": VALID_UNSAMPLED})
        self.assertNotEqual(trace_id, "4bf92f3577b34da6a3ce929d0e0e4736")
        self.assertEqual(flags, "01")

    def test_r1_f1_malformed_traceparent_flags_default_to_01(self):
        *_, flags = app()._resolve_trace_context({"HTTP_TRACEPARENT": MALFORMED})
        self.assertEqual(flags, "01")


class TrustIncomingTraceCliFlagTests(unittest.TestCase):
    def test_default_is_false(self):
        self.assertFalse(app().trust_incoming_trace)

    def test_constructor_accepts_true(self):
        self.assertTrue(app(trust_incoming_trace=True).trust_incoming_trace)

    def test_flag_is_registered_on_the_serve_subparser(self):
        # Same pattern as test_cli_observability.py's boundary test: force a
        # DIFFERENT, deterministic rejection (bad --backend) after argparse
        # has already accepted --trust-incoming-trace, proving it parsed
        # rather than tripping "unrecognized arguments".
        rc, out, err = run_cli(["serve", SHORTEN, "--port", "0",
                                "--trust-incoming-trace", "--backend", "redis://x"])
        self.assertEqual(2, rc)
        self.assertIn("redis://x", err)
        self.assertNotIn("unrecognized argument", err)


if __name__ == "__main__":
    unittest.main()

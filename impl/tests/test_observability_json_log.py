"""Issue #78: `--log-format json` — one JSON Line per HTTP request
(correlation_id/method/path/workflow/status/duration_ms/skipped[]/
diagnostics[]), and the default `text` format stays byte-identical (plan
t78-observability, D1/D2). `TraceExporter` itself is test_trace_exporter.py's
concern — this file is the access-log line only.
"""

import contextlib
import http.client
import io
import json
import unittest

from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.wsgi import make_wsgi_app
from tests.test_serve import ServerTestCase
from tests.test_serve_sse import TWO_EVENT_SRC, compile_src as compile_sse_src
from tests.test_wsgi_contract import call_wsgi
import lnpl.wsgi as wsgi_mod

# Vocabulary reused from test_masking_channels.py's own PAYMENT_SRC (closed
# vocabulary): a `when` guard whose false branch skips a step, a Password
# field to prove the log line never carries it raw. No `security jwt`, so a
# plain POST needs no Authorization header.
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
    when payment.amountCents <= 1000000
    update payment
"""

CARD = "4111111111111111"
PATH = "/payment-service/approval"


def _doc():
    return lower(parse(PAYMENT_SRC), "pay").to_document()


def _payload(amount_cents=500):
    return {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
            "cardNumber": CARD, "amountCents": amount_cents}


def _post_with_captured_stderr(app, payload):
    """-> (status, headers, body, json_log_line).

    stderr may also carry the pre-existing, unchanged plain-text diagnostic
    lines (`format_lines` — e.g. a guard skip) ahead of the JSON access-log
    line (D2: that channel is untouched by this issue), so the JSON line is
    picked out by what actually parses, not by position.
    """
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        status, headers, body = call_wsgi(
            app, "POST", PATH, body=json.dumps(payload).encode("utf-8"))
    raw_lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    json_lines = []
    for ln in raw_lines:
        try:
            json.loads(ln)
        except ValueError:
            continue
        json_lines.append(ln)
    return status, headers, body, json_lines


class JsonLogNormalTest(unittest.TestCase):
    """D5 normal: one request = one parseable JSON line with every required
    field (issue #78's own objective line)."""

    def test_normal_one_request_is_one_parseable_json_line_with_required_fields(self):
        app = make_wsgi_app(_doc(), log_format="json")

        status, _headers, body, lines = _post_with_captured_stderr(app, _payload())

        self.assertEqual(200, status)
        self.assertEqual(1, len(lines), lines)
        line = json.loads(lines[0])   # must parse — the whole point of D1
        self.assertEqual(body["correlation_id"], line["correlation_id"])
        self.assertTrue(line["correlation_id"].startswith("req-"))
        self.assertEqual("POST", line["method"])
        self.assertEqual(PATH, line["path"])
        self.assertEqual("wf.approval", line["workflow"])
        self.assertEqual(200, line["status"])
        self.assertIsInstance(line["duration_ms"], (int, float))
        self.assertGreaterEqual(line["duration_ms"], 0)
        self.assertEqual([], line["skipped"])
        self.assertEqual([], line["diagnostics"])


class JsonLogErrorTest(unittest.TestCase):
    """D5 error: a failure before any workflow ran (M1/M5) still gets exactly
    one log line — the access log is not opt-in per outcome."""

    def test_error_a_body_unreadable_rejection_still_logs_one_line(self):
        app = make_wsgi_app(_doc(), log_format="json")
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            status, _headers, body = call_wsgi(app, "POST", PATH, body=b"not json")
        lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]

        self.assertEqual(400, status)
        self.assertEqual("body-unreadable", body["code"])
        self.assertEqual(1, len(lines), lines)
        line = json.loads(lines[0])
        self.assertEqual(400, line["status"])
        self.assertEqual("POST", line["method"])
        self.assertEqual([], line["skipped"])


class JsonLogBoundaryTest(unittest.TestCase):
    """D5 boundary: text-mode byte invariance, a skipped guard riding the log
    line, and sensitive fields never appearing raw."""

    def test_boundary_default_text_mode_emits_no_log_line_at_all(self):
        # D2: the pre-existing suite is the primary byte-invariance witness
        # (unchanged response bytes); this pins the other half — silence.
        app_default = make_wsgi_app(_doc())
        app_explicit_text = make_wsgi_app(_doc(), log_format="text")
        payload = _payload()

        buf1 = io.StringIO()
        with contextlib.redirect_stderr(buf1):
            status1, headers1, body1 = call_wsgi(
                app_default, "POST", PATH, body=json.dumps(payload).encode())
        buf2 = io.StringIO()
        with contextlib.redirect_stderr(buf2):
            status2, headers2, body2 = call_wsgi(
                app_explicit_text, "POST", PATH, body=json.dumps(payload).encode())

        self.assertEqual(status1, status2)
        self.assertEqual(headers1, headers2)
        self.assertEqual(
            {k: v for k, v in body1.items() if k != "correlation_id"},
            {k: v for k, v in body2.items() if k != "correlation_id"})
        self.assertEqual("", buf1.getvalue())
        self.assertEqual("", buf2.getvalue())

    def test_boundary_a_skipped_guard_rides_in_the_json_log_line(self):
        app = make_wsgi_app(_doc(), log_format="json")

        status, _headers, body, lines = _post_with_captured_stderr(
            app, _payload(amount_cents=2000000))

        self.assertEqual(200, status)   # a guard skip is not a failure (M9)
        self.assertEqual(1, len(body["skipped"]))
        line = json.loads(lines[0])
        self.assertEqual(body["skipped"], line["skipped"])

    def test_boundary_sensitive_field_never_appears_raw_in_the_json_log_line(self):
        app = make_wsgi_app(_doc(), log_format="json")

        _status, _headers, _body, lines = _post_with_captured_stderr(
            app, _payload())

        self.assertNotIn(CARD, lines[0])


class JsonLogSseBoundaryTest(ServerTestCase):
    """D5 boundary: an SSE request logs exactly one line, at stream end — not
    at connection open, since duration must reflect the stream's lifetime."""

    def setUp(self):
        self._orig_poll = wsgi_mod.SSE_POLL_INTERVAL_S
        self._orig_idle = wsgi_mod.SSE_IDLE_TIMEOUT_S
        wsgi_mod.SSE_POLL_INTERVAL_S = 0.02
        wsgi_mod.SSE_IDLE_TIMEOUT_S = 0.3
        self.addCleanup(self._restore_timing)

    def _restore_timing(self):
        wsgi_mod.SSE_POLL_INTERVAL_S = self._orig_poll
        wsgi_mod.SSE_IDLE_TIMEOUT_S = self._orig_idle

    def test_boundary_an_idle_sse_stream_logs_one_line_when_it_closes(self):
        doc = compile_sse_src(TWO_EVENT_SRC)
        port = self.start(doc, log_format="json")
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        self.addCleanup(conn.close)

        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            conn.request("GET", "/orders/events/order-placed",
                        headers={"Authorization": "Bearer test-token"})
            resp = conn.getresponse()
            self.assertEqual(200, resp.status)
            raw = resp.fp.readline()   # blocks until idle timeout ends it
            self.assertEqual(b"", raw, "an idle stream must reach a clean EOF")

        lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
        self.assertEqual(1, len(lines), buf.getvalue())
        line = json.loads(lines[0])
        self.assertEqual("GET", line["method"])
        self.assertEqual("/orders/events/order-placed", line["path"])
        self.assertEqual(200, line["status"])


if __name__ == "__main__":
    unittest.main()

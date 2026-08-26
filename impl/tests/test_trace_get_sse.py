"""issue #123: `trace_id`/`span_id` on the GET single/list and SSE canonical
lines too -- issue #107 wired this for the workflow POST path only (a
deliberately narrow, non-blocking gap the #107 review left open). No `Trace`
object for GET/SSE (plan D3/D5): only the canonical `--log-format json` line
carries the two keys, seeded once per request in `_call_with_json_log` and
read out of `log_sink` by `_emit_request_log`.

Reuses the established JSON-log stderr-capture harness
(test_observability_json_log.py, test_trace_canonical_line.py) and the SSE
fixtures from test_serve_sse.py.
"""

import contextlib
import io
import json
import unittest
from unittest import mock

from lnpl.interp import FakeRepository
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.wsgi import make_wsgi_app
import lnpl.wsgi as wsgi_mod

from tests.test_serve import ServerTestCase
from tests.test_serve_sse import TWO_EVENT_SRC, compile_src as compile_sse_src
from tests.test_wsgi_contract import call_wsgi

ORDERS_SRC = """capability postgres

entity Order
    field
        id UUID
        placedAt DateTime
        total Integer

service Orders
    policy
        retry 0
    security
        jwt
    expose
        list Order by placedAt

workflow SaveOrder
    validate order
    find order
"""

VALID = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
MALFORMED = "not-a-traceparent"


def doc():
    return lower(parse(ORDERS_SRC), "m").to_document()


def uid(n):
    return "3f2504e0-4f89-41d3-9a0c-0305e82c33%02x" % n


def order_payload(id_):
    return {"id": id_, "placedAt": "2026-01-01T00:00:00Z", "total": 100}


class GetSingleTraceTest(ServerTestCase):
    def setUp(self):
        self.repo = FakeRepository()
        self.port = self.start(doc(), repository_factory=lambda: self.repo,
                               log_format="json", trust_incoming_trace=True)

    def _save(self, port, id_):
        resp, body = self.post_json(port, "/orders/save-order", order_payload(id_))
        self.assertEqual(200, resp.status, body)

    def _get_with_headers(self, port, path, headers=None):
        h = dict(headers or {})
        h.setdefault("Authorization", "Bearer x")
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            resp, raw = self.request(port, "GET", path, headers=h)
        lines = [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]
        return resp, raw, lines

    def test_normal_valid_inbound_traceparent_trust_on_get_single_trace_id_matches(self):
        self._save(self.port, uid(1))

        resp, _raw, lines = self._get_with_headers(
            self.port, "/orders/order/%s" % uid(1), headers={"traceparent": VALID})

        self.assertEqual(200, resp.status)
        self.assertEqual(1, len(lines), lines)
        self.assertEqual("4bf92f3577b34da6a3ce929d0e0e4736", lines[0]["trace_id"])

    def test_negative_trust_off_get_single_does_not_adopt_inbound_trace_id(self):
        repo = FakeRepository()
        port = self.start(doc(), repository_factory=lambda: repo,
                          log_format="json")   # trust_incoming_trace defaults off
        self._save(port, uid(2))

        resp, _raw, lines = self._get_with_headers(
            port, "/orders/order/%s" % uid(2), headers={"traceparent": VALID})

        self.assertEqual(200, resp.status)
        self.assertNotEqual("4bf92f3577b34da6a3ce929d0e0e4736", lines[0]["trace_id"])

    def test_boundary_no_traceparent_header_gets_a_fresh_trace_id_and_succeeds(self):
        self._save(self.port, uid(3))

        resp, _raw, lines = self._get_with_headers(
            self.port, "/orders/order/%s" % uid(3))

        self.assertEqual(200, resp.status)
        self.assertIn("trace_id", lines[0])
        self.assertIsNotNone(lines[0]["trace_id"])

    def test_boundary_malformed_traceparent_does_not_fail_the_request(self):
        self._save(self.port, uid(4))

        resp, _raw, lines = self._get_with_headers(
            self.port, "/orders/order/%s" % uid(4), headers={"traceparent": MALFORMED})

        self.assertEqual(200, resp.status)
        self.assertIn("trace_id", lines[0])
        self.assertIsNotNone(lines[0]["trace_id"])


class GetListTraceTest(ServerTestCase):
    def setUp(self):
        self.repo = FakeRepository()
        self.port = self.start(doc(), repository_factory=lambda: self.repo,
                               log_format="json")

    def test_normal_get_list_canonical_line_carries_a_trace_id(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            resp, _raw = self.request(self.port, "GET", "/orders/order",
                                      headers={"Authorization": "Bearer x"})
        lines = [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]

        self.assertEqual(200, resp.status)
        self.assertEqual(1, len(lines), lines)
        self.assertIn("trace_id", lines[0])
        self.assertIsNotNone(lines[0]["trace_id"])


class SseTraceTest(ServerTestCase):
    """Mirrors test_observability_json_log.py's idle-SSE-stream harness --
    D2: `_log_sse_then` must receive `log_sink` (seeded with the trace
    context in `_call_with_json_log`), not the literal `{}` it passed before
    this task."""

    def setUp(self):
        self._orig_poll = wsgi_mod.SSE_POLL_INTERVAL_S
        self._orig_idle = wsgi_mod.SSE_IDLE_TIMEOUT_S
        wsgi_mod.SSE_POLL_INTERVAL_S = 0.02
        wsgi_mod.SSE_IDLE_TIMEOUT_S = 0.3
        self.addCleanup(self._restore_timing)

    def _restore_timing(self):
        wsgi_mod.SSE_POLL_INTERVAL_S = self._orig_poll
        wsgi_mod.SSE_IDLE_TIMEOUT_S = self._orig_idle

    def _subscribe_with_headers(self, headers):
        import http.client
        doc_ = compile_sse_src(TWO_EVENT_SRC)
        port = self.start(doc_, log_format="json", trust_incoming_trace=True)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        self.addCleanup(conn.close)
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            conn.request("GET", "/orders/events/order-placed", headers=headers)
            resp = conn.getresponse()
            self.assertEqual(200, resp.status)
            raw = resp.fp.readline()
            self.assertEqual(b"", raw, "an idle stream must reach a clean EOF")
        lines = [json.loads(ln) for ln in buf.getvalue().splitlines() if ln.strip()]
        return resp, lines

    def test_normal_valid_inbound_traceparent_trust_on_sse_trace_id_matches(self):
        _resp, lines = self._subscribe_with_headers(
            {"Authorization": "Bearer test-token", "traceparent": VALID})

        self.assertEqual(1, len(lines), lines)
        self.assertEqual("4bf92f3577b34da6a3ce929d0e0e4736", lines[0]["trace_id"])
        self.assertIn("span_id", lines[0])


class ResolveTraceContextCallCountTest(unittest.TestCase):
    """D1: exactly one `_resolve_trace_context` call per request, whatever
    the route kind or log format -- two calls would mint two different
    span_ids and let the canonical line and any `Trace` disagree."""

    def setUp(self):
        self._orig_poll = wsgi_mod.SSE_POLL_INTERVAL_S
        self._orig_idle = wsgi_mod.SSE_IDLE_TIMEOUT_S
        wsgi_mod.SSE_POLL_INTERVAL_S = 0.01
        wsgi_mod.SSE_IDLE_TIMEOUT_S = 0.05
        self.addCleanup(self._restore_timing)

    def _restore_timing(self):
        wsgi_mod.SSE_POLL_INTERVAL_S = self._orig_poll
        wsgi_mod.SSE_IDLE_TIMEOUT_S = self._orig_idle

    def _call_count(self, app, method, path, **kw):
        with mock.patch.object(app, "_resolve_trace_context",
                               wraps=app._resolve_trace_context) as spy:
            call_wsgi(app, method, path, **kw)
        return spy.call_count

    def test_json_mode_post_workflow_resolves_exactly_once(self):
        app = make_wsgi_app(doc(), log_format="json")

        n = self._call_count(
            app, "POST", "/orders/save-order",
            body=json.dumps(order_payload(uid(10))).encode("utf-8"),
            headers={"Authorization": "Bearer x"})

        self.assertEqual(1, n)

    def test_json_mode_get_single_resolves_exactly_once(self):
        repo = FakeRepository()
        app = make_wsgi_app(doc(), repository_factory=lambda: repo, log_format="json")
        call_wsgi(app, "POST", "/orders/save-order",
                 body=json.dumps(order_payload(uid(11))).encode("utf-8"),
                 headers={"Authorization": "Bearer x"})

        n = self._call_count(app, "GET", "/orders/order/%s" % uid(11),
                             headers={"Authorization": "Bearer x"})

        self.assertEqual(1, n)

    def test_json_mode_sse_resolves_exactly_once(self):
        app = make_wsgi_app(compile_sse_src(TWO_EVENT_SRC), log_format="json")

        n = self._call_count(app, "GET", "/orders/events/order-placed",
                             headers={"Authorization": "Bearer test-token"})

        self.assertEqual(1, n)

    def test_text_mode_post_workflow_still_resolves_exactly_once(self):
        # D1's r1 fallback: `_respond` keeps self-resolving when no
        # `trace_ctx` is threaded in -- text mode never goes through
        # `_call_with_json_log` at all (`__call__` only routes there when
        # `log_format == "json"`), so this is the only resolution it gets.
        app = make_wsgi_app(doc(), log_format="text")

        n = self._call_count(
            app, "POST", "/orders/save-order",
            body=json.dumps(order_payload(uid(12))).encode("utf-8"),
            headers={"Authorization": "Bearer x"})

        self.assertEqual(1, n)


if __name__ == "__main__":
    unittest.main()

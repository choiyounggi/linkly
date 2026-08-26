"""Issue #110, Task 03: `/-/metrics` (`--metrics` opt-in, RED 3).

`Trace.metric`'s label allowlist already blocks unbounded-cardinality
labels at the source (RFC-0003) — this task's whole job is exposing an
aggregate ON TOP of that guarantee, in a shape Prometheus can scrape,
without touching the per-request `Trace.metrics` array `--trace-exporter`
(#78) already depends on (D9).

Normal: `--metrics` on serves RED 3 in Prometheus text format, parsed (not
line-counted) into real values; two runs of the same workflow accumulate
(D9's whole point — this survives across requests, `Trace.metrics` does
not). Error: `--metrics` off (the default) makes `/-/metrics` a plain 404;
a label outside the allowlist still raises `RunError` (D7's "no new label
axis" holds, unchanged from before this issue existed). Boundary: zero
workflow runs still renders a valid, parseable exposition (HELP/TYPE
present, zero series — not an empty body).
"""

import io
import re
import unittest

from lnpl.drivers import HmacTokenProvider
from lnpl.interp import RunError, Trace
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.wsgi import MetricsRegistry, make_wsgi_app

from tests.test_wsgi_contract import call_wsgi

# `validate input` rejects a payload missing required fields (RFC-0001) —
# the deterministic way to make one workflow both succeed and fail without
# a second document.
ORDER_SRC = """entity Order
    field
        id UUID
        amount Integer

service OrderService

workflow PlaceOrder
    validate input
    create order
"""

ORDER_PATH = "/order-service/place-order"
VALID_ORDER = (b'{"id":"3f2504e0-4f89-41d3-9a0c-0305e82c3301","amount":5}')

# `security jwt` + `security role admin` together — D2's unauthenticated
# exemption has to hold for `/-/metrics` too, the same as healthz/readyz
# (test_ops_surface.py already covers those two).
ROLE_GATED_SRC = """entity Order
    field
        id UUID
        amount Integer

service OrderService
    security
        jwt
        role admin

workflow PlaceOrder
    validate input
    create order
"""

SECRET = b"0123456789abcdef0123456789abcdef"          # exactly 32 bytes


def _doc(src, module="m110metrics"):
    return lower(parse(src), module).to_document()


def _raw_get(app, path):
    """Like `call_wsgi` but returns the raw (non-JSON) body — `/-/metrics`
    is Prometheus text, not `application/json`."""
    environ = {
        "REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": "",
        "wsgi.input": io.BytesIO(b""), "wsgi.errors": io.StringIO(),
        "wsgi.version": (1, 0), "wsgi.multithread": True,
        "wsgi.multiprocess": False, "wsgi.run_once": False,
        "wsgi.url_scheme": "http", "SERVER_NAME": "test", "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1", "SCRIPT_NAME": "",
    }
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = dict(headers)

    result = app(environ, start_response)
    raw = b"".join(result)
    status_code = int(captured["status"].split(" ", 1)[0])
    return status_code, captured["headers"], raw


_SERIES_RE = re.compile(r'^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)'
                        r'(\{(?P<labels>[^}]*)\})?\s+(?P<value>\S+)$')
_LABEL_RE = re.compile(r'(?P<key>[a-zA-Z_][a-zA-Z0-9_]*)="(?P<value>(?:[^"\\]|\\.)*)"')


def parse_prometheus_text(text):
    """The exposition format's data lines -> {(metric_name, frozenset of
    (label, value) pairs): float value}. `# HELP`/`# TYPE` lines (and
    blanks) are skipped — this is a real parse of the series, not a
    substring/line-count check."""
    series = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        match = _SERIES_RE.match(line)
        if match is None:
            raise AssertionError("unparseable exposition line: %r" % line)
        labels = frozenset(
            (m.group("key"), m.group("value"))
            for m in _LABEL_RE.finditer(match.group("labels") or ""))
        series[(match.group("name"), labels)] = float(match.group("value"))
    return series


class NormalTest(unittest.TestCase):

    def test_normal_metrics_needs_no_token_on_a_role_gated_service(self):
        # D2's exemption applies to all three ops paths, not just
        # healthz/readyz — a kubelet scraping metrics never carries a token
        # either.
        provider = HmacTokenProvider(SECRET)
        app = make_wsgi_app(_doc(ROLE_GATED_SRC), token_provider=provider,
                            metrics=True)

        status, headers, _raw = _raw_get(app, "/-/metrics")

        self.assertEqual(200, status)
        self.assertIn("text/plain", headers["Content-Type"])

    def test_normal_metrics_off_route_never_exists(self):
        # Regression sibling of the error-case 404 below: confirms the
        # route is absent from the routing table itself (D6), not merely
        # rendered empty.
        app = make_wsgi_app(_doc(ORDER_SRC))
        self.assertNotIn("/-/metrics", app.routes)

    def test_normal_metrics_on_serves_red_three_in_prometheus_format(self):
        app = make_wsgi_app(_doc(ORDER_SRC), metrics=True)
        call_wsgi(app, "POST", ORDER_PATH, body=VALID_ORDER)

        status, headers, raw = _raw_get(app, "/-/metrics")

        self.assertEqual(200, status)
        self.assertIn("text/plain", headers["Content-Type"])
        series = parse_prometheus_text(raw.decode("utf-8"))
        runs_key = ("lnpl_workflow_runs_total",
                   frozenset({("service", "OrderService"),
                              ("workflow", "PlaceOrder"),
                              ("status", "completed")}))
        self.assertEqual(1.0, series[runs_key])
        count_key = ("lnpl_workflow_duration_seconds_count",
                    frozenset({("service", "OrderService"),
                               ("workflow", "PlaceOrder")}))
        self.assertEqual(1.0, series[count_key])

    def test_normal_two_runs_of_the_same_workflow_accumulate(self):
        # D9: the registry survives across requests — `Trace.metrics` would
        # not (a fresh array every request). This is the whole reason a
        # process-level registry exists alongside it.
        app = make_wsgi_app(_doc(ORDER_SRC), metrics=True)
        call_wsgi(app, "POST", ORDER_PATH, body=VALID_ORDER)
        call_wsgi(app, "POST", ORDER_PATH, body=VALID_ORDER)

        _status, _headers, raw = _raw_get(app, "/-/metrics")

        series = parse_prometheus_text(raw.decode("utf-8"))
        runs_key = ("lnpl_workflow_runs_total",
                   frozenset({("service", "OrderService"),
                              ("workflow", "PlaceOrder"),
                              ("status", "completed")}))
        self.assertEqual(2.0, series[runs_key])

    def test_normal_a_failed_run_increments_step_failures_and_status_label(self):
        app = make_wsgi_app(_doc(ORDER_SRC), metrics=True)
        call_wsgi(app, "POST", ORDER_PATH, body=VALID_ORDER)          # completed
        call_wsgi(app, "POST", ORDER_PATH, body=b"{}")                # validation-failed

        _status, _headers, raw = _raw_get(app, "/-/metrics")

        series = parse_prometheus_text(raw.decode("utf-8"))
        completed_key = ("lnpl_workflow_runs_total",
                        frozenset({("service", "OrderService"),
                                   ("workflow", "PlaceOrder"),
                                   ("status", "completed")}))
        failed_key = ("lnpl_workflow_runs_total",
                     frozenset({("service", "OrderService"),
                                ("workflow", "PlaceOrder"),
                                ("status", "failed")}))
        self.assertEqual(1.0, series[completed_key])
        self.assertEqual(1.0, series[failed_key])
        failure_key = ("lnpl_step_failures_total",
                      frozenset({("service", "OrderService"),
                                 ("workflow", "PlaceOrder"),
                                 ("step", "validate input"),
                                 ("kind", "validation-failed")}))
        self.assertEqual(1.0, series[failure_key])


class ErrorTest(unittest.TestCase):

    def test_error_metrics_off_by_default_is_404(self):
        app = make_wsgi_app(_doc(ORDER_SRC))

        status, _headers, body = call_wsgi(app, "GET", "/-/metrics")

        self.assertEqual(404, status)
        self.assertEqual("not-found", body["code"])

    def test_error_a_label_outside_the_allowlist_still_raises_run_error(self):
        # D7: no new label axis — the allowlist `Trace.metric` already
        # enforced keeps enforcing it, this issue only adds a reader.
        trace = Trace("req-test")
        with self.assertRaises(RunError) as cm:
            trace.metric("custom", {"user_id": "u-1"}, 1)
        self.assertIn("user_id", str(cm.exception))


class BoundaryTest(unittest.TestCase):

    def test_boundary_zero_runs_still_renders_a_parseable_exposition(self):
        app = make_wsgi_app(_doc(ORDER_SRC), metrics=True)

        status, _headers, raw = _raw_get(app, "/-/metrics")

        self.assertEqual(200, status)
        text = raw.decode("utf-8")
        self.assertNotEqual(b"", raw)
        self.assertIn("# TYPE lnpl_workflow_runs_total counter", text)
        series = parse_prometheus_text(text)
        self.assertEqual({}, series)

    def test_boundary_registry_render_is_thread_safe_under_concurrent_updates(self):
        # D10: a lock-free `+=` would lose updates — 50 concurrent
        # record_run calls must all land.
        import threading as _threading
        registry = MetricsRegistry()
        threads = [_threading.Thread(
            target=lambda: registry.record_run("svc", "wf", "completed", 0.01))
            for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        series = parse_prometheus_text(registry.render())
        key = ("lnpl_workflow_runs_total",
              frozenset({("service", "svc"), ("workflow", "wf"),
                         ("status", "completed")}))
        self.assertEqual(50.0, series[key])


if __name__ == "__main__":
    unittest.main()

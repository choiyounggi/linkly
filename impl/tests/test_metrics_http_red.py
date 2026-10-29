"""issue #237: `/-/metrics` per-route HTTP RED series.

Normal: the registry counts HTTP responses by route/method/status and
observes their duration; cache/claim counters and caller-supplied gauges
render; through the app, 429 (text and json log modes), 401 and 503 are
counted, a single-row GET uses its route template, an SSE stream is
observed when it ends, and a scrape counts the scrape before it. Error:
`Trace.metric`'s label allowlist still rejects a `route` label (D7's
revision widened the registry, not the per-request trace); an unmatched
path (GET of any depth, or a non-GET with or without a query string)
collapses to `unmatched`, an unknown method to `other`, and an
escaping exception is counted as 500. Boundary: a fresh registry renders
every new family's HELP/TYPE with no series; an SSE stream closed before
its first chunk is still counted; 50 concurrent requests are all counted.
The Grafana RED example (examples/deploy/grafana-red-dashboard.json) has
the three panels, queries only series a live scrape declares, never
charts an average, and gives every target a unique refId.
"""

import contextlib
import io
import json
import os
import re
import tempfile
import threading
import time
import unittest

import lnpl.wsgi as wsgi_mod
from lnpl.drivers import HmacTokenProvider, SqliteRepositoryDriver
from lnpl.interp import RunError, Trace
from lnpl.wsgi import MetricsRegistry, make_wsgi_app
from tests.test_ops_metrics import (ORDER_PATH, ORDER_SRC, SECRET, VALID_ORDER,
                                    _doc, _raw_get, parse_prometheus_text)
from tests.test_serve_sse import TWO_EVENT_SRC
from tests.test_wsgi_contract import _wsgi_environ, call_wsgi

JWT_SRC = ORDER_SRC.replace("service OrderService\n",
                            "service OrderService\n    security\n        jwt\n")
SSE_SRC = TWO_EVENT_SRC.replace("    security\n        jwt\n", "")
SSE_PATH = "/orders/events/order-placed"
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GRAFANA = os.path.join(REPO, "examples", "deploy", "grafana-red-dashboard.json")


def _panel_exprs(dashboard):
    return [t["expr"] for p in dashboard["panels"] for t in p["targets"]]


def _family(name):
    for suffix in ("_bucket", "_sum", "_count"):
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


def _grafana():
    with open(GRAFANA, encoding="utf-8") as f:
        return json.load(f)


def _scratch_dir(test):
    root = os.path.join(REPO, ".claude", "tmp")
    os.makedirs(root, exist_ok=True)
    box = tempfile.TemporaryDirectory(dir=root)
    test.addCleanup(box.cleanup)
    return box.name


def _scrape(app):
    return parse_prometheus_text(_raw_get(app, "/-/metrics")[2].decode("utf-8"))


def _http_key(route, method, status):
    return ("lnpl_http_requests_total",
            frozenset({("route", route), ("method", method), ("status", status)}))


def _sse_app(test):
    originals = (wsgi_mod.SSE_POLL_INTERVAL_S, wsgi_mod.SSE_IDLE_TIMEOUT_S)

    def restore():
        wsgi_mod.SSE_POLL_INTERVAL_S, wsgi_mod.SSE_IDLE_TIMEOUT_S = originals
    test.addCleanup(restore)
    wsgi_mod.SSE_POLL_INTERVAL_S = 0.01
    wsgi_mod.SSE_IDLE_TIMEOUT_S = 0.05
    db = os.path.join(_scratch_dir(test), "store.db")
    return make_wsgi_app(_doc(SSE_SRC),
                         repository_factory=lambda: SqliteRepositoryDriver(db),
                         metrics=True)


class NormalTest(unittest.TestCase):

    def test_normal_registry_counts_http_requests_by_route_method_status(self):
        r = MetricsRegistry()
        r.record_http_request("/a", "GET", "200", 0.001)
        r.record_http_request("/a", "GET", "200", 0.001)
        r.record_http_request("/a", "GET", "404", 0.3)
        series = parse_prometheus_text(r.render())
        self.assertEqual(2.0, series[("lnpl_http_requests_total", frozenset(
            {("route", "/a"), ("method", "GET"), ("status", "200")}))])
        self.assertEqual(1.0, series[("lnpl_http_requests_total", frozenset(
            {("route", "/a"), ("method", "GET"), ("status", "404")}))])
        self.assertEqual(3.0, series[("lnpl_http_request_duration_seconds_count",
                                      frozenset({("route", "/a")}))])
        self.assertEqual(2.0, series[("lnpl_http_request_duration_seconds_bucket",
                                      frozenset({("route", "/a"), ("le", "0.005")}))])
        self.assertEqual(3.0, series[("lnpl_http_request_duration_seconds_bucket",
                                      frozenset({("route", "/a"), ("le", "+Inf")}))])

    def test_normal_registry_counts_cache_ops_and_claims_and_renders_gauges(self):
        r = MetricsRegistry()
        r.record_cache_op("get", "hit")
        r.record_cache_op("get", "hit")
        r.record_idempotency_claim("started")
        text = r.render(gauges=[
            ("lnpl_outbox_undelivered",
             "Outbox rows not yet delivered, sampled at scrape time.", 2),
            ("lnpl_driver_ratio", "x", 0.5)])
        series = parse_prometheus_text(text)
        self.assertEqual(2.0, series[("lnpl_cache_ops_total", frozenset(
            {("op", "get"), ("result", "hit")}))])
        self.assertEqual(1.0, series[("lnpl_idempotency_claims_total", frozenset(
            {("status", "started")}))])
        self.assertEqual(2.0, series[("lnpl_outbox_undelivered", frozenset())])
        self.assertEqual(0.5, series[("lnpl_driver_ratio", frozenset())])
        self.assertIn("# TYPE lnpl_outbox_undelivered gauge", text)

    def test_normal_429_after_200_is_counted_in_text_mode(self):
        app = make_wsgi_app(_doc(ORDER_SRC), metrics=True, rate_limit=1)
        statuses = [call_wsgi(app, "POST", ORDER_PATH, body=VALID_ORDER)[0]
                    for _ in range(2)]
        self.assertEqual([200, 429], statuses)
        series = _scrape(app)
        self.assertEqual(1.0, series[_http_key(ORDER_PATH, "POST", "200")])
        self.assertEqual(1.0, series[_http_key(ORDER_PATH, "POST", "429")])

    def test_normal_429_is_counted_in_json_log_mode(self):
        with contextlib.redirect_stderr(io.StringIO()):
            app = make_wsgi_app(_doc(ORDER_SRC), metrics=True, rate_limit=1,
                                log_format="json")
            statuses = [call_wsgi(app, "POST", ORDER_PATH, body=VALID_ORDER)[0]
                        for _ in range(2)]
            series = _scrape(app)
        self.assertEqual([200, 429], statuses)
        self.assertEqual(1.0, series[_http_key(ORDER_PATH, "POST", "429")])

    def test_normal_401_without_a_token_is_counted(self):
        app = make_wsgi_app(_doc(JWT_SRC), token_provider=HmacTokenProvider(SECRET),
                            metrics=True)
        status, _, _ = call_wsgi(app, "POST", ORDER_PATH, body=VALID_ORDER)
        self.assertEqual(401, status)
        self.assertEqual(1.0, _scrape(app)[_http_key(ORDER_PATH, "POST", "401")])

    def test_normal_503_while_shutting_down_is_counted(self):
        app = make_wsgi_app(_doc(ORDER_SRC), metrics=True)
        app.begin_shutdown()
        status, _, _ = call_wsgi(app, "POST", ORDER_PATH, body=VALID_ORDER)
        self.assertEqual(503, status)
        self.assertEqual(1.0, _scrape(app)[_http_key(ORDER_PATH, "POST", "503")])

    def test_normal_duration_histogram_observes_each_response_once(self):
        app = make_wsgi_app(_doc(ORDER_SRC), metrics=True)
        self.assertEqual(200, call_wsgi(app, "POST", ORDER_PATH, body=VALID_ORDER)[0])
        series = _scrape(app)
        self.assertEqual(1.0, series[("lnpl_http_request_duration_seconds_count",
                                      frozenset({("route", ORDER_PATH)}))])
        self.assertEqual(1.0, series[("lnpl_http_request_duration_seconds_bucket",
                                      frozenset({("route", ORDER_PATH), ("le", "+Inf")}))])

    def test_normal_get_single_uses_the_route_template(self):
        app = make_wsgi_app(_doc(ORDER_SRC), metrics=True)
        for suffix in ("3301", "3302"):
            status, _, _ = call_wsgi(
                app, "GET", "/order-service/order/3f2504e0-4f89-41d3-9a0c-0305e82c" + suffix)
            self.assertEqual(404, status)
        text = _raw_get(app, "/-/metrics")[2].decode("utf-8")
        self.assertEqual(2.0, parse_prometheus_text(text)[
            _http_key("/order-service/order/{id}", "GET", "404")])
        self.assertNotIn("0305e82c3301", text)
        self.assertNotIn("0305e82c3302", text)

    def test_normal_sse_stream_is_observed_when_it_ends(self):
        app = _sse_app(self)
        result = app(_wsgi_environ("GET", SSE_PATH), lambda s, h, e=None: None)
        count_key = ("lnpl_http_request_duration_seconds_count",
                     frozenset({("route", SSE_PATH)}))
        self.assertNotIn(count_key, _scrape(app))
        b"".join(result)
        result.close()
        series = _scrape(app)
        self.assertEqual(1.0, series[count_key])
        self.assertEqual(1.0, series[_http_key(SSE_PATH, "GET", "200")])

    def test_normal_second_scrape_counts_the_first_scrape_only(self):
        app = make_wsgi_app(_doc(ORDER_SRC), metrics=True)
        _raw_get(app, "/-/metrics")
        series = _scrape(app)
        self.assertEqual(1.0, series[_http_key("/-/metrics", "GET", "200")])

    def test_normal_parser_reads_a_brace_inside_a_label_value(self):
        self.assertEqual(
            {("m", frozenset({("route", "/a/b/{id}"), ("status", "404")})): 2.0},
            parse_prometheus_text('m{route="/a/b/{id}",status="404"} 2\n'))

    def test_normal_grafana_example_has_the_three_red_panels(self):
        d = _grafana()
        self.assertEqual(["Rate", "Errors", "Duration p95"], [p["title"] for p in d["panels"]])
        exprs = _panel_exprs(d)
        self.assertTrue(any("lnpl_http_requests_total" in e for e in exprs))
        self.assertTrue(any("lnpl_http_request_duration_seconds_bucket" in e for e in exprs))
        self.assertFalse(any("avg(" in e for e in exprs))

    def test_normal_every_series_the_grafana_example_queries_exists(self):
        names = {_family(n) for e in _panel_exprs(_grafana())
                 for n in re.findall(r"lnpl_[a-z_]+", e)}
        text = _raw_get(make_wsgi_app(_doc(ORDER_SRC), metrics=True), "/-/metrics")[2].decode("utf-8")
        for name in names:
            self.assertRegex(text, r"(?m)^# TYPE %s " % re.escape(name))
        self.assertIn("lnpl_http_request_duration_seconds", names)


class ErrorTest(unittest.TestCase):

    def test_error_trace_metric_still_rejects_a_route_label(self):
        with self.assertRaises(RunError):
            Trace("req-test").metric("custom", {"route": "/a"}, 1)
        self.assertIn("route", MetricsRegistry.__doc__)
        self.assertIn("unmatched", MetricsRegistry.__doc__)

    def test_error_parser_still_rejects_an_unclosed_label_set(self):
        with self.assertRaises(AssertionError):
            parse_prometheus_text('broken{a="x" 1\n')

    def test_error_family_strip_leaves_unsuffixed_names_alone(self):
        self.assertEqual("lnpl_http_requests_total", _family("lnpl_http_requests_total"))
        self.assertEqual("lnpl_http_request_duration_seconds",
                         _family("lnpl_http_request_duration_seconds_bucket"))

    def test_error_unmatched_path_collapses_to_one_label(self):
        app = make_wsgi_app(_doc(ORDER_SRC), metrics=True)
        for _ in range(2):
            self.assertEqual(404, call_wsgi(app, "GET", "/no/such/path")[0])
        text = _raw_get(app, "/-/metrics")[2].decode("utf-8")
        self.assertEqual(2.0, parse_prometheus_text(text)[
            _http_key("unmatched", "GET", "404")])
        self.assertNotIn("/no/such/path", text)

    def test_error_unmatched_post_collapses_to_one_label(self):
        app = make_wsgi_app(_doc(ORDER_SRC), metrics=True)
        self.assertEqual(404, call_wsgi(app, "POST", "/no/such/path", body=VALID_ORDER)[0])
        self.assertEqual(404, call_wsgi(app, "POST", "/zzz", query="q=1", body=VALID_ORDER)[0])
        text = _raw_get(app, "/-/metrics")[2].decode("utf-8")
        self.assertEqual(2.0, parse_prometheus_text(text)[
            _http_key("unmatched", "POST", "404")])
        self.assertNotIn("/no/such/path", text)
        self.assertNotIn("zzz", text)

    def test_error_unmatched_get_of_other_depths_collapses_to_one_label(self):
        app = make_wsgi_app(_doc(ORDER_SRC), metrics=True)
        for path in ("/nope", "/a/b/c/d/e"):
            self.assertEqual(404, call_wsgi(app, "GET", path)[0])
        text = _raw_get(app, "/-/metrics")[2].decode("utf-8")
        self.assertEqual(2.0, parse_prometheus_text(text)[
            _http_key("unmatched", "GET", "404")])
        self.assertNotIn("/nope", text)
        self.assertNotIn("/a/b/c/d/e", text)

    def test_error_unknown_method_collapses_to_other(self):
        app = make_wsgi_app(_doc(ORDER_SRC), metrics=True)
        self.assertEqual(405, call_wsgi(app, "BREW", ORDER_PATH)[0])
        text = _raw_get(app, "/-/metrics")[2].decode("utf-8")
        self.assertEqual(1.0, parse_prometheus_text(text)[
            _http_key(ORDER_PATH, "other", "405")])
        self.assertNotIn("BREW", text)

    def test_error_an_escaping_exception_is_counted_as_500(self):
        app = make_wsgi_app(_doc(ORDER_SRC), metrics=True)

        def boom(*args, **kwargs):
            raise RuntimeError("boom")
        app._dispatch = boom
        with self.assertRaises(RuntimeError):
            call_wsgi(app, "POST", ORDER_PATH, body=VALID_ORDER)
        del app._dispatch
        self.assertEqual(1.0, _scrape(app)[_http_key(ORDER_PATH, "POST", "500")])


class BoundaryTest(unittest.TestCase):

    def test_boundary_fresh_registry_renders_every_new_family_header_and_no_series(self):
        text = MetricsRegistry().render()
        for header in ("# TYPE lnpl_http_requests_total counter",
                       "# TYPE lnpl_http_request_duration_seconds histogram",
                       "# TYPE lnpl_cache_ops_total counter",
                       "# TYPE lnpl_idempotency_claims_total counter"):
            self.assertIn(header, text)
        self.assertEqual({}, parse_prometheus_text(text))
        self.assertNotIn("gauge", text)

    def test_boundary_sse_closed_before_first_chunk_is_still_counted(self):
        app = _sse_app(self)
        result = app(_wsgi_environ("GET", SSE_PATH), lambda s, h, e=None: None)
        result.close()
        self.assertEqual(1.0, _scrape(app)[("lnpl_http_request_duration_seconds_count",
                                            frozenset({("route", SSE_PATH)}))])

    def test_boundary_fifty_concurrent_requests_all_counted(self):
        class _SlowSetDict(dict):
            def __setitem__(self, key, value):
                time.sleep(0.001)
                super().__setitem__(key, value)

        app = make_wsgi_app(_doc(ORDER_SRC), metrics=True)
        app.metrics._http_requests_total = _SlowSetDict()
        threads = [threading.Thread(target=lambda: call_wsgi(app, "GET", "/no/such/path"))
                   for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(50.0, _scrape(app)[_http_key("unmatched", "GET", "404")])

    def test_boundary_grafana_example_targets_all_carry_ref_ids(self):
        for panel in _grafana()["panels"]:
            ref_ids = [t.get("refId") for t in panel["targets"]]
            self.assertTrue(all(ref_ids), panel["title"])
            self.assertEqual(len(ref_ids), len(set(ref_ids)), panel["title"])


if __name__ == "__main__":
    unittest.main()

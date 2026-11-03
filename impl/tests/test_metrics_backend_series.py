"""issue #237: `/-/metrics` backend series — cache operations,
Idempotency-Key claims, the outbox backlog gauge and the optional driver
`metrics()` hook.

Normal: a cached read counts a miss, a set, then a hit; the `cache` /
`invalidate` effects count set and invalidate; the same key sent twice
counts `started` then `done`; the outbox gauge reports undelivered rows;
a driver hook entry becomes a `lnpl_driver_<name>` gauge. Error: a cache
`get` that raises counts `error` and the request still succeeds; a driver
without idempotency support counts `unsupported` (501); an unknown claim status counts
`other`; invalid hook
entries are skipped one by one; a raising hook exports nothing and logs
once per distinct line; a raising count leaves the outbox gauge out.
Boundary: no header counts no claim; with metrics off the cache is left
unwrapped; no backend, or a driver with neither optional method, exports
no driver gauge; an empty outbox reports 0;
the sqlite driver has no `metrics()` hook.
"""

import contextlib
import io
import os
import tempfile
import unittest

from lnpl.drivers import DriverError, SqliteRepositoryDriver
from lnpl.interp import Clock, FakeCache
from lnpl.wsgi import make_wsgi_app
from tests.test_cache_read_through import BUDGET, HEAD
from tests.test_ops_metrics import (ORDER_PATH, ORDER_SRC, VALID_ORDER, _doc,
                                    _raw_get, parse_prometheus_text)
from tests.test_wsgi_contract import call_wsgi

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHED_READ_SRC = HEAD % BUDGET + "workflow G\n    find product cached\n"
CACHE_ACCESS_SRC = (HEAD % BUDGET
                    + "workflow G\n    find product\n    cache product\n    invalidate product\n")
PRODUCT_BODY = b'{"id":"p1","sku":"S1","name":"W","qty":1}'


def _scratch_dir(test):
    root = os.path.join(REPO, ".claude", "tmp")
    os.makedirs(root, exist_ok=True)
    box = tempfile.TemporaryDirectory(dir=root)
    test.addCleanup(box.cleanup)
    return box.name


def _scrape(app):
    return parse_prometheus_text(_raw_get(app, "/-/metrics")[2].decode("utf-8"))


def _cache_key(op, result):
    return ("lnpl_cache_ops_total", frozenset({("op", op), ("result", result)}))


def _claim_key(status):
    return ("lnpl_idempotency_claims_total", frozenset({("status", status)}))


class _GetDown(FakeCache):
    def get(self, key):
        raise DriverError("cache down")


class _NoIdempotency(SqliteRepositoryDriver):
    def supports_idempotency(self):
        return False


class _OddClaimDriver(SqliteRepositoryDriver):
    """Claims the key, then reports a status outside the four known words."""

    def idempotency_begin(self, workflow_id, key, now_ms, ttl_ms):
        super().idempotency_begin(workflow_id, key, now_ms, ttl_ms)
        return "bogus-claim", None


class _HookDriver(SqliteRepositoryDriver):
    def metrics(self):
        return {"pool_size": 4}


class _BadNamesDriver(SqliteRepositoryDriver):
    def metrics(self):
        return {"bad name": 1, "ok\n": 3, "ok": 2, "flag": True}


class _RaisingHookDriver(SqliteRepositoryDriver):
    message = "pool gone"

    def metrics(self):
        raise DriverError(type(self).message)


class _RaisingCountDriver(SqliteRepositoryDriver):
    def outbox_undelivered_count(self):
        raise DriverError("count down")


class _NoneCountDriver(SqliteRepositoryDriver):
    def outbox_undelivered_count(self):
        return None


class _BareDriver:
    """A repository object with neither optional method."""

    def close(self):
        pass


def _seeded_store(test, undelivered):
    db = os.path.join(_scratch_dir(test), "store.db")
    d = SqliteRepositoryDriver(db)
    for i in range(undelivered):
        d.record_emission({"emission_id": "e%d" % i, "event": "OrderPlaced",
                           "payload": {"n": i}})
    d.close()
    return db


def _driver_app(driver_cls, db):
    return make_wsgi_app(_doc(ORDER_SRC), repository_factory=lambda: driver_cls(db),
                         metrics=True)


class NormalTest(unittest.TestCase):

    def test_normal_cached_read_counts_miss_set_then_hit(self):
        app = make_wsgi_app(_doc(CACHED_READ_SRC), cache=FakeCache(Clock()), metrics=True)
        for _ in range(2):
            self.assertEqual(200, call_wsgi(app, "POST", "/catalog/g", body=PRODUCT_BODY)[0])
        series = _scrape(app)
        self.assertEqual(1.0, series[_cache_key("get", "miss")])
        self.assertEqual(1.0, series[_cache_key("get", "hit")])
        self.assertEqual(1.0, series[_cache_key("set", "ok")])

    def test_normal_cache_access_counts_set_and_invalidate(self):
        app = make_wsgi_app(_doc(CACHE_ACCESS_SRC), cache=FakeCache(Clock()), metrics=True)
        self.assertEqual(200, call_wsgi(app, "POST", "/catalog/g", body=PRODUCT_BODY)[0])
        series = _scrape(app)
        self.assertEqual(1.0, series[_cache_key("set", "ok")])
        self.assertEqual(1.0, series[_cache_key("invalidate", "ok")])

    def test_normal_same_key_twice_counts_started_then_done(self):
        db = os.path.join(_scratch_dir(self), "store.db")
        app = make_wsgi_app(_doc(ORDER_SRC),
                            repository_factory=lambda: SqliteRepositoryDriver(db),
                            metrics=True)
        for _ in range(2):
            status, _, _ = call_wsgi(app, "POST", ORDER_PATH, body=VALID_ORDER,
                                     headers={"Idempotency-Key": "k-1"})
            self.assertEqual(200, status)
        series = _scrape(app)
        self.assertEqual(1.0, series[_claim_key("started")])
        self.assertEqual(1.0, series[_claim_key("done")])

    def test_normal_outbox_gauge_reports_undelivered_rows(self):
        app = _driver_app(SqliteRepositoryDriver, _seeded_store(self, 2))
        status, _, raw = _raw_get(app, "/-/metrics")
        text = raw.decode("utf-8")
        self.assertEqual(200, status)
        self.assertEqual(2.0, parse_prometheus_text(text)[("lnpl_outbox_undelivered", frozenset())])
        self.assertIn("# TYPE lnpl_outbox_undelivered gauge", text)

    def test_normal_driver_hook_is_exported_as_prefixed_gauge(self):
        app = _driver_app(_HookDriver, _seeded_store(self, 0))
        text = _raw_get(app, "/-/metrics")[2].decode("utf-8")
        self.assertEqual(4.0, parse_prometheus_text(text)[("lnpl_driver_pool_size", frozenset())])
        self.assertIn("# TYPE lnpl_driver_pool_size gauge", text)


class ErrorTest(unittest.TestCase):

    def test_error_cache_get_failure_counts_error_and_request_still_succeeds(self):
        app = make_wsgi_app(_doc(CACHED_READ_SRC), cache=_GetDown(Clock()), metrics=True)
        self.assertEqual(200, call_wsgi(app, "POST", "/catalog/g", body=PRODUCT_BODY)[0])
        self.assertEqual(1.0, _scrape(app)[_cache_key("get", "error")])

    def test_error_refusing_driver_counts_unsupported(self):
        db = os.path.join(_scratch_dir(self), "store.db")
        app = make_wsgi_app(_doc(ORDER_SRC), repository_factory=lambda: _NoIdempotency(db),
                            metrics=True)
        status, _, _ = call_wsgi(app, "POST", ORDER_PATH, body=VALID_ORDER,
                                 headers={"Idempotency-Key": "k-2"})
        self.assertEqual(501, status)
        self.assertEqual(1.0, _scrape(app)[_claim_key("unsupported")])

    def test_error_unknown_claim_status_is_counted_as_other(self):
        db = os.path.join(_scratch_dir(self), "store.db")
        app = make_wsgi_app(_doc(ORDER_SRC), repository_factory=lambda: _OddClaimDriver(db),
                            metrics=True)
        status, _, _ = call_wsgi(app, "POST", ORDER_PATH, body=VALID_ORDER,
                                 headers={"Idempotency-Key": "k-3"})
        self.assertEqual(200, status)
        text = _raw_get(app, "/-/metrics")[2].decode("utf-8")
        self.assertEqual(1.0, parse_prometheus_text(text)[_claim_key("other")])
        self.assertNotIn("bogus-claim", text)

    def test_error_invalid_hook_entries_are_skipped_one_by_one(self):
        app = _driver_app(_BadNamesDriver, _seeded_store(self, 0))
        status, _, raw = _raw_get(app, "/-/metrics")
        self.assertEqual(200, status)
        series = parse_prometheus_text(raw.decode("utf-8"))
        driver_series = {name: value for (name, _), value in series.items()
                         if name.startswith("lnpl_driver_")}
        self.assertEqual({"lnpl_driver_ok": 2.0}, driver_series)
        self.assertNotIn(("lnpl_driver_flag", frozenset()), series)

    def test_error_raising_hook_exports_nothing_and_logs_once(self):
        app = _driver_app(_RaisingHookDriver, _seeded_store(self, 0))
        self.addCleanup(setattr, _RaisingHookDriver, "message", "pool gone")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            first = _raw_get(app, "/-/metrics")
            second = _raw_get(app, "/-/metrics")
            self.assertEqual((200, 200), (first[0], second[0]))
            self.assertEqual(1, err.getvalue().count("serve: metrics: metrics() failed"))
            self.assertNotIn("lnpl_driver_", second[2].decode("utf-8"))
            _RaisingHookDriver.message = "pool down"
            _raw_get(app, "/-/metrics")
            self.assertEqual(2, err.getvalue().count("serve: metrics: metrics() failed"))

    def test_error_raising_count_leaves_the_outbox_gauge_out(self):
        app = _driver_app(_RaisingCountDriver, _seeded_store(self, 1))
        with contextlib.redirect_stderr(io.StringIO()) as err:
            status, _, raw = _raw_get(app, "/-/metrics")
        self.assertEqual(200, status)
        self.assertNotIn("lnpl_outbox_undelivered", raw.decode("utf-8"))
        self.assertIn("serve: metrics: outbox_undelivered_count failed (DriverError): count down",
                      err.getvalue())

    def test_error_non_integer_count_leaves_the_outbox_gauge_out(self):
        app = _driver_app(_NoneCountDriver, _seeded_store(self, 1))
        with contextlib.redirect_stderr(io.StringIO()) as err:
            status, _, raw = _raw_get(app, "/-/metrics")
        self.assertEqual(200, status)
        self.assertNotIn("lnpl_outbox_undelivered", raw.decode("utf-8"))
        self.assertIn("serve: metrics: outbox_undelivered_count failed (TypeError)", err.getvalue())


class BoundaryTest(unittest.TestCase):

    def test_boundary_no_idempotency_header_counts_no_claim(self):
        db = os.path.join(_scratch_dir(self), "store.db")
        app = make_wsgi_app(_doc(ORDER_SRC),
                            repository_factory=lambda: SqliteRepositoryDriver(db),
                            metrics=True)
        self.assertEqual(200, call_wsgi(app, "POST", ORDER_PATH, body=VALID_ORDER)[0])
        names = {name for name, _ in _scrape(app)}
        self.assertNotIn("lnpl_idempotency_claims_total", names)

    def test_boundary_metrics_off_leaves_the_cache_unwrapped(self):
        cache = FakeCache(Clock())
        app = make_wsgi_app(_doc(CACHED_READ_SRC), cache=cache)
        for _ in range(2):
            self.assertEqual(200, call_wsgi(app, "POST", "/catalog/g", body=PRODUCT_BODY)[0])
        self.assertIsNone(app.metrics)
        self.assertEqual((1, 1), (cache.hits, cache.misses))

    def test_boundary_no_backend_exports_no_driver_gauges(self):
        app = make_wsgi_app(_doc(ORDER_SRC), metrics=True)
        text = _raw_get(app, "/-/metrics")[2].decode("utf-8")
        self.assertNotIn("lnpl_outbox_undelivered", text)
        self.assertNotIn("lnpl_driver_", text)

    def test_boundary_driver_without_either_method_exports_no_driver_gauges(self):
        app = make_wsgi_app(_doc(ORDER_SRC), repository_factory=_BareDriver, metrics=True)
        status, _, raw = _raw_get(app, "/-/metrics")
        text = raw.decode("utf-8")
        self.assertEqual(200, status)
        self.assertNotIn("lnpl_outbox_undelivered", text)
        self.assertNotIn("lnpl_driver_", text)

    def test_boundary_empty_outbox_reports_zero(self):
        app = _driver_app(SqliteRepositoryDriver, _seeded_store(self, 0))
        self.assertEqual(0.0, _scrape(app)[("lnpl_outbox_undelivered", frozenset())])

    def test_boundary_sqlite_has_no_metrics_hook(self):
        self.assertFalse(callable(getattr(SqliteRepositoryDriver, "metrics", None)))
        app = _driver_app(SqliteRepositoryDriver, _seeded_store(self, 2))
        self.assertNotIn("lnpl_driver_", _raw_get(app, "/-/metrics")[2].decode("utf-8"))


if __name__ == "__main__":
    unittest.main()

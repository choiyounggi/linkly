"""`--cache`'s entry-points fallback (issue #131): a scheme not built in
(`fake`) is looked up in the `lnpl.caches` entry-points group before the
selector is rejected — the same shape `test_driver_spi.py` proves for
`lnpl.drivers` (issue #75).

Discovery (`importlib.metadata.entry_points(group=...)`) is monkeypatched to
a controlled, in-process set, same reasoning as `test_driver_spi.py`:
installing a second distribution just to prove group lookup works would need
a package this repo does not ship. `EntryPoint.load()` itself is never
mocked.
"""

import contextlib
import http.client
import io
import json
import os
import tempfile
import threading
import time
import unittest
from importlib import metadata as importlib_metadata
from unittest import mock

from lnpl import cli as cli_module
from lnpl import drivers as drivers_module
from lnpl.drivers import CACHES, DriverError, open_cache
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.serve import serve
from lnpl.testing import CacheDriverTCK
from lnpl.wsgi import make_wsgi_app

from tests.cache_spi_fixture import DemoCacheDriver
from tests.fixtures import GUARDED_LNPL
from tests.test_wsgi_contract import call_wsgi

GROUP = drivers_module.CACHES_ENTRY_POINT_GROUP


def entry_point(name, value):
    return importlib_metadata.EntryPoint(name=name, value=value, group=GROUP)


def registered(*entry_points):
    """A patcher for `drivers_module._cache_entry_points`'s only external
    call — `importlib_metadata.entry_points(group=...)` — returning exactly
    `entry_points` regardless of what is actually installed."""
    return mock.patch.object(
        drivers_module.importlib_metadata, "entry_points",
        lambda **_kwargs: list(entry_points))


DEMO_ENTRY_POINT = entry_point(
    "demo", "tests.cache_spi_fixture:make_demo_cache")


class RegisteredSchemeTest(unittest.TestCase):
    """Normal: a fixture driver registered under `lnpl.caches` is caught by
    `--cache demo:<arg>` on registration alone — no change to `open_cache`
    beyond the entry-points fallback itself."""

    def test_a_registered_scheme_is_caught_and_the_arg_reaches_the_factory(self):
        with registered(DEMO_ENTRY_POINT):
            driver = open_cache("demo:hello")

        self.assertIsInstance(driver, DemoCacheDriver)
        self.assertEqual(driver.arg, "hello")

    def test_the_loaded_driver_behaves_like_a_cache_driver(self):
        with registered(DEMO_ENTRY_POINT):
            driver = open_cache("demo:unused")

        driver.set("k", "v", ttl_ms=60_000)
        self.assertEqual(driver.get("k"), "v")
        driver.close()


class UnregisteredSchemeTest(unittest.TestCase):
    """Error: a scheme neither built in nor registered is rejected, and the
    message names both closed-table halves so a typo is diagnosable."""

    def test_names_the_spec_and_the_built_in_set(self):
        with registered(DEMO_ENTRY_POINT):
            with self.assertRaises(ValueError) as caught:
                open_cache("nope:x")

        message = str(caught.exception)
        self.assertIn("nope:x", message)
        for name in CACHES:
            self.assertIn(name, message)

    def test_names_the_registered_entry_point_scheme(self):
        with registered(DEMO_ENTRY_POINT):
            with self.assertRaises(ValueError) as caught:
                open_cache("nope:x")

        self.assertIn("demo", str(caught.exception))

    def test_zero_registered_entry_points_says_none_rather_than_an_empty_list(self):
        with registered():
            with self.assertRaises(ValueError) as caught:
                open_cache("nope:x")

        self.assertIn("none", str(caught.exception))


class EntryPointLoadFailureTest(unittest.TestCase):
    """Error: a registered scheme whose entry-point fails to import is a
    driver fault (`DriverError`), not a traceback out of `open_cache` — the
    module's own "ONE ERROR TYPE OUT" rule applied to the new path."""

    def test_an_import_failure_becomes_a_driver_error(self):
        broken = entry_point(
            "broken", "tests.no_such_fixture_module_xyz:make_cache")

        with registered(broken):
            with self.assertRaises(DriverError) as caught:
                open_cache("broken:x")

        self.assertIn("broken", str(caught.exception))
        self.assertIsInstance(caught.exception.__cause__, ImportError)


class BuiltinShadowingTest(unittest.TestCase):
    """Boundary: a package registering `fake` can never shadow the built-in
    cache — the built-in check runs before entry-points are ever consulted."""

    def test_a_same_named_entry_point_never_shadows_builtin_fake(self):
        shadow = entry_point("fake", "tests.cache_spi_fixture:make_demo_cache")

        with registered(shadow):
            driver = open_cache("fake")

        self.assertIsNone(driver)


class DemoCachePassesTheTCKTest(CacheDriverTCK, unittest.TestCase):
    """The point of the SPI boundary: a cache the core module did not
    construct still has to pass the same contract the built-in one does — a
    driver that can't is proof the contract itself is unimplementable, not
    that the TCK is wrong."""

    def make_cache(self):
        return DemoCacheDriver()

    def advance(self, ms):
        self.cache.advance(ms)


def run_cli(argv):
    """-> (rc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli_module.main(argv)
    return rc, out.getvalue(), err.getvalue()


class CliCacheFlagTest(unittest.TestCase):
    """`--cache` on `run` (issue #131, D3): default is unchanged, a
    registered entry-point driver is the one the interpreter actually uses,
    and an unknown selector is an operator error naming both closed-table
    halves — the `test_cli_backend.py`/`--backend` precedent mirrored."""

    def test_the_default_run_is_unchanged_by_the_new_flag(self):
        implicit = run_cli(["run", GUARDED_LNPL, "--json"])
        explicit = run_cli(["run", GUARDED_LNPL, "--json", "--cache", "fake"])

        self.assertEqual(implicit[0], 0)
        self.assertEqual(explicit[0], 0)
        self.assertEqual(json.loads(implicit[1])["result"],
                         json.loads(explicit[1])["result"])

    def test_a_registered_cache_is_the_one_the_run_actually_uses(self):
        """`examples/guarded.lnpl`'s default seed makes `when token.cachedAt
        exists` true, so `cache token` really executes a `CacheAccess set` —
        this independently proves the entry-point-loaded driver, not the
        Interpreter's own FakeCache, is what receives it (asserting on the
        driver's own store, not merely that the run completed — a run that
        silently kept using FakeCache would still report `status: completed`
        and would pass a weaker assertion)."""
        real = cli_module.open_cache
        opened = []

        def opener(spec, clock=None):
            driver = real(spec, clock=clock)
            opened.append(driver)
            return driver

        cli_module.open_cache = opener
        self.addCleanup(setattr, cli_module, "open_cache", real)

        with registered(DEMO_ENTRY_POINT):
            rc, out, err = run_cli(["run", GUARDED_LNPL, "--json",
                                    "--cache", "demo:hello"])

        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)["result"]["status"], "completed")
        self.assertEqual(len(opened), 1)
        self.assertIsInstance(opened[0], DemoCacheDriver)
        self.assertTrue(opened[0].store, "the registered driver's store is "
                        "empty — CacheAccess never reached it")

    def test_an_unknown_cache_is_an_operator_error(self):
        rc, out, err = run_cli(["run", GUARDED_LNPL, "--cache", "redis://x"])

        self.assertEqual(rc, 2)
        self.assertEqual(out, "")            # a rejected run emits no result
        self.assertIn("redis://x", err)
        for name in CACHES:
            self.assertIn(name, err)


class CacheLifetimeTest(unittest.TestCase):
    """The driver is released whichever way the run ends — `StoreLifetimeTest`
    (`test_cli_backend.py`) mirrored for `--cache`."""

    def _recording_open(self, calls):
        real = cli_module.open_cache

        def opener(spec, clock=None):
            driver = real(spec, clock=clock)
            if driver is None:
                return None
            close = driver.close

            def closing():
                calls.append("closed")
                return close()

            driver.close = closing
            return driver

        cli_module.open_cache = opener
        self.addCleanup(setattr, cli_module, "open_cache", real)
        return calls

    def test_the_cache_is_released_after_a_completing_run(self):
        with registered(DEMO_ENTRY_POINT):
            calls = self._recording_open([])
            rc, out, err = run_cli(["run", GUARDED_LNPL, "--json",
                                    "--cache", "demo:hello"])

        self.assertEqual(rc, 0, err)
        self.assertEqual(calls, ["closed"])


SCHEDULED_SRC = """service Rollup

entity Report
    field
        id UUID

event DailyRollup on schedule daily at 00:00 UTC

workflow GetReport
    read report
"""


class CliCacheOnTriggerAndServeTest(unittest.TestCase):
    """The same flag, wired into `trigger` and `serve` too (D3: all three
    commands). `serve` validates the selector before the socket binds, the
    same "fail at the boundary" `--backend` probe already does — it never
    needs to run a workflow to prove the rejection."""

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.scheduled_source = os.path.join(box.name, "scheduled.lnpl")
        with open(self.scheduled_source, "w", encoding="utf-8") as fh:
            fh.write(SCHEDULED_SRC)

    def test_trigger_rejects_an_unknown_cache_selector(self):
        rc, out, err = run_cli(["trigger", self.scheduled_source,
                                "--schedule", "event.daily.rollup",
                                "--cache", "redis://x"])

        self.assertEqual(rc, 2)
        self.assertIn("redis://x", err)

    def test_serve_rejects_an_unknown_cache_selector_before_binding(self):
        rc, out, err = run_cli(["serve", GUARDED_LNPL, "--port", "0",
                                "--cache", "redis://x"])

        self.assertEqual(rc, 2)
        self.assertIn("redis://x", err)


class ServedRequestUsesTheRegisteredCacheTest(unittest.TestCase):
    """r1 rework: `--cache` on `serve` used to be a launch-time probe only —
    the driver it opened was discarded, and every request still went
    through the Interpreter's own FakeCache no matter what was registered.
    This proves the fix: a request actually served through
    `serve(..., cache=...)` reaches the SAME registered driver instance, the
    way `test_a_registered_cache_is_the_one_the_run_actually_uses` already
    proves for `run` — a rejection-path test alone cannot tell "wired" from
    "validated and discarded" apart."""

    def setUp(self):
        with open(GUARDED_LNPL, encoding="utf-8") as fh:
            self.doc = lower(parse(fh.read()), "guarded").to_document()

    def start(self, cache):
        server = serve(self.doc, port=0, cache=cache)
        thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def post(self, port, payload):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        self.addCleanup(conn.close)
        conn.request("POST", "/token-service/retrieve-with-cache",
                     body=json.dumps(payload).encode(),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        return resp, resp.read()

    def test_a_request_reaches_the_registered_cache_driver(self):
        """`examples/guarded.lnpl`'s `cache token` step executes when
        `token.cachedAt` is present — this payload sets it, so the request
        really performs a `CacheAccess set`."""
        with registered(DEMO_ENTRY_POINT):
            driver = open_cache("demo:hello")
        self.assertIsInstance(driver, DemoCacheDriver)
        port = self.start(driver)

        resp, raw = self.post(port, {
            "id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
            "cachedAt": "2026-07-31T09:00:00Z",
            "retryBudget": 1,
        })

        self.assertEqual(resp.status, 200, raw)
        self.assertTrue(driver.store, "the registered driver's store is "
                        "empty — the served request never reached it")

    def test_the_fake_default_still_serves_the_request(self):
        """Regression: `cache=None` (the untouched default — no `--cache`)
        still reaches a working FakeCache and the request still completes.
        This does not by itself prove the workflow caches anything — that is
        `test_a_request_reaches_the_registered_cache_driver` above, which
        asserts on the registered driver's own store; this only guards
        against the wiring change breaking the pre-existing default path."""
        port = self.start(None)

        resp, raw = self.post(port, {
            "id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
            "cachedAt": "2026-07-31T09:00:00Z",
            "retryBudget": 1,
        })

        self.assertEqual(resp.status, 200, raw)


EVENT_CACHE_SRC = """
capability postgres
capability redis

entity Order
    field
        id UUID
        amount Integer

service OrderService
    performance
        cache 5m

event OrderCached
    consume by CacheOrder

workflow CacheOrder
    find order
    cache order
"""


class EventConsumeRequestUsesTheRegisteredCacheTest(unittest.TestCase):
    """r1 audit follow-up: `LnplWsgiApp` has TWO `Interpreter(...)`
    construction sites — `_respond` (the OpenAPI POST route, proven by
    `ServedRequestUsesTheRegisteredCacheTest` above) and
    `_respond_event_consume` (`POST /-/events/<slug>`, issue #118). Both
    pass `cache=self.cache` identically, but nothing proved the SECOND site
    actually wires it — a test only exercising the first site could not
    catch a regression specific to the event-consume path."""

    def test_a_consumed_event_reaches_the_registered_cache_driver(self):
        doc = lower(parse(EVENT_CACHE_SRC), "t").to_document()
        with registered(DEMO_ENTRY_POINT):
            driver = open_cache("demo:hello")
        app = make_wsgi_app(doc, cache=driver)

        status, _headers, body = call_wsgi(
            app, "POST", "/-/events/order-cached",
            body=json.dumps({
                "specversion": "1.0", "id": "evt-1", "source": "test",
                "type": "OrderCached",
                "data": {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c330b",
                        "amount": 1},
            }).encode("utf-8"))

        self.assertEqual(status, 200, body)
        self.assertTrue(driver.store, "the registered driver's store is "
                        "empty — the event-consume path never reached it")


if __name__ == "__main__":
    unittest.main()

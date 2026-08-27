"""Issue #109 — retry/backoff/jitter/Retry-After + circuit breaker, the
runtime half of `capability http`'s resilience layer. `FakeNetworkDriver`
and `HttpNetworkDriver` share one resilience core (`drivers._call_with_resilience`)
so the two can never grade the same declaration two different ways — that
sharing is exactly what `NetworkDriverTCK` (a separate file) then exercises
against both. This file drives the core directly, through whichever driver
makes each scenario clearest and fastest.
"""

import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lnpl.drivers import DriverError, FakeNetworkDriver, HttpNetworkDriver

from tests.test_network_driver import _ServerTestCase, _make_handler


class _FailNTimesHandler(BaseHTTPRequestHandler):
    """Fails with `fail_status` `fail_count` times, then serves `ok_body`.
    Records timestamps (`time.monotonic()`) of every request so a test can
    assert the backoff between them without depending on wall-clock sleep
    inside the *test* itself."""

    fail_count = 0
    fail_status = 500
    ok_body = b"{}"
    retry_after = None
    calls = []

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        import time
        type(self).calls.append(time.monotonic())
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.rfile.read(length)
        if len(type(self).calls) <= type(self).fail_count:
            self.send_response(type(self).fail_status)
            if type(self).retry_after is not None:
                self.send_header("Retry-After", str(type(self).retry_after))
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(type(self).ok_body)))
        self.end_headers()
        self.wfile.write(type(self).ok_body)

    do_GET = do_POST


def _make_fail_n_handler(fail_count, fail_status=500, retry_after=None):
    return type("_FailHandler", (_FailNTimesHandler,), {
        "fail_count": fail_count, "fail_status": fail_status,
        "retry_after": retry_after, "calls": [],
    })


class _NoSleep:
    """Records requested delays (seconds) instead of blocking — keeps retry
    tests fast while still letting them assert the exact backoff schedule."""

    def __init__(self):
        self.delays = []

    def __call__(self, seconds):
        self.delays.append(seconds)


class _FixedClock:
    """Deterministic ms clock a test advances by hand — the same injection
    point (`.now`) `interp.Clock`/`interp.RealClock` expose (RFC-0029)."""

    def __init__(self, start=0):
        self.now = start

    def advance(self, ms):
        self.now += ms


class RetryTest(_ServerTestCase):

    def test_no_retry_declaration_means_zero_retries(self):
        """Regression (DoD): a capability with no `retry` clause makes
        exactly one attempt, even against a 5xx — the pre-#109 behaviour."""
        handler = _make_fail_n_handler(fail_count=5, fail_status=500)
        url = self.start(handler)
        driver = HttpNetworkDriver(endpoints={"Orders": url},
                                   capabilities={"Orders": {"method": "POST", "headers": {}}})
        self.addCleanup(driver.close)

        status, body, _headers = driver.call("Orders", {}, 2000)

        self.assertEqual(status, 500)
        self.assertEqual(len(handler.calls), 1)

    def test_a_5xx_is_retried_until_it_recovers(self):
        handler = _make_fail_n_handler(fail_count=2, fail_status=500)
        url = self.start(handler)
        sleep = _NoSleep()
        driver = HttpNetworkDriver(
            endpoints={"Orders": url},
            capabilities={"Orders": {"method": "POST", "headers": {},
                                     "retry": {"count": 3, "backoff_ms": 100,
                                               "jitter": False}}},
            sleep=sleep)
        self.addCleanup(driver.close)

        status, body, _headers = driver.call("Orders", {}, 2000)

        self.assertEqual(status, 200)
        self.assertEqual(len(handler.calls), 3)

    def test_backoff_is_exponential_base_times_two_pow_attempt_minus_one(self):
        handler = _make_fail_n_handler(fail_count=3, fail_status=500)
        url = self.start(handler)
        sleep = _NoSleep()
        driver = HttpNetworkDriver(
            endpoints={"Orders": url},
            capabilities={"Orders": {"method": "POST", "headers": {},
                                     "retry": {"count": 3, "backoff_ms": 100,
                                               "jitter": False}}},
            sleep=sleep)
        self.addCleanup(driver.close)

        driver.call("Orders", {}, 2000)

        # base=100ms: 100ms, 200ms, 400ms before attempts 2, 3, 4.
        self.assertEqual(sleep.delays, [0.1, 0.2, 0.4])

    def test_a_408_is_retried(self):
        handler = _make_fail_n_handler(fail_count=1, fail_status=408)
        url = self.start(handler)
        driver = HttpNetworkDriver(
            endpoints={"Orders": url},
            capabilities={"Orders": {"method": "POST", "headers": {},
                                     "retry": {"count": 1, "backoff_ms": 10,
                                               "jitter": False}}},
            sleep=_NoSleep())
        self.addCleanup(driver.close)

        status, _body, _headers = driver.call("Orders", {}, 2000)

        self.assertEqual(status, 200)
        self.assertEqual(len(handler.calls), 2)

    def test_a_429_is_retried(self):
        handler = _make_fail_n_handler(fail_count=1, fail_status=429)
        url = self.start(handler)
        driver = HttpNetworkDriver(
            endpoints={"Orders": url},
            capabilities={"Orders": {"method": "POST", "headers": {},
                                     "retry": {"count": 1, "backoff_ms": 10,
                                               "jitter": False}}},
            sleep=_NoSleep())
        self.addCleanup(driver.close)

        status, _body, _headers = driver.call("Orders", {}, 2000)

        self.assertEqual(status, 200)
        self.assertEqual(len(handler.calls), 2)

    def test_a_501_is_not_retried(self):
        """Boundary (D2): 501 is excluded from the retryable 5xx range —
        Not Implemented will never succeed on a retry."""
        handler = _make_fail_n_handler(fail_count=5, fail_status=501)
        url = self.start(handler)
        driver = HttpNetworkDriver(
            endpoints={"Orders": url},
            capabilities={"Orders": {"method": "POST", "headers": {},
                                     "retry": {"count": 3, "backoff_ms": 10,
                                               "jitter": False}}},
            sleep=_NoSleep())
        self.addCleanup(driver.close)

        status, _body, _headers = driver.call("Orders", {}, 2000)

        self.assertEqual(status, 501)
        self.assertEqual(len(handler.calls), 1)

    def test_a_plain_4xx_is_not_retried(self):
        handler = _make_fail_n_handler(fail_count=5, fail_status=404)
        url = self.start(handler)
        driver = HttpNetworkDriver(
            endpoints={"Orders": url},
            capabilities={"Orders": {"method": "POST", "headers": {},
                                     "retry": {"count": 3, "backoff_ms": 10,
                                               "jitter": False}}},
            sleep=_NoSleep())
        self.addCleanup(driver.close)

        status, _body, _headers = driver.call("Orders", {}, 2000)

        self.assertEqual(status, 404)
        self.assertEqual(len(handler.calls), 1)

    def test_a_connection_failure_is_retried_then_raises_if_exhausted(self):
        """Error case: nothing is listening — every attempt is a transport
        failure, and the final one still raises `DriverError` (RFC-0027 §3:
        no response ever arrived)."""
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        _host, port = sock.getsockname()
        sock.close()
        driver = HttpNetworkDriver(
            capabilities={"http://127.0.0.1:%d/" % port: {
                "method": "POST", "headers": {},
                "retry": {"count": 2, "backoff_ms": 1, "jitter": False}}},
            sleep=_NoSleep())
        self.addCleanup(driver.close)

        with self.assertRaises(DriverError):
            driver.call("http://127.0.0.1:%d/" % port, {}, 500)

    def test_retry_after_header_extends_the_computed_delay(self):
        handler = _make_fail_n_handler(fail_count=1, fail_status=429, retry_after=5)
        url = self.start(handler)
        sleep = _NoSleep()
        driver = HttpNetworkDriver(
            endpoints={"Orders": url},
            capabilities={"Orders": {"method": "POST", "headers": {},
                                     "retry": {"count": 1, "backoff_ms": 10,
                                               "jitter": False}}},
            sleep=sleep)
        self.addCleanup(driver.close)

        driver.call("Orders", {}, 2000)

        # computed backoff is 10ms, but Retry-After: 5 (seconds) wins.
        self.assertEqual(sleep.delays, [5.0])

    def test_jitter_stays_within_the_full_jitter_range_with_a_seeded_rng(self):
        """Deterministic seed (D2): full jitter is uniform[0, computed_delay) —
        seeding `random.Random` makes the exact draw reproducible."""
        import random
        handler = _make_fail_n_handler(fail_count=1, fail_status=500)
        url = self.start(handler)
        sleep = _NoSleep()
        seeded_rand = random.Random(12345)
        expected = random.Random(12345).uniform(0, 0.1)
        driver = HttpNetworkDriver(
            endpoints={"Orders": url},
            capabilities={"Orders": {"method": "POST", "headers": {},
                                     "retry": {"count": 1, "backoff_ms": 100,
                                               "jitter": True}}},
            sleep=sleep, rand=seeded_rand)
        self.addCleanup(driver.close)

        driver.call("Orders", {}, 2000)

        self.assertEqual(len(sleep.delays), 1)
        self.assertAlmostEqual(sleep.delays[0], expected)
        self.assertGreaterEqual(sleep.delays[0], 0)
        self.assertLess(sleep.delays[0], 0.1)

    def test_fake_driver_honours_a_scripted_failure_then_recovery_sequence(self):
        """`FakeNetworkDriver` shares the same resilience core — a list stub
        scripts one failure then a recovery, mirroring the real transport."""
        driver = FakeNetworkDriver(
            stubs={"Orders": [(500, {}), (200, {"ok": True})]},
            capabilities={"Orders": {"method": "POST",
                                     "retry": {"count": 2, "backoff_ms": 1,
                                               "jitter": False}}},
            sleep=_NoSleep())

        status, body, _headers = driver.call("Orders", {}, 1000)

        self.assertEqual((status, body), (200, {"ok": True}))
        self.assertEqual(len(driver.received), 2)


class BreakerTest(_ServerTestCase):

    def test_breaker_opens_after_the_threshold_and_rejects_without_attempting(self):
        handler = _make_fail_n_handler(fail_count=99, fail_status=500)
        url = self.start(handler)
        clock = _FixedClock(0)
        driver = HttpNetworkDriver(
            endpoints={"Orders": url},
            capabilities={"Orders": {"method": "POST", "headers": {},
                                     "breaker": {"threshold": 2, "window_ms": 60000}}},
            clock=clock)
        self.addCleanup(driver.close)

        driver.call("Orders", {}, 2000)   # failure 1
        driver.call("Orders", {}, 2000)   # failure 2 -> breaker opens
        calls_before = len(handler.calls)

        with self.assertRaises(DriverError) as caught:
            driver.call("Orders", {}, 2000)

        self.assertEqual(len(handler.calls), calls_before,
                         "the open breaker must reject without attempting a call")
        self.assertIn("breaker-open", str(caught.exception))

    def test_breaker_half_opens_after_the_window_and_a_success_closes_it(self):
        handler = _make_fail_n_handler(fail_count=2, fail_status=500)
        url = self.start(handler)
        clock = _FixedClock(0)
        driver = HttpNetworkDriver(
            endpoints={"Orders": url},
            capabilities={"Orders": {"method": "POST", "headers": {},
                                     "breaker": {"threshold": 2, "window_ms": 1000}}},
            clock=clock)
        self.addCleanup(driver.close)

        driver.call("Orders", {}, 2000)   # failure 1 (handler fails twice total)
        driver.call("Orders", {}, 2000)   # failure 2 -> breaker opens
        with self.assertRaises(DriverError):
            driver.call("Orders", {}, 2000)  # rejected, still within window

        clock.advance(1000)              # window elapsed -> half-open probe allowed
        status, _body, _headers = driver.call("Orders", {}, 2000)  # 3rd real attempt succeeds

        self.assertEqual(status, 200)

        # Breaker closed by the successful probe: re-tripping it needs the
        # full threshold again, not just one more failure.
        handler2 = _make_fail_n_handler(fail_count=99, fail_status=500)
        driver._endpoints["Orders"] = self.start(handler2)
        status1, _body, _headers = driver.call("Orders", {}, 2000)  # failure 1 post-reset
        self.assertEqual(status1, 500, "still closed: this call must reach the handler")
        status2, _body, _headers = driver.call("Orders", {}, 2000)  # failure 2 -> opens
        self.assertEqual(status2, 500, "the tripping call itself still attempts")
        with self.assertRaises(DriverError):
            driver.call("Orders", {}, 2000)  # NOW rejected without attempting

    def test_breaker_reopens_immediately_if_the_half_open_probe_fails(self):
        handler = _make_fail_n_handler(fail_count=99, fail_status=500)
        url = self.start(handler)
        clock = _FixedClock(0)
        driver = HttpNetworkDriver(
            endpoints={"Orders": url},
            capabilities={"Orders": {"method": "POST", "headers": {},
                                     "breaker": {"threshold": 1, "window_ms": 500}}},
            clock=clock)
        self.addCleanup(driver.close)

        status1, _body, _headers = driver.call("Orders", {}, 2000)  # fails -> opens
        self.assertEqual(status1, 500)
        clock.advance(500)
        status2, _body, _headers = driver.call("Orders", {}, 2000)  # half-open probe, fails -> re-opens
        self.assertEqual(status2, 500)

        calls_before = len(handler.calls)
        with self.assertRaises(DriverError) as caught:
            driver.call("Orders", {}, 2000)   # immediately rejected, no window elapsed
        self.assertIn("breaker-open", str(caught.exception))
        self.assertEqual(len(handler.calls), calls_before,
                         "the re-opened breaker must reject without attempting")

    def test_no_breaker_declared_never_rejects_without_attempting(self):
        handler = _make_fail_n_handler(fail_count=99, fail_status=500)
        url = self.start(handler)
        driver = HttpNetworkDriver(endpoints={"Orders": url},
                                   capabilities={"Orders": {"method": "POST", "headers": {}}})
        self.addCleanup(driver.close)

        for _ in range(5):
            status, _body, _headers = driver.call("Orders", {}, 2000)
            self.assertEqual(status, 500)

        self.assertEqual(len(handler.calls), 5)


if __name__ == "__main__":
    unittest.main()

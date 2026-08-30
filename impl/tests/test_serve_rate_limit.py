"""issue #148, D1: `--rate-limit N` — a single process-wide token bucket
(rate == burst capacity == N), exempting every `/-/` ops path (a k8s probe
must never see 429). Exceeding it returns `429` + `Retry-After:
ceil(deficit/rate)` seconds, problem+json with code `rate-limited`.

`TokenBucketTest` pins the bucket's own math in isolation (with an injected
clock, so refill is deterministic and needs no real sleeping). The WSGI-level
tests drive `make_wsgi_app(doc, rate_limit=N)` directly via `call_wsgi` (no
socket) — normal (unlimited, the default), exceeded (429+Retry-After),
burst boundary (exactly N admitted, N+1th rejected), and ops exemption.
"""

import contextlib
import io
import os
import unittest
from unittest import mock

from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.wsgi import TokenBucket, make_wsgi_app

from tests.test_wsgi_contract import call_wsgi

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OPEN_SRC = """entity Report
    field
        id UUID

service Rollup

workflow GetReport
    read report
"""


def _doc(src, module="m148rate"):
    return lower(parse(src), module).to_document()


class _FakeClock:
    def __init__(self, start=0.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class TokenBucketTest(unittest.TestCase):

    def test_normal_acquire_under_capacity_succeeds(self):
        clock = _FakeClock()
        bucket = TokenBucket(rate=5, capacity=5, clock=clock)

        self.assertIsNone(bucket.acquire())
        self.assertIsNone(bucket.acquire())

    def test_error_acquire_past_capacity_returns_ceil_retry_after(self):
        clock = _FakeClock()
        bucket = TokenBucket(rate=2, capacity=2, clock=clock)
        bucket.acquire()
        bucket.acquire()

        retry_after = bucket.acquire()

        # deficit=1 token, rate=2/s -> 0.5s -> ceil -> 1
        self.assertEqual(1, retry_after)

    def test_boundary_exactly_capacity_admitted_next_rejected(self):
        clock = _FakeClock()
        bucket = TokenBucket(rate=3, capacity=3, clock=clock)

        for _ in range(3):
            self.assertIsNone(bucket.acquire())
        self.assertIsNotNone(bucket.acquire())

    def test_boundary_refill_over_time_restores_tokens(self):
        clock = _FakeClock()
        bucket = TokenBucket(rate=1, capacity=1, clock=clock)
        bucket.acquire()
        self.assertIsNotNone(bucket.acquire())  # empty, rejected

        clock.advance(1.0)                       # exactly one token's worth

        self.assertIsNone(bucket.acquire())      # refilled, admitted

    def test_boundary_refill_never_exceeds_capacity(self):
        clock = _FakeClock()
        bucket = TokenBucket(rate=1, capacity=2, clock=clock)
        clock.advance(100.0)                     # would overfill without a cap

        self.assertIsNone(bucket.acquire())
        self.assertIsNone(bucket.acquire())
        self.assertIsNotNone(bucket.acquire())   # still only 2 capacity


class RateLimitWsgiTest(unittest.TestCase):

    def test_normal_unlimited_by_default(self):
        app = make_wsgi_app(_doc(OPEN_SRC))

        for _ in range(10):
            status, _headers, _body = call_wsgi(app, "POST", "/rollup/get-report", body=b"{}")
            self.assertNotEqual(429, status)

    def test_error_exceeding_rate_limit_is_429_with_retry_after(self):
        app = make_wsgi_app(_doc(OPEN_SRC), rate_limit=1)

        first_status, _h, _b = call_wsgi(app, "POST", "/rollup/get-report", body=b"{}")
        second_status, second_headers, second_body = call_wsgi(
            app, "POST", "/rollup/get-report", body=b"{}")

        self.assertNotEqual(429, first_status)
        self.assertEqual(429, second_status)
        self.assertEqual("rate-limited", second_body["code"])
        self.assertIn("Retry-After", second_headers)

    def test_boundary_burst_capacity_admits_exactly_n(self):
        app = make_wsgi_app(_doc(OPEN_SRC), rate_limit=3)

        statuses = [call_wsgi(app, "POST", "/rollup/get-report", body=b"{}")[0]
                   for _ in range(4)]

        self.assertNotIn(429, statuses[:3])
        self.assertEqual(429, statuses[3])

    def test_boundary_ops_paths_are_exempt_from_rate_limit(self):
        app = make_wsgi_app(_doc(OPEN_SRC), rate_limit=1)
        call_wsgi(app, "POST", "/rollup/get-report", body=b"{}")  # spend the 1 token

        for _ in range(5):
            status, _headers, _body = call_wsgi(app, "GET", "/-/healthz")
            self.assertEqual(200, status)


class CliRateLimitFlagTest(unittest.TestCase):
    """`--rate-limit` reaches `serve()` unmolested, and a non-positive value
    is a startup rejection (rc 2) rather than a `TokenBucket` that could
    never admit anything (rate<=0 makes `deficit/rate` nonsensical)."""

    def setUp(self):
        self.workdir = os.path.join(REPO, ".claude", "tmp", "cli-rate-limit")
        os.makedirs(self.workdir, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _write(self, name, text):
        path = os.path.join(self.workdir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def _main(self, argv):
        from lnpl import cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_normal_rate_limit_flag_reaches_serve(self):
        src = self._write("ok.lnpl", OPEN_SRC)
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 8080)
        server.serve_forever.side_effect = KeyboardInterrupt
        with mock.patch("lnpl.cli.serve", return_value=server) as factory:
            rc, _out, _err = self._main(["serve", src, "--rate-limit", "5"])
        self.assertEqual(0, rc)
        self.assertEqual(5.0, factory.call_args.kwargs["rate_limit"])

    def test_error_non_positive_rate_limit_is_rc_2(self):
        src = self._write("ok.lnpl", OPEN_SRC)
        with mock.patch("lnpl.cli.serve") as factory:
            rc, _out, err = self._main(["serve", src, "--rate-limit", "0"])
        self.assertEqual(2, rc)
        self.assertIn("--rate-limit", err)
        factory.assert_not_called()

    def test_boundary_rate_limit_omitted_defaults_to_none(self):
        src = self._write("ok.lnpl", OPEN_SRC)
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 8080)
        server.serve_forever.side_effect = KeyboardInterrupt
        with mock.patch("lnpl.cli.serve", return_value=server) as factory:
            self._main(["serve", src])
        self.assertIsNone(factory.call_args.kwargs["rate_limit"])


if __name__ == "__main__":
    unittest.main()

"""issue #148, D2: SIGTERM graceful drain (k8s apiserver
`shutdown-send-retry-after` pattern). `/-/readyz` flipping to 503 on SIGTERM
is unchanged (issue #110, D11 -- see `test_ops_surface.ShutdownTest`); this
adds three NEW behaviors on top of that flag:

  (a) a new non-ops request made after SIGTERM is rejected `503` +
      `Retry-After`, never dispatched to the workflow/route it named.
  (b) an in-flight-request counter (WSGI entry/exit, `threading.Condition`)
      the server waits on before it actually stops accepting connections --
      draining to zero shuts down promptly, not after the full grace period.
  (c) a `--grace-period` ceiling (default 30s) -- in-flight requests that
      never drain do not block shutdown forever.

`InflightCounterTest`/`DrainRejectionTest` pin (a)/(b)'s mechanics directly
against the WSGI app (no socket, deterministic, sub-millisecond). The
`Sigterm...Test` classes drive the real `serve()`/`signal` wiring end to end
(short grace periods, bounded joins -- no test waits the real default 30s).
"""

import contextlib
import http.client
import io
import json
import os
import signal
import threading
import time
import unittest
from unittest import mock

from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.serve import serve
from lnpl.wsgi import make_wsgi_app

from tests.test_wsgi_contract import call_wsgi

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OPEN_SRC = """entity Report
    field
        id UUID

service Rollup

workflow GetReport
    read report
"""


def _doc(src, module="m148drain"):
    return lower(parse(src), module).to_document()


class InflightCounterTest(unittest.TestCase):
    """`wait_for_drain` in isolation -- no socket, no signal."""

    def test_normal_drain_returns_true_promptly_once_inflight_hits_zero(self):
        app = make_wsgi_app(_doc(OPEN_SRC))
        app._inflight_incr()

        def release():
            time.sleep(0.05)
            app._inflight_decr()
        threading.Thread(target=release).start()

        start = time.monotonic()
        drained = app.wait_for_drain(5.0)
        elapsed = time.monotonic() - start

        self.assertTrue(drained)
        self.assertLess(elapsed, 1.0)   # woke on the decrement, not the 5s timeout

    def test_error_drain_returns_false_after_timeout_when_never_drains(self):
        app = make_wsgi_app(_doc(OPEN_SRC))
        app._inflight_incr()

        start = time.monotonic()
        drained = app.wait_for_drain(0.1)
        elapsed = time.monotonic() - start

        self.assertFalse(drained)
        self.assertGreaterEqual(elapsed, 0.1)

    def test_boundary_zero_inflight_drains_immediately(self):
        app = make_wsgi_app(_doc(OPEN_SRC))

        start = time.monotonic()
        drained = app.wait_for_drain(5.0)
        elapsed = time.monotonic() - start

        self.assertTrue(drained)
        self.assertLess(elapsed, 0.5)

    def test_normal_a_completed_request_decrements_inflight(self):
        app = make_wsgi_app(_doc(OPEN_SRC))

        call_wsgi(app, "GET", "/-/healthz")

        self.assertTrue(app.wait_for_drain(0.0))


class DrainRejectionTest(unittest.TestCase):
    """`shutting_down=True` -> new non-ops requests 503, ops paths
    untouched. Direct WSGI-level check (no socket, no real SIGTERM) --
    `SigtermIntegrationTest` below covers the real signal wiring."""

    def test_error_non_ops_request_is_503_with_retry_after_while_shutting_down(self):
        app = make_wsgi_app(_doc(OPEN_SRC))
        app.shutting_down = True

        status, headers, body = call_wsgi(app, "POST", "/rollup/get-report", body=b"{}")

        self.assertEqual(503, status)
        self.assertEqual("shutting-down", body["code"])
        self.assertIn("Retry-After", headers)

    def test_boundary_healthz_is_unaffected_by_shutting_down(self):
        app = make_wsgi_app(_doc(OPEN_SRC))
        app.shutting_down = True

        status, _headers, body = call_wsgi(app, "GET", "/-/healthz")

        self.assertEqual(200, status)
        self.assertEqual({"status": "ok"}, body)

    def test_normal_non_ops_request_is_unaffected_before_shutdown(self):
        app = make_wsgi_app(_doc(OPEN_SRC))

        status, _headers, _body = call_wsgi(app, "POST", "/rollup/get-report", body=b"{}")

        self.assertNotEqual(503, status)


class SigtermIntegrationTest(unittest.TestCase):
    """Real `serve()` + real `signal.signal(SIGTERM, ...)` wiring -- confirms
    the drain thread actually calls `server.shutdown()` (stopping
    `serve_forever()`), not just that the in-memory flag/counter move."""

    def setUp(self):
        self._old_handler = signal.getsignal(signal.SIGTERM)
        self.addCleanup(signal.signal, signal.SIGTERM, self._old_handler)

    def _start(self, **kwargs):
        server = serve(_doc(OPEN_SRC), port=0, **kwargs)
        thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.02), daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        return server, thread

    def test_normal_sigterm_with_no_inflight_shuts_down_promptly(self):
        server, thread = self._start(grace_period_s=5.0)

        os.kill(os.getpid(), signal.SIGTERM)
        thread.join(timeout=3.0)

        self.assertFalse(thread.is_alive())

    def test_normal_sigterm_shuts_down_promptly_once_inflight_drains(self):
        server, thread = self._start(grace_period_s=5.0)
        app = server.get_app()
        app._inflight_incr()

        def release():
            time.sleep(0.1)
            app._inflight_decr()
        threading.Thread(target=release).start()

        start = time.monotonic()
        os.kill(os.getpid(), signal.SIGTERM)
        thread.join(timeout=3.0)
        elapsed = time.monotonic() - start

        self.assertFalse(thread.is_alive())
        self.assertLess(elapsed, 2.0)   # well under the 5s grace period

    def test_error_sigterm_shuts_down_after_grace_period_when_never_drains(self):
        server, thread = self._start(grace_period_s=0.2)
        app = server.get_app()
        app._inflight_incr()            # simulates a request that never finishes

        start = time.monotonic()
        os.kill(os.getpid(), signal.SIGTERM)
        thread.join(timeout=3.0)
        elapsed = time.monotonic() - start

        self.assertFalse(thread.is_alive())
        self.assertGreaterEqual(elapsed, 0.2)

    def test_error_new_request_over_the_real_socket_is_503_after_sigterm(self):
        server, thread = self._start(grace_period_s=5.0)
        app = server.get_app()
        # Holds the server past SIGTERM (0 in-flight would shut down almost
        # instantly, closing the window this test needs to hit).
        app._inflight_incr()
        port = server.server_address[1]

        os.kill(os.getpid(), signal.SIGTERM)

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        self.addCleanup(conn.close)
        conn.request("POST", "/rollup/get-report", body=b"{}",
                    headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        body = json.loads(resp.read())

        self.assertEqual(503, resp.status)
        self.assertEqual("shutting-down", body["code"])
        self.assertIsNotNone(resp.getheader("Retry-After"))

        app._inflight_decr()
        thread.join(timeout=3.0)


class CliGracePeriodFlagTest(unittest.TestCase):
    """`--grace-period` reaches `serve()` unmolested; the default (30, matching
    gunicorn's own `graceful_timeout`) applies when omitted; a negative value
    is a startup rejection (rc 2)."""

    def setUp(self):
        self.workdir = os.path.join(REPO, ".claude", "tmp", "cli-grace-period")
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

    def test_normal_grace_period_flag_reaches_serve(self):
        src = self._write("ok.lnpl", OPEN_SRC)
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 8080)
        server.serve_forever.side_effect = KeyboardInterrupt
        with mock.patch("lnpl.cli.serve", return_value=server) as factory:
            rc, _out, _err = self._main(["serve", src, "--grace-period", "5"])
        self.assertEqual(0, rc)
        self.assertEqual(5.0, factory.call_args.kwargs["grace_period_s"])

    def test_boundary_grace_period_omitted_defaults_to_30(self):
        src = self._write("ok.lnpl", OPEN_SRC)
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 8080)
        server.serve_forever.side_effect = KeyboardInterrupt
        with mock.patch("lnpl.cli.serve", return_value=server) as factory:
            self._main(["serve", src])
        self.assertEqual(30.0, factory.call_args.kwargs["grace_period_s"])

    def test_error_negative_grace_period_is_rc_2(self):
        src = self._write("ok.lnpl", OPEN_SRC)
        with mock.patch("lnpl.cli.serve") as factory:
            rc, _out, err = self._main(["serve", src, "--grace-period", "-1"])
        self.assertEqual(2, rc)
        self.assertIn("--grace-period", err)
        factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""`NetworkDriver` — the capability adapter contract for `NetworkCall` (#64).

Written against the *contract*, not against either implementation: every
assertion but the http-specific ones (real socket I/O, JSON-over-the-wire) is
one a third `NetworkDriver` would have to satisfy too. `FakeNetworkDriver` is
the reference implementation `Interpreter` builds by default; `HttpNetworkDriver`
is exercised here against a local `ThreadingHTTPServer` fixture on an ephemeral
port — no external network is contacted (RFC-0027 §Reference-level
Specification/1, D8).
"""

import json
import socket
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lnpl.drivers import (DriverError, FakeNetworkDriver, HttpNetworkDriver,
                          NETWORKS, open_network)


class _StubHandler(BaseHTTPRequestHandler):
    """Replies with the class's configured status/body/delay to every request,
    and records the request body it received for the test to inspect."""

    status = 200
    body = {}
    delay_s = 0
    raw_body = None  # not JSON-encoded when set, to exercise the malformed-body path
    received = []

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        type(self).received.append(json.loads(raw) if raw else None)
        if self.delay_s:
            time.sleep(self.delay_s)
        payload = (self.raw_body if self.raw_body is not None
                   else json.dumps(self.body).encode("utf-8"))
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _make_handler(status=200, body=None, delay_s=0, raw_body=None):
    return type("_Handler", (_StubHandler,), {
        "status": status, "body": body if body is not None else {},
        "delay_s": delay_s, "raw_body": raw_body, "received": [],
    })


class _ServerTestCase(unittest.TestCase):
    """Starts one `ThreadingHTTPServer` on an ephemeral loopback port per test,
    torn down in `addCleanup` — a fresh port avoids state leaking between
    tests (testing/data/test-data-and-isolation)."""

    def start(self, handler_cls):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        server.daemon_threads = True
        import threading
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop():
            # Order matters: `shutdown()` must run before `join()` or the
            # thread blocks in `serve_forever()` forever — `addCleanup` runs
            # LIFO, so registering them separately would join before asking
            # the loop to stop. One callback fixes the order explicitly.
            server.shutdown()
            thread.join()
            server.server_close()

        self.addCleanup(stop)
        host, port = server.server_address
        return "http://%s:%d/" % (host, port)


class FakeNetworkDriverTest(unittest.TestCase):

    def test_an_unstubbed_target_returns_the_deterministic_default(self):
        """No stub means 200/empty body, every time — the default has to be
        deterministic or spec cases relying on it (RFC-0027 §7, D4) would be
        flaky."""
        driver = FakeNetworkDriver({})

        first = driver.call("PaymentGateway", {}, 1000)
        second = driver.call("PaymentGateway", {}, 1000)

        self.assertEqual(first, (200, {}))
        self.assertEqual(second, (200, {}))

    def test_a_stubbed_target_returns_the_stubbed_response(self):
        driver = FakeNetworkDriver({"PaymentGateway": (500, {"message": "card declined"})})

        status, body = driver.call("PaymentGateway", {}, 1000)

        self.assertEqual(status, 500)
        self.assertEqual(body, {"message": "card declined"})

    def test_a_different_targets_stub_does_not_leak_onto_an_unstubbed_one(self):
        driver = FakeNetworkDriver({"PaymentGateway": (500, {})})

        status, body = driver.call("ShippingApi", {}, 1000)

        self.assertEqual((status, body), (200, {}))

    def test_close_does_not_raise(self):
        FakeNetworkDriver({}).close()


class HttpNetworkDriverTest(_ServerTestCase):

    def test_a_successful_call_returns_the_parsed_status_and_body(self):
        url = self.start(_make_handler(status=200, body={"ok": True}))
        driver = HttpNetworkDriver()
        self.addCleanup(driver.close)

        status, body = driver.call(url, {"amount": 42}, 2000)

        self.assertEqual(status, 200)
        self.assertEqual(body, {"ok": True})

    def test_the_payload_is_sent_as_the_json_request_body(self):
        handler = _make_handler(status=200, body={})
        url = self.start(handler)
        driver = HttpNetworkDriver()
        self.addCleanup(driver.close)

        driver.call(url, {"amount": 42, "currency": "USD"}, 2000)

        self.assertEqual(handler.received, [{"amount": 42, "currency": "USD"}])

    def test_a_5xx_response_is_a_value_not_an_exception(self):
        """RFC-0027 §3, D3: an HTTP failure status is a normal return — the
        connection succeeded, so this is not a DriverError."""
        url = self.start(_make_handler(status=500, body={"message": "boom"}))
        driver = HttpNetworkDriver()
        self.addCleanup(driver.close)

        status, body = driver.call(url, {}, 2000)

        self.assertEqual(status, 500)
        self.assertEqual(body, {"message": "boom"})

    def test_a_non_json_body_becomes_an_empty_dict(self):
        """Boundary: the value shape (dict) stays stable even when the peer
        does not speak JSON."""
        url = self.start(_make_handler(status=200, raw_body=b"not json"))
        driver = HttpNetworkDriver()
        self.addCleanup(driver.close)

        status, body = driver.call(url, {}, 2000)

        self.assertEqual(status, 200)
        self.assertEqual(body, {})

    def test_connection_refused_raises_driver_error(self):
        """Error case: nothing is listening on this loopback port."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        _host, port = sock.getsockname()
        sock.close()  # closed immediately: the port is free, nothing answers it
        driver = HttpNetworkDriver()
        self.addCleanup(driver.close)

        with self.assertRaises(DriverError):
            driver.call("http://127.0.0.1:%d/" % port, {}, 500)

    def test_a_response_slower_than_the_timeout_raises_driver_error(self):
        """Error case: the peer is reachable but does not answer in time."""
        url = self.start(_make_handler(status=200, body={}, delay_s=1.0))
        driver = HttpNetworkDriver()
        self.addCleanup(driver.close)

        with self.assertRaises(DriverError):
            driver.call(url, {}, timeout_ms=50)

    def test_a_logical_name_target_raises_driver_error_not_attribute_error(self):
        """Issue #90: `urlsplit("PaymentGateway")` yields `hostname=None`, and
        without entry-point validation `http.client.HTTPConnection(None, ...)`
        raises a raw `AttributeError` the module's exception clause does not
        catch — the ONE ERROR TYPE OUT contract breaks. The message carries
        the original target verbatim (docs/backends.md path-value convention)."""
        driver = HttpNetworkDriver()
        self.addCleanup(driver.close)

        with self.assertRaises(DriverError) as caught:
            driver.call("PaymentGateway", {}, 1000)

        self.assertIn("PaymentGateway", str(caught.exception))

    def test_a_non_http_scheme_target_raises_driver_error(self):
        """Boundary: a well-formed URL whose scheme is not http/https (RFC-0027
        §1 — this driver speaks http.client only) is rejected the same way as
        a logical name, not attempted as a connection."""
        driver = HttpNetworkDriver()
        self.addCleanup(driver.close)

        with self.assertRaises(DriverError) as caught:
            driver.call("ftp://host/path", {}, 1000)

        self.assertIn("ftp://host/path", str(caught.exception))

    def test_close_does_not_raise(self):
        HttpNetworkDriver().close()


class OpenNetworkTest(unittest.TestCase):

    def test_fake_selector_returns_none(self):
        """`None` means "the Interpreter builds its own FakeNetworkDriver" —
        the same convention `open_repository` uses for `--backend fake`."""
        self.assertIsNone(open_network("fake"))

    def test_http_selector_returns_a_driver_instance(self):
        driver = open_network("http")
        self.addCleanup(driver.close)

        self.assertIsInstance(driver, HttpNetworkDriver)

    def test_an_unknown_selector_names_itself_and_the_accepted_set(self):
        with self.assertRaises(ValueError) as ctx:
            open_network("bogus")

        message = str(ctx.exception)
        self.assertIn("bogus", message)
        for name in NETWORKS:
            self.assertIn(name, message)


if __name__ == "__main__":
    unittest.main()

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
    received_headers = []
    received_methods = []
    received_paths = []

    def log_message(self, format, *args):
        pass

    def _reply(self, body_received):
        type(self).received.append(body_received)
        type(self).received_headers.append(dict(self.headers))
        type(self).received_methods.append(self.command)
        type(self).received_paths.append(self.path)
        if self.delay_s:
            time.sleep(self.delay_s)
        payload = (self.raw_body if self.raw_body is not None
                   else json.dumps(self.body).encode("utf-8"))
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        self._reply(json.loads(raw) if raw else None)

    def do_GET(self):
        # method get 본문 없음 (issue #101, D6): a GET carries no body — this
        # driver-side fixture records `None` when it received none, so a test
        # can assert the request had no JSON body the same way it does for POST.
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        self._reply(json.loads(raw) if raw else None)

    # issue #109: PUT/PATCH/DELETE all carry a JSON body the same way POST
    # does (`HttpNetworkDriver.call`'s `method != "GET"` branch), so they
    # share one body-reading path.
    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST


def _make_handler(status=200, body=None, delay_s=0, raw_body=None):
    return type("_Handler", (_StubHandler,), {
        "status": status, "body": body if body is not None else {},
        "delay_s": delay_s, "raw_body": raw_body, "received": [],
        "received_headers": [], "received_methods": [], "received_paths": [],
    })


class _ScriptedHandler(BaseHTTPRequestHandler):
    """Serves `script` — a list of `(status, body)`/`(status, body,
    headers)` tuples — one entry per request, in order, holding on the last
    once exhausted (`FakeNetworkDriver`'s list-stub convention mirrored on
    the wire, issue #109). Used by `NetworkDriverTCK`'s HTTP-backed subclass,
    where a scenario is expressed once and must answer the same way whether
    the driver under test is fake or real."""

    script = [(200, {})]
    calls = []

    def log_message(self, format, *args):
        pass

    def _reply(self):
        idx = len(type(self).calls)
        type(self).calls.append(self.path)
        item = type(self).script[min(idx, len(type(self).script) - 1)]
        status, body, headers = item if len(item) == 3 else (*item, {})
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.rfile.read(length)
        self._reply()

    do_POST = do_GET
    do_PUT = do_GET
    do_PATCH = do_GET
    do_DELETE = do_GET


def _make_scripted_handler(script):
    return type("_Scripted", (_ScriptedHandler,), {"script": script, "calls": []})


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
        """No stub means 200/empty body/empty headers, every time — the
        default has to be deterministic or spec cases relying on it
        (RFC-0027 §7, D4) would be flaky."""
        driver = FakeNetworkDriver({})

        first = driver.call("PaymentGateway", {}, 1000)
        second = driver.call("PaymentGateway", {}, 1000)

        self.assertEqual(first, (200, {}, {}))
        self.assertEqual(second, (200, {}, {}))

    def test_a_stubbed_target_returns_the_stubbed_response(self):
        driver = FakeNetworkDriver({"PaymentGateway": (500, {"message": "card declined"})})

        status, body, headers = driver.call("PaymentGateway", {}, 1000)

        self.assertEqual(status, 500)
        self.assertEqual(body, {"message": "card declined"})
        self.assertEqual(headers, {})

    def test_a_different_targets_stub_does_not_leak_onto_an_unstubbed_one(self):
        driver = FakeNetworkDriver({"PaymentGateway": (500, {})})

        status, body, headers = driver.call("ShippingApi", {}, 1000)

        self.assertEqual((status, body, headers), (200, {}, {}))

    def test_close_does_not_raise(self):
        FakeNetworkDriver({}).close()


class HttpNetworkDriverTest(_ServerTestCase):

    def test_a_successful_call_returns_the_parsed_status_and_body(self):
        url = self.start(_make_handler(status=200, body={"ok": True}))
        driver = HttpNetworkDriver()
        self.addCleanup(driver.close)

        status, body, headers = driver.call(url, {"amount": 42}, 2000)

        self.assertEqual(status, 200)
        self.assertEqual(body, {"ok": True})
        self.assertEqual(headers.get("content-type"), "application/json")

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

        status, body, _headers = driver.call(url, {}, 2000)

        self.assertEqual(status, 500)
        self.assertEqual(body, {"message": "boom"})

    def test_a_non_json_body_becomes_an_empty_dict(self):
        """Boundary: the value shape (dict) stays stable even when the peer
        does not speak JSON."""
        url = self.start(_make_handler(status=200, raw_body=b"not json"))
        driver = HttpNetworkDriver()
        self.addCleanup(driver.close)

        status, body, _headers = driver.call(url, {}, 2000)

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

    # ---- issue #101: logical-name resolution + method/auth ----

    def test_a_logical_name_resolves_through_endpoints_and_calls_out(self):
        """Normal case: `--endpoint PaymentGateway=<url>`-style mapping makes
        a logical-name `call` reach the mock server, same as a URL literal."""
        url = self.start(_make_handler(status=200, body={"ok": True}))
        driver = HttpNetworkDriver(endpoints={"PaymentGateway": url})
        self.addCleanup(driver.close)

        status, body, _headers = driver.call("PaymentGateway", {"amount": 42}, 2000)

        self.assertEqual((status, body), (200, {"ok": True}))

    def test_a_declared_bearer_auth_capability_sends_the_authorization_header(self):
        handler = _make_handler(status=200, body={})
        url = self.start(handler)
        driver = HttpNetworkDriver(
            endpoints={"PaymentGateway": url},
            capabilities={"PaymentGateway": {
                "method": "POST", "headers": {"Authorization": "Bearer tok123"}}})
        self.addCleanup(driver.close)

        driver.call("PaymentGateway", {}, 2000)

        self.assertEqual(handler.received_headers[0].get("Authorization"),
                         "Bearer tok123")

    def test_a_declared_apikey_auth_capability_sends_the_named_header(self):
        handler = _make_handler(status=200, body={})
        url = self.start(handler)
        driver = HttpNetworkDriver(
            endpoints={"PaymentGateway": url},
            capabilities={"PaymentGateway": {
                "method": "POST", "headers": {"X-Api-Key": "abc123"}}})
        self.addCleanup(driver.close)

        driver.call("PaymentGateway", {}, 2000)

        self.assertEqual(handler.received_headers[0].get("X-Api-Key"), "abc123")

    def test_a_get_method_capability_sends_no_body(self):
        """Boundary (D6): `method get` sends no request body — a webhook-style
        GET, unlike the fixed-POST pre-#101 behaviour."""
        handler = _make_handler(status=200, body={})
        url = self.start(handler)
        driver = HttpNetworkDriver(
            endpoints={"Webhook": url},
            capabilities={"Webhook": {"method": "GET", "headers": {}}})
        self.addCleanup(driver.close)

        driver.call("Webhook", {"amount": 42}, 2000)

        self.assertEqual(handler.received_methods[0], "GET")
        self.assertIsNone(handler.received[0])

    def test_put_patch_delete_capabilities_send_the_declared_method(self):
        """Issue #109: PUT/PATCH/DELETE reach the wire as real HTTP methods,
        not just as parsed capability metadata."""
        for method in ("PUT", "PATCH", "DELETE"):
            handler = _make_handler(status=200, body={})
            url = self.start(handler)
            driver = HttpNetworkDriver(
                endpoints={"Orders": url},
                capabilities={"Orders": {"method": method, "headers": {}}})
            self.addCleanup(driver.close)

            driver.call("Orders", {"amount": 42}, 2000)

            self.assertEqual(handler.received_methods[0], method)
            self.assertEqual(handler.received[0], {"amount": 42})

    def test_a_mapped_but_undeclared_logical_name_defaults_to_post_no_auth(self):
        """A logical name mapped via `endpoints` but naming no `capabilities`
        entry (declared-not-bound, issue #101 D4) still calls out — method
        POST, no extra headers, same as the pre-#101 fixed behaviour."""
        handler = _make_handler(status=200, body={})
        url = self.start(handler)
        driver = HttpNetworkDriver(endpoints={"Unbound": url})
        self.addCleanup(driver.close)

        driver.call("Unbound", {"x": 1}, 2000)

        self.assertEqual(handler.received_methods[0], "POST")
        self.assertEqual(handler.received[0], {"x": 1})
        self.assertNotIn("Authorization", handler.received_headers[0])

    def test_a_url_literal_target_ignores_capabilities_and_stays_post(self):
        """Regression (DoD): a URL literal target is byte-identical to
        pre-#101 behaviour even when a `capabilities` entry happens to share
        its exact string — capability lookup is keyed by logical name only,
        and a URL literal never goes through it."""
        handler = _make_handler(status=200, body={})
        url = self.start(handler)
        driver = HttpNetworkDriver(
            capabilities={url: {"method": "GET", "headers": {"X-Should-Not": "1"}}})
        self.addCleanup(driver.close)

        driver.call(url, {"amount": 42}, 2000)

        self.assertEqual(handler.received_methods[0], "POST")
        self.assertEqual(handler.received[0], {"amount": 42})
        self.assertNotIn("X-Should-Not", handler.received_headers[0])

    def test_a_logical_name_with_no_endpoint_entry_raises_driver_error(self):
        """Error case: defense-in-depth for a driver used directly, without
        the CLI's startup mapping check (issue #101 D3) ever running."""
        driver = HttpNetworkDriver(endpoints={"OtherGateway": "http://x/"})
        self.addCleanup(driver.close)

        with self.assertRaises(DriverError) as caught:
            driver.call("PaymentGateway", {}, 1000)

        self.assertIn("PaymentGateway", str(caught.exception))


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

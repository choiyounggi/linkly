"""issue #148, D3: `HttpNetworkDriver` keep-alive connection pool -- a
thread-local cache keyed by `(scheme, host, port)` (`http.client` is not
thread-safe, so nothing wider than thread-local is safe; the workflow
interpreter runs each request's steps on whatever thread called it).

Normal: repeated calls to the same target reuse ONE TCP connection instead
of opening a new one each time. Error: a cached connection the remote
already closed (idle keep-alive timeout) is retried ONCE with a fresh
reconnect rather than failing outright; a genuine failure (server down) is
still a `DriverError`, and the broken connection is discarded from the
cache rather than cached for a future call to fail on again.

`_CountingHandler` (`protocol_version = "HTTP/1.1"`, the stdlib default's
opposite -- `BaseHTTPRequestHandler` defaults to HTTP/1.0, which would close
every connection and make reuse untestable) counts `connections_opened`
(once per accepted TCP connection, `setup()`) separately from
`requests_handled` (once per HTTP request, however many share one
connection) -- reuse shows up as `requests_handled > connections_opened`.
"""

import socket
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lnpl.drivers import DriverError, HttpNetworkDriver

from tests.test_network_driver import _ServerTestCase


class _CountingHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    connections_opened = 0
    requests_handled = 0
    close_after_n_requests = None   # None = never force a server-side close
    sockets = None                  # every accepted connection's raw socket

    def log_message(self, format, *args):
        pass

    def setup(self):
        super().setup()
        type(self).connections_opened += 1
        if type(self).sockets is not None:
            type(self).sockets.append(self.request)

    def _reply(self):
        type(self).requests_handled += 1
        payload = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        if (type(self).close_after_n_requests is not None
                and type(self).requests_handled >= type(self).close_after_n_requests):
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.rfile.read(length)
        self._reply()

    do_POST = do_GET


def _make_counting_handler(close_after_n_requests=None, track_sockets=False):
    return type("_Counting", (_CountingHandler,), {
        "connections_opened": 0, "requests_handled": 0,
        "close_after_n_requests": close_after_n_requests,
        "sockets": [] if track_sockets else None,
    })


class KeepAliveReuseTest(_ServerTestCase):

    def test_normal_repeated_calls_reuse_one_connection(self):
        handler = _make_counting_handler()
        url = self.start(handler)
        driver = HttpNetworkDriver()
        self.addCleanup(driver.close)

        for _ in range(3):
            status, body, _headers = driver.call(url, {}, 2000)
            self.assertEqual(200, status)
            self.assertEqual({"ok": True}, body)

        self.assertEqual(3, handler.requests_handled)
        self.assertEqual(1, handler.connections_opened)

    def test_normal_different_targets_get_independent_connections(self):
        handler_a = _make_counting_handler()
        handler_b = _make_counting_handler()
        url_a = self.start(handler_a)
        url_b = self.start(handler_b)
        driver = HttpNetworkDriver()
        self.addCleanup(driver.close)

        driver.call(url_a, {}, 2000)
        driver.call(url_b, {}, 2000)
        driver.call(url_a, {}, 2000)

        self.assertEqual(1, handler_a.connections_opened)
        self.assertEqual(1, handler_b.connections_opened)
        self.assertEqual(2, handler_a.requests_handled)
        self.assertEqual(1, handler_b.requests_handled)

    def test_normal_a_stale_connection_is_retried_once_and_succeeds(self):
        # The server closes the connection after its 1st reply -- the
        # driver's cached `conn` object still thinks it is open, so the 2nd
        # `driver.call` hits the real "reused-but-stale" path, not a clean
        # `sock is None` reconnect.
        handler = _make_counting_handler(close_after_n_requests=1)
        url = self.start(handler)
        driver = HttpNetworkDriver()
        self.addCleanup(driver.close)

        first_status, _b1, _h1 = driver.call(url, {}, 2000)
        time.sleep(0.1)   # let the server's close reach the client's socket
        second_status, _b2, _h2 = driver.call(url, {}, 2000)

        self.assertEqual(200, first_status)
        self.assertEqual(200, second_status)   # the caller never sees an error
        self.assertEqual(2, handler.requests_handled)
        self.assertEqual(2, handler.connections_opened)   # had to reconnect once

    def test_error_a_dead_target_raises_driver_error_and_discards_the_cache_entry(self):
        # Not `self.start()` -- this test needs the `server`/`thread`
        # handles themselves, to stop the server at an exact point mid-test
        # rather than at teardown (see the shutdown-ordering note below).
        handler = _make_counting_handler(track_sockets=True)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        url = "http://%s:%d/" % (host, port)

        driver = HttpNetworkDriver()
        self.addCleanup(driver.close)
        driver.call(url, {}, 2000)   # populate the cache with a live connection
        key = (urllib.parse.urlsplit(url).scheme,
              urllib.parse.urlsplit(url).hostname,
              urllib.parse.urlsplit(url).port)
        self.assertIn(key, driver._connection_cache())

        # Sever the SPECIFIC connection the driver cached -- its keep-alive
        # handler thread is otherwise still alive and would happily answer
        # a 2nd request on it (a plain `server.shutdown()` only stops the
        # listening socket from accepting NEW connections; it does not
        # touch already-accepted ones, so a `driver.close()`/`stop()`
        # registered as a normal `addCleanup` -- which runs LIFO, AFTER
        # this test body -- would arrive too late anyway). SHUT_RDWR forces
        # an immediate reset/EOF on the client's next use, standing in for
        # "the remote closed this specific keep-alive connection."
        handler.sockets[0].shutdown(socket.SHUT_RDWR)
        handler.sockets[0].close()
        # And stop the server itself -- the reconnect-retry after that
        # failed reuse must ALSO fail (a genuinely dead target, not just
        # one stale connection to an otherwise-live server -- that
        # scenario is already covered by
        # `test_normal_a_stale_connection_is_retried_once_and_succeeds`).
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

        with self.assertRaises(DriverError):
            driver.call(url, {}, 500)
        self.assertNotIn(key, driver._connection_cache())


class CloseTest(_ServerTestCase):

    def test_normal_close_closes_every_cached_connection_on_this_thread(self):
        handler = _make_counting_handler()
        url = self.start(handler)
        driver = HttpNetworkDriver()

        driver.call(url, {}, 2000)
        cache_before = dict(driver._connection_cache())
        self.assertEqual(1, len(cache_before))

        driver.close()

        self.assertEqual({}, driver._connection_cache())
        for conn in cache_before.values():
            self.assertIsNone(conn.sock)

    def test_boundary_close_with_nothing_cached_does_not_raise(self):
        HttpNetworkDriver().close()

    def test_normal_each_thread_gets_its_own_cache(self):
        handler = _make_counting_handler()
        url = self.start(handler)
        driver = HttpNetworkDriver()
        self.addCleanup(driver.close)

        driver.call(url, {}, 2000)   # populate this (main) thread's cache

        other_thread_cache_len = []

        def from_other_thread():
            driver.call(url, {}, 2000)
            other_thread_cache_len.append(len(driver._connection_cache()))
            driver.close()   # closes only THIS thread's entry (asserted below)

        t = threading.Thread(target=from_other_thread)
        t.start()
        t.join(timeout=5)

        self.assertEqual([1], other_thread_cache_len)     # its own, separate entry
        self.assertEqual(1, len(driver._connection_cache()))  # main thread's is untouched
        self.assertEqual(2, handler.connections_opened)   # one connection per thread


if __name__ == "__main__":
    unittest.main()

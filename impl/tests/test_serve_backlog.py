"""Issue #226: `lnpl serve`'s listen backlog.

The server used socketserver's default `request_queue_size` of 5. When more
than that many connections arrived while the accept loop was busy, the kernel
dropped the extra SYNs and each client retried 1 s (then 2 s) later — the
1–2 s stalls seen at 150 rps. These tests open a burst of connections against
a server that is not accepting yet, which is exactly that moment.
"""

import http.client
import socket
import threading
import unittest

from lnpl import serve

BURST = 64           # well above the old 5, below macOS's somaxconn of 128
CONNECT_TIMEOUT_S = 0.5  # shorter than the 1 s SYN retry, so a drop shows up


def ok_app(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/plain"),
                              ("Content-Length", "2")])
    return [b"ok"]


def make_server(queue_size=None):
    cls = serve._Server
    if queue_size is not None:
        cls = type("_SmallQueueServer", (serve._Server,),
                   {"request_queue_size": queue_size})
    server = cls(("127.0.0.1", 0), serve._WSGIRequestHandler)
    server.set_app(ok_app)
    return server


def open_burst(address, count):
    """Connect up to `count` sockets without the server accepting any of
    them. Stops at the first connect that fails, so a dropped SYN costs one
    timeout, not one per remaining socket. Returns (connected sockets, the
    error that stopped the burst or None)."""
    connected = []
    for _ in range(count):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(CONNECT_TIMEOUT_S)
        try:
            sock.connect(address)
        except OSError as exc:
            sock.close()
            return connected, exc
        connected.append(sock)
    return connected, None


class ListenBacklogTest(unittest.TestCase):

    def setUp(self):
        self.sockets = []

    def tearDown(self):
        for sock in self.sockets:
            sock.close()

    def test_burst_of_pending_connections_all_connect(self):
        server = make_server()
        self.addCleanup(server.server_close)
        connected, error = open_burst(server.server_address, BURST)
        self.sockets.extend(connected)
        self.assertIsNone(error, "connect #%d failed" % (len(connected) + 1))
        self.assertEqual(len(connected), BURST)

    def test_stdlib_default_queue_drops_part_of_the_same_burst(self):
        # Known-bad control: the old backlog of 5 cannot hold the burst, so
        # the test above would catch a regression back to it.
        server = make_server(queue_size=5)
        self.addCleanup(server.server_close)
        connected, error = open_burst(server.server_address, BURST)
        self.sockets.extend(connected)
        self.assertIsInstance(error, OSError)
        self.assertLess(len(connected), BURST)

    def test_queued_connections_are_served_once_accepting_starts(self):
        server = make_server()
        self.addCleanup(server.server_close)
        connected, error = open_burst(server.server_address, BURST)
        self.sockets.extend(connected)
        self.assertIsNone(error)
        for sock in connected:
            sock.sendall(b"GET / HTTP/1.0\r\nHost: test\r\n\r\n")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.shutdown)
        statuses = []
        for sock in connected:
            sock.settimeout(5)
            response = http.client.HTTPResponse(sock)
            response.begin()
            statuses.append(response.status)
            self.assertEqual(response.read(), b"ok")
        self.assertEqual(statuses, [200] * BURST)


if __name__ == "__main__":
    unittest.main()

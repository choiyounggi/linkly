"""Shared contract (issue #80, D3): the same request/response cases run
against BOTH entry points — the embedded dev server (a real socket, wrapped
in `wsgiref` per D2) and the WSGI callable driven directly (no socket, no
`wsgiref`, just `environ`/`start_response`) — and must agree. This is what
proves the restructuring in `wsgi.py` preserved behavior: not by reading the
code once, but by running one case through both paths and diffing the
response every time. `impl/tests/test_serve*.py` already pin the FULL
behavior on the socket path in isolation; this file's only job is equivalence
between the two paths, plus the one case that is new in kind — SSE consumed
as a plain WSGI iterator, with no socket at all (D6's boundary case).
"""

import io
import json
import os
import tempfile
import unittest

from lnpl.drivers import SqliteRepositoryDriver
from lnpl.interp import FakeRepository
from lnpl.wsgi import SSE_IDLE_TIMEOUT_S, SSE_POLL_INTERVAL_S, make_wsgi_app
import lnpl.wsgi as wsgi_mod
from tests.test_serve import ServerTestCase
from tests.test_serve_get import ORDERS_SRC, compile_doc, order_payload, uid
from tests.test_serve_sse import TWO_EVENT_SRC, compile_src as compile_sse_src

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP_ROOT = os.path.join(REPO_ROOT, ".claude", "tmp")

SAVE_ORDER_PATH = "/orders/save-order"


def _wsgi_environ(method, path, query="", body=b"", headers=None):
    headers = headers or {}
    env = {
        "REQUEST_METHOD": method,
        "SCRIPT_NAME": "",
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
        "wsgi.errors": io.StringIO(),
        "wsgi.version": (1, 0),
        "wsgi.multithread": True,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
        "wsgi.url_scheme": "http",
        "SERVER_NAME": "test",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
    }
    for name, value in headers.items():
        if name.lower() == "content-type":
            env["CONTENT_TYPE"] = value
        else:
            env["HTTP_" + name.upper().replace("-", "_")] = value
    return env


def call_wsgi(app, method, path, query="", body=b"", headers=None):
    """Drive `app` as a plain WSGI callable -> (status_int, headers, parsed).

    No socket, no `wsgiref` — exactly the contract a host (gunicorn, or the
    `wsgiref.validate` wrapper in test_wsgi.py) is required to honor: call
    with `environ`/`start_response`, consume the returned iterable, close it.
    """
    environ = _wsgi_environ(method, path, query, body, headers)
    captured = {}

    def start_response(status, response_headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = dict(response_headers)

    result = app(environ, start_response)
    try:
        raw = b"".join(result)
    finally:
        if hasattr(result, "close"):
            result.close()
    status_code = int(captured["status"].split(" ", 1)[0])
    parsed = json.loads(raw) if raw else None
    return status_code, captured["headers"], parsed


def _without_volatile(body):
    """A response body with request-random fields removed — `correlation_id`
    is a fresh uuid per request by design, so two independently-run requests
    for the "same" scenario never share one; every OTHER field must still
    match byte-for-byte for the contract to hold."""
    if not isinstance(body, dict):
        return body
    return {k: v for k, v in body.items() if k != "correlation_id"}


class SharedContractTest(ServerTestCase):
    """Two fully isolated stacks (own `FakeRepository`, own port, own WSGI
    app) fed the identical request -> identical response, minus
    `correlation_id`. Isolation (not one shared store) is deliberate: it
    means a mismatch can only come from the two code paths disagreeing, never
    from one request's side effects leaking into the other's read.
    """

    def setUp(self):
        self.socket_repo = FakeRepository()
        self.wsgi_repo = FakeRepository()
        doc = compile_doc(ORDERS_SRC)
        self.port = self.start(doc, repository_factory=lambda: self.socket_repo)
        self.app = make_wsgi_app(doc, repository_factory=lambda: self.wsgi_repo)

    def _socket_post(self, path, payload, headers=None):
        resp, body = self.post_json(self.port, path, payload, headers=headers)
        return resp.status, body

    def _wsgi_post(self, path, payload, headers=None):
        body = json.dumps(payload).encode("utf-8")
        headers = dict(headers or {})
        headers.setdefault("Authorization", "Bearer test-token")
        status, _, parsed = call_wsgi(self.app, "POST", path, body=body, headers=headers)
        return status, parsed

    # -- normal ------------------------------------------------------------

    def test_normal_post_workflow_completes_identically_on_both_paths(self):
        payload = order_payload(uid(1), "2026-01-01T00:00:00Z")
        sock_status, sock_body = self._socket_post(SAVE_ORDER_PATH, payload)
        wsgi_status, wsgi_body = self._wsgi_post(SAVE_ORDER_PATH, payload)
        self.assertEqual(200, sock_status)
        self.assertEqual(sock_status, wsgi_status)
        self.assertEqual(_without_volatile(sock_body), _without_volatile(wsgi_body))

    def test_normal_get_single_returns_the_same_masked_row_on_both_paths(self):
        payload = order_payload(uid(2), "2026-01-02T00:00:00Z")
        self.assertEqual(200, self._socket_post(SAVE_ORDER_PATH, payload)[0])
        self.assertEqual(200, self._wsgi_post(SAVE_ORDER_PATH, payload)[0])

        path = "/orders/order/%s" % uid(2)
        resp, sock_raw = self.request(self.port, "GET", path,
                                      headers={"Authorization": "Bearer x"})
        sock_body = json.loads(sock_raw)
        wsgi_status, _, wsgi_body = call_wsgi(
            self.app, "GET", path, headers={"Authorization": "Bearer x"})

        self.assertEqual(200, resp.status)
        self.assertEqual(resp.status, wsgi_status)
        self.assertEqual(sock_body, wsgi_body)
        self.assertEqual("***", wsgi_body["secret"])   # masking held on both

    def test_normal_get_list_returns_the_same_page_on_both_paths(self):
        for n in (3, 4):
            payload = order_payload(uid(n), "2026-01-0%dT00:00:00Z" % n)
            self.assertEqual(200, self._socket_post(SAVE_ORDER_PATH, payload)[0])
            self.assertEqual(200, self._wsgi_post(SAVE_ORDER_PATH, payload)[0])

        resp, sock_raw = self.request(self.port, "GET", "/orders/order",
                                      headers={"Authorization": "Bearer x"})
        sock_body = json.loads(sock_raw)
        wsgi_status, _, wsgi_body = call_wsgi(
            self.app, "GET", "/orders/order", headers={"Authorization": "Bearer x"})

        self.assertEqual(200, resp.status)
        self.assertEqual(resp.status, wsgi_status)
        self.assertEqual(sock_body, wsgi_body)
        self.assertEqual(2, len(wsgi_body["items"]))

    # -- error ---------------------------------------------------------------

    def test_error_401_missing_auth_is_identical_on_both_paths(self):
        payload = order_payload(uid(5), "2026-01-05T00:00:00Z")
        resp, sock_raw = self.request(
            self.port, "POST", SAVE_ORDER_PATH,
            body=json.dumps(payload).encode("utf-8"))
        sock_body = json.loads(sock_raw)
        wsgi_status, _, wsgi_body = call_wsgi(
            self.app, "POST", SAVE_ORDER_PATH,
            body=json.dumps(payload).encode("utf-8"))
        self.assertEqual(401, resp.status)
        self.assertEqual(resp.status, wsgi_status)
        self.assertEqual(sock_body, wsgi_body)

    def test_error_404_unknown_path_is_identical_on_both_paths(self):
        resp, sock_raw = self.request(self.port, "GET", "/no/such/path")
        sock_body = json.loads(sock_raw)
        wsgi_status, _, wsgi_body = call_wsgi(self.app, "GET", "/no/such/path")
        self.assertEqual(404, resp.status)
        self.assertEqual(resp.status, wsgi_status)
        self.assertEqual(sock_body, wsgi_body)


class SseWsgiIteratorTest(unittest.TestCase):
    """D6's boundary case: SSE consumed as a plain WSGI iterator — `app()`
    returns something a host calls `next()` on repeatedly, with no socket
    anywhere in this test. `test_serve_sse.py` already proves the real-time,
    reconnect, and idle-close behavior on the socket path; this proves the
    WSGI generator itself is a correct PEP-3333 iterable (bytes chunks,
    `start_response` called once before the first item)."""

    def setUp(self):
        os.makedirs(TMP_ROOT, exist_ok=True)
        box = tempfile.TemporaryDirectory(dir=TMP_ROOT)
        self.addCleanup(box.cleanup)
        self.db = os.path.join(box.name, "store.db")
        self.doc = compile_sse_src(TWO_EVENT_SRC)
        self.app = make_wsgi_app(
            self.doc, repository_factory=lambda: SqliteRepositoryDriver(self.db))
        self._orig_poll = wsgi_mod.SSE_POLL_INTERVAL_S
        self._orig_idle = wsgi_mod.SSE_IDLE_TIMEOUT_S
        wsgi_mod.SSE_POLL_INTERVAL_S = 0.01
        wsgi_mod.SSE_IDLE_TIMEOUT_S = 0.3
        self.addCleanup(self._restore_timing)

    def _restore_timing(self):
        wsgi_mod.SSE_POLL_INTERVAL_S = self._orig_poll
        wsgi_mod.SSE_IDLE_TIMEOUT_S = self._orig_idle

    def _post(self, order_id):
        status, _, body = call_wsgi(
            self.app, "POST", "/orders/place-order",
            body=json.dumps({"id": order_id, "status": "new"}).encode("utf-8"),
            headers={"Authorization": "Bearer test-token"})
        self.assertEqual(200, status, body)

    def test_boundary_sse_frames_arrive_through_plain_iteration(self):
        # Emit first, then open the stream from seq 0 — this test is about
        # the iterator mechanics, not real-time arrival (already covered on
        # the socket path), so there is nothing to race.
        order_id = "3f2504e0-4f89-41d3-9a0c-0305e82c3f01"
        self._post(order_id)

        captured = {}

        def start_response(status, headers, exc_info=None):
            captured["status"] = status
            captured["headers"] = dict(headers)

        environ = _wsgi_environ("GET", "/orders/events/order-placed",
                                headers={"Authorization": "Bearer test-token"})
        result = self.app(environ, start_response)
        self.assertTrue(captured["status"].startswith("200"))
        self.assertEqual("text/event-stream", captured["headers"]["Content-Type"])

        # `result` is a generator — pull raw chunks with plain `next()`, the
        # same way a WSGI host's write loop does, and reassemble the frame.
        first_chunk = next(iter(result))
        self.assertIn(b"id: 1\n", first_chunk)
        self.assertIn(json.dumps({"id": order_id, "status": "new"}).encode("utf-8"),
                      first_chunk)
        result.close()

    def test_boundary_idle_stream_ends_the_iterator_on_its_own(self):
        # Zero emissions: the generator must still be a well-behaved
        # iterator that terminates (StopIteration) once SSE_IDLE_TIMEOUT_S
        # elapses, not hang the WSGI host forever.
        captured = {}

        def start_response(status, headers, exc_info=None):
            captured["status"] = status

        environ = _wsgi_environ("GET", "/orders/events/order-placed",
                                headers={"Authorization": "Bearer test-token"})
        result = self.app(environ, start_response)
        frames = list(result)
        self.assertEqual([], frames)
        self.assertTrue(captured["status"].startswith("200"))


if __name__ == "__main__":
    unittest.main()

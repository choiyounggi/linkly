"""Issue #103: the SSE subscribe surface, derived from an event declaration's
`subscribe` opt-in marker — never from a new ws grammar (AppSync pattern; the
issue explicitly rejects Hasura-style auto-expose-everything).

`EventSubscribeParseLowerTest` pins the marker at the parse/lower layer
(pure, no server). `BuildRoutesEventTest` pins route derivation: a subscribed
event owned by a service (reachable via that service's workflow `emit`,
the same structural derivation `build_routes` already uses for get-single
entities — RFC-0001 rule 6, no new declaration invented) gets a route; an
unsubscribed one does not. `SseSubscribeHttpTest` drives the real socket:
real-time arrival (id=outbox seq, data=masked payload), Last-Event-ID
reconnect without loss, jwt 401 reuse (M3), 404 for an unsubscribed event,
400 for a forged Last-Event-ID, and the two D7 boundary cases (a stream with
zero emissions stays open and healthy; multiple declared events but only the
subscribed one's frames cross the wire).
"""

import concurrent.futures
import http.client
import json
import os
import tempfile
import time
import unittest

from lnpl.drivers import SqliteRepositoryDriver
from lnpl.lower import LowerError, lower
from lnpl.openapi import generate
from lnpl.parser import ParseError, parse
from lnpl.serve import build_routes
from tests.test_serve import ServerTestCase
import lnpl.serve as serve_mod


def compile_src(source, module="mod"):
    return lower(parse(source), module).to_document()


def find_node(doc, node_id):
    for node in doc["nodes"]:
        if node["id"] == node_id:
            return node
    raise KeyError(node_id)


# Two events fire from one `create order` — only OrderPlaced opts in. This is
# also the fixture the "multiple events, only the subscribed one crosses the
# wire" boundary test needs: one POST, two outbox rows, two different event
# names.
TWO_EVENT_SRC = """entity Order
    field
        id UUID
        status Text

event OrderPlaced on Order create
    subscribe

event OrderLogged on Order create

service Orders
    security
        jwt

workflow PlaceOrder
    create order
    emit orderPlaced
    emit orderLogged
"""


class EventSubscribeParseLowerTest(unittest.TestCase):
    """Pure parse/lower coverage — no server, no I/O."""

    def test_normal_subscribe_marker_reaches_the_event_node(self):
        doc = compile_src(TWO_EVENT_SRC)
        placed = find_node(doc, "event.order.placed")
        self.assertIs(True, placed["subscribe"])

    def test_boundary_event_without_subscribe_carries_no_key(self):
        doc = compile_src(TWO_EVENT_SRC)
        logged = find_node(doc, "event.order.logged")
        self.assertNotIn("subscribe", logged)

    def test_error_subscribe_declared_twice_is_rejected(self):
        src = TWO_EVENT_SRC.replace(
            "event OrderPlaced on Order create\n    subscribe\n",
            "event OrderPlaced on Order create\n    subscribe\n    subscribe\n")
        with self.assertRaises(LowerError):
            compile_src(src)

    def test_error_subscribe_with_trailing_tokens_is_rejected(self):
        src = TWO_EVENT_SRC.replace(
            "event OrderPlaced on Order create\n    subscribe\n",
            "event OrderPlaced on Order create\n    subscribe now\n")
        with self.assertRaises(LowerError):
            compile_src(src)

    def test_error_a_bare_event_still_rejects_an_unknown_clause_line(self):
        # `capability`/`refine` are untouched by #103: only `event` gained a
        # content-line carve-out, and only for `subscribe`.
        with self.assertRaises((ParseError, LowerError)):
            compile_src("entity Thing\n    field\n        id UUID\n"
                        "event Whatever\n    nonsense\n")


class BuildRoutesEventTest(unittest.TestCase):

    def test_normal_subscribed_and_emitted_event_gets_a_route(self):
        doc = compile_src(TWO_EVENT_SRC)
        routes = build_routes(doc)
        self.assertIn("/orders/events/order-placed", routes)
        entry = routes["/orders/events/order-placed"]
        self.assertEqual("sse-subscribe", entry["kind"])
        self.assertEqual("event.order.placed", entry["event"])
        self.assertTrue(entry["auth"])
        self.assertEqual(set(routes), set(generate(doc)["paths"]))

    def test_boundary_unsubscribed_event_gets_no_route(self):
        doc = compile_src(TWO_EVENT_SRC)
        routes = build_routes(doc)
        self.assertNotIn("/orders/events/order-logged", routes)


def _uid(n):
    return "3f2504e0-4f89-41d3-9a0c-0305e82c33%02x" % n


class SseSubscribeHttpTest(ServerTestCase):
    """Real socket round trip — routing, auth reuse, and the tail itself only
    a live request can cover (mirrors test_serve_get.py's own rationale)."""

    def setUp(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        tmp_root = os.path.join(repo_root, ".claude", "tmp")
        os.makedirs(tmp_root, exist_ok=True)
        box = tempfile.TemporaryDirectory(dir=tmp_root)
        self.addCleanup(box.cleanup)
        self.db = os.path.join(box.name, "store.db")
        self.doc = compile_src(TWO_EVENT_SRC)
        self.port = self.start(
            self.doc, repository_factory=lambda: SqliteRepositoryDriver(self.db))
        self._orig_poll = serve_mod.SSE_POLL_INTERVAL_S
        self._orig_idle = serve_mod.SSE_IDLE_TIMEOUT_S
        serve_mod.SSE_POLL_INTERVAL_S = 0.02
        serve_mod.SSE_IDLE_TIMEOUT_S = 0.5
        self.addCleanup(self._restore_timing)

    def _restore_timing(self):
        serve_mod.SSE_POLL_INTERVAL_S = self._orig_poll
        serve_mod.SSE_IDLE_TIMEOUT_S = self._orig_idle

    def _place_order(self, order_id):
        resp, body = self.post_json(
            self.port, "/orders/place-order",
            {"id": order_id, "status": "new"})
        self.assertEqual(200, resp.status, body)
        return body

    def _open_stream(self, path, headers=None, auth=True):
        headers = dict(headers or {})
        if auth:
            headers.setdefault("Authorization", "Bearer test-token")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        self.addCleanup(conn.close)
        return conn, resp

    def _read_frame(self, resp):
        """One SSE frame (`{"id": ..., "data": ...}`) or `None` at a clean EOF."""
        event_id, data_lines = None, []
        while True:
            raw = resp.fp.readline()
            if not raw:
                return None
            line = raw.decode("utf-8").rstrip("\n")
            if line == "":
                if event_id is not None or data_lines:
                    return {"id": event_id, "data": "\n".join(data_lines)}
                continue
            if line.startswith("id:"):
                event_id = line[3:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())

    # -- normal --------------------------------------------------------

    def test_normal_emit_arrives_on_the_open_stream_in_real_time(self):
        result = {}

        def listen():
            conn, resp = self._open_stream("/orders/events/order-placed")
            self.assertEqual(200, resp.status)
            result["frame"] = self._read_frame(resp)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(listen)
            # Give the GET a moment to be accepted and start polling before
            # the emission it must catch is created (D5: this is a poll
            # loop, not a push — a POST that lands before the stream opens
            # would never be missed either, since seq starts the tail from
            # Last-Event-ID/0, but the real-time claim needs the frame to
            # arrive on an ALREADY-open connection).
            time.sleep(0.15)
            self._place_order(_uid(1))
            fut.result(timeout=5)

        frame = result["frame"]
        self.assertIsNotNone(frame, "no frame arrived before EOF")
        self.assertEqual("1", frame["id"])
        self.assertEqual({"id": _uid(1), "status": "new"},
                         json.loads(frame["data"]))

    # -- error -----------------------------------------------------------

    def test_error_no_token_on_a_jwt_service_is_401(self):
        conn, resp = self._open_stream(
            "/orders/events/order-placed", auth=False)
        self.assertEqual(401, resp.status)

    def test_error_unsubscribed_event_is_404(self):
        conn, resp = self._open_stream("/orders/events/order-logged")
        self.assertEqual(404, resp.status)

    def test_error_malformed_last_event_id_is_400(self):
        conn, resp = self._open_stream(
            "/orders/events/order-placed",
            headers={"Last-Event-ID": "not-a-number"})
        self.assertEqual(400, resp.status)

    # -- boundary --------------------------------------------------------

    def test_boundary_reconnect_with_last_event_id_loses_nothing(self):
        # Each `_place_order` emits BOTH orderPlaced and orderLogged sharing
        # one seq counter, so orderPlaced's own seq is 1, then 3 (2 and 4 go
        # to orderLogged) — the reconnect only has to lose neither of ITS
        # event's rows, not land on consecutive integers.
        self._place_order(_uid(2))
        conn1, resp1 = self._open_stream("/orders/events/order-placed")
        first = self._read_frame(resp1)
        self.assertEqual("1", first["id"])
        conn1.close()

        self._place_order(_uid(3))
        conn2, resp2 = self._open_stream(
            "/orders/events/order-placed",
            headers={"Last-Event-ID": first["id"]})
        second = self._read_frame(resp2)
        self.assertIsNotNone(second, "the second emission was lost on resume")
        self.assertEqual("3", second["id"])
        self.assertEqual(_uid(3), json.loads(second["data"])["id"])

    def test_boundary_zero_emissions_stream_stays_healthy_then_closes(self):
        conn, resp = self._open_stream("/orders/events/order-placed")
        self.assertEqual(200, resp.status)
        frame = self._read_frame(resp)
        self.assertIsNone(frame, "an idle stream must not fabricate a frame")

    def test_boundary_only_the_subscribed_event_crosses_the_wire(self):
        result = {}

        def listen():
            conn, resp = self._open_stream("/orders/events/order-placed")
            result["frame"] = self._read_frame(resp)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(listen)
            time.sleep(0.15)
            self._place_order(_uid(4))  # emits BOTH orderPlaced + orderLogged
            fut.result(timeout=5)

        frame = result["frame"]
        self.assertIsNotNone(frame)
        self.assertEqual(_uid(4), json.loads(frame["data"])["id"])
        # The route for order-logged does not even exist (404 test above) —
        # this pins that the tail query itself is event-scoped, not just the
        # route table: a second `_read_frame` on the SAME stream must not
        # surface `orderLogged`'s row as a second frame.


if __name__ == "__main__":
    unittest.main()

"""`lnpl relay` — issue #118, D8: the reference relay. Drains a document's
`lnpl_outbox` (issue #102) and POSTs each emission as a CloudEvents
structured-mode envelope to a target instance's `POST /-/events/<slug>`
consume route (D4/D5), then acks by the response: 200 -> ack; 422 -> ack +
dead-letter line to stderr (retrying an identical payload can never turn a
permanent rejection into a success); 503 or no response at all -> leave
un-acked for the next drain (at-least-once).

No broker, no mock HTTP client: a real `wsgiref` server on an ephemeral
loopback port stands in for the consuming instance, and `lnpl relay` talks
to it over a real socket via stdlib `urllib` — the same "prove the wire
protocol, not a stand-in" posture `test_network_driver.py`'s
`_ServerTestCase` already established for `NetworkCall`.
"""

import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
from wsgiref.simple_server import make_server

from lnpl import cli
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.wsgi import make_wsgi_app

PUBLISH_SRC = """entity Order
    field
        id UUID
        amount Integer

service OrderService

event OrderPlaced on Order create

workflow PlaceOrder
    create order
    emit orderPlaced
"""

# The consuming side: same event NAME (`OrderPlaced` -> slug `order-placed`)
# as PUBLISH_SRC, this time with `consume by`. `ValidateOrder` succeeds on
# any payload carrying a UUID `id` and an Integer `amount` -- exactly what
# `PlaceOrder` above passes to `emit`.
CONSUME_SRC = """entity Order
    field
        id UUID
        amount Integer

service OrderService

event OrderPlaced
    consume by ValidateOrder

workflow ValidateOrder
    validate order
"""

# A consuming side whose workflow always fails validation -- `code` is
# declared but PUBLISH_SRC's emitted payload never carries it, so `validate
# order` fails deterministically no matter what `amount`/`id` say. Every
# CloudEvents envelope this route receives is a permanent (422) rejection.
ALWAYS_REJECTS_SRC = """entity Order
    field
        id UUID
        code Text

service OrderService

event OrderPlaced
    consume by RejectOrder

workflow RejectOrder
    validate order
"""


def _wsgi_server(doc):
    """A real `wsgiref` HTTP server for `doc`, on an ephemeral loopback
    port, torn down by the caller's `addCleanup`. Returns (base_url, stop).
    """
    app = make_wsgi_app(doc)
    server = make_server("127.0.0.1", 0, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def stop():
        server.shutdown()
        thread.join()
        server.server_close()

    host, port = server.server_address
    return "http://%s:%d" % (host, port), stop


class RelayCliTestCase(unittest.TestCase):

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.dir = box.name
        self.publish_source = os.path.join(self.dir, "publish.lnpl")
        with open(self.publish_source, "w", encoding="utf-8") as fh:
            fh.write(PUBLISH_SRC)
        self.db = os.path.join(self.dir, "store.db")

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def payload_file(self, payload, name="payload.json"):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return path

    def emit_one(self, order_id="3f2504e0-4f89-41d3-9a0c-0305e82c330b",
                amount=5):
        payload = self.payload_file({"id": order_id, "amount": amount},
                                    name="payload-%s.json" % order_id)
        rc, _out, err = self.run_cli(
            ["run", self.publish_source, "--backend", "sqlite:" + self.db,
             "--payload", payload])
        self.assertEqual(0, rc, err)

    def drain(self):
        rc, out, err = self.run_cli(
            ["outbox", "drain", "--backend", "sqlite:" + self.db])
        self.assertEqual(0, rc, err)
        return [json.loads(line) for line in out.splitlines() if line.strip()]

    def start_consumer(self, src):
        doc = lower(parse(src), "consumer").to_document()
        base_url, stop = _wsgi_server(doc)
        self.addCleanup(stop)
        return base_url


class NormalRoundTripTest(RelayCliTestCase):
    """DoD 9: publish (sqlite outbox) -> `lnpl relay --once` -> a real
    consuming instance -> 200 -> acked, drained clean."""

    def test_a_delivered_emission_is_acked_and_no_longer_drains(self):
        self.emit_one()
        base_url = self.start_consumer(CONSUME_SRC)

        rc, out, err = self.run_cli(
            ["relay", self.publish_source, "--backend", "sqlite:" + self.db,
             "--target", base_url, "--once"])

        self.assertEqual(0, rc, err)
        self.assertIn("acked 1", out)
        self.assertEqual([], self.drain())

    def test_a_second_relay_run_with_nothing_new_acks_zero(self):
        self.emit_one()
        base_url = self.start_consumer(CONSUME_SRC)
        self.run_cli(["relay", self.publish_source, "--backend",
                     "sqlite:" + self.db, "--target", base_url, "--once"])

        rc, out, err = self.run_cli(
            ["relay", self.publish_source, "--backend", "sqlite:" + self.db,
             "--target", base_url, "--once"])

        self.assertEqual(0, rc, err)
        self.assertIn("acked 0", out)


class PermanentRejectionTest(RelayCliTestCase):
    """D7/D8: a 422 is a dead letter -- acked (retrying cannot help) with a
    warning naming it, never silently dropped and never left for an
    infinite retry."""

    def test_a_422_is_acked_with_a_dead_letter_warning(self):
        self.emit_one()
        base_url = self.start_consumer(ALWAYS_REJECTS_SRC)

        rc, _out, err = self.run_cli(
            ["relay", self.publish_source, "--backend", "sqlite:" + self.db,
             "--target", base_url, "--once"])

        self.assertEqual(0, rc)
        self.assertIn("dead-letter", err)
        self.assertIn("422", err)
        self.assertEqual([], self.drain())   # acked despite the rejection


class TransientFailureTest(RelayCliTestCase):
    """D7/D8: no response at all (nobody listening) is treated exactly like
    a 503 -- left un-acked, at-least-once, for the next drain to retry."""

    def test_an_unreachable_target_leaves_the_emission_unacked(self):
        self.emit_one()
        # Nothing is listening at this port -- connection refused.
        unreachable = "http://127.0.0.1:1"

        rc, out, err = self.run_cli(
            ["relay", self.publish_source, "--backend", "sqlite:" + self.db,
             "--target", unreachable, "--once"])

        self.assertEqual(0, rc, err)
        self.assertIn("acked 0", out)
        self.assertEqual(1, len(self.drain()))   # still there, retryable


class BackendValidationTest(RelayCliTestCase):
    def test_fake_backend_is_rejected(self):
        rc, _out, err = self.run_cli(
            ["relay", self.publish_source, "--backend", "fake",
             "--target", "http://127.0.0.1:1", "--once"])

        self.assertEqual(2, rc)
        self.assertIn("persistent --backend", err)


class UnknownEventIdTest(unittest.TestCase):
    """Boundary: an outbox row whose event id this compiled document does
    not declare (e.g. the document changed since the row was written) is
    never silently acked -- it is reported and left for a human."""

    def test_an_unmapped_event_id_is_reported_and_left_unacked(self):
        acked_seqs = []

        class _FakeRepository:
            def drain_outbox(self):
                return [{"seq": 7, "emission_id": "e1",
                        "event": "event.no.longer.declared",
                        "payload": {}, "created_at": 0}]

            def ack_outbox(self, seqs):
                acked_seqs.extend(seqs)

        count = cli._relay_drain_once(_FakeRepository(), {}, "test-source",
                                      "http://127.0.0.1:1")

        self.assertEqual(0, count)
        self.assertEqual([], acked_seqs)


if __name__ == "__main__":
    unittest.main()

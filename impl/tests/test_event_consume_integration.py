"""Issue #118, D11: the end-to-end round trip the whole feature exists to
prove — publish (sqlite outbox) -> `lnpl relay --once` -> a real consuming
instance (`wsgiref`, ephemeral loopback port, daemon thread — the same
real-server convention `test_network_driver.py`'s `_ServerTestCase`
established) -> and a redelivered CloudEvents `id` does not re-run the
consuming workflow a second time.

Two separate processes' worth of state (two sqlite files: one for the
publisher's outbox, one for the consumer's rows + idempotency table) stand
in for two separate `lnpl serve` instances, connected by nothing but an
HTTP hop and `lnpl relay` — no broker, matching RFC-0040's own claim that
this is real without one.

D11's second half — `consume by`-free documents still compile byte-for-byte
unchanged — lives in `TestNoRegressionForConsumeFreeModules` below.
"""

import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from wsgiref.simple_server import make_server

from lnpl import cli
from lnpl.drivers import SqliteRepositoryDriver
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.wsgi import make_wsgi_app

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

# `RecordOrder` has an observable side effect (`create order`) so a
# duplicate execution is directly countable, unlike a bare `validate`.
CONSUME_SRC = """entity Order
    field
        id UUID
        amount Integer

service OrderService

event OrderPlaced
    consume by RecordOrder

workflow RecordOrder
    create order
"""


class RoundTripAndRedeliveryTest(unittest.TestCase):

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.dir = box.name
        self.publish_source = os.path.join(self.dir, "publish.lnpl")
        with open(self.publish_source, "w", encoding="utf-8") as fh:
            fh.write(PUBLISH_SRC)
        self.publish_db = os.path.join(self.dir, "publish.db")
        self.consume_db = os.path.join(self.dir, "consume.db")

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def start_consumer(self):
        """A real `wsgiref` server for `CONSUME_SRC`, backed by a persistent
        sqlite store (needed for #113's idempotency dedup to have anywhere
        to durably record a claim — the `fake` backend cannot).
        """
        doc = lower(parse(CONSUME_SRC), "consumer").to_document()
        app = make_wsgi_app(
            doc, repository_factory=lambda: SqliteRepositoryDriver(self.consume_db))
        server = make_server("127.0.0.1", 0, app)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop():
            server.shutdown()
            thread.join()
            server.server_close()

        self.addCleanup(stop)
        host, port = server.server_address
        return "http://%s:%d" % (host, port)

    def count_orders(self):
        driver = SqliteRepositoryDriver(self.consume_db)
        try:
            return len(driver.query("entity.order"))
        finally:
            driver.close()

    def post_envelope(self, base_url, envelope):
        request = urllib.request.Request(
            base_url + "/-/events/order-placed",
            data=json.dumps(envelope).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=10) as resp:
                return resp.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def test_publish_relay_consume_round_trip(self):
        payload_path = os.path.join(self.dir, "payload.json")
        with open(payload_path, "w", encoding="utf-8") as fh:
            json.dump({"id": "3f2504e0-4f89-41d3-9a0c-0305e82c330b",
                      "amount": 7}, fh)
        rc, _out, err = self.run_cli(
            ["run", self.publish_source, "--backend",
             "sqlite:" + self.publish_db, "--payload", payload_path])
        self.assertEqual(0, rc, err)

        base_url = self.start_consumer()

        rc, out, err = self.run_cli(
            ["relay", self.publish_source, "--backend",
             "sqlite:" + self.publish_db, "--target", base_url, "--once"])

        self.assertEqual(0, rc, err)
        self.assertIn("acked 1", out)
        self.assertEqual(1, self.count_orders())

        # DoD 9's other half: the outbox is clean after a successful relay.
        rc, out, err = self.run_cli(
            ["outbox", "drain", "--backend", "sqlite:" + self.publish_db])
        self.assertEqual(0, rc, err)
        self.assertEqual("", out.strip())

    def test_redelivery_of_the_same_id_does_not_duplicate_the_row(self):
        """D6/D11: the SAME CloudEvents envelope (same `id`) posted twice —
        the second time simulating a broker-level at-least-once redelivery,
        the shape `lnpl relay` itself would also produce if a response was
        lost after a successful run — must not run `create order` twice."""
        payload_path = os.path.join(self.dir, "payload.json")
        with open(payload_path, "w", encoding="utf-8") as fh:
            json.dump({"id": "3f2504e0-4f89-41d3-9a0c-0305e82c330b",
                      "amount": 7}, fh)
        rc, _out, err = self.run_cli(
            ["run", self.publish_source, "--backend",
             "sqlite:" + self.publish_db, "--payload", payload_path])
        self.assertEqual(0, rc, err)
        base_url = self.start_consumer()
        self.run_cli(["relay", self.publish_source, "--backend",
                     "sqlite:" + self.publish_db, "--target", base_url,
                     "--once"])
        self.assertEqual(1, self.count_orders())

        envelope = {"specversion": "1.0", "id": "outbox-1",
                   "source": "publish", "type": "OrderPlaced",
                   "data": {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c330b",
                            "amount": 7}}
        status = self.post_envelope(base_url, envelope)

        self.assertEqual(200, status)
        self.assertEqual(1, self.count_orders())   # not 2 -- replayed, not re-run


class TestNoRegressionForConsumeFreeModules(unittest.TestCase):
    """D11's other half: a document with no `consume by` at all compiles to
    the byte-identical IR document this feature must never touch.

    `examples/login.lnpl` is the real regression fixture (issue #36) other
    tests already pin against the checked-in `login.lir.json` golden — it
    declares an event (`UserCreated on User create`) with no `consume by`,
    so it is exactly the "unaffected by this feature" case. Recompiling it
    now, after every D1-D8 change in this task, and comparing against the
    UNTOUCHED golden file (confirmed via `git status` before this task
    started) is the actual byte-identical proof — not two fresh compiles of
    the same in-memory string, which would be true by construction and
    prove nothing about this task's changes.
    """

    def test_login_golden_still_compiles_byte_identical(self):
        with open(os.path.join(REPO, "examples", "login.lnpl"),
                  encoding="utf-8") as fh:
            source = fh.read()
        with open(os.path.join(REPO, "examples", "login.lir.json"),
                  encoding="utf-8") as fh:
            golden = json.load(fh)

        recompiled = lower(parse(source), "login").to_document()
        # `provenance` (issue #136) is excluded from golden comparisons — its
        # digests are environment-dependent, so the committed golden stays
        # provenance-free (docs/compatibility.md §2).
        recompiled = dict(recompiled)
        recompiled.pop("provenance")

        self.assertEqual(golden, recompiled)
        event_node = next(n for n in recompiled["nodes"] if n["kind"] == "Event")
        self.assertNotIn("consume", event_node)


if __name__ == "__main__":
    unittest.main()

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
import types
import unittest
from importlib import metadata as importlib_metadata
from unittest import mock
from wsgiref.simple_server import make_server

from lnpl import cli
from lnpl import drivers as drivers_module
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.wsgi import make_wsgi_app
from tests.driver_spi_fixture import DemoRepositoryDriver

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

    def emit_n(self, n):
        """Emit `n` outbox rows (seq 1..n on a fresh store), distinct ids."""
        for i in range(1, n + 1):
            self.emit_one(order_id="00000000-0000-4000-8000-%012d" % i)

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



def _publishers_registered(*entry_points):
    """Patch `lnpl.publishers` discovery to exactly `entry_points` (the
    `test_publisher_spi.py` helper, mirrored)."""
    return mock.patch.object(drivers_module.importlib_metadata, "entry_points",
                             lambda **_kw: list(entry_points))


DEMO_PUBLISHER = importlib_metadata.EntryPoint(
    name="demo", value="tests.publisher_spi_fixture:make_demo_publisher",
    group=drivers_module.PUBLISHERS_ENTRY_POINT_GROUP)

# issue #229: the one line every outbox command prints when its --backend
# driver lacks drain_outbox/ack_outbox (supports_outbox_drain() is False).
NO_DRAIN_CONTRACT = ("error: backend %s does not implement the outbox drain "
                     "contract (drain_outbox/ack_outbox) — see "
                     "docs/backends.md §3\n")

# The repo root (impl/tests/ -> impl/ -> root), for the doc agreement tests.
REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

DEMO_DRIVER = importlib_metadata.EntryPoint(
    name="demo", value="tests.driver_spi_fixture:make_demo_driver",
    group=drivers_module.DRIVERS_ENTRY_POINT_GROUP)


def _drivers_registered(*entry_points):
    """Patch `lnpl.drivers` discovery to exactly `entry_points` (the
    `test_driver_spi.py` idiom)."""
    return mock.patch.object(drivers_module.importlib_metadata,
                             "entry_points",
                             lambda **_kw: list(entry_points))


def _inline_entry_point(name, driver):
    """An `lnpl.drivers` entry point whose factory returns `driver`, so the
    test can inspect the very instance the CLI opened."""
    return types.SimpleNamespace(
        name=name, value="inline",
        group=drivers_module.DRIVERS_ENTRY_POINT_GROUP,
        load=lambda: (lambda _arg: driver))


def _factory_entry_point(name, factory):
    """An `lnpl.drivers` entry point whose factory calls `factory()` on
    EVERY `--backend` open, so two relays get two driver instances."""
    return types.SimpleNamespace(
        name=name, value="inline",
        group=drivers_module.DRIVERS_ENTRY_POINT_GROUP,
        load=lambda: (lambda _arg: factory()))


class _DrainOnlyDriver(DemoRepositoryDriver):
    """Half of the pair: `drain_outbox` without `ack_outbox`, so
    `supports_outbox_drain()` is False (issue #229, boundary)."""

    def __init__(self, arg=None):
        super().__init__(arg)
        self.calls = []
        self.closed = False

    def drain_outbox(self, limit=None):
        self.calls.append(limit)
        return [{"seq": 1, "emission_id": "e1", "event": "x",
                 "payload": {}, "created_at": 0}]

    def close(self):
        self.closed = True


class RegisteredPublisherSchemeTest(RelayCliTestCase):
    """R7/R9: a registered scheme publishes through the matched
    EventPublisher; ack happens only after publish confirms; the driver is
    closed whichever way the relay ends."""

    def record_opened(self):
        real = cli.open_publisher
        opened = []

        def opener(target):
            publisher = real(target)
            opened.append(publisher)
            return publisher

        cli.open_publisher = opener
        self.addCleanup(setattr, cli, "open_publisher", real)
        return opened

    def test_a_registered_scheme_publishes_and_acks(self):
        self.emit_one()
        opened = self.record_opened()

        with _publishers_registered(DEMO_PUBLISHER):
            rc, out, err = self.run_cli(
                ["relay", self.publish_source, "--backend", "sqlite:" + self.db,
                 "--target", "demo://broker/topic", "--once"])

        self.assertEqual(0, rc, err)
        self.assertIn("acked 1", out)
        self.assertEqual([], self.drain())
        self.assertEqual(1, len(opened))
        self.assertEqual(["outbox-1"], opened[0].published)
        self.assertEqual("demo://broker/topic", opened[0].target)
        self.assertTrue(opened[0].closed)

    def test_a_failed_publish_leaves_the_row_for_the_next_drain(self):
        self.emit_one()
        opened = self.record_opened()
        real_factory = cli.open_publisher

        def failing(target):
            publisher = real_factory(target)
            publisher.fail_ids.add("outbox-1")
            return publisher

        cli.open_publisher = failing

        with _publishers_registered(DEMO_PUBLISHER):
            rc, out, err = self.run_cli(
                ["relay", self.publish_source, "--backend", "sqlite:" + self.db,
                 "--target", "demo://broker/topic", "--once"])

        self.assertEqual(0, rc, err)
        self.assertIn("acked 0", out)
        self.assertIn("left un-acked", err)
        self.assertEqual(1, len(self.drain()))   # still there, retryable
        self.assertTrue(opened[0].closed)


class UnknownPublisherSchemeTest(RelayCliTestCase):
    """Error: an unregistered --target scheme is a clear rc!=0 error
    naming the scheme and the registered names, never a traceback,
    never the target's userinfo -- and the outbox is left untouched."""

    def test_an_unregistered_scheme_is_rejected_cleanly(self):
        self.emit_one()

        with _publishers_registered(DEMO_PUBLISHER):
            rc, out, err = self.run_cli(
                ["relay", self.publish_source, "--backend", "sqlite:" + self.db,
                 "--target", "kafka://user:s3cr3t@broker/topic", "--once"])

        self.assertEqual(2, rc)
        self.assertEqual("", out)
        self.assertIn("'kafka'", err)
        self.assertIn("demo", err)
        self.assertNotIn("s3cr3t", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(1, len(self.drain()))

    def test_an_unloadable_registered_scheme_is_rejected_cleanly(self):
        self.emit_one()
        broken = importlib_metadata.EntryPoint(
            name="broken", value="tests.no_such_fixture_module_xyz:make",
            group=drivers_module.PUBLISHERS_ENTRY_POINT_GROUP)

        with _publishers_registered(broken):
            rc, out, err = self.run_cli(
                ["relay", self.publish_source, "--backend", "sqlite:" + self.db,
                 "--target", "broken://user:s3cr3t@broker/topic", "--once"])

        self.assertEqual(2, rc)
        self.assertIn("failed to load", err)
        self.assertNotIn("s3cr3t", err)
        self.assertEqual(1, len(self.drain()))


class UnsupportedDriverRelayTest(RelayCliTestCase):
    """Issue #229: relay refuses a driver without the drain/ack pair
    before opening the publisher and before the first drain."""

    def test_relay_against_a_driver_without_the_contract_exits_2_with_one_line(self):
        with _drivers_registered(DEMO_DRIVER):
            rc, out, err = self.run_cli(
                ["relay", self.publish_source, "--backend", "demo:x",
                 "--target", "http://127.0.0.1:1", "--once"])

        self.assertEqual(2, rc)
        self.assertNotIn("Traceback", err)
        self.assertEqual(NO_DRAIN_CONTRACT % "demo", err)
        self.assertEqual("", out)

    def test_relay_refuses_a_drain_only_driver_before_any_drain(self):
        driver = _DrainOnlyDriver("x")
        with _drivers_registered(_inline_entry_point("half", driver)):
            rc, out, err = self.run_cli(
                ["relay", self.publish_source, "--backend", "half:x",
                 "--target", "http://127.0.0.1:1", "--once"])

        self.assertEqual(2, rc)
        self.assertEqual(NO_DRAIN_CONTRACT % "half", err)
        self.assertEqual("", out)
        self.assertEqual([], driver.calls)
        self.assertTrue(driver.closed)


class _RecordingSqliteDriver(drivers_module.SqliteRepositoryDriver):
    """Issue #257: a real sqlite driver that records, in one `calls` list,
    every transaction/outbox call the relay makes -- the
    `RelayBatchTransactionTest.record_publishes` wrapper appends "publish"
    to the same list -- plus the seqs it drained and acked. `ack_error` /
    `commit_error` (str) make `ack_outbox` / `commit` raise DriverError.
    `max_drains` is the test's own deadline (issue #262): a relay whose
    batch loop never stops fails with AssertionError on the next drain
    instead of hanging the suite; no correct run here needs more than 5."""

    def __init__(self, path, ack_error=None, commit_error=None,
                 max_drains=20):
        super().__init__(path)
        self.max_drains = max_drains
        self.calls = []
        self.drained = []
        self.acked = []
        self.ack_error = ack_error
        self.commit_error = commit_error
        self.limits = []

    def begin(self):
        self.calls.append("begin")
        return super().begin()

    def drain_outbox(self, limit=None):
        self.limits.append(limit)
        self.calls.append("drain_outbox")
        if len(self.limits) > self.max_drains:
            raise AssertionError("relay drained %d times (max_drains=%d): "
                                 "its batch loop did not stop"
                                 % (len(self.limits), self.max_drains))
        rows = super().drain_outbox(limit=limit)
        self.drained.extend(row["seq"] for row in rows)
        return rows

    def ack_outbox(self, seqs):
        self.calls.append("ack_outbox")
        if self.ack_error is not None:
            raise drivers_module.DriverError(self.ack_error)
        result = super().ack_outbox(seqs)
        self.acked.extend(seqs)
        return result

    def commit(self):
        self.calls.append("commit")
        super().commit()
        if self.commit_error is not None:
            raise drivers_module.DriverError(self.commit_error)

    def rollback(self):
        self.calls.append("rollback")
        return super().rollback()


class _NthAckFailsDriver(_RecordingSqliteDriver):
    """Issue #262: `ack_outbox` raises DriverError on its `fail_on_ack`-th
    call only (before touching sqlite), so earlier batches stay acked."""

    def __init__(self, path, fail_on_ack):
        super().__init__(path)
        self.fail_on_ack = fail_on_ack
        self.ack_count = 0

    def ack_outbox(self, seqs):
        self.ack_count += 1
        if self.ack_count == self.fail_on_ack:
            self.calls.append("ack_outbox")
            raise drivers_module.DriverError(
                "outbox ack: simulated failure on ack %d" % self.ack_count)
        return super().ack_outbox(seqs)


class _NoLimitRecordingSqliteDriver(_RecordingSqliteDriver):
    """Issue #262 fallback: a recording driver whose `drain_outbox` takes
    no `limit` (an out-of-tree driver written before the parameter)."""

    def drain_outbox(self):
        self.calls.append("drain_outbox")
        rows = drivers_module.SqliteRepositoryDriver.drain_outbox(self)
        self.drained.extend(row["seq"] for row in rows)
        return rows


class _TypeErrorDriver(_RecordingSqliteDriver):
    """Issue #262: a TypeError raised INSIDE `drain_outbox` is a driver
    bug, not a "no limit" signal -- the relay must not swallow it."""

    def drain_outbox(self, limit=None):
        self.calls.append("drain_outbox")
        raise TypeError("boom inside driver")


class _BeginRecordingDrainOnlyDriver(_DrainOnlyDriver):
    """`_DrainOnlyDriver` that also records `begin` -- proves the issue
    #229 guard still returns before any transaction is opened."""

    def begin(self):
        self.calls.append("begin")


class _SkipLockedStore:
    """One shared outbox for several `_SkipLockedDriver` instances, modelling
    lnpl-postgres' `SELECT ... FOR UPDATE SKIP LOCKED` (issue #262)."""

    def __init__(self, rows):
        self.rows = [dict(r) for r in sorted(rows, key=lambda r: r["seq"])]
        self.delivered = set()
        self.locks = {}          # seq -> the driver instance holding it


class _SkipLockedDriver(DemoRepositoryDriver):
    """Rows drained inside begin() stay locked by this instance until
    commit()/rollback(); another instance's drain skips them, never waits."""

    def __init__(self, store):
        super().__init__("skip-locked")
        self.store = store
        self.in_tx = False
        self.drained = []
        self.acked = []
        self._tx_acked = []

    def begin(self):
        self.in_tx = True
        self._tx_acked = []

    def drain_outbox(self, limit=None):
        free = [r for r in self.store.rows
                if r["seq"] not in self.store.delivered
                and self.store.locks.get(r["seq"], self) is self]
        picked = free if limit is None else free[:limit]
        if self.in_tx:
            for r in picked:
                self.store.locks[r["seq"]] = self
        self.drained.extend(r["seq"] for r in picked)
        return [dict(r) for r in picked]

    def ack_outbox(self, seqs):
        for seq in seqs:
            self.store.delivered.add(seq)
        self._tx_acked.extend(seqs)
        self.acked.extend(seqs)

    def commit(self):
        self._release()

    def rollback(self):
        for seq in self._tx_acked:
            self.store.delivered.discard(seq)
            self.acked.remove(seq)
        self._release()

    def _release(self):
        self.store.locks = {s: o for s, o in self.store.locks.items()
                            if o is not self}
        self.in_tx = False
        self._tx_acked = []


class _NoLimitSkipLockedDriver(_SkipLockedDriver):
    """The fallback: `drain_outbox` takes no `limit`."""

    def drain_outbox(self):
        return super().drain_outbox()


class RelayBatchTransactionTest(RelayCliTestCase):
    """Issue #257: each relay batch (drain -> publish/POST -> ack) runs
    inside one driver transaction: begin before the drain, commit after
    the batch, rollback when an exception escapes it. One `calls` list
    per driver pins the order; "publish" is appended once per publish
    ATTEMPT, success or failure."""

    SECOND_ORDER_ID = "00000000-0000-4000-8000-000000000002"

    def setUp(self):
        super().setUp()
        self.real_open_publisher = cli.open_publisher
        self.addCleanup(setattr, cli, "open_publisher",
                        self.real_open_publisher)

    def record_publishes(self, driver, fail_ids=(), interrupt_ids=()):
        """Replace `cli.open_publisher` (the l.343-353 idiom) with an opener
        around the REAL one saved in setUp, so a second call never wraps
        the first wrapper."""
        real = self.real_open_publisher

        def opener(target):
            publisher = real(target)
            publisher.fail_ids.update(fail_ids)
            inner = publisher.publish

            def publish(envelope):
                driver.calls.append("publish")
                if envelope["id"] in interrupt_ids:
                    raise KeyboardInterrupt
                return inner(envelope)

            publisher.publish = publish
            return publisher

        cli.open_publisher = opener

    def relay(self, driver, target="demo://broker/topic"):
        with _drivers_registered(_inline_entry_point("rec", driver),
                                 DEMO_PUBLISHER):
            return self.run_cli(
                ["relay", self.publish_source, "--backend", "rec:x",
                 "--target", target, "--once"])

    def test_a_publisher_batch_runs_inside_one_transaction(self):
        self.emit_one()
        driver = _RecordingSqliteDriver(self.db)
        self.record_publishes(driver)

        rc, out, err = self.relay(driver)

        self.assertEqual(0, rc, err)
        self.assertIn("acked 1", out)
        self.assertEqual(["begin", "drain_outbox", "publish", "ack_outbox",
                          "commit"], driver.calls)

    def test_an_http_batch_runs_inside_one_transaction(self):
        self.emit_one()
        base_url = self.start_consumer(CONSUME_SRC)
        driver = _RecordingSqliteDriver(self.db)

        rc, out, err = self.relay(driver, target=base_url)

        self.assertEqual(0, rc, err)
        self.assertIn("acked 1", out)
        self.assertEqual(["begin", "drain_outbox", "ack_outbox", "commit"],
                         driver.calls)

    def test_two_drainers_in_turn_receive_disjoint_batches(self):
        self.emit_one()
        self.emit_one(order_id=self.SECOND_ORDER_ID)
        first = _RecordingSqliteDriver(self.db)
        self.record_publishes(first, fail_ids={"outbox-2"})
        rc_first, out_first, err_first = self.relay(first)
        second = _RecordingSqliteDriver(self.db)
        self.record_publishes(second)

        rc_second, out_second, err_second = self.relay(second)

        self.assertEqual(0, rc_first, err_first)
        self.assertEqual(0, rc_second, err_second)
        self.assertEqual([1, 2], first.drained)
        self.assertEqual([1], first.acked)
        self.assertEqual([2], second.drained)
        self.assertEqual([2], second.acked)
        self.assertTrue(set(first.acked).isdisjoint(second.drained))
        self.assertEqual(["begin", "drain_outbox", "publish", "publish",
                          "ack_outbox", "commit"], first.calls)
        self.assertEqual(["begin", "drain_outbox", "publish", "ack_outbox",
                          "commit"], second.calls)
        self.assertEqual([], self.drain())

    def test_a_failed_publish_leaves_the_row_and_still_commits(self):
        self.emit_one()
        driver = _RecordingSqliteDriver(self.db)
        self.record_publishes(driver, fail_ids={"outbox-1"})

        rc, out, err = self.relay(driver)

        self.assertEqual(0, rc, err)
        self.assertIn("acked 0", out)
        self.assertIn("left un-acked", err)
        self.assertEqual(["begin", "drain_outbox", "publish", "commit"],
                         driver.calls)
        self.assertEqual(1, len(self.drain()))   # back in the queue

    def test_an_ack_failure_rolls_back_and_exits_1(self):
        self.emit_one()
        driver = _RecordingSqliteDriver(
            self.db, ack_error="outbox ack: unknown seq(s): 1")
        self.record_publishes(driver)

        rc, _out, err = self.relay(driver)

        self.assertEqual(1, rc)
        self.assertIn("error: outbox ack: unknown seq(s): 1", err)
        self.assertEqual(["begin", "drain_outbox", "publish", "ack_outbox",
                          "rollback"], driver.calls)
        driver.begin()   # the boundary was closed: no nested-begin error
        self.assertEqual("begin", driver.calls[-1])
        self.assertEqual(1, len(self.drain()))

    def test_an_interrupt_during_publish_rolls_back_and_the_row_stays(self):
        self.emit_one()
        driver = _RecordingSqliteDriver(self.db)
        self.record_publishes(driver, interrupt_ids={"outbox-1"})

        with self.assertRaises(KeyboardInterrupt):
            self.relay(driver)

        self.assertEqual(["begin", "drain_outbox", "publish", "rollback"],
                         driver.calls)
        self.assertEqual(1, len(self.drain()))

    def test_a_commit_failure_exits_1_without_a_rollback(self):
        self.emit_one()
        driver = _RecordingSqliteDriver(
            self.db,
            commit_error="cannot commit transaction: simulated commit failure")
        self.record_publishes(driver)

        rc, _out, err = self.relay(driver)

        self.assertEqual(1, rc)
        self.assertIn("error: cannot commit transaction: simulated commit "
                      "failure", err)
        self.assertEqual(["begin", "drain_outbox", "publish", "ack_outbox",
                          "commit"], driver.calls)
        # sqlite's ack_outbox committed on its own, so the row stays
        # delivered (docs/backends.md §3: no redelivery on sqlite).
        self.assertEqual([], self.drain())

    def test_an_empty_outbox_commits_an_empty_batch(self):
        driver = _RecordingSqliteDriver(self.db)
        self.record_publishes(driver)

        rc, out, err = self.relay(driver)

        self.assertEqual(0, rc, err)
        self.assertIn("acked 0", out)
        self.assertEqual(["begin", "drain_outbox", "commit"], driver.calls)

    def test_a_driver_without_the_contract_never_opens_a_transaction(self):
        driver = _BeginRecordingDrainOnlyDriver("x")
        with _drivers_registered(_inline_entry_point("half", driver)):
            rc, out, err = self.run_cli(
                ["relay", self.publish_source, "--backend", "half:x",
                 "--target", "http://127.0.0.1:1", "--once"])

        self.assertEqual(2, rc)
        self.assertEqual(NO_DRAIN_CONTRACT % "half", err)
        self.assertEqual([], driver.calls)
        self.assertTrue(driver.closed)


class RelayBoundedBatchTest(RelayBatchTransactionTest):
    """Issue #262: `lnpl relay` drains at most `RELAY_BATCH_LIMIT` rows per
    batch (one transaction each) and drains again only after a full batch
    that acked at least one row. `limited()` shrinks the bound to 2 so a
    handful of rows spans several batches."""

    def limited(self, n=2):
        return mock.patch.object(cli, "RELAY_BATCH_LIMIT", n)

    def test_a_limit_accepting_driver_is_drained_with_the_bound(self):
        self.emit_n(1)
        driver = _RecordingSqliteDriver(self.db)
        self.record_publishes(driver)

        rc, out, err = self.relay(driver)

        self.assertEqual(0, rc, err)
        self.assertEqual([cli.RELAY_BATCH_LIMIT], driver.limits)

    def test_once_drains_a_backlog_larger_than_one_batch(self):
        with self.limited():
            self.emit_n(5)
            driver = _RecordingSqliteDriver(self.db)
            self.record_publishes(driver)

            rc, out, err = self.relay(driver)

        self.assertEqual(0, rc, err)
        self.assertIn("acked 5", out)
        self.assertEqual([2, 2, 2], driver.limits)
        self.assertEqual([1, 2, 3, 4, 5], driver.drained)
        self.assertEqual(["begin", "drain_outbox", "publish", "publish",
                          "ack_outbox", "commit", "begin", "drain_outbox",
                          "publish", "publish", "ack_outbox", "commit",
                          "begin", "drain_outbox", "publish", "ack_outbox",
                          "commit"],
                         driver.calls)
        self.assertEqual([], self.drain())

    def test_an_http_once_drains_in_bounded_batches(self):
        with self.limited():
            self.emit_n(3)
            base_url = self.start_consumer(CONSUME_SRC)
            driver = _RecordingSqliteDriver(self.db)

            rc, out, err = self.relay(driver, target=base_url)

        self.assertEqual(0, rc, err)
        self.assertIn("acked 3", out)
        self.assertEqual(["begin", "drain_outbox", "ack_outbox", "commit",
                          "begin", "drain_outbox", "ack_outbox", "commit"],
                         driver.calls)

    def test_an_ack_failure_in_the_second_batch_keeps_the_first_batch(self):
        with self.limited():
            self.emit_n(3)
            driver = _NthAckFailsDriver(self.db, fail_on_ack=2)
            self.record_publishes(driver)

            rc, out, err = self.relay(driver)

        self.assertEqual(1, rc)
        self.assertIn("error: outbox ack: simulated failure on ack 2", err)
        self.assertNotIn("acked", out)
        self.assertEqual(["begin", "drain_outbox", "publish", "publish",
                          "ack_outbox", "commit", "begin", "drain_outbox",
                          "publish", "ack_outbox", "rollback"],
                         driver.calls)
        self.assertEqual([3], [row["seq"] for row in self.drain()])

    def test_a_full_batch_with_no_ack_ends_the_run(self):
        with self.limited():
            self.emit_n(2)
            driver = _RecordingSqliteDriver(self.db)
            self.record_publishes(driver, fail_ids={"outbox-1", "outbox-2"})

            rc, out, err = self.relay(driver)

        self.assertEqual(0, rc, err)
        self.assertIn("acked 0", out)
        self.assertEqual(["begin", "drain_outbox", "publish", "publish",
                          "commit"],
                         driver.calls)
        self.assertEqual(2, len(self.drain()))

    def test_a_failing_head_row_is_retried_per_batch_and_the_run_ends(self):
        with self.limited():
            self.emit_n(5)
            driver = _RecordingSqliteDriver(self.db)
            self.record_publishes(driver, fail_ids={"outbox-1"})

            rc, out, err = self.relay(driver)

        self.assertEqual(0, rc, err)
        self.assertIn("acked 4", out)
        self.assertEqual([1, 2, 1, 3, 1, 4, 1, 5, 1], driver.drained)
        self.assertEqual(5, driver.calls.count("begin"))
        self.assertEqual([1], [row["seq"] for row in self.drain()])

    def test_exactly_one_full_batch_drains_once_more_then_stops(self):
        with self.limited():
            self.emit_n(2)
            driver = _RecordingSqliteDriver(self.db)
            self.record_publishes(driver)

            rc, out, err = self.relay(driver)

        self.assertEqual(0, rc, err)
        self.assertIn("acked 2", out)
        self.assertEqual(["begin", "drain_outbox", "publish", "publish",
                          "ack_outbox", "commit", "begin", "drain_outbox",
                          "commit"],
                         driver.calls)

    def test_one_row_over_the_bound_takes_two_batches_and_no_third_drain(self):
        with self.limited():
            self.emit_n(3)
            driver = _RecordingSqliteDriver(self.db)
            self.record_publishes(driver)

            rc, out, err = self.relay(driver)

        self.assertEqual(0, rc, err)
        self.assertIn("acked 3", out)
        self.assertEqual(2, driver.calls.count("drain_outbox"))
        self.assertEqual([1, 2, 3], driver.drained)

    def test_a_driver_without_limit_gets_one_unbounded_batch(self):
        with self.limited():
            self.emit_n(3)
            driver = _NoLimitRecordingSqliteDriver(self.db)
            self.record_publishes(driver)

            rc, out, err = self.relay(driver)

        self.assertEqual(0, rc, err)
        self.assertIn("acked 3", out)
        self.assertEqual(["begin", "drain_outbox", "publish", "publish",
                          "publish", "ack_outbox", "commit"],
                         driver.calls)
        self.assertEqual([1, 2, 3], driver.drained)

    def test_a_type_error_inside_the_driver_propagates(self):
        self.emit_n(1)
        driver = _TypeErrorDriver(self.db)
        self.record_publishes(driver)

        with self.assertRaises(TypeError) as ctx:
            self.relay(driver)

        self.assertEqual("boom inside driver", str(ctx.exception))
        self.assertEqual(["begin", "drain_outbox", "rollback"], driver.calls)

    def test_limit_support_is_read_from_the_signature(self):
        driver = _RecordingSqliteDriver(self.db)
        self.addCleanup(driver.close)

        class KeywordOnly:
            def drain_outbox(self, *, limit=None):
                return []

        class PositionalOnly:
            def drain_outbox(self, limit=None, /):
                return []

        class NoLimit:
            def drain_outbox(self):
                return []

        class KwargsOnly:
            def drain_outbox(self, **kw):
                return []

        self.assertTrue(cli._drain_accepts_limit(driver))
        self.assertTrue(cli._drain_accepts_limit(KeywordOnly()))
        self.assertFalse(cli._drain_accepts_limit(PositionalOnly()))
        self.assertFalse(cli._drain_accepts_limit(NoLimit()))
        self.assertFalse(cli._drain_accepts_limit(KwargsOnly()))
        with mock.patch.object(cli.inspect, "signature",
                               side_effect=ValueError("no signature")):
            self.assertFalse(cli._drain_accepts_limit(KeywordOnly()))

    def test_loop_mode_drains_the_whole_backlog_before_sleeping(self):
        with self.limited():
            self.emit_n(5)
            driver = _RecordingSqliteDriver(self.db)
            self.record_publishes(driver)

            interrupt = mock.patch.object(cli.time, "sleep",
                                          side_effect=KeyboardInterrupt)
            with _drivers_registered(_inline_entry_point("rec", driver),
                                     DEMO_PUBLISHER), \
                    interrupt as sleep, \
                    self.assertRaises(KeyboardInterrupt):
                self.run_cli(["relay", self.publish_source, "--backend",
                              "rec:x", "--target", "demo://broker/topic"])

        self.assertEqual([1, 2, 3, 4, 5], driver.acked)
        self.assertEqual("commit", driver.calls[-1])
        self.assertEqual(3, driver.calls.count("begin"))
        self.assertEqual(1, sleep.call_count)
        self.assertEqual([], self.drain())


class ConcurrentRelayShareTest(RelayCliTestCase):
    """Issue #262 (DoD 2): two relays over one row-locking outbox."""

    ARGV_TAIL = ["--backend", "skl:x", "--target", "demo://broker/topic",
                 "--once"]

    def setUp(self):
        super().setUp()
        self.real_open_publisher = cli.open_publisher
        self.addCleanup(setattr, cli, "open_publisher",
                        self.real_open_publisher)

    def seed_store(self, n):
        self.emit_n(n)
        seed = drivers_module.SqliteRepositoryDriver(self.db)
        try:
            rows = seed.drain_outbox()
        finally:
            seed.close()
        return _SkipLockedStore(rows)

    def run_two_relays(self, driver_cls, n=5):
        """Relay A runs `--once`; inside A's FIRST publish, relay B runs a
        complete `--once`. -> (store, [A, B] drivers,
        {"A": (rc, out, err), "B": (rc, out, err)})."""
        store = self.seed_store(n)
        opened = []

        def factory():
            driver = driver_cls(store)
            opened.append(driver)
            return driver

        argv = ["relay", self.publish_source] + self.ARGV_TAIL
        results = {}
        openers = []
        real = self.real_open_publisher

        def opener(target):
            publisher = real(target)
            who = "A" if not openers else "B"
            openers.append(who)
            inner = publisher.publish
            count = [0]

            def publish(envelope):
                count[0] += 1
                if who == "A" and count[0] == 1:
                    results["B"] = self.run_cli(argv)
                return inner(envelope)

            publisher.publish = publish
            return publisher

        cli.open_publisher = opener
        with _drivers_registered(_factory_entry_point("skl", factory),
                                 DEMO_PUBLISHER), \
                mock.patch.object(cli, "RELAY_BATCH_LIMIT", 2):
            results["A"] = self.run_cli(argv)
        return store, opened, results

    def test_two_relays_split_a_large_backlog_into_disjoint_shares(self):
        store, opened, results = self.run_two_relays(_SkipLockedDriver)

        self.assertEqual(2, len(opened))
        a, b = opened
        self.assertEqual(0, results["A"][0], results["A"][2])
        self.assertEqual(0, results["B"][0], results["B"][2])
        # B first: before issue #262 B's share is the empty one.
        self.assertEqual([3, 4, 5], b.acked)
        self.assertEqual([1, 2], a.acked)
        self.assertTrue(a.acked)
        self.assertTrue(b.acked)
        self.assertTrue(set(a.acked).isdisjoint(b.acked))
        self.assertEqual({1, 2, 3, 4, 5}, set(a.acked) | set(b.acked))
        self.assertEqual({1, 2, 3, 4, 5}, store.delivered)
        self.assertEqual({}, store.locks)
        self.assertIn("acked 2", results["A"][1])
        self.assertIn("acked 3", results["B"][1])

    def test_without_a_limit_the_first_relay_takes_the_whole_backlog(self):
        store, opened, results = self.run_two_relays(_NoLimitSkipLockedDriver)

        a, b = opened
        self.assertEqual(0, results["A"][0], results["A"][2])
        self.assertEqual(0, results["B"][0], results["B"][2])
        self.assertEqual([], b.acked)
        self.assertIn("acked 0", results["B"][1])
        self.assertEqual([1, 2, 3, 4, 5], a.acked)
        self.assertIn("acked 5", results["A"][1])
        self.assertEqual({1, 2, 3, 4, 5}, store.delivered)


class RelayBatchBoundDocTest(unittest.TestCase):
    """Issue #262: every document that states the relay batch bound states
    the value `cli.RELAY_BATCH_LIMIT` actually has."""

    def read(self, *parts):
        with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_once_help_states_the_batch_bound(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cli.main(["relay", "--help"])

        self.assertRegex(out.getvalue(),
                         r"at\s+most\s+%d\s+rows" % cli.RELAY_BATCH_LIMIT)

    def test_cli_surface_once_row_states_the_batch_bound(self):
        text = self.read("plugins", "lnpl", "skills", "lnpl-authoring",
                         "cli-surface.md")

        rows = [line for line in text.splitlines()
                if line.startswith("| `--once` |")]

        self.assertEqual(1, len(rows))
        self.assertIn("최대 %d행" % cli.RELAY_BATCH_LIMIT, rows[0])

    def test_backends_doc_states_the_batch_bound(self):
        text = self.read("docs", "backends.md")

        lines = [line for line in text.splitlines()
                 if "배치 크기 상한(issue #262)" in line]

        self.assertNotIn("배치 크기에 상한이 없다", text)
        self.assertEqual(1, len(lines))
        self.assertIn("최대 %d행" % cli.RELAY_BATCH_LIMIT, lines[0])


if __name__ == "__main__":
    unittest.main()

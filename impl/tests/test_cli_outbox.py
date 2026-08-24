"""`lnpl outbox drain` / `lnpl outbox ack` — issue #102: the CLI surface for
the transactional outbox's at-least-once contract.

A `--backend sqlite:...` run's `emit` registers durably in `lnpl_outbox`
(D1/D2). `outbox drain` prints every undelivered emission as JSON Lines,
oldest first by `seq` (D3). `outbox ack <seq>...` marks rows delivered —
idempotent on a re-ack, and it fails closed (naming the seq, rc != 0) before
writing anything when any seq in the batch is unknown, rather than silently
acking the ones it recognizes. `fake` has no persistent store, so both
subcommands reject it instead of crashing on a `None` repository.

`seq`, not `emission_id`, addresses a row: two separate `lnpl run`
invocations of the same document reproduce the same `emission_id` for their
first emission of a given effect (interp.py's counter is local to one
Interpreter instance), and that is two distinct emissions, not one
redelivered — `SecondRunAgainstTheSameStoreTest` pins this as the normal
path, not a crash (the bug this schema exists to fix, measured 2026-08-24).
"""

import contextlib
import io
import json
import os
import tempfile
import unittest

from lnpl import cli

EMIT_SRC = """entity Order
    field
        id UUID
        status Text

event OrderPlaced on Order create

workflow PlaceOrder
    create order
    emit orderPlaced
"""


class OutboxCliTestCase(unittest.TestCase):

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.dir = box.name
        self.source = os.path.join(self.dir, "orders.lnpl")
        with open(self.source, "w", encoding="utf-8") as fh:
            fh.write(EMIT_SRC)
        self.db = os.path.join(self.dir, "store.db")

    def payload_file(self, payload, name="payload.json"):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return path

    def run_cli(self, argv):
        """-> (rc, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def emit_one(self, order_id="o-1"):
        """Runs `EMIT_SRC` once against `self.db`, registering exactly one
        emission — the shared setup every drain/ack test in this file needs
        before it can exercise the CLI surface."""
        payload = self.payload_file({"id": order_id, "status": "new"},
                                    name="payload-%s.json" % order_id)
        rc, _, err = self.run_cli(
            ["run", self.source, "--backend", "sqlite:" + self.db,
             "--payload", payload])
        self.assertEqual(0, rc, err)

    def drain(self):
        rc, out, err = self.run_cli(
            ["outbox", "drain", "--backend", "sqlite:" + self.db])
        self.assertEqual(0, rc, err)
        return [json.loads(line) for line in out.splitlines() if line.strip()]


class DrainAndAckRoundTripTest(OutboxCliTestCase):
    """DoD 1: a sqlite run's emit persists; drain sees it; ack marks it
    delivered; a re-drain no longer shows it."""

    def test_drain_shows_a_recorded_emission(self):
        self.emit_one()

        emissions = self.drain()

        self.assertEqual(1, len(emissions))
        self.assertEqual("event.order.placed", emissions[0]["event"])
        self.assertEqual({"id": "o-1", "status": "new"}, emissions[0]["payload"])
        self.assertIn("emission_id", emissions[0])
        self.assertIn("seq", emissions[0])

    def test_ack_then_redrain_shows_nothing(self):
        self.emit_one()
        seq = self.drain()[0]["seq"]

        rc, _, err = self.run_cli(
            ["outbox", "ack", "--backend", "sqlite:" + self.db, str(seq)])
        self.assertEqual(0, rc, err)

        self.assertEqual([], self.drain())

    def test_drain_respects_limit(self):
        self.emit_one("o-1")
        self.emit_one("o-2")

        rc, out, err = self.run_cli(
            ["outbox", "drain", "--backend", "sqlite:" + self.db, "--limit", "1"])

        self.assertEqual(0, rc, err)
        lines = [line for line in out.splitlines() if line.strip()]
        self.assertEqual(1, len(lines))


class AckIdempotencyTest(OutboxCliTestCase):

    def test_a_duplicate_ack_is_idempotent(self):
        self.emit_one()
        seq = str(self.drain()[0]["seq"])
        rc, _, err = self.run_cli(
            ["outbox", "ack", "--backend", "sqlite:" + self.db, seq])
        self.assertEqual(0, rc, err)

        rc, _, err = self.run_cli(
            ["outbox", "ack", "--backend", "sqlite:" + self.db, seq])

        self.assertEqual(0, rc, err)
        self.assertEqual([], self.drain())


class AckUnknownSeqTest(OutboxCliTestCase):

    def test_an_unknown_seq_fails_with_a_nonzero_rc_naming_it(self):
        self.emit_one()  # the store/table exist, but this seq never was

        rc, _, err = self.run_cli(
            ["outbox", "ack", "--backend", "sqlite:" + self.db, "999999"])

        self.assertNotEqual(0, rc)
        self.assertIn("999999", err)

    def test_a_known_seq_in_the_same_batch_as_an_unknown_one_is_not_acked(self):
        """Fails closed: a caller must never learn "some of these worked"
        from a message that only names the ones that did not."""
        self.emit_one()
        seq = str(self.drain()[0]["seq"])

        rc, _, err = self.run_cli(
            ["outbox", "ack", "--backend", "sqlite:" + self.db,
             seq, "999999"])

        self.assertNotEqual(0, rc)
        self.assertEqual(1, len(self.drain()))


class SecondRunAgainstTheSameStoreTest(OutboxCliTestCase):
    """The normal path the seq-identity schema exists for: a second `lnpl
    run` of the same document against the same store reproduces the first
    run's `emission_id` for its own first emission — that must record as a
    second, distinct row, not fail the run with a PK conflict."""

    def test_a_second_run_records_a_second_row_with_the_same_emission_id(self):
        self.emit_one("o-1")
        self.emit_one("o-2")  # must not raise / fail the run (emit_one asserts rc==0)

        emissions = self.drain()

        self.assertEqual(2, len(emissions))
        self.assertEqual(emissions[0]["emission_id"], emissions[1]["emission_id"])
        self.assertNotEqual(emissions[0]["seq"], emissions[1]["seq"])
        self.assertEqual({"o-1", "o-2"},
                         {e["payload"]["id"] for e in emissions})


class EmptyOutboxDrainTest(OutboxCliTestCase):

    def test_drain_on_a_store_with_no_emissions_prints_nothing(self):
        no_emit_path = os.path.join(self.dir, "no_emit.lnpl")
        with open(no_emit_path, "w", encoding="utf-8") as fh:
            fh.write("""entity Order
    field
        id UUID
        status Text

workflow PlaceOrder
    create order
""")
        payload = self.payload_file({"id": "o-1", "status": "new"})
        rc, _, err = self.run_cli(
            ["run", no_emit_path, "--backend", "sqlite:" + self.db,
             "--payload", payload])
        self.assertEqual(0, rc, err)

        self.assertEqual([], self.drain())


class OutboxBackendGuardTest(OutboxCliTestCase):
    """`fake` has no persistent store to drain/ack — rejected at the
    boundary rather than crashing on a `None` repository."""

    def test_drain_against_fake_is_rejected(self):
        rc, _, err = self.run_cli(["outbox", "drain", "--backend", "fake"])

        self.assertNotEqual(0, rc)
        self.assertIn("fake", err)

    def test_ack_against_fake_is_rejected(self):
        rc, _, err = self.run_cli(
            ["outbox", "ack", "--backend", "fake", "1"])

        self.assertNotEqual(0, rc)
        self.assertIn("fake", err)


if __name__ == "__main__":
    unittest.main()

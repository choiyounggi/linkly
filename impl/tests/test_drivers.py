"""drivers: the capability adapter contracts and the sqlite repository (issue #25).

These tests are written against the *contract*, not against sqlite: every
assertion but the last group is one a second `RepositoryDriver` implementation
would have to satisfy too. The last group is the part the Fake cannot supply —
the store outlives the object that wrote it — and it is what makes "a real
backend" a claim this file can settle rather than assert.

The conflict message is pinned byte-for-byte against `interp.FakeRepository`'s.
That is not cosmetic: `test_driver_contract.py` runs one scenario set over both
drivers with the same assertions, and a message that drifts turns that shared
suite into two suites that happen to share a name.
"""

import os
import stat
import tempfile
import unittest

from lnpl.drivers import (BACKENDS, DriverError, SqliteRepositoryDriver,
                          open_repository)
from lnpl.repo_policy import row_key

PRODUCT = "entity.product"
ORDER = "entity.order"


class DriverTestCase(unittest.TestCase):
    """A temp directory tied to the test's lifetime, so a failing assertion
    still cleans up (a removal after the assertions is skipped by exactly the
    exception that makes cleanup matter)."""

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.dir = box.name
        self.path = os.path.join(self.dir, "store.db")

    def open(self, path=None):
        driver = SqliteRepositoryDriver(path or self.path)
        self.addCleanup(driver.close)
        return driver


class SeedAndReadTest(DriverTestCase):

    def test_a_seeded_row_is_read_back(self):
        driver = self.open()
        payload = {"id": "p-1", "stock": 9}
        key = row_key(PRODUCT, payload)
        driver.seed({PRODUCT: {key: dict(payload)}})

        self.assertEqual(driver.execute(PRODUCT, "read", key), payload)

    def test_query_reads_the_same_row_as_read(self):
        """Both members of repo_policy.READ_OPS resolve to a row lookup."""
        driver = self.open()
        payload = {"id": "p-1", "stock": 9}
        key = row_key(PRODUCT, payload)
        driver.seed({PRODUCT: {key: dict(payload)}})

        self.assertEqual(driver.execute(PRODUCT, "query", key),
                         driver.execute(PRODUCT, "read", key))

    def test_a_read_on_an_empty_store_is_none_not_an_error(self):
        """The absent row is a value the interpreter branches on, not a fault —
        `interp` turns it into "repository read found no row" itself."""
        driver = self.open()

        self.assertIsNone(driver.execute(PRODUCT, "read", "entity.product#p-1"))

    def test_seed_does_not_overwrite_a_row_that_is_already_there(self):
        """The property the persistence story rests on: a second run re-seeds
        and must not erase what the first run wrote."""
        driver = self.open()
        payload = {"id": "p-1", "stock": 9}
        key = row_key(PRODUCT, payload)
        driver.seed({PRODUCT: {key: dict(payload)}})
        driver.persist(PRODUCT, key, {"id": "p-1", "stock": 4})

        driver.seed({PRODUCT: {key: dict(payload)}})

        self.assertEqual(driver.execute(PRODUCT, "read", key)["stock"], 4)

    def test_seeding_nothing_is_not_an_error(self):
        driver = self.open()
        driver.seed({})

        self.assertIsNone(driver.execute(PRODUCT, "read", "entity.product#-"))


class WriteOperationTest(DriverTestCase):

    def test_create_then_read_returns_the_created_row(self):
        driver = self.open()
        key = row_key(ORDER, {"id": "o-1"})

        self.assertEqual(driver.execute(ORDER, "create", key), {"affected": 1})
        self.assertEqual(driver.execute(ORDER, "read", key), {"id": key})

    def test_a_duplicate_create_conflicts(self):
        driver = self.open()
        key = row_key(ORDER, {"id": "o-1"})
        driver.execute(ORDER, "create", key)

        with self.assertRaises(DriverError) as caught:
            driver.execute(ORDER, "create", key)
        self.assertIn("create conflicts", str(caught.exception))
        self.assertIn(ORDER, str(caught.exception))

    def test_persist_writes_a_mutated_row_back(self):
        driver = self.open()
        payload = {"id": "p-1", "stock": 9}
        key = row_key(PRODUCT, payload)
        driver.seed({PRODUCT: {key: dict(payload)}})

        row = driver.execute(PRODUCT, "read", key)
        row["stock"] = row["stock"] - 5
        driver.persist(PRODUCT, key, row)

        self.assertEqual(driver.execute(PRODUCT, "read", key)["stock"], 4)

    def test_update_and_delete_report_what_they_touched(self):
        driver = self.open()
        key = row_key(ORDER, {"id": "o-1"})
        driver.execute(ORDER, "create", key)

        self.assertEqual(driver.execute(ORDER, "update", key), {"affected": 1})
        self.assertEqual(driver.execute(ORDER, "delete", key), {"affected": 1})
        self.assertEqual(driver.execute(ORDER, "delete", key), {"affected": 0})

    def test_an_unknown_operation_names_the_accepted_set(self):
        """A miss in a closed table is a diagnostic, never a plausible no-op."""
        driver = self.open()

        with self.assertRaises(DriverError) as caught:
            driver.execute(ORDER, "upsert", "entity.order#o-1")
        message = str(caught.exception)
        self.assertIn("upsert", message)
        self.assertIn("create", message)


class PersistenceTest(DriverTestCase):
    """The group the Fake cannot satisfy."""

    def test_a_reopened_driver_sees_what_the_closed_one_wrote(self):
        payload = {"id": "p-1", "stock": 9}
        key = row_key(PRODUCT, payload)
        first = SqliteRepositoryDriver(self.path)
        first.seed({PRODUCT: {key: dict(payload)}})
        first.persist(PRODUCT, key, {"id": "p-1", "stock": 4})
        first.close()

        second = self.open()

        self.assertEqual(second.execute(PRODUCT, "read", key)["stock"], 4)

    def test_a_create_survives_the_driver_that_made_it(self):
        key = row_key(ORDER, {"id": "o-1"})
        first = SqliteRepositoryDriver(self.path)
        first.execute(ORDER, "create", key)
        first.close()

        second = self.open()

        with self.assertRaises(DriverError) as caught:
            second.execute(ORDER, "create", key)
        self.assertIn("create conflicts", str(caught.exception))

    def test_close_is_idempotent(self):
        driver = SqliteRepositoryDriver(self.path)
        driver.close()
        driver.close()          # must not raise


class OutboxRecordTest(DriverTestCase):
    """`record_emission` (issue #102, D1/D2 — revised, see the schema
    comment above `drivers._CREATE_OUTBOX_TABLE`): the same `{emission_id,
    event, payload}` dict the interpreter's in-memory `outbox` already
    holds, persisted so it survives the process. `seq` (sqlite's own
    AUTOINCREMENT), not `emission_id`, is the row's identity — `emission_id`
    is a per-Interpreter counter (interp.py), not a store-wide dedupe key.
    """

    def test_a_recorded_emission_is_seen_by_drain(self):
        driver = self.open()
        driver.record_emission({"emission_id": "step.emit#1",
                                "event": "entity.event.orderPlaced",
                                "payload": {"id": "o-1"}})

        drained = driver.drain_outbox()
        self.assertEqual(1, len(drained))
        self.assertEqual("step.emit#1", drained[0]["emission_id"])
        self.assertEqual("entity.event.orderPlaced", drained[0]["event"])
        self.assertEqual({"id": "o-1"}, drained[0]["payload"])
        self.assertIn("seq", drained[0])

    def test_a_repeated_emission_id_is_two_distinct_rows_not_a_conflict(self):
        """The bug this schema fixes (measured 2026-08-24): two separate
        `lnpl run` invocations of the same document reproduce the same
        `emission_id` for their first emission of a given effect — that is
        two distinct emissions, not a redelivery, so a second write under
        the same `emission_id` must succeed, not conflict."""
        driver = self.open()
        emission = {"emission_id": "step.emit#1", "event": "E", "payload": {}}
        driver.record_emission(emission)

        driver.record_emission(emission)  # must not raise

        drained = driver.drain_outbox()
        self.assertEqual(2, len(drained))
        self.assertEqual(["step.emit#1", "step.emit#1"],
                         [e["emission_id"] for e in drained])
        self.assertNotEqual(drained[0]["seq"], drained[1]["seq"])

    def test_a_recorded_emission_survives_the_driver_that_wrote_it(self):
        first = SqliteRepositoryDriver(self.path)
        first.record_emission({"emission_id": "step.emit#1", "event": "E",
                               "payload": {"x": 1}})
        first.close()

        second = self.open()

        self.assertEqual(1, len(second.drain_outbox()))


class OutboxDrainTest(DriverTestCase):
    """`drain_outbox` (issue #102, D3 revised): undelivered rows, `seq`
    ascending (insertion order — also the monotonic cursor t103's SSE
    surface needs), `--limit` capped."""

    def _record(self, driver, n):
        for i in range(1, n + 1):
            driver.record_emission({"emission_id": "step.emit#%d" % i,
                                    "event": "E", "payload": {"i": i}})

    def test_drain_orders_by_seq(self):
        driver = self.open()
        self._record(driver, 3)

        drained = driver.drain_outbox()
        self.assertEqual(["step.emit#1", "step.emit#2", "step.emit#3"],
                         [e["emission_id"] for e in drained])
        self.assertEqual(sorted(e["seq"] for e in drained),
                         [e["seq"] for e in drained])

    def test_drain_respects_limit(self):
        driver = self.open()
        self._record(driver, 3)

        drained = driver.drain_outbox(limit=1)
        self.assertEqual(["step.emit#1"], [e["emission_id"] for e in drained])

    def test_an_empty_outbox_drains_to_an_empty_list(self):
        """Boundary: no emissions ever recorded is a valid, non-error state
        (D1's status-marking model has nothing to mark yet), not an absent
        answer."""
        driver = self.open()

        self.assertEqual([], driver.drain_outbox())

    def test_drain_never_returns_a_delivered_emission(self):
        """D1: status marking, not deletion — `ack` is what removes a row
        from this view, and the removal is by `delivered_at`, not a DELETE."""
        driver = self.open()
        self._record(driver, 2)
        first_seq = driver.drain_outbox()[0]["seq"]
        driver.ack_outbox([first_seq])

        drained = driver.drain_outbox()
        self.assertEqual(["step.emit#2"], [e["emission_id"] for e in drained])


class OutboxAckTest(DriverTestCase):
    """`ack_outbox` (issue #102, D3 revised): addresses by `seq`, marks
    delivered, idempotent on a re-ack, and fails closed (naming the seq)
    before writing anything when any seq in the batch is unknown."""

    def test_ack_removes_the_emission_from_the_next_drain(self):
        driver = self.open()
        driver.record_emission({"emission_id": "step.emit#1", "event": "E",
                                "payload": {}})
        seq = driver.drain_outbox()[0]["seq"]

        driver.ack_outbox([seq])

        self.assertEqual([], driver.drain_outbox())

    def test_a_duplicate_ack_is_idempotent(self):
        driver = self.open()
        driver.record_emission({"emission_id": "step.emit#1", "event": "E",
                                "payload": {}})
        seq = driver.drain_outbox()[0]["seq"]
        driver.ack_outbox([seq])

        driver.ack_outbox([seq])  # must not raise

        self.assertEqual([], driver.drain_outbox())

    def test_an_unknown_seq_names_itself_and_fails_closed(self):
        driver = self.open()
        driver.record_emission({"emission_id": "step.emit#1", "event": "E",
                                "payload": {}})
        seq = driver.drain_outbox()[0]["seq"]
        no_such_seq = seq + 999

        with self.assertRaises(DriverError) as caught:
            driver.ack_outbox([seq, no_such_seq])
        self.assertIn(str(no_such_seq), str(caught.exception))

        # A caller must never learn "some of these worked" from a message
        # that only names the ones that did not — the known seq in the same
        # batch is untouched too.
        self.assertEqual(1, len(driver.drain_outbox()))


class OpenRepositoryTest(DriverTestCase):

    def test_fake_selects_the_interpreters_own_store(self):
        """`None` is the answer that means "the Interpreter builds its Fake" —
        the default path stays exactly what it was before this issue."""
        self.assertIsNone(open_repository("fake"))

    def test_sqlite_selects_the_file_backed_driver(self):
        driver = open_repository("sqlite:" + self.path)
        self.addCleanup(driver.close)

        self.assertIsInstance(driver, SqliteRepositoryDriver)

    def test_an_unknown_backend_names_the_token_and_the_accepted_set(self):
        with self.assertRaises(ValueError) as caught:
            open_repository("postgres://localhost/db")
        message = str(caught.exception)
        self.assertIn("postgres://localhost/db", message)
        for name in BACKENDS:
            self.assertIn(name, message)

    def test_an_empty_sqlite_path_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            open_repository("sqlite:")
        self.assertIn("sqlite:", str(caught.exception))

    def test_a_missing_parent_directory_names_the_path_it_received(self):
        """The operator sees the value they typed, not its resolved form —
        a resolved path they never wrote is a second thing to debug."""
        raw = os.path.join(self.dir, "no-such-dir", "store.db")

        with self.assertRaises(ValueError) as caught:
            open_repository("sqlite:" + raw)
        self.assertIn(raw, str(caught.exception))

    def test_an_unwritable_parent_directory_is_rejected_at_open(self):
        locked = os.path.join(self.dir, "locked")
        os.mkdir(locked)
        os.chmod(locked, stat.S_IRUSR | stat.S_IXUSR)
        self.addCleanup(os.chmod, locked, stat.S_IRWXU)
        raw = os.path.join(locked, "store.db")

        with self.assertRaises(ValueError) as caught:
            open_repository("sqlite:" + raw)
        self.assertIn(raw, str(caught.exception))


class ModuleShapeTest(unittest.TestCase):

    def test_the_module_does_not_import_the_interpreter(self):
        """`interp` imports `drivers`; the reverse would be a cycle that breaks
        the build — the same rule `repo_policy` states for itself."""
        import lnpl.drivers as drivers

        with open(drivers.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in ("from .interp", "from .backend", "from .cli",
                          "from lnpl.interp", "import interp"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()

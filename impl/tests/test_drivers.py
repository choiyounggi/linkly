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

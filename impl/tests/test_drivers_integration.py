"""Persistence across a process boundary — the claim "a real backend" makes.

Everything else in this issue's suite runs in one interpreter. That is enough to
show a driver is swappable and enough to show a row survives a run, but not
enough to show the store is real: an in-memory object also survives a run, and a
cached dict also answers a re-read. The only test that separates a real store
from a convincing one is a second OS process that shares nothing with the first
but the file.

So every case here shells out. The evidence is: process A writes, process A
exits, process B — a fresh interpreter, a fresh connection, a fresh everything —
sees what A did. And the same command against `--backend fake` does not, which
is what makes the first result about persistence rather than about the workflow.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

from lnpl.drivers import SqliteRepositoryDriver
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import row_key

from tests.fixtures import VALUE_INVENTORY

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IMPL = os.path.join(REPO, "impl")

# stock 9 minus quantity 4. `quantity` is supplied by the payload and has no
# default, so a run that never received the payload cannot produce this number.
INITIAL_STOCK = 9
QUANTITY = 4
REMAINING = INITIAL_STOCK - QUANTITY


class ProcessBoundaryTest(unittest.TestCase):

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.dir = box.name
        self.source = os.path.join(self.dir, "inventory.lnpl")
        with open(self.source, "w", encoding="utf-8") as fh:
            fh.write(VALUE_INVENTORY)
        self.payload_path = os.path.join(self.dir, "payload.json")
        with open(self.payload_path, "w", encoding="utf-8") as fh:
            json.dump({"id": "p-1", "stock": INITIAL_STOCK,
                       "quantity": QUANTITY}, fh)
        self.db = os.path.join(self.dir, "store.db")

    def lnpl(self, *extra):
        """Run `python -m lnpl run ...` in a brand-new process."""
        env = dict(os.environ, PYTHONPATH=IMPL)
        proc = subprocess.run(
            [sys.executable, "-m", "lnpl", "run", self.source,
             "--payload", self.payload_path, "--json", *extra],
            capture_output=True, text=True, env=env, timeout=120)
        return proc

    def product_entity_id(self):
        """Read the id from the compiled document rather than writing it down —
        a hardcoded `entity.product` would keep passing if the derivation
        changed, while the store it addresses moved."""
        doc = lower(parse(VALUE_INVENTORY), "inventory").to_document()
        return next(n["id"] for n in doc["nodes"]
                    if n["kind"] == "Entity" and n["name"] == "Product")

    # -- the evidence ------------------------------------------------------

    def test_a_first_process_completes_and_deducts_the_stock(self):
        proc = self.lnpl("--backend", "sqlite:" + self.db)

        self.assertEqual(0, proc.returncode, proc.stderr)
        result = json.loads(proc.stdout)["result"]
        self.assertEqual("completed", result["status"])
        self.assertTrue(os.path.isfile(self.db))

    def test_a_second_process_meets_the_first_processs_write(self):
        """The whole point. `Order` is created, never read, so the seed rule
        leaves it empty — and the only way the second process can conflict on
        it is if the first process's create outlived the first process."""
        first = self.lnpl("--backend", "sqlite:" + self.db)
        self.assertEqual(0, first.returncode, first.stderr)

        second = self.lnpl("--backend", "sqlite:" + self.db)

        self.assertEqual(1, second.returncode)
        self.assertIn("create conflicts",
                      json.loads(second.stdout)["result"]["failure_reason"])

    def test_the_fake_backend_does_not_do_that(self):
        """The negative control. Same command, same two processes, no store:
        both succeed. Without this line the conflict above would be evidence of
        a workflow that cannot run twice."""
        first = self.lnpl()
        second = self.lnpl()

        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)

    def test_the_stored_row_carries_the_value_the_first_process_wrote(self):
        """Key survival and value survival are different facts. The conflict
        above proves a row exists; only this proves `set` reached the disk."""
        self.assertEqual(0, self.lnpl("--backend", "sqlite:" + self.db).returncode)
        entity_id = self.product_entity_id()

        driver = SqliteRepositoryDriver(self.db)
        self.addCleanup(driver.close)
        row = driver.execute(entity_id, "read",
                             row_key(entity_id, {"id": "p-1"}))

        self.assertEqual(REMAINING, row["stock"])

    def test_a_fresh_store_runs_clean_again(self):
        """Separates "the store said no" from "the workflow is broken": the
        same command against an empty file completes."""
        self.assertEqual(0, self.lnpl("--backend", "sqlite:" + self.db).returncode)
        self.assertEqual(1, self.lnpl("--backend", "sqlite:" + self.db).returncode)

        elsewhere = os.path.join(self.dir, "second-store.db")

        self.assertEqual(0, self.lnpl("--backend", "sqlite:" + elsewhere).returncode)

    # -- error and boundary ------------------------------------------------

    def test_a_store_under_an_unwritable_directory_is_an_operator_error(self):
        locked = os.path.join(self.dir, "locked")
        os.mkdir(locked)
        os.chmod(locked, 0o500)
        self.addCleanup(os.chmod, locked, 0o700)
        blocked = os.path.join(locked, "store.db")

        proc = self.lnpl("--backend", "sqlite:" + blocked)

        self.assertEqual(2, proc.returncode)
        self.assertIn(blocked, proc.stderr)

    def test_an_empty_store_reads_nothing_rather_than_failing_to_open(self):
        """The boundary between "no store" and "an empty store". Both read
        nothing; neither is a crash, and they must not be confused — one is an
        operator error and the other is an ordinary failed run."""
        proc = self.lnpl("--backend", "sqlite:" + self.db, "--no-row")

        self.assertEqual(1, proc.returncode)
        self.assertIn("found no row",
                      json.loads(proc.stdout)["result"]["failure_reason"])
        self.assertTrue(os.path.isfile(self.db))

    def test_the_run_leaves_nothing_outside_its_own_directory(self):
        """The store goes where it was told and nowhere else — no stray
        journal or scratch file in the repository."""
        before = set(os.listdir(REPO))

        self.assertEqual(0, self.lnpl("--backend", "sqlite:" + self.db).returncode)

        self.assertEqual(before, set(os.listdir(REPO)))


if __name__ == "__main__":
    unittest.main()

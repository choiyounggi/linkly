"""Issue #120: `FakeRepository.rollback()` actually discards the writes made
since the matching `begin()`, instead of the no-op RFC-0032 previously
tolerated on `--backend fake` (docs/backends.md §5). `--backend fake` is the
suite's default backend, so a no-op rollback there meant the enforced
"one execution = one transaction" policy was silently false on the most
common path.

`FakeRepositoryTransactionTest` drives `begin`/`commit`/`rollback` directly
against the unit, including the one subtle case (D2, plan t120): the
snapshot has to go two dict levels deep, because RFC-0015's `set` mutates a
read row's dict *in place* and a read binds that exact object -- a
one-level-deep snapshot would share that same row dict with the live table,
so "restoring" it would restore a dict that was mutated right along with the
original.

`FakeBackendRollbackIntegrationTest` reuses `test_transactions.py`'s
`TWO_WRITES` fixture and `ContractTestCase` harness to prove the fix at the
`run_workflow` boundary, not just against the unit in isolation.
"""

import unittest

from lnpl.interp import FakeRepository, RunError

from tests.test_driver_contract import ContractTestCase
from tests.test_transactions import TWO_WRITES


class FakeRepositoryTransactionTest(unittest.TestCase):
    def test_rollback_discards_writes_made_after_begin(self):
        repo = FakeRepository()
        repo.begin()
        repo.execute("Order", "create", "o-1")
        self.assertIn("o-1", repo.rows.get("Order", {}))

        repo.rollback()

        self.assertNotIn("o-1", repo.rows.get("Order", {}))

    def test_rollback_discards_an_in_place_mutation_of_a_read_row(self):
        """The D2 case: a shallow (one-level) snapshot would share the row
        dict with the live table, so this in-place mutation would survive
        rollback even though it happened after `begin()`."""
        repo = FakeRepository(rows={"Product": {"p-1": {"stock": 5}}})
        repo.begin()

        row = repo.execute("Product", "read", "p-1")
        row["stock"] = 999

        self.assertEqual(999, repo.rows["Product"]["p-1"]["stock"])

        repo.rollback()

        self.assertEqual(5, repo.rows["Product"]["p-1"]["stock"])

    def test_commit_discards_the_snapshot_so_a_later_rollback_is_a_no_op(self):
        repo = FakeRepository()
        repo.begin()
        repo.execute("Order", "create", "o-1")
        repo.commit()

        repo.rollback()

        self.assertIn("o-1", repo.rows.get("Order", {}))

    def test_nested_begin_is_rejected(self):
        repo = FakeRepository()
        repo.begin()

        with self.assertRaises(RunError):
            repo.begin()

    def test_rollback_without_a_matching_begin_is_a_no_op(self):
        repo = FakeRepository(rows={"Product": {"p-1": {"stock": 5}}})

        repo.rollback()

        self.assertEqual(5, repo.rows["Product"]["p-1"]["stock"])

    def test_begin_then_rollback_on_an_empty_repo_raises_nothing(self):
        repo = FakeRepository()
        repo.begin()

        repo.rollback()

        self.assertEqual({}, repo.rows)


class FakeBackendRollbackIntegrationTest(ContractTestCase):
    """The `run_workflow` boundary, not just the unit in isolation (issue
    #120's role): a failed two-write workflow on `--backend fake` must not
    leave the first write behind, matching what sqlite already does
    (`test_transactions.test_sqlite_discards_the_first_write_when_the_second_fails`).
    """

    def test_a_failed_fake_backend_run_discards_the_first_write(self):
        repository = self._repository("fake")
        payload = {"id": "x-1"}
        repository.seed({"entity.order": {"entity.order#x-1": {"id": "x-1"}}})

        result, _ = self.execute(TWO_WRITES, payload, "fake", seed=False,
                                 repository=repository)

        self.assertEqual(result["status"], "failed")
        self.assertIsNone(repository.execute(
            "entity.product", "read", "entity.product#x-1"))


if __name__ == "__main__":
    unittest.main()

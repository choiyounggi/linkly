"""Optimistic version guard on the sqlite persist path (issue #92).

Concurrent read-modify-write on one row is lost-update territory: two runs
read the same row, both mutate their own copy, and whichever persists second
overwrites the first with no trace it happened (measured: 12 of 31 concurrent
increments lost with no guard). `SqliteRepositoryDriver` closes this with an
internal `_version` column no LNPL document, payload, or response ever names
-- `persist()` conditions its UPDATE on the version the read that produced
this row observed, and `rows_affected == 0` becomes a `DriverError` the
interpreter turns into an ordinary failed run (`docs/backends.md`'s
concurrency section).

Deterministic injection is the primary evidence here -- a competing write
forced between one run's read and its persist, single-threaded and
reproducible on every run. Real threads (`ThreadedIncrementTest`) only
confirm the same guarantee holds under actual OS scheduling.
"""

import os
import tempfile
import threading
import unittest

from lnpl.drivers import DriverError, SqliteRepositoryDriver
from lnpl.interp import Interpreter
from lnpl.lower import lower
from lnpl.parser import parse

COUNTER = "entity.counter"

INCREMENT = """capability postgres

entity Counter
    field
        id UUID
        value Integer

service CounterService
    policy
        timeout 5s
        retry 3

workflow Increment
    read counter
    set counter.value to counter.value + 1
"""


def compile_source(source, module="m"):
    return lower(parse(source), module).to_document()


def with_retry(n):
    """`INCREMENT` with its declared retry budget swapped for `n` (same
    substitution style as test_lower.py's policy-line replacements)."""
    return INCREMENT.replace("        retry 3\n", "        retry %d\n" % n)


class _OnceStolenDriver(SqliteRepositoryDriver):
    """Injects exactly one competing increment, on the first `read` this
    instance serves. Deterministic proof that a version conflict is possible
    and survivable, without depending on real thread scheduling to land it.
    """

    def __init__(self, path):
        super().__init__(path)
        self._stolen = False

    def execute(self, entity_id, operation, key):
        row = super().execute(entity_id, operation, key)
        if operation == "read" and not self._stolen:
            self._stolen = True
            thief = SqliteRepositoryDriver(self.path)
            try:
                thief_row = thief.execute(entity_id, operation, key)
                if thief_row is not None:
                    thief_row["value"] = thief_row["value"] + 1
                    thief.persist(entity_id, key, thief_row)
            finally:
                thief.close()
        return row


class DriverLevelConflictTest(unittest.TestCase):
    """The claim `persist()` makes on its own, beneath any workflow: a write
    against a version that changed since the read raises, it does not
    silently overwrite."""

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.path = os.path.join(box.name, "store.db")

    def _driver(self):
        driver = SqliteRepositoryDriver(self.path)
        self.addCleanup(driver.close)
        return driver

    def test_a_stale_version_is_rejected_not_overwritten(self):
        key = "entity.counter#c-1"
        seeder = self._driver()
        seeder.seed({COUNTER: {key: {"id": "c-1", "value": 0}}})

        reader = self._driver()
        row = reader.execute(COUNTER, "read", key)

        writer = self._driver()
        stolen = writer.execute(COUNTER, "read", key)
        stolen["value"] = 1
        writer.persist(COUNTER, key, stolen)

        row["value"] = row["value"] + 1
        with self.assertRaises(DriverError) as caught:
            reader.persist(COUNTER, key, row)
        self.assertIn("conflict", str(caught.exception))
        # The write that landed first is what a re-read sees -- reader's
        # stale attempt never reached the row.
        self.assertEqual(reader.execute(COUNTER, "read", key)["value"], 1)


def run_with_client_retry(interp, target, payload, retry_budget):
    """What a caller of a `policy retry`-declared workflow does on a
    conflict -- the "재조회-재시도" loop the plan calls for, reusing the
    contract as-is rather than inventing a new one.

    A single `WorkflowStep` is exactly one source line (`lower.py`'s
    `_step`), so a `read` and the `set` that follows it are always two
    separate steps: retrying the failing `set` step alone re-runs the same
    Assignment against the same stale binding and can never recover -- it
    never re-reads. What actually recovers a cross-step conflict is a fresh
    call to `run_workflow`, which re-reads from scratch. `policy retry`
    already declares these effects idempotent (RFC-0003 Sec Policy
    Enforcement), which is what makes that whole-call retry safe: nothing
    landed, so calling again is not a duplicate, and its own declared budget
    is what bounds how many times it is safe to try -- no new concept.
    """
    attempts = 0
    while True:
        attempts += 1
        result = interp.run_workflow(target, dict(payload))
        if result["status"] == "completed":
            return result, attempts
        if attempts > retry_budget or "conflict" not in (result["failure_reason"] or ""):
            return result, attempts


class WorkflowConflictTest(unittest.TestCase):
    """The interpreter layer: a conflict becomes an ordinary failed run with
    "conflict" in `failure_reason`, never a silent overwrite. Whether that
    surfaces to the caller as failed or is absorbed depends only on whether
    the caller retries within the declared `policy retry` budget."""

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.path = os.path.join(box.name, "store.db")

    def _seed(self, doc, target, initial):
        from lnpl.repo_policy import default_rows
        payload = {"id": "c-1", "value": initial}
        driver = SqliteRepositoryDriver(self.path)
        driver.seed(default_rows(doc, target, payload))
        driver.close()
        return payload

    def _driver(self):
        driver = _OnceStolenDriver(self.path)
        self.addCleanup(driver.close)
        return driver

    def test_retry_declared_recovers_from_the_same_conflict(self):
        budget = 3
        doc = compile_source(with_retry(budget))
        target = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        payload = self._seed(doc, target, 0)
        driver = self._driver()
        interp = Interpreter(doc, repository=driver)

        result, attempts = run_with_client_retry(interp, target, payload, budget)

        self.assertEqual(result["status"], "completed")
        self.assertIsNone(result["failure_reason"])
        self.assertEqual(attempts, 2)
        # thief's concurrent +1 landed (0 -> 1), then the retried call re-read
        # it and applied its own +1 on top (1 -> 2) -- neither increment lost.
        self.assertEqual(driver.execute(COUNTER, "read",
                                        "entity.counter#c-1")["value"], 2)

    def test_retry_budget_exactly_sufficient_for_one_conflict(self):
        """The boundary: a budget of exactly 1 (two total calls) against
        exactly one injected conflict. One fewer and this is
        `test_an_undeclared_retry_surfaces_the_conflict_as_a_failed_run`
        below."""
        budget = 1
        doc = compile_source(with_retry(budget))
        target = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        payload = self._seed(doc, target, 0)
        driver = self._driver()
        interp = Interpreter(doc, repository=driver)

        result, attempts = run_with_client_retry(interp, target, payload, budget)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(attempts, 2)

    def test_an_undeclared_retry_surfaces_the_conflict_as_a_failed_run(self):
        doc = compile_source(with_retry(0))
        target = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        payload = self._seed(doc, target, 0)
        driver = self._driver()

        result = Interpreter(doc, repository=driver).run_workflow(target, payload)

        self.assertEqual(result["status"], "failed")
        self.assertIn("conflict", result["failure_reason"])
        # the conflicting write is the only one that landed -- nothing was
        # silently lost, the run just reports it instead of masking it.
        self.assertEqual(driver.execute(COUNTER, "read",
                                        "entity.counter#c-1")["value"], 1)


class ThreadedIncrementTest(unittest.TestCase):
    """Real OS thread scheduling, confirming the mechanism the deterministic
    tests above already proved: N concurrent increments, retry declared,
    lose nothing."""

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.path = os.path.join(box.name, "store.db")

    def test_concurrent_increments_lose_nothing(self):
        from lnpl.repo_policy import default_rows

        n_workers = 10
        # Bounded, not unbounded (kb/antipatterns-unbounded-retry): worst case
        # every worker loses every race but the last, so n_workers - 1 extra
        # calls covers it with headroom.
        budget = n_workers
        doc = compile_source(with_retry(budget))
        target = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        payload = {"id": "c-1", "value": 0}
        seeder = SqliteRepositoryDriver(self.path)
        seeder.seed(default_rows(doc, target, payload))
        seeder.close()

        errors = []
        errors_lock = threading.Lock()

        def worker():
            driver = SqliteRepositoryDriver(self.path)
            try:
                interp = Interpreter(doc, repository=driver)
                result, _ = run_with_client_retry(interp, target, payload, budget)
                if result["status"] != "completed":
                    with errors_lock:
                        errors.append(result["failure_reason"])
            finally:
                driver.close()

        threads = [threading.Thread(target=worker) for _ in range(n_workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        final = SqliteRepositoryDriver(self.path)
        self.addCleanup(final.close)
        self.assertEqual(
            final.execute(COUNTER, "read", "entity.counter#c-1")["value"],
            n_workers)


if __name__ == "__main__":
    unittest.main()

"""One scenario set, two repository drivers, one set of assertions (issue #25).

A fake is only trustworthy while it passes the real thing's tests. So the cases
here never name a backend: each runs through `Interpreter` with the driver
swapped underneath and asserts the same observable both times. Anything the two
are allowed to differ on is not asserted here — it is asserted in
`test_drivers.py`, where sqlite-specific facts belong.

The last class is the sharper form of the same claim. Rather than checking two
runs against a written-down expectation, it checks them against *each other*:
same document, same payload, only the driver differs, and the run's observables
must be identical. That is the contract `--backend` promises — swap the store,
keep the semantics — and it is a claim no single-backend test can make.
"""

import os
import tempfile
import unittest

from lnpl.drivers import DriverError, SqliteRepositoryDriver
from lnpl.interp import (MASK, Clock, FakeCache, FakeRepository,
                        Interpreter)
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import default_rows

from tests.fixtures import GUARDED, SECRET_ACCOUNT, VALUE_INVENTORY

READ_ONLY = """capability postgres

entity Product
    field
        id UUID
        stock Integer

service Shop
    policy
        timeout 5s

workflow Look
    read product
"""

BACKENDS = ("fake", "sqlite")


def compile_source(source, module="m"):
    return lower(parse(source), module).to_document()


class ContractTestCase(unittest.TestCase):
    """Runs a workflow through whichever driver the case names.

    Every sqlite run gets its own file: a store shared across cases would let
    one case's writes decide another's outcome, and the resulting failure would
    point at the wrong test.
    """

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.dir = box.name
        self._stores = 0

    def _repository(self, backend):
        """A driver instance for either backend.

        The fake is injected explicitly rather than left to the Interpreter's
        default, so both backends get the same lifetime: one driver, reused
        across however many runs a case makes. Leaving the fake implicit would
        hand it a brand-new store per run, and cases about what survives a run
        would then be comparing lifetimes rather than drivers.
        `DefaultPathTest` covers the implicit path separately.
        """
        if backend == "fake":
            return FakeRepository()
        self._stores += 1
        driver = SqliteRepositoryDriver(
            os.path.join(self.dir, "store-%d.db" % self._stores))
        self.addCleanup(driver.close)
        return driver

    def execute(self, source, payload, backend, seed=True, repository=None,
                workflow=None):
        """-> (result, interpreter). `repository` reuses a driver across runs."""
        doc = compile_source(source)
        target = workflow or next(n["id"] for n in doc["nodes"]
                                  if n["kind"] == "Workflow")
        rows = default_rows(doc, target, payload) if seed else {}
        if repository is None:
            repository = self._repository(backend)
        # The Interpreter seeds the driver it is handed; seeding here too would
        # hide a driver that ignored the rows it was given.
        interp = Interpreter(doc, repo_rows=rows, repository=repository)
        return interp.run_workflow(target, payload), interp


class QueryContractTest(ContractTestCase):
    """RFC-0025 §7: `RepositoryDriver.query(entity_id) -> list[dict]`, ordered
    by row_key ascending, identical on both backends. No surface verb reaches
    this path yet (RFC-0025 §Motivation — `list` lands in a later task), so
    these cases call the driver directly, the same way
    `test_an_assignment_is_visible_after_the_run` above reaches `repo.execute`
    directly to check a fact `run_workflow` alone would not isolate.
    """

    def test_an_empty_table_returns_an_empty_list(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                repository = self._repository(backend)

                self.assertEqual(repository.query("entity.link"), [])

    def test_a_single_row_returns_a_list_of_one(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                repository = self._repository(backend)
                repository.seed({"entity.link":
                                 {"entity.link#1": {"id": "1", "clicks": 5}}})

                self.assertEqual(repository.query("entity.link"),
                                 [{"id": "1", "clicks": 5}])

    def test_reverse_insertion_order_still_sorts_by_row_key(self):
        """The forcing case: seeding out of key order is what actually tells
        insertion-order iteration and row_key-ordered iteration apart. A fake
        that just returned `dict.values()` would pass every other case here
        and still disagree with sqlite on this one."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                repository = self._repository(backend)
                # Inserted 2, 0, 1 — row_key ascending is "0", "1", "2".
                repository.seed({"entity.link": {
                    "2": {"id": "2", "clicks": 9},
                    "0": {"id": "0", "clicks": 5},
                    "1": {"id": "1", "clicks": 3},
                }})

                rows = repository.query("entity.link")

                self.assertEqual([row["id"] for row in rows], ["0", "1", "2"])

    def test_fake_and_sqlite_agree_on_order(self):
        """`DriverSwapEquivalenceTest`'s sharper claim, for `query` alone:
        same seed inserted out of key order, only the driver differs, and the
        returned list must match exactly — not just as a set."""
        seed = {"entity.link": {
            "2": {"id": "2", "clicks": 9},
            "0": {"id": "0", "clicks": 5},
            "1": {"id": "1", "clicks": 3},
        }}
        seen = {}
        for backend in BACKENDS:
            repository = self._repository(backend)
            repository.seed(seed)
            seen[backend] = repository.query("entity.link")

        self.assertEqual(seen["fake"], seen["sqlite"])
        self.assertEqual([row["id"] for row in seen["fake"]], ["0", "1", "2"])


class SharedContractTest(ContractTestCase):
    """The assertions that must hold identically on every driver."""

    def test_a_seeded_read_completes_and_binds_its_row(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                payload = {"id": "p-1", "stock": 9}

                result, _ = self.execute(READ_ONLY, payload, backend)

                self.assertEqual(result["status"], "completed")
                self.assertIsNone(result["failed_step"])

    def test_an_unseeded_read_fails_with_the_same_reason(self):
        """The forcing input for the repository dimension: with no row the
        store is what decides the outcome, so this is where two backends can
        actually disagree."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                result, _ = self.execute(READ_ONLY, {"id": "p-1"}, backend,
                                         seed=False)

                self.assertEqual(result["status"], "failed")
                self.assertIn("repository read found no row",
                              result["failure_reason"])

    def test_an_assignment_is_visible_after_the_run(self):
        """RFC-0015's `set` writes into the row a read bound. On the Fake that
        dict IS the stored row; on a real store it is a detached copy, so this
        passes only while the driver flushes the write back."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                repository = self._repository(backend)
                payload = {"id": "p-1", "stock": 9, "quantity": 4}

                result, interp = self.execute(VALUE_INVENTORY, payload, backend,
                                              repository=repository)

                self.assertEqual(result["status"], "completed")
                self.assertEqual(interp.repo.execute(
                    "entity.product", "read", "entity.product#p-1")["stock"], 5)

    def test_a_repeated_create_conflicts_with_the_same_message(self):
        """The rule "never retry a non-idempotent effect" is only testable
        while a create can fail, so both drivers must fail it the same way."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                repository = self._repository(backend)
                payload = {"id": "p-1", "stock": 9, "quantity": 1}
                self.execute(VALUE_INVENTORY, payload, backend,
                             repository=repository)

                result, _ = self.execute(VALUE_INVENTORY, payload, backend,
                                         repository=repository)

                self.assertEqual(result["status"], "failed")
                self.assertIn("create conflicts", result["failure_reason"])

    def test_an_empty_payload_fails_the_same_way(self):
        """The boundary input: no id, so the seed key falls back to the '-'
        sentinel and nothing the workflow reads is where it looks."""
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                result, _ = self.execute(READ_ONLY, {}, backend, seed=False)

                self.assertEqual(result["status"], "failed")
                self.assertIn("repository read found no row",
                              result["failure_reason"])

    def test_masking_holds_on_every_backend(self):
        """Swapping the store must not change which values reach a channel.
        The plain `label` is the negative control: a channel missing it was
        never captured, and the secret's absence there would prove nothing."""
        secret = "4111111111111111"
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                payload = {"id": "a-1", "label": "primary", "cardSecret": secret}

                result, interp = self.execute(SECRET_ACCOUNT, payload, backend)

                self.assertEqual(result["status"], "completed")
                logged = str(interp.trace.to_dict())
                self.assertNotIn(secret, logged)
                self.assertIn("primary", logged)          # control present
                self.assertIn(MASK, logged)


class DriverSwapEquivalenceTest(ContractTestCase):
    """Same document, same payload, only the driver differs — the observables
    must match. This is the claim `--backend` makes."""

    def observe(self, source, payload, seed=True):
        seen = {}
        for backend in BACKENDS:
            result, interp = self.execute(source, payload, backend, seed=seed)
            seen[backend] = {
                "status": result["status"],
                "failed_step": result["failed_step"],
                "failure_reason": result["failure_reason"],
                "skipped": result["skipped"],
                "steps": [entry["step"] for entry in result["steps"]],
                "effects": [child.kind for child in interp.trace.root.children[0].children]
                           if interp.trace.root and interp.trace.root.children else [],
            }
        return seen["fake"], seen["sqlite"]

    def test_a_completing_run_is_observationally_identical(self):
        fake, sqlite = self.observe(VALUE_INVENTORY,
                                    {"id": "p-1", "stock": 9, "quantity": 4})

        self.assertEqual(fake, sqlite)
        self.assertEqual(fake["status"], "completed")

    def test_a_failing_run_is_observationally_identical(self):
        fake, sqlite = self.observe(READ_ONLY, {"id": "p-1"}, seed=False)

        self.assertEqual(fake, sqlite)
        self.assertEqual(fake["status"], "failed")

    def test_a_guard_skip_is_observationally_identical(self):
        """A skipped step is a signal orthogonal to status, and it is derived
        above the driver — so it must survive the swap untouched."""
        fake, sqlite = self.observe(VALUE_INVENTORY,
                                    {"id": "p-1", "stock": 1, "quantity": 9})

        self.assertEqual(fake, sqlite)
        self.assertTrue(fake["skipped"])


class _FailingRepository(FakeRepository):
    """A driver that fails the way a real one does — network gone, disk full,
    permissions revoked. Injected because sqlite is too reliable to produce
    these on demand, and the translation has to hold for every driver, not
    only for the one whose failures we can provoke."""

    def __init__(self, failing="execute"):
        super().__init__(None)
        self.failing = failing

    def execute(self, entity_id, operation, key):
        if self.failing == "execute":
            raise DriverError("the store is unreachable")
        return super().execute(entity_id, operation, key)

    def persist(self, entity_id, key, row):
        if self.failing == "persist":
            raise DriverError("the store rejected the write")
        return super().persist(entity_id, key, row)


class _FailingCache(FakeCache):

    def set(self, key, value, ttl_ms):
        raise DriverError("the cache is unreachable")


class _StealingSqliteDriver(SqliteRepositoryDriver):
    """Lands one competing write on the first `read` this instance serves --
    deterministic proof that a real sqlite version conflict (issue #92)
    translates through the same site as every other `DriverError`, without
    depending on real thread scheduling to produce one."""

    def __init__(self, path):
        super().__init__(path)
        self._stolen = False

    def execute(self, entity_id, operation, key):
        row = super().execute(entity_id, operation, key)
        if operation == "read" and not self._stolen and row is not None:
            self._stolen = True
            thief = SqliteRepositoryDriver(self.path)
            try:
                thief_row = thief.execute(entity_id, operation, key)
                thief_row["stock"] = thief_row["stock"] - 1
                thief.persist(entity_id, key, thief_row)
            finally:
                thief.close()
        return row


class DriverFaultTranslationTest(ContractTestCase):
    """A driver fault must arrive as an ordinary failed run.

    This is what lets `--backend` be a swap rather than a rewrite: the CLI's
    rc, the served status code, and the result shape are all derived from
    `status`/`failure_reason`, so a DriverError that escaped instead of being
    translated would turn a bad database into a traceback at every one of them.
    Each case names one translation site; without them the three try/except
    blocks could be deleted and every other test would stay green.
    """

    def test_a_failing_read_becomes_a_failed_run(self):
        doc = compile_source(READ_ONLY)
        target = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        interp = Interpreter(doc, repository=_FailingRepository("execute"))

        result = interp.run_workflow(target, {"id": "p-1"})

        self.assertEqual(result["status"], "failed")
        self.assertIn("the store is unreachable", result["failure_reason"])

    def test_a_failing_persist_becomes_a_failed_run(self):
        """The assignment flush is a driver call like any other, and it happens
        after the step's visible work — so an untranslated fault here is the
        one most likely to look like a crash rather than a failure."""
        doc = compile_source(VALUE_INVENTORY)
        target = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        payload = {"id": "p-1", "stock": 9, "quantity": 4}
        repository = _FailingRepository("persist")
        interp = Interpreter(doc, repo_rows=default_rows(doc, target, payload),
                             repository=repository)

        result = interp.run_workflow(target, payload)

        self.assertEqual(result["status"], "failed")
        self.assertIn("the store rejected the write", result["failure_reason"])

    def test_a_failing_cache_write_becomes_a_failed_run(self):
        doc = compile_source(GUARDED)
        target = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        payload = {"id": "u-1", "email": "a@b.co"}
        interp = Interpreter(doc, repo_rows=default_rows(doc, target, payload),
                             cache=_FailingCache(Clock()))

        result = interp.run_workflow(target, payload)

        self.assertEqual(result["status"], "failed")
        self.assertIn("the cache is unreachable", result["failure_reason"])

    def test_a_persist_conflict_becomes_a_failed_run_naming_it(self):
        """The one translation site this issue adds: `rows_affected == 0` on
        the versioned UPDATE is a `DriverError` like any other, so it reaches
        the caller the same way -- an ordinary failed run naming the
        conflict, not a silent overwrite and not a traceback (issue #92)."""
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        driver = _StealingSqliteDriver(os.path.join(box.name, "store.db"))
        self.addCleanup(driver.close)
        doc = compile_source(VALUE_INVENTORY)
        target = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        payload = {"id": "p-1", "stock": 9, "quantity": 4}
        interp = Interpreter(doc, repo_rows=default_rows(doc, target, payload),
                             repository=driver)

        result = interp.run_workflow(target, payload)

        self.assertEqual(result["status"], "failed")
        self.assertIn("conflict", result["failure_reason"])

    def test_a_driver_error_never_escapes_the_run(self):
        """The guarantee stated directly: whatever the driver raises, the
        caller gets a result, not an exception."""
        doc = compile_source(READ_ONLY)
        target = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        interp = Interpreter(doc, repository=_FailingRepository("execute"))

        try:
            result = interp.run_workflow(target, {"id": "p-1"})
        except DriverError:
            self.fail("DriverError escaped run_workflow instead of being "
                      "translated into a failed result")
        self.assertEqual(result["status"], "failed")


class _RecordingRepository(FakeRepository):
    """Records every flush so a test can assert which row was addressed."""

    def __init__(self):
        super().__init__(None)
        self.persisted = []

    def persist(self, entity_id, key, row):
        self.persisted.append((entity_id, key))
        return super().persist(entity_id, key, row)


class AssignmentFlushTargetTest(ContractTestCase):
    """Which row the flush addresses, and what happens when there is none.

    The interpreter maps a binding back to its Entity through
    `repo_policy.binding_name`, the same function a read binds under. If that
    map were wrong the Fake would not notice — its bound dict is the stored row
    either way — so only a real store would show the damage, as a write landing
    under the wrong key or under none at all.
    """

    def test_the_flush_addresses_the_row_the_read_bound(self):
        doc = compile_source(VALUE_INVENTORY)
        target = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        payload = {"id": "p-1", "stock": 9, "quantity": 4}
        repository = _RecordingRepository()

        result = Interpreter(doc, repo_rows=default_rows(doc, target, payload),
                             repository=repository).run_workflow(target, payload)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(repository.persisted,
                         [("entity.product", "entity.product#p-1")])

    def test_a_binding_with_no_entity_behind_it_fails_the_run(self):
        """The compiler cannot emit this — it refuses `set input.x` and an
        assignment to an unread entity — so it can only arrive on a document
        built outside the compiler. It must still not pass silently: a skipped
        flush keeps the write on the Fake and drops it on a real store, which
        is the two backends disagreeing about the operation this flush exists
        for.
        """
        doc = compile_source(VALUE_INVENTORY)
        target = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        payload = {"id": "p-1", "stock": 9, "quantity": 4}
        rows = default_rows(doc, target, payload)
        # A read binds its row by node id without consulting the node's kind,
        # while the binding -> entity map filters on kind. Demoting the kind
        # therefore leaves the read (and so the guards, and so the assignment)
        # working while the map comes up empty — the one shape that reaches
        # this branch. Renaming the entity instead does NOT: the guard reading
        # `product.stock` would resolve to nothing, go false, and skip the
        # assignment before it ran.
        for node in doc["nodes"]:
            if node["kind"] == "Entity" and node["name"] == "Product":
                node["kind"] = "EntityFromSomewhereElse"
        repository = _RecordingRepository()

        result = Interpreter(doc, repo_rows=rows,
                             repository=repository).run_workflow(target, payload)

        self.assertEqual(result["status"], "failed")
        self.assertIn("names no declared entity", result["failure_reason"])
        self.assertEqual(repository.persisted, [])


class DefaultPathTest(ContractTestCase):
    """The untouched path stays untouched: no driver named, nothing changes."""

    def test_no_repository_argument_still_builds_the_fake(self):
        from lnpl.interp import FakeCache, FakeRepository

        doc = compile_source(READ_ONLY)
        interp = Interpreter(doc)

        self.assertIsInstance(interp.repo, FakeRepository)
        self.assertIsInstance(interp.cache, FakeCache)

    def test_the_new_arguments_are_keyword_only(self):
        """Appended after a bare `*`, so a stale positional call fails loudly
        instead of binding a driver to `correlation_id`."""
        import inspect

        parameters = inspect.signature(Interpreter.__init__).parameters

        for name in ("repository", "cache"):
            self.assertEqual(parameters[name].kind,
                             inspect.Parameter.KEYWORD_ONLY)

    def test_the_positional_prefix_is_unchanged(self):
        import inspect

        positional = [name for name, p in
                      inspect.signature(Interpreter.__init__).parameters.items()
                      if p.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD]

        self.assertEqual(positional,
                         ["self", "document", "clock", "repo_rows",
                          "correlation_id"])


if __name__ == "__main__":
    unittest.main()

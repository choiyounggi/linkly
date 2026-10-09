"""Issue #113: a repository create-conflict maps to 409, not 500 -- and the
verdict is TYPE-based (`ConflictError` -> `run_workflow`'s `failure_kind`
field), never a `failure_reason` string match. `map_result` (wsgi.py) only
ever sees the result dict, never the exception (D2) -- M6's mistake
(`failure_reason.startswith("deadline")`) is exactly what this issue forbids
repeating. M6/M7/M8 stay byte-identical (D3); M8a sits between M7 and M8
(D4).
"""

import json
import os
import tempfile
import unittest

from lnpl.drivers import (DriverError, SqliteRepositoryDriver,
                          WriteConflictError)
from lnpl.interp import FakeRepository, Interpreter
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.wsgi import make_wsgi_app, map_result

from tests.fixtures import VALUE_PAYMENT
from tests.test_driver_concurrency import _OnceStolenDriver
from tests.test_wsgi_contract import call_wsgi

PAYMENT_PATH = "/payment-service/approve"


def compile_source(source, module="mod"):
    return lower(parse(source), module).to_document()


def result_stub(status="completed", failed_step=None, failure_reason=None,
                steps=(), skipped=(), failure_kind=None):
    """A `run_workflow` result with only the keys `map_result` reads --
    mirrors `test_serve.py`'s `result_stub`, plus the new `failure_kind`."""
    result = {"status": status, "failed_step": failed_step,
              "failure_reason": failure_reason, "steps": list(steps),
              "skipped": list(skipped), "bindings": {}, "duration_ms": 5,
              "correlation_id": "cid-test"}
    if failure_kind is not None:
        result["failure_kind"] = failure_kind
    return result


class MapResultConflictTest(unittest.TestCase):
    """M8a, ordered after M7 and before M8 (D4)."""

    def test_m8a_conflict_kind_maps_to_409(self):
        result = result_stub(
            status="failed", failed_step="create payment",
            failure_reason="repository create conflicts: payment#1 already exists",
            failure_kind="conflict",
            steps=[{"step": "create payment", "effects": ["RepositoryCall"]}])
        self.assertEqual((409, "conflict"), map_result(result))

    def test_conflict_verdict_survives_a_reworded_failure_reason(self):
        """The decisive proof (issue #113, D2): reword `failure_reason`
        completely, keep `failure_kind` -- 409 must still hold. A verdict
        that depends on the string breaks the moment the wording does (M6's
        mistake); a verdict that depends on the type does not."""
        result = result_stub(
            status="failed", failed_step="create payment",
            failure_reason="a totally reworded message with no 'conflict' "
                           "substring anywhere in it",
            failure_kind="conflict",
            steps=[{"step": "create payment", "effects": ["RepositoryCall"]}])
        self.assertEqual((409, "conflict"), map_result(result))

    def test_missing_failure_kind_falls_back_to_m8_500(self):
        """Boundary: a failure with no `failure_kind` (every failure this
        issue does not know about) keeps M8's catch-all, unchanged."""
        result = result_stub(
            status="failed", failed_step="cache link",
            failure_reason="cache set without a TTL",
            steps=[{"step": "cache link", "effects": ["CacheAccess"]}])
        self.assertEqual((500, "workflow-failed"), map_result(result))

    def test_m6_and_m7_are_unaffected_byte_for_byte(self):
        """Regression (D3): M6/M7 keep their exact tuples -- M8a is
        additive, inserted between M7 and M8, never ahead of either."""
        deadline_result = result_stub(
            status="failed", failed_step="update",
            failure_reason="deadline exceeded after step 'update'",
            failure_kind="deadline",
            steps=[{"step": "update", "effects": ["RepositoryCall"]}])
        self.assertEqual((504, "deadline-exceeded"), map_result(deadline_result))

        validation_result = result_stub(
            status="failed", failed_step="validate input",
            failure_reason="field 'slug' does not match Slug's pattern",
            steps=[{"step": "validate input", "effects": ["Validation"]}])
        self.assertEqual((400, "validation-failed"), map_result(validation_result))


class ConflictFailureKindBothBackendsTest(unittest.TestCase):
    """`failure_kind == "conflict"` on a REAL create-conflict, for both
    `--backend` values (D1's `ConflictError`, D2's structured field) -- not
    just the hand-built `map_result` stub above."""

    def _run_twice(self, repository):
        doc = compile_source(VALUE_PAYMENT)
        target = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        payload = {"id": "p-conflict-1", "amount": 500}
        Interpreter(doc, repository=repository).run_workflow(target, payload)
        return Interpreter(doc, repository=repository).run_workflow(target, payload)

    def test_fake_backend_sets_conflict_failure_kind(self):
        result = self._run_twice(FakeRepository())
        self.assertEqual("failed", result["status"])
        self.assertEqual("conflict", result.get("failure_kind"))

    def test_sqlite_backend_sets_conflict_failure_kind(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        driver = SqliteRepositoryDriver(os.path.join(box.name, "store.db"))
        self.addCleanup(driver.close)
        result = self._run_twice(driver)
        self.assertEqual("failed", result["status"])
        self.assertEqual("conflict", result.get("failure_kind"))

    def test_non_conflict_driver_error_carries_no_failure_kind(self):
        """Negative control: a `DriverError` that is NOT a `ConflictError`
        must not be mistaken for a conflict -- the `isinstance` check
        discriminates by type, it does not treat every `DriverError` as a
        conflict."""
        class _AlwaysFailsRepository(FakeRepository):
            def execute(self, entity_id, operation, key):
                if operation == "create":
                    raise DriverError("the store is unreachable")
                return super().execute(entity_id, operation, key)

        doc = compile_source(VALUE_PAYMENT)
        target = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        interp = Interpreter(doc, repository=_AlwaysFailsRepository())

        result = interp.run_workflow(target, {"id": "p-1", "amount": 500})

        self.assertEqual("failed", result["status"])
        self.assertNotIn("failure_kind", result)

    def test_success_never_carries_a_failure_kind_key(self):
        """Boundary: M9 success carries no `failure_kind` key at all, not
        even `None` -- additive-and-non-destructive, same precedent
        `response`/`emissions` (issues #96/#102) already set."""
        doc = compile_source(VALUE_PAYMENT)
        target = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        interp = Interpreter(doc, repository=FakeRepository())

        result = interp.run_workflow(target, {"id": "p-1", "amount": 500})

        self.assertEqual("completed", result["status"])
        self.assertNotIn("failure_kind", result)


class ConflictOverWsgiTest(unittest.TestCase):
    """The full path: HTTP POST -> `run_workflow` -> `map_result` -> 409, via
    the plain WSGI callable (no socket), mirroring `test_wsgi_contract.py`'s
    `call_wsgi` convention."""

    def setUp(self):
        self.repo = FakeRepository()
        doc = compile_source(VALUE_PAYMENT)
        self.app = make_wsgi_app(doc, repository_factory=lambda: self.repo)

    def _post(self, payload):
        return call_wsgi(self.app, "POST", PAYMENT_PATH,
                         body=json.dumps(payload).encode("utf-8"))

    def test_first_create_completes_second_create_conflicts_with_409(self):
        payload = {"id": "p-http-1", "amount": 500}

        first_status, _, first_body = self._post(payload)
        second_status, _, second_body = self._post(payload)

        self.assertEqual(200, first_status)
        self.assertEqual("completed", first_body["status"])
        self.assertEqual(409, second_status)
        self.assertEqual("conflict", second_body["code"])
        self.assertIn("already exists", second_body["detail"])

    def test_a_conflict_response_is_well_formed_problem_json(self):
        payload = {"id": "p-http-2", "amount": 500}
        self._post(payload)

        status, headers, body = self._post(payload)

        self.assertEqual(409, status)
        self.assertEqual(409, body["status"])
        self.assertEqual("conflict", body["code"])
        self.assertIn("title", body)
        self.assertIn("correlation_id", body)


# Issue #201: an optimistic-version write conflict (issue #92) is its own
# kind, `write-conflict` -> 409, told apart from the create conflict above by
# TYPE (`WriteConflictError`), never by `failure_reason`'s wording. The entity
# field is `value` because `_OnceStolenDriver` increments exactly that field.

WRITE_CONFLICT_SRC = """capability postgres

entity Widget
    field
        id UUID
        value Integer

service WidgetService
    policy
        timeout 5s
        retry 0

workflow Bump
    read widget
    set widget.value to widget.value + 1
"""

# The same increment inside a `parallel` block -- `run_workflow`'s second
# translation site (the block's result loop), not the sequential one.
PARALLEL_WRITE_CONFLICT_SRC = WRITE_CONFLICT_SRC.replace(
    "    set widget.value to widget.value + 1\n",
    "    parallel\n"
    "        set widget.value to widget.value + 1\n"
    "    merge\n")

WIDGET_BUMP_SRC = """capability postgres

entity Widget
    field
        id UUID
        value Integer

event WidgetBumped

service WidgetService
    policy
        timeout 5s
        retry 0

workflow Bump
    read widget
    emit widgetBumped with widget.value
    set widget.value to widget.value + 1
"""

WIDGET_BUMP_PATH = "/widget-service/bump"
BUMP_STEP = "set widget.value to widget.value + 1"
OLD_CONFLICT_TEXT = ("write conflict: row changed since read "
                     "(entity.widget entity.widget#w-synthetic)")


class MapResultWriteConflictTest(unittest.TestCase):
    """M8c, ordered after M8b and before M8."""

    def test_m8c_write_conflict_kind_maps_to_409(self):
        result = result_stub(
            status="failed", failed_step=BUMP_STEP,
            failure_reason=OLD_CONFLICT_TEXT,
            failure_kind="write-conflict",
            steps=[{"step": BUMP_STEP, "effects": ["Assignment"]}])
        self.assertEqual((409, "write-conflict"), map_result(result))

    def test_write_conflict_verdict_survives_a_reworded_failure_reason(self):
        result = result_stub(
            status="failed", failed_step=BUMP_STEP,
            failure_reason="a totally reworded message with no such "
                           "substring anywhere in it",
            failure_kind="write-conflict",
            steps=[{"step": BUMP_STEP, "effects": ["Assignment"]}])
        self.assertEqual((409, "write-conflict"), map_result(result))

    def test_the_old_text_without_a_kind_still_falls_back_to_m8_500(self):
        """Negative control: the old literal message with NO `failure_kind`
        (what an untyped `DriverError` produces) stays 500 -- the verdict
        never reads the message."""
        result = result_stub(
            status="failed", failed_step=BUMP_STEP,
            failure_reason=OLD_CONFLICT_TEXT,
            steps=[{"step": BUMP_STEP, "effects": ["Assignment"]}])
        self.assertEqual((500, "workflow-failed"), map_result(result))


def _seed_widget(path, doc, target, payload):
    from lnpl.repo_policy import default_rows
    seeder = SqliteRepositoryDriver(path)
    seeder.seed(default_rows(doc, target, payload))
    seeder.close()


class _RaisesOnPersist(SqliteRepositoryDriver):
    """A driver whose every `persist` raises `self.error` -- how an external
    driver that has (or has not) opted into `WriteConflictError` looks to
    the interpreter, with a message of the test's choosing."""

    error = None

    def persist(self, entity_id, key, row):
        raise self.error


class WriteConflictFailureKindTest(unittest.TestCase):
    """`failure_kind == "write-conflict"` on a REAL version conflict (sqlite
    -- `fake` is one in-memory process, this conflict cannot exist there)."""

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.path = os.path.join(box.name, "store.db")

    def _run(self, source, driver_factory):
        doc = compile_source(source)
        target = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        payload = {"id": "w-1", "value": 0}
        _seed_widget(self.path, doc, target, payload)
        driver = driver_factory(self.path)
        self.addCleanup(driver.close)
        return Interpreter(doc, repository=driver).run_workflow(target, payload)

    def test_sqlite_backend_sets_write_conflict_failure_kind(self):
        result = self._run(WRITE_CONFLICT_SRC, _OnceStolenDriver)

        self.assertEqual("failed", result["status"])
        self.assertEqual(BUMP_STEP, result["failed_step"])
        self.assertEqual("write-conflict", result.get("failure_kind"))

    def test_a_conflict_inside_a_parallel_block_sets_the_same_kind(self):
        result = self._run(PARALLEL_WRITE_CONFLICT_SRC, _OnceStolenDriver)

        self.assertEqual("failed", result["status"])
        self.assertEqual("write-conflict", result.get("failure_kind"))

    def test_a_typed_error_with_a_reworded_message_is_still_write_conflict(self):
        class _Reworded(_RaisesOnPersist):
            error = WriteConflictError("someone else got there first")

        result = self._run(WRITE_CONFLICT_SRC, _Reworded)

        self.assertEqual("write-conflict", result.get("failure_kind"))
        self.assertNotIn("write conflict", result["failure_reason"])

    def test_a_plain_driver_error_with_the_old_text_carries_no_kind(self):
        """An external driver that still raises a plain `DriverError` with
        the very text the built-in one used keeps today's untyped failure --
        no string matching promotes it."""
        class _Untyped(_RaisesOnPersist):
            error = DriverError(OLD_CONFLICT_TEXT)

        result = self._run(WRITE_CONFLICT_SRC, _Untyped)

        self.assertEqual("failed", result["status"])
        self.assertNotIn("failure_kind", result)
        self.assertEqual((500, "workflow-failed"), map_result(result))


class WriteConflictOverWsgiTest(unittest.TestCase):
    """HTTP POST -> a genuine version conflict -> 409 `write-conflict`, and
    the losing run's write and its outbox emission are both rolled back."""

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.path = os.path.join(box.name, "store.db")
        self.doc = compile_source(WIDGET_BUMP_SRC)
        self.target = next(n["id"] for n in self.doc["nodes"]
                           if n["kind"] == "Workflow")
        self.event_id = next(n["id"] for n in self.doc["nodes"]
                             if n["kind"] == "Event")

    def _post(self, driver_factory, payload):
        _seed_widget(self.path, self.doc, self.target, payload)
        app = make_wsgi_app(self.doc, repository_factory=driver_factory)
        return call_wsgi(app, "POST", WIDGET_BUMP_PATH,
                         body=json.dumps(payload).encode("utf-8"))

    def test_a_concurrent_write_is_409_with_rollback(self):
        payload = {"id": "w-http-1", "value": 0}

        status, _headers, body = self._post(
            lambda: _OnceStolenDriver(self.path), payload)

        self.assertEqual(409, status)
        self.assertEqual(409, body["status"])
        self.assertEqual("write-conflict", body["code"])
        self.assertEqual(BUMP_STEP, body["failed_step"])
        self.assertIn("title", body)
        checker = SqliteRepositoryDriver(self.path)
        self.addCleanup(checker.close)
        row = checker.execute("entity.widget", "read", "entity.widget#w-http-1")
        # the thief's +1 only -- this run's own +1 never landed
        self.assertEqual(1, row["value"])
        # the emit that ran before the failed `set` was rolled back too
        self.assertEqual([], checker.read_outbox(self.event_id))

    def test_without_a_conflict_the_same_request_completes(self):
        """Boundary: the plain driver, no competing write -- 200, the
        increment and the emission both land."""
        payload = {"id": "w-http-2", "value": 0}

        status, _headers, body = self._post(
            lambda: SqliteRepositoryDriver(self.path), payload)

        self.assertEqual(200, status)
        self.assertEqual("completed", body["status"])
        checker = SqliteRepositoryDriver(self.path)
        self.addCleanup(checker.close)
        row = checker.execute("entity.widget", "read", "entity.widget#w-http-2")
        self.assertEqual(1, row["value"])
        self.assertEqual(1, len(checker.read_outbox(self.event_id)))

    def test_a_plain_driver_error_with_the_old_text_is_still_500(self):
        class _Untyped(_RaisesOnPersist):
            error = DriverError(OLD_CONFLICT_TEXT)

        status, _headers, body = self._post(
            lambda: _Untyped(self.path), {"id": "w-http-3", "value": 0})

        self.assertEqual(500, status)
        self.assertEqual("workflow-failed", body["code"])

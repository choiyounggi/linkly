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

from lnpl.drivers import DriverError, SqliteRepositoryDriver
from lnpl.interp import FakeRepository, Interpreter
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.wsgi import make_wsgi_app, map_result

from tests.fixtures import VALUE_PAYMENT
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

"""Issue #128: M6 (deadline) moves from string-matching to a typed
`failure_kind`, the same standard issue #113 set for M8a's conflict check.
`interp.py` raises a deadline failure from two sites -- P1 (`run_workflow`,
after a step completes) and P2 (`_run_step`'s entry guard, before a step
starts) -- and both now stamp `result["failure_kind"] = "deadline"`. `M7`,
`M8a`, and `M8` are untouched (issue #113 D3): this file pins their output
byte-identical, same convention as `test_conflict_409.py`'s regression class.
"""

import unittest

from lnpl.interp import Interpreter
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import row_key
from lnpl.wsgi import map_result

# P1: each step costs 6ms (1ms per effect + the default 5ms step advance).
# 3 steps x 6ms = 18ms, past a 15ms deadline -- but only after "update
# payment" completes (12ms, after step 2, is still under it). The deadline
# trips in `run_workflow`'s post-step check.
P1_SRC = """
capability postgres
entity Payment
    field
        id UUID
        amountCents Integer
service SlowService
    policy
        timeout 15ms
workflow Crawl
    validate payment
    find payment
    update payment
"""

# P2: 2 steps, same 6ms-per-step cost, against a 6ms deadline -- after "find
# payment" the clock lands exactly ON the deadline (6 == 6, not `>`), so P1's
# post-step check does not fire; `_run_step`'s entry guard for "update
# payment" then sees `now >= deadline` and raises before that step's effects
# ever run. This is the case the plan calls out: fix only P1 and this path
# quietly falls through to a bare 500.
P2_SRC = """
capability postgres
entity Payment
    field
        id UUID
        amountCents Integer
service SlowService
    policy
        timeout 6ms
workflow Peek
    find payment
    update payment
"""

PAYLOAD = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301", "amountCents": 500}


def compile_source(source, module="mod"):
    return lower(parse(source), module).to_document()


def run(source, payload=PAYLOAD):
    doc = compile_source(source)
    target = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
    # Pre-seed the row "find payment" reads, so the run fails on the deadline
    # (what this test is about) rather than on a missing row.
    rows = {"entity.payment": {row_key("entity.payment", payload): dict(payload)}}
    return Interpreter(doc, repo_rows=rows).run_workflow(target, payload)


def result_stub(status="completed", failed_step=None, failure_reason=None,
                steps=(), skipped=(), failure_kind=None):
    """A `run_workflow` result with only the keys `map_result` reads --
    same shape as `test_conflict_409.py`'s `result_stub`."""
    result = {"status": status, "failed_step": failed_step,
              "failure_reason": failure_reason, "steps": list(steps),
              "skipped": list(skipped), "bindings": {}, "duration_ms": 5,
              "correlation_id": "cid-test"}
    if failure_kind is not None:
        result["failure_kind"] = failure_kind
    return result


class RealDeadlineFailureKindTest(unittest.TestCase):
    """Both raise sites, through the real interpreter -- not a hand-built
    stub -- so a fix that only covers one of P1/P2 shows up here.

    Review r1/F1: status, failed_step, failure_kind, and the map_result pair
    are IDENTICAL for P1 and P2 -- none of them can tell the two raise sites
    apart. Only `failure_reason`'s wording differs ("exceeded after" vs
    "exhausted before"), so each case also pins that exact string. This is
    the one place in the whole change where asserting message wording is
    correct, not the mistake #128 removes: `map_result` must NOT depend on
    the wording (that was M6's bug), but THIS test's job is to prove which
    site fired, and wording is the only signal that does that. A fixture
    that drifts (e.g. the per-effect/step clock cost changes) and starts
    tripping the other site would otherwise stay green here -- silently
    testing P1 twice and P2 zero times -- which is exactly the regression
    this file exists to catch.
    """

    def test_p1_deadline_after_a_completed_step_sets_failure_kind(self):
        result = run(P1_SRC)
        self.assertEqual("failed", result["status"])
        self.assertEqual("update payment", result["failed_step"])
        self.assertEqual("deadline exceeded after step 'update payment'",
                         result.get("failure_reason"))
        self.assertEqual("deadline", result.get("failure_kind"))
        self.assertEqual((504, "deadline-exceeded"), map_result(result))

    def test_p2_deadline_before_a_step_starts_sets_failure_kind(self):
        result = run(P2_SRC)
        self.assertEqual("failed", result["status"])
        self.assertEqual("update payment", result["failed_step"])
        self.assertEqual("deadline exhausted before step 'update payment'",
                         result.get("failure_reason"))
        self.assertEqual("deadline", result.get("failure_kind"))
        self.assertEqual((504, "deadline-exceeded"), map_result(result))


class MapResultDeadlineTest(unittest.TestCase):
    """`map_result`, stub-driven: the negative control, the M7/M8/M8a
    regressions, and the two boundaries."""

    def test_negative_control_deadline_worded_reason_without_kind_is_not_504(self):
        """The decisive proof (D5): word `failure_reason` exactly like a
        deadline, carry no `failure_kind` -- must NOT be 504. A verdict that
        still depended on the string would pass this by accident; a
        type-based verdict cannot."""
        result = result_stub(
            status="failed", failed_step="cache link",
            failure_reason="deadline-flavored message that is not a timeout",
            steps=[{"step": "cache link", "effects": ["CacheAccess"]}])
        self.assertEqual((500, "workflow-failed"), map_result(result))

    def test_regression_conflict_still_maps_to_409(self):
        result = result_stub(
            status="failed", failed_step="create payment",
            failure_reason="repository create conflicts: payment#1 already exists",
            failure_kind="conflict",
            steps=[{"step": "create payment", "effects": ["RepositoryCall"]}])
        self.assertEqual((409, "conflict"), map_result(result))

    def test_regression_validation_still_maps_to_400(self):
        result = result_stub(
            status="failed", failed_step="validate input",
            failure_reason="field 'slug' does not match Slug's pattern",
            steps=[{"step": "validate input", "effects": ["Validation"]}])
        self.assertEqual((400, "validation-failed"), map_result(result))

    def test_regression_generic_failure_still_maps_to_500(self):
        result = result_stub(
            status="failed", failed_step="cache link",
            failure_reason="cache set without a TTL",
            steps=[{"step": "cache link", "effects": ["CacheAccess"]}])
        self.assertEqual((500, "workflow-failed"), map_result(result))

    def test_boundary_failure_reason_none_with_no_kind_maps_to_500(self):
        result = result_stub(
            status="failed", failed_step="cache link", failure_reason=None,
            steps=[{"step": "cache link", "effects": ["CacheAccess"]}])
        self.assertEqual((500, "workflow-failed"), map_result(result))

    def test_boundary_completed_maps_to_200(self):
        self.assertEqual((200, None), map_result(result_stub()))

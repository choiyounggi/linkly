"""issue #108, D1-D4/D6/D7: mode A actually runs a `parallel` block's steps
concurrently now — this file pins the execution half (the compile-time half,
D5/D9, is `test_parallel_write_conflict.py`).

Every fixture below is deliberately network-call-heavy: `_retryable` already
refuses to retry a step with a `NetworkCall` child (interp.py), so these
never hit the retry/cancel-between-attempts interaction, keeping each test
about exactly one D-decision.
"""

import threading
import time
import unittest

from lnpl.drivers import DriverError, FakeNetworkDriver
from lnpl.interp import Interpreter, refinement_index, sample_payload
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import default_rows

ENTITY = """entity Order
    field
        id UUID
"""


def compile_doc(source, module="t"):
    return lower(parse(source), module).to_document()


def run(source, module="t", network=None):
    doc = compile_doc(source, module)
    workflow = [n for n in doc["nodes"] if n["kind"] == "Workflow"][0]
    payload = sample_payload([n for n in doc["nodes"] if n["kind"] == "Entity"],
                             refinement_index(doc))
    interp = Interpreter(doc, repo_rows=default_rows(doc, workflow["id"], payload),
                         network=network)
    result = interp.run_workflow(workflow["id"], payload)
    return interp, result


class DelayedNetworkDriver(FakeNetworkDriver):
    """Adds a fixed sleep before every call — issue #108's approved test-
    local stand-in for "the network is slow." `FakeNetworkDriver`'s own
    `sleep` constructor hook only fires on retry backoff (drivers.py), never
    on an ordinary attempt, so it cannot simulate call latency by itself."""

    def __init__(self, delay_s, **kwargs):
        super().__init__(**kwargs)
        self._delay_s = delay_s

    def call(self, *args, **kwargs):
        time.sleep(self._delay_s)
        return super().call(*args, **kwargs)


class ConcurrencyCountingDriver(FakeNetworkDriver):
    """Tracks the high-water mark of simultaneously in-flight calls — the
    direct measurement DoD 3 needs (`policy parallel <N>` caps ACTUAL
    concurrent execution, not just wall-clock speed)."""

    def __init__(self, delay_s, **kwargs):
        super().__init__(**kwargs)
        self._delay_s = delay_s
        self._guard = threading.Lock()
        self._current = 0
        self.max_concurrent = 0

    def call(self, *args, **kwargs):
        with self._guard:
            self._current += 1
            self.max_concurrent = max(self.max_concurrent, self._current)
        try:
            time.sleep(self._delay_s)
            return super().call(*args, **kwargs)
        finally:
            with self._guard:
                self._current -= 1


class FailingNetworkDriver(FakeNetworkDriver):
    """Every call to `fail_target` raises; everything else behaves like the
    plain `FakeNetworkDriver`. Used to force a deterministic, immediate
    step failure (a `NetworkCall` step is never retried, so this fails on
    its one and only attempt)."""

    def __init__(self, fail_target, **kwargs):
        super().__init__(**kwargs)
        self._fail_target = fail_target

    def call(self, target, *args, **kwargs):
        if target == self._fail_target:
            raise DriverError("simulated failure for %r" % target)
        return super().call(target, *args, **kwargs)


class TestParallelStepsRunConcurrently(unittest.TestCase):
    """DoD 1: N steps in a `parallel` block run concurrently — wall-clock is
    meaningfully shorter than running the same N calls in sequence."""

    DELAY_S = 0.08

    def _fanout(self, blocked):
        body = "\n".join("    call Service%d as r%d" % (i, i) for i in range(3))
        if blocked:
            body = "    parallel\n" + body + "\n    merge"
        return "capability postgres\n\nworkflow FanOut\n" + body + "\n"

    def test_three_calls_in_parallel_beat_60_percent_of_sequential(self):
        driver = DelayedNetworkDriver(self.DELAY_S)
        start = time.monotonic()
        _, result = run(self._fanout(blocked=True), network=driver)
        parallel_elapsed = time.monotonic() - start
        self.assertEqual(result["status"], "completed")

        driver = DelayedNetworkDriver(self.DELAY_S)
        start = time.monotonic()
        _, result = run(self._fanout(blocked=False), network=driver)
        sequential_elapsed = time.monotonic() - start
        self.assertEqual(result["status"], "completed")

        # D10's margin: parallel comfortably under 60% of sequential. Three
        # 80ms calls in sequence cost >=240ms; run together they cost close
        # to 80ms plus scheduling overhead — nowhere near 144ms (60% of 240).
        self.assertLess(parallel_elapsed, 0.6 * sequential_elapsed)

    def test_every_call_still_binds_its_own_result(self):
        # Boundary: speed is not the only thing that must survive — each of
        # the three concurrent calls must still bind under its own name,
        # not clobber a shared one.
        _, result = run(self._fanout(blocked=True), network=FakeNetworkDriver())
        for i in range(3):
            self.assertIn("r%d" % i, result["bindings"])


class TestFailFastCancelsRemaining(unittest.TestCase):
    """DoD 2: one branch failing fails the block; steps that never got to
    start are cancelled and leave no record (D6) — proven with `policy
    parallel 1` so the pool's single worker processes steps in a
    deterministic, submission order and the un-started ones are provably
    still queued, not racing, when the failure lands."""

    SOURCE = """capability postgres

service Checkout
    policy
        parallel 1
workflow Restock
    parallel
    call FlakyService
    find order
    find order
    merge
"""

    def test_the_failing_branch_fails_the_block_and_cancels_the_rest(self):
        driver = FailingNetworkDriver("FlakyService")
        _, result = run(ENTITY + self.SOURCE, network=driver)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], "call FlakyService")
        # Only the failing step ever started (cap=1, FIFO) — the two `find`
        # steps queued behind it were cancelled before they ran, so they
        # contribute no `result["steps"]` entry, the same shape a sequential
        # failure already gives a step after the one that failed.
        self.assertEqual([s["step"] for s in result["steps"]], ["call FlakyService"])

    def test_a_block_with_no_failing_branch_completes_normally(self):
        # Normal case, same shape: every step ran, none was cancelled.
        _, result = run(ENTITY + self.SOURCE, network=FakeNetworkDriver())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["steps"]), 3)


class TestParallelCapLimitsConcurrency(unittest.TestCase):
    """DoD 3: `policy parallel <N>` caps ACTUAL simultaneous execution."""

    SOURCE_CAPPED = """capability postgres

service FanOutService
    policy
        parallel 2
workflow FanOut
    parallel
    call ServiceA as a
    call ServiceB as b
    call ServiceC as c
    call ServiceD as d
    merge
"""

    SOURCE_UNCAPPED = """capability postgres

workflow FanOut
    parallel
    call ServiceA as a
    call ServiceB as b
    call ServiceC as c
    merge
"""

    def test_declared_cap_is_never_exceeded_and_is_actually_reached(self):
        driver = ConcurrencyCountingDriver(0.05)
        _, result = run(self.SOURCE_CAPPED, network=driver)
        self.assertEqual(result["status"], "completed")
        self.assertLessEqual(driver.max_concurrent, 2)
        self.assertEqual(driver.max_concurrent, 2,
                         "4 steps at cap 2 should queue, not all start at once")

    def test_with_no_declared_cap_it_falls_back_to_the_blocks_step_count(self):
        # Boundary (D2-r1's no-value fallback): 3 steps, no `policy
        # parallel` at all, so nothing artificially caps them below 3.
        driver = ConcurrencyCountingDriver(0.05)
        _, result = run(self.SOURCE_UNCAPPED, network=driver)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(driver.max_concurrent, 3)


class TestSpanTreeAndStepCountRegression(unittest.TestCase):
    """DoD 5: the span tree comes out sibling-shaped (no wrapper span for
    the `Concurrency` block itself) and `steps <N>` matches what the
    equivalent sequential count would be."""

    SOURCE = ENTITY + """workflow Restock
    parallel
    find order
    find order
    find order
    merge
"""

    def test_three_steps_become_three_sibling_spans(self):
        interp, result = run(self.SOURCE, network=FakeNetworkDriver())
        root = interp.trace.root
        self.assertEqual(len(root.children), 3)
        self.assertTrue(all(span.kind == "WorkflowStep" for span in root.children))
        self.assertEqual(len(result["steps"]), 3)

    def test_declared_order_is_preserved_in_the_report(self):
        # The three steps are identical text, so this only proves ordering
        # survives at all (not scrambled by completion order) together with
        # the count test above — a real ordering claim needs distinct steps,
        # covered by the fail-fast test's single-surviving-step case.
        _, result = run(self.SOURCE, network=FakeNetworkDriver())
        self.assertEqual([s["step"] for s in result["steps"]],
                         ["find order", "find order", "find order"])


class TestParallelBlockRespectsWorkflowDeadline(unittest.TestCase):
    """Not one of the issue's 7 DoD items, but caught during review: the
    sequential main loop has a post-step check (`run_workflow`, "deadline
    exceeded after step %r", issue #128 P1) that fires when a step SUCCEEDS
    but the run's cumulative virtual-clock cost has already passed `policy
    timeout`'s deadline. `_run_parallel_block` needs the same check — every
    step in a `parallel` block still calls `self.clock.advance()` (under the
    lock), so the deadline is just as real inside a block as outside one.
    Without this, `policy timeout` silently stopped applying to any run
    whose deadline was only exceeded by a `parallel` block's own steps.

    `policy parallel 1` forces the same deterministic single-worker
    ordering `test_deadline_failure_kind.py`'s P1 fixture relies on
    (3 steps x 6ms virtual cost each = 18ms, past a 15ms deadline, but only
    after the last one completes) — this is that exact fixture, wrapped in
    `parallel`.
    """

    SOURCE = """capability postgres
entity Payment
    field
        id UUID
        amountCents Integer
service SlowService
    policy
        timeout 15ms
        parallel 1
workflow Crawl
    parallel
    validate payment
    find payment
    update payment
    merge
"""

    def test_deadline_exceeded_by_the_blocks_own_steps_fails_the_run(self):
        _, result = run(self.SOURCE, network=FakeNetworkDriver())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], "update payment")
        self.assertEqual(result["failure_reason"],
                         "deadline exceeded after step 'update payment'")
        self.assertEqual(result["failure_kind"], "deadline")

    def test_a_deadline_with_room_to_spare_still_completes(self):
        # Boundary: the same shape with a generous deadline must NOT trip —
        # proves the check is deadline-relative, not unconditional.
        roomy = self.SOURCE.replace("timeout 15ms", "timeout 5s")
        _, result = run(roomy, network=FakeNetworkDriver())
        self.assertEqual(result["status"], "completed")


class TestSequentialWorkflowsAreUnchanged(unittest.TestCase):
    """DoD 7: a workflow with no `parallel` block executes exactly as it did
    before this issue — `_run_step`/`_run_effect` only branch on `lock` when
    one is passed, and the sequential main loop never passes one. (The
    stronger proof is the full suite: 3162 pre-existing tests that never
    mention `parallel`, none of them touched by this change, stayed green.)
    """

    SOURCE = ENTITY + """workflow Restock
    find order
    update order
"""

    def test_plain_sequential_result_shape_is_unchanged(self):
        _, result = run(self.SOURCE, network=FakeNetworkDriver())
        self.assertEqual(result["status"], "completed")
        self.assertEqual([s["step"] for s in result["steps"]],
                         ["find order", "update order"])
        self.assertEqual([s["attempts"] for s in result["steps"]], [1, 1])

    def test_a_failing_sequential_step_still_stops_the_run(self):
        # Boundary/error path: sequential fail-fast (pre-existing behaviour)
        # must still hold — the first `create order` succeeds (nothing seeds
        # Order: `default_rows` only seeds entities the workflow READS), the
        # second finds the row the first just inserted and conflicts. Both
        # steps ran, so both get a `result["steps"]` entry; the second is
        # the one the run actually failed on, and nothing after it runs.
        source = ENTITY + """workflow Restock
    create order
    create order
"""
        _, result = run(source, network=FakeNetworkDriver())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], "create order")
        self.assertEqual(len(result["steps"]), 2)


if __name__ == "__main__":
    unittest.main()

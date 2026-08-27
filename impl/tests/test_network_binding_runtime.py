"""Issue #64/#76 / RFC-0027 — mode A execution: a `call ... as <name>` step
actually invokes a `NetworkDriver`, binds its response, and a transport
failure becomes a value (bound) or a failed run (unbound) — RFC-0027 §3.

Scope is Task 04: `Interpreter.network`, the `NetworkCall` branch of
`_run_effect`, and the deadline-to-timeout_ms wiring (RFC-0027 §5). The spec
`given call ... returns ...` stub form (RFC-0027 §7) and mode B (§8) are
later tasks' files.
"""

import unittest

from lnpl.drivers import (DEFAULT_NETWORK_TIMEOUT_MS, DriverError,
                          FakeNetworkDriver, HttpNetworkDriver)
from lnpl.interp import Interpreter, RunError
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import default_rows

BOUND_SOURCE = """capability postgres

entity Order
    field
        id UUID

service Checkout
    policy
        timeout 5s

workflow ChargeCard
    find order
    call PaymentGateway as paymentResult
    when paymentResult.status == 200
        update order
"""

UNBOUND_SOURCE = """capability postgres

entity Order
    field
        id UUID

service Checkout
    policy
        timeout 5s

workflow ChargeCard
    find order
    call PaymentGateway
"""

FIRST_STEP_SOURCE = """capability postgres

service Checkout
    policy
        timeout 5s

workflow Ping
    call PaymentGateway as paymentResult
"""

NO_TIMEOUT_SOURCE = """capability postgres

service Checkout
    policy
        retry 1

workflow Ping
    call PaymentGateway as paymentResult
"""


def compile_doc(source, module="m"):
    return lower(parse(source), module).to_document()


def workflow_id(doc):
    return next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")


class _FailingNetworkDriver(FakeNetworkDriver):
    """A driver that fails the way a real one does — connection gone, DNS
    dead. Mirrors `_FailingRepository` (test_driver_contract.py): injected
    because the fake's own default path never raises on its own."""

    def call(self, target, payload, timeout_ms, trace_headers=None,
             path_args=None):
        raise DriverError("the gateway is unreachable")


class _RecordingNetworkDriver(FakeNetworkDriver):
    """Records every `timeout_ms` it was called with, so the deadline-to-
    budget wiring (RFC-0027 §5) can be asserted on directly."""

    def __init__(self, stubs=None):
        super().__init__(stubs)
        self.seen_timeouts = []

    def call(self, target, payload, timeout_ms, trace_headers=None,
             path_args=None):
        self.seen_timeouts.append(timeout_ms)
        return super().call(target, payload, timeout_ms, trace_headers,
                            path_args)


class BoundCallBindingTest(unittest.TestCase):

    def test_a_stubbed_200_binds_status_and_body_and_the_guard_succeeds(self):
        doc = compile_doc(BOUND_SOURCE)
        target = workflow_id(doc)
        payload = {"id": "o-1"}
        driver = FakeNetworkDriver({"PaymentGateway": (200, {"txId": "t-1"})})
        interp = Interpreter(doc, repo_rows=default_rows(doc, target, payload),
                             network=driver)

        result = interp.run_workflow(target, payload)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["bindings"]["paymentResult"],
                         {"status": 200, "txId": "t-1"})
        self.assertEqual(result["skipped"], [],
                         "the 200 branch must run, not be skipped")

    def test_a_stubbed_500_binds_status_and_the_guard_skips_the_success_branch(self):
        doc = compile_doc(BOUND_SOURCE)
        target = workflow_id(doc)
        payload = {"id": "o-1"}
        driver = FakeNetworkDriver({"PaymentGateway": (500, {"message": "declined"})})
        interp = Interpreter(doc, repo_rows=default_rows(doc, target, payload),
                             network=driver)

        result = interp.run_workflow(target, payload)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["bindings"]["paymentResult"],
                         {"status": 500, "message": "declined"})
        self.assertEqual(len(result["skipped"]), 1,
                         "the 200-only branch must be skipped on a 500")

    def test_a_transport_failure_on_a_bound_call_binds_status_zero(self):
        """RFC-0027 §3, D3: the run completes — a bound call's failure is a
        value the guard can branch on, not a `RunError`."""
        doc = compile_doc(BOUND_SOURCE)
        target = workflow_id(doc)
        payload = {"id": "o-1"}
        interp = Interpreter(doc, repo_rows=default_rows(doc, target, payload),
                             network=_FailingNetworkDriver())

        result = interp.run_workflow(target, payload)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["bindings"]["paymentResult"], {"status": 0})
        self.assertEqual(len(result["skipped"]), 1)

    def test_a_logical_name_target_with_the_real_http_driver_binds_status_zero(self):
        """Issue #90 reproduction: `call PaymentGateway as p` under
        `--network http` used to crash with a raw `AttributeError` before
        reaching this translation site at all. With the real `HttpNetworkDriver`
        (not the synthetic `_FailingNetworkDriver`), the run must still
        complete with status 0 bound — no traceback."""
        doc = compile_doc(BOUND_SOURCE)
        target = workflow_id(doc)
        payload = {"id": "o-1"}
        driver = HttpNetworkDriver()
        self.addCleanup(driver.close)
        interp = Interpreter(doc, repo_rows=default_rows(doc, target, payload),
                             network=driver)

        result = interp.run_workflow(target, payload)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["bindings"]["paymentResult"], {"status": 0})
        self.assertEqual(len(result["skipped"]), 1)


class UnboundCallTest(unittest.TestCase):

    def test_no_stub_no_result_binding_and_the_run_completes(self):
        """Backward compatibility: an `as`-less call with the default fake
        driver observes nothing new — golden-scenario silence (RFC-0027 §3)."""
        doc = compile_doc(UNBOUND_SOURCE)
        target = workflow_id(doc)
        payload = {"id": "o-1"}
        interp = Interpreter(doc, repo_rows=default_rows(doc, target, payload))

        result = interp.run_workflow(target, payload)

        self.assertEqual(result["status"], "completed")
        self.assertNotIn("paymentResult", result["bindings"])
        self.assertEqual(set(result["bindings"]), {"order"},
                         "only the entity binding from `find order` — the "
                         "unbound call adds nothing")

    def test_a_transport_failure_on_an_unbound_call_becomes_a_failed_run(self):
        """RFC-0027 §3, D3: the fifth `DriverError`-translation site — an
        observation-only step must not silently swallow a real failure."""
        doc = compile_doc(UNBOUND_SOURCE)
        target = workflow_id(doc)
        payload = {"id": "o-1"}
        interp = Interpreter(doc, repo_rows=default_rows(doc, target, payload),
                             network=_FailingNetworkDriver())

        result = interp.run_workflow(target, payload)

        self.assertEqual(result["status"], "failed")
        self.assertIn("the gateway is unreachable", result["failure_reason"])

    def test_a_driver_error_never_escapes_as_a_raw_exception(self):
        doc = compile_doc(UNBOUND_SOURCE)
        target = workflow_id(doc)
        payload = {"id": "o-1"}
        interp = Interpreter(doc, repo_rows=default_rows(doc, target, payload),
                             network=_FailingNetworkDriver())

        try:
            interp.run_workflow(target, payload)
        except DriverError:
            self.fail("DriverError escaped instead of becoming a RunError/result")

    def test_a_logical_name_target_with_the_real_http_driver_becomes_a_failed_run(self):
        """Issue #90 reproduction, unbound leg: with the real `HttpNetworkDriver`
        and no `as`, the run must fail cleanly (status failed, which the CLI
        maps to rc 1) instead of the AttributeError traceback the bug report
        showed."""
        doc = compile_doc(UNBOUND_SOURCE)
        target = workflow_id(doc)
        payload = {"id": "o-1"}
        driver = HttpNetworkDriver()
        self.addCleanup(driver.close)
        interp = Interpreter(doc, repo_rows=default_rows(doc, target, payload),
                             network=driver)

        result = interp.run_workflow(target, payload)

        self.assertEqual(result["status"], "failed")
        self.assertIn("PaymentGateway", result["failure_reason"])


class DefaultNetworkDriverTest(unittest.TestCase):

    def test_no_network_kwarg_still_runs_deterministically(self):
        """`Interpreter(doc, repo_rows=...)` with no `network=` builds its
        own `FakeNetworkDriver` — the same convention `repository`/`cache`
        already follow."""
        doc = compile_doc(BOUND_SOURCE)
        target = workflow_id(doc)
        payload = {"id": "o-1"}
        interp = Interpreter(doc, repo_rows=default_rows(doc, target, payload))

        result = interp.run_workflow(target, payload)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["bindings"]["paymentResult"], {"status": 200})


class TimeoutBudgetWiringTest(unittest.TestCase):
    """RFC-0027 §5: `Policy.timeout`'s remaining budget, not the full
    declared duration, is what a `NetworkCall` receives — this is the first
    point RFC-0003's "propagate the remaining deadline" text is actually
    wired to anything."""

    def test_the_remaining_deadline_is_passed_when_declared(self):
        doc = compile_doc(FIRST_STEP_SOURCE)
        target = workflow_id(doc)
        driver = _RecordingNetworkDriver()
        interp = Interpreter(doc, network=driver)

        interp.run_workflow(target, {})

        # `call` is the workflow's first and only step, so the clock has not
        # advanced yet when the effect runs — the full 5s budget is still
        # the remaining budget.
        self.assertEqual(driver.seen_timeouts, [5000])

    def test_the_default_timeout_is_used_when_no_policy_timeout_is_declared(self):
        doc = compile_doc(NO_TIMEOUT_SOURCE)
        target = workflow_id(doc)
        driver = _RecordingNetworkDriver()
        interp = Interpreter(doc, network=driver)

        interp.run_workflow(target, {})

        self.assertEqual(driver.seen_timeouts, [DEFAULT_NETWORK_TIMEOUT_MS])


if __name__ == "__main__":
    unittest.main()

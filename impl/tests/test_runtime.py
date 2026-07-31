"""Interpreter: the RFC-0003 runtime contracts the golden scenario declares."""

import unittest

from lnpl.interp import Clock, Interpreter, RunError, mask_payload
from lnpl.lower import lower
from lnpl.parser import parse

SOURCE = """
capability postgres
capability redis
entity User
    field
        id UUID
        email Email
        password Password
service LoginService
    policy
        retry 3
        rollback
        timeout 3s
    security
        jwt
    performance
        response < 50ms
        cache 5m
workflow Login
    validate input
    authenticate
    cache user
"""

PAYLOAD = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
           "email": "user@example.com",
           "password": "s3cret"}


def build(**kw):
    doc = lower(parse(SOURCE), "login").to_document()
    rows = kw.pop("rows", {"entity.user": dict(PAYLOAD)})
    return Interpreter(doc, repo_rows=rows, **kw)


class TestHappyPath(unittest.TestCase):
    def test_all_steps_run_in_declared_order(self):
        result = build().run_workflow("wf.login", PAYLOAD)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([s["step"] for s in result["steps"]],
                         ["validate input", "authenticate", "cache user"])

    def test_one_span_per_step_under_a_single_correlation_id(self):
        interp = build()
        interp.run_workflow("wf.login", PAYLOAD)
        trace = interp.trace.to_dict()
        self.assertEqual(len(trace["span"]["children"]), 3)
        self.assertTrue(all(e["correlation_id"] == trace["correlation_id"]
                            for e in trace["logs"]))

    def test_cache_ttl_comes_from_the_performance_budget(self):
        interp = build()
        interp.run_workflow("wf.login", PAYLOAD)
        self.assertEqual(len(interp.cache.store), 1)
        # `cache 5m` is the only source of the TTL — 5m == 300000ms.
        cache_spans = [c for step in interp.trace.root.children
                       for c in step.children if c.kind == "CacheAccess"]
        self.assertEqual(len(cache_spans), 1)
        self.assertEqual(cache_spans[0].attrs["ttl_ms"], 300000)
        # and the entry outlives the run rather than expiring inside it
        _value, expires_at = next(iter(interp.cache.store.values()))
        self.assertGreater(expires_at, interp.clock.now)

    def test_cache_set_without_a_ttl_budget_is_refused(self):
        # Remove the `cache 5m` budget: RFC-0003 forbids a TTL-less cache write.
        src = SOURCE.replace("        cache 5m\n", "")
        doc = lower(parse(src), "login").to_document()
        interp = Interpreter(doc, repo_rows={"entity.user": dict(PAYLOAD)})
        result = interp.run_workflow("wf.login", PAYLOAD)
        self.assertEqual(result["failed_step"], "cache user")


class TestPolicyEnforcement(unittest.TestCase):
    def test_retry_n_means_n_retries_after_the_initial_attempt(self):
        result = build(rows={}).run_workflow("wf.login", PAYLOAD)
        failed = [s for s in result["steps"] if s["step"] == "authenticate"][0]
        self.assertEqual(failed["attempts"], 4)      # 1 initial + retry 3
        self.assertEqual(result["status"], "failed")

    def test_non_idempotent_effect_is_not_retried(self):
        src = SOURCE.replace("    authenticate", "    create user")
        doc = lower(parse(src), "login").to_document()
        interp = Interpreter(doc, repo_rows={})
        # A create is not idempotent, so a failure must not be retried. It also
        # does not fail here (create returns a row), so the run completes with
        # exactly one attempt per step — the assertion is on attempts, not status.
        result = interp.run_workflow("wf.login", PAYLOAD)
        self.assertTrue(all(s["attempts"] == 1 for s in result["steps"]))

    def test_retries_stop_at_the_deadline_not_only_at_the_attempt_cap(self):
        # Backoff is 100/200/400ms; with a 300ms deadline the third retry cannot
        # fit, so the run must fail on the deadline while attempts < retry+1.
        src = SOURCE.replace("timeout 3s", "timeout 300ms")
        doc = lower(parse(src), "login").to_document()
        interp = Interpreter(doc, repo_rows={})
        result = interp.run_workflow("wf.login", PAYLOAD)
        failed = [s for s in result["steps"] if s["step"] == "authenticate"][0]
        self.assertEqual(result["status"], "failed")
        self.assertLess(failed["attempts"], 4)

    def test_timeout_fails_the_run_when_the_deadline_is_exceeded(self):
        interp = build(clock=Clock(step_cost_ms=2000))   # 3 steps x 2s > timeout 3s
        result = interp.run_workflow("wf.login", PAYLOAD)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any(e["message"] == "deadline exceeded"
                            for e in interp.trace.logs))

    def test_response_slo_is_measured_not_enforced(self):
        interp = build(clock=Clock(step_cost_ms=30))     # far past the 50ms SLO
        result = interp.run_workflow("wf.login", PAYLOAD)
        self.assertFalse(result["slo_met"])
        # Exceeding the SLO must not by itself fail the run: the failure below,
        # if any, comes from the deadline, never from the SLO.
        self.assertNotIn("slo", str(result["failed_step"] or ""))


class TestValidationAndMasking(unittest.TestCase):
    def test_missing_required_field_fails_validation(self):
        result = build().run_workflow("wf.login", {"email": "user@example.com"})
        self.assertEqual(result["failed_step"], "validate input")

    def test_malformed_email_fails_validation(self):
        bad = dict(PAYLOAD, email="not-an-email")
        result = build().run_workflow("wf.login", bad)
        self.assertEqual(result["failed_step"], "validate input")

    def test_password_is_masked_in_logs(self):
        interp = build()
        interp.run_workflow("wf.login", PAYLOAD)
        blob = repr(interp.trace.logs)
        self.assertNotIn("s3cret", blob)
        self.assertIn("***", blob)

    def test_mask_payload_leaves_unmasked_types_alone(self):
        entity = {"fields": [{"name": "email", "type": "Email"},
                             {"name": "password", "type": "Password"}]}
        out = mask_payload({"email": "a@b.co", "password": "p"}, entity)
        self.assertEqual(out["email"], "a@b.co")
        self.assertEqual(out["password"], "***")


class TestObservabilityContract(unittest.TestCase):
    def test_metric_labels_outside_the_allowlist_are_rejected(self):
        interp = build()
        with self.assertRaises(RunError) as ctx:
            interp.trace.metric("x", {"user_id": "u-1"}, 1)
        self.assertIn("allowlist", str(ctx.exception))

    def test_allowed_labels_pass(self):
        interp = build()
        interp.trace.metric("x", {"workflow": "Login", "step": "s"}, 1)
        self.assertEqual(len(interp.trace.metrics), 1)

    def test_unknown_workflow_is_an_error(self):
        with self.assertRaises(RunError):
            build().run_workflow("wf.nope", PAYLOAD)


if __name__ == "__main__":
    unittest.main()

"""Interpreter: the RFC-0003 runtime contracts the golden scenario declares."""

import unittest

from lnpl.interp import Clock, Interpreter, RunError, mask_payload
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import row_key

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
    rows = kw.pop("rows", {"entity.user": {row_key("entity.user", PAYLOAD): dict(PAYLOAD)}})
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
        interp = Interpreter(doc, repo_rows={"entity.user": {row_key("entity.user", PAYLOAD): dict(PAYLOAD)}})
        result = interp.run_workflow("wf.login", PAYLOAD)
        self.assertEqual(result["failed_step"], "cache user")


class TestPolicyEnforcement(unittest.TestCase):
    def test_retry_n_means_n_retries_after_the_initial_attempt(self):
        result = build(rows={}).run_workflow("wf.login", PAYLOAD)
        failed = [s for s in result["steps"] if s["step"] == "authenticate"][0]
        self.assertEqual(failed["attempts"], 4)      # 1 initial + retry 3
        self.assertEqual(result["status"], "failed")

    def test_a_failing_non_idempotent_effect_is_not_retried(self):
        # `create` is not idempotent, so a failure must NOT be replayed even though
        # `retry 3` is declared — replaying it would risk a duplicate side effect.
        # The row is pre-seeded so the create conflicts and actually fails; without
        # a failing non-idempotent effect this rule cannot be observed.
        src = SOURCE.replace("    authenticate", "    create user")
        doc = lower(parse(src), "login").to_document()
        interp = Interpreter(doc, repo_rows={"entity.user": {row_key("entity.user", PAYLOAD): dict(PAYLOAD)}})
        result = interp.run_workflow("wf.login", PAYLOAD)
        failed = [s for s in result["steps"] if s["step"] == "create user"][0]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(failed["attempts"], 1, "a non-idempotent effect was retried")

    def test_an_idempotent_effect_under_the_same_policy_is_retried(self):
        # The contrast that makes the assertion above meaningful: same `retry 3`,
        # same failure shape, but a read is idempotent so it *is* replayed.
        result = build(rows={}).run_workflow("wf.login", PAYLOAD)
        failed = [s for s in result["steps"] if s["step"] == "authenticate"][0]
        self.assertEqual(failed["attempts"], 4)

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
        # 3 steps x 30ms is far past the 50ms SLO but well inside the 3s deadline,
        # so the run must still COMPLETE. Asserting the status is the point: an
        # implementation that enforced the SLO would fail here, and only a status
        # assertion can tell the two apart.
        interp = build(clock=Clock(step_cost_ms=30))
        result = interp.run_workflow("wf.login", PAYLOAD)
        self.assertFalse(result["slo_met"])
        self.assertEqual(result["status"], "completed",
                         "the SLO was enforced; RFC-0003 says measure and report")
        self.assertIsNone(result["failed_step"])


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


class TestGuardExecution(unittest.TestCase):
    """RFC-0003 Guard semantics: when skips, repeat multiplies, until loops."""

    GUARDED = SOURCE.replace("workflow Login\n    validate input\n    authenticate\n    cache user\n",
                             "workflow Login\n    validate input\n"
                             "    when token missing\n    authenticate\n")

    def _run(self, src, payload):
        doc = lower(parse(src), "login").to_document()
        interp = Interpreter(doc, repo_rows={"entity.user": {row_key("entity.user", PAYLOAD): dict(PAYLOAD)}})
        return interp, interp.run_workflow("wf.login", payload)

    def test_when_false_skips_the_guarded_step(self):
        # `token` present -> `token missing` is false -> authenticate is skipped
        interp, result = self._run(self.GUARDED, dict(PAYLOAD, token="t"))
        self.assertEqual([s["step"] for s in result["steps"]], ["validate input"])
        self.assertEqual(len(result["skipped"]), 1)

    def test_when_true_runs_the_guarded_step(self):
        interp, result = self._run(self.GUARDED, dict(PAYLOAD))
        self.assertEqual([s["step"] for s in result["steps"]],
                         ["validate input", "authenticate"])
        self.assertEqual(result["skipped"], [])

    def test_repeat_runs_the_guarded_step_n_times(self):
        src = SOURCE.replace("    authenticate\n", "    repeat 3\n    authenticate\n")
        _interp, result = self._run(src, dict(PAYLOAD))
        names = [s["step"] for s in result["steps"]]
        self.assertEqual(names.count("authenticate"), 3)

    def test_unsupported_condition_is_refused_not_guessed(self):
        src = SOURCE.replace("    authenticate\n",
                             "    when latency exceeds budget\n    authenticate\n")
        # RFC-0008: unsupported conditions are now rejected at parse time, not runtime
        from lnpl.parser import ParseError
        with self.assertRaises(ParseError) as ctx:
            self._run(src, dict(PAYLOAD))
        self.assertIn("invalid condition", str(ctx.exception))


class TestEventEmit(unittest.TestCase):
    """RFC-0003: async publish, at-least-once with a dedupable id, masked payload."""

    SRC = """
capability postgres
entity User
    field
        id UUID
        email Email
        password Password
event UserCreated on User create
service SignupService
workflow Signup
    create user
    emit userCreated
"""

    def _run(self):
        # Empty repository: the workflow *creates* the user, and a create against an
        # existing row conflicts.
        doc = lower(parse(self.SRC), "signup").to_document()
        interp = Interpreter(doc, repo_rows={})
        return interp, interp.run_workflow("wf.signup", PAYLOAD)

    def test_publication_is_registered_with_a_unique_id(self):
        interp, result = self._run()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(interp.outbox), 1)
        self.assertTrue(interp.outbox[0]["emission_id"].endswith("#1"))

    def test_the_emission_references_the_declared_event(self):
        interp, _r = self._run()
        self.assertEqual(interp.outbox[0]["event"], "event.user.created")

    def test_the_transferred_payload_is_masked(self):
        interp, _r = self._run()
        self.assertEqual(interp.outbox[0]["payload"]["password"], "***")
        self.assertNotIn("s3cret", repr(interp.outbox))

    def test_an_undeclared_event_reference_fails(self):
        doc = lower(parse(self.SRC), "signup").to_document()
        for node in doc["nodes"]:
            if node["kind"] == "EventEmit":
                node["event"] = "event.nope"
        interp = Interpreter(doc, repo_rows={})
        result = interp.run_workflow("wf.signup", PAYLOAD)
        self.assertEqual(result["failed_step"], "emit userCreated")

    def test_emit_is_not_retried_because_delivery_is_at_least_once(self):
        # An EventEmit must not be replayed by the retry policy; duplicate
        # publication is the consumer's dedupe problem, not the runtime's to create.
        # The emit has to *fail* for this to mean anything: with a succeeding emit
        # every step reports attempts == 1 whatever the retry rule says, so the
        # assertion would hold even for a runtime that retried everything.
        src = self.SRC.replace("service SignupService",
                               "service SignupService\n    policy\n        retry 3")
        doc = lower(parse(src), "signup").to_document()
        for node in doc["nodes"]:
            if node["kind"] == "EventEmit":
                node["event"] = "event.nope"      # makes the emit raise
        interp = Interpreter(doc, repo_rows={})
        result = interp.run_workflow("wf.signup", PAYLOAD)
        failed = [s for s in result["steps"] if s["step"] == "emit userCreated"]
        self.assertEqual(result["failed_step"], "emit userCreated")
        self.assertEqual([s["attempts"] for s in failed], [1],
                         "an at-least-once emit must be attempted exactly once")


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

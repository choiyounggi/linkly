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


# A refinement of Password. `ApiKey` is a name the registry has never heard of,
# so nothing but base resolution can make it masked. One entity only: masking
# consults the first Entity in the document and stops (pre-existing behavior).
API_KEY = """
capability postgres
refine ApiKey of Password
    minLength 8
entity Token
    field
        id UUID
        token ApiKey
event TokenIssued on Token create
service TokenService
    policy
        retry 0
workflow Issue
    create token
    emit TokenIssued
"""

SECRET = "SUPER-SECRET-VALUE"
API_KEY_PAYLOAD = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301", "token": SECRET}


class TestRefinementInheritsMasking(unittest.TestCase):
    """RFC-0001's Password row forbids exposure in logs, serialization and error
    messages; RFC-0003 owns the runtime contract and puts masking at ONE central
    chokepoint. A refinement strengthens its base — it cannot shed the base's
    obligations, so `refine ApiKey of Password` is masked too.
    """

    def _run(self, src=API_KEY, payload=None):
        doc = lower(parse(src), "tok").to_document()
        interp = Interpreter(doc, repo_rows={})
        result = interp.run_workflow("wf.issue",
                                     dict(API_KEY_PAYLOAD if payload is None
                                          else payload))
        return interp, result

    def test_password_refinement_is_masked_in_logs(self):
        interp, result = self._run()
        self.assertEqual(result["status"], "completed")
        blob = repr(interp.trace.logs)
        self.assertNotIn(SECRET, blob)
        self.assertIn("***", blob)

    def test_password_refinement_is_masked_in_the_outbox(self):
        # The second sink: an event leaves the process, so its payload is masked
        # too. Fixing only the log path would leak here.
        interp, _ = self._run()
        self.assertEqual(len(interp.outbox), 1)
        self.assertEqual(interp.outbox[0]["payload"]["token"], "***")
        self.assertNotIn(SECRET, repr(interp.outbox))

    def test_an_unmasked_field_of_the_same_entity_is_untouched(self):
        # Guards against over-masking: only the Password-derived field changes.
        interp, _ = self._run()
        self.assertEqual(interp.outbox[0]["payload"]["id"],
                         API_KEY_PAYLOAD["id"])

    def test_a_refinement_of_a_non_masked_base_is_not_masked(self):
        src = API_KEY.replace("refine ApiKey of Password",
                              "refine ApiKey of Text")
        interp, _ = self._run(src=src)
        self.assertEqual(interp.outbox[0]["payload"]["token"], SECRET)

    def test_a_plain_password_field_is_still_masked(self):
        # The pre-existing contract, restated on the same code path.
        src = API_KEY.replace("        token ApiKey", "        token Password")
        interp, _ = self._run(src=src)
        self.assertEqual(interp.outbox[0]["payload"]["token"], "***")

    def test_mask_payload_still_accepts_an_entity_without_resolved_bases(self):
        # Boundary: a hand-built entity node (no `base` key) must keep working —
        # `mask_payload` is a module-level function with callers outside the
        # interpreter.
        entity = {"fields": [{"name": "token", "type": "Password"},
                             {"name": "id", "type": "UUID"}]}
        out = mask_payload({"token": SECRET, "id": "x"}, entity)
        self.assertEqual(out["token"], "***")
        self.assertEqual(out["id"], "x")

    def test_mask_payload_leaves_a_none_entity_alone(self):
        self.assertEqual(mask_payload({"token": SECRET}, None),
                         {"token": SECRET})


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


# ---- RFC-0012: execution scope (issue #37) ---------------------------------

CHECKOUT_WORKFLOW = "wf.checkout"
GUARD_ID = "wf.checkout.guard.1"
PRODUCT = "entity.product"


def checkout_doc(condition="product.stock > 0", guard_first=False):
    """The shipped checkout document, with its guard condition substituted.

    The subject is the real shipped shape — `find product` -> guard ->
    `create order` — rather than a fixture invented to make the feature look
    good. The default `condition` is what `examples/checkout.lnpl` now carries;
    passing another lets one test vary the condition without a second fixture.

    `guard_first` moves the guard ahead of the read, which is how the "nothing is
    bound yet" boundary is reached without inventing a `query` verb: no
    RepositoryCall has completed when the condition is evaluated.
    """
    from tests.fixtures import CHECKOUT_LNPL
    with open(CHECKOUT_LNPL, encoding="utf-8") as fh:
        doc = lower(parse(fh.read()), "checkout").to_document()
    for node in doc["nodes"]:
        if node["id"] == GUARD_ID:
            node["condition"] = condition
        if node["id"] == CHECKOUT_WORKFLOW and guard_first:
            children = list(node["children"])
            children.remove(GUARD_ID)
            node["children"] = [GUARD_ID] + children
    return doc


def checkout_payload(**overrides):
    """The derived sample payload, with explicit overrides."""
    from lnpl.interp import refinement_index, sample_payload
    doc = checkout_doc()
    payload = sample_payload([n for n in doc["nodes"] if n["kind"] == "Entity"],
                             refinement_index(doc))
    payload.update(overrides)
    return payload


def product_rows(payload, **row_overrides):
    """Seed `entity.product` with a row that may DIFFER from the payload.

    This is the whole point of the issue #37 tests. `repo_policy.default_rows`
    seeds the row as `dict(payload)`, so under the default seed the row and the
    input carry the same `stock` and a guard reading either one gives the same
    answer — the bug and the fix are indistinguishable. Only a row that differs
    from the payload can tell them apart.
    """
    row = dict(payload)
    row.update(row_overrides)
    return {PRODUCT: {row_key(PRODUCT, payload): row}}


class TestStepResultBinding(unittest.TestCase):
    """Issue #37: `when product.stock > 0` must read the row `find product` got."""

    def _run(self, condition="product.stock > 0", guard_first=False, **kw):
        payload = checkout_payload(**kw.pop("payload", {}))
        rows = product_rows(payload, **kw.pop("row", {}))
        doc = checkout_doc(condition=condition, guard_first=guard_first)
        interp = Interpreter(doc, repo_rows=rows)
        return interp, interp.run_workflow(CHECKOUT_WORKFLOW, payload)

    def test_the_guard_reads_the_fetched_row_not_the_input_payload(self):
        # The input says 5 (guard would be TRUE on the payload); the stored row
        # says 0 (guard is FALSE on the row). If `create order` runs, the guard
        # read the payload — which is issue #37.
        _interp, result = self._run(payload={"stock": 5}, row={"stock": 0})
        self.assertEqual(result["status"], "completed")
        self.assertIn(GUARD_ID, result["skipped"],
                      "issue #37: the stored row has stock=0, so `when "
                      "product.stock > 0` is false and the guarded item is "
                      "skipped. The payload's stock=5 must not decide this.")
        self.assertEqual([s["step"] for s in result["steps"]],
                         ["validate product", "find product", "cache product"],
                         "issue #37: `create order` is guarded and the guard is "
                         "false, so it must not run.")

    def test_the_guard_opens_on_the_row_even_when_the_payload_would_close_it(self):
        # The mirror image: payload 0 (would be FALSE), row 5 (is TRUE).
        _interp, result = self._run(payload={"stock": 0}, row={"stock": 5})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["skipped"], [],
                         "issue #37: the stored row has stock=5, so the guard "
                         "holds even though the payload's stock=0 would close it.")
        self.assertIn("create order", [s["step"] for s in result["steps"]])

    def test_the_binding_carries_the_stored_row(self):
        _interp, result = self._run(payload={"stock": 5}, row={"stock": 0})
        self.assertEqual(result["bindings"]["product"]["stock"], 0,
                         "the binding must hold the row the repository returned, "
                         "not the input payload.")

    def test_a_bare_reference_still_reads_the_payload(self):
        # Control (RFC-0012 G12.3): the bare form must not have moved. Payload 5,
        # row 0 — bare `stock > 0` reads the payload, so the guard HOLDS. This is
        # the exact input where the two forms give opposite answers.
        _interp, result = self._run(condition="stock > 0",
                                    payload={"stock": 5}, row={"stock": 0})
        self.assertEqual(result["skipped"], [],
                         "RFC-0012 G12.3: bare `stock` names the input payload, "
                         "which is 5 here, so the guard holds. If this flipped, "
                         "every guard written before RFC-0012 changed meaning.")

    # ---- boundary cases ----------------------------------------------------
    def test_an_unbound_reference_is_false_not_an_error(self):
        # Boundary: the guard runs BEFORE any read, so nothing is bound.
        # RFC-0012 G12.4 — an unresolved reference compares false.
        _interp, result = self._run(payload={"stock": 5}, row={"stock": 5},
                                    guard_first=True)
        self.assertEqual(result["status"], "completed")
        self.assertIn(GUARD_ID, result["skipped"],
                      "RFC-0012 G12.4: no RepositoryCall has completed, so "
                      "`product.stock` resolves to nothing and the comparison "
                      "is false — not an error, and not vacuously true.")

    def test_an_unbound_reference_does_not_exist(self):
        _interp, result = self._run(condition="product.stock exists",
                                    guard_first=True)
        self.assertIn(GUARD_ID, result["skipped"],
                      "RFC-0012 G12.4: `exists` on an unbound reference is false.")

    def test_a_field_absent_from_the_row_is_false(self):
        # Boundary: the binding exists, but the row has no such field.
        _interp, result = self._run(condition="product.nosuch > 0")
        self.assertIn(GUARD_ID, result["skipped"],
                      "RFC-0012 G12.4: a field the row does not carry compares "
                      "false rather than raising.")

    def test_a_field_absent_from_the_row_is_missing(self):
        _interp, result = self._run(condition="product.nosuch missing")
        self.assertEqual(result["skipped"], [],
                         "RFC-0012 G12.4: `missing` holds for a field the row "
                         "does not carry.")

    # ---- error case --------------------------------------------------------
    def test_comparing_a_non_numeric_bound_field_is_an_error(self):
        # `name` is Text. RFC-0012 G12.4's last row: present-but-not-numeric is
        # an error, not absence.
        with self.assertRaises(RunError) as caught:
            self._run(condition="product.name > 0")
        message = str(caught.exception)
        self.assertIn("product.name", message,
                      "the refusal must name the reference that could not be "
                      "compared; got %r" % message)

    # ---- isolation (mutable-state trap) ------------------------------------
    def test_bindings_do_not_leak_between_runs_of_one_interpreter(self):
        # The guard runs BEFORE the read here, and the row says stock=5. So:
        #   correct  — run 2's guard finds nothing bound yet   -> skips
        #   leaking  — run 2's guard sees run 1's row (stock=5) -> OPENS
        # `create order` in run 2's steps is therefore the observable signature
        # of a binding map shared across runs.
        payload = checkout_payload(stock=0)
        doc = checkout_doc(guard_first=True)
        interp = Interpreter(doc, repo_rows=product_rows(payload, stock=5))
        first = interp.run_workflow(CHECKOUT_WORKFLOW, payload)
        self.assertEqual(first["bindings"]["product"]["stock"], 5,
                         "precondition: run 1 must end with the row bound, "
                         "otherwise run 2 has nothing to leak from.")
        first["bindings"]["product"] = {"stock": 999}
        second = interp.run_workflow(CHECKOUT_WORKFLOW, payload)
        self.assertIsNot(first["bindings"], second["bindings"],
                         "each run must get its own binding map; sharing one "
                         "object across runs is the mutable-state trap that "
                         "carries one run's rows into the next.")
        self.assertIn(GUARD_ID, second["skipped"],
                      "the second run's guard is evaluated before its own read, "
                      "so nothing is bound yet and it must skip. If it opened, "
                      "it read the FIRST run's binding.")
        self.assertNotIn("create order", [s["step"] for s in second["steps"]])


class TestScopeResolution(unittest.TestCase):
    """The single resolver both guards and `spec … expect` call (RFC-0012)."""

    def test_bare_name_resolves_against_the_payload(self):
        from lnpl.interp import resolve_reference
        self.assertEqual(resolve_reference("stock", {"stock": 7}, {}), 7)

    def test_qualified_name_resolves_against_the_binding(self):
        from lnpl.interp import resolve_reference
        self.assertEqual(
            resolve_reference("product.stock", {"stock": 7},
                              {"product": {"stock": 0}}), 0,
            "a qualified reference must never fall back to the payload — that "
            "fallback is what makes the two forms indistinguishable.")

    def test_unknown_binding_resolves_to_none(self):
        from lnpl.interp import resolve_reference
        self.assertIsNone(resolve_reference("widget.stock", {"stock": 7}, {}))

    def test_unknown_field_resolves_to_none(self):
        from lnpl.interp import resolve_reference
        self.assertIsNone(
            resolve_reference("product.nosuch", {}, {"product": {"stock": 1}}))

    def test_missing_payload_field_resolves_to_none(self):
        from lnpl.interp import resolve_reference
        self.assertIsNone(resolve_reference("stock", {}, {}))

    def test_binding_name_is_the_camelcase_declared_name(self):
        from lnpl.interp import binding_name
        self.assertEqual(binding_name({"name": "Product"}), "product")

    def test_binding_name_keeps_inner_capitals(self):
        # RFC-0012 G12.2: derived from the declared name, NOT the node id — the
        # id splits multi-word names on dots (`entity.order.item`), which is not
        # a single CamelName.
        from lnpl.interp import binding_name
        self.assertEqual(binding_name({"name": "OrderItem"}), "orderItem")


class TestRunResultAdditions(unittest.TestCase):
    """The result keys `spec`'s new expectations read (issue #39 groundwork)."""

    def test_effects_are_recorded_per_step(self):
        payload = checkout_payload(stock=5)
        doc = checkout_doc()
        interp = Interpreter(doc, repo_rows=product_rows(payload, stock=5))
        result = interp.run_workflow(CHECKOUT_WORKFLOW, payload)
        by_step = {s["step"]: s["effects"] for s in result["steps"]}
        self.assertEqual(by_step["find product"], ["RepositoryCall"])
        self.assertEqual(by_step["validate product"], ["Validation"])

    def test_failure_reason_is_none_on_success(self):
        payload = checkout_payload(stock=5)
        doc = checkout_doc()
        interp = Interpreter(doc, repo_rows=product_rows(payload, stock=5))
        result = interp.run_workflow(CHECKOUT_WORKFLOW, payload)
        self.assertIsNone(result["failure_reason"])

    def test_failure_reason_records_why_the_step_failed(self):
        # Empty repository: `find product` reads nothing and fails.
        payload = checkout_payload(stock=5)
        doc = checkout_doc()
        interp = Interpreter(doc, repo_rows={})
        result = interp.run_workflow(CHECKOUT_WORKFLOW, payload)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failed_step"], "find product")
        self.assertIn("no row", result["failure_reason"],
                      "the reason must carry the repository's own message so a "
                      "spec can assert on it; got %r" % result["failure_reason"])


if __name__ == "__main__":
    unittest.main()

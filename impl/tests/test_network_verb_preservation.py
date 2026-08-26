"""Issue #125 — `declared-not-bound` and `rollback-escapes-network` quote the
author's own verb (`call` or `request`), not a hardcoded `"call"`.

`call` and `request` both lower to a `NetworkCall` node (`VERB_LEXICON`,
`lower.py:112-113`); the node itself carries no `verb` field. Before this
task both diagnostics that name a `NetworkCall` step built their `subject`
as `"call %s" % target` unconditionally, so a workflow that wrote `request
PaymentGateway` still got told about `call PaymentGateway` — the machine
misquoting the author's own source. The fix is a compile-time-only side map
(`_WfContext.network_verbs`, keyed by the Effect node's `eid`) threaded into
both diagnostics; the IR itself is untouched, so the golden `.lir.json`
files and `schemas/lir.schema.json` are byte-identical before and after.
"""
import unittest

from lnpl.lower import lower
from lnpl.parser import parse

DECLARED_NOT_BOUND = "declared-not-bound"
ROLLBACK_ESCAPES_NETWORK = "rollback-escapes-network"


def diagnose(source, code, name="probe"):
    """`source`'s diagnostics for `code` — the compiler decides, not the test."""
    module = lower(parse(source), name)
    return list(module.diagnostics.by_code(code))


def unbound_source(verb, target="PaymentGateway"):
    """A `capability http` for `PaymentGateway` is deliberately absent, so
    `declared-not-bound` fires — same fixture shape as
    `test_network_binding.py`'s `call_source`."""
    return """capability postgres

entity Payment
    field
        id UUID

service Checkout
    policy
        timeout 5s

workflow ChargeCard
    %s %s
""" % (verb, target)


def rollback_source(verb, target="X"):
    """`policy rollback` owns the workflow, so a `NetworkCall` step inside it
    trips `rollback-escapes-network` — same fixture shape as
    `test_rollback_escapes_network.py`'s `ONE_CALL_WITH_ROLLBACK`."""
    return """entity Order
    field
        id UUID

service Checkout
    policy
        rollback

workflow Pay
    %s %s
""" % (verb, target)


class DeclaredNotBoundQuotesTheAuthorsVerb(unittest.TestCase):
    """D3: `_derive_effect` already has `verb` as a parameter for this site —
    no side map needed."""

    def test_request_subject_is_request_not_call(self):
        found = diagnose(unbound_source("request"), DECLARED_NOT_BOUND)
        self.assertEqual(len(found), 1, found)
        self.assertEqual(found[0].subject, "request PaymentGateway")

    def test_request_message_is_unchanged_by_the_verb(self):
        # `declared-not-bound`'s message only ever names the target, never
        # the subject/verb — D3 only touches `subject`.
        found = diagnose(unbound_source("request"), DECLARED_NOT_BOUND)[0]
        self.assertEqual(
            found.message,
            "'PaymentGateway' has no `capability http` declaration — it "
            "runs with method POST and no auth")


class RollbackEscapesNetworkQuotesTheAuthorsVerb(unittest.TestCase):
    """D4: `_check_rollback_escapes_network` reads the verb back out of
    `ctx.network_verbs`, keyed by the Effect node's `eid` (not `step_id` —
    see the plan's r1 correction)."""

    def test_request_subject_is_request_not_call(self):
        found = diagnose(rollback_source("request"), ROLLBACK_ESCAPES_NETWORK)
        self.assertEqual(len(found), 1, found)
        self.assertEqual(found[0].subject, "request X")

    def test_request_message_embeds_the_request_subject(self):
        found = diagnose(rollback_source("request"), ROLLBACK_ESCAPES_NETWORK)[0]
        self.assertEqual(
            found.message,
            "workflow Pay declares 'policy rollback', but step `request X` "
            "leaves the transaction boundary — a rollback cannot undo it")


class CallVerbIsAByteIdenticalRegression(unittest.TestCase):
    """D5: the default for an unresolvable verb stays the literal `"call"`
    (not a neutral `"network call to X"`), so every existing `call X`
    diagnostic must read exactly as it did before this task. These literals
    were captured from the pre-fix compiler — a change to either string is a
    regression, not an improvement, for #125's purposes."""

    def test_declared_not_bound_subject_and_message_unchanged(self):
        found = diagnose(unbound_source("call"), DECLARED_NOT_BOUND)
        self.assertEqual(len(found), 1, found)
        self.assertEqual(found[0].subject, "call PaymentGateway")
        self.assertEqual(
            found[0].message,
            "'PaymentGateway' has no `capability http` declaration — it "
            "runs with method POST and no auth")

    def test_rollback_escapes_network_subject_and_message_unchanged(self):
        found = diagnose(
            rollback_source("call", target="PaymentGateway"), ROLLBACK_ESCAPES_NETWORK)
        self.assertEqual(len(found), 1, found)
        self.assertEqual(found[0].subject, "call PaymentGateway")
        self.assertEqual(
            found[0].message,
            "workflow Pay declares 'policy rollback', but step `call "
            "PaymentGateway` leaves the transaction boundary — a rollback "
            "cannot undo it")


class TargetlessNetworkCallStillPreservesTheVerb(unittest.TestCase):
    """Boundary: a bare `call`/`request` with no trailing target token lowers
    `target` to the literal `"unspecified"` (`lower.py`: `target = obj or
    "unspecified"`) — the verb-preservation fix must not special-case that
    away, in either diagnostic."""

    def test_declared_not_bound_keeps_request_with_no_target(self):
        found = diagnose(rollback_source("request", target=""), DECLARED_NOT_BOUND)
        self.assertEqual(len(found), 1, found)
        self.assertEqual(found[0].subject, "request unspecified")

    def test_rollback_escapes_network_keeps_request_with_no_target(self):
        found = diagnose(
            rollback_source("request", target=""), ROLLBACK_ESCAPES_NETWORK)
        self.assertEqual(len(found), 1, found)
        self.assertEqual(found[0].subject, "request unspecified")

    def test_declared_not_bound_keeps_call_with_no_target(self):
        # D5's regression guarantee applies at this boundary too.
        found = diagnose(rollback_source("call", target=""), DECLARED_NOT_BOUND)
        self.assertEqual(found[0].subject, "call unspecified")


if __name__ == "__main__":
    unittest.main()

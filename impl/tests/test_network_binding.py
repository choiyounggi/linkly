"""Issue #64/#76 / RFC-0027 — `call`/`request ... as <name>`, the lowering-time
contract.

Scope is Task 03 of the network effort: reading the trailing tokens a `call`/
`request` step line carries past its target, binding a `result` field on the
`NetworkCall` IR node, and the two static rejections that guard the new
binding name (shape, and collision with an entity's single-row binding name —
RFC-0027 §2). Mode A execution (actually invoking a driver, binding a value at
run time) is a later task's file; nothing here runs a workflow.
"""

import os
import subprocess
import sys
import unittest

from lnpl.lower import LowerError, VERB_LEXICON, lower
from lnpl.parser import parse

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


def compile_doc(source, module="m"):
    return lower(parse(source), module)


def nodes_of(doc, kind):
    return [n for n in doc["nodes"] if n["kind"] == kind]


def call_source(body):
    """`Payment` fixture — an entity whose camelCase binding name (`payment`)
    is available for the name-collision cases."""
    return """capability postgres

entity Payment
    field
        id UUID

service Checkout
    policy
        timeout 5s

workflow ChargeCard
%s
""" % body


class TestUnboundCallUnchanged(unittest.TestCase):
    """RFC-0027 §3: `as`-less `call`/`request` is byte-for-byte what it was
    before this RFC — no `result` field, no diagnostics."""

    def test_call_with_no_trailing_tokens_carries_no_result_field(self):
        mod = compile_doc(call_source("    call PaymentGateway\n"))
        doc = mod.to_document()
        calls = nodes_of(doc, "NetworkCall")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["target"], "PaymentGateway")
        self.assertNotIn("result", calls[0])
        # RFC-0027's own diagnostics (the `as`-binding feature this file
        # covers) still emit none; issue #101 adds one `declared-not-bound`
        # for `PaymentGateway` naming no `capability http` in this fixture —
        # a later, separate feature, not a regression of this one.
        codes = [d.code for d in mod.diagnostics.all()]
        self.assertEqual(codes, ["declared-not-bound"])

    def test_request_with_no_trailing_tokens_carries_no_result_field(self):
        mod = compile_doc(call_source("    request PaymentGateway\n"))
        doc = mod.to_document()
        calls = nodes_of(doc, "NetworkCall")
        self.assertNotIn("result", calls[0])


class TestAsBinding(unittest.TestCase):
    """RFC-0027 §2: `call`/`request <target> as <name>` binds a result."""

    def test_call_as_binds_the_result_field(self):
        mod = compile_doc(call_source("    call PaymentGateway as paymentResult\n"))
        doc = mod.to_document()
        calls = nodes_of(doc, "NetworkCall")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["target"], "PaymentGateway")
        self.assertEqual(calls[0]["result"], "paymentResult")
        # issue #101: `PaymentGateway` names no `capability http` in this
        # fixture, so `declared-not-bound` is the one expected diagnostic —
        # see the no-trailing-tokens case above for the full rationale.
        codes = [d.code for d in mod.diagnostics.all()]
        self.assertEqual(codes, ["declared-not-bound"])

    def test_request_as_binds_the_result_field_too(self):
        """`call`/`request` share one `VERB_LEXICON` entry (`NetworkCall`,
        `{}`) — the `as` handling must not care which surface verb it saw."""
        mod = compile_doc(call_source("    request PaymentGateway as paymentResult\n"))
        doc = mod.to_document()
        calls = nodes_of(doc, "NetworkCall")
        self.assertEqual(calls[0]["result"], "paymentResult")

    def test_the_lexicon_entry_itself_is_unchanged(self):
        """No new verb, no new Effect kind — `as` is read positionally by
        lowering, not by widening `VERB_LEXICON` (RFC-0027 §2)."""
        self.assertEqual(VERB_LEXICON["call"], ("NetworkCall", {}))
        self.assertEqual(VERB_LEXICON["request"], ("NetworkCall", {}))


class TestStaticRejections(unittest.TestCase):
    """RFC-0027 §2: malformed trailing tokens and unsafe names are compile
    errors, not silently dropped (the gap RFC-0027 §Motivation names)."""

    def test_a_third_keyword_that_is_not_as_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(call_source("    call PaymentGateway to paymentResult\n"))
        self.assertIn("'as <name>'", str(ctx.exception))

    def test_as_with_no_name_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(call_source("    call PaymentGateway as\n"))
        self.assertIn("'as <name>'", str(ctx.exception))

    def test_a_pascal_case_name_is_refused(self):
        """`<name>.status` must be a valid `Reference` (RFC-0012 §G12.1),
        which requires camelCase — the same shape every other binding name
        already carries."""
        with self.assertRaises(LowerError) as ctx:
            compile_doc(call_source("    call PaymentGateway as PaymentResult\n"))
        self.assertIn("camelCase", str(ctx.exception))

    def test_a_snake_case_name_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(call_source("    call PaymentGateway as payment_result\n"))
        self.assertIn("camelCase", str(ctx.exception))

    def test_a_name_colliding_with_an_entitys_binding_name_is_refused(self):
        """`payment` is `Payment`'s single-row binding name (RFC-0012
        §G12.2) — `<name>.field` and `<binding>.field` share the same
        grammar position, so the two cannot alias (RFC-0027 §2)."""
        with self.assertRaises(LowerError) as ctx:
            compile_doc(call_source(
                "    find payment\n    call PaymentGateway as payment\n"))
        self.assertIn("Payment", str(ctx.exception))


class TestIrSchemaGate(unittest.TestCase):
    """RFC-0027 §2: `result` is a new optional field on `nodeNetworkCall` —
    the schema self-test must accept it and reject a malformed one
    (`scripts/validate_ir.py --self-test`)."""

    def test_a_compiled_document_with_result_validates_against_the_schema(self):
        import jsonschema

        mod = compile_doc(call_source("    call PaymentGateway as paymentResult\n"))
        doc = mod.to_document()
        schema_path = os.path.join(REPO_ROOT, "schemas", "lir.schema.json")
        import json
        with open(schema_path, encoding="utf-8") as fh:
            schema = json.load(fh)
        jsonschema.validate(doc, schema)

    def test_the_validator_self_test_includes_network_negatives_and_passes(self):
        result = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "scripts", "validate_ir.py"),
             "--self-test"],
            capture_output=True, text=True, cwd=REPO_ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("NETWORK_FIXTURE", result.stdout)


if __name__ == "__main__":
    unittest.main()

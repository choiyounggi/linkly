"""Issue #109 — `capability http` extensions at lowering time.

Covers: HTTP_METHODS widened to 5, `retry`/`breaker`/`path` clauses on
`capability http`, the `retry-on-non-idempotent` compile warning, and the
`call/request <Target> with <ref>...` grammar that substitutes into a
declared `path` template. Runtime behaviour (actually retrying, breaking,
assembling an escaped URL) is `drivers.py`'s file — this one is lowering only.
"""

import json
import os
import unittest

from lnpl.diagnostics import CODES, SEVERITY_OF
from lnpl.lower import LowerError, lower
from lnpl.parser import parse

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


def compile_doc(source, module="m"):
    return lower(parse(source), module)


def nodes_of(doc, kind):
    return [n for n in doc["nodes"] if n["kind"] == kind]


def cap_source(cap_body, call_line="    call PaymentGateway as p\n"):
    return """capability http PaymentGateway
%s
entity Order
    field
        id UUID
service Checkout
workflow Pay
%s""" % (cap_body, call_line)


class HttpMethodsTest(unittest.TestCase):

    def test_put_patch_delete_are_accepted_methods(self):
        for method in ("put", "patch", "delete"):
            mod = compile_doc(cap_source("    method %s\n" % method))
            caps = nodes_of(mod.to_document(), "Capability")
            self.assertEqual(caps[0]["method"], method)

    def test_get_and_post_still_accepted(self):
        for method in ("get", "post"):
            mod = compile_doc(cap_source("    method %s\n" % method))
            caps = nodes_of(mod.to_document(), "Capability")
            self.assertEqual(caps[0]["method"], method)

    def test_an_unknown_method_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(cap_source("    method head\n"))
        self.assertIn("method", str(ctx.exception))


class RetryClauseTest(unittest.TestCase):

    def test_retry_backoff_jitter_parses_into_the_capability_node(self):
        mod = compile_doc(cap_source(
            "    method get\n    retry 3 backoff 200ms jitter\n"))
        caps = nodes_of(mod.to_document(), "Capability")
        self.assertEqual(caps[0]["retry"],
                         {"count": 3, "backoff_ms": 200, "jitter": True})

    def test_retry_without_jitter_flag_defaults_jitter_false(self):
        mod = compile_doc(cap_source(
            "    method get\n    retry 3 backoff 200ms\n"))
        caps = nodes_of(mod.to_document(), "Capability")
        self.assertEqual(caps[0]["retry"],
                         {"count": 3, "backoff_ms": 200, "jitter": False})

    def test_no_retry_clause_leaves_no_retry_field(self):
        """Boundary/regression: declaring nothing carries no `retry` key at
        all (RFC-0027-style byte-identical-when-undeclared)."""
        mod = compile_doc(cap_source("    method get\n"))
        caps = nodes_of(mod.to_document(), "Capability")
        self.assertNotIn("retry", caps[0])

    def test_retry_accepts_a_one_minute_backoff(self):
        mod = compile_doc(cap_source("    method get\n    retry 5 backoff 1m\n"))
        caps = nodes_of(mod.to_document(), "Capability")
        self.assertEqual(caps[0]["retry"]["backoff_ms"], 60000)

    def test_retry_count_must_be_a_positive_integer(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(cap_source("    method get\n    retry 0 backoff 200ms\n"))
        self.assertIn("retry", str(ctx.exception))

    def test_retry_needs_the_backoff_keyword(self):
        with self.assertRaises(LowerError):
            compile_doc(cap_source("    method get\n    retry 3 200ms\n"))

    def test_retry_backoff_needs_a_real_duration(self):
        with self.assertRaises(LowerError):
            compile_doc(cap_source("    method get\n    retry 3 backoff soon\n"))

    def test_retry_rejects_a_stray_trailing_word(self):
        with self.assertRaises(LowerError):
            compile_doc(cap_source(
                "    method get\n    retry 3 backoff 200ms please\n"))

    def test_retry_declared_twice_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(cap_source(
                "    method get\n    retry 3 backoff 200ms\n"
                "    retry 5 backoff 1s\n"))
        self.assertIn("twice", str(ctx.exception))


class BreakerClauseTest(unittest.TestCase):

    def test_breaker_after_within_parses_into_the_capability_node(self):
        mod = compile_doc(cap_source(
            "    method get\n    breaker after 10 within 1m\n"))
        caps = nodes_of(mod.to_document(), "Capability")
        self.assertEqual(caps[0]["breaker"], {"threshold": 10, "window_ms": 60000})

    def test_no_breaker_clause_leaves_no_breaker_field(self):
        mod = compile_doc(cap_source("    method get\n"))
        caps = nodes_of(mod.to_document(), "Capability")
        self.assertNotIn("breaker", caps[0])

    def test_breaker_threshold_must_be_a_positive_integer(self):
        with self.assertRaises(LowerError):
            compile_doc(cap_source("    method get\n    breaker after 0 within 1m\n"))

    def test_breaker_needs_the_after_and_within_keywords(self):
        with self.assertRaises(LowerError):
            compile_doc(cap_source("    method get\n    breaker 10 1m\n"))

    def test_breaker_within_needs_a_real_duration(self):
        with self.assertRaises(LowerError):
            compile_doc(cap_source("    method get\n    breaker after 10 within soon\n"))

    def test_breaker_declared_twice_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(cap_source(
                "    method get\n    breaker after 10 within 1m\n"
                "    breaker after 5 within 30s\n"))
        self.assertIn("twice", str(ctx.exception))


class PathClauseTest(unittest.TestCase):

    def test_path_parses_into_the_capability_node(self):
        mod = compile_doc(cap_source(
            '    method get\n    path "/orders/{}"\n',
            call_line="    call PaymentGateway with order.id as p\n"))
        caps = nodes_of(mod.to_document(), "Capability")
        self.assertEqual(caps[0]["path"], "/orders/{}")

    def test_no_path_clause_leaves_no_path_field(self):
        mod = compile_doc(cap_source("    method get\n"))
        caps = nodes_of(mod.to_document(), "Capability")
        self.assertNotIn("path", caps[0])

    def test_path_must_be_double_quoted(self):
        with self.assertRaises(LowerError):
            compile_doc(cap_source("    method get\n    path /orders/{}\n"))

    def test_path_must_be_one_token_no_spaces(self):
        with self.assertRaises(LowerError):
            compile_doc(cap_source('    method get\n    path "/orders/" "{}"\n'))

    def test_path_must_start_with_a_slash(self):
        with self.assertRaises(LowerError):
            compile_doc(cap_source('    method get\n    path "orders/{}"\n'))

    def test_path_with_no_placeholder_is_refused(self):
        """A `path` with no `{}` would compile and then do nothing at run
        time — no `with` clause can ever reach it, and none is required to
        — the exact 'parses but the runtime ignores it' shape this language
        forbids. A fixed path belongs in the endpoint URL, not here."""
        with self.assertRaises(LowerError) as ctx:
            compile_doc(cap_source('    method get\n    path "/health"\n'))
        self.assertIn("placeholder", str(ctx.exception))

    def test_path_declared_twice_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(cap_source(
                '    method get\n    path "/a/{}"\n    path "/b/{}"\n',
                call_line="    call PaymentGateway with order.id as p\n"))
        self.assertIn("twice", str(ctx.exception))


class IdempotencyGateTest(unittest.TestCase):

    def test_post_with_retry_emits_a_warning(self):
        mod = compile_doc(cap_source(
            "    method post\n    retry 3 backoff 200ms\n"))
        codes = [d.code for d in mod.diagnostics.all()]
        self.assertIn("retry-on-non-idempotent", codes)

    def test_patch_with_retry_emits_a_warning(self):
        mod = compile_doc(cap_source(
            "    method patch\n    retry 3 backoff 200ms\n"))
        codes = [d.code for d in mod.diagnostics.all()]
        self.assertIn("retry-on-non-idempotent", codes)

    def test_get_with_retry_emits_no_warning(self):
        mod = compile_doc(cap_source(
            "    method get\n    retry 3 backoff 200ms\n"))
        codes = [d.code for d in mod.diagnostics.all()]
        self.assertNotIn("retry-on-non-idempotent", codes)

    def test_put_with_retry_emits_no_warning(self):
        mod = compile_doc(cap_source(
            "    method put\n    retry 3 backoff 200ms\n"))
        codes = [d.code for d in mod.diagnostics.all()]
        self.assertNotIn("retry-on-non-idempotent", codes)

    def test_delete_with_retry_emits_no_warning(self):
        mod = compile_doc(cap_source(
            "    method delete\n    retry 3 backoff 200ms\n"))
        codes = [d.code for d in mod.diagnostics.all()]
        self.assertNotIn("retry-on-non-idempotent", codes)

    def test_post_with_no_retry_emits_no_warning(self):
        mod = compile_doc(cap_source("    method post\n"))
        codes = [d.code for d in mod.diagnostics.all()]
        self.assertNotIn("retry-on-non-idempotent", codes)

    def test_the_new_code_is_registered_with_a_severity(self):
        self.assertIn("retry-on-non-idempotent", CODES)
        self.assertEqual(SEVERITY_OF["retry-on-non-idempotent"], "warning")


class CallWithPathArgsTest(unittest.TestCase):

    def test_with_one_ref_binds_path_args_matching_one_placeholder(self):
        mod = compile_doc(cap_source(
            '    method get\n    path "/orders/{}"\n',
            call_line="    call PaymentGateway with order.id as p\n"))
        calls = nodes_of(mod.to_document(), "NetworkCall")
        self.assertEqual(calls[0]["path_args"], ["order.id"])
        self.assertEqual(calls[0]["result"], "p")

    def test_with_and_no_as_is_accepted_unbound(self):
        mod = compile_doc(cap_source(
            '    method get\n    path "/orders/{}"\n',
            call_line="    call PaymentGateway with order.id\n"))
        calls = nodes_of(mod.to_document(), "NetworkCall")
        self.assertEqual(calls[0]["path_args"], ["order.id"])
        self.assertNotIn("result", calls[0])

    def test_with_two_refs_matches_two_placeholders(self):
        mod = compile_doc(cap_source(
            '    method get\n    path "/orders/{}/items/{}"\n',
            call_line="    call PaymentGateway with order.id order.sku as p\n"))
        calls = nodes_of(mod.to_document(), "NetworkCall")
        self.assertEqual(calls[0]["path_args"], ["order.id", "order.sku"])

    def test_no_with_clause_leaves_no_path_args_field(self):
        mod = compile_doc(cap_source("    method get\n"))
        calls = nodes_of(mod.to_document(), "NetworkCall")
        self.assertNotIn("path_args", calls[0])

    def test_placeholder_count_mismatch_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(cap_source(
                '    method get\n    path "/orders/{}"\n',
                call_line="    call PaymentGateway with order.id order.sku as p\n"))
        self.assertIn("placeholder", str(ctx.exception))

    def test_with_needs_a_declared_path_to_substitute_into(self):
        with self.assertRaises(LowerError) as ctx:
            compile_doc(cap_source(
                "    method get\n",
                call_line="    call PaymentGateway with order.id as p\n"))
        self.assertIn("path", str(ctx.exception))

    def test_bare_with_needs_at_least_one_reference(self):
        with self.assertRaises(LowerError):
            compile_doc(cap_source(
                '    method get\n    path "/orders/{}"\n',
                call_line="    call PaymentGateway with as p\n"))

    def test_a_malformed_reference_argument_is_refused(self):
        with self.assertRaises(LowerError):
            compile_doc(cap_source(
                '    method get\n    path "/orders/{}"\n',
                call_line="    call PaymentGateway with Order.Id as p\n"))

    def test_a_third_keyword_that_is_neither_with_nor_as_is_still_refused(self):
        with self.assertRaises(LowerError):
            compile_doc(cap_source(
                "    method get\n",
                call_line="    call PaymentGateway to p\n"))


class IrSchemaGateTest(unittest.TestCase):
    """RFC-0027 §2 precedent: new optional fields must validate against the
    published schema, not just against the lowering code that emits them."""

    def test_a_capability_with_retry_breaker_path_validates_against_the_schema(self):
        import jsonschema

        mod = compile_doc(cap_source(
            '    method get\n'
            '    retry 3 backoff 200ms jitter\n'
            '    breaker after 10 within 1m\n'
            '    path "/orders/{}"\n',
            call_line="    call PaymentGateway with order.id as p\n"))
        doc = mod.to_document()
        schema_path = os.path.join(REPO_ROOT, "schemas", "lir.schema.json")
        with open(schema_path, encoding="utf-8") as fh:
            schema = json.load(fh)
        jsonschema.validate(doc, schema)


if __name__ == "__main__":
    unittest.main()

"""Issue #54: `given` reaches the whole input namespace, not just the first entity.

The 2026-08-07 re-measurement filed three frictions that share one line. The spec
runner built its payload from `sample_payload([first_entity])` and resolved field
givens against that one entity, while every execution path — `lnpl run`,
`lnpl diff`, mode B's host — uses `sample_payload(all_entities)`. RFC-0015 §G15.2
(rfcs/0015-value-semantics.md:203) defines the input namespace as "the union of
every declared entity's fields", so the runner was the narrow one:

- r1 N-4 (major): `given quantity 2` refused because `quantity` belongs to the
  SECOND entity, blocking the qty=0 boundary spec.
- r2 N-2 (major): a read-row guard could not be made true, because the guard's
  other operand (`input.requestedAt`, a second-entity field) was absent from the
  payload and unsettable. Measured: `stored` was applying correctly the whole
  time; injecting only `requestedAt` took the run from steps=1 to steps=2.
- r4 F-6: `no priorNotification` refused for the same reason.

`input.<field>` is the canonical dotted spelling RFC-0015 §G15.2 already uses in
guards; the bare name means the same thing there, so it means the same thing here.
The default payload derivation is deliberately NOT widened — issue #48's contract
(spec.py) keeps a Presence guard on another entity's absent field observable.
"""

import unittest

from lnpl.interp import refinement_index
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.spec import SpecError, _payload_from_given, extract, run_manifest

# Two entities; the workflow reads the FIRST and guards on a field of the SECOND.
# `quantity` is exactly the shape r1 N-4 could not express.
TWO_ENTITY = """
capability postgres

entity Product
    field
        id UUID
        name Text
        stock Integer

entity Order
    field
        id UUID
        quantity Integer
        placedAt DateTime

workflow PlaceOrder
    find product
    when product.stock >= input.quantity
    create order
    spec
        given
            stored Product stock 5
            input.quantity 2
        when
            place order
        expect
            completed
            steps 2
"""

# r2 N-2, reconstructed inline (qa/ is read-only). The guard needs BOTH a stored
# row and an input field that no `sample_payload` of the first entity produces.
REFUND = """
capability postgres

entity Payment
    field
        id UUID
        amountCents Integer
        createdAt DateTime

entity Refund
    field
        id UUID
        paymentId UUID
        amountCents Integer
        requestedAt DateTime

workflow RefundRequest
    read payment
    when input.requestedAt - payment.createdAt <= 30d and input.amountCents <= payment.amountCents
    create refund
    spec
        given
            stored payment id 3f2504e0-4f89-41d3-9a0c-0305e82c3301
            stored payment amountCents 5
            stored payment createdAt 2026-07-31T09:00:00Z
            input.amountCents 3
            input.requestedAt %s
        when
            refund request
        expect
            completed
            steps %d
"""

# Same field name in two entities, different declared types — D5's tie-break.
DUP_FIELD = """
capability postgres

entity First
    field
        id UUID
        code Text

entity Second
    field
        id UUID
        code Integer

workflow Run
    validate first
    spec
        given
            input.code 42
        when
            run
        expect
            completed
"""

PRODUCT_ENTITY = {"id": "entity.product", "name": "Product",
                  "fields": [{"name": "id", "type": "UUID"},
                             {"name": "stock", "type": "Integer"}]}


def build(src, module="m"):
    decls = parse(src)
    return lower(decls, module).to_document(), extract(decls, module)


def payload_and_stored(src, case=0):
    doc, manifest = build(src)
    entity = next(n for n in doc["nodes"] if n["kind"] == "Entity")
    return _payload_from_given(manifest["cases"][case]["given"], entity,
                               refinement_index(doc), doc)


def payload_for(src, case=0):
    return payload_and_stored(src, case)[0]


class TestInputFieldForm(unittest.TestCase):
    """`input.<field> <value>` resolves against every declared entity."""

    def test_a_second_entity_field_is_settable(self):
        # r1 N-4: this exact line was `unsupported given`.
        self.assertEqual(payload_for(TWO_ENTITY)["quantity"], 2)

    def test_a_first_entity_field_is_still_settable(self):
        src = TWO_ENTITY.replace("input.quantity 2", "input.stock 7")
        self.assertEqual(payload_for(src)["stock"], 7)

    def test_zero_is_settable_as_an_integer(self):
        # The boundary r1 N-4 named: qty=0 had to be measured outside the language.
        src = TWO_ENTITY.replace("input.quantity 2", "input.quantity 0")
        self.assertEqual(payload_for(src)["quantity"], 0)

    def test_an_undeclared_input_field_is_refused_naming_the_union(self):
        src = TWO_ENTITY.replace("input.quantity 2", "input.nosuchfield 1")
        with self.assertRaises(SpecError) as ctx:
            payload_for(src)
        message = str(ctx.exception)
        self.assertIn("no declared entity", message)
        self.assertIn("nosuchfield", message)
        # The accepted set is named, not merely implied (unenforced-declarations #1).
        self.assertIn("quantity", message)
        self.assertIn("stock", message)

    def test_the_diagnostic_cites_the_governing_rule(self):
        src = TWO_ENTITY.replace("input.quantity 2", "input.nosuchfield 1")
        with self.assertRaises(SpecError) as ctx:
            payload_for(src)
        self.assertIn("RFC-0015", str(ctx.exception))


class TestNoInputFieldForm(unittest.TestCase):
    """`no input.<field>` drops the field from the input payload."""

    def test_a_present_field_is_dropped(self):
        src = TWO_ENTITY.replace("input.quantity 2", "no input.stock")
        self.assertNotIn("stock", payload_for(src))

    def test_dropping_an_already_absent_field_is_a_no_op_not_an_error(self):
        # r4 F-6: `no priorNotification` named a field the payload never had.
        # Asserting absence is legitimate; it must not raise, and must not
        # disturb the rest of the payload.
        src = TWO_ENTITY.replace("input.quantity 2", "no input.quantity")
        payload = payload_for(src)
        self.assertNotIn("quantity", payload)
        self.assertIn("stock", payload)

    def test_an_undeclared_name_is_refused(self):
        src = TWO_ENTITY.replace("input.quantity 2", "no input.nosuchfield")
        with self.assertRaises(SpecError) as ctx:
            payload_for(src)
        self.assertIn("nosuchfield", str(ctx.exception))


class TestBareFormWidens(unittest.TestCase):
    """RFC-0015 §G15.2: the bare name points at the same input payload."""

    def test_a_second_entity_field_is_settable_bare(self):
        src = TWO_ENTITY.replace("input.quantity 2", "quantity 2")
        self.assertEqual(payload_for(src)["quantity"], 2)

    def test_bare_no_reaches_the_second_entity_too(self):
        src = TWO_ENTITY.replace("input.quantity 2",
                                 "quantity 2\n            no quantity")
        self.assertNotIn("quantity", payload_for(src))

    def test_a_name_no_entity_declares_is_still_refused(self):
        src = TWO_ENTITY.replace("input.quantity 2", "frobnicate widgets")
        with self.assertRaises(SpecError):
            payload_for(src)


class TestGuardTrueContractualization(unittest.TestCase):
    """r2 N-2: both directions of the read-row guard, asserted on executed steps.

    Per qa-exploratory-guard-true-path-coverage: run each guard direction at
    least once and assert on the executed-step list, not on skip markers.
    """

    def test_the_guard_true_path_runs_the_guarded_step(self):
        # Before #54 this was FAIL — steps=1 want=2, with `stored` correct and
        # `input.requestedAt` unrepresentable.
        doc, manifest = build(REFUND % ("2026-08-01T09:00:00Z", 2), "refund")
        passed, failed, lines = run_manifest(manifest, doc)
        self.assertEqual(failed, 0, lines)
        self.assertEqual(passed, 2)

    def test_the_guard_false_path_skips_it(self):
        # The control pair: same module, only the date moves outside the window.
        doc, manifest = build(REFUND % ("2026-10-31T09:00:00Z", 1), "refund")
        passed, failed, lines = run_manifest(manifest, doc)
        self.assertEqual(failed, 0, lines)
        self.assertEqual(passed, 2)

    def test_the_two_directions_disagree_on_the_executed_step_count(self):
        # Guards against a test that would pass whatever the guard did: the same
        # `expect steps 2` must FAIL on the guard-false module.
        doc, manifest = build(REFUND % ("2026-10-31T09:00:00Z", 2), "refund")
        _passed, failed, _lines = run_manifest(manifest, doc)
        self.assertEqual(failed, 1)

    def test_stored_still_seeds_the_row_it_always_did(self):
        _payload, stored = payload_and_stored(REFUND % ("2026-08-01T09:00:00Z", 2))
        self.assertEqual(stored["entity.payment"]["amountCents"], 5)


class TestDuplicateFieldNameTypes(unittest.TestCase):
    """A name two entities declare coerces by the LAST declaration.

    That is `sample_payload`'s own overwrite order (interp.py) — the spec runner
    must produce the payload `lnpl run` would have produced for the same module.
    """

    def test_the_last_declaring_entity_wins(self):
        self.assertEqual(payload_for(DUP_FIELD)["code"], 42)

    def test_reversing_the_declared_types_reverses_the_coercion(self):
        # Same declaration ORDER, types swapped between the two entities: the
        # last block now declares Text, so the value must stay a raw string.
        # Without this pair the first assertion could pass on a rule that simply
        # always coerced digits.
        src = (DUP_FIELD.replace("code Text", "code TMP")
                        .replace("code Integer", "code Text")
                        .replace("code TMP", "code Integer"))
        self.assertEqual(payload_for(src)["code"], "42")


class TestScopeAndFallback(unittest.TestCase):
    """The edges: empty given, the document-less call, and the untouched default."""

    def test_an_empty_given_leaves_the_sample_payload_alone(self):
        doc, _manifest = build(TWO_ENTITY)
        entity = next(n for n in doc["nodes"] if n["kind"] == "Entity")
        payload, stored = _payload_from_given([], entity, refinement_index(doc), doc)
        self.assertEqual(stored, {})
        self.assertIn("stock", payload)
        self.assertNotIn("quantity", payload)

    def test_without_a_document_the_union_is_the_one_entity_given(self):
        # Existing call sites pass a single entity and no document; they must
        # keep seeing exactly that entity's fields.
        payload, _stored = _payload_from_given(["input.stock 3"], PRODUCT_ENTITY)
        self.assertEqual(payload["stock"], 3)
        with self.assertRaises(SpecError):
            _payload_from_given(["input.quantity 1"], PRODUCT_ENTITY)

    def test_the_default_payload_still_omits_unvalidated_entities(self):
        # Issue #48's contract, deliberately unchanged: a Presence guard reading
        # another entity's absent field must stay observable. Widening the
        # RESOLUTION namespace must not widen the DEFAULT sample — so a
        # second-entity field the given never mentions stays absent.
        self.assertNotIn("placedAt", payload_for(TWO_ENTITY))
        without_given = "\n".join(
            line for line in (REFUND % ("2026-08-01T09:00:00Z", 2)).splitlines()
            if "input.requestedAt" not in line)
        self.assertNotIn("requestedAt", payload_for(without_given))

    def test_an_explicit_input_given_is_what_puts_it_there(self):
        # The other half of the pair above: absence is the default, presence is
        # the author's explicit act.
        self.assertIn("requestedAt",
                      payload_for(REFUND % ("2026-08-01T09:00:00Z", 2)))


if __name__ == "__main__":
    unittest.main()

"""`derived` field direction (issue #95).

An entity field marked `derived` is server-computed, not client-supplied: the
brief's own regression is `Order{total, placedAt}` being *required in the
payload* despite being values only the server ever produces. `derived` closes
that trust-boundary inversion in four places, each with its own test class
below:

  * `lower.py`  — the field clause accepts an optional third token, `derived`
    (TestFieldParsing).
  * `interp.py` `validate_effect` — a derived field is excluded from the
    "must be present" check and rejected outright if the payload supplies it
    anyway (TestValidatePolicy). Both mode A (the interpreter) and mode B
    (`backend._validation_fails`) call this one function, so a single change
    covers both (see the function's own docstring).
  * `interp.py` `sample_payload` — the default fixture `lnpl run`/mode B build
    synthesize must not manufacture a value for a field the client can never
    send (TestSamplePayload) — otherwise every derived-field entity would
    fail its own default-payload validation forever.
  * `openapi.py` `_entity_schema` — a derived field is dropped from
    `required` and marked `readOnly: true`, the same shared-schema mechanism
    the codebase already uses for `Password`'s `writeOnly` (TestOpenApi).
  * `diagnostics.py` — `derived-never-assigned` (warning): a workflow that
    `create`s an entity with a derived field, and never `set`/`format`s it
    anywhere in that workflow, is silently dropping the value RFC-0021's
    visibility contract says must be reported (TestNeverAssignedDiagnostic).
"""

import unittest

from lnpl.diagnostics import CODES, SEVERITY_OF
from lnpl.interp import Interpreter, sample_payload
from lnpl.lower import LowerError, lower
from lnpl.openapi import generate
from lnpl.parser import parse
from lnpl.serve import map_result


def compile_doc(src, module="mod"):
    return lower(parse(src), module).to_document()


def compile_mod(src, module="mod"):
    return lower(parse(src), module)


def entity_named(doc, name):
    return next(n for n in doc["nodes"] if n["kind"] == "Entity" and n["name"] == name)


def only_workflow_id(doc):
    return next(n for n in doc["nodes"] if n["kind"] == "Workflow")["id"]


def only_operation(spec):
    return next(iter(spec["paths"].values()))["post"]


ORDER_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"


# One entity, one derived field (`total`) and two non-derived fields (`id`,
# `quantity`) — every payload-shaped test below shares this fixture so a
# passing case and a failing case differ by exactly one payload key.
ORDER_SRC = """
capability postgres

entity Order
    field
        id UUID
        quantity Integer
        total Integer derived

service OrderService
    policy
        timeout 5s

workflow PlaceOrder
    validate input
    create order
"""

# Same shape, but `total` is filled by `set` after an explicit `read` — the
# only legal way to combine `create` and `set` on one entity in this language
# (`set`'s target must name a row this workflow already read; RFC-0012 §G12.5).
ASSIGNED_SRC = """
capability postgres

entity Order
    field
        id UUID
        quantity Integer
        total Integer derived

service OrderService
    policy
        timeout 5s

workflow PlaceOrder
    create order
    read order
    set order.total to 5
"""

# `format` (issue #94, t94) is the other assignment verb D5 names — a second
# fixture is what proves the never-assigned check accepts either, not just `set`.
FORMAT_ASSIGNED_SRC = """
capability postgres

entity Order
    field
        id UUID
        quantity Integer
        label Text derived

service OrderService
    policy
        timeout 5s

workflow PlaceOrder
    create order
    read order
    format order.label from "order-{}" with order.id
"""


class TestFieldParsing(unittest.TestCase):
    """`lower.py`: the field clause grows an optional third token."""

    def test_a_derived_field_carries_the_marker(self):
        doc = compile_doc(ORDER_SRC)
        fields = {f["name"]: f for f in entity_named(doc, "Order")["fields"]}
        self.assertTrue(fields["total"]["derived"])

    def test_a_plain_field_carries_no_derived_key_at_all(self):
        # `.get("derived", False)` is the convention `openapi.py` already
        # uses for `required` — the byte-identical guarantee (D6) depends on
        # an untouched field never gaining a new dict key.
        doc = compile_doc(ORDER_SRC)
        fields = {f["name"]: f for f in entity_named(doc, "Order")["fields"]}
        self.assertNotIn("derived", fields["id"])
        self.assertNotIn("derived", fields["quantity"])

    def test_every_field_of_an_entity_may_be_derived(self):
        # Boundary: nothing about `derived` presumes a plain field remains.
        src = """
entity Snapshot
    field
        id UUID derived
        total Integer derived

service SnapshotService
workflow TakeSnapshot
    validate input
"""
        doc = compile_doc(src)
        fields = entity_named(doc, "Snapshot")["fields"]
        self.assertTrue(all(f["derived"] for f in fields))

    def test_an_unknown_third_token_is_a_lower_error(self):
        src = """
entity Order
    field
        id UUID
        total Integer computed

service OrderService
workflow Noop
    validate input
"""
        with self.assertRaises(LowerError):
            lower(parse(src), "mod")

    def test_a_fourth_token_is_a_lower_error(self):
        src = """
entity Order
    field
        id UUID
        total Integer derived extra

service OrderService
workflow Noop
    validate input
"""
        with self.assertRaises(LowerError):
            lower(parse(src), "mod")


class TestValidatePolicy(unittest.TestCase):
    """`interp.validate_effect`: exclude from required, reject if supplied."""

    def test_a_payload_without_the_derived_field_completes(self):
        doc = compile_doc(ORDER_SRC, "order")
        interp = Interpreter(doc, repo_rows={})
        result = interp.run_workflow(only_workflow_id(doc),
                                     {"id": ORDER_ID, "quantity": 2})
        self.assertEqual(result["status"], "completed")
        self.assertEqual((200, None), map_result(result))

    def test_a_payload_supplying_the_derived_field_is_rejected_with_its_name(self):
        doc = compile_doc(ORDER_SRC, "order")
        interp = Interpreter(doc, repo_rows={})
        result = interp.run_workflow(
            only_workflow_id(doc),
            {"id": ORDER_ID, "quantity": 2, "total": 999})
        self.assertEqual(result["status"], "failed")
        self.assertIn("total", result["failure_reason"])
        self.assertEqual((400, "validation-failed"), map_result(result))

    def test_a_missing_non_derived_field_is_still_rejected(self):
        # Regression: excluding `derived` from the required check must not
        # loosen the check for every other field.
        doc = compile_doc(ORDER_SRC, "order")
        interp = Interpreter(doc, repo_rows={})
        result = interp.run_workflow(only_workflow_id(doc), {"id": ORDER_ID})
        self.assertEqual(result["status"], "failed")
        self.assertIn("quantity", result["failure_reason"])
        self.assertEqual((400, "validation-failed"), map_result(result))

    def test_an_entity_whose_every_field_is_derived_accepts_an_empty_payload(self):
        src = """
capability postgres

entity Snapshot
    field
        id UUID derived
        total Integer derived

service SnapshotService
    policy
        timeout 5s

workflow TakeSnapshot
    validate input
"""
        doc = compile_doc(src, "snap")
        interp = Interpreter(doc, repo_rows={})
        result = interp.run_workflow(only_workflow_id(doc), {})
        self.assertEqual(result["status"], "completed")


class TestSamplePayload(unittest.TestCase):
    """`interp.sample_payload`: the default fixture must not fabricate a
    value for a field the client can never send — otherwise the payload
    `lnpl run`/mode B build synthesize would fail the very validation
    TestValidatePolicy above just fixed."""

    def test_a_derived_field_is_never_in_the_default_fixture(self):
        entities = [{"kind": "Entity", "id": "entity.e",
                     "fields": [{"name": "a", "type": "Integer"},
                                {"name": "b", "type": "Integer", "derived": True}]}]
        payload = sample_payload(entities)
        self.assertEqual(set(payload), {"a"})

    def test_an_entity_of_only_derived_fields_yields_an_empty_fixture(self):
        entities = [{"kind": "Entity", "id": "entity.e",
                     "fields": [{"name": "a", "type": "Integer", "derived": True}]}]
        self.assertEqual(sample_payload(entities), {})


class TestOpenApi(unittest.TestCase):
    """`openapi._entity_schema`: excluded from `required`, `readOnly: true` —
    the same shared-schema mechanism `Password`/`writeOnly` already uses, so
    the request and response schema stay one `$ref` (D3: no schema split)."""

    def setUp(self):
        self.spec = generate(compile_doc(ORDER_SRC, "order"))
        self.schema = self.spec["components"]["schemas"]["Order"]

    def test_the_derived_field_is_not_required(self):
        self.assertNotIn("total", self.schema["required"])

    def test_the_derived_field_is_marked_read_only(self):
        self.assertTrue(self.schema["properties"]["total"]["readOnly"])

    def test_a_non_derived_field_stays_required_and_gains_no_read_only_key(self):
        self.assertIn("quantity", self.schema["required"])
        self.assertNotIn("readOnly", self.schema["properties"]["quantity"])

    def test_the_request_body_still_shares_the_one_component_schema(self):
        op = only_operation(self.spec)
        ref = op["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        self.assertEqual(ref, "#/components/schemas/Order")

    def test_an_entity_of_only_derived_fields_has_no_required_key_at_all(self):
        src = """
entity Snapshot
    field
        id UUID derived
        total Integer derived

service SnapshotService
workflow TakeSnapshot
    validate input
"""
        schema = generate(compile_doc(src, "snap"))["components"]["schemas"]["Snapshot"]
        self.assertNotIn("required", schema)
        self.assertTrue(schema["properties"]["id"]["readOnly"])
        self.assertTrue(schema["properties"]["total"]["readOnly"])


class TestNeverAssignedDiagnostic(unittest.TestCase):
    """`derived-never-assigned` (warning) — issue #95, same wiring t91/t98
    established: a `CODES` entry, a `SEVERITY_OF` grade, and a lowering-time
    `diagnostics.add(...)` call. `docs/ENFORCEMENT-MATRIX.md` §C and its own
    sync test (`test_enforcement_matrix.py`) cover the doc side generically —
    nothing here needs to re-check that table."""

    def test_the_code_and_its_grade_exist(self):
        self.assertIn("derived-never-assigned", CODES)
        self.assertEqual(SEVERITY_OF["derived-never-assigned"], "warning")

    def test_create_without_ever_assigning_the_derived_field_warns(self):
        mod = compile_mod(ORDER_SRC, "order")
        codes = [d.code for d in mod.diagnostics.all()]
        self.assertIn("derived-never-assigned", codes)
        hit = next(d for d in mod.diagnostics.all()
                  if d.code == "derived-never-assigned")
        self.assertIn("total", hit.message)

    def test_a_set_that_fills_it_silences_the_warning(self):
        mod = compile_mod(ASSIGNED_SRC, "order")
        codes = [d.code for d in mod.diagnostics.all()]
        self.assertNotIn("derived-never-assigned", codes)

    def test_a_format_that_fills_it_also_silences_the_warning(self):
        mod = compile_mod(FORMAT_ASSIGNED_SRC, "order")
        codes = [d.code for d in mod.diagnostics.all()]
        self.assertNotIn("derived-never-assigned", codes)

    def test_a_workflow_with_no_derived_fields_reports_nothing(self):
        src = """
capability postgres

entity Order
    field
        id UUID
        quantity Integer

service OrderService
workflow PlaceOrder
    validate input
    create order
"""
        mod = compile_mod(src, "order")
        codes = [d.code for d in mod.diagnostics.all()]
        self.assertNotIn("derived-never-assigned", codes)


if __name__ == "__main__":
    unittest.main()

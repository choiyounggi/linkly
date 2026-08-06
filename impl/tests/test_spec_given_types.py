"""Issue #46 [2][3]: `given <field> <value>` must produce a payload `run` runs.

QA measured (t4 F-5, t2 F-11) that a spec's given values stayed raw strings, so
an Integer field failed `check_semantic_type`'s isinstance check at the
`validate` step — the same values as a JSON payload passed `lnpl run`. The QA
report read this as "given replaces the payload wholesale / id is lost"; the
verified mechanism is the value TYPE, not the merge (the field-wise merge onto
`sample_payload` already existed). These tests pin the repair: Integer-shaped
fields coerce, everything else keeps the exact pre-#46 raw-string meaning.

Also issue #46 [4] (t1 F-8, t2 F-12): `stored` only matched the lowercase
binding name and reported a declared entity as "not a declared entity".
"""

import unittest

from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.spec import SpecError, _payload_from_given, extract, run_manifest
from lnpl.interp import refinement_index

RATE_SRC = """
entity Measurement
    field
        id UUID
        value Integer
        acknowledged Integer
entity Notification
    field
        id UUID
        sentAt DateTime
service RateService
    policy
        retry 3
workflow Report
    validate measurement
    find measurement
    when measurement.value > 100
    create notification
    spec
        given
            valid measurement
            id 3f2504e0-4f89-41d3-9a0c-0305e82c3301
            value 150
            acknowledged 1
        when
            report
        expect
            completed
            steps 3
            rows Notification 1
"""

TEXT_SRC = """
entity User
    field
        id UUID
        name Text
workflow Register
    validate user
    spec
        given
            name 42
        when
            register
        expect
            completed
"""

REFINE_SRC = """
refine BoundedQty of Integer
    min 1
entity Order
    field
        id UUID
        quantity BoundedQty
workflow Place
    validate order
    spec
        given
            quantity 5
        when
            place
        expect
            completed
"""


def build(src, module="m"):
    decls = parse(src)
    return lower(decls, module).to_document(), extract(decls, module)


def payload_for(src):
    doc, manifest = build(src)
    entity = next(n for n in doc["nodes"] if n["kind"] == "Entity")
    return _payload_from_given(manifest["cases"][0]["given"], entity,
                               refinement_index(doc), doc)[0]


class TestIntegerGivenCoercion(unittest.TestCase):
    def test_an_integer_field_coerces_to_int(self):
        payload = payload_for(RATE_SRC)
        self.assertEqual(payload["value"], 150)
        self.assertEqual(payload["acknowledged"], 1)

    def test_the_uuid_given_survives_alongside(self):
        # t4 F-5 blamed the id; the id was fine — pin that it stays applied.
        payload = payload_for(RATE_SRC)
        self.assertEqual(payload["id"], "3f2504e0-4f89-41d3-9a0c-0305e82c3301")

    def test_the_t4_shaped_case_runs_end_to_end(self):
        # The repro that was 0/4 FAIL before the fix (evidence/08-spec.md 시도 3).
        doc, manifest = build(RATE_SRC)
        passed, failed, lines = run_manifest(manifest, doc)
        self.assertEqual(failed, 0, lines)
        self.assertEqual(passed, 3)

    def test_a_negative_value_coerces(self):
        src = RATE_SRC.replace("value 150", "value -1")
        self.assertEqual(payload_for(src)["value"], -1)

    def test_a_non_numeric_value_stays_raw_and_fails_validation(self):
        # No silent absorption: "abc" cannot be an Integer, so the run must
        # fail at validate rather than the given being reinterpreted.
        src = RATE_SRC.replace("value 150", "value abc")
        self.assertEqual(payload_for(src)["value"], "abc")
        doc, manifest = build(src)
        _passed, failed, _lines = run_manifest(manifest, doc)
        self.assertGreater(failed, 0)

    def test_a_refinement_of_integer_coerces_via_its_base(self):
        self.assertEqual(payload_for(REFINE_SRC)["quantity"], 5)


class TestNonIntegerGivenIsUnchanged(unittest.TestCase):
    def test_a_text_field_keeps_the_raw_string(self):
        # The pre-#46 contract spelled out at the assignment site: `name 42`
        # is a valid Text and must NOT become an int.
        self.assertEqual(payload_for(TEXT_SRC)["name"], "42")


class TestStoredAcceptsTheDeclaredName(unittest.TestCase):
    STORED_SRC = """
entity Product
    field
        id UUID
        stock Integer
workflow Check
    find product
    spec
        given
            stored Product stock 0
        when
            check
        expect
            completed
"""

    def _stored(self, src):
        doc, manifest = build(src)
        entity = next(n for n in doc["nodes"] if n["kind"] == "Entity")
        return doc, _payload_from_given(manifest["cases"][0]["given"], entity,
                                        refinement_index(doc), doc)[1]

    def test_the_declared_name_is_accepted(self):
        # t1 F-8 / t2 F-12: `stored Product ...` was refused although Product
        # is declared — and `rows Product N` accepts exactly this name.
        doc, stored = self._stored(self.STORED_SRC)
        entity_id = next(n["id"] for n in doc["nodes"] if n["kind"] == "Entity")
        self.assertEqual(stored, {entity_id: {"stock": 0}})

    def test_the_binding_name_still_works(self):
        doc, stored = self._stored(
            self.STORED_SRC.replace("stored Product", "stored product"))
        entity_id = next(n["id"] for n in doc["nodes"] if n["kind"] == "Entity")
        self.assertEqual(stored, {entity_id: {"stock": 0}})

    def test_an_undeclared_name_lists_the_declared_entities(self):
        # The diagnostic must stop calling declared entities undeclared and
        # name what IS declared, so the author can branch on it.
        with self.assertRaisesRegex(SpecError, r"declared: Product"):
            self._stored(self.STORED_SRC.replace("stored Product stock 0",
                                                 "stored Basket stock 0"))

    def test_an_undeclared_field_is_still_refused(self):
        with self.assertRaisesRegex(SpecError, "does not declare"):
            self._stored(self.STORED_SRC.replace("stored Product stock 0",
                                                 "stored Product weight 0"))


if __name__ == "__main__":
    unittest.main()

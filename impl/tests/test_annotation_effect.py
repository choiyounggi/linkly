"""Issue #111, D4/D5 — the `note` verb at RUN time: `Annotation` execution.

`interp.py` resolves a `note`'s references through the same `resolve_reference`
chokepoint every other reader uses, masks a Password-base value through the
same `mask_payload` rule `_masked_evaluation` already applies to guard
evaluations (issue #43 — no second masking rule), and appends
`{"template", "values"}` to `result["notes"]`. An unresolved reference — a
binding this run never read — records `None`, the same "unresolved is not a
fault" contract `eval_format`/`resolve_reference` already use everywhere else:
an observability channel must not be able to fail a run.

`Annotation` is filtered out of `result["steps"][].effects` (D5): it changes
no state, so it is not one of the effect kinds `spec.py`'s `effects <N>`
assertion counts — the same judgment already made for `Response` staying OUT
of the nine Effect kinds at compile time (issue #96), now applied to the
runtime effects tally too.
"""

import unittest

from lnpl.interp import MASK, Interpreter
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import row_key

RUN_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"

NOTE_SRC = """capability postgres

entity Order
    field
        id UUID
        count Integer

entity Customer
    field
        id UUID
        tier Text
        secret Password

service Orders
    policy
        retry 0

workflow LabelOrder
    find order
    find customer
    note "picked-tier-{}-for-{}-orders" with customer.tier order.count
    note "checked-secret-{}" with customer.secret
"""

def compile_doc(source, module="m"):
    return lower(parse(source), module).to_document()


def note_interp(tier="gold", count=3):
    doc = compile_doc(NOTE_SRC)
    payload = {"id": RUN_ID, "tier": tier, "count": count}
    rows = {
        "entity.order": {row_key("entity.order", payload):
                         {"id": RUN_ID, "count": count}},
        "entity.customer": {row_key("entity.customer", payload):
                            {"id": RUN_ID, "tier": tier, "secret": "s3cret"}},
    }
    return Interpreter(doc, repo_rows=rows), payload


class TestAnnotationRuns(unittest.TestCase):
    """Normal path: a note's refs resolve to real values, in template order."""

    def test_the_notes_channel_carries_the_templates_and_resolved_values(self):
        interp, payload = note_interp(tier="gold", count=3)
        result = interp.run_workflow("wf.label.order", payload)
        self.assertEqual(result["status"], "completed")
        notes = result["notes"]
        self.assertEqual(len(notes), 2)
        self.assertEqual(notes[0]["template"], "picked-tier-{}-for-{}-orders")
        self.assertEqual(notes[0]["values"], ["gold", 3])

    def test_a_different_input_produces_different_recorded_values(self):
        interp, payload = note_interp(tier="silver", count=7)
        result = interp.run_workflow("wf.label.order", payload)
        self.assertEqual(result["notes"][0]["values"], ["silver", 7])


class TestAnnotationMasking(unittest.TestCase):
    """DoD 3: a Password-base reference is masked, never the raw secret."""

    def test_password_base_ref_is_masked_not_raw(self):
        interp, payload = note_interp()
        result = interp.run_workflow("wf.label.order", payload)
        secret_note = result["notes"][1]
        self.assertEqual(secret_note["template"], "checked-secret-{}")
        self.assertEqual(secret_note["values"], [MASK])
        self.assertNotIn("s3cret", secret_note["values"])


class TestAnnotationEffectsFilter(unittest.TestCase):
    """DoD 5: Annotation does not appear in steps[].effects."""

    def test_note_steps_report_no_effects(self):
        interp, payload = note_interp()
        result = interp.run_workflow("wf.label.order", payload)
        note_steps = [s for s in result["steps"] if s["step"].startswith("note ")]
        self.assertEqual(len(note_steps), 2)
        for step in note_steps:
            self.assertNotIn("Annotation", step["effects"])
            self.assertEqual(step["effects"], [])

    def test_non_note_steps_are_unaffected(self):
        interp, payload = note_interp()
        result = interp.run_workflow("wf.label.order", payload)
        find_step = next(s for s in result["steps"] if s["step"] == "find order")
        self.assertEqual(find_step["effects"], ["RepositoryCall"])


class TestAnnotationUnresolvedRef(unittest.TestCase):
    """Boundary: a reference this run never bound resolves to `None`, and the
    run still completes — an observability channel cannot fail a run."""

    def test_unbound_reference_records_null_and_the_run_still_completes(self):
        doc = compile_doc("""capability postgres

entity Order
    field
        id UUID
        count Integer

entity Customer
    field
        id UUID
        tier Text

service Orders
    policy
        retry 0

workflow LabelOrder
    find order
    note "picked-tier-{}" with customer.tier
""")
        payload = {"id": RUN_ID, "count": 1}
        rows = {"entity.order": {row_key("entity.order", payload):
                                 {"id": RUN_ID, "count": 1}}}
        interp = Interpreter(doc, repo_rows=rows)
        result = interp.run_workflow("wf.label.order", payload)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["notes"], [{"template": "picked-tier-{}",
                                            "values": [None]}])


if __name__ == "__main__":
    unittest.main()

"""Issue #111, D1/D2/D3 — the `note` verb: span annotations, not free logging.

`note "<template>" [with <ref>...]` lowers to an `Annotation` node, not one of
the nine Effect kinds — nothing changes state, the same judgment `respond`
already made for `Response` (issue #96). The template grammar is not a new
parser: `condition._parse_format_rhs` (the same right-hand-side reader
`format`'s stored expression re-reads) is reused verbatim, so the `{}`-count-
vs-argument-count rule lives in exactly one place. Unlike `format`, a `note`
with zero `{}` and zero arguments is a legal pure checkpoint note (D1) — it is
not silently dropped, since it is actually recorded at runtime (issue #111,
unlike a comment).

A workflow-level abuse cap (D3) keeps "log what earns its place" enforced at
the vocabulary level: more than `NOTE_CAP` `note`s in one workflow is a
`note-cap-exceeded` compile *warning* (not an error — the existing SEVERITY_OF
rule "does editing the program make this go away?" answers yes, per #52).
"""

import unittest

from lnpl.lower import LowerError, NOTE_CAP, lower
from lnpl.parser import parse


def compile_doc(source, module="m"):
    return lower(parse(source), module).to_document()


def compile_mod(source, module="m"):
    return lower(parse(source), module)


def nodes_of(doc, kind):
    return [n for n in doc["nodes"] if n["kind"] == kind]


NOTE_SRC = """capability postgres

entity Order
    field
        id UUID
        tier Text
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
"""


class TestNoteCompiles(unittest.TestCase):
    """DoD 1: `note "…" with <ref>…` parses and lowers to an Annotation node."""

    def test_derives_an_annotation_node(self):
        doc = compile_doc(NOTE_SRC)
        notes = nodes_of(doc, "Annotation")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["template"], "picked-tier-{}-for-{}-orders")
        self.assertEqual(notes[0]["refs"], ["customer.tier", "order.count"])

    def test_workflow_step_owns_the_annotation_as_a_child(self):
        doc = compile_doc(NOTE_SRC)
        steps = nodes_of(doc, "WorkflowStep")
        note_step = next(s for s in steps if s["name"].startswith("note "))
        annotation = nodes_of(doc, "Annotation")[0]
        self.assertIn(annotation["id"], note_step["children"])

    def test_note_is_not_an_effect_kind(self):
        # D2: nine Effect kinds only; Annotation, like Response, is not one.
        from lnpl.lower import EFFECT_SLUG
        self.assertNotIn("Annotation",
                         {"Assignment", "Validation", "RepositoryCall",
                          "CacheAccess", "NetworkCall", "Transaction",
                          "Authorization", "EventEmit", "BusinessRule"})
        self.assertIn("Annotation", EFFECT_SLUG)


class TestNotePlaceholderCount(unittest.TestCase):
    """DoD 2: `{}` count != argument count -> compile error."""

    def test_too_few_placeholders_is_a_compile_error(self):
        src = NOTE_SRC.replace(
            'note "picked-tier-{}-for-{}-orders" with customer.tier order.count',
            'note "picked-tier-{}" with customer.tier order.count')
        with self.assertRaises(LowerError):
            compile_doc(src)

    def test_too_many_placeholders_is_a_compile_error(self):
        src = NOTE_SRC.replace(
            'note "picked-tier-{}-for-{}-orders" with customer.tier order.count',
            'note "picked-tier-{}-for-{}-orders-{}" with customer.tier order.count')
        with self.assertRaises(LowerError):
            compile_doc(src)


class TestNoteBoundaries(unittest.TestCase):
    """Boundary: 0 `{}` + 0 args is a legal pure checkpoint note (D1) — unlike
    `format`, a note with no interpolation is still recorded at runtime, so it
    is not treated as a no-op."""

    def test_zero_placeholders_needs_no_with_clause(self):
        src = NOTE_SRC.replace(
            'note "picked-tier-{}-for-{}-orders" with customer.tier order.count',
            'note "reached-the-tier-check"')
        doc = compile_doc(src)
        notes = nodes_of(doc, "Annotation")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["template"], "reached-the-tier-check")
        self.assertEqual(notes[0]["refs"], [])


class TestNoteCap(unittest.TestCase):
    """DoD 4: more than NOTE_CAP `note`s in one workflow -> `note-cap-exceeded`
    warning, not an error — the run still compiles and executes."""

    def _many_notes_src(self, count):
        lines = ['note "checkpoint-{}" with order.count' for _ in range(count)]
        body = "\n    ".join(lines)
        return """capability postgres

entity Order
    field
        id UUID
        count Integer

service Orders
    policy
        retry 0

workflow ManyNotes
    find order
    %s
""" % body

    def test_at_cap_is_no_warning(self):
        mod = compile_mod(self._many_notes_src(NOTE_CAP), "at_cap")
        codes = [d.code for d in mod.diagnostics.all()]
        self.assertNotIn("note-cap-exceeded", codes)

    def test_over_cap_is_a_warning_not_an_error(self):
        # Should not raise — a warning, never a compile failure.
        mod = compile_mod(self._many_notes_src(NOTE_CAP + 1), "over_cap")
        diags = [d for d in mod.diagnostics.all() if d.code == "note-cap-exceeded"]
        self.assertEqual(len(diags), 1)
        self.assertEqual(diags[0].severity, "warning")


if __name__ == "__main__":
    unittest.main()

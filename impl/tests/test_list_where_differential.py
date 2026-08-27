"""Issue #116, D9 — a `list where` predicate as mode B's "unverified
dimension" note in the mode A/mode B differential report.

Toolchain-independent, the same design `test_differential_skips.py`'s
`compare_observations` cases already use (this module's own docstring):
`document`/`workflow_id` are the only new inputs `compare_observations`
needs for this, so a synthetic observation pair proves the note's presence
(or absence) without ever invoking mode B's compiler.
"""

import unittest

from lnpl.differential import _list_where_step_count, compare_observations
from lnpl.lower import lower
from lnpl.parser import parse

ORDERS_SOURCE = """capability postgres

entity Order
    field
        id UUID
        amount Integer

entity Report
    field
        id UUID
        totalAmount Integer

service Shop
    policy
        timeout 5s

workflow SummarizeOrders
    find report
%s
    set report.totalAmount to sum order.amount
    update report
"""


def compile_doc(body):
    return lower(parse(ORDERS_SOURCE % body), "m").to_document()


def _observation(order=("find report", "list order", "set", "update report")):
    """A minimal observation pair member — only what the four classes read
    (mirrors `test_differential_skips.py`'s own helper of the same name)."""
    return {"order": list(order),
           "effects": {name: [] for name in order},
           "status": "completed",
           "skips": [],
           "text": "\n".join(["step %s" % n for n in order] + ["status completed"])}


class TestListWhereStepCount(unittest.TestCase):

    def test_a_bare_list_counts_zero(self):
        doc = compile_doc("    list order")
        wid = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        self.assertEqual(_list_where_step_count(doc, wid), 0)

    def test_a_predicated_list_counts_one(self):
        doc = compile_doc("    list order where amount > 0")
        wid = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        self.assertEqual(_list_where_step_count(doc, wid), 1)

    def test_an_unknown_workflow_id_counts_zero(self):
        doc = compile_doc("    list order where amount > 0")
        self.assertEqual(_list_where_step_count(doc, "wf.nosuch"), 0)


class TestCompareObservationsUnverifiedDimensionNote(unittest.TestCase):
    """'일치' 미출력 테스트 (t116 DoD): a `list where` workflow's report
    carries the unverified-dimension note alongside `EQUIVALENT` — the
    verdict is not simply the bare 'differential: EQUIVALENT' text a
    predicate-free workflow gets."""

    def test_no_predicate_produces_no_note(self):
        doc = compile_doc("    list order")
        wid = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        obs = _observation()

        ok, report = compare_observations(obs, dict(obs), doc, wid)

        self.assertTrue(ok)
        self.assertTrue(any("EQUIVALENT" in line for line in report))
        self.assertFalse(any("unverified dimension" in line for line in report))

    def test_a_predicate_adds_the_unverified_dimension_note(self):
        doc = compile_doc("    list order where amount > 0")
        wid = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        obs = _observation()

        ok, report = compare_observations(obs, dict(obs), doc, wid)

        self.assertTrue(ok)
        self.assertTrue(any("EQUIVALENT" in line for line in report))
        note_lines = [l for l in report if "unverified dimension" in l]
        self.assertEqual(len(note_lines), 1)
        self.assertIn("1 `list where` step", note_lines[0])
        self.assertIn("docs/backends.md", note_lines[0])

    def test_a_divergent_pair_still_gets_the_note(self):
        """The note is additive to the verdict, not conditioned on it —
        even a DIVERGENT comparison names the extra unverified dimension."""
        doc = compile_doc("    list order where amount > 0")
        wid = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        a = _observation()
        b = _observation(order=("find report", "list order"))

        ok, report = compare_observations(a, b, doc, wid)

        self.assertFalse(ok)
        self.assertTrue(any("DIVERGENT" in line for line in report))
        self.assertTrue(any("unverified dimension" in line for line in report))

    def test_omitting_document_and_workflow_id_never_adds_a_note(self):
        """Every pre-#116 caller passes neither — behaviour is unchanged."""
        obs = _observation()

        ok, report = compare_observations(obs, dict(obs))

        self.assertTrue(ok)
        self.assertFalse(any("unverified dimension" in line for line in report))


if __name__ == "__main__":
    unittest.main()

"""Issue #108, D8 — a `parallel` block as mode B's "unverified dimension"
note in the mode A/mode B differential report. Same design issue #116's
`list where` note already established (`test_list_where_differential.py`):
`document`/`workflow_id` are the only new inputs `compare_observations`
needs, so a synthetic observation pair proves the note's presence (or
absence) without ever invoking mode B's compiler.

Mode B keeps running everything sequentially (RFC-0004 §5(#7), still open —
this issue only changed mode A), so nothing DIVERGES; the note exists so
`EQUIVALENT` is never read as "mode A's concurrency was verified too."
"""

import unittest

from lnpl.differential import _parallel_block_count, compare_observations
from lnpl.lower import lower
from lnpl.parser import parse

FANOUT_SOURCE = """capability postgres

entity Order
    field
        id UUID
        total Integer

service FanOutService
    policy
        timeout 5s

workflow FanOut
%s
"""


def compile_doc(body):
    return lower(parse(FANOUT_SOURCE % body), "m").to_document()


def _observation(order=("find order",)):
    """A minimal observation pair member — only what the four classes read
    (mirrors `test_list_where_differential.py`'s own helper)."""
    return {"order": list(order),
           "effects": {name: [] for name in order},
           "status": "completed",
           "skips": [],
           "text": "\n".join(["step %s" % n for n in order] + ["status completed"])}


class TestParallelBlockCount(unittest.TestCase):

    def test_a_workflow_with_no_parallel_block_counts_zero(self):
        doc = compile_doc("    find order")
        wid = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        self.assertEqual(_parallel_block_count(doc, wid), 0)

    def test_one_parallel_block_counts_one(self):
        doc = compile_doc("    parallel\n    find order\n    find order\n    merge")
        wid = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        self.assertEqual(_parallel_block_count(doc, wid), 1)

    def test_a_pipeline_block_is_not_counted(self):
        # Boundary: `pipeline` still expands sequentially in both modes
        # (unchanged by this issue) — only `Concurrency` nodes count.
        # `pipeline` closes implicitly (no `merge` — that keyword closes
        # only `parallel`, references/grammar.md), so it runs to the end
        # of the workflow body here.
        doc = compile_doc("    pipeline\n    find order")
        wid = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        self.assertEqual(_parallel_block_count(doc, wid), 0)

    def test_an_unknown_workflow_id_counts_zero(self):
        doc = compile_doc("    parallel\n    find order\n    find order\n    merge")
        self.assertEqual(_parallel_block_count(doc, "wf.nosuch"), 0)


class TestCompareObservationsUnverifiedDimensionNote(unittest.TestCase):

    def test_no_parallel_block_produces_no_note(self):
        doc = compile_doc("    find order")
        wid = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        obs = _observation()

        ok, report = compare_observations(obs, dict(obs), doc, wid)

        self.assertTrue(ok)
        self.assertTrue(any("EQUIVALENT" in line for line in report))
        self.assertFalse(any("unverified dimension" in line for line in report))

    def test_a_parallel_block_adds_the_unverified_dimension_note(self):
        doc = compile_doc("    parallel\n    find order\n    find order\n    merge")
        wid = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        obs = _observation(order=("find order", "find order"))

        ok, report = compare_observations(obs, dict(obs), doc, wid)

        self.assertTrue(ok)
        self.assertTrue(any("EQUIVALENT" in line for line in report))
        note_lines = [l for l in report if "unverified dimension" in l]
        self.assertEqual(len(note_lines), 1)
        self.assertIn("1 `parallel` block", note_lines[0])
        self.assertIn("mode B runs them sequentially", note_lines[0])
        self.assertIn("docs/backends.md", note_lines[0])

    def test_a_divergent_pair_still_gets_the_note(self):
        # The note is additive to the verdict, not conditioned on it — even
        # a DIVERGENT comparison names the extra unverified dimension.
        doc = compile_doc("    parallel\n    find order\n    find order\n    merge")
        wid = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        a = _observation(order=("find order", "find order"))
        b = _observation(order=("find order",))

        ok, report = compare_observations(a, b, doc, wid)

        self.assertFalse(ok)
        self.assertTrue(any("DIVERGENT" in line for line in report))
        self.assertTrue(any("unverified dimension" in line for line in report))

    def test_a_list_where_and_a_parallel_block_both_get_their_own_note(self):
        # Boundary: the two unverified dimensions are independent notes,
        # not a single line that only fires for whichever comes first.
        doc = compile_doc(
            "    parallel\n    list order where total > 0\n    find order\n    merge")
        wid = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        obs = _observation(order=("list order", "find order"))

        ok, report = compare_observations(obs, dict(obs), doc, wid)

        self.assertTrue(ok)
        note_lines = [l for l in report if "unverified dimension" in l]
        self.assertEqual(len(note_lines), 2)
        self.assertTrue(any("list where" in l for l in note_lines))
        self.assertTrue(any("parallel" in l for l in note_lines))

    def test_omitting_document_and_workflow_id_never_adds_a_note(self):
        # Every pre-#108 caller passes neither — behaviour is unchanged.
        obs = _observation()

        ok, report = compare_observations(obs, dict(obs))

        self.assertTrue(ok)
        self.assertFalse(any("unverified dimension" in line for line in report))


if __name__ == "__main__":
    unittest.main()

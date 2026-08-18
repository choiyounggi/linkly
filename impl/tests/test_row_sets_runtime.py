"""Issue #65 / RFC-0025 — row sets and aggregation, mode A execution.

Scope is Task 04: `list` binding a RowSet into its own execution-scope
namespace (RFC-0025 §5), `sum`/`count` evaluated against it (RFC-0025 §5,
`eval_aggregate`), and the 0-row boundary. Lowering-time concerns (grammar,
static rejections, the `aggregation-orphaned-list` warning itself) are
`test_row_sets.py`'s file — this one only runs workflows.
"""

import unittest

from lnpl.interp import Interpreter
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import row_key

REPORT_ID = "r-1"

CLICKS_SOURCE = """capability postgres

entity Link
    field
        id UUID
        clicks Integer

entity Report
    field
        id UUID
        totalClicks Integer
        linkCount Integer

service Analytics
    policy
        timeout 5s

workflow SummarizeClicks
    find report
    list link
    set report.totalClicks to sum link.clicks
    set report.linkCount to count link
    update report
"""


def compile_doc(source, module="m"):
    return lower(parse(source), module).to_document()


def report_row(interp):
    return interp.repo.rows["entity.report"][row_key("entity.report", {"id": REPORT_ID})]


def run_with_links(links):
    """`CLICKS_SOURCE` seeded with one `Report` row and the given `Link` rows
    (`{row_key: {"id": ..., "clicks": ...}}`). -> (result, interp)."""
    doc = compile_doc(CLICKS_SOURCE)
    rows = {"entity.report": {row_key("entity.report", {"id": REPORT_ID}):
                              {"id": REPORT_ID}},
           "entity.link": links}
    interp = Interpreter(doc, repo_rows=rows)
    result = interp.run_workflow("wf.summarize.clicks", {"id": REPORT_ID})
    return result, interp


class TestRowSetBinding(unittest.TestCase):
    """RFC-0025 §5: `list` binds a RowSet into its own execution-scope
    namespace, separate from single-row `bindings`."""

    def test_a_completed_run_lands_the_effect(self):
        result, _ = run_with_links({"0": {"id": "0", "clicks": 5}})
        effects = [kind for step in result["steps"] for kind in step["effects"]]
        self.assertIn("RepositoryCall", effects)
        self.assertIn("Assignment", effects)

    def test_list_does_not_populate_the_single_row_bindings(self):
        """A RowSet is not a row — `result["bindings"]` (the single-row scope
        `expect result` reads) must not carry it."""
        result, _ = run_with_links({"0": {"id": "0", "clicks": 5}})
        self.assertNotIn("link", result["bindings"])
        self.assertIn("report", result["bindings"])

    def test_last_list_wins(self):
        """Two `list`s of the same entity: the second replaces the first, the
        same rule single-row binding already has (RFC-0012 §G12.2)."""
        doc = compile_doc("""capability postgres

entity Link
    field
        id UUID
        clicks Integer

entity Report
    field
        id UUID
        linkCount Integer

service Analytics
    policy
        timeout 5s

workflow Recount
    find report
    list link
    list link
    set report.linkCount to count link
    update report
""")
        rows = {"entity.report": {row_key("entity.report", {"id": REPORT_ID}):
                                  {"id": REPORT_ID}},
               "entity.link": {"0": {"id": "0", "clicks": 1},
                               "1": {"id": "1", "clicks": 2}}}
        interp = Interpreter(doc, repo_rows=rows)
        result = interp.run_workflow("wf.recount", {"id": REPORT_ID})
        self.assertEqual(result["status"], "completed")
        row = interp.repo.rows["entity.report"][
            row_key("entity.report", {"id": REPORT_ID})]
        self.assertEqual(row["linkCount"], 2)


class TestAggregateEvaluation(unittest.TestCase):
    """RFC-0025 §5: `sum`/`count` against the bound RowSet — normal, error,
    boundary."""

    # ---- normal --------------------------------------------------------
    def test_sum_and_count_over_several_rows(self):
        result, interp = run_with_links({
            "0": {"id": "0", "clicks": 5},
            "1": {"id": "1", "clicks": 3},
            "2": {"id": "2", "clicks": 0},
        })
        self.assertEqual(result["status"], "completed")
        row = report_row(interp)
        self.assertEqual(row["totalClicks"], 8)
        self.assertEqual(row["linkCount"], 3)

    def test_the_assignment_effect_is_recorded(self):
        _, interp = run_with_links({"0": {"id": "0", "clicks": 5}})
        applied = [log for log in interp.trace.to_dict()["logs"]
                  if log["message"] == "assignment applied"
                  and log["target"] == "report.totalClicks"]
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]["value"], 5)

    # ---- boundary --------------------------------------------------------
    def test_zero_rows_sum_and_count_to_zero(self):
        result, interp = run_with_links({})
        self.assertEqual(result["status"], "completed")
        row = report_row(interp)
        self.assertEqual(row["totalClicks"], 0)
        self.assertEqual(row["linkCount"], 0)

    def test_a_never_listed_entity_also_aggregates_to_zero(self):
        """RFC-0025 §5: an ABSENT RowSet binding is the same "nothing to
        aggregate" as an EMPTY one — the `aggregation-orphaned-list` warning
        (RFC-0025 §4) is a compile-time hint, not a runtime distinction."""
        doc = compile_doc("""capability postgres

entity Link
    field
        id UUID
        clicks Integer

entity Report
    field
        id UUID
        totalClicks Integer

service Analytics
    policy
        timeout 5s

workflow SummarizeClicks
    find report
    set report.totalClicks to sum link.clicks
    update report
""")
        rows = {"entity.report": {row_key("entity.report", {"id": REPORT_ID}):
                                  {"id": REPORT_ID}}}
        interp = Interpreter(doc, repo_rows=rows)
        result = interp.run_workflow("wf.summarize.clicks", {"id": REPORT_ID})
        self.assertEqual(result["status"], "completed")
        row = interp.repo.rows["entity.report"][
            row_key("entity.report", {"id": REPORT_ID})]
        self.assertEqual(row["totalClicks"], 0)

    def test_a_single_row_sums_and_counts_correctly(self):
        result, interp = run_with_links({"0": {"id": "0", "clicks": 7}})
        self.assertEqual(result["status"], "completed")
        row = report_row(interp)
        self.assertEqual(row["totalClicks"], 7)
        self.assertEqual(row["linkCount"], 1)

    # ---- error -------------------------------------------------------------
    def test_a_row_missing_the_summed_field_fails_the_run(self):
        """A `create`d row carries only `id` (`FakeRepository.execute`) —
        reachable in practice, not a hypothetical malformed document."""
        result, _ = run_with_links({"0": {"id": "0"}})
        self.assertEqual(result["status"], "failed")
        self.assertIn("has no", result["failure_reason"])
        self.assertIn("clicks", result["failure_reason"])

    def test_a_non_numeric_field_value_fails_the_run(self):
        result, _ = run_with_links({"0": {"id": "0", "clicks": "five"}})
        self.assertEqual(result["status"], "failed")
        self.assertIn("non-numeric", result["failure_reason"])

    def test_a_sum_past_the_64_bit_range_fails(self):
        result, _ = run_with_links({
            "0": {"id": "0", "clicks": 2 ** 62},
            "1": {"id": "1", "clicks": 2 ** 62},
            "2": {"id": "2", "clicks": 2 ** 62},
        })
        self.assertEqual(result["status"], "failed")
        self.assertIn("64-bit range", result["failure_reason"])


if __name__ == "__main__":
    unittest.main()

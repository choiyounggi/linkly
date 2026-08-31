"""Issue #65 / RFC-0025 — row sets and aggregation, mode A execution.
Issue #145 / RFC-0045 — `avg`/`min`/`max` widen the same evaluator.

Scope is Task 04: `list` binding a RowSet into its own execution-scope
namespace (RFC-0025 §5), `sum`/`count`/`avg`/`min`/`max` evaluated against it
(RFC-0025 §5, RFC-0045 §3-§5, `eval_aggregate`), and the 0-row boundary.
Lowering-time concerns (grammar, static rejections, the
`aggregation-orphaned-list` warning itself) are `test_row_sets.py`'s file —
this one only runs workflows.
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


def run_doc(source, workflow_id, list_rows, list_table):
    """A one-off `.lnpl` source, seeded with one `Report` row and the given
    `list_rows` under `list_table` (e.g. `"entity.payment"`).
    -> (result, interp)."""
    doc = compile_doc(source)
    rows = {"entity.report": {row_key("entity.report", {"id": REPORT_ID}):
                              {"id": REPORT_ID}},
           list_table: list_rows}
    interp = Interpreter(doc, repo_rows=rows)
    result = interp.run_workflow(workflow_id, {"id": REPORT_ID})
    return result, interp


# RFC-0045 §3/§4: `avg`/`min`/`max` over an Integer field, alongside the
# existing `sum`/`count`.
AGG_SOURCE = """capability postgres

entity Link
    field
        id UUID
        clicks Integer

entity Report
    field
        id UUID
        totalClicks Integer
        avgClicks Integer
        minClicks Integer
        maxClicks Integer

service Analytics
    policy
        timeout 5s

workflow SummarizeClicks
    find report
    list link
    set report.totalClicks to sum link.clicks
    set report.avgClicks to avg link.clicks
    set report.minClicks to min link.clicks
    set report.maxClicks to max link.clicks
    update report
"""

# RFC-0045 §3/§4/§5: the same four functions over a Money field.
MONEY_SOURCE = """capability postgres

entity Payment
    field
        id UUID
        amount Money

entity Report
    field
        id UUID
        totalAmount Money
        avgAmount Money
        minAmount Money
        maxAmount Money

service Analytics
    policy
        timeout 5s

workflow SummarizePayments
    find report
    list payment
    set report.totalAmount to sum payment.amount
    set report.avgAmount to avg payment.amount
    set report.minAmount to min payment.amount
    set report.maxAmount to max payment.amount
    update report
"""

# RFC-0045 §4: `min`/`max` over a DateTime field (`avg`(DateTime) stays
# closed — RFC-0045 §Alternatives 2 — so this fixture has no `avg` step).
EVENT_SOURCE = """capability postgres

entity Event
    field
        id UUID
        occurredAt DateTime

entity Report
    field
        id UUID
        earliestAt DateTime
        latestAt DateTime

service Analytics
    policy
        timeout 5s

workflow SummarizeEvents
    find report
    list event
    set report.earliestAt to min event.occurredAt
    set report.latestAt to max event.occurredAt
    update report
"""


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


class TestAvgMinMaxIntegerEvaluation(unittest.TestCase):
    """RFC-0045 §3/§4: `avg`/`min`/`max` over an Integer field."""

    def test_avg_uses_half_to_even_not_truncation(self):
        """D13(a): 7/2 truncates to 3 but half-to-even rounds 3.5 to 4 — a
        naive `total // count` implementation would fail this."""
        result, interp = run_doc(AGG_SOURCE, "wf.summarize.clicks",
                                 {"0": {"id": "0", "clicks": 3},
                                  "1": {"id": "1", "clicks": 4}},
                                 "entity.link")
        self.assertEqual(result["status"], "completed")
        row = report_row(interp)
        self.assertEqual(row["totalClicks"], 7)
        self.assertEqual(row["avgClicks"], 4)
        self.assertEqual(row["minClicks"], 3)
        self.assertEqual(row["maxClicks"], 4)

    def test_a_single_row_is_its_own_avg_min_and_max(self):
        result, interp = run_doc(AGG_SOURCE, "wf.summarize.clicks",
                                 {"0": {"id": "0", "clicks": 9}},
                                 "entity.link")
        self.assertEqual(result["status"], "completed")
        row = report_row(interp)
        self.assertEqual(row["avgClicks"], 9)
        self.assertEqual(row["minClicks"], 9)
        self.assertEqual(row["maxClicks"], 9)


class TestEmptyRowSetBoundary(unittest.TestCase):
    """D13(b): `sum`/`count` = 0 but `avg`/`min`/`max` fail, contrasted in
    the same workflow — RFC-0045 §3/§4."""

    def test_sum_is_zero_but_avg_fails_in_the_same_workflow(self):
        """A failed run rolls back every write (`Interpreter.run_workflow`'s
        `self.repo.rollback()`), so the contrast has to be read from the
        trace log — the same signal `test_the_assignment_effect_is_recorded`
        uses — not from `interp.repo.rows`."""
        result, interp = run_doc(AGG_SOURCE, "wf.summarize.clicks", {},
                                 "entity.link")
        self.assertEqual(result["status"], "failed")
        self.assertIn("avg-of-empty-rowset", result["failure_reason"])
        applied = {log["target"]: log["value"]
                  for log in interp.trace.to_dict()["logs"]
                  if log["message"] == "assignment applied"}
        self.assertEqual(applied.get("report.totalClicks"), 0,
                         "the `sum` assignment ran and logged 0 before the "
                         "`avg` assignment failed")
        self.assertNotIn("report.avgClicks", applied)
        self.assertNotIn("report.minClicks", applied)

    def test_min_max_of_an_empty_rowset_fails(self):
        source = AGG_SOURCE.replace(
            "    set report.totalClicks to sum link.clicks\n"
            "    set report.avgClicks to avg link.clicks\n"
            "    set report.minClicks to min link.clicks\n",
            "    set report.minClicks to min link.clicks\n")
        result, _ = run_doc(source, "wf.summarize.clicks", {}, "entity.link")
        self.assertEqual(result["status"], "failed")
        self.assertIn("min-max-of-empty-rowset", result["failure_reason"])

    def test_an_empty_money_rowsets_sum_is_plain_integer_zero(self):
        """Load-bearing decision (documented on the blackboard): `sum` over
        an empty RowSet cannot recover the target field's Money-ness from
        zero rows without a signature change the brief forbids, so it
        returns plain `0`, not RFC-0045 §5's `{"amount": "0", "currency":
        null}`."""
        source = MONEY_SOURCE.replace(
            "    set report.avgAmount to avg payment.amount\n"
            "    set report.minAmount to min payment.amount\n"
            "    set report.maxAmount to max payment.amount\n", "")
        result, interp = run_doc(source, "wf.summarize.payments", {},
                                 "entity.payment")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(report_row(interp)["totalAmount"], 0)


class TestMoneyAggregateEvaluation(unittest.TestCase):
    """RFC-0044 §4/§5 consumed via RFC-0045 §3-§5: `sum`/`avg`/`min`/`max`
    over a Money field, through `impl/lnpl/money.py`."""

    def _run(self, rows):
        return run_doc(MONEY_SOURCE, "wf.summarize.payments", rows,
                       "entity.payment")

    def test_avg_uses_half_to_even_and_sum_is_correct(self):
        """D13(a) for Money: 2003 minor / 2 truncates to 1001 (-> "10.01")
        but half-to-even rounds 1001.5 to 1002 (-> "10.02")."""
        result, interp = self._run({
            "0": {"id": "0", "amount": {"amount": "10.01", "currency": "USD"}},
            "1": {"id": "1", "amount": {"amount": "10.02", "currency": "USD"}},
        })
        self.assertEqual(result["status"], "completed")
        row = report_row(interp)
        self.assertEqual(row["totalAmount"], {"amount": "20.03", "currency": "USD"})
        self.assertEqual(row["avgAmount"], {"amount": "10.02", "currency": "USD"})

    def test_min_max_return_the_original_row_value_not_minor_units(self):
        """D10: the result must be the untouched Money dict a row carried,
        not an internal minor-unit integer."""
        row0 = {"amount": "5.00", "currency": "USD"}
        row1 = {"amount": "12.50", "currency": "USD"}
        result, interp = self._run({
            "0": {"id": "0", "amount": row0},
            "1": {"id": "1", "amount": row1},
        })
        self.assertEqual(result["status"], "completed")
        row = report_row(interp)
        self.assertEqual(row["minAmount"], row0)
        self.assertEqual(row["maxAmount"], row1)

    def test_currency_mismatch_is_a_runtime_failure_not_a_compile_error(self):
        """D13(c): `MONEY_SOURCE` compiles (proven by `_run` reaching
        `run_workflow` at all); the mismatch only fails at run time."""
        result, _ = self._run({
            "0": {"id": "0", "amount": {"amount": "10.00", "currency": "USD"}},
            "1": {"id": "1", "amount": {"amount": "10.00", "currency": "EUR"}},
        })
        self.assertEqual(result["status"], "failed")
        self.assertIn("money-currency-mismatch", result["failure_reason"])

    def test_currency_mismatch_also_fails_min_max(self):
        source = MONEY_SOURCE.replace(
            "    set report.totalAmount to sum payment.amount\n"
            "    set report.avgAmount to avg payment.amount\n", "")
        result, _ = run_doc(source, "wf.summarize.payments", {
            "0": {"id": "0", "amount": {"amount": "10.00", "currency": "USD"}},
            "1": {"id": "1", "amount": {"amount": "10.00", "currency": "EUR"}},
        }, "entity.payment")
        self.assertEqual(result["status"], "failed")
        self.assertIn("money-currency-mismatch", result["failure_reason"])

    def test_a_sum_past_the_64_bit_range_fails(self):
        """D5: Money's i64 overflow reuses `_checked()` — `money.add()` has
        no bound check of its own (t7's blackboard note)."""
        result, _ = self._run({
            "0": {"id": "0", "amount": {"amount": "9000000000000000000",
                                        "currency": "JPY"}},
            "1": {"id": "1", "amount": {"amount": "9000000000000000000",
                                        "currency": "JPY"}},
        })
        self.assertEqual(result["status"], "failed")
        self.assertIn("64-bit range", result["failure_reason"])

    def test_avg_of_an_empty_money_rowset_fails(self):
        result, _ = self._run({})
        self.assertEqual(result["status"], "failed")
        self.assertIn("avg-of-empty-rowset", result["failure_reason"])


class TestDateTimeMinMaxEvaluation(unittest.TestCase):
    """RFC-0045 §4: `min`/`max` over a DateTime field — new in this RFC."""

    def test_min_max_return_the_earliest_and_latest_instant_as_original_text(self):
        """D10: an epoch-ms integer must never leak into a DateTime field."""
        result, interp = run_doc(EVENT_SOURCE, "wf.summarize.events", {
            "0": {"id": "0", "occurredAt": "2026-06-15T12:00:00Z"},
            "1": {"id": "1", "occurredAt": "2026-01-01T00:00:00Z"},
            "2": {"id": "2", "occurredAt": "2026-12-31T23:59:59Z"},
        }, "entity.event")
        self.assertEqual(result["status"], "completed")
        row = report_row(interp)
        self.assertEqual(row["earliestAt"], "2026-01-01T00:00:00Z")
        self.assertEqual(row["latestAt"], "2026-12-31T23:59:59Z")
        self.assertIsInstance(row["earliestAt"], str)

    def test_min_max_of_an_empty_datetime_rowset_fails(self):
        result, _ = run_doc(EVENT_SOURCE, "wf.summarize.events", {},
                            "entity.event")
        self.assertEqual(result["status"], "failed")
        self.assertIn("min-max-of-empty-rowset", result["failure_reason"])


if __name__ == "__main__":
    unittest.main()

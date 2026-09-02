"""Issue #116 — `list <Entity> where ...`, mode A execution (Task 02/03 of
t116's plan): a FILTERED RowSet binds into execution scope, `sum`/`count`
see only the filtered rows, `order by`/`limit` are honored, and a driver
that does not declare `supports_predicate` gets the over-fetch-then-filter
fallback plus the `predicate-not-pushed-down` INFO trace line (D5).

Lowering-time concerns (grammar, static rejections, candidates) are
`test_list_where.py`'s file; driver-contract facts (TCK, sqlite pushdown,
fake/sqlite cross-backend agreement) are `testing.py`'s
`RepositoryDriverTCK` and `test_driver_contract.py`. This file only runs
workflows.
"""

import unittest

from lnpl.interp import FakeRepository, Interpreter
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import row_key

REPORT_ID = "r-1"

ORDERS_SOURCE = """capability postgres

entity Order
    field
        id UUID
        amount Integer
        status Text

entity Report
    field
        id UUID
        totalAmount Integer
        orderCount Integer

service Shop
    policy
        timeout 5s

workflow SummarizeOrders
    find report
    list order where amount > 10
    set report.totalAmount to sum order.amount
    set report.orderCount to count order
    update report
"""


def compile_doc(source, module="m"):
    return lower(parse(source), module).to_document()


def report_row(interp):
    return interp.repo.rows["entity.report"][row_key("entity.report", {"id": REPORT_ID})]


def run_with_orders(orders, source=ORDERS_SOURCE, repository=None, payload=None):
    """`source` seeded with one `Report` row and the given `Order` rows
    (`{row_key: {"id": ..., "amount": ..., ...}}`). -> (result, interp)."""
    doc = compile_doc(source)
    rows = {"entity.report": {row_key("entity.report", {"id": REPORT_ID}):
                              {"id": REPORT_ID}},
           "entity.order": orders}
    interp = Interpreter(doc, repo_rows=rows, repository=repository)
    result = interp.run_workflow("wf.summarize.orders", payload or {"id": REPORT_ID})
    return result, interp


class TestFilteredRowSetBinding(unittest.TestCase):
    """D5: the predicate is applied before the RowSet binds — `sum`/`count`
    (RFC-0025) see only the matching rows, exactly as if the entity had
    never had the filtered-out rows at all."""

    def test_sum_and_count_see_only_matching_rows(self):
        _, interp = run_with_orders({
            "0": {"id": "0", "amount": 5, "status": "open"},
            "1": {"id": "1", "amount": 20, "status": "open"},
            "2": {"id": "2", "amount": 30, "status": "closed"},
        })
        row = report_row(interp)
        self.assertEqual(row["totalAmount"], 50)   # 20 + 30, not 5
        self.assertEqual(row["orderCount"], 2)

    def test_predicate_matching_nothing_is_a_valid_empty_rowset(self):
        """RFC-0025 §5: an empty RowSet is a normal 0-row result, not an
        error — unchanged by a predicate that happens to match nothing."""
        result, interp = run_with_orders({
            "0": {"id": "0", "amount": 1, "status": "open"},
        })
        self.assertEqual(result["status"], "completed")
        row = report_row(interp)
        self.assertEqual(row["totalAmount"], 0)
        self.assertEqual(row["orderCount"], 0)

    def test_predicate_referencing_input_is_resolved_from_the_payload(self):
        doc = ORDERS_SOURCE.replace(
            "list order where amount > 10",
            "list order where amount > input.totalAmount")
        result, interp = run_with_orders(
            {"0": {"id": "0", "amount": 5}, "1": {"id": "1", "amount": 50}},
            source=doc, payload={"id": REPORT_ID, "totalAmount": 10})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(report_row(interp)["orderCount"], 1)

    def test_equality_predicate_against_a_bound_rows_field(self):
        """D2's motivating case at runtime: a Text field's equality against
        a single-row binding field, pushed down and correctly filtering."""
        doc = """capability postgres

entity Customer
    field
        id UUID
        tier Text

entity Order
    field
        id UUID
        amount Integer
        tier Text

entity Report
    field
        id UUID
        totalAmount Integer
        orderCount Integer

service Shop
    policy
        timeout 5s

workflow SummarizeOrders
    find customer
    find report
    list order where tier == customer.tier
    set report.totalAmount to sum order.amount
    set report.orderCount to count order
    update report
"""
        compiled = lower(parse(doc), "m").to_document()
        rows = {
            "entity.customer": {row_key("entity.customer", {"id": REPORT_ID}):
                                {"id": REPORT_ID, "tier": "gold"}},
            "entity.report": {row_key("entity.report", {"id": REPORT_ID}):
                              {"id": REPORT_ID}},
            "entity.order": {
                "0": {"id": "0", "amount": 7, "tier": "gold"},
                "1": {"id": "1", "amount": 3, "tier": "silver"},
            },
        }
        interp = Interpreter(compiled, repo_rows=rows)
        result = interp.run_workflow("wf.summarize.orders", {"id": REPORT_ID})
        self.assertEqual(result["status"], "completed")
        row = interp.repo.rows["entity.report"][row_key("entity.report", {"id": REPORT_ID})]
        self.assertEqual(row["totalAmount"], 7)
        self.assertEqual(row["orderCount"], 1)


    def test_equality_predicate_against_the_caller_scope(self):
        """issue #119's `caller.<field>` namespace, reused as a `list
        where` right side — the resolver must thread the run's verified
        `caller` scope through, not silently treat it as absent."""
        doc = """capability postgres

entity Order
    field
        id UUID
        createdBy UUID
        amount Integer

entity Report
    field
        id UUID
        totalAmount Integer
        orderCount Integer

service Shop
    policy
        timeout 5s

workflow SummarizeOrders
    find report
    list order where createdBy == caller.subject
    set report.totalAmount to sum order.amount
    set report.orderCount to count order
    update report
"""
        compiled = lower(parse(doc), "m").to_document()
        rows = {
            "entity.report": {row_key("entity.report", {"id": REPORT_ID}):
                              {"id": REPORT_ID}},
            "entity.order": {
                "0": {"id": "0", "createdBy": "user-1", "amount": 7},
                "1": {"id": "1", "createdBy": "user-2", "amount": 9},
            },
        }
        interp = Interpreter(compiled, repo_rows=rows,
                             claims={"sub": "user-1"})
        result = interp.run_workflow("wf.summarize.orders", {"id": REPORT_ID})
        self.assertEqual(result["status"], "completed")
        row = interp.repo.rows["entity.report"][row_key("entity.report", {"id": REPORT_ID})]
        self.assertEqual(row["orderCount"], 1)
        self.assertEqual(row["totalAmount"], 7)


class TestOrderByAndLimitExecution(unittest.TestCase):
    """D7/D5: `order by`/`limit` reach the driver and shape the bound
    RowSet — observed here through `count`, since the RowSet itself is not
    directly assertable outside an aggregate (RFC-0025 §5)."""

    def test_limit_caps_the_rowset(self):
        doc = ORDERS_SOURCE.replace(
            "list order where amount > 10",
            "list order where amount > 0 order by amount desc limit 1")
        _, interp = run_with_orders({
            "0": {"id": "0", "amount": 5}, "1": {"id": "1", "amount": 50},
            "2": {"id": "2", "amount": 25},
        }, source=doc)
        row = report_row(interp)
        self.assertEqual(row["orderCount"], 1)
        self.assertEqual(row["totalAmount"], 50)  # the highest, `desc`


class _NoPushdownRepository(FakeRepository):
    """A driver that has NOT opted into predicate pushdown (issue #116, D5)
    — `query`'s old one-argument shape only. If `interp.Interpreter` ever
    called it with `predicate=`/`order=`/`limit=`, this would raise
    `TypeError`, which is exactly the enforcement this fixture wants: proof
    the fallback path never sends these to a driver that never declared
    `supports_predicate`.
    """

    supports_predicate = False

    def query(self, entity_id):
        return super().query(entity_id)


class TestNonPushdownDriverFallback(unittest.TestCase):
    """D5: a driver that does not declare `supports_predicate` still
    produces the correct filtered/ordered/limited RowSet — the core
    over-fetches via the driver's plain `query(entity_id)` and applies the
    predicate itself — and logs exactly one `predicate-not-pushed-down`
    INFO trace line."""

    def test_filtering_still_works_through_the_fallback(self):
        repo = _NoPushdownRepository()
        _, interp = run_with_orders({
            "0": {"id": "0", "amount": 5}, "1": {"id": "1", "amount": 20},
        }, repository=repo)
        row = report_row(interp)
        self.assertEqual(row["orderCount"], 1)
        self.assertEqual(row["totalAmount"], 20)

    def test_logs_one_info_line_naming_the_entity(self):
        repo = _NoPushdownRepository()
        _, interp = run_with_orders({"0": {"id": "0", "amount": 20}}, repository=repo)
        info_logs = [l for l in interp.trace.logs
                    if l["message"] == "predicate-not-pushed-down"]
        self.assertEqual(len(info_logs), 1)
        self.assertEqual(info_logs[0]["level"], "INFO")
        self.assertEqual(info_logs[0]["entity"], "entity.order")

    def test_logs_the_predicate_not_pushed_down_diagnostic(self):
        repo = _NoPushdownRepository()
        _, interp = run_with_orders({"0": {"id": "0", "amount": 20}}, repository=repo)
        records = [d for d in interp.diagnostics.all()
                  if d.code == "predicate-not-pushed-down"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].severity, "info")

    def test_a_bare_list_never_emits_the_diagnostic(self):
        """No predicate/order/limit clause -> no diagnostic either, same
        condition as the existing trace-line test above."""
        doc = ORDERS_SOURCE.replace("list order where amount > 10", "list order")
        repo = _NoPushdownRepository()
        _, interp = run_with_orders({"0": {"id": "0", "amount": 5}},
                                    source=doc, repository=repo)
        self.assertEqual(
            [d for d in interp.diagnostics.all()
            if d.code == "predicate-not-pushed-down"], [])

    def test_a_bare_list_never_logs_the_fallback_line(self):
        """No predicate/order/limit clause -> the unchanged single-argument
        `query(entity_id)` call, regardless of `supports_predicate` — the
        fallback only exists for a predicate/order/limit that needs it."""
        doc = ORDERS_SOURCE.replace("list order where amount > 10", "list order")
        repo = _NoPushdownRepository()
        _, interp = run_with_orders({"0": {"id": "0", "amount": 5}},
                                    source=doc, repository=repo)
        self.assertEqual(
            [l for l in interp.trace.logs
            if l["message"] == "predicate-not-pushed-down"], [])


if __name__ == "__main__":
    unittest.main()

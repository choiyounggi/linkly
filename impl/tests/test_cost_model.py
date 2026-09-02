"""COST_TABLE / cost_model_document() and docs/cost-model.md agree (issue #164).

`cost_model.py`'s module docstring says these Big-O facts exist nowhere else
as code — the tests here check the table's own internal shape and cross-check
it against the markdown doc that is supposed to carry the same content.
"""
import os
import unittest

from lnpl.cost_model import COST_TABLE, cost_model_document

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COST_MODEL_MD = os.path.join(REPO, "docs", "cost-model.md")


class CostModelTableTest(unittest.TestCase):
    def test_has_exactly_seven_rows(self):
        # list where(pushdown 유/무 2) + order by + limit + aggregate + cache
        # get/set + single row read = 7 (brief DoD's operation list).
        self.assertEqual(len(cost_model_document()["cost_model"]), 7)

    def test_every_row_has_a_status_and_nonempty_evidence(self):
        for row in COST_TABLE:
            self.assertIn(row["status"], {"current", "contract"})
            self.assertTrue(row["evidence"])

    def test_pushdown_and_no_pushdown_share_the_on_complexity_class(self):
        # D3 regression guard: pushdown does not change scan complexity —
        # only IO/transfer volume — because there is no index on the
        # json_extract'd field.
        by_op = {row["operation"]: row for row in COST_TABLE}
        for op in ("list_where_pushdown", "list_where_no_pushdown"):
            self.assertIn("O(n)", by_op[op]["complexity"])

    def test_unknown_operation_lookup_returns_none(self):
        row = next((r for r in COST_TABLE if r["operation"] == "nope"), None)
        self.assertIsNone(row)

    def test_every_operation_appears_in_the_markdown_doc(self):
        with open(COST_MODEL_MD, encoding="utf-8") as fh:
            text = fh.read()
        for row in COST_TABLE:
            self.assertIn(row["operation"], text,
                         "%s가 docs/cost-model.md에 없다" % row["operation"])


if __name__ == "__main__":
    unittest.main()

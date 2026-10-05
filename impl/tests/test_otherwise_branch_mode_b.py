"""RFC-0062 §Mode B: `otherwise` is a recorded exemption — mode B compiles no
branch that runs on a false guard, so `build` and `diff` refuse any workflow
using it, by name, as the last link of the chain and before any toolchain
lookup. A guard whose condition alone is a plain Integer comparison mode B
already compiles is refused all the same.
"""

import os
import unittest

from lnpl import backend
from lnpl.lower import lower
from lnpl.parser import parse

from tests.test_assigned_field_guard import HEAD, UNGUARDED_DECREMENT
from tests.test_assigned_field_guard_mode_b import WF, _Refusals

PLAIN_OTHERWISE = HEAD + """    when input.quantity > 0
    create order
    otherwise
    update product
"""


def doc_of(source):
    return lower(parse(source), "shop").to_document()


class TestOtherwiseModeB(_Refusals):

    def test_emit_mlir_refuses_naming_the_guard(self):
        doc = doc_of(PLAIN_OTHERWISE)
        with self.assertRaises(backend.BackendError) as ctx:
            backend.emit_mlir(doc, WF)
        msg = str(ctx.exception)
        self.assertIn("step create order", msg)
        self.assertIn("'input.quantity > 0'", msg)
        self.assertIn("`otherwise`", msg)
        self.assertIn("RFC-0062", msg)
        self.assertIn("mode A", msg)

    def test_the_same_guard_without_otherwise_still_compiles(self):
        doc = doc_of(PLAIN_OTHERWISE.replace("    otherwise\n    update product\n",
                                             ""))
        self.assertFalse(backend.workflow_uses_otherwise(doc, WF))
        self.assertIn("scf.if", backend.emit_mlir(doc, WF))

    def test_build_refuses_without_a_toolchain(self):
        msg = self._build_refusal(doc_of(PLAIN_OTHERWISE))
        self.assertIn("`otherwise`", msg)
        self.assertIn("RFC-0062", msg)

    def test_diff_refuses_without_a_toolchain(self):
        msg = self._diff_refusal(doc_of(PLAIN_OTHERWISE))
        self.assertIn("uses `otherwise`", msg)
        self.assertIn("RFC-0062", msg)

    def test_an_otherwise_inside_a_pipeline_block_is_found(self):
        doc = doc_of(HEAD + "    pipeline place\n        create order\n"
                     "    when input.quantity > 0\n    update product\n"
                     "    otherwise\n    pipeline refund\n        create order\n")
        self.assertTrue(backend.workflow_uses_otherwise(doc, WF))

    def test_unknown_workflow_raises(self):
        with self.assertRaises(backend.BackendError):
            backend.workflow_uses_otherwise(doc_of(PLAIN_OTHERWISE), "wf.nope")

    def test_the_assigned_field_guard_is_refused_before_otherwise(self):
        source = UNGUARDED_DECREMENT + "    otherwise\n    create order\n"
        doc = doc_of(source)
        self.assertTrue(backend.workflow_uses_otherwise(doc, WF))
        self.assertTrue(backend.workflow_uses_assigned_guard_field(doc, WF))
        for msg in (self._build_refusal(doc), self._diff_refusal(doc)):
            self.assertIn("earlier step assigns", msg)
            self.assertNotIn("`otherwise`", msg)

    def test_fail_owned_by_otherwise_is_refused_as_fail_first(self):
        doc = doc_of(PLAIN_OTHERWISE.replace("    update product\n",
                                             "    fail no-quantity\n"))
        self.assertTrue(backend.workflow_uses_otherwise(doc, WF))
        for msg in (self._build_refusal(doc), self._diff_refusal(doc)):
            self.assertIn("RFC-0058", msg)
            self.assertNotIn("RFC-0062", msg)

    def test_lnpl_build_and_diff_report_the_refusal_as_rc_4(self):
        from tests.test_cli import run_cli_err
        workdir = self._workdir()
        src = os.path.join(workdir, "shop.lnpl")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(PLAIN_OTHERWISE)
        for cmd in ("diff", "build"):
            with self.subTest(cmd=cmd):
                rc, text = run_cli_err([cmd, src, "--workdir", workdir,
                                        "--workflow", WF])
                self.assertEqual(rc, 4, text)
                self.assertIn("`otherwise`", text)
                self.assertNotIn("EQUIVALENT", text)



class TestOtherwiseWithRespondTerms(_Refusals):
    """RFC-0061 x RFC-0062: an `otherwise` item that answers a `respond`
    aggregate term, in mode A and against both mode B chains."""

    def _source(self, guarded, other):
        from tests.test_respond_aggregate import HEAD as STATS, LIST_A
        return (STATS + "    %s\n    when input.quantity > 0\n    %s\n"
                "    otherwise\n    %s\n" % (LIST_A, guarded, other))

    def _run(self, quantity):
        from lnpl.interp import Interpreter
        from tests.test_respond_aggregate import (CUSTOMER_A, THREE_FOR_A,
                                                  WORKFLOW, order_rows)
        doc = doc_of(self._source("respond orderCount as count order",
                                  "respond revenue as sum order.total"))
        return Interpreter(doc, repo_rows=order_rows(*THREE_FOR_A)).run_workflow(
            WORKFLOW, {"customerId": CUSTOMER_A, "quantity": quantity})

    def test_each_branch_answers_its_own_aggregate(self):
        held = self._run(quantity=1)
        self.assertEqual(held["response"], {"orderCount": 3})
        self.assertEqual([(r["mode"], r["steps"]) for r in held["skipped"]],
                         [("otherwise", ["respond revenue as sum order.total"])])
        fell = self._run(quantity=0)
        self.assertEqual(fell["response"],
                         {"revenue": {"amount": "4.00", "currency": "USD"}})
        self.assertEqual([(r["mode"], r["steps"]) for r in fell["skipped"]],
                         [("when", ["respond orderCount as count order"])])

    def test_the_respond_term_link_fires_before_otherwise_in_both_commands(self):
        from tests.test_respond_aggregate import WORKFLOW
        doc = doc_of(self._source("respond orderCount as count order",
                                  "respond revenue as sum order.total"))
        self.assertTrue(backend.workflow_uses_otherwise(doc, WORKFLOW))
        for msg in (self._build_refusal(doc, WORKFLOW),
                    self._diff_refusal(doc, WORKFLOW)):
            self.assertIn("RFC-0061", msg)
            self.assertNotIn("RFC-0062", msg)

    def test_a_list_term_still_must_be_the_only_respond_across_branches(self):
        """RFC-0061 §4 counts `respond` steps workflow-wide, `otherwise`
        branches included — a conservative rejection, kept as is."""
        from lnpl.lower import LowerError
        with self.assertRaises(LowerError) as ctx:
            doc_of(self._source("respond list order",
                                "respond orderCount as count order"))
        self.assertIn("must be the workflow's only `respond` step",
                      str(ctx.exception))

if __name__ == "__main__":
    unittest.main()

"""RFC-0062 §Mode B: a guard reading a field an earlier step assigns is a
recorded exemption — `build` and `diff` refuse it by name, in the same chain
position, before any toolchain lookup.

Mode B compiles every condition field as an i64 parameter fixed at entry
(RFC-0008 G8), so it would compare the value before the assignment where mode
A compares the value after it. The refusal covers exactly the workflows
RFC-0015 used to reject at compile time: a guard judged before the item it
owns, so an `until` whose body assigns the field its condition reads is NOT
refused (RFC-0015 always admitted it).
"""

import os
import shutil
import tempfile
import unittest

from lnpl import backend, differential
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import default_rows

from tests.test_assigned_field_guard import (HEAD, ISSUE_REPRO, PRODUCT_ID,
                                             UNGUARDED_DECREMENT)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WF = "wf.place.order"


def doc_of(source):
    return lower(parse(source), "shop").to_document()


class _Refusals(unittest.TestCase):
    """Build/diff refusal helpers, the shape `test_differential_skips` uses."""

    def _workdir(self):
        base = os.path.join(REPO, ".claude", "tmp")
        os.makedirs(base, exist_ok=True)
        workdir = tempfile.mkdtemp(prefix="lnpl-t211b-", dir=base)
        self.addCleanup(shutil.rmtree, workdir, True)
        return workdir

    def _build_refusal(self, doc, wf=WF):
        real_tool = backend.tool

        def _forbidden(*_a, **_k):
            raise AssertionError("tool() called before the mode B exemption")
        backend.tool = _forbidden
        self.addCleanup(setattr, backend, "tool", real_tool)
        with self.assertRaises(backend.BackendError) as ctx:
            backend.build(doc, wf, self._workdir(), seeded=frozenset())
        return str(ctx.exception)

    def _diff_refusal(self, doc, wf=WF):
        real = backend.toolchain_available
        backend.toolchain_available = lambda: False
        self.addCleanup(setattr, backend, "toolchain_available", real)
        payload = {"id": PRODUCT_ID, "quantity": 2}
        with self.assertRaises(differential.DifferentialError) as ctx:
            differential.verify(doc, wf, payload, default_rows(doc, wf, payload),
                                self._workdir())
        msg = str(ctx.exception)
        self.assertNotIn("toolchain unavailable", msg)
        return msg


class TestAssignedFieldGuardModeB(_Refusals):

    def test_emit_mlir_refuses_naming_the_guard_and_the_field(self):
        with self.assertRaises(backend.BackendError) as ctx:
            backend.emit_mlir(doc_of(UNGUARDED_DECREMENT), WF)
        msg = str(ctx.exception)
        self.assertIn("step update product", msg)
        self.assertIn("'product.stock >= 0'", msg)
        self.assertIn("reads product.stock, which an earlier step assigns", msg)
        self.assertIn("RFC-0062", msg)
        self.assertIn("mode A", msg)

    def test_build_refuses_without_a_toolchain(self):
        msg = self._build_refusal(doc_of(ISSUE_REPRO))
        self.assertIn("RFC-0062", msg)
        self.assertIn("product.stock", msg)

    def test_diff_refuses_without_a_toolchain(self):
        msg = self._diff_refusal(doc_of(ISSUE_REPRO))
        self.assertIn("reads a field an earlier step assigns", msg)
        self.assertIn("RFC-0062", msg)

    def test_detector_reads_alternatives_too(self):
        source = UNGUARDED_DECREMENT.replace(
            "    when product.stock >= 0\n",
            "    when input.quantity > 100\n    or product.stock >= 0\n")
        self.assertNotEqual(source, UNGUARDED_DECREMENT)
        self.assertTrue(backend.workflow_uses_assigned_guard_field(doc_of(source), WF))

    # ---- not refused: everything RFC-0015 already admitted --------------

    def test_a_guard_above_the_assignment_is_not_refused(self):
        doc = doc_of(HEAD + "    when product.stock >= 2\n    update product\n"
                     "    set product.stock to product.stock - input.quantity\n")
        self.assertFalse(backend.workflow_uses_assigned_guard_field(doc, WF))
        self.assertIn("scf.if", backend.emit_mlir(doc, WF))

    def test_an_until_whose_body_assigns_its_own_field_is_not_refused(self):
        """The guard is judged before the item it owns, as RFC-0015 judged it;
        an unrolled-step walk would wrongly flag the loop's second round."""
        doc = doc_of(HEAD + "    until product.stock >= 3\n"
                     "    set product.stock to product.stock + 1\n")
        self.assertFalse(backend.workflow_uses_assigned_guard_field(doc, WF))

    def test_a_guard_reading_a_different_field_is_not_refused(self):
        doc = doc_of(HEAD + "    set product.stock to product.stock - input.quantity\n"
                     "    when input.quantity >= 0\n    update product\n")
        self.assertFalse(backend.workflow_uses_assigned_guard_field(doc, WF))

    # ---- errors / order -------------------------------------------------

    def test_unknown_workflow_raises(self):
        with self.assertRaises(backend.BackendError):
            backend.workflow_uses_assigned_guard_field(doc_of(ISSUE_REPRO), "wf.nope")

    def test_fail_is_refused_before_the_assigned_field_guard(self):
        """RFC-0058's link precedes RFC-0062's in both commands."""
        doc = doc_of(UNGUARDED_DECREMENT.replace("    update product\n",
                                                 "    fail out-of-stock\n"))
        self.assertTrue(backend.workflow_uses_assigned_guard_field(doc, WF))
        self.assertTrue(backend.workflow_uses_fail(doc, WF))
        for msg in (self._build_refusal(doc), self._diff_refusal(doc)):
            self.assertIn("RFC-0058", msg)
            self.assertNotIn("RFC-0062", msg)

    def test_lnpl_build_and_diff_report_the_refusal_as_rc_4(self):
        from tests.test_cli import run_cli_err
        workdir = self._workdir()
        src = os.path.join(workdir, "shop.lnpl")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(UNGUARDED_DECREMENT)
        for cmd in ("diff", "build"):
            with self.subTest(cmd=cmd):
                rc, text = run_cli_err([cmd, src, "--workdir", workdir,
                                        "--workflow", WF])
                self.assertEqual(rc, 4, text)
                self.assertIn("RFC-0062", text)
                self.assertNotIn("EQUIVALENT", text)


if __name__ == "__main__":
    unittest.main()

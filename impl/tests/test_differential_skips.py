"""Issue #44: the skip signal in the mode A/B differential check.

RFC-0008 §5 already requires the skip set and the `until` round count to be
compared, inside RFC-0004's execution-order class rather than as a fifth class.
This module is the control set for that comparison: a doctored pair proving it
goes red without any toolchain, and end-to-end runs proving the two modes really
do observe the same skips.

The comparison is on a per-STEP projection. Mode A records one entry per guard
(carrying every step the guard owns); mode B can only reconstruct a skip as
"planned but never printed", which is per step. Flattening mode A's record to
per-step entries makes the two sides directly comparable without either one
having to guess how the other groups its records.
"""

import os
import shutil
import tempfile
import unittest

from lnpl import backend, differential
from lnpl.differential import _normalise_skips, compare_observations
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import default_rows, row_key
from tests.fixtures import CHECKOUT_LNPL, UNTIL_COUNTER, guarded_source

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NEEDS_TOOLS = unittest.skipUnless(
    backend.toolchain_available(),
    "MLIR/LLVM toolchain not installed (brew install llvm)")

USER = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
        "email": "user@example.com"}


def _observation(order, skips):
    """A minimal observation pair member — only what the four classes read."""
    return {"order": list(order),
            "effects": {name: [] for name in order},
            "status": "completed",
            "skips": skips,
            "text": "\n".join(["step %s" % n for n in order] + ["status completed"])}


class TestNumericPredicateExemption(unittest.TestCase):
    """RFC-0050 §5: a workflow using `is-numeric`/`is-not-numeric` is a
    recorded mode B exemption. `verify` says so BEFORE the toolchain check,
    so the answer is the same with or without LLVM installed."""

    def _f5(self):
        from tests.test_arithmetic_and_alt_guards import F5_SOURCE
        doc = lower(parse(F5_SOURCE), "fx").to_document()
        wf = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        return doc, wf

    def _verify(self, doc, wf):
        payload = {"id": USER["id"]}
        workdir = tempfile.mkdtemp(dir=os.path.join(REPO, ".claude", "tmp")
                                   if os.path.isdir(os.path.join(REPO, ".claude", "tmp"))
                                   else None)
        self.addCleanup(shutil.rmtree, workdir, True)
        return differential.verify(doc, wf, payload,
                                   default_rows(doc, wf, payload), workdir)

    def test_verify_raises_the_recorded_exemption(self):
        doc, wf = self._f5()
        with self.assertRaises(differential.DifferentialError) as ctx:
            self._verify(doc, wf)
        self.assertIn("RFC-0050", str(ctx.exception))
        self.assertNotIn("toolchain unavailable", str(ctx.exception))

    def test_the_exemption_fires_without_a_toolchain(self):
        doc, wf = self._f5()
        real = backend.toolchain_available
        backend.toolchain_available = lambda: False
        self.addCleanup(setattr, backend, "toolchain_available", real)
        with self.assertRaises(differential.DifferentialError) as ctx:
            self._verify(doc, wf)
        self.assertIn("RFC-0050", str(ctx.exception))

    def test_a_workflow_without_the_predicate_is_not_exempted(self):
        # Control: without a toolchain, a predicate-free workflow still gets
        # the ordinary toolchain message — the exemption is scoped.
        with open(CHECKOUT_LNPL) as f:
            doc = lower(parse(f.read()), "checkout").to_document()
        wf = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        real = backend.toolchain_available
        backend.toolchain_available = lambda: False
        self.addCleanup(setattr, backend, "toolchain_available", real)
        with self.assertRaises(differential.DifferentialError) as ctx:
            self._verify(doc, wf)
        self.assertIn("toolchain unavailable", str(ctx.exception))


MONEY_BARE = """capability postgres

entity Order
    field
        id UUID
        stock Integer
        total Money

service OrderService
    policy
        timeout 5s

workflow Approve
    read order
    %s
    set order.stock to order.stock + 1
"""


class TestMoneyGuardExemption(unittest.TestCase):
    """RFC-0051 §6: a guard comparing a declared Money field is a recorded mode
    B exemption, reported before the toolchain check; a Money-shaped value an
    undeclared reference carries into mode B's condition channel is refused
    rather than zeroed (a zero would let mode B evaluate a guard mode A
    evaluates as money, and still report EQUIVALENT)."""

    def _doc(self, source):
        doc = lower(parse(source), "money").to_document()
        wf = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        return doc, wf

    def _verify(self, doc, wf, payload=None):
        payload = payload or {"id": USER["id"]}
        workdir = tempfile.mkdtemp(dir=os.path.join(REPO, ".claude", "tmp")
                                   if os.path.isdir(os.path.join(REPO, ".claude", "tmp"))
                                   else None)
        self.addCleanup(shutil.rmtree, workdir, True)
        return differential.verify(doc, wf, payload,
                                   default_rows(doc, wf, payload), workdir)

    def _without_toolchain(self):
        real = backend.toolchain_available
        backend.toolchain_available = lambda: False
        self.addCleanup(setattr, backend, "toolchain_available", real)

    def test_a_declared_money_guard_is_the_recorded_exemption(self):
        from tests.test_backend import MONEY_GUARD
        doc, wf = self._doc(MONEY_GUARD % "when order.total > order.threshold")
        with self.assertRaises(differential.DifferentialError) as ctx:
            self._verify(doc, wf)
        self.assertIn("RFC-0051", str(ctx.exception))
        self.assertIn("Money guard", str(ctx.exception))
        self.assertNotIn("toolchain unavailable", str(ctx.exception))

    def test_an_input_money_guard_is_exempted_without_a_toolchain(self):
        from tests.test_backend import MONEY_GUARD
        doc, wf = self._doc(MONEY_GUARD % "when input.total > input.threshold")
        self._without_toolchain()
        with self.assertRaises(differential.DifferentialError) as ctx:
            self._verify(doc, wf)
        self.assertIn("RFC-0051", str(ctx.exception))

    def test_a_create_as_alias_money_guard_is_exempted_without_a_toolchain(self):
        from tests.test_backend import MONEY_ALIAS_GUARD
        doc, wf = self._doc(MONEY_ALIAS_GUARD)
        self._without_toolchain()
        with self.assertRaises(differential.DifferentialError) as ctx:
            self._verify(doc, wf)
        self.assertIn("RFC-0051", str(ctx.exception))
        self.assertIn("Money guard", str(ctx.exception))

    def test_a_money_free_guard_is_not_exempted(self):
        # Control: the same document with an Integer guard gets the ordinary
        # toolchain message — the exemption is scoped to Money guards.
        from tests.test_backend import MONEY_GUARD
        doc, wf = self._doc(MONEY_GUARD % "when order.stock > 0")
        self._without_toolchain()
        with self.assertRaises(differential.DifferentialError) as ctx:
            self._verify(doc, wf)
        self.assertIn("toolchain unavailable", str(ctx.exception))

    def _observe_b(self, source, payload):
        """Drive `observe_mode_b` up to the binary run with the build and run
        stubbed, returning the condition values it would pass."""
        doc, wf = self._doc(source)
        seen = {}
        real_build, real_run = backend.build, backend.run_binary
        backend.build = lambda *a, **k: "unused"

        def run_binary(bin_path, skip=False, condition_fields=None):
            seen.update(condition_fields or {})
            return 0, ["status completed"]
        backend.run_binary = run_binary
        self.addCleanup(setattr, backend, "build", real_build)
        self.addCleanup(setattr, backend, "run_binary", real_run)
        differential.observe_mode_b(doc, wf, "unused", payload=payload)
        return seen

    def test_a_money_shaped_undeclared_value_is_refused_not_zeroed(self):
        with self.assertRaises(differential.DifferentialError) as ctx:
            self._observe_b(MONEY_BARE % "when extra > limit",
                            {"id": USER["id"], "limit": 5,
                             "extra": {"amount": "1.00", "currency": "USD"}})
        self.assertIn("'extra'", str(ctx.exception))
        self.assertIn("Money-shaped", str(ctx.exception))
        self.assertIn("RFC-0051", str(ctx.exception))

    def test_other_non_numeric_values_keep_the_zero_placeholder(self):
        # Boundary: a Presence guard's field and a plain non-Money dict still
        # take the i64 placeholder — only a Money-shaped dict is intercepted.
        seen = self._observe_b(MONEY_BARE % "when extra exists",
                               {"id": USER["id"], "extra": "abc"})
        self.assertEqual({"extra": 0}, seen)
        seen = self._observe_b(MONEY_BARE % "when extra exists",
                               {"id": USER["id"], "extra": {"amount": "1.00"}})
        self.assertEqual({"extra": 0}, seen)

    @NEEDS_TOOLS
    def test_a_money_set_without_a_money_guard_compares_equivalent(self):
        # RFC-0028 §6: an Assignment is one opaque effect marker in mode B, so
        # a Money `set` needs no mode B change and still compares.
        doc, wf = self._doc(MONEY_BARE.replace(
            "    %s\n    set order.stock to order.stock + 1",
            "    when order.stock > 0\n    set order.total to order.total * 2"))
        total = {"amount": "2.50", "currency": "USD"}
        payload = {"id": USER["id"], "stock": 1, "total": total}
        rows = {"entity.order": {row_key("entity.order", payload):
                                 {"id": USER["id"], "stock": 1,
                                  "total": dict(total)}}}
        workdir = tempfile.mkdtemp(dir=os.path.join(REPO, ".claude", "tmp"))
        self.addCleanup(shutil.rmtree, workdir, True)
        ok, report = differential.verify(doc, wf, payload, rows, workdir)
        self.assertTrue(ok, "\n".join(report))
        self.assertIn("EQUIVALENT", report[-1])


def _predicate_money_guard_doc():
    from tests.test_backend import MONEY_GUARD
    doc = lower(parse(MONEY_GUARD % "when order.total > order.threshold"),
                "money").to_document()
    wf = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
    return doc, wf


class TestLookupKeyExemption(unittest.TestCase):
    """RFC-0052 §6 (issue #175): a workflow with a `by <ref>` repository call
    is a recorded mode B exemption, reported before the toolchain check —
    never a false EQUIVALENT. A `by`-free workflow in the same module still
    compares."""

    def _doc(self, body):
        from tests.test_backend import LOOKUP_MODULE
        return lower(parse(LOOKUP_MODULE % body), "orders").to_document()

    def _workdir(self):
        base = os.path.join(REPO, ".claude", "tmp")
        os.makedirs(base, exist_ok=True)
        workdir = tempfile.mkdtemp(prefix="lnpl-t175-", dir=base)
        self.addCleanup(shutil.rmtree, workdir, True)
        return workdir

    def _verify(self, doc, wf, payload):
        return differential.verify(doc, wf, payload,
                                   default_rows(doc, wf, payload), self._workdir())

    def test_a_by_workflow_is_the_recorded_exemption_without_a_toolchain(self):
        real = backend.toolchain_available
        backend.toolchain_available = lambda: False
        self.addCleanup(setattr, backend, "toolchain_available", real)
        doc = self._doc("    find stock by input.productId")
        with self.assertRaises(differential.DifferentialError) as ctx:
            self._verify(doc, "wf.restock", {"id": "O1", "productId": "P1"})
        msg = str(ctx.exception)
        self.assertIn("lookup key", msg)
        self.assertIn("RFC-0052", msg)
        self.assertNotIn("toolchain unavailable", msg)

    @NEEDS_TOOLS
    def test_a_by_free_workflow_in_the_same_module_compares_equivalent(self):
        doc = self._doc("    find stock by input.productId")
        ok, report = self._verify(doc, "wf.audit", {"id": "O1", "productId": "P1",
                                                    "onHand": 3})
        self.assertTrue(ok, "\n".join(report))
        self.assertIn("EQUIVALENT", report[-1])

    def test_lnpl_diff_and_build_report_the_refusal_as_rc_4(self):
        from tests.test_cli import run_cli_err
        workdir = self._workdir()
        src = os.path.join(workdir, "orders.lnpl")
        from tests.test_backend import LOOKUP_MODULE
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(LOOKUP_MODULE % "    find stock by input.productId")
        for cmd in ("diff", "build"):
            with self.subTest(cmd=cmd):
                rc, text = run_cli_err([cmd, src, "--workdir", workdir,
                                        "--workflow", "wf.restock"])
                self.assertEqual(rc, 4, text)
                self.assertIn("RFC-0052", text)
                self.assertNotIn("EQUIVALENT", text)

    def _forbid_tool(self):
        real_tool = backend.tool

        def _guard(*_a, **_k):
            raise AssertionError(
                "tool() called before the mode B exemption guard")
        backend.tool = _guard
        self.addCleanup(setattr, backend, "tool", real_tool)

    def _hide_tools(self):
        """Make every mlir-opt lookup fail: tool() tries LNPL_LLVM_BIN, then
        BREW_LLVM_BIN, then PATH, so all three are emptied (and restored)."""
        from unittest import mock
        empty = self._workdir()
        patcher = mock.patch.dict(os.environ, {"PATH": empty})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("LNPL_LLVM_BIN", None)
        brew = mock.patch.object(backend, "BREW_LLVM_BIN", empty)
        brew.start()
        self.addCleanup(brew.stop)
        with self.assertRaises(backend.BackendError):
            backend.tool("mlir-opt")

    def test_build_refuses_the_lookup_before_any_toolchain_lookup(self):
        doc = self._doc("    find stock by input.productId")
        workdir = self._workdir()
        self._forbid_tool()
        with self.assertRaises(backend.BackendError) as ctx:
            backend.build(doc, "wf.restock", workdir, seeded=frozenset())
        self.assertIn("RFC-0052", str(ctx.exception))

    def test_build_refuses_a_money_guard_before_any_toolchain_lookup(self):
        doc, wf = _predicate_money_guard_doc()
        workdir = self._workdir()
        self._forbid_tool()
        with self.assertRaises(backend.BackendError) as ctx:
            backend.build(doc, wf, workdir, seeded=frozenset())
        self.assertIn("RFC-0051", str(ctx.exception))

    def test_build_still_raises_the_duration_overflow_error_first(self):
        # Placement pin: the refusal call sits after emit_lnpl_mlir, so an
        # overflowing timeout is still reported first.
        from tests.test_backend import MONEY_GUARD
        overflow_source = (MONEY_GUARD % "when order.total > order.threshold"
                           ).replace("timeout 5s", "timeout 100000000000000000d")
        doc = lower(parse(overflow_source), "money").to_document()
        wf = next(n["id"] for n in doc["nodes"] if n["kind"] == "Workflow")
        workdir = self._workdir()
        with self.assertRaises(backend.BackendError) as ctx:
            backend.build(doc, wf, workdir, seeded=frozenset())
        self.assertNotIn("RFC-0051", str(ctx.exception))
        self.assertIn("100000000000000000d", str(ctx.exception))

    def test_a_refused_lookup_document_still_leaves_the_module_on_disk(self):
        # Placement pin: the refusal call sits after the module write.
        doc = self._doc("    find stock by input.productId")
        workdir = self._workdir()
        with self.assertRaises(backend.BackendError):
            backend.build(doc, "wf.restock", workdir)
        self.assertTrue(os.path.isfile(
            os.path.join(workdir, "module.lnpl.mlir")))

    def test_build_and_diff_agree_on_a_money_and_lookup_document(self):
        from tests.test_cli import run_cli_err
        workdir = self._workdir()
        src = os.path.join(workdir, "orders.lnpl")
        from tests.test_backend import LOOKUP_MODULE
        fields = ("entity Stock\n    field\n        id Text\n"
                  "        productId Text\n        onHand Integer\n")
        source = (LOOKUP_MODULE % "    find stock by input.productId").replace(
            fields, fields + "        price Money\n        limit Money\n"
        ).replace(
            "workflow Restock\n    find stock by input.productId\n",
            "workflow Restock\n    find stock by input.productId\n"
            "    when stock.price > stock.limit\n    update stock\n")
        self.assertIn("limit Money", source)
        self.assertIn("when stock.price > stock.limit", source)
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(source)
        self._hide_tools()
        diff_rc, diff_text = run_cli_err(["diff", src, "--workdir", workdir,
                                          "--workflow", "wf.restock"])
        build_rc, build_text = run_cli_err(["build", src, "--workdir", workdir,
                                            "--workflow", "wf.restock"])
        self.assertEqual(diff_rc, 4, diff_text)
        self.assertEqual(build_rc, 4, build_text)
        self.assertIn("RFC-0051", diff_text)
        self.assertIn("RFC-0051", build_text)

    def test_build_and_emit_mlir_raise_identical_lookup_messages(self):
        doc = self._doc("    find stock by input.productId")
        self._hide_tools()
        with self.assertRaises(backend.BackendError) as build_ctx:
            backend.build(doc, "wf.restock", self._workdir())
        with self.assertRaises(backend.BackendError) as emit_ctx:
            backend.emit_mlir(doc, "wf.restock")
        self.assertEqual(str(build_ctx.exception), str(emit_ctx.exception))

    def test_build_and_emit_mlir_raise_identical_money_messages(self):
        doc, wf = _predicate_money_guard_doc()
        self._hide_tools()
        with self.assertRaises(backend.BackendError) as build_ctx:
            backend.build(doc, wf, self._workdir())
        with self.assertRaises(backend.BackendError) as emit_ctx:
            backend.emit_mlir(doc, wf)
        self.assertEqual(str(build_ctx.exception), str(emit_ctx.exception))


class TestNormaliseSkips(unittest.TestCase):
    """The projection both modes are compared on."""

    def test_a_guard_record_becomes_one_entry_per_step(self):
        records = [{"guard": "wf.w.guard.1", "mode": "when",
                    "condition": "token missing",
                    "steps": ["cache user", "load user"], "rounds": None}]
        self.assertEqual(
            _normalise_skips(records),
            [{"mode": "when", "condition": "token missing",
              "step": "cache user", "rounds": None},
             {"mode": "when", "condition": "token missing",
              "step": "load user", "rounds": None}])

    def test_the_guard_node_id_is_dropped(self):
        # Mode B's stdout has no IR node ids, so a comparison keyed on one could
        # never pass. Dropping it here is what makes the two modes comparable.
        records = [{"guard": "wf.w.guard.1", "mode": "when", "condition": "x > 0",
                    "steps": ["s"], "rounds": None}]
        self.assertNotIn("guard", _normalise_skips(records)[0])

    def test_an_until_record_keeps_its_round_count(self):
        records = [{"guard": "wf.w.guard.1", "mode": "until",
                    "condition": "counter >= 10",
                    "steps": ["step Loop"], "rounds": 0}]
        self.assertEqual(_normalise_skips(records),
                         [{"mode": "until", "condition": "counter >= 10",
                           "step": "step Loop", "rounds": 0}])

    def test_no_records_project_to_no_entries(self):
        self.assertEqual(_normalise_skips([]), [])

    def test_a_guard_owning_no_step_projects_to_no_entries(self):
        # Boundary: a record whose subtree held no WorkflowStep contributes
        # nothing rather than an entry with a missing step name.
        records = [{"guard": "wf.w.guard.1", "mode": "when", "condition": "x > 0",
                    "steps": [], "rounds": None}]
        self.assertEqual(_normalise_skips(records), [])


class TestSkipDivergenceIsDetected(unittest.TestCase):
    """The negative control: the execution-order class must go red on a skip
    the other mode does not report. No toolchain needed — the observations are
    supplied directly, the way `TestDifferentialMaskingSurface` does for the
    masking class.
    """

    SKIP = [{"mode": "when", "condition": "product.stock > 0",
             "step": "create order", "rounds": None}]

    def test_a_skip_only_mode_a_reports_fails_the_order_class(self):
        a = _observation(["find product"], self.SKIP)
        b = _observation(["find product"], [])
        ok, report = compare_observations(a, b)
        self.assertFalse(ok, "\n".join(report))
        self.assertTrue(any("FAIL 1/4" in line for line in report), report)
        self.assertIn("DIVERGENT", report[-1])

    def test_the_failure_report_names_both_sides_skips(self):
        a = _observation(["find product"], self.SKIP)
        b = _observation(["find product"], [])
        _ok, report = compare_observations(a, b)
        line = next(l for l in report if "FAIL 1/4" in l)
        self.assertIn("create order", line,
                      "the report must name the skip that differs, not just "
                      "say the class failed")

    def test_a_differing_round_count_fails_the_order_class(self):
        # RFC-0008 §5 names the `until` round count as its own comparison item.
        a = _observation(["a"], [{"mode": "until", "condition": "c >= 10",
                                  "step": "b", "rounds": 0}])
        b = _observation(["a"], [{"mode": "until", "condition": "c >= 10",
                                  "step": "b", "rounds": 3}])
        ok, report = compare_observations(a, b)
        self.assertFalse(ok)
        self.assertTrue(any("FAIL 1/4" in line for line in report), report)

    def test_matching_skips_keep_the_order_class_green(self):
        # Positive control: sharpening the class must not redden honest runs.
        a = _observation(["find product"], self.SKIP)
        b = _observation(["find product"], list(self.SKIP))
        ok, report = compare_observations(a, b)
        self.assertTrue(ok, "\n".join(report))
        self.assertTrue(any("PASS 1/4" in line for line in report), report)
        self.assertIn("EQUIVALENT", report[-1])

    def test_an_absent_skips_key_reads_as_no_skips(self):
        # Boundary: an observation built before this key existed must compare
        # as "nothing was skipped" rather than as a divergence against [].
        a = _observation(["s"], [])
        b = _observation(["s"], [])
        del b["skips"]
        ok, _report = compare_observations(a, b)
        self.assertTrue(ok)


class TestBothModesObserveTheSameSkips(unittest.TestCase):
    """End to end: the two modes really do agree, on inputs where a guard is
    false. `testing-quality-differential-run-agreement`: the default input never
    reaches the guard's false side, so it certifies nothing about this class.
    """

    def setUp(self):
        tmp = os.path.join(REPO, ".claude", "tmp")
        os.makedirs(tmp, exist_ok=True)
        self.workdir = tempfile.mkdtemp(prefix="lnpl-skip-", dir=tmp)

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _checkout(self, stock):
        from lnpl.interp import refinement_index, sample_payload
        with open(CHECKOUT_LNPL, encoding="utf-8") as fh:
            doc = lower(parse(fh.read()), "checkout").to_document()
        payload = sample_payload([n for n in doc["nodes"] if n["kind"] == "Entity"],
                                 refinement_index(doc))
        payload["stock"] = stock
        return doc, payload

    def test_mode_a_reports_the_skip_on_the_forcing_input(self):
        # Mode A side alone, so the claim below is not resting on the toolchain.
        doc, payload = self._checkout(stock=0)
        a = differential.observe_mode_a(doc, "wf.checkout", payload,
                                        default_rows(doc, "wf.checkout", payload))
        self.assertEqual(a["skips"],
                         [{"mode": "when", "condition": "product.stock > 0",
                           "step": "create order", "rounds": None}])

    @NEEDS_TOOLS
    def test_a_false_when_is_equivalent_across_the_two_modes(self):
        doc, payload = self._checkout(stock=0)
        rows = default_rows(doc, "wf.checkout", payload)
        ok, report = differential.verify(doc, "wf.checkout", payload, rows,
                                         self.workdir)
        self.assertTrue(ok, "\n".join(report))
        self.assertTrue(any("1 skip" in line for line in report), report)

    @NEEDS_TOOLS
    def test_the_guard_true_run_reports_no_skip_in_either_mode(self):
        # The forcing input's control: same workflow, guard taken.
        doc, payload = self._checkout(stock=1)
        rows = default_rows(doc, "wf.checkout", payload)
        ok, report = differential.verify(doc, "wf.checkout", payload, rows,
                                         self.workdir)
        self.assertTrue(ok, "\n".join(report))
        self.assertTrue(any("0 skip" in line for line in report), report)

    @NEEDS_TOOLS
    def test_an_until_that_never_loops_is_equivalent_across_the_modes(self):
        doc = lower(parse(UNTIL_COUNTER), "t").to_document()
        payload = {"counter": 100}
        rows = default_rows(doc, "wf.w", payload)
        ok, report = differential.verify(doc, "wf.w", payload, rows, self.workdir)
        self.assertTrue(ok, "\n".join(report))
        b = differential.observe_mode_b(doc, "wf.w", self.workdir,
                                        payload=payload, seeded=None)
        self.assertEqual(b["skips"],
                         [{"mode": "until", "condition": "counter >= 10",
                           "step": "step Loop", "rounds": 0}],
                         "a 0-round until must produce exactly one record in "
                         "mode B too, not one per unrolled round")

    @NEEDS_TOOLS
    def test_an_unguarded_workflow_reports_no_skips_in_either_mode(self):
        # Boundary: the workflows that have no guard at all must be untouched.
        doc = lower(parse(guarded_source("when token missing")), "t").to_document()
        for node in doc["nodes"]:
            if node["id"] == "wf.w":
                node["children"] = [c for c in node["children"]
                                    if not c.startswith("wf.w.guard")]
        payload = dict(USER, token="present")
        rows = {"entity.user": {row_key("entity.user", payload): dict(payload)}}
        ok, report = differential.verify(doc, "wf.w", payload, rows, self.workdir)
        self.assertTrue(ok, "\n".join(report))
        a = differential.observe_mode_a(doc, "wf.w", payload, rows)
        self.assertEqual(a["skips"], [])

    # A step name that appears both inside the guard and outside it. Matching
    # ran-vs-planned by NAME lets the unguarded occurrence mask the guarded one,
    # so mode B reports no skip while mode A reports one.
    DUPLICATE_NAME = """
capability postgres
entity User
    field
        id UUID
        email Email
        token Text
service S
workflow W
    load user
    when token missing
    load user
"""

    @NEEDS_TOOLS
    def test_a_step_name_repeated_outside_the_guard_does_not_mask_the_skip(self):
        doc = lower(parse(self.DUPLICATE_NAME), "t").to_document()
        payload = dict(USER, token="present")           # `token missing` is false
        rows = {"entity.user": {row_key("entity.user", payload): dict(payload)}}

        a = differential.observe_mode_a(doc, "wf.w", payload, rows)
        self.assertEqual(a["skips"],
                         [{"mode": "when", "condition": "token missing",
                           "step": "load user", "rounds": None}],
                         "precondition: mode A sees the guarded occurrence skipped")

        ok, report = differential.verify(doc, "wf.w", payload, rows, self.workdir)
        self.assertTrue(ok, "\n".join(report))
        b = differential.observe_mode_b(doc, "wf.w", self.workdir,
                                        payload=payload, seeded=None)
        self.assertEqual(b["skips"], a["skips"],
                         "mode B must identify the skipped op by its index; "
                         "the identically named step that DID run must not "
                         "mask it.")


class TestRanStepIndices(unittest.TestCase):
    """`backend.ran_step_indices` — which planned ops the binary printed.

    Indices, not names: `TestBothModesObserveTheSameSkips.DUPLICATE_NAME` is the
    workflow that makes the difference observable.
    """

    def test_step_lines_yield_their_indices(self):
        lines = ["step 1 validate product", "effect validate product Validation",
                 "step 2 find product", "status completed"]

        self.assertEqual(backend.ran_step_indices(lines), {"1", "2"})

    def test_a_step_name_containing_spaces_still_yields_one_index(self):
        self.assertEqual(backend.ran_step_indices(["step 7 step Loop"]), {"7"})

    def test_no_lines_yield_no_indices(self):
        self.assertEqual(backend.ran_step_indices([]), set())

    def test_effect_and_status_lines_alone_yield_no_indices(self):
        # Boundary: a binary whose guard skipped everything still prints these.
        lines = ["effect find product RepositoryCall", "status completed"]

        self.assertEqual(backend.ran_step_indices(lines), set())

    def test_a_malformed_step_line_is_not_counted(self):
        # `step` with no name is not the contract's shape; counting it would
        # credit a planned op as run and hide a real skip.
        self.assertEqual(backend.ran_step_indices(["step 3"]), set())


class TestRestoreSkips(unittest.TestCase):
    """`backend.restore_skips` — RFC-0014 §2.6's absence-as-observation.

    Pure: no toolchain, no build. The function's whole input is the compiled step
    plan plus the set of indices that printed, so a synthetic `ran_indices`
    exercises it at the level the logic actually lives at.
    """

    def _checkout(self, stock):
        from lnpl.interp import refinement_index, sample_payload
        with open(CHECKOUT_LNPL, encoding="utf-8") as fh:
            doc = lower(parse(fh.read()), "checkout").to_document()
        payload = sample_payload([n for n in doc["nodes"] if n["kind"] == "Entity"],
                                 refinement_index(doc))
        payload["stock"] = stock
        return doc, payload

    def _all_indices(self, doc, workflow_id, payload):
        return {str(e["index"])
                for e in backend.step_plan(doc, workflow_id, payload=payload)}

    def test_a_planned_guarded_step_that_never_printed_is_one_record(self):
        doc, payload = self._checkout(stock=0)
        # `create order` is plan index 4; the three unguarded steps printed.
        skips = backend.restore_skips(doc, "wf.checkout", {"1", "2", "3"},
                                     payload=payload)

        self.assertEqual(skips, [{"mode": "when",
                                  "condition": "product.stock > 0",
                                  "step": "create order", "rounds": None}])

    def test_a_guarded_step_that_printed_is_not_a_skip(self):
        # Positive control: the same plan, the guard taken.
        doc, payload = self._checkout(stock=1)
        ran = self._all_indices(doc, "wf.checkout", payload)

        self.assertEqual(backend.restore_skips(doc, "wf.checkout", ran,
                                               payload=payload), [])

    def test_an_absent_unguarded_step_is_not_a_skip(self):
        # Boundary: nothing printed at all. An unguarded step's absence means the
        # run stopped, not that a guard refused it — only guarded ops are skips.
        doc, payload = self._checkout(stock=0)
        skips = backend.restore_skips(doc, "wf.checkout", set(), payload=payload)

        self.assertEqual([s["step"] for s in skips], ["create order"])

    def test_a_zero_round_until_is_exactly_one_record(self):
        doc = lower(parse(UNTIL_COUNTER), "t").to_document()
        payload = {"counter": 100}
        # Plan: index 1 `step Start`, 2-17 the unrolled `step Loop`, 18 `step End`.
        skips = backend.restore_skips(doc, "wf.w", {"1", "18"}, payload=payload)

        self.assertEqual(skips, [{"mode": "until", "condition": "counter >= 10",
                                  "step": "step Loop", "rounds": 0}],
                         "rounds 2..N are unrolled copies; counting each absence "
                         "would report 16 skips against mode A's single record")

    def test_an_until_that_ran_every_round_is_not_a_skip(self):
        doc = lower(parse(UNTIL_COUNTER), "t").to_document()
        payload = {"counter": 0}
        ran = self._all_indices(doc, "wf.w", payload)

        self.assertEqual(backend.restore_skips(doc, "wf.w", ran,
                                               payload=payload), [])

    def test_a_workflow_with_no_guard_restores_no_skips(self):
        # Boundary: the unguarded workflows must be untouched by this reading.
        doc, payload = self._checkout(stock=0)
        for node in doc["nodes"]:
            if node["id"] == "wf.checkout":
                node["children"] = [c for c in node["children"]
                                    if not c.startswith("wf.checkout.guard")]

        self.assertEqual(backend.restore_skips(doc, "wf.checkout", set(),
                                               payload=payload), [])

    def test_the_restored_record_carries_exactly_the_comparable_fields(self):
        # The shape is the contract: `_normalise_skips` projects mode A onto
        # these four keys, so an extra key here would fail the comparison for a
        # reason RFC-0014 §2.4 says is not a behavioural difference.
        doc, payload = self._checkout(stock=0)
        skips = backend.restore_skips(doc, "wf.checkout", {"1", "2", "3"},
                                     payload=payload)

        self.assertEqual(sorted(skips[0]), ["condition", "mode", "rounds", "step"])

    def test_a_repeated_step_name_does_not_mask_the_guarded_occurrence(self):
        # The index-not-name rule, at the level it is implemented rather than
        # only end to end: `TestBothModesObserveTheSameSkips` covers this too,
        # but that test needs the toolchain and is skipped without it.
        # Plan: index 1 `load user` unguarded, index 2 `load user` under the
        # guard. Only the unguarded one printed. Matching on the NAME would find
        # `load user` among the ran steps and report no skip at all.
        doc = lower(parse(TestBothModesObserveTheSameSkips.DUPLICATE_NAME),
                    "t").to_document()
        skips = backend.restore_skips(doc, "wf.w", {"1"},
                                     payload={"token": "present"})

        self.assertEqual(skips, [{"mode": "when", "condition": "token missing",
                                  "step": "load user", "rounds": None}])

    def test_an_empty_plan_restores_nothing(self):
        # Negative control for the two positive cases above: with the plan
        # emptied, the same `ran_indices` must yield nothing. A restoration that
        # returned a constant would keep one of the three tests green and break
        # this one.
        from unittest import mock

        doc, payload = self._checkout(stock=0)
        with mock.patch.object(backend, "step_plan", return_value=[]):
            self.assertEqual(backend.restore_skips(doc, "wf.checkout",
                                                   {"1", "2", "3"},
                                                   payload=payload), [])



# RFC-0055 §10: mode B refuses any guard — Presence or comparison — that reads
# an `optional` field, in `build` and `diff` alike, before any toolchain use.
OPTIONAL_MODE_B = """capability postgres
%s
entity Customer
    field
        id UUID
        score Integer
        nickname Text optional
        bonus Integer optional

entity Order
    field
        id UUID
%s
service CustomerService
    policy
        timeout 5s

workflow Greet
    read customer
%s
"""

LEDGER = "\nentity Ledger\n    field\n        id UUID\n        bonus Integer\n"


def _optional_doc(body, before="", after=""):
    doc = lower(parse(OPTIONAL_MODE_B % (before, after, body)), "crm").to_document()
    return doc, "wf.greet"


class TestOptionalGuardExemption(unittest.TestCase):

    _workdir = TestLookupKeyExemption._workdir
    _forbid_tool = TestLookupKeyExemption._forbid_tool

    def _no_toolchain(self):
        real = backend.toolchain_available
        backend.toolchain_available = lambda: False
        self.addCleanup(setattr, backend, "toolchain_available", real)

    def _verify(self, doc, wf):
        payload = {"id": "0b6f1c2e-5555-4a2b-9c3d-000000000208"}
        return differential.verify(doc, wf, payload,
                                   default_rows(doc, wf, payload), self._workdir())

    def _build_refusal(self, doc, wf):
        self._forbid_tool()
        with self.assertRaises(backend.BackendError) as ctx:
            backend.build(doc, wf, self._workdir(), seeded=frozenset())
        return str(ctx.exception)

    def _diff_refusal(self, doc, wf):
        self._no_toolchain()
        with self.assertRaises(differential.DifferentialError) as ctx:
            self._verify(doc, wf)
        msg = str(ctx.exception)
        self.assertNotIn("toolchain unavailable", msg)
        return msg

    def test_build_refuses_presence_on_optional_field(self):
        doc, wf = _optional_doc("    when customer.nickname exists\n    create order")
        msg = self._build_refusal(doc, wf)
        self.assertIn("customer.nickname exists", msg)
        self.assertIn("`optional`", msg)
        self.assertIn("RFC-0055", msg)
        self.assertTrue(backend.workflow_uses_optional_guard(doc, wf))

    def test_build_refuses_comparison_on_optional_field(self):
        doc, wf = _optional_doc("    when customer.bonus > 5\n    create order")
        msg = self._build_refusal(doc, wf)
        self.assertIn("customer.bonus > 5", msg)
        self.assertIn("RFC-0055", msg)

    def test_emit_mlir_refuses_too(self):
        doc, wf = _optional_doc("    when customer.bonus > 5\n    create order")
        with self.assertRaises(backend.BackendError) as ctx:
            backend.emit_mlir(doc, wf)
        self.assertIn("RFC-0055", str(ctx.exception))

    def test_build_refuses_presence_on_optional_create_as_alias(self):
        doc, wf = _optional_doc(
            "    create customer as fresh\n    when fresh.bonus exists\n"
            "    create order")
        msg = self._build_refusal(doc, wf)
        self.assertIn("fresh.bonus exists", msg)
        self.assertTrue(backend.workflow_uses_optional_guard(doc, wf))

    def test_build_refuses_an_optional_field_only_in_an_or_alternative(self):
        doc, wf = _optional_doc(
            "    when customer.score > 1\n    or customer.bonus > 1\n    create order")
        self.assertIn("customer.bonus > 1", self._build_refusal(doc, wf))

    def test_build_still_builds_guard_on_non_optional_sibling_field(self):
        doc, wf = _optional_doc("    when customer.score > 5\n    create order")
        self.assertFalse(backend.workflow_uses_optional_guard(doc, wf))
        self.assertIn("scf.if", backend.emit_mlir(doc, wf))

    def test_diff_refuses_presence_on_optional_field_without_toolchain(self):
        doc, wf = _optional_doc("    when customer.nickname exists\n    create order")
        msg = self._diff_refusal(doc, wf)
        self.assertIn("`optional`", msg)
        self.assertIn("RFC-0055", msg)

    def test_diff_refuses_comparison_on_optional_field_without_toolchain(self):
        doc, wf = _optional_doc("    when customer.bonus > 5\n    create order")
        self.assertIn("RFC-0055", self._diff_refusal(doc, wf))

    def test_mixed_entity_comparison_input_field_refused_both_orders(self):
        # `Ledger.bonus` is required, `Customer.bonus` optional: the ANY rule
        # refuses whichever entity is declared last.
        for before, after in ((LEDGER, ""), ("", LEDGER)):
            with self.subTest(ledger_first=bool(before)):
                doc, wf = _optional_doc("    when input.bonus > 5\n    create order",
                                        before=before, after=after)
                self.assertTrue(backend.workflow_uses_optional_guard(doc, wf))
                self.assertIn("RFC-0055", self._build_refusal(doc, wf))
                self.assertIn("RFC-0055", self._diff_refusal(doc, wf))

    def test_build_with_no_optional_guard_still_builds(self):
        doc, wf = _optional_doc("    create order")
        self.assertFalse(backend.workflow_uses_optional_guard(doc, wf))
        self.assertIn("func.func", backend.emit_mlir(doc, wf))

    def test_diff_with_no_optional_guard_still_diffs(self):
        # Without a toolchain the ordinary toolchain message comes back —
        # the exemption is scoped to optional guards.
        doc, wf = _optional_doc("    when customer.score > 5\n    create order")
        self._no_toolchain()
        with self.assertRaises(differential.DifferentialError) as ctx:
            self._verify(doc, wf)
        self.assertIn("toolchain unavailable", str(ctx.exception))

    def test_an_unknown_workflow_is_a_backend_error(self):
        doc, _ = _optional_doc("    create order")
        with self.assertRaises(backend.BackendError):
            backend.workflow_uses_optional_guard(doc, "wf.nope")

    def test_lnpl_diff_and_build_report_the_refusal_as_rc_4(self):
        from tests.test_cli import run_cli_err
        workdir = self._workdir()
        src = os.path.join(workdir, "crm.lnpl")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(OPTIONAL_MODE_B % ("", "", "    when customer.nickname exists\n"
                                                "    create order"))
        for cmd in ("diff", "build"):
            with self.subTest(cmd=cmd):
                rc, text = run_cli_err([cmd, src, "--workdir", workdir,
                                        "--workflow", "wf.greet"])
                self.assertEqual(rc, 4, text)
                self.assertIn("RFC-0055", text)
                self.assertNotIn("EQUIVALENT", text)


# RFC-0056 §Mode B: mode B refuses a guard comparing a Text-family field, in
# `build` and `diff` alike, LAST among the guard exemptions and before any
# toolchain use.
def _text_doc(body):
    from tests.test_backend import TEXT_GUARD
    return lower(parse(TEXT_GUARD % body), "shop").to_document(), "wf.cancel"


class TestTextGuardExemption(unittest.TestCase):

    _workdir = TestLookupKeyExemption._workdir
    _forbid_tool = TestLookupKeyExemption._forbid_tool
    _no_toolchain = TestOptionalGuardExemption._no_toolchain
    _verify = TestOptionalGuardExemption._verify
    _build_refusal = TestOptionalGuardExemption._build_refusal
    _diff_refusal = TestOptionalGuardExemption._diff_refusal

    def test_a_text_guard_is_detected(self):
        doc, wf = _text_doc("read order\n    when order.status == input.expected")
        self.assertTrue(backend.workflow_uses_text_guard(doc, wf))

    def test_a_text_guard_through_create_as_alias_is_detected(self):
        doc, wf = _text_doc("create order as fresh\n    when fresh.status != paid")
        self.assertTrue(backend.workflow_uses_text_guard(doc, wf))

    def test_a_workflow_with_no_text_guard_is_not_detected(self):
        doc, wf = _text_doc("read order\n    when order.stock > 0")
        self.assertFalse(backend.workflow_uses_text_guard(doc, wf))

    def test_build_refuses_text_equality_without_toolchain(self):
        doc, wf = _text_doc("read order\n    when order.status == paid")
        msg = self._build_refusal(doc, wf)
        self.assertIn("order.status == paid", msg)
        self.assertIn("RFC-0056", msg)

    def test_diff_refuses_text_equality_without_toolchain(self):
        doc, wf = _text_doc("read order\n    when order.status == paid")
        msg = self._diff_refusal(doc, wf)
        self.assertIn("Text-family", msg)
        self.assertIn("RFC-0056", msg)

    def test_diff_with_no_text_guard_still_diffs(self):
        doc, wf = _text_doc("read order\n    when order.stock > 0")
        self._no_toolchain()
        with self.assertRaises(differential.DifferentialError) as ctx:
            self._verify(doc, wf)
        self.assertIn("toolchain unavailable", str(ctx.exception))

    def test_build_and_diff_refuse_in_the_same_order(self):
        # The earlier exemptions win in both commands: optional (RFC-0055),
        # lookup (RFC-0052), then text (RFC-0056) last.
        optional = lower(parse(OPTIONAL_MODE_B % (
            "", "", "    when customer.nickname == input.nickname\n"
                    "    create order")), "crm").to_document()
        from tests.test_backend import LOOKUP_MODULE
        lookup = lower(parse(LOOKUP_MODULE % (
            "    find stock by input.productId\n"
            "    when stock.productId == p1\n    find stock")),
            "orders").to_document()
        for doc, wf, first in ((optional, "wf.greet", "RFC-0055"),
                               (lookup, "wf.restock", "RFC-0052")):
            with self.subTest(first=first):
                self.assertTrue(backend.workflow_uses_text_guard(doc, wf))
                for msg in (self._build_refusal(doc, wf),
                            self._diff_refusal(doc, wf)):
                    self.assertIn(first, msg)
                    self.assertNotIn("RFC-0056", msg)

    def test_lnpl_diff_and_build_report_the_refusal_as_rc_4(self):
        from tests.test_backend import TEXT_GUARD
        from tests.test_cli import run_cli_err
        workdir = self._workdir()
        src = os.path.join(workdir, "shop.lnpl")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(TEXT_GUARD % "read order\n    when order.status == paid")
        for cmd in ("diff", "build"):
            with self.subTest(cmd=cmd):
                rc, text = run_cli_err([cmd, src, "--workdir", workdir,
                                        "--workflow", "wf.cancel"])
                self.assertEqual(rc, 4, text)
                self.assertIn("RFC-0056", text)
                self.assertNotIn("EQUIVALENT", text)

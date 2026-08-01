"""The custom `lnpl` MLIR dialect — RFC-0004 S4.

The dialect is defined declaratively in `mlir/lnpl.irdl.mlir` and registered into
stock `mlir-opt` with `--irdl-file`, so these tests exercise a dialect that MLIR
itself parses and verifies — not a text format this repo invented.

`TestDialectRegistration` therefore leads with negative controls. A test that
only shows a valid module verifying would pass just as well if `--irdl-file` were
silently ignored and everything fell through as an unregistered dialect, so the
suite pins the three ways verification must fail (unknown op, missing node id,
non-string node id) plus the fact that dropping `--irdl-file` breaks parsing
outright.
"""

import json
import os
import re
import subprocess
import unittest

from lnpl import backend
from lnpl.lower import lower
from lnpl.parser import parse

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GOLDEN_IR = os.path.join(REPO, "examples", "login.lir.json")

NEEDS_TOOLS = unittest.skipUnless(
    backend.toolchain_available(),
    "MLIR/LLVM toolchain not installed (brew install llvm)")

# Same shape test_backend.py uses, so the guard cases here and there stay
# comparable. The guard line is substituted per test.
GUARDED = """
capability postgres
entity User
    field
        id UUID
        email Email
service S
workflow W
    load user
    when token missing
    cache user
"""


def golden():
    with open(GOLDEN_IR, encoding="utf-8") as fh:
        return json.load(fh)


def guarded_doc(guard):
    """The GUARDED workflow with its guard line replaced by `guard`."""
    src = GUARDED.replace("when token missing", guard)
    return lower(parse(src), "t").to_document()


def node_ids(lnpl_text, op='"lnpl.step"'):
    """Ordered lnpl.node_id values for `op`, read back out of emitted text."""
    found = []
    for line in lnpl_text.split("\n"):
        if not line.strip().startswith(op):
            continue
        match = re.search(r'lnpl\.node_id = "([^"]*)"', line)
        if match is None:
            # The dialect verifier rejects this, so reaching it means the emitter
            # produced something that would not compile. Fail loudly, naming the line.
            raise AssertionError("%s op emitted without a node id: %s" % (op, line))
        found.append(match.group(1))
    return found


def attr_ints(lnpl_text, attr):
    return [int(m) for m in re.findall(r"%s = (\d+) : i64" % re.escape(attr),
                                       lnpl_text)]


def module(body):
    """Wrap op text in a module. `builtin.module` needs no terminator."""
    return "module {\n%s\n}\n" % body


STEP = ('  "lnpl.step"() {lnpl.node_id = "wf.login.step.1", '
        'lnpl.name = "validate input", lnpl.index = 1 : i64} : () -> ()')
EFFECT = ('  "lnpl.effect"() {lnpl.node_id = "wf.login.step.1.check", '
          'lnpl.kind = "Validation", lnpl.step = "wf.login.step.1"} : () -> ()')


class TestDialectFileIsPresent(unittest.TestCase):
    """Needs no toolchain — the path is a pure function of the source layout."""

    def test_the_dialect_file_is_where_the_code_looks_for_it(self):
        self.assertTrue(os.path.isfile(backend.LNPL_IRDL_PATH),
                        backend.LNPL_IRDL_PATH)

    def test_the_repo_root_resolves_to_this_repository(self):
        # Guards the dirname count in backend.REPO_ROOT: one too few or too many
        # would still produce a plausible-looking path.
        self.assertTrue(os.path.isfile(os.path.join(backend.REPO_ROOT,
                                                    "CHARTER.md")))


@NEEDS_TOOLS
class TestDialectRegistration(unittest.TestCase):
    def test_a_valid_module_verifies(self):
        out = backend.verify_lnpl_module(module(STEP + "\n" + EFFECT))
        self.assertIn('"lnpl.step"', out)
        self.assertIn('"lnpl.effect"', out)
        self.assertIn("wf.login.step.1", out)

    def test_a_location_survives_the_round_trip(self):
        # RFC-0004 carries the node id on two paths because the attribute is
        # discardable. Without --mlir-print-debuginfo mlir-opt emits no loc at
        # all, so this is what keeps that flag from being dropped as noise.
        text = module('  "lnpl.step"() {lnpl.node_id = "wf.login.step.1"} '
                      ': () -> () loc("wf.login.step.1")')
        out = backend.verify_lnpl_module(text)
        self.assertIn("loc(", out)
        self.assertIn("wf.login.step.1", out)

    def test_an_op_without_a_node_id_is_rejected(self):
        with self.assertRaises(backend.BackendError) as ctx:
            backend.verify_lnpl_module(module('  "lnpl.step"() : () -> ()'))
        self.assertIn("lnpl.node_id", str(ctx.exception))

    def test_a_non_string_node_id_is_rejected(self):
        # The dialect binds node_id to #builtin.string. With irdl.any instead,
        # this module would verify and the invariant would be presence-only.
        with self.assertRaises(backend.BackendError) as ctx:
            backend.verify_lnpl_module(
                module('  "lnpl.step"() {lnpl.node_id = 42 : i64} : () -> ()'))
        self.assertIn("builtin.string", str(ctx.exception))

    def test_an_undefined_lnpl_op_is_rejected(self):
        with self.assertRaises(backend.BackendError) as ctx:
            backend.verify_lnpl_module(
                module('  "lnpl.bogus"() {lnpl.node_id = "x"} : () -> ()'))
        self.assertIn("lnpl.bogus", str(ctx.exception))

    def test_an_empty_module_verifies(self):
        # Boundary: zero ops. Nothing to trace, so nothing to reject.
        self.assertIn("module", backend.verify_lnpl_module("module {\n}\n"))

    def test_undeclared_attributes_are_allowed_through(self):
        # The dialect closes only node_id; new compile decisions must be able to
        # ride along without editing the .irdl.mlir.
        out = backend.verify_lnpl_module(module(
            '  "lnpl.step"() {lnpl.node_id = "x", lnpl.guard_mode = "until", '
            'lnpl.unroll_round = 7 : i64} : () -> ()'))
        self.assertIn("lnpl.unroll_round", out)

    def test_the_registration_is_what_makes_it_parse(self):
        """Negative control: without --irdl-file the same module must not parse.

        If this passed, every other test in this class would prove nothing — they
        would be exercising an unregistered-dialect fallthrough rather than the
        `lnpl` dialect.
        """
        tmpdir = os.path.join(REPO, ".claude", "tmp")
        os.makedirs(tmpdir, exist_ok=True)
        path = os.path.join(tmpdir, "negative-control.lnpl.mlir")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(module(STEP))
        try:
            proc = subprocess.run([backend.tool(backend.MLIR_OPT), path],
                                  capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0,
                                "mlir-opt accepted lnpl.step without --irdl-file")
            self.assertIn("unregistered dialect", proc.stderr)
        finally:
            os.remove(path)


class TestLnplEmission(unittest.TestCase):
    """S4 emission needs no toolchain — it is text generation."""

    def test_every_step_becomes_an_lnpl_step_op_in_order(self):
        text = backend.emit_lnpl_mlir(golden(), "wf.login")
        self.assertEqual(node_ids(text),
                         ["wf.login.step.%d" % n for n in range(1, 7)])

    def test_every_op_carries_a_node_id_and_a_location(self):
        text = backend.emit_lnpl_mlir(golden(), "wf.login")
        op_lines = [l for l in text.split("\n") if l.strip().startswith('"lnpl.')]
        # Assert there is something to iterate before iterating, or an emitter
        # that produced no ops at all would satisfy the loop vacuously.
        self.assertEqual(len(op_lines), 9)          # 6 steps + 3 effects
        for line in op_lines:
            self.assertIn('lnpl.node_id = "', line)
            self.assertIn("loc(", line)

    def test_effects_become_lnpl_effect_ops(self):
        text = backend.emit_lnpl_mlir(golden(), "wf.login")
        self.assertEqual(node_ids(text, '"lnpl.effect"'),
                         ["wf.login.step.1.check", "wf.login.step.2.repo",
                          "wf.login.step.3.cache"])
        for kind in ("Validation", "RepositoryCall", "CacheAccess"):
            self.assertIn('lnpl.kind = "%s"' % kind, text)

    def test_an_effect_names_its_owning_step(self):
        text = backend.emit_lnpl_mlir(golden(), "wf.login")
        self.assertIn('lnpl.node_id = "wf.login.step.2.repo", '
                      'lnpl.kind = "RepositoryCall", '
                      'lnpl.step = "wf.login.step.2"', text)

    def test_unrolled_until_rounds_share_one_node_id(self):
        # RFC-0004's 1:다 확장 rule: one IR node becoming many ops keeps its id on
        # all of them, so the rounds are told apart by lnpl.unroll_round.
        text = backend.emit_lnpl_mlir(guarded_doc("until counter >= 10"), "wf.w")
        guarded = [n for n in node_ids(text) if n == "wf.w.step.2"]
        self.assertEqual(len(guarded), backend._UNTIL_ROUND_CAP)
        self.assertEqual(len(set(guarded)), 1)
        self.assertEqual(attr_ints(text, "lnpl.unroll_round"),
                         list(range(1, backend._UNTIL_ROUND_CAP + 1)))

    def test_unrolled_repeat_rounds_share_one_node_id(self):
        # `repeat` attaches no guard at all, so this is the case that catches an
        # implementation keying the round marker off guard_mode == "until".
        text = backend.emit_lnpl_mlir(guarded_doc("repeat 3"), "wf.w")
        guarded = [n for n in node_ids(text) if n == "wf.w.step.2"]
        self.assertEqual(len(guarded), 3)
        self.assertEqual(len(set(guarded)), 1)
        self.assertEqual(attr_ints(text, "lnpl.unroll_round"), [1, 2, 3])

    def test_a_step_appearing_once_carries_no_round_marker(self):
        # Boundary on the other side of the same rule.
        text = backend.emit_lnpl_mlir(golden(), "wf.login")
        self.assertNotIn("lnpl.unroll_round", text)

    def test_a_guard_is_materialised_as_attributes(self):
        text = backend.emit_lnpl_mlir(guarded_doc("until counter >= 10"), "wf.w")
        self.assertIn('lnpl.guard_mode = "until"', text)
        self.assertIn('lnpl.guard_condition = "counter >= 10"', text)

    def test_condition_fields_come_from_the_single_source(self):
        for doc, workflow in ((golden(), "wf.login"),
                              (guarded_doc("until counter >= 10"), "wf.w")):
            expected = backend.condition_field_names(doc, workflow)
            rendered = "[%s]" % ", ".join('"%s"' % f for f in expected)
            self.assertIn("lnpl.condition_fields = %s" % rendered,
                          backend.emit_lnpl_mlir(doc, workflow))
        # The golden workflow has no guards, so this also covers the empty list.
        self.assertEqual(backend.condition_field_names(golden(), "wf.login"), [])

    def test_unknown_workflow_is_an_error(self):
        with self.assertRaises(backend.BackendError) as ctx:
            backend.emit_lnpl_mlir(golden(), "wf.nope")
        self.assertIn("wf.nope", str(ctx.exception))


@NEEDS_TOOLS
class TestEmittedModuleVerifies(unittest.TestCase):
    """The emitted module is checked by MLIR, not just by this suite."""

    def test_the_emitted_golden_module_passes_the_dialect_verifier(self):
        out = backend.verify_lnpl_module(
            backend.emit_lnpl_mlir(golden(), "wf.login"))
        self.assertIn('"lnpl.step"', out)

    def test_the_emitted_until_module_passes_the_dialect_verifier(self):
        out = backend.verify_lnpl_module(
            backend.emit_lnpl_mlir(guarded_doc("until counter >= 10"), "wf.w"))
        self.assertIn('"lnpl.step"', out)

    def test_node_ids_survive_the_round_trip(self):
        text = backend.emit_lnpl_mlir(golden(), "wf.login")
        out = backend.verify_lnpl_module(text)
        # RFC-0004's traceability requirement, checked against what MLIR itself
        # produced rather than against our own emitter's string.
        for n in range(1, 7):
            self.assertIn("wf.login.step.%d" % n, out)


GOLDEN_DIR = os.path.join(REPO, "impl", "tests", "golden")


def _body(text):
    """Drop the leading `//` comment block.

    The fixtures hold pre-change bytes and are never regenerated, so the
    comparison has to survive a deliberate edit to the header comment without
    becoming a snapshot of the current implementation. Everything below the
    header is the part that must not move.
    """
    lines = text.split("\n")
    i = 0
    while i < len(lines) and lines[i].startswith("//"):
        i += 1
    return "\n".join(lines[i:])


def fixture(name):
    with open(os.path.join(GOLDEN_DIR, name), encoding="utf-8") as fh:
        return fh.read()


class TestStandardLoweringIsUnchanged(unittest.TestCase):
    """Routing emit_mlir through the lnpl op stream must not move its output.

    The fixtures were captured from emit_mlir *before* the dialect existed. They
    are the only evidence that S4 was inserted without changing what mode B
    compiles, which is why nothing regenerates them.
    """

    def test_the_fixtures_exist(self):
        for name in ("wf_login.std.mlir", "w_until.std.mlir"):
            self.assertTrue(os.path.isfile(os.path.join(GOLDEN_DIR, name)), name)

    def test_golden_login_lowering_is_unchanged(self):
        self.assertEqual(_body(fixture("wf_login.std.mlir")),
                         _body(backend.emit_mlir(golden(), "wf.login")))

    def test_until_workflow_lowering_is_unchanged(self):
        # The 16-round case: largest output, and the only one with guard branches.
        doc = guarded_doc("until counter >= 10")
        self.assertEqual(_body(fixture("w_until.std.mlir")),
                         _body(backend.emit_mlir(doc, "wf.w")))

    def test_the_header_still_names_the_module_and_version(self):
        # _body discards the header, so the values it carries are asserted here
        # rather than left uncovered.
        first = backend.emit_mlir(golden(), "wf.login").split("\n")[0]
        self.assertIn("lir_version 0.1", first)
        self.assertIn("module login", first)

    def test_the_stripper_leaves_non_comment_text_alone(self):
        # _body is test-only logic the two comparisons above depend on, so it is
        # pinned rather than trusted.
        self.assertEqual(_body("// a\n// b\nmodule {\n}\n"), "module {\n}\n")
        self.assertEqual(_body("module {\n// inner\n}\n"), "module {\n// inner\n}\n")
        self.assertEqual(_body(""), "")


class TestLnplAndStandardDescribeTheSameWorkflow(unittest.TestCase):
    """The lnpl module must not be able to disagree with what gets compiled.

    The dialect verifier is a structural gate — it accepts a one-step module where
    six belong, and it accepts an empty one. The differential check observes only
    the binary. So without these assertions a drop, reorder or duplication in
    emit_lnpl_mlir alone would leave the lnpl artifact describing a different
    workflow while the build and the equivalence check both pass.
    """

    def cases(self):
        return ((golden(), "wf.login"),
                (guarded_doc("until counter >= 10"), "wf.w"))

    def test_step_counts_agree(self):
        for doc, workflow in self.cases():
            lnpl = backend.emit_lnpl_mlir(doc, workflow)
            std = backend.emit_mlir(doc, workflow)
            self.assertEqual(lnpl.count('"lnpl.step"'),
                             std.count("func.call @lnpl_step"), workflow)

    def test_effect_counts_agree(self):
        for doc, workflow in self.cases():
            lnpl = backend.emit_lnpl_mlir(doc, workflow)
            std = backend.emit_mlir(doc, workflow)
            # Count call sites, not the bare symbol: the standard module also
            # contains one @lnpl_effect declaration.
            self.assertEqual(lnpl.count('"lnpl.effect"'),
                             std.count("func.call @lnpl_effect"), workflow)

    def test_node_ids_match_the_op_stream_in_order(self):
        for doc, workflow in self.cases():
            _attrs, ops = backend._lnpl_ops(doc, workflow)
            lnpl = backend.emit_lnpl_mlir(doc, workflow)
            self.assertEqual(node_ids(lnpl), [o["node_id"] for o in ops], workflow)
            self.assertEqual(
                node_ids(lnpl, '"lnpl.effect"'),
                [e["node_id"] for o in ops for e in o["effects"]], workflow)


class TestOpStreamRoutesThroughStepsInOrder(unittest.TestCase):
    """_lnpl_ops must read its steps through the module-global _steps_in_order.

    That indirection is what lets the deliberate-mismatch tests reach mode B by
    monkeypatching one name. It gets a direct test because the differential suite
    is a weak detector of it: three of its five mismatch cases pass against a
    baseline divergence their patch never causes, so they would stay green even if
    this routing were bypassed.
    """

    def setUp(self):
        self.original = backend._steps_in_order

    def tearDown(self):
        backend._steps_in_order = self.original

    def test_patching_steps_in_order_changes_the_op_stream(self):
        _attrs, before = backend._lnpl_ops(golden(), "wf.login")

        original = self.original

        def drop_last(nodes, ids, out):
            got = original(nodes, ids, [])
            out.extend(got[:-1])
            return out

        backend._steps_in_order = drop_last
        _attrs, after = backend._lnpl_ops(golden(), "wf.login")
        self.assertEqual(len(after), len(before) - 1)

    def test_patching_steps_in_order_reaches_the_standard_module(self):
        # Same seam, followed all the way to what mode B would compile.
        original = self.original

        def drop_last(nodes, ids, out):
            out.extend(original(nodes, ids, [])[:-1])
            return out

        backend._steps_in_order = drop_last
        std = backend.emit_mlir(golden(), "wf.login")
        self.assertEqual(std.count("func.call @lnpl_step"), 5)


if __name__ == "__main__":
    unittest.main()

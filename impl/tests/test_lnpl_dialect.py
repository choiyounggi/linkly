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


if __name__ == "__main__":
    unittest.main()

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

import os
import subprocess
import unittest

from lnpl import backend

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NEEDS_TOOLS = unittest.skipUnless(
    backend.toolchain_available(),
    "MLIR/LLVM toolchain not installed (brew install llvm)")


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


if __name__ == "__main__":
    unittest.main()

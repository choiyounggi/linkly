"""Mode B (native) and the mode A/B differential check.

RFC-0004 requires the equivalence check to include a **deliberate-mismatch case**
proving it can go red; `TestDivergenceIsDetected` is that case. Tests needing the
MLIR/LLVM toolchain skip when it is absent rather than passing vacuously.
"""

import json
import os
import shutil
import tempfile
import unittest

from lnpl import backend, differential
from lnpl.lower import lower
from lnpl.parser import parse

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GOLDEN_IR = os.path.join(REPO, "examples", "login.lir.json")

PAYLOAD = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
           "email": "user@example.com",
           "password": "s3cret-value",
           "createdAt": "2026-07-31T09:00:00Z"}

HAS_TOOLS = backend.toolchain_available()
NEEDS_TOOLS = unittest.skipUnless(
    HAS_TOOLS, "MLIR/LLVM toolchain not installed (brew install llvm)")

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


def rows_for(doc):
    return {n["id"]: dict(PAYLOAD) for n in doc["nodes"] if n["kind"] == "Entity"}


class TestMlirEmission(unittest.TestCase):
    """Emission needs no toolchain — it is text generation."""

    def test_every_step_appears_in_declared_order(self):
        text = backend.emit_mlir(golden(), "wf.login")
        positions = [text.index('"%s\\00"' % name) for name in
                     ("validate input", "authenticate", "cache user",
                      "generate token", "audit login", "return token")]
        self.assertEqual(positions, sorted(positions))

    def test_effects_are_emitted_as_calls(self):
        text = backend.emit_mlir(golden(), "wf.login")
        self.assertEqual(text.count("@lnpl_effect"), 3 + 1)   # 3 call sites + 1 decl

    def test_repeat_guard_unrolls_to_a_constant_number_of_steps(self):
        src = GUARDED.replace("    when token missing", "    repeat 3")
        doc = lower(parse(src), "t").to_document()
        text = backend.emit_mlir(doc, "wf.w")
        self.assertEqual(text.count("func.call @lnpl_step"), 1 + 3)

    def test_when_guard_becomes_a_runtime_branch(self):
        doc = lower(parse(GUARDED), "t").to_document()
        text = backend.emit_mlir(doc, "wf.w")
        self.assertIn("scf.if", text)

    def test_until_guard_is_refused_with_a_citation(self):
        src = GUARDED.replace("when token missing", "until token exists")
        doc = lower(parse(src), "t").to_document()
        with self.assertRaises(backend.BackendError) as ctx:
            backend.emit_mlir(doc, "wf.w")
        self.assertIn("Open Questions 2", str(ctx.exception))

    def test_unknown_workflow_is_an_error(self):
        with self.assertRaises(backend.BackendError):
            backend.emit_mlir(golden(), "wf.nope")


@NEEDS_TOOLS
class TestNativeBuild(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="lnpl-build-",
                                        dir=os.path.join(REPO, ".claude", "tmp"))

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def test_golden_compiles_to_a_runnable_binary(self):
        path = backend.build(golden(), "wf.login", self.workdir)
        self.assertTrue(os.access(path, os.X_OK))
        rc, lines = backend.run_binary(path)
        self.assertEqual(rc, 0)
        self.assertEqual(lines[-1], "status completed")

    def test_binary_reports_every_step(self):
        path = backend.build(golden(), "wf.login", self.workdir)
        _rc, lines = backend.run_binary(path)
        steps = [l for l in lines if l.startswith("step ")]
        self.assertEqual(len(steps), 6)

    def test_intermediates_are_kept_for_inspection(self):
        backend.build(golden(), "wf.login", self.workdir)
        for name in ("module.mlir", "module.llvm.mlir", "module.ll"):
            self.assertTrue(os.path.isfile(os.path.join(self.workdir, name)), name)

    def test_when_guard_flag_skips_the_guarded_step_in_the_binary(self):
        doc = lower(parse(GUARDED), "t").to_document()
        path = backend.build(doc, "wf.w", self.workdir)
        _rc, ran = backend.run_binary(path, skip=False)
        _rc, skipped = backend.run_binary(path, skip=True)
        self.assertEqual(len([l for l in ran if l.startswith("step ")]), 2)
        self.assertEqual(len([l for l in skipped if l.startswith("step ")]), 1)


@NEEDS_TOOLS
class TestDifferential(unittest.TestCase):
    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="lnpl-diff-",
                                        dir=os.path.join(REPO, ".claude", "tmp"))

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def test_the_two_modes_are_equivalent_on_the_golden_scenario(self):
        doc = golden()
        ok, report = differential.verify(doc, "wf.login", PAYLOAD,
                                         rows_for(doc), self.workdir)
        self.assertTrue(ok, "\n".join(report))
        self.assertIn("differential: EQUIVALENT", report[-1])

    def test_all_four_observable_classes_are_checked(self):
        doc = golden()
        _ok, report = differential.verify(doc, "wf.login", PAYLOAD,
                                          rows_for(doc), self.workdir)
        for n in ("1/4", "2/4", "3/4", "4/4"):
            self.assertTrue(any(n in line for line in report), n)

    def test_secrets_do_not_reach_either_mode_output(self):
        doc = golden()
        a = differential.observe_mode_a(doc, "wf.login", PAYLOAD, rows_for(doc))
        b = differential.observe_mode_b(doc, "wf.login", self.workdir)
        self.assertNotIn("s3cret", a["text"])
        self.assertNotIn("s3cret", b["text"])


@NEEDS_TOOLS
class TestDivergenceIsDetected(unittest.TestCase):
    """RFC-0004's deliberate-mismatch requirement: the check must be able to fail."""

    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="lnpl-div-",
                                        dir=os.path.join(REPO, ".claude", "tmp"))
        self.original = backend._steps_in_order

    def tearDown(self):
        backend._steps_in_order = self.original
        shutil.rmtree(self.workdir, ignore_errors=True)

    def test_reordered_backend_is_reported_as_divergent(self):
        original = self.original

        def reversed_order(nodes, ids, out):
            got = original(nodes, ids, [])
            out.extend(reversed(got))
            return out

        backend._steps_in_order = reversed_order
        doc = golden()
        ok, report = differential.verify(doc, "wf.login", PAYLOAD,
                                         rows_for(doc), self.workdir)
        self.assertFalse(ok, "a reversed backend must not compare as equivalent")
        self.assertTrue(any("FAIL 1/4" in line for line in report), report)

    def test_dropped_effect_in_the_backend_is_reported_as_divergent(self):
        original = self.original

        def without_effects(nodes, ids, out):
            got = original(nodes, ids, [])
            for step, cond in got:
                stripped = {k: v for k, v in step.items() if k != "children"}
                out.append((stripped, cond))
            return out

        backend._steps_in_order = without_effects
        doc = golden()
        ok, report = differential.verify(doc, "wf.login", PAYLOAD,
                                         rows_for(doc), self.workdir)
        self.assertFalse(ok)
        self.assertTrue(any("FAIL 3/4" in line for line in report), report)


class TestToolchainHonesty(unittest.TestCase):
    def test_missing_toolchain_raises_instead_of_silently_skipping(self):
        original = backend.toolchain_available
        backend.toolchain_available = lambda: False
        differential.backend.toolchain_available = lambda: False
        try:
            with self.assertRaises(differential.DifferentialError) as ctx:
                differential.verify(golden(), "wf.login", PAYLOAD, {}, self.workdir())
            self.assertIn("brew install llvm", str(ctx.exception))
        finally:
            backend.toolchain_available = original
            differential.backend.toolchain_available = original

    def workdir(self):
        return os.path.join(REPO, ".claude", "tmp", "unused")


if __name__ == "__main__":
    unittest.main()

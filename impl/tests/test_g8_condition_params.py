"""RFC-0008 G8: the condition-field parameter contract between the three places
that independently decide "which fields, in what order".

`emit_mlir` derives `lnpl_run`'s parameters from the workflow's condition
expressions. The C shim has to declare and pass exactly those, and
`differential`/`cli` have to supply values for exactly those. C linkage matches
on symbol name only, so a disagreement is not a link error — it is an
uninitialised register and a guard that silently takes the wrong branch. These
tests pin the contract at the observable level (generated `runtime.c` vs emitted
MLIR, and guard outcomes) rather than against any one function's signature.

Tests needing the MLIR/LLVM toolchain skip when it is absent rather than passing
vacuously.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

from lnpl import backend, differential
from lnpl.lower import lower
from lnpl.parser import parse

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP = os.path.join(REPO, ".claude", "tmp")

HAS_TOOLS = backend.toolchain_available()
NEEDS_TOOLS = unittest.skipUnless(
    HAS_TOOLS, "MLIR/LLVM toolchain not installed (brew install llvm)")


def _src(fields, body):
    """Build a source with the given entity fields and workflow body."""
    field_lines = "\n".join("        %s Integer" % f for f in fields)
    return (
        "capability postgres\n\n"
        "entity Workflow\n"
        "    field\n"
        "        id UUID\n"
        "%s\n"
        "        doneAt DateTime\n\n"
        "service S\n"
        "    policy\n"
        "        timeout 5s\n\n"
        "workflow W\n"
        "%s\n" % (field_lines, body)
    )


# Two condition fields — the shape the committed example happens to have, and the
# only shape the hardcoded shim agrees with. This is the control: it must pass
# both before and after the fix, otherwise these tests prove nothing.
TWO = _src(["flag", "counter"],
           "    step Start\n"
           "    when flag > 0\n"
           "    step Guarded\n"
           "    until counter >= 10\n"
           "    step Loop\n"
           "    step End")

# One condition field — fewer than the shim hardcodes.
ONE = _src(["flag", "counter"],
           "    step Start\n"
           "    when flag > 0\n"
           "    step Guarded\n"
           "    step End")

# Three condition fields — one more than the shim was written for.
THREE = _src(["flag", "counter", "retries"],
             "    step Start\n"
             "    when flag > 0\n"
             "    step GuardedByFlag\n"
             "    when counter > 0\n"
             "    step GuardedByCounter\n"
             "    when retries < 5\n"
             "    step GuardedByRetries\n"
             "    step End")

# No guards at all — the lower boundary of the parameter list.
NONE = _src(["flag"], "    step Start\n    step End")


def _doc(src):
    return lower(parse(src), "t").to_document()


def _mlir_param_count(document, workflow_id="wf.w"):
    mlir = backend.emit_mlir(document, workflow_id)
    sig = re.search(r"func\.func @lnpl_run\((.*?)\) ->", mlir).group(1)
    return len([p for p in sig.split(",") if p.strip()])


def _c_param_count(workdir):
    """Parameter count in the declaration the build actually compiled."""
    with open(os.path.join(workdir, "runtime.c"), encoding="utf-8") as fh:
        c = fh.read()
    decl = re.search(r"int lnpl_run\((.*?)\)\s*;", c, re.S)
    assert decl, "runtime.c has no lnpl_run declaration"
    return len([p for p in decl.group(1).split(",") if p.strip()])


class _Built(unittest.TestCase):
    def setUp(self):
        os.makedirs(TMP, exist_ok=True)
        self.workdir = tempfile.mkdtemp(prefix="lnpl-g8-", dir=TMP)

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _build(self, src):
        doc = _doc(src)
        return doc, backend.build(doc, "wf.w", self.workdir)

    def _ran(self, lines, step_name):
        return any(step_name in line for line in lines)


@NEEDS_TOOLS
class TestParameterContract(_Built):
    """The compiled C declaration must match the emitted MLIR signature."""

    def test_two_condition_fields_agree(self):
        """Control: the shape the shim was written for must agree (and did)."""
        doc, _ = self._build(TWO)
        self.assertEqual(_c_param_count(self.workdir), _mlir_param_count(doc),
                         "two-field case must agree; if this fails the harness "
                         "is wrong, not the code")

    def test_one_condition_field_agrees(self):
        """One field fewer than the shim hardcodes must still agree."""
        doc, _ = self._build(ONE)
        self.assertEqual(_c_param_count(self.workdir), _mlir_param_count(doc))

    def test_three_condition_fields_agree(self):
        """One field more than the shim hardcodes must still agree."""
        doc, _ = self._build(THREE)
        self.assertEqual(_c_param_count(self.workdir), _mlir_param_count(doc),
                         "C declaration must be generated from the same field "
                         "list emit_mlir uses")

    def test_no_condition_fields_agree(self):
        """Boundary: a workflow with no guards takes only the skip flag."""
        doc, _ = self._build(NONE)
        self.assertEqual(_mlir_param_count(doc), 1)
        self.assertEqual(_c_param_count(self.workdir), 1)


@NEEDS_TOOLS
class TestGuardOutcomes(_Built):
    """A satisfied comparison guard must execute its step, whatever its slot."""

    def test_first_field_guard_executes_when_satisfied(self):
        """Control: the already-working slot keeps working."""
        _, binary = self._build(TWO)
        _, lines = backend.run_binary(binary, condition_fields={"counter": 0, "flag": 1})
        self.assertTrue(self._ran(lines, "Guarded"))

    def test_first_field_guard_skips_when_unsatisfied(self):
        """Control (negative): the guard can still go the other way."""
        _, binary = self._build(TWO)
        _, lines = backend.run_binary(binary, condition_fields={"counter": 0, "flag": 0})
        self.assertFalse(self._ran(lines, "Guarded"))

    def test_third_field_guard_executes_when_satisfied(self):
        """`retries < 5` with retries=1 must run its step, not read a stale register."""
        _, binary = self._build(THREE)
        rc, lines = backend.run_binary(
            binary, condition_fields={"counter": 1, "flag": 1, "retries": 1})
        self.assertEqual(rc, 0, "\n".join(lines))
        self.assertTrue(self._ran(lines, "GuardedByRetries"),
                        "step guarded by the 3rd condition field was dropped:\n"
                        + "\n".join(lines))

    def test_third_field_guard_skips_when_unsatisfied(self):
        """And it must still be able to go the other way."""
        _, binary = self._build(THREE)
        _, lines = backend.run_binary(
            binary, condition_fields={"counter": 1, "flag": 1, "retries": 9})
        self.assertFalse(self._ran(lines, "GuardedByRetries"))


@NEEDS_TOOLS
class TestPayloadFieldSelection(_Built):
    """Values must be bound by field name, not by position in the payload."""

    def test_unrelated_payload_int_does_not_shift_bindings(self):
        """An int the conditions never mention must not displace a real field."""
        doc = _doc(TWO)
        clean = differential.observe_mode_b(
            doc, "wf.w", self.workdir, payload={"flag": 1, "counter": 0})
        noisy = differential.observe_mode_b(
            doc, "wf.w", self.workdir, payload={"flag": 1, "counter": 0, "extra": 0})
        self.assertIn("step Guarded", clean["order"],
                      "control failed: guard should run when flag=1")
        self.assertEqual(noisy["order"], clean["order"],
                         "an unrelated payload int changed the guard outcome")

    def test_unrelated_payload_int_cannot_force_execution(self):
        """The inverse: noise must not switch a closed guard on."""
        doc = _doc(TWO)
        clean = differential.observe_mode_b(
            doc, "wf.w", self.workdir, payload={"flag": 0, "counter": 0})
        noisy = differential.observe_mode_b(
            doc, "wf.w", self.workdir, payload={"flag": 0, "counter": 0, "extra": 7})
        self.assertNotIn("step Guarded", clean["order"],
                         "control failed: guard should not run when flag=0")
        self.assertEqual(noisy["order"], clean["order"],
                         "an unrelated payload int switched the guard on")

    def test_missing_condition_field_defaults_without_crashing(self):
        """Boundary: a condition field absent from the payload is treated as 0."""
        doc = _doc(TWO)
        observed = differential.observe_mode_b(doc, "wf.w", self.workdir, payload={})
        self.assertNotIn("step Guarded", observed["order"])
        self.assertEqual(observed["status"], "completed")


@NEEDS_TOOLS
class TestCliPassesConditionFields(_Built):
    """M1: the CLI build path must be able to supply condition values."""

    def _cli(self, src, extra):
        path = os.path.join(self.workdir, "w.lnpl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(src)
        proc = subprocess.run(
            [sys.executable, "-m", "lnpl", "build", path, "--workflow", "wf.w",
             "--workdir", os.path.join(self.workdir, "out"), "--run"] + extra,
            capture_output=True, text=True,
            cwd=os.path.join(REPO, "impl"))
        return proc

    def test_cli_field_value_opens_the_guard(self):
        proc = self._cli(TWO, ["--field", "flag=1"])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("step Guarded", proc.stdout,
                      "CLI did not pass the condition value:\n" + proc.stdout)

    def test_cli_without_field_leaves_the_guard_closed(self):
        proc = self._cli(TWO, [])
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("step Guarded", proc.stdout)

    def test_cli_rejects_malformed_field(self):
        proc = self._cli(TWO, ["--field", "flag"])
        self.assertNotEqual(proc.returncode, 0,
                            "a --field without '=' must be rejected")
        self.assertIn("field", (proc.stdout + proc.stderr).lower())


class TestFieldValueValidation(unittest.TestCase):
    """Non-integer condition values must fail loudly, not silently truncate."""

    def test_non_numeric_value_is_a_backend_error(self):
        with self.assertRaises(backend.BackendError):
            backend.run_binary("/nonexistent", condition_fields={"flag": "yes"})

    def test_float_value_is_a_backend_error(self):
        with self.assertRaises(backend.BackendError):
            backend.run_binary("/nonexistent", condition_fields={"flag": 1.5})

    def test_bool_value_is_accepted_as_zero_or_one(self):
        """Boundary: bool is an int in Python and 0/1 is a meaningful i64."""
        self.assertEqual(backend.encode_condition_value(True), 1)
        self.assertEqual(backend.encode_condition_value(False), 0)


if __name__ == "__main__":
    unittest.main()

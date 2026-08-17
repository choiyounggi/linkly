"""RFC-0024 — enforcement diagnostics carry a source line (issue #67).

`declared-not-enforced`, `declared-measured-only`, and `authorization-not-
verified` used to point only at a node id (`[security.shorten]`); nobody
reading `lnpl compile`'s output could jump to the declaration without
grepping. This module pins the fix against the golden `examples/shorten.lnpl`,
which carries all three: `security jwt` (unenforced), `performance response`
(measured only), and `authorize owner` (never checked).

The first two are compile-time (`lower.py::_declaration_diagnostics`), so
`lnpl compile` alone shows them. `authorization-not-verified` is emitted by
the interpreter (`interp.py`), which `lnpl compile` never runs — only `lnpl
run` does — so its line is exercised here by running the workflow directly,
the same way `TestGoldenExecution` in test_golden.py does.
"""

import os
import subprocess
import sys
import unittest

from lnpl.diagnostics import Diagnostics, format_lines
from lnpl.interp import Interpreter, refinement_index, sample_payload
from lnpl.lower import lower
from lnpl.parser import parse

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHORTEN_SRC = os.path.join(REPO, "examples", "shorten.lnpl")
VALIDATOR = os.path.join(REPO, "scripts", "validate_ir.py")


def _compile_shorten():
    with open(SHORTEN_SRC, encoding="utf-8") as fh:
        source = fh.read()
    return lower(parse(source), "shorten")


def _run_shorten():
    """Compile and run examples/shorten.lnpl to completion.

    `repo_rows={}` is enough: the workflow's only RepositoryCall is `create
    link`, which does not need a pre-seeded row (the same recipe
    test_refinement_runtime.py's shortener fixture uses).
    """
    doc = _compile_shorten().to_document()
    entities = [n for n in doc["nodes"] if n["kind"] == "Entity"]
    payload = sample_payload(entities, refinement_index(doc))
    interp = Interpreter(doc, repo_rows={})
    result = interp.run_workflow("wf.shorten", payload)
    return interp, result, doc


class TestCompileTimeEnforcementDiagnosticsCarryLine(unittest.TestCase):
    """The two enforcement diagnostics `lnpl compile examples/shorten.lnpl`
    emits — both from `lower.py`, so no run is needed to observe them."""

    def test_declared_not_enforced_carries_the_security_clause_line(self):
        module = _compile_shorten()
        by_code = {d.code: d for d in module.diagnostics}
        d = by_code["declared-not-enforced"]
        self.assertEqual(d.subject, "security jwt")
        # `jwt` sits on examples/shorten.lnpl:46, under the `security` clause.
        self.assertEqual(d.line, 46)

    def test_declared_measured_only_carries_the_performance_clause_line(self):
        module = _compile_shorten()
        by_code = {d.code: d for d in module.diagnostics}
        d = by_code["declared-measured-only"]
        self.assertEqual(d.subject, "performance response")
        # `response < 40ms` sits on examples/shorten.lnpl:48.
        self.assertEqual(d.line, 48)

    def test_both_render_as_line_n_in_the_compile_output(self):
        module = _compile_shorten()
        rendered = format_lines(module.diagnostics)
        enforcement = [l for l in rendered
                       if "declared-not-enforced" in l
                       or "declared-measured-only" in l]
        self.assertEqual(len(enforcement), 2)
        for line in enforcement:
            self.assertIn("(line ", line)


class TestRuntimeAuthorizationDiagnosticCarriesLine(unittest.TestCase):
    """`authorization-not-verified` only fires once the workflow actually
    runs (`lnpl run`, not `lnpl compile`) — RFC-0024's runtime path."""

    def test_authorization_not_verified_carries_the_steps_line(self):
        interp, result, _doc = _run_shorten()
        self.assertEqual(result["status"], "completed")
        by_code = {d.code: d for d in interp.diagnostics}
        d = by_code["authorization-not-verified"]
        self.assertEqual(d.subject, "owner")
        # `authorize owner` sits on examples/shorten.lnpl:53.
        self.assertEqual(d.line, 53)

    def test_it_renders_as_line_n_in_the_run_output(self):
        interp, _result, _doc = _run_shorten()
        rendered = format_lines(interp.diagnostics)
        auth_lines = [l for l in rendered if "authorization-not-verified" in l]
        self.assertEqual(len(auth_lines), 1)
        self.assertIn("(line 53)", auth_lines[0])


class TestMissingLineFallsBackToTheOldFormat(unittest.TestCase):
    """Boundary: a node lowering never recorded a line for (or an IR handed
    in from outside this compiler) must not crash the diagnostic — RFC-0024
    made `line` optional precisely so an absent one degrades, not errors."""

    def test_authorization_effect_without_a_line_renders_the_pre_rfc_form(self):
        interp, _result, doc = _run_shorten()
        auth_node = next(n for n in doc["nodes"] if n["kind"] == "Authorization")
        del auth_node["line"]
        # Re-run against the now-line-less document.
        entities = [n for n in doc["nodes"] if n["kind"] == "Entity"]
        payload = sample_payload(entities, refinement_index(doc))
        interp2 = Interpreter(doc, repo_rows={})
        result2 = interp2.run_workflow("wf.shorten", payload)
        self.assertEqual(result2["status"], "completed")

        by_code = {d.code: d for d in interp2.diagnostics}
        d = by_code["authorization-not-verified"]
        self.assertIsNone(d.line)

        rendered = format_lines(interp2.diagnostics)
        auth_lines = [l for l in rendered if "authorization-not-verified" in l]
        self.assertEqual(len(auth_lines), 1)
        self.assertNotIn("(line", auth_lines[0])
        self.assertIn("[wf.shorten.step.2.authz]", auth_lines[0])


class TestDiagnosticsAddStillValidatesTheCode(unittest.TestCase):
    """Error case: `Diagnostics.add`'s new `line` keyword must not loosen the
    existing code-validation contract (`Diagnostic.__post_init__`)."""

    def test_an_unknown_code_still_raises_even_with_a_line_supplied(self):
        diagnostics = Diagnostics()
        with self.assertRaises(ValueError):
            diagnostics.add(code="not-a-real-code", where="x", subject="y",
                            message="z", line=1)


class TestSchemaGateCoversTheLineField(unittest.TestCase):
    """A suite in which nothing loads the schema is unaffected by any edit to
    it (test_golden.py's rationale) — invoke the gate here too, and pin the
    two negatives RFC-0024 added to `validate_ir.py --self-test`."""

    def test_the_schema_self_test_rejects_the_line_negatives(self):
        proc = subprocess.run([sys.executable, VALIDATOR, "--self-test"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        for label in ("line below minimum: wf.login.line = 0",
                      "line is not an integer: wf.login.line = '4'"):
            self.assertIn(label, proc.stdout,
                          "the gate no longer runs the %r negative" % label)


if __name__ == "__main__":
    unittest.main()

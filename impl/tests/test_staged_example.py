"""examples/staged.lnpl (issue #211, RFC-0058) — the exemplar's own regression guard.

Four claims, each run against the actual toolchain:

  1. `lnpl compile --strict=warning` exits 0 with zero diagnostics of any grade.
  2. `lnpl spec --run`'s three cases (both guards true / first false / second
     false) all pass, and every one asserts `effects complete`.
  3. The staged pattern rests on "a comparison on an unbound reference is
     false" (RFC-0012 §G12.4): when the first guard is false, `pay` is never
     bound and the second guard's skip record shows `pay.status` as None,
     not an error.
  4. The regression guard can go red: flattening `pipeline place` (the
     author forgot it) leaves the guard owning only the create, so the
     payment call runs even when stock is short and the first-false case
     fails.

Mode A/B equivalence is out of scope (the brief scopes the exemplar to the
fake backend).
"""

import os
import subprocess
import sys
import unittest

from lnpl.drivers import FakeNetworkDriver
from lnpl.interp import Interpreter, refinement_index, sample_payload
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import default_rows
from lnpl.spec import extract, run_manifest

from tests.fixtures import STAGED_LNPL

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IMPL = os.path.join(REPO, "impl")
WORKFLOW = "wf.place.order"

# The whole first stage: the marker line and its two child steps.
PIPELINE_BLOCK = ("    pipeline place\n"
                  "        create order as o\n"
                  "        call PaymentGateway as pay\n")


def _source():
    with open(STAGED_LNPL, encoding="utf-8") as fh:
        return fh.read()


def _document(source=None):
    return lower(parse(source or _source()), "staged").to_document()


def _run(stock, quantity):
    """Run PlaceOrder on the fake backend with the stored product's stock set."""
    doc = _document()
    product = [n for n in doc["nodes"] if n["kind"] == "Entity"][0]
    payload = dict(sample_payload([product], refinement_index(doc)))
    payload["quantity"] = quantity
    rows = default_rows(doc, WORKFLOW, payload)
    for row in rows["entity.product"].values():
        row["stock"] = stock
    interp = Interpreter(doc, repo_rows=rows, network=FakeNetworkDriver({}))
    return interp, interp.run_workflow(WORKFLOW, payload)


class TestStagedStrictGateIsClean(unittest.TestCase):

    def test_strict_warning_gate_exits_zero_with_no_diagnostics(self):
        env = dict(os.environ, PYTHONPATH=IMPL)
        proc = subprocess.run(
            [sys.executable, "-m", "lnpl", "compile", STAGED_LNPL,
             "--strict=warning", "-o", os.devnull],
            capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stderr, "",
                         "the exemplar must carry zero diagnostics: %r"
                         % proc.stderr)


class TestStagedSpecAllCasesPass(unittest.TestCase):

    def _manifest(self):
        return extract(parse(_source()), "staged")

    def test_the_manifest_declares_exactly_three_cases(self):
        self.assertEqual([c["name"] for c in self._manifest()["cases"]],
                         ["PlaceOrder spec 1", "PlaceOrder spec 2",
                          "PlaceOrder spec 3"])

    def test_every_case_passes(self):
        passed, failed, lines = run_manifest(self._manifest(), _document())
        self.assertEqual(failed, 0, "\n".join(lines))
        self.assertGreater(passed, 0)

    def test_every_case_asserts_effects_complete(self):
        for case in self._manifest()["cases"]:
            with self.subTest(case=case["name"]):
                self.assertIn("effects complete", case["expect"])


class TestStagedFlow(unittest.TestCase):
    """What each stage actually did, read off the run rather than the spec."""

    def test_both_stages_run_and_the_confirmed_order_is_stored(self):
        interp, result = _run(stock=10, quantity=1)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["skipped"], [])
        orders = list(interp.repo.rows["entity.order"].values())
        self.assertEqual([o["status"] for o in orders], ["confirmed"])

    def test_a_false_first_guard_leaves_pay_unbound_and_the_second_guard_false(self):
        # RFC-0012 §G12.4: `pay` is never bound, so `pay.status == 200`
        # compares an unbound reference — false, not an error.
        _interp, result = _run(stock=0, quantity=5)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([s["condition"] for s in result["skipped"]],
                         ["product.stock >= input.quantity", "pay.status == 200"])
        self.assertEqual(result["skipped"][1]["evaluations"],
                         [{"ref": "pay.status", "value": None, "op": "==",
                           "expected": 200, "holds": False}])

    def test_an_empty_product_table_fails_the_read_before_any_guard(self):
        # Boundary: no stored product — the `find` fails the step (issue #197),
        # so neither stage is reached.
        doc = _document()
        interp = Interpreter(doc, repo_rows={}, network=FakeNetworkDriver({}))
        result = interp.run_workflow(WORKFLOW, {"id": "00000000-0000-4000-8000-000000000001",
                                               "quantity": 1})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_kind"], "not-found")
        self.assertEqual(result["skipped"], [])


class TestStagedMutatedVariantGoesRed(unittest.TestCase):
    """Flatten the first stage — same steps, no `pipeline` — and it must fail.

    Deleting the block outright, or only its marker line with the steps left
    indented, no longer compiles at all (a guard after a guard; RFC-0019's
    guard-scope rule), so neither reaches the spec runner. The flat variant
    compiles: the guard owns only `create order as o`, the payment call runs
    unconditionally, answers 200, and the confirm stage then writes to an
    order that was never created.
    """

    FLAT = ("    create order as o\n"
            "    call PaymentGateway as pay\n")

    def _mutated(self):
        source = _source()
        self.assertIn(PIPELINE_BLOCK, source,
                      "this control is anchored on the exact pipeline block "
                      "text; examples/staged.lnpl no longer declares it")
        return source.replace(PIPELINE_BLOCK, self.FLAT)

    def test_the_mutation_drops_the_pipeline_node(self):
        kinds = [n["kind"] for n in _document()["nodes"]]
        mutated = [n["kind"] for n in _document(self._mutated())["nodes"]]
        self.assertEqual(kinds.count("Pipeline") - mutated.count("Pipeline"), 1)

    def test_the_first_false_case_now_fails(self):
        mutated = self._mutated()
        _passed, failed, lines = run_manifest(extract(parse(mutated), "staged"),
                                              _document(mutated))
        self.assertEqual(failed, 1, "\n".join(lines))
        self.assertIn("FAIL PlaceOrder spec 2 — completed (status=failed)",
                      "\n".join(lines))


class TestStagedIsReachable(unittest.TestCase):
    """An exemplar nobody is routed to teaches nothing: the authoring skill
    and the generated patterns page must both point here, and the RFC they
    cite must exist."""

    SKILL_DIR = os.path.join(REPO, "plugins", "lnpl", "skills", "lnpl-authoring")

    def _read(self, *parts):
        with open(os.path.join(self.SKILL_DIR, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_the_skill_routing_link_resolves_to_this_file(self):
        link = "../../../../examples/staged.lnpl"
        self.assertIn("(%s)" % link, self._read("SKILL.md"))
        self.assertEqual(os.path.realpath(os.path.join(self.SKILL_DIR, link)),
                         os.path.realpath(STAGED_LNPL))

    def test_the_patterns_page_names_this_file_and_its_rfc(self):
        text = self._read("references", "patterns.md")
        self.assertIn("examples/staged.lnpl", text)
        self.assertIn("RFC-0058", text)
        self.assertTrue(os.path.isfile(os.path.join(
            REPO, "rfcs", "0058-pipeline-implicit-close-indentation.md")))


if __name__ == "__main__":
    unittest.main()

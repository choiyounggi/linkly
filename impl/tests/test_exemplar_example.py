"""examples/linkhub.lnpl (issue #66) — the exemplar's own regression guard.

Four claims, four checks, each run against the actual toolchain rather than a
hand-copied assertion of what it should say:

  1. `lnpl compile --strict=warning` exits 0 with zero diagnostics of any
     grade — the file's whole point is that everything in it executes.
  2. `lnpl spec --run`'s three cases (normal / error / boundary, RFC/spec.md
     "정상/에러/경계") all pass.
  3. The regression guard can actually go red: a variant with the `pipeline`
     block removed fails the normal case's `rows`/`cache written`
     expectations. This is a coordinator-approved reading of the acceptance
     criterion — see the class docstring below for why a lighter mutation
     (deleting only the `pipeline persist` marker line) does not qualify.
  4. Mode A and mode B agree on both workflows (`lnpl diff`), skipped without
     the MLIR/LLVM toolchain — the same gate `test_backend.py` uses.
"""

import os
import subprocess
import sys
import tempfile
import unittest

from lnpl import backend, differential
from lnpl.interp import refinement_index, sample_payload
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import default_rows
from lnpl.spec import extract, run_manifest

from tests.fixtures import LINKHUB_LNPL

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IMPL = os.path.join(REPO, "impl")

HAS_TOOLS = backend.toolchain_available()
NEEDS_TOOLS = unittest.skipUnless(
    HAS_TOOLS, "MLIR/LLVM toolchain not installed (brew install llvm)")

# The whole `persist` pipeline: the marker line and its three child steps.
# Removing only the marker line is not used as the negative — see
# `TestLinkhubMutatedVariantGoesRed`.
PIPELINE_BLOCK = ("    pipeline persist\n"
                  "        create bookmark\n"
                  "        cache bookmark\n"
                  "        emit bookmarkSaved\n")


def _source():
    with open(LINKHUB_LNPL, encoding="utf-8") as fh:
        return fh.read()


def _document(source=None):
    return lower(parse(source or _source()), "linkhub").to_document()


def _payload(doc):
    entities = [n for n in doc["nodes"] if n["kind"] == "Entity"]
    return dict(sample_payload(entities, refinement_index(doc)))


class TestLinkhubStrictGateIsClean(unittest.TestCase):
    """DoD 3: `lnpl compile examples/linkhub.lnpl --strict=warning` -> rc=0.

    Shells out to the real CLI (like `test_drivers_integration.py`'s
    `ProcessBoundaryTest`) so a future diagnostic added to
    `diagnostics.SEVERITY_OF` that regrades a verb this file uses is caught
    here, not only in a hand-copied assertion.
    """

    def test_strict_warning_gate_exits_zero_with_no_diagnostics(self):
        env = dict(os.environ, PYTHONPATH=IMPL)
        proc = subprocess.run(
            [sys.executable, "-m", "lnpl", "compile", LINKHUB_LNPL,
             "--strict=warning"],
            capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        # Not just zero *warnings* — zero diagnostics of any grade. D5's
        # claim is that the exemplar is fully executed, not merely that it
        # clears the warning gate while carrying `info`-grade declarations.
        self.assertEqual(proc.stderr, "",
                         "the exemplar must carry zero diagnostics: %r"
                         % proc.stderr)


class TestLinkhubSpecAllCasesPass(unittest.TestCase):
    """DoD 2: three spec blocks (normal/error/boundary), every case PASS."""

    def test_the_manifest_declares_exactly_three_cases(self):
        decls = parse(_source())
        manifest = extract(decls, "linkhub")
        self.assertEqual(len(manifest["cases"]), 3)
        self.assertEqual([c["name"] for c in manifest["cases"]],
                         ["SaveBookmark spec 1", "SaveBookmark spec 2",
                          "GetBookmark spec"])

    def test_every_case_passes(self):
        decls = parse(_source())
        manifest = extract(decls, "linkhub")
        doc = _document()
        _passed, failed, lines = run_manifest(manifest, doc)
        self.assertEqual(failed, 0, "\n".join(lines))

    def test_every_case_asserts_effects_complete(self):
        # DoD 2: "전 spec effects complete" — checked on the manifest text
        # itself, not just that the run happened to satisfy it, so a future
        # case that forgets the clause is caught even if it would still pass.
        decls = parse(_source())
        manifest = extract(decls, "linkhub")
        for case in manifest["cases"]:
            with self.subTest(case=case["name"]):
                self.assertIn("effects complete", case["expect"])


class TestLinkhubMutatedVariantGoesRed(unittest.TestCase):
    """DoD 5 / plan D6③: prove the regression guard can actually fail.

    Coordinator-approved reading (2026-08-17): deleting only the `pipeline
    persist` marker line and leaving its three child steps in place produces
    NO observable difference — measured directly against this file, status
    stays `completed`, all four steps still run, `rows Bookmark 1` still
    holds. That is because mode A's interpreter treats `Pipeline` as purely
    structural: `interp.py`'s `_flatten_items` comments that "Concurrency and
    Pipeline both expand to their children in declared order," identically to
    plain top-level steps. So the marker-only edit is not a valid negative
    control here — it does not exercise anything `effects complete`/`rows`
    would catch.

    The mutation that DOES go red is removing the whole pipeline block — the
    marker line and its three child steps together — which drops `create
    bookmark` (no row is written) and `cache bookmark` (nothing is cached).
    """

    def _mutated_document(self):
        source = _source()
        self.assertIn(PIPELINE_BLOCK, source,
                      "this control is anchored on the exact pipeline block "
                      "text; examples/linkhub.lnpl no longer declares it, so "
                      "the control would silently degrade to a no-op")
        mutated = source.replace(PIPELINE_BLOCK, "")
        return lower(parse(mutated), "linkhub").to_document()

    def test_the_mutation_actually_drops_the_pipeline_node(self):
        original_kinds = {n["kind"] for n in _document()["nodes"]}
        self.assertIn("Pipeline", original_kinds)
        mutated_kinds = {n["kind"] for n in self._mutated_document()["nodes"]}
        self.assertNotIn("Pipeline", mutated_kinds)

    def test_the_normal_case_rows_and_cache_expectations_now_fail(self):
        doc = self._mutated_document()
        manifest = extract(parse(_source().replace(PIPELINE_BLOCK, "")),
                           "linkhub")
        _passed, failed, lines = run_manifest(manifest, doc)
        self.assertGreater(failed, 0,
                           "removing the whole pipeline block must fail at "
                           "least one expectation")
        report = "\n".join(lines)
        self.assertIn("FAIL SaveBookmark spec 1 — rows Bookmark 1", report)
        self.assertIn("FAIL SaveBookmark spec 1 — cache written", report)


@NEEDS_TOOLS
class TestLinkhubModeEquivalence(unittest.TestCase):
    """DoD 3: `lnpl diff` — mode A and mode B agree, on both workflows."""

    def setUp(self):
        self.workdir = tempfile.mkdtemp(
            prefix="lnpl-diff-linkhub-", dir=os.path.join(REPO, ".claude", "tmp"))
        self.addCleanup(lambda: subprocess.run(
            ["rm", "-rf", self.workdir], check=False))

    def test_save_bookmark_is_equivalent(self):
        doc = _document()
        payload = _payload(doc)
        ok, report = differential.verify(
            doc, "wf.save.bookmark", payload,
            default_rows(doc, "wf.save.bookmark", payload), self.workdir)
        self.assertTrue(ok, "\n".join(report))
        self.assertIn("differential: EQUIVALENT", report[-1])

    def test_get_bookmark_is_equivalent(self):
        doc = _document()
        payload = _payload(doc)
        ok, report = differential.verify(
            doc, "wf.get.bookmark", payload,
            default_rows(doc, "wf.get.bookmark", payload), self.workdir)
        self.assertTrue(ok, "\n".join(report))
        self.assertIn("differential: EQUIVALENT", report[-1])


if __name__ == "__main__":
    unittest.main()

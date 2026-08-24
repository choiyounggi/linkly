"""Issue #62: the no-op-verb defenses stop being opt-in.

`unknown-verb` is a real diagnostic, `--strict=warning` is a real gate, and
`effects complete` is a real spec assertion — but before this change none of
them ran by default. A workflow step that misspells its verb into something
outside `VERB_LEXICON` compiled rc=0 and passed every spec case, because
nothing in the verify path turned "diagnostic reported" into "build fails".

This module pins the gate side of that fix: `lnpl compile --strict=warning`,
promoted to lnpl-verify's step 1, must mechanically reject a no-op-verb leak
(rc != 0) while passing the three non-fixture golden examples (rc == 0,
`declared-*` `info` diagnostics do not gate).

Four cases:
  1. The three golden examples (shorten/checkout/guarded) pass the gate as
     committed.
  2. `login.lnpl` — issue #36's dedicated regression fixture, never edited —
     still fails the gate: it is the fixture proving `unknown-verb` remains a
     real, gate-worthy diagnostic.
  3. Issue #62's own repro: `create link` mutated to the vocab-outside
     lookalike `persist link` in a throwaway copy of `shorten.lnpl`. This is
     the exact scenario the issue reported working (rc=0) before the gate was
     promoted to the default path.
  4. `guarded.lnpl` is the boundary: it emits zero diagnostics at all, so the
     gate has nothing to report and still exits 0.
"""

import contextlib
import io
import os
import shutil
import tempfile
import unittest

from lnpl import cli

from tests.fixtures import CHECKOUT_LNPL, GUARDED_LNPL, SHORTEN_LNPL

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOGIN_LNPL = os.path.join(REPO, "examples", "login.lnpl")
TMP_ROOT = os.path.join(REPO, ".claude", "tmp")


def run_cli_split(argv):
    """Drive `cli.main(argv)`, keeping stdout and stderr apart."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


class TestGoldenExamplesPassTheStrictGate(unittest.TestCase):
    """(1) shorten/checkout/guarded compile clean under the new default gate.

    Each carries only `info`-grade `declared-*` diagnostics — `--strict=warning`
    gates warning-and-above, so none of these block.
    """

    def test_shorten_passes_strict_warning(self):
        rc, _, err = run_cli_split(["compile", SHORTEN_LNPL, "--strict=warning"])
        self.assertEqual(rc, 0, err)

    def test_checkout_passes_strict_warning(self):
        rc, _, err = run_cli_split(["compile", CHECKOUT_LNPL, "--strict=warning"])
        self.assertEqual(rc, 0, err)

    def test_guarded_passes_strict_warning(self):
        rc, _, err = run_cli_split(["compile", GUARDED_LNPL, "--strict=warning"])
        self.assertEqual(rc, 0, err)


class TestLoginFixtureFailsTheStrictGate(unittest.TestCase):
    """(2) `login.lnpl` (issue #36's fixture, never edited) still gates.

    Its three unknown verbs (`generate`/`audit`/`return`) are `warning`-grade
    `unknown-verb` diagnostics, so `--strict=warning` rejects it — proving the
    gate can actually turn red, not just pass everything it is pointed at.
    """

    def test_login_fails_strict_warning(self):
        rc, _, err = run_cli_split(["compile", LOGIN_LNPL, "--strict=warning"])
        self.assertNotEqual(rc, 0)
        self.assertIn("unknown-verb", err)


class TestIssue62ReproProbeStopsAtTheGate(unittest.TestCase):
    """(3) The exact repro from issue #62's "실측 재현": `create` -> `persist`.

    Before this change, substituting the in-vocabulary verb `create` for the
    outside-vocabulary lookalike `persist` in `shorten.lnpl` compiled rc=0
    with only an unread `unknown-verb` warning on stderr — the bug the whole
    issue is about. This proves the promoted gate now stops that exact case.
    """

    def setUp(self):
        os.makedirs(TMP_ROOT, exist_ok=True)
        self.tmpdir = tempfile.mkdtemp(dir=TMP_ROOT)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_to_persist_substitution_stops_at_the_gate(self):
        with open(SHORTEN_LNPL, encoding="utf-8") as fh:
            source = fh.read()
        self.assertIn("create link", source,
                      "fixture assumption broken: shorten.lnpl no longer has "
                      "a `create link` step to substitute")
        mutated = source.replace("create link", "persist link")

        probe = os.path.join(self.tmpdir, "probe.lnpl")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write(mutated)

        rc, _, err = run_cli_split(["compile", probe, "--strict=warning"])

        self.assertNotEqual(rc, 0)
        self.assertIn("unknown-verb", err)
        self.assertIn("persist", err)


class TestGuardedBoundaryHasNoDiagnostics(unittest.TestCase):
    """(4) The boundary: `guarded.lnpl` reports nothing above `info`, and
    still rc=0. Issue #101 adds one `info`-grade `declared-not-bound` for
    `call token` — the fixture's `token` names no `capability http` — which
    does not gate `--strict=warning` either, the same as the other examples'
    `declared-*` diagnostics this module's docstring already describes."""

    def test_guarded_has_zero_diagnostics(self):
        rc, _, err = run_cli_split(["compile", GUARDED_LNPL, "--strict=warning"])
        self.assertEqual(rc, 0)
        self.assertIn("declared-not-bound", err)
        self.assertNotIn("warning:", err)


if __name__ == "__main__":
    unittest.main()

"""D4: `unknown-entity` (issue #91) must not false-positive on the corpus.

Every real `.lnpl` file under `examples/` and `qa/` that still compiles is
swept for the new diagnostic. Two files are the deliberate exception —
`qa/rerun/cases/batch-report/probes/probe-c1.lnpl` (H-rc1) and `probe-c2.lnpl`
(H-rc2) — the re-measurement probes that documented issue #91 itself (a
multi-word entity's declared spelling used verbatim as a step object, and a
plural noun used where the entity is declared singular). Before this change
both compiled silently with zero diagnostics; catching them is the fix
working, not a regression, so they are pinned to fire exactly once instead of
being swept for zero.

Files that fail to compile at all (LowerError/parse error) are QA probes for
unrelated failure axes (bad policy names, guard/spec grammar, type
mismatches, undeclared events — none of them naming a resolution ambiguity)
and are recorded, not asserted on: they never reach entity resolution.

Two of those uncompiled files are pinned rather than left to that silent
bucket, the same way H-rc1/H-rc2 are pinned in `hits`: issue #127 removed
`security encrypt` from the closed vocabulary, so both payment-refund QA
fixtures (`qa/cases/...` and `qa/rerun/cases/...`, which still declare
`encrypt cardNumber` — qa/ is read-only, per #127's user decision) now fail
to compile for a reason this sweep would otherwise absorb without comment.
Without the pin, the two fixtures would silently drift into "uncompiled"
the moment the vocabulary shrank and the suite would stay green while
quietly covering less — exactly the failure mode this file's own docstring
above warns against for `unknown-entity`.
"""

import glob
import os
import unittest

from lnpl.lower import LowerError, lower
from lnpl.parser import ParseError, parse

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CORPUS = sorted(
    glob.glob(os.path.join(REPO, "examples", "*.lnpl"))
    + glob.glob(os.path.join(REPO, "qa", "**", "*.lnpl"), recursive=True)
)

# H-rc1/H-rc2 (issue #91's own re-measurement evidence): the two files that
# are EXPECTED to newly report `unknown-entity` — everything else compiling
# must report zero.
EXPECTED_HITS = {
    os.path.join(REPO, "qa", "rerun", "cases", "batch-report", "probes",
                 "probe-c1.lnpl"): ["DailyReport"],
    os.path.join(REPO, "qa", "rerun", "cases", "batch-report", "probes",
                 "probe-c2.lnpl"): ["orders"],
}

# issue #127: the two payment-refund QA fixtures are EXPECTED to newly land
# in `uncompiled` now that `security encrypt` is gone from the vocabulary —
# qa/ is read-only (user decision, r1), so the fixtures themselves are not
# migrated. Each maps to why, so a future reader does not mistake this for
# an unrelated grammar failure.
EXPECTED_UNCOMPILED = {
    os.path.join(REPO, "qa", "cases", "payment-refund",
                 "payment-refund.lnpl"):
        "declares `encrypt cardNumber` (2026-08-05 run); #127 removed "
        "`security encrypt` from the vocabulary and qa/ is read-only",
    os.path.join(REPO, "qa", "rerun", "cases", "payment-refund",
                 "payment-refund.lnpl"):
        "declares `encrypt cardNumber` (rerun r2); #127 removed "
        "`security encrypt` from the vocabulary and qa/ is read-only",
}


def _sweep():
    """Compile the whole corpus once; returns (clean, hits, uncompiled) paths.

    `hits` maps path -> the `unknown-entity` subjects it reported (empty dict
    value never occurs — a file with zero hits is filed under `clean`).
    """
    clean, hits, uncompiled = [], {}, []
    for path in CORPUS:
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        try:
            mod = lower(parse(source), "sweep")
        except (LowerError, ParseError):
            uncompiled.append(path)
            continue
        subjects = [d.subject for d in mod.diagnostics.by_code("unknown-entity")]
        if subjects:
            hits[path] = subjects
        else:
            clean.append(path)
    return clean, hits, uncompiled


class TestCorpusSweep(unittest.TestCase):
    def test_the_corpus_is_not_trivially_empty(self):
        # A guard against a glob typo silently making every check below pass.
        self.assertGreaterEqual(len(CORPUS), 30, CORPUS)

    def test_no_compiling_file_reports_an_unexpected_hit(self):
        _clean, hits, _uncompiled = _sweep()
        unexpected = {p: s for p, s in hits.items() if p not in EXPECTED_HITS}
        self.assertEqual(unexpected, {},
                         "unexpected unknown-entity hit(s) in the corpus")

    def test_the_two_known_probes_report_exactly_the_expected_hit(self):
        # H-rc1/H-rc2 (issue #91's own evidence) — pinned, not swept away.
        _clean, hits, _uncompiled = _sweep()
        for path, expected_subjects in EXPECTED_HITS.items():
            self.assertIn(path, hits, path)
            self.assertEqual(hits[path], expected_subjects, path)

    def test_every_compiling_file_is_accounted_for(self):
        clean, hits, uncompiled = _sweep()
        # D4 evidence: nothing compiling falls through the sweep uncounted.
        self.assertEqual(len(clean) + len(hits) + len(uncompiled), len(CORPUS))
        self.assertGreater(len(clean), 0)
        self.assertEqual(set(hits), set(EXPECTED_HITS))

    def test_the_payment_refund_fixtures_are_uncompiled_for_the_pinned_reason(self):
        # issue #127: proves these two land in `uncompiled` (not `clean` or
        # `hits`, and not silently absent from the corpus) — and stays red
        # if either fixture is later migrated or removed without updating
        # this registration.
        _clean, _hits, uncompiled = _sweep()
        for path in EXPECTED_UNCOMPILED:
            self.assertIn(path, CORPUS, path)
            self.assertIn(path, uncompiled, path)


if __name__ == "__main__":
    unittest.main()

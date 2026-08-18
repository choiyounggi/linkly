"""Issue #65 / RFC-0025 — row sets and aggregation, mode B (Task 06).

RFC-0025 §10's central finding: mode B does not model `Assignment` VALUES at
all (`_render_std` never holds a computed value in an SSA register — RFC-0015
§5 already calls that an "allowed difference"), so `sum`/`count` need no new
MLIR. What DOES need fixing is mode B's static failure prediction
(`backend._lnpl_ops`'s fail_at scan) and `differential._check_seed_agreement`,
both of which inherited `query` from `repo_policy.READ_OPS` for reasons that
apply to `read` only. This file proves `lnpl diff` (`differential.verify`)
agrees with mode A on `list`/`sum`/`count` workflows, at the 0-row and N-row
boundary the RFC calls out, and that genuine read-failure divergence
detection still works (a negative control against over-correcting).
"""

import os
import tempfile
import unittest

from lnpl import backend, differential
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.repo_policy import row_key

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HAS_TOOLS = backend.toolchain_available()
NEEDS_TOOLS = unittest.skipUnless(
    HAS_TOOLS, "MLIR/LLVM toolchain not installed (brew install llvm)")

CLICKS_SRC = """capability postgres

entity Link
    field
        id UUID
        clicks Integer

entity Report
    field
        id UUID
        totalClicks Integer
        linkCount Integer

service Analytics
    policy
        timeout 5s

workflow SummarizeClicks
    find report
    list link
    set report.totalClicks to sum link.clicks
    set report.linkCount to count link
    update report
"""

GUARDED_CLICKS_SRC = """capability postgres

entity Link
    field
        id UUID
        clicks Integer

entity Report
    field
        id UUID
        totalClicks Integer

service Analytics
    policy
        timeout 5s

workflow SummarizeClicks
    find report
    when report.totalClicks == 0
    list link
    set report.totalClicks to sum link.clicks
    update report
"""


def clicks_doc(src=CLICKS_SRC):
    return lower(parse(src), "m").to_document()


class TestDifferentialEquivalence(unittest.TestCase):
    """`lnpl diff` (`differential.verify`) agrees on `list`/`sum`/`count`."""

    def setUp(self):
        self.workdir = tempfile.mkdtemp(
            prefix="lnpl-rowset-diff-", dir=os.path.join(REPO, ".claude", "tmp"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.workdir, ignore_errors=True)

    @NEEDS_TOOLS
    def test_zero_rows_is_equivalent(self):
        """RFC-0025 §10: the boundary case — an unseeded `list`-only entity
        must NOT make mode B predict a failure mode A never has."""
        doc = clicks_doc()
        payload = {"id": "r-1"}
        rows = {"entity.report": {row_key("entity.report", payload): {"id": "r-1"}}}
        ok, report = differential.verify(doc, "wf.summarize.clicks", payload,
                                         rows, self.workdir)
        self.assertTrue(ok, "\n".join(report))

    @NEEDS_TOOLS
    def test_n_rows_is_equivalent(self):
        doc = clicks_doc()
        payload = {"id": "r-1"}
        rows = {
            "entity.report": {row_key("entity.report", payload): {"id": "r-1"}},
            "entity.link": {"0": {"id": "0", "clicks": 5},
                            "1": {"id": "1", "clicks": 3},
                            "2": {"id": "2", "clicks": 9}},
        }
        ok, report = differential.verify(doc, "wf.summarize.clicks", payload,
                                         rows, self.workdir)
        self.assertTrue(ok, "\n".join(report))

    @NEEDS_TOOLS
    def test_a_guarded_list_is_equivalent(self):
        """A `list` under a `when` — mode B's scf.if branching must agree with
        mode A on whether the guarded RepositoryCall + Assignment ran at all,
        for both a taken and a not-taken guard."""
        doc = clicks_doc(GUARDED_CLICKS_SRC)
        for totals, label in ((0, "guard true"), (5, "guard false")):
            with self.subTest(label):
                # RFC-0012 §G12.6: mode B derives the guard-watched field from
                # the SEED RULE (a copy of the payload), so it has to be in
                # the payload too, or `_check_rows_are_reproducible` correctly
                # refuses a comparison mode B could not have reproduced.
                payload = {"id": "r-1", "totalClicks": totals}
                rows = {"entity.report": {row_key("entity.report", payload):
                                          {"id": "r-1", "totalClicks": totals}},
                       "entity.link": {"0": {"id": "0", "clicks": 4}}}
                ok, report = differential.verify(doc, "wf.summarize.clicks",
                                                 payload, rows, self.workdir)
                self.assertTrue(ok, "\n".join(report))

    @NEEDS_TOOLS
    def test_no_row_flag_is_equivalent(self):
        """`--no-row`'s seed condition (`seeded=frozenset()`) — the entity the
        workflow `find`s is unseeded on purpose, so BOTH modes must agree the
        run fails at `find report`, before `list` is ever reached."""
        doc = clicks_doc()
        payload = {"id": "r-1"}
        ok, report = differential.verify(doc, "wf.summarize.clicks", payload,
                                         {}, self.workdir, seeded=frozenset())
        self.assertTrue(ok, "\n".join(report))


class TestFailAtPredictionIsNarrowedToRead(unittest.TestCase):
    """`backend._lnpl_ops`'s static failure scan: `query` (`list`) must never
    be predicted to fail on an unseeded entity — only `read` does."""

    def test_an_unseeded_list_only_workflow_predicts_no_failure(self):
        doc = clicks_doc()
        # `find report` would fail first if `report` were also unseeded
        # (unseeded `read`), and `list link` would never even be reached — so
        # seed `report` and leave only `link` unseeded, to isolate the
        # `query` branch this test is actually about.
        module_attrs, ops = backend._lnpl_ops(
            doc, "wf.summarize.clicks", seeded=frozenset({"entity.report"}),
            payload={"id": "r-1"})
        self.assertNotIn("lnpl.terminal_status", module_attrs,
                         "an unseeded `list`-only entity must not be predicted "
                         "to fail — an empty RowSet is a normal result")
        self.assertEqual(len(ops), 5,
                         "all five steps must be predicted to run: find, "
                         "list, set totalClicks, set linkCount, update")

    def test_an_unseeded_read_still_predicts_failure(self):
        """Negative control: the narrowing must not swallow `read`'s own
        failure prediction — only `query` becomes forgiving."""
        doc = clicks_doc()
        module_attrs, ops = backend._lnpl_ops(
            doc, "wf.summarize.clicks", seeded=frozenset(), payload={"id": "r-1"})
        self.assertEqual(module_attrs.get("lnpl.terminal_status"), "failed")
        self.assertEqual(len(ops), 1, "must stop at the failing `find report`")

    def test_read_ops_is_backend_local_and_read_only(self):
        """RFC-0025 §10: `backend.READ_OPS` is `("read",)`, not
        `repo_policy.READ_OPS` (`read`+`query`) — the deliberate-mismatch seam
        `TestRepositoryDivergenceIsDetected` patches."""
        self.assertEqual(backend.READ_OPS, ("read",))


class TestSeedAgreementExcludesQuery(unittest.TestCase):
    """`differential._check_seed_agreement`: a `query`-only entity must not
    have to "agree" between mode A's `repo_rows` and mode B's `seeded`."""

    def test_rowset_rows_do_not_trigger_a_seed_disagreement(self):
        doc = clicks_doc()
        payload = {"id": "r-1"}
        # `entity.link` is seeded in mode A's rows (an indexed RowSet seed)
        # but is correctly ABSENT from mode B's `seeded` (repo_policy
        # excludes `query`-only entities, RFC-0025 §5) — must not raise.
        rows = {
            "entity.report": {row_key("entity.report", payload): {"id": "r-1"}},
            "entity.link": {"0": {"id": "0", "clicks": 5}},
        }
        differential._check_seed_agreement(doc, "wf.summarize.clicks", rows,
                                           frozenset({"entity.report"}))

    def test_a_genuine_read_disagreement_still_raises(self):
        """Negative control: the exclusion is `query`-only, not blanket."""
        doc = clicks_doc()
        payload = {"id": "r-1"}
        rows = {"entity.report": {row_key("entity.report", payload): {"id": "r-1"}}}
        with self.assertRaises(differential.DifferentialError):
            differential._check_seed_agreement(doc, "wf.summarize.clicks", rows,
                                               frozenset())


if __name__ == "__main__":
    unittest.main()

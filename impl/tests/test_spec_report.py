"""Issue #46 [4]: a failing case must say WHY the run failed.

QA measured (t4 F-12) that a spec whose run completed with status=failed
printed only `FAIL ... completed (status=failed)` — diagnosing t4's failure
required a separate `lnpl run` probe to see failed_step/failure_reason. These
tests pin the repair: one `reason:` line per failing case carrying the run's
failed_step and failure_reason; the PASS/FAIL line shapes stay untouched.
"""

import unittest

from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.spec import extract, run_manifest

SRC = """
entity Account
    field
        id UUID
        balance Integer
service AccountService
    policy
        retry 2
workflow Open
    validate account
    find account
    spec
        given
            valid account
        when
            open
        expect
            completed
            steps 2
"""


def build(src=SRC):
    decls = parse(src)
    return lower(decls, "accounts").to_document(), extract(decls, "accounts")


class TestFailureReasonLine(unittest.TestCase):
    def test_a_failed_run_reports_step_and_reason(self):
        # `empty repository` makes `find account` exhaust its retries: the run
        # completes with status=failed, and pre-#46 the report never said so.
        src = SRC.replace("            valid account",
                          "            empty repository")
        doc, manifest = build(src)
        _passed, failed, lines = run_manifest(manifest, doc)
        self.assertGreater(failed, 0)
        reason_lines = [l for l in lines if "reason: step=" in l]
        self.assertEqual(len(reason_lines), 1, lines)
        self.assertIn("find account", reason_lines[0])
        self.assertIn("no row", reason_lines[0])

    def test_an_all_pass_case_has_no_reason_line(self):
        doc, manifest = build()
        _passed, failed, lines = run_manifest(manifest, doc)
        self.assertEqual(failed, 0, lines)
        self.assertFalse([l for l in lines if "reason:" in l], lines)

    def test_a_failing_expectation_on_a_completed_run_has_no_reason_line(self):
        # The run itself succeeded — there is no failed_step to report, and a
        # reason line here would claim one.
        doc, manifest = build(SRC.replace("steps 2", "steps 99"))
        _passed, failed, lines = run_manifest(manifest, doc)
        self.assertEqual(failed, 1)
        self.assertFalse([l for l in lines if "reason:" in l], lines)

    def test_the_expectation_detail_still_carries_got_vs_want(self):
        doc, manifest = build(SRC.replace("steps 2", "steps 99"))
        _passed, _failed, lines = run_manifest(manifest, doc)
        self.assertTrue(any("steps=2 want=99" in l for l in lines), lines)

    def test_the_run_error_path_keeps_its_shape(self):
        # A RunError (not a failed run) already reported its reason; that
        # line's shape is a consumed contract and must not change.
        doc, manifest = build()
        manifest["cases"][0]["workflow"] = "wf.nonexistent"
        _passed, failed, lines = run_manifest(manifest, doc)
        self.assertEqual(failed, 1)
        self.assertTrue(any(l.startswith("FAIL") and "run error:" in l
                            for l in lines), lines)
        self.assertFalse([l for l in lines if "reason: step=" in l], lines)


if __name__ == "__main__":
    unittest.main()

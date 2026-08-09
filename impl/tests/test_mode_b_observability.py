"""RFC-0022 — mode B의 관측 표면이 문서와 코드 양쪽에서 어긋나지 않는다 (이슈 #55).

두 부류의 검사가 있다.

`TestRfc0022NormativeTables`는 RFC-0022의 규범 표 셋을 표의 **key 열**로 앵커하고,
코드가 정하는 셀은 코드와 대조한다. "그 문구가 문서에 있다"가 아니라 "그 주장이
지금도 참이다"를 단정하는 것이 목적이다 — 잔여 목록(표 3)이 특히 그렇다. 잔여는
언젠가 닫히고, 닫힌 뒤에도 "아직 열려 있다"고 적힌 표가 남는 것이 이 문서의 가장
그럴듯한 부패 경로다.

`TestReproductionsAreClosed`는 이슈 #55가 인용한 세 재현(r1 N-2, r1 N-3, r2 N-1)을
**사용자가 보는 표면에서** 다시 돌린다. 단위 테스트는 각 함수가 옳다고 말하고, 이쪽은
그 함수들이 합쳐져 재현 커맨드의 오독 소지를 실제로 없앴다고 말한다.

전사(transcript)를 문자열로 고정하지 않는다 — 진단 문구 한 줄을 다듬으면 깨지는
검사는 계약을 지키지 않고 표현을 지킨다. 대신 구조를 단정한다: 어떤 스텝이 스킵으로
**이름 붙어** 보고되는가, 어떤 코드가 stderr에 나오는가, 두 모드가 같은 이름 집합을
말하는가.
"""

import io
import json
import os
import re
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from lnpl import backend
from lnpl.cli import main
from lnpl.diagnostics import CODES, SEVERITY_OF

from tests.fixtures import GUARDED_LNPL, SHORTEN_LNPL
from tests.test_enforcement_matrix import parse_table

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RFC = os.path.join(REPO, "rfcs", "0022-mode-b-observation-surface.md")
CLI_SURFACE = os.path.join(REPO, "plugins", "lnpl", "skills", "lnpl-authoring",
                           "cli-surface.md")
SKILL = os.path.join(REPO, "plugins", "lnpl", "skills", "lnpl-authoring",
                     "SKILL.md")
# The golden scenario. `tests.fixtures` carries no constant for it, and adding one
# there would widen this task's blast radius for a single path.
LOGIN_LNPL = os.path.join(REPO, "examples", "login.lnpl")

# r2 N-1's shape, inlined rather than read from `qa/rerun/cases/payment-refund/`.
# Three reasons, in order of weight: the mutation harness does not copy `qa/` into
# its mutant trees (`mutation_check.TREE_CONTENTS`), so a test rooted there would
# fail identically across all 77 mutants and read as a caught mutation;
# `qa/**` is read-only evidence; and a regression test should carry the shape it
# pins. The shape is the whole finding — two entities declaring the SAME field
# name, and a guard comparing one against the other.
SAME_NAME_FIELD = """capability postgres

entity Payment
    field
        id UUID
        amountCents Integer

entity Refund
    field
        id UUID
        amountCents Integer

service RefundService

workflow RefundRequest
    read payment
    when input.amountCents <= payment.amountCents
    create refund
"""
CLAUDE_TMP = os.path.join(REPO, ".claude", "tmp")

NEEDS_TOOLS = unittest.skipUnless(
    backend.toolchain_available(),
    "MLIR/LLVM toolchain not installed — see scripts/dev_doctor.sh")

# The three `### ` headings the RFC's normative tables live under, with the column
# count each carries. `section()` cuts to the next `## `, and a `### ` line does not
# terminate it, so each parse reaches the FIRST table after its own heading — which
# holds only because every heading below is immediately followed by its own table.
TABLE_1 = "### 표 1 — 관측 신호별 모드 대조"
TABLE_2 = "### 표 2 — 상태 모델 diff"
TABLE_3 = "### 표 3 — 남는 공백"

SIGNALS = ["`스킵 레코드`", "`스킵 진단`", "`진단 기계 판독`",
           "`Validation 결과를 구동하는 입력`", "`동명 필드 독립 주입`"]
DIMENSIONS = ["`저장소 행`", "`캐시`", "`시계`", "`세션·인증`", "`가드 노드 id`"]
RESIDUALS = ["`bare-binary`", "`build --json 없음`", "`build --strict 없음`",
             "`가드 단위 그룹핑 없음`"]

# `  skipped by `<mode> <condition>`: <step name>` — the line both modes print.
SKIPPED_RE = re.compile(r"^\s*skipped by `[^`]*`: (.+)$", re.MULTILINE)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def subcommand_help(name):
    """`lnpl <name> --help` text. argparse writes it to stdout and exits 0."""
    out = io.StringIO()
    with redirect_stdout(out):
        try:
            main([name, "--help"])
        except SystemExit as exc:
            if exc.code:
                raise AssertionError("`%s --help` exited %r" % (name, exc.code))
    return out.getvalue()


def run_cli(argv):
    """-> (rc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = main(argv)
    return rc, out.getvalue(), err.getvalue()


class TestRfc0022NormativeTables(unittest.TestCase):
    """The three tables, anchored on their key column and checked against code."""

    def setUp(self):
        self.markdown = read(RFC)

    def rows(self, heading, columns):
        return parse_table(self.markdown, heading, columns)

    def keys(self, heading, columns):
        return [cells[0] for cells in self.rows(heading, columns)]

    # ---- table 1: the signals ----

    def test_table_1_covers_exactly_the_named_signals(self):
        self.assertEqual(self.keys(TABLE_1, 4), SIGNALS)

    def test_table_1_names_the_skip_diagnostic_the_code_actually_emits(self):
        # assert-applied: the row must name a code that exists and is graded the
        # way the row's own claim depends on (a `warning`, i.e. something the
        # author can act on), not merely mention a plausible string.
        row = {cells[0]: cells for cells in self.rows(TABLE_1, 4)}["`스킵 진단`"]

        for mode_cell in (row[1], row[2]):
            self.assertIn("guard-skipped-steps", mode_cell)
        self.assertIn("guard-skipped-steps", CODES)
        self.assertEqual(SEVERITY_OF["guard-skipped-steps"], "warning")

    def test_table_1_records_the_per_step_grain_asymmetry(self):
        # RFC-0014 §2.4 lets mode B off the per-guard grain; the table must say
        # so, because a reader comparing the two modes' diagnostic COUNTS would
        # otherwise read the difference as a defect.
        row = {cells[0]: cells for cells in self.rows(TABLE_1, 4)}["`스킵 진단`"]

        self.assertIn("가드당", row[1])
        self.assertIn("스텝당", row[2])

    # ---- table 2: the state model ----

    def test_table_2_covers_exactly_the_named_dimensions(self):
        self.assertEqual(self.keys(TABLE_2, 4), DIMENSIONS)

    def test_table_2_says_mode_b_models_no_repository(self):
        # The claim the union-payload contract is a corollary of. If mode B ever
        # models a store, that contract has to be rewritten, not just this cell.
        row = {cells[0]: cells for cells in self.rows(TABLE_2, 4)}["`저장소 행`"]

        self.assertIn("미모형", row[2])
        self.assertIn("모형함", row[1])

    # ---- table 3: the residuals ----

    def test_table_3_covers_exactly_the_named_residuals(self):
        self.assertEqual(self.keys(TABLE_3, 4 - 1), RESIDUALS)

    def test_the_two_missing_build_flags_are_really_missing(self):
        # assert-applied, and the most perishable rows in the document: they
        # claim an ABSENCE in the CLI. Read the CLI's own help rather than the
        # prose, so closing either gap without updating the table fails here.
        help_text = subcommand_help("build")

        self.assertNotIn("--strict", help_text)
        self.assertNotIn("--json", help_text)

    def test_the_absence_check_discriminates(self):
        # The control for the test above: the same reading finds both flags where
        # they DO exist, so a broken help capture cannot pass it vacuously.
        self.assertIn("--strict", subcommand_help("run"))
        self.assertIn("--json", subcommand_help("run"))

    def test_the_field_flag_the_union_payload_row_points_at_exists(self):
        # Table 1's `동명 필드 독립 주입` row names mode B `--field` as the only
        # sanctioned forcing channel. That flag must be on `build`.
        self.assertIn("--field", subcommand_help("build"))

    # ---- negative controls, one per check ----

    def test_negative_control_a_deleted_signal_row_is_caught(self):
        mutant = self.markdown.replace(
            "| `진단 기계 판독` |", "| `진단 기계 판독 (삭제됨)` |")
        self.assertNotEqual(mutant, self.markdown, "the mutation did not apply")
        keys = [cells[0] for cells in parse_table(mutant, TABLE_1, 4)]
        self.assertNotEqual(keys, SIGNALS)

    def test_negative_control_a_deleted_residual_row_is_caught(self):
        mutant = self.markdown.replace("| `bare-binary` |", "| `closed` |")
        self.assertNotEqual(mutant, self.markdown, "the mutation did not apply")
        keys = [cells[0] for cells in parse_table(mutant, TABLE_3, 3)]
        self.assertNotEqual(keys, RESIDUALS)

    def test_negative_control_a_renamed_heading_raises_rather_than_passing(self):
        # "Target missing" must not read as "content fine": a reworded heading
        # has to fail loudly, or the whole class silently stops guarding.
        mutant = self.markdown.replace(TABLE_3, "### 표 3 — (이름이 바뀐 절)")
        self.assertNotEqual(mutant, self.markdown, "the mutation did not apply")
        with self.assertRaises(AssertionError):
            parse_table(mutant, TABLE_3, 3)


class TestDiagnosticCodesReachTheHandWrittenDocs(unittest.TestCase):
    """Every code in the closed set is enumerated where the docs enumerate them.

    `references/declarations.md` is generated and gated by
    `scripts/gen_plugin_references.py --check`. These two are hand-written, and
    that is exactly why they went stale: adding `validation-sample-derived` left
    both lists silently incomplete, the same way `ENFORCEMENT-MATRIX.md` §C went
    stale after RFC-0021 (issue #55, measured).
    """

    def test_cli_surface_enumerates_every_code(self):
        text = read(CLI_SURFACE)
        missing = [code for code in CODES if code not in text]

        self.assertEqual(missing, [])

    def test_the_skill_enumerates_every_code(self):
        text = read(SKILL)
        missing = [code for code in CODES if code not in text]

        self.assertEqual(missing, [])

    def test_negative_control_the_scan_notices_an_absent_code(self):
        # Proves the two checks above are reading, not just finding an empty
        # `missing` list because `CODES` was empty or the file unread.
        text = read(CLI_SURFACE).replace("validation-sample-derived", "x")

        self.assertEqual([c for c in CODES if c not in text],
                         ["validation-sample-derived"])


class TestReproductionsAreClosed(unittest.TestCase):
    """r1 N-2 / r1 N-3 / r2 N-1, re-run through the user-facing surfaces."""

    def setUp(self):
        os.makedirs(CLAUDE_TMP, exist_ok=True)
        self.box = tempfile.mkdtemp(prefix="lnpl-i55-repro-", dir=CLAUDE_TMP)
        self.addCleanup(shutil.rmtree, self.box, ignore_errors=True)

    def workdir(self, name):
        path = os.path.join(self.box, name)
        os.makedirs(path, exist_ok=True)
        return path

    def payload_file(self, payload):
        path = os.path.join(self.box, "payload.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return path

    @NEEDS_TOOLS
    def test_r1_n2_both_modes_name_the_same_skipped_steps(self):
        # The finding was that mode B said NOTHING while mode A said it three
        # ways. The fix is judged on the two surfaces agreeing, not on mode B
        # merely printing something.
        token = {"id": "11111111-1111-1111-1111-111111111111",
                 "cachedAt": "2026-08-07T00:00:00Z", "retryBudget": 0}
        payload = dict(token, token=dict(token))

        rc_a, out_a, _err_a = run_cli(
            ["run", GUARDED_LNPL, "--payload", self.payload_file(payload)])
        rc_b, out_b, err_b = run_cli(
            ["build", GUARDED_LNPL, "--run", "--workdir", self.workdir("b"),
             "--field", "token.retryBudget=0"])

        self.assertEqual(0, rc_a)
        self.assertEqual(0, rc_b)
        mode_a = set(SKIPPED_RE.findall(out_a))
        mode_b = set(SKIPPED_RE.findall(out_b))
        self.assertEqual({"call token"}, mode_a,
                         "precondition: mode A reports the skip on this input")
        self.assertEqual(mode_a, mode_b,
                         "the two modes must name the same skipped step")
        self.assertIn("guard-skipped-steps", err_b)

    @NEEDS_TOOLS
    def test_r1_n2_the_guard_true_run_names_nothing_in_either_mode(self):
        # Control: without it, a surface that always printed a skip would pass.
        token = {"id": "11111111-1111-1111-1111-111111111111",
                 "cachedAt": "2026-08-07T00:00:00Z", "retryBudget": 1}
        payload = dict(token, token=dict(token))

        _rc_a, out_a, _err_a = run_cli(
            ["run", GUARDED_LNPL, "--payload", self.payload_file(payload)])
        _rc_b, out_b, err_b = run_cli(
            ["build", GUARDED_LNPL, "--run", "--workdir", self.workdir("b2"),
             "--field", "token.retryBudget=1"])

        self.assertEqual(set(), set(SKIPPED_RE.findall(out_a)))
        self.assertEqual(set(), set(SKIPPED_RE.findall(out_b)))
        self.assertNotIn("guard-skipped-steps", err_b)

    def test_r1_n3_the_rejected_field_explains_the_channel(self):
        # The misreading path: rc 2 with a message that was true and silent about
        # why. No toolchain — the rejection precedes the build.
        rc, out, err = run_cli(
            ["build", SHORTEN_LNPL, "--run", "--workdir", self.workdir("n3"),
             "--field", "slug=1"])

        self.assertEqual(2, rc)
        self.assertEqual("", out, "the build never ran, so stdout stays empty")
        self.assertIn("do not match any comparison-guard field", err)
        self.assertIn("validation-sample-derived", err)

    def same_name_field_source(self):
        path = os.path.join(self.box, "samename.lnpl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(SAME_NAME_FIELD)
        return path

    @NEEDS_TOOLS
    def test_r2_n1_the_asymmetric_injection_and_its_refusal_are_observable(self):
        # `amountCents` is declared on both Payment and Refund. mode B `--field`
        # is the only channel that can make them differ (RFC-0022 표 2), and the
        # refusal it produces must be NAMED, not just an absent step line.
        base = ["build", self.same_name_field_source(),
                "--workflow", "wf.refund.request", "--run"]

        rc_over, out_over, err_over = run_cli(
            base + ["--workdir", self.workdir("over"),
                    "--field", "input.amountCents=9",
                    "--field", "payment.amountCents=5"])
        rc_part, out_part, err_part = run_cli(
            base + ["--workdir", self.workdir("part"),
                    "--field", "input.amountCents=3",
                    "--field", "payment.amountCents=5"])

        self.assertEqual(0, rc_over)
        self.assertEqual(0, rc_part)
        # Over-refund: refused, and the refusal names the step.
        self.assertEqual({"create refund"}, set(SKIPPED_RE.findall(out_over)))
        self.assertIn("guard-skipped-steps", err_over)
        # Partial: performed. This is the negative control — the over-refund
        # assertion above would also pass on a surface that always reported a
        # skip, and this is the run that catches that.
        self.assertEqual(set(), set(SKIPPED_RE.findall(out_part)))
        self.assertIn("step 2 create refund", out_part)

    @NEEDS_TOOLS
    def test_the_golden_login_run_reports_no_skips(self):
        # Boundary and RFC-0022 §Examples' golden case: a workflow with no guard
        # must be untouched by all of this.
        rc, out, err = run_cli(["build", LOGIN_LNPL, "--run",
                                "--workdir", self.workdir("login")])

        self.assertEqual(0, rc, err)
        self.assertEqual(set(), set(SKIPPED_RE.findall(out)))
        self.assertNotIn("guard-skipped-steps", err)
        # ...but the build fact still applies: Login has `validate input`.
        self.assertIn("validation-sample-derived", err)


if __name__ == "__main__":
    unittest.main()

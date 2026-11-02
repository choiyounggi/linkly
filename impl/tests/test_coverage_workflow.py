"""`.github/workflows/ci.yml`의 `coverage (advisory)` 잡 배선 단언 (issue #247).

모양 검사(`coverage_job_problems`)는 `test_dependency_lockfile.pip_audit_job_problems`와
같은 패턴이고, 요약 스텝은 텍스트가 아니라 그 `run:` 스크립트를 러너와 같은
`bash -e`로 실제로 돌려 `$GITHUB_STEP_SUMMARY`에 남은 내용을 본다.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CI_YML_PATH = os.path.join(REPO, ".github", "workflows", "ci.yml")
BRANCH_PROTECTION_SCRIPT_PATH = os.path.join(REPO, "scripts", "setup_branch_protection.sh")
DIFF_SCRIPT_PATH = os.path.join(REPO, "scripts", "diff_coverage.py")
CLAUDE_TMP = os.path.join(REPO, ".claude", "tmp")
SUMMARY_STEP = "      - name: Coverage summary (advisory, job summary only)\n"

REQUIRED = [
    ("    name: coverage (advisory)\n", "not named coverage (advisory)"),
    ("    permissions:\n      contents: read\n    steps:", "permissions is not exactly contents: read"),
    ("          fetch-depth: 0\n", "checkout is shallow"),
    ('python-version: "3.13"', "python is not 3.13"),
    ("      - name: Install from lockfile (requirements.txt)\n        run: |\n"
     "          pip install --require-hashes -r requirements.txt\n"
     "          pip install --require-hashes -r requirements-coverage.txt\n",
     "coverage is not installed from requirements-coverage.txt as the install step's second line"),
    ("run: PYTHONPATH=impl python3 -m coverage run --branch --source=impl/lnpl scripts/ci_test_suite.py\n",
     "coverage run is not --branch over scripts/ci_test_suite.py"),
    ("python3 -m coverage xml -o coverage.xml\n", "no coverage xml"),
    ("python3 -m coverage json -o coverage.json\n", "no coverage json"),
    ("BASE_SHA: ${{ github.event.pull_request.base.sha }}\n", "PR base not passed through env"),
    ('git diff --unified=0 --diff-filter=d --no-color "$BASE_SHA" "$GITHUB_SHA" -- impl/lnpl > pr.diff',
     "no PR diff step"),
    ('cat coverage-summary.md >> "$GITHUB_STEP_SUMMARY"', "summary not written to the job summary"),
    ("uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2",
     "no pinned artifact upload"),
]
FORBIDDEN = [
    ("continue-on-error", "continue-on-error set"),
    ("--fail-under", "fail-under set (coverage is advisory)"),
    ("pull-requests: write", "write permission requested"),
    ("gh pr comment", "PR comment step present (job summary only)"),
]
ALWAYS = "if: always()"


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def coverage_job(ci_text):
    start = ci_text.find("\n  coverage:\n")
    if start < 0:
        return None
    nxt = re.search(r"\n  [A-Za-z0-9_-]+:\n", ci_text[start + 1:])
    return ci_text[start:start + 1 + nxt.start()] if nxt else ci_text[start:]


def coverage_job_problems(ci_text):
    job = coverage_job(ci_text)
    if job is None:
        return ["no coverage job"]
    problems = [problem for snippet, problem in REQUIRED if snippet not in job]
    problems += [problem for snippet, problem in FORBIDDEN if snippet in job]
    if job.count(ALWAYS) != 4:
        problems.append("report steps: expected 4 `%s`, found %d" % (ALWAYS, job.count(ALWAYS)))
    return problems


def summary_step_script(ci_text):
    job = coverage_job(ci_text)
    start = job.index(SUMMARY_STEP)
    start = job.index("run: |\n", start) + len("run: |\n")
    end = job.index("\n\n      - ", start)
    return "\n".join(line[10:] for line in job[start:end].split("\n")) + "\n"


class CoverageJobShapeTest(unittest.TestCase):
    def test_real_ci_yml_has_no_problems(self):
        self.assertEqual(coverage_job_problems(_read(CI_YML_PATH)), [])

    def test_missing_job_is_reported(self):
        """경계값: coverage 잡 자체가 없다."""
        self.assertEqual(coverage_job_problems("jobs:\n  gate:\n    runs-on: x\n"), ["no coverage job"])

    def test_each_missing_required_snippet_is_named(self):
        """에러 케이스: 필수 조각을 하나씩 지우면 그 문제가 이름으로 나온다."""
        text = _read(CI_YML_PATH)
        for snippet, problem in REQUIRED:
            with self.subTest(problem=problem):
                job = coverage_job(text)
                mutated = text.replace(job, job.replace(snippet, "", 1))
                self.assertIn(problem, coverage_job_problems(mutated))

    def test_each_forbidden_snippet_is_named(self):
        text = _read(CI_YML_PATH)
        anchor = "          python3 -m coverage json -o coverage.json\n"
        for snippet, problem in FORBIDDEN:
            with self.subTest(problem=problem):
                job = coverage_job(text)
                mutated = text.replace(job, job.replace(anchor, anchor + "          echo '%s'\n" % snippet, 1))
                self.assertIn(problem, coverage_job_problems(mutated))

    def test_a_report_step_without_always_is_named(self):
        text = _read(CI_YML_PATH)
        job = coverage_job(text)
        mutated = text.replace(job, job.replace("        " + ALWAYS + "\n", "", 1))
        self.assertIn("report steps: expected 4 `%s`, found 3" % ALWAYS, coverage_job_problems(mutated))

    def test_coverage_is_not_a_required_check(self):
        checks = re.search(r"CHECKS='(.+)'", _read(BRANCH_PROTECTION_SCRIPT_PATH)).group(1)
        self.assertNotIn("coverage", checks)

    def test_gitignore_ignores_the_coverage_jobs_data_files(self):
        """issue #247 F2: `git check-ignore` actually ignores the paths the
        coverage job writes at the repo root — a real behavioural check, not
        just that the lines exist in .gitignore's text."""
        for path in (".coverage", ".coverage.123", "coverage.xml", "coverage.json", "htmlcov/"):
            with self.subTest(path=path):
                proc = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO)
                self.assertEqual(proc.returncode, 0)

    def test_gitignore_does_not_ignore_a_nested_coverage_json(self):
        """경계값: 루트가 아니면 안 지운다 — 과도한 패턴이 아님을 보장."""
        proc = subprocess.run(["git", "check-ignore", "-q", "impl/tests/coverage.json"], cwd=REPO)
        self.assertEqual(proc.returncode, 1)


class SummaryStepBehaviourTest(unittest.TestCase):
    """요약 스텝의 `run:` 스크립트를 `bash -e`로 실제로 돌린다."""

    def _run_step(self, with_diff):
        os.makedirs(CLAUDE_TMP, exist_ok=True)
        tmp = tempfile.mkdtemp(prefix="coverage-step-", dir=CLAUDE_TMP)
        self.addCleanup(shutil.rmtree, tmp, True)
        os.makedirs(os.path.join(tmp, "scripts"))
        shutil.copy(DIFF_SCRIPT_PATH, os.path.join(tmp, "scripts", "diff_coverage.py"))
        with open(os.path.join(tmp, "coverage.json"), "w", encoding="utf-8") as fh:
            json.dump({"totals": {"covered_lines": 3, "num_statements": 4,
                                  "covered_branches": 1, "num_branches": 2},
                       "files": {"impl/lnpl/fake_mod.py": {"executed_lines": [1, 2, 3],
                                                           "missing_lines": [4]}}}, fh)
        if with_diff:
            with open(os.path.join(tmp, "pr.diff"), "w", encoding="utf-8") as fh:
                fh.write("+++ b/impl/lnpl/fake_mod.py\n@@ -2,0 +3,2 @@\n")
        with open(os.path.join(tmp, "step.sh"), "w", encoding="utf-8") as fh:
            fh.write(summary_step_script(_read(CI_YML_PATH)))
        summary = os.path.join(tmp, "summary.md")
        open(summary, "w").close()
        proc = subprocess.run(
            ["bash", "-e", "step.sh"], cwd=tmp,
            env={"PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"],
                 "GITHUB_STEP_SUMMARY": summary},
            capture_output=True, text=True,
        )
        return proc, _read(summary)

    def test_pull_request_run_reports_totals_and_diff(self):
        proc, summary = self._run_step(with_diff=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("- Line coverage: 75.00% (3/4 statements)", summary)
        self.assertIn("Diff coverage: 50.00% (1/2 changed executable lines)", summary)
        self.assertEqual(proc.stdout, summary)

    def test_push_run_without_a_diff_reports_totals_only(self):
        """경계값: push 이벤트 — pr.diff가 없다."""
        proc, summary = self._run_step(with_diff=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("- Branch coverage: 50.00% (1/2 branches)", summary)
        self.assertNotIn("### Diff coverage", summary)


if __name__ == "__main__":
    unittest.main()

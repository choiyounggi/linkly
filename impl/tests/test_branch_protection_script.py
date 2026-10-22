"""`scripts/setup_branch_protection.sh`의 --check(읽기 전용) 모드 단언 (issues #166, #244).

`--check`는 원하는 페이로드와, 라이브 main 보호 설정을 GET 한 번으로 읽은 읽기 전용
drift 보고를 출력한다. 테스트는 격리된 PATH의 가짜 `gh`로 네트워크에 닿지 않고,
적용(PUT) 경로는 절대 실행하지 않는다.
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
SCRIPT_PATH = os.path.join(REPO, "scripts", "setup_branch_protection.sh")
CALLER = os.path.join(REPO, ".github", "workflows", "ai-gates-quality.yml")
REUSABLE = os.path.join(REPO, ".github", "workflows", "_ai-gate.yml")

EXPECTED_CONTEXTS = [
    "gate (py3.11)",
    "gate (py3.12)",
    "gate (py3.13)",
    "lint (ruff)",
    "modeb-linux (test_repo_state under real mode B)",
    "test-quality / gate",
]
PROMOTED_CONTEXT = "test-quality / gate"
GET_ARGV = ("api --method GET -H Accept: application/vnd.github+json "
            "-H X-GitHub-Api-Version: 2022-11-28 "
            "/repos/choiyounggi/linkly/branches/main/protection")


def _live(contexts, conversation=False, reviews=None, linear=False):
    body = {
        "required_status_checks": {"strict": True,
                                   "checks": [{"context": c, "app_id": 1} for c in contexts]},
        "enforce_admins": {"enabled": True},
        "required_conversation_resolution": {"enabled": conversation},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
        "required_linear_history": {"enabled": linear},
        "block_creations": {"enabled": False},
        "lock_branch": {"enabled": False},
        "allow_fork_syncing": {"enabled": False},
        "required_signatures": {"enabled": False},
    }
    if isinstance(reviews, dict):
        body["required_pull_request_reviews"] = reviews
    return body


def _run(args, body=None, gh_rc=0, with_gh=True, with_python=True):
    """격리된 bin 디렉터리를 PATH로 스크립트를 돌린다. (proc, gh argv 줄 목록)."""
    base = os.path.join(REPO, ".claude", "tmp")
    os.makedirs(base, exist_ok=True)
    bash = shutil.which("bash")
    with tempfile.TemporaryDirectory(prefix="lnpl-t244-", dir=base) as box:
        bindir = os.path.join(box, "bin")
        os.makedirs(bindir)
        os.symlink(bash, os.path.join(bindir, "bash"))
        os.symlink(shutil.which("cat"), os.path.join(bindir, "cat"))
        if with_python:
            os.symlink(sys.executable, os.path.join(bindir, "python3"))
        argv_log = os.path.join(box, "gh-argv.log")
        open(argv_log, "w").close()
        body_file = os.path.join(box, "gh-body")
        with open(body_file, "w") as fh:
            fh.write(json.dumps(body if body is not None else _live(EXPECTED_CONTEXTS[:5]))
                     if not isinstance(body, str) else body)
        if with_gh:
            gh = os.path.join(bindir, "gh")
            with open(gh, "w") as fh:
                fh.write("#!%s\nprintf '%%s\\n' \"$*\" >> \"$GH_ARGV_LOG\"\n"
                         "cat \"$GH_FAKE_BODY\"\nexit \"${GH_FAKE_RC:-0}\"\n" % bash)
            os.chmod(gh, 0o755)
        env = {"PATH": bindir, "GH_ARGV_LOG": argv_log, "GH_FAKE_BODY": body_file,
               "GH_FAKE_RC": str(gh_rc), "LANG": "C.UTF-8"}
        proc = subprocess.run([bash, SCRIPT_PATH] + args, cwd=REPO, env=env,
                              capture_output=True, text=True, timeout=30)
        with open(argv_log) as fh:
            argv = fh.read().splitlines()
        return proc, argv


def _payload(stdout):
    return json.loads(stdout.split("\n--- live vs desired")[0].split("\n", 1)[1])


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class ScriptSyntaxTest(unittest.TestCase):
    """정상 케이스: 스크립트가 존재하고 문법이 유효하며 실행 가능하다."""

    def test_bash_syntax_check(self):
        result = subprocess.run(
            ["bash", "-n", SCRIPT_PATH], capture_output=True, text=True, timeout=10
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_script_is_executable(self):
        self.assertTrue(os.access(SCRIPT_PATH, os.X_OK))


class CheckPayloadTest(unittest.TestCase):
    """정상 케이스: --check는 원하는 보호 페이로드와 라이브 대비 drift를 읽기 전용으로 보고한다."""

    def test_check_payload_is_the_desired_protection(self):
        proc, _ = _run(["--check"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = _payload(proc.stdout)
        self.assertEqual(payload["required_status_checks"],
                         {"strict": True, "checks": [{"context": c} for c in EXPECTED_CONTEXTS]})
        self.assertEqual({k: v for k, v in payload.items() if k != "required_status_checks"}, {
            "enforce_admins": True,
            "required_pull_request_reviews": None,
            "restrictions": None,
            "allow_force_pushes": False,
            "allow_deletions": False,
            "required_conversation_resolution": True,
            "required_linear_history": False,
            "block_creations": False,
            "lock_branch": False,
            "allow_fork_syncing": False,
        })
        self.assertEqual(list(payload), [
            "required_status_checks", "enforce_admins", "required_pull_request_reviews",
            "restrictions", "allow_force_pushes", "allow_deletions",
            "required_conversation_resolution", "required_linear_history", "block_creations",
            "lock_branch", "allow_fork_syncing"])

    def test_check_reports_drift_against_live_today(self):
        proc, _ = _run(["--check"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.splitlines()
        self.assertIn('drift: check "test-quality / gate" missing live', lines)
        self.assertIn("drift: required_conversation_resolution desired=true live=false", lines)
        for context in EXPECTED_CONTEXTS[:5]:
            self.assertIn('ok: check "%s"' % context, lines)
        self.assertEqual(lines[-1], "summary: 2 drift, 15 ok")

    def test_check_issues_exactly_one_get(self):
        proc, argv = _run(["--check"])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(argv, [GET_ARGV])
        for line in argv:
            for forbidden in ("PUT", "PATCH", "--input"):
                self.assertNotIn(forbidden, line)


class CheckDriftBoundaryTest(unittest.TestCase):
    """경계값 케이스: 라이브가 같을 때·비었을 때·여분이 있을 때의 drift 보고."""

    def test_check_in_sync_reports_no_drift(self):
        proc, _ = _run(["--check"], body=_live(EXPECTED_CONTEXTS, conversation=True))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.splitlines()[-1], "summary: 0 drift, 17 ok")
        self.assertNotIn("drift:", proc.stdout)

    def test_check_reports_live_only_context(self):
        proc, _ = _run(["--check"], body=_live(EXPECTED_CONTEXTS + ["legacy (ci)"], conversation=True))
        lines = proc.stdout.splitlines()
        self.assertIn('drift: check "legacy (ci)" live only (PUT would remove it)', lines)
        self.assertEqual(lines[-1], "summary: 1 drift, 17 ok")

    def test_check_empty_live_checks_reports_every_context(self):
        proc, _ = _run(["--check"], body=_live([], conversation=True))
        lines = proc.stdout.splitlines()
        for context in EXPECTED_CONTEXTS:
            self.assertIn('drift: check "%s" missing live' % context, lines)
        self.assertEqual(lines[-1], "summary: 6 drift, 11 ok")

    def test_check_live_reviews_present_is_drift(self):
        body = _live(EXPECTED_CONTEXTS, conversation=True,
                     reviews={"required_approving_review_count": 1})
        proc, _ = _run(["--check"], body=body)
        self.assertIn("drift: required_pull_request_reviews desired=null live=set",
                      proc.stdout.splitlines())

    def test_check_live_linear_history_is_drift(self):
        proc, _ = _run(["--check"], body=_live(EXPECTED_CONTEXTS, conversation=True, linear=True))
        self.assertIn("drift: required_linear_history desired=false live=true",
                      proc.stdout.splitlines())

    def test_include_modeb_is_a_noop(self):
        plain, _ = _run(["--check"])
        flagged, _ = _run(["--check", "--include-modeb"])
        self.assertEqual(flagged.returncode, 0, flagged.stderr)
        self.assertEqual(flagged.stdout, plain.stdout)
        contexts = [c["context"] for c in _payload(flagged.stdout)["required_status_checks"]["checks"]]
        self.assertEqual(contexts.count("modeb-linux (test_repo_state under real mode B)"), 1)

    def test_checks_literal_is_one_line(self):
        text = _read(SCRIPT_PATH)
        literals = re.findall(r"^CHECKS='(.+)'$", text, re.M)
        self.assertEqual(len(literals), 1)
        for context in EXPECTED_CONTEXTS:
            self.assertIn('{"context":"%s"}' % context, literals[0])

    def test_promoted_context_is_composed_from_the_workflow_sources(self):
        caller = _read(CALLER)
        reusable = _read(REUSABLE)
        self.assertEqual(caller.count("\n  test-quality:\n"), 1)
        job_id = re.search(r"^jobs:\n  ([a-z][a-z0-9_-]*):$", reusable, re.M).group(1)
        self.assertEqual(re.findall(r"^    name:.*$", reusable[reusable.index("\n  gate:\n"):], re.M), [])
        self.assertEqual("test-quality / " + job_id, PROMOTED_CONTEXT)
        checks_line = re.search(r"^CHECKS='(.+)'$", _read(SCRIPT_PATH), re.M).group(1)
        self.assertIn('{"context":"%s"}' % PROMOTED_CONTEXT, checks_line)


class CheckUnavailableTest(unittest.TestCase):
    """에러 케이스: 라이브를 읽지 못해도 --check는 페이로드를 출력하고 0으로 끝난다."""

    def test_gh_failure_reports_unavailable(self):
        proc, _ = _run(["--check"], gh_rc=1)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("live: unavailable (gh api exited 1)", proc.stderr)
        self.assertEqual(_payload(proc.stdout)["enforce_admins"], True)
        self.assertNotIn("drift:", proc.stdout)
        self.assertNotIn("summary:", proc.stdout)

    def test_missing_gh_reports_unavailable(self):
        proc, _ = _run(["--check"], with_gh=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("live: unavailable (gh not found)", proc.stderr)

    def test_missing_python_reports_unavailable(self):
        proc, argv = _run(["--check"], with_python=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("live: unavailable (python3 not found)", proc.stderr)
        self.assertEqual(argv, [])

    def test_unparseable_response_reports_unavailable(self):
        proc, _ = _run(["--check"], body="not json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("live: unavailable (unparseable response)", proc.stderr)
        self.assertNotIn("summary:", proc.stdout)


class UnknownFlagTest(unittest.TestCase):
    """에러 케이스: 알 수 없는 플래그는 종료 코드 2로 끝나고 gh를 부르지 않는다."""

    def test_unknown_flag_exits_two(self):
        proc, argv = _run(["--bogus"])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unknown flag: --bogus", proc.stderr)
        self.assertEqual(argv, [])


if __name__ == "__main__":
    unittest.main()

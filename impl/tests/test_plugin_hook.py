"""PostToolUse 진단 훅의 계약 테스트.

훅은 stdin으로 JSON을 받고, `.lnpl`일 때만 컴파일하고, 진단이 있으면
exit 2 + stderr로 모델에게 되돌린다. `lnpl`이 없으면 사용자 워크플로를
깨지 않는다(세션당 한 번만 안내).
"""
import json
import os
import shutil
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HOOK = os.path.join(REPO, "plugins", "lnpl", "hooks", "lnpl-diagnostics.sh")
TMP = os.path.join(REPO, ".claude", "tmp", "hooktest")

CLEAN = ("entity Note\n    field\n        id UUID\n\n"
         "workflow Save\n    validate input\n    create note\n")
NOISY = ("entity Note\n    field\n        id UUID\n\n"
         "workflow Save\n    validate input\n    return note\n")
BROKEN = ("entity Note\n    field\n        id UUID\n\n"
          "workflow Save\n    if something\n")


def write(name, text):
    os.makedirs(TMP, exist_ok=True)
    path = os.path.join(TMP, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def run_hook(file_path, session="s1", env=None):
    payload = json.dumps({"session_id": session, "cwd": REPO,
                          "hook_event_name": "PostToolUse", "tool_name": "Write",
                          "tool_input": {"file_path": file_path}})
    run_env = dict(os.environ)
    # 설치 없이도 `lnpl`이 잡히도록 venv의 bin을 앞에 둔다.
    run_env["PATH"] = os.path.join(REPO, ".venv", "bin") + os.pathsep + run_env["PATH"]
    run_env["PYTHONPATH"] = os.path.join(REPO, "impl")
    if env:
        run_env.update(env)
    return subprocess.run(["bash", HOOK], input=payload, capture_output=True,
                          text=True, env=run_env)


class DiagnosticsHookTest(unittest.TestCase):
    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)

    def test_hook_script_exists(self):
        self.assertTrue(os.path.isfile(HOOK))

    def test_ignores_non_lnpl_files(self):
        path = write("notes.md", "# hello")
        proc = run_hook(path)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr.strip(), "")

    def test_ignores_missing_file_path(self):
        proc = subprocess.run(["bash", HOOK], input=json.dumps({"tool_name": "Write"}),
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)

    def test_ignores_a_path_that_does_not_exist(self):
        proc = run_hook(os.path.join(TMP, "ghost.lnpl"))
        self.assertEqual(proc.returncode, 0)

    def test_silent_on_a_clean_source(self):
        proc = run_hook(write("clean.lnpl", CLEAN))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr.strip(), "")

    def test_reports_unknown_verb_back_to_the_model(self):
        proc = run_hook(write("noisy.lnpl", NOISY))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unknown-verb", proc.stderr)
        self.assertIn("return", proc.stderr)

    def test_reports_a_compile_error(self):
        proc = run_hook(write("broken.lnpl", BROKEN))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("reserved", proc.stderr)

    def test_golden_shorten_example_surfaces_its_three_warnings(self):
        # 계획서 수용 기준 4. 합성 파일이 아니라 레포가 커밋한 실제 소스로
        # 확인한다 — shorten.lnpl은 세 가지 증상을 의도적으로 보존한 교보재다.
        proc = run_hook(os.path.join(REPO, "examples", "shorten.lnpl"))
        self.assertEqual(proc.returncode, 2)
        for code in ("declared-not-enforced", "declared-measured-only",
                     "unknown-verb"):
            self.assertIn(code, proc.stderr)

    def test_missing_cli_notifies_once_then_stays_quiet(self):
        marker_home = os.path.join(TMP, "home")
        os.makedirs(marker_home, exist_ok=True)
        path = write("clean.lnpl", CLEAN)
        # PATH에서 lnpl을 제거하고, 마커가 쌓일 HOME도 격리한다.
        stripped = {"PATH": "/usr/bin:/bin", "HOME": marker_home}
        first = run_hook(path, session="missing-cli", env=stripped)
        self.assertEqual(first.returncode, 2)
        self.assertIn("lnpl-doctor", first.stderr)
        second = run_hook(path, session="missing-cli", env=stripped)
        self.assertEqual(second.returncode, 0,
                         "같은 세션에서 두 번째 안내가 나가면 소음이다")

    def test_missing_cli_notifies_again_in_a_different_session(self):
        marker_home = os.path.join(TMP, "home2")
        os.makedirs(marker_home, exist_ok=True)
        path = write("clean.lnpl", CLEAN)
        stripped = {"PATH": "/usr/bin:/bin", "HOME": marker_home}
        run_hook(path, session="sess-a", env=stripped)
        other = run_hook(path, session="sess-b", env=stripped)
        self.assertEqual(other.returncode, 2)

    def test_hooks_json_wires_write_and_edit(self):
        with open(os.path.join(REPO, "plugins", "lnpl", "hooks", "hooks.json"),
                  encoding="utf-8") as fh:
            cfg = json.load(fh)
        entries = cfg["hooks"]["PostToolUse"]
        self.assertEqual(entries[0]["matcher"], "Write|Edit")
        command = entries[0]["hooks"][0]["command"]
        self.assertIn("${CLAUDE_PLUGIN_ROOT}", command)
        self.assertIn("lnpl-diagnostics.sh", command)


if __name__ == "__main__":
    unittest.main()

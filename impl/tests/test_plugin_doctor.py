"""lnpl-doctor 스크립트의 계약 테스트.

플러그인은 레포에 묶여 커밋 단위로 정합하지만(A2), 사용자가 설치한 lnpl은
다른 버전일 수 있다. drift가 배포 경계에서 다시 나타나는 유일한 지점이라
여기서만 런타임 검사를 한다.
"""
import json
import os
import shutil
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCTOR = os.path.join(REPO, "plugins", "lnpl", "scripts", "doctor.sh")
SKILL_MD = os.path.join(REPO, "plugins", "lnpl", "skills", "lnpl-doctor", "SKILL.md")
TMP = os.path.join(REPO, ".claude", "tmp", "doctortest")
# issue #205: doctor reads the MCP launcher's state file. Tests never let it
# read the real ~/.claude/lnpl-plugin/mcp-last-start.json — a stale one there
# would turn every healthy-path test red.
TMP_STATE = os.path.join(REPO, ".claude", "tmp", "doctortest-state")
NO_STATE = os.path.join(TMP_STATE, "never-created.json")


def run_doctor(env=None, plugin_root=None):
    run_env = dict(os.environ)
    run_env["PATH"] = os.path.join(REPO, ".venv", "bin") + os.pathsep + run_env["PATH"]
    run_env["PYTHONPATH"] = os.path.join(REPO, "impl")
    run_env["CLAUDE_PLUGIN_ROOT"] = plugin_root or os.path.join(REPO, "plugins", "lnpl")
    run_env["LNPL_MCP_STATE"] = NO_STATE
    if env:
        run_env.update(env)
    return subprocess.run(["bash", DOCTOR], capture_output=True, text=True, env=run_env)


class DoctorTest(unittest.TestCase):
    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)
        shutil.rmtree(TMP_STATE, ignore_errors=True)

    def test_doctor_script_exists(self):
        self.assertTrue(os.path.isfile(DOCTOR))

    def test_reports_healthy_when_cli_is_present(self):
        proc = run_doctor()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("lnpl", proc.stdout)

    def test_reports_the_installed_version(self):
        import lnpl
        proc = run_doctor()
        self.assertIn(lnpl.__version__, proc.stdout)

    def test_fails_when_cli_is_absent(self):
        proc = run_doctor(env={"PATH": "/usr/bin:/bin"})
        self.assertEqual(proc.returncode, 1)
        self.assertIn("pip install", proc.stdout)

    def test_tolerates_a_missing_plugin_json(self):
        # plugin.json은 Task 07 산출물이다. 없어도 죽지 않아야 한다.
        os.makedirs(TMP, exist_ok=True)
        proc = run_doctor(plugin_root=TMP)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_flags_a_version_mismatch(self):
        os.makedirs(os.path.join(TMP, ".claude-plugin"), exist_ok=True)
        with open(os.path.join(TMP, ".claude-plugin", "plugin.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"name": "lnpl", "version": "9.9.9"}, fh)
        proc = run_doctor(plugin_root=TMP)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("9.9.9", proc.stdout)

    def test_passes_when_versions_agree(self):
        import lnpl
        os.makedirs(os.path.join(TMP, ".claude-plugin"), exist_ok=True)
        with open(os.path.join(TMP, ".claude-plugin", "plugin.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"name": "lnpl", "version": lnpl.__version__}, fh)
        proc = run_doctor(plugin_root=TMP)
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_skill_file_exists_and_names_itself(self):
        self.assertTrue(os.path.isfile(SKILL_MD))
        with open(SKILL_MD, encoding="utf-8") as fh:
            head = fh.read(400)
        self.assertIn("name: lnpl-doctor", head)


    # ---- CLI/MCP vocabulary digest (issue #205) ---------------------------

    def _state_file(self, document):
        os.makedirs(TMP_STATE, exist_ok=True)
        path = os.path.join(TMP_STATE, "state.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(document, fh)
        return path

    def test_flags_a_vocabulary_digest_mismatch(self):
        stale = "sha256:" + "0" * 64
        path = self._state_file({"vocabulary_digest": stale})
        proc = run_doctor(env={"LNPL_MCP_STATE": path})
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("어휘 불일치", proc.stdout)
        self.assertIn(stale, proc.stdout)
        self.assertIn("LNPL_IMPL_PATH", proc.stdout)

    def test_stays_quiet_when_the_mcp_digest_matches(self):
        from lnpl import provenance
        path = self._state_file(
            {"vocabulary_digest": provenance._current_vocabulary_digest()})
        proc = run_doctor(env={"LNPL_MCP_STATE": path})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("어휘 불일치", proc.stdout)
        self.assertIn("이상 없음.", proc.stdout)

    def test_quiet_when_no_state_file_exists(self):
        proc = run_doctor(env={"LNPL_MCP_STATE": NO_STATE})
        self.assertFalse(os.path.exists(NO_STATE))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("어휘 불일치", proc.stdout)

    def test_a_state_file_without_a_digest_is_not_a_mismatch(self):
        # boundary: an empty/foreign document has nothing to compare
        path = self._state_file({})
        proc = run_doctor(env={"LNPL_MCP_STATE": path})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("어휘 불일치", proc.stdout)

    def test_skill_md_documents_the_digest_check(self):
        with open(SKILL_MD, encoding="utf-8") as fh:
            self.assertIn("어휘 digest", fh.read())


if __name__ == "__main__":
    unittest.main()

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


def run_doctor(env=None, plugin_root=None):
    run_env = dict(os.environ)
    run_env["PATH"] = os.path.join(REPO, ".venv", "bin") + os.pathsep + run_env["PATH"]
    run_env["PYTHONPATH"] = os.path.join(REPO, "impl")
    run_env["CLAUDE_PLUGIN_ROOT"] = plugin_root or os.path.join(REPO, "plugins", "lnpl")
    if env:
        run_env.update(env)
    return subprocess.run(["bash", DOCTOR], capture_output=True, text=True, env=run_env)


class DoctorTest(unittest.TestCase):
    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)

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


if __name__ == "__main__":
    unittest.main()

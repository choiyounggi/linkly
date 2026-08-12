"""마켓플레이스·플러그인 매니페스트의 정합 검사.

레포가 제품이면서 동시에 마켓플레이스다. 매니페스트가 가리키는 경로가
실재하지 않으면 설치는 되고 아무것도 로드되지 않는다 — 조용한 실패라
테스트로 고정한다.
"""
import json
import os
import subprocess
import unittest

import lnpl

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MARKET = os.path.join(REPO, ".claude-plugin", "marketplace.json")
PLUGIN_DIR = os.path.join(REPO, "plugins", "lnpl")
PLUGIN_JSON = os.path.join(PLUGIN_DIR, ".claude-plugin", "plugin.json")


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class MarketplaceTest(unittest.TestCase):
    def test_marketplace_manifest_exists_and_parses(self):
        self.assertTrue(os.path.isfile(MARKET))
        self.assertIsInstance(load(MARKET), dict)

    def test_marketplace_declares_every_plugin(self):
        # 셋은 대상 사용자와 전달 방식이 서로 달라 합치지 않는다:
        #   `lnpl`     — .lnpl을 쓰는 쪽. 스킬 + 쓰기 시점 진단 훅.
        #   `lnpl-dev` — linkly 자체를 만드는 쪽. 환경·RFC·뮤테이션 하네스.
        #   `lnpl-mcp` — 같은 컴파일러를 셸이 아니라 MCP 툴로 부르는 쪽.
        #                진단을 stderr 줄글이 아니라 구조로 받는다.
        entries = load(MARKET)["plugins"]
        self.assertEqual(sorted(e["name"] for e in entries),
                         ["lnpl", "lnpl-dev", "lnpl-mcp"])

    def test_plugin_names_are_unique(self):
        names = [e["name"] for e in load(MARKET)["plugins"]]
        self.assertEqual(len(names), len(set(names)))

    def test_every_source_resolves_to_a_real_directory(self):
        for entry in load(MARKET)["plugins"]:
            resolved = os.path.normpath(os.path.join(REPO, entry["source"]))
            self.assertTrue(os.path.isdir(resolved),
                            "source가 실재하지 않는다: %s" % entry["source"])
            self.assertEqual(os.path.basename(resolved), entry["name"],
                             "source 디렉터리명이 플러그인 이름과 다르다")

    def test_every_source_carries_its_own_plugin_manifest(self):
        for entry in load(MARKET)["plugins"]:
            manifest = os.path.join(REPO, entry["source"],
                                    ".claude-plugin", "plugin.json")
            self.assertTrue(os.path.isfile(manifest),
                            "%s에 plugin.json이 없다" % entry["name"])
            self.assertEqual(load(manifest)["name"], entry["name"])
            self.assertEqual(load(manifest)["version"], entry["version"])
            self.assertEqual(load(manifest)["version"], lnpl.__version__)

    def test_marketplace_has_an_owner(self):
        self.assertIn("name", load(MARKET)["owner"])


class PluginManifestTest(unittest.TestCase):
    def test_plugin_manifest_exists_and_parses(self):
        self.assertTrue(os.path.isfile(PLUGIN_JSON))
        self.assertIsInstance(load(PLUGIN_JSON), dict)

    def test_plugin_name_matches_the_marketplace_entry(self):
        self.assertEqual(load(PLUGIN_JSON)["name"],
                         load(MARKET)["plugins"][0]["name"])

    def test_plugin_version_tracks_the_package_version(self):
        # A12: 버전 단일 출처는 lnpl.__version__이다.
        self.assertEqual(load(PLUGIN_JSON)["version"], lnpl.__version__)

    def test_marketplace_entry_version_matches_plugin_manifest(self):
        self.assertEqual(load(MARKET)["plugins"][0]["version"],
                         load(PLUGIN_JSON)["version"])

    def test_plugin_description_is_substantive(self):
        self.assertGreater(len(load(PLUGIN_JSON)["description"]), 60)


class PluginContentsTest(unittest.TestCase):
    REQUIRED = (
        os.path.join("skills", "lnpl-authoring", "SKILL.md"),
        os.path.join("skills", "lnpl-doctor", "SKILL.md"),
        os.path.join("hooks", "hooks.json"),
        os.path.join("hooks", "lnpl-diagnostics.sh"),
        os.path.join("scripts", "doctor.sh"),
        "README.md",
    )

    def test_every_declared_component_is_present(self):
        for rel in self.REQUIRED:
            self.assertTrue(os.path.isfile(os.path.join(PLUGIN_DIR, rel)),
                            "플러그인에 %s가 없다" % rel)

    def test_shell_entrypoints_are_executable(self):
        for rel in (os.path.join("hooks", "lnpl-diagnostics.sh"),
                    os.path.join("scripts", "doctor.sh")):
            self.assertTrue(os.access(os.path.join(PLUGIN_DIR, rel), os.X_OK),
                            "%s에 실행 권한이 없다" % rel)

    def test_doctor_now_compares_versions_and_agrees(self):
        # Task 06까지는 plugin.json이 없어 비교를 건너뛰었다. 이제 실제로 비교한다.
        env = dict(os.environ)
        env["PATH"] = os.path.join(REPO, ".venv", "bin") + os.pathsep + env["PATH"]
        env["PYTHONPATH"] = os.path.join(REPO, "impl")
        env["CLAUDE_PLUGIN_ROOT"] = PLUGIN_DIR
        proc = subprocess.run(["bash", os.path.join(PLUGIN_DIR, "scripts", "doctor.sh")],
                              capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn(lnpl.__version__, proc.stdout)
        self.assertNotIn("건너뜀", proc.stdout)


if __name__ == "__main__":
    unittest.main()

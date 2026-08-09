"""리뷰어 서브에이전트와 SessionStart 훅의 계약.

두 가지를 붙든다.

**리뷰어는 고칠 수 없어야 한다.** 이 에이전트가 있는 이유는 쓴 세션이 자기
어휘를 자기가 채점하지 못하게 하는 것이다. 도구 목록에 `Write`/`Edit`가 들어가는
순간 그 분리가 사라진다 — 리뷰어가 고치면 다시 자기 것을 자기가 평가하는 자리로
돌아간다. 문서에 "고치지 마라"라고 적는 것만으로는 부족하고, 능력 자체가 없어야
한다.

**SessionStart는 준비됐을 때 조용해야 한다.** 세션 시작 출력은 그 세션의 모든
턴이 지고 가는 컨텍스트다. 행동을 바꾸지 않는 사실을 거기에 실으면 소음이고,
소음은 읽히지 않는다. 그래서 "말한다"와 "조용하다"를 둘 다 테스트한다 — 한쪽만
보면 항상 조용한 훅과 구별되지 않는다.
"""
import json
import os
import shutil
import subprocess
import unittest

from lnpl import __version__

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLUGIN = os.path.join(REPO, "plugins", "lnpl")
AGENT = os.path.join(PLUGIN, "agents", "lnpl-reviewer.md")
HOOKS_JSON = os.path.join(PLUGIN, "hooks", "hooks.json")
SESSION_HOOK = os.path.join(PLUGIN, "hooks", "lnpl-session-start.sh")
DIAG_HOOK = os.path.join(PLUGIN, "hooks", "lnpl-diagnostics.sh")
RESOLVER = os.path.join(PLUGIN, "hooks", "lib", "resolve-lnpl.sh")
TMP = os.path.join(REPO, ".claude", "tmp", "agenttest")

WRITE_TOOLS = ("Write", "Edit", "NotebookEdit", "MultiEdit")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def frontmatter(path):
    text = read(path)
    if not text.startswith("---\n"):
        raise AssertionError("%s 에 YAML frontmatter가 없다" % path)
    body = text.split("---\n", 2)
    fields = {}
    for line in body[1].splitlines():
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields, body[2]


def run_session_hook(env):
    base = {"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp")}
    base.update(env)
    return subprocess.run(["bash", SESSION_HOOK], input="",
                          capture_output=True, text=True, env=base)


class ReviewerAgentTest(unittest.TestCase):

    def test_the_agent_file_exists(self):
        self.assertTrue(os.path.isfile(AGENT))

    def test_its_name_matches_the_filename(self):
        fields, _ = frontmatter(AGENT)
        self.assertEqual(fields.get("name"), "lnpl-reviewer")

    def test_the_description_says_when_to_reach_for_it(self):
        fields, _ = frontmatter(AGENT)
        description = fields.get("description", "")
        # 라우팅은 이 한 줄로 결정된다. 짧으면 안 불리고, 무엇에 쓰는지가
        # 없으면 엉뚱한 데서 불린다.
        self.assertGreater(len(description), 80, description)
        self.assertIn(".lnpl", description)

    def test_the_reviewer_cannot_write(self):
        fields, _ = frontmatter(AGENT)
        tools = [t.strip() for t in fields.get("tools", "").split(",")]
        self.assertTrue(tools and tools[0],
                        "tools가 비면 기본값으로 모든 도구가 열린다")
        for banned in WRITE_TOOLS:
            self.assertNotIn(
                banned, tools,
                "리뷰어에게 %s 를 주면 구현/평가 분리가 사라진다" % banned)

    def test_it_can_run_the_compiler(self):
        # 판정을 컴파일러 출력으로 하라고 요구하면서 실행 수단이 없으면
        # 그 요구는 지킬 수 없는 것이 된다.
        fields, _ = frontmatter(AGENT)
        tools = [t.strip() for t in fields.get("tools", "").split(",")]
        self.assertIn("Bash", tools)
        self.assertIn("Read", tools)


class SharedResolverTest(unittest.TestCase):
    """훅 둘이 같은 해석기를 쓴다 — 두 벌이면 갈라진다."""

    def test_the_resolver_library_exists(self):
        self.assertTrue(os.path.isfile(RESOLVER))

    def test_both_hooks_source_it_rather_than_reimplementing(self):
        for hook in (SESSION_HOOK, DIAG_HOOK):
            with self.subTest(hook=os.path.basename(hook)):
                text = read(hook)
                self.assertIn("lib/resolve-lnpl.sh", text)
                self.assertNotIn(
                    "find_up_exec() {", text,
                    "%s 가 해석기를 다시 구현한다" % os.path.basename(hook))


class HooksJsonTest(unittest.TestCase):

    def test_session_start_is_wired_to_the_shipped_script(self):
        cfg = json.loads(read(HOOKS_JSON))
        entries = cfg["hooks"]["SessionStart"]
        command = entries[0]["hooks"][0]["command"]
        self.assertIn("${CLAUDE_PLUGIN_ROOT}", command)
        self.assertIn("lnpl-session-start.sh", command)
        self.assertTrue(os.path.isfile(SESSION_HOOK))

    def test_the_post_tool_use_hook_is_still_wired(self):
        # 새 훅을 붙이면서 기존 훅을 떨어뜨리는 것이 이 파일의 실패 모드다.
        cfg = json.loads(read(HOOKS_JSON))
        command = cfg["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
        self.assertIn("lnpl-diagnostics.sh", command)
        self.assertEqual(cfg["hooks"]["PostToolUse"][0]["matcher"], "Write|Edit")


class SessionStartBehaviourTest(unittest.TestCase):

    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)

    def _shim(self, name, version_line):
        os.makedirs(os.path.join(TMP, name, "bin"), exist_ok=True)
        path = os.path.join(TMP, name, "bin", "lnpl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\necho \"%s\"\n" % version_line)
        os.chmod(path, 0o755)
        return path

    def test_it_stays_silent_when_the_compiler_resolves_and_matches(self):
        proc = run_session_hook({"CLAUDE_PROJECT_DIR": REPO})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            proc.stdout.strip(), "",
            "준비된 세션에서 말하면 그 출력은 모든 턴이 지고 가는 소음이다")

    def test_it_speaks_when_the_compiler_cannot_be_found(self):
        proc = run_session_hook({"LNPL_BIN": "/nonexistent/lnpl"})
        self.assertEqual(proc.returncode, 0, "세션 시작을 막으면 안 된다")
        payload = json.loads(proc.stdout)
        out = payload["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "SessionStart")
        self.assertIn("lnpl-doctor", out["additionalContext"])

    def test_it_speaks_when_the_compiler_version_disagrees(self):
        shim = self._shim("mismatch", "lnpl 9.9.9")
        proc = run_session_hook({"LNPL_BIN": shim})
        self.assertEqual(proc.returncode, 0)
        context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("9.9.9", context)
        self.assertIn(__version__, context)

    def test_it_speaks_when_version_cannot_be_read(self):
        os.makedirs(os.path.join(TMP, "mute", "bin"), exist_ok=True)
        path = os.path.join(TMP, "mute", "bin", "lnpl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\nexit 3\n")
        os.chmod(path, 0o755)
        proc = run_session_hook({"LNPL_BIN": path})
        self.assertEqual(proc.returncode, 0)
        context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("--version", context)

    def test_a_matching_shim_is_silent(self):
        # 음성 통제: 버전이 맞으면 위 두 경로가 아니라 침묵이어야 한다.
        shim = self._shim("match", "lnpl %s" % __version__)
        proc = run_session_hook({"LNPL_BIN": shim})
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()

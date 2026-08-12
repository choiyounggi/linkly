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


def run_hook(file_path, session="s1", env=None, inject_venv=True):
    """훅을 한 번 돌린다.

    `inject_venv=True`가 기본인 이유는 기존 케이스들의 계약을 그대로 두기
    위해서다. 하지만 그 주입이 바로 이 파일이 오래 놓치고 있던 것이다:
    실제 Claude Code 세션은 훅에게 레포의 `.venv/bin`이 얹힌 PATH를 주지
    않는다. `inject_venv=False`가 production이 실제로 주는 환경이다.
    """
    payload = json.dumps({"session_id": session, "cwd": REPO,
                          "hook_event_name": "PostToolUse", "tool_name": "Write",
                          "tool_input": {"file_path": file_path}})
    run_env = dict(os.environ)
    if inject_venv:
        # 설치 없이도 `lnpl`이 잡히도록 venv의 bin을 앞에 둔다.
        run_env["PATH"] = (os.path.join(REPO, ".venv", "bin")
                           + os.pathsep + run_env["PATH"])
        run_env["PYTHONPATH"] = os.path.join(REPO, "impl")
    else:
        run_env["PATH"] = "/usr/bin:/bin"
        run_env.pop("PYTHONPATH", None)
        run_env.pop("LNPL_BIN", None)
        run_env.pop("CLAUDE_PROJECT_DIR", None)
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

class ProductionEnvironmentTest(unittest.TestCase):
    """훅이 실제로 받는 환경 — 레포 venv가 PATH에 없는 상태.

    Claude Code는 훅을 자기 프로세스 환경에서 실행한다. 사용자가 `activate`한
    venv도, 테스트가 합성하던 PATH도 거기에는 없다. 그래서 이 클래스만이
    "플러그인이 설치돼 있고 훅이 등록돼 있는데 보호는 0"인 상태를 잡을 수 있다.
    """

    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)

    def _isolated_home(self, name):
        """마커가 쌓일 HOME. 격리하지 않으면 실패 경로를 탈 때 실제
        `~/.claude/lnpl-plugin/`에 파일을 흘린다 — 테스트가 초록일 때는
        보이지 않다가 뮤테이션 실행에서 드러난다."""
        path = os.path.join(TMP, name)
        os.makedirs(path, exist_ok=True)
        return {"HOME": path}

    def test_resolves_the_repo_local_cli_without_it_being_on_path(self):
        proc = run_hook(write("noisy.lnpl", NOISY), session="prod-1",
                        inject_venv=False, env=self._isolated_home("h1"))
        self.assertEqual(
            proc.returncode, 2,
            "PATH에 lnpl이 없다는 이유로 진단을 포기하면, 훅이 붙어 있는 어떤 "
            "실제 세션에서도 이 플러그인은 아무것도 하지 않는다.\n"
            "stderr: %s" % proc.stderr)
        self.assertIn("unknown-verb", proc.stderr)

    def test_stays_silent_on_a_clean_source_without_path(self):
        proc = run_hook(write("clean.lnpl", CLEAN), session="prod-2",
                        inject_venv=False, env=self._isolated_home("h2"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr.strip(), "")

    def test_the_session_marker_does_not_disable_resolution(self):
        """마커는 안내 반복만 억제한다 — 해석 자체를 끄지 않는다."""
        marker_home = os.path.join(TMP, "home-marker")
        os.makedirs(marker_home, exist_ok=True)
        noisy = write("noisy.lnpl", NOISY)
        # (i) CLI를 못 찾는 실행으로 이 세션의 마커를 만든다.
        first = run_hook(noisy, session="marker-x", inject_venv=False,
                         env={"HOME": marker_home,
                              "LNPL_BIN": "/nonexistent/lnpl"})
        self.assertEqual(first.returncode, 2)
        self.assertIn("lnpl-doctor", first.stderr)
        # (ii) 같은 세션에서 CLI가 찾아지는 실행. 마커가 있다고 조용해지면,
        #      한 번 못 찾은 세션은 남은 내내 무방비가 된다.
        second = run_hook(noisy, session="marker-x", inject_venv=False,
                          env={"HOME": marker_home})
        self.assertEqual(
            second.returncode, 2,
            "마커가 진단 자체를 삼켰다 — 같은 세션의 이후 모든 .lnpl 쓰기가 "
            "무음이 된다.\nstderr: %s" % second.stderr)
        self.assertIn("unknown-verb", second.stderr)

    def test_lnpl_bin_override_does_not_fall_back(self):
        """명시적 오버라이드가 조용히 다른 걸 쓰면 오버라이드가 아니다."""
        marker_home = os.path.join(TMP, "home-override")
        os.makedirs(marker_home, exist_ok=True)
        proc = run_hook(write("noisy.lnpl", NOISY), session="override-1",
                        inject_venv=False,
                        env={"HOME": marker_home,
                             "LNPL_BIN": "/nonexistent/lnpl"})
        self.assertEqual(proc.returncode, 2)
        self.assertIn("lnpl-doctor", proc.stderr)
        self.assertNotIn(
            "unknown-verb", proc.stderr,
            "LNPL_BIN이 지정됐는데 폴백으로 다른 lnpl을 찾아 썼다.")


SHIM = "#!/bin/sh\necho \"%s\" >&2\nexit 0\n"


def make_shim(path, sentinel):
    """실행되면 자기 이름표를 stderr로 내는 가짜 lnpl.

    훅은 stderr가 비어 있지 않으면 exit 2로 되돌린다. 그래서 어느 후보가
    실제로 **실행됐는지**를 출력으로 구별할 수 있다 — 어느 경로가 존재하는지가
    아니라.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(SHIM % sentinel)
    os.chmod(path, 0o755)
    return path


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


class ResolutionOrderTest(unittest.TestCase):
    """해석 순서는 설계 결정이므로 테스트가 그 순서를 붙들어야 한다.

    "찾기는 한다"는 것과 "옳은 것을 찾는다"는 것은 다르다. 워크트리는 각자
    자기 `.venv`를 갖기 때문에, 편집된 파일 기준 walk-up이
    `$CLAUDE_PROJECT_DIR`보다 **앞서야** 한다 — 아니면 워크트리 안의 `.lnpl`을
    다른 체크아웃의 컴파일러로 검사하게 된다.
    """

    def setUp(self):
        self.sandbox = os.path.join(TMP, "resolve")
        self.home = os.path.join(self.sandbox, "home")
        os.makedirs(self.home, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)

    def _run(self, source_path, extra_env):
        env = {"HOME": self.home}
        env.update(extra_env)
        return run_hook(source_path, session="resolve", inject_venv=False,
                        env=env)

    def test_the_file_local_venv_wins_over_claude_project_dir(self):
        near = os.path.join(self.sandbox, "near")
        far = os.path.join(self.sandbox, "far")
        make_shim(os.path.join(near, ".venv", "bin", "lnpl"), "SENTINEL-WALKUP")
        make_shim(os.path.join(far, ".venv", "bin", "lnpl"), "SENTINEL-PROJECTDIR")
        src = put(os.path.join(near, "src", "x.lnpl"), CLEAN)

        proc = self._run(src, {"CLAUDE_PROJECT_DIR": far})

        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("SENTINEL-WALKUP", proc.stderr)
        self.assertNotIn(
            "SENTINEL-PROJECTDIR", proc.stderr,
            "CLAUDE_PROJECT_DIR가 편집된 파일의 워크트리를 이겼다 — 워크트리의 "
            ".lnpl을 다른 체크아웃의 컴파일러로 검사하게 된다.")

    def test_the_nearest_venv_wins_when_two_are_stacked(self):
        outer = os.path.join(self.sandbox, "outer")
        inner = os.path.join(outer, "inner")
        make_shim(os.path.join(outer, ".venv", "bin", "lnpl"), "SENTINEL-OUTER")
        make_shim(os.path.join(inner, ".venv", "bin", "lnpl"), "SENTINEL-INNER")
        src = put(os.path.join(inner, "src", "x.lnpl"), CLEAN)

        proc = self._run(src, {})

        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("SENTINEL-INNER", proc.stderr)
        self.assertNotIn("SENTINEL-OUTER", proc.stderr)

    def test_claude_project_dir_is_used_when_no_venv_is_above_the_file(self):
        far = os.path.join(self.sandbox, "far")
        make_shim(os.path.join(far, ".venv", "bin", "lnpl"), "SENTINEL-PROJECTDIR")
        # 파일은 레포 밖에 둔다 — 레포 안이면 walk-up이 레포의 .venv를 먼저 만난다.
        outside = outside_repo_dir("projectdir")
        try:
            src = put(os.path.join(outside, "src", "x.lnpl"), CLEAN)
            if venv_above(src):
                self.skipTest("이 머신의 홈 위쪽에 .venv/bin/lnpl이 있어 격리 불가")
            proc = self._run(src, {"CLAUDE_PROJECT_DIR": far})
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertIn("SENTINEL-PROJECTDIR", proc.stderr)
        finally:
            shutil.rmtree(outside, ignore_errors=True)


def outside_repo_root():
    """이 모듈이 레포 밖에 만드는 모든 것의 단일 뿌리 — 정리 소유자도 하나다."""
    return os.path.join(os.path.expanduser("~"), ".claude",
                        "lnpl-hooktest-%d" % os.getpid())


def tearDownModule():
    # 클래스마다 각자 지우면 실행 순서에 따라 뿌리가 남는다. 뿌리를 지우는
    # 책임은 여기 하나뿐이다.
    shutil.rmtree(outside_repo_root(), ignore_errors=True)
    shutil.rmtree(TMP, ignore_errors=True)


def outside_repo_dir(name):
    """레포 트리 **밖**의 작업 디렉터리.

    walk-up 검사는 레포 안에서는 격리할 수 없다 — 어느 하위 디렉터리에서
    출발하든 결국 레포 루트의 `.venv/bin/lnpl`을 만난다. `/tmp`는 이 레포의
    규약이 금지하므로 사용자 설정 디렉터리 아래에 만들고 즉시 지운다.
    """
    root = os.path.join(outside_repo_root(), name)
    os.makedirs(root, exist_ok=True)
    return root


def venv_above(path):
    """`path`의 어느 상위에든 실행 가능한 `.venv/bin/lnpl`이 있는가."""
    cur = os.path.dirname(os.path.abspath(path))
    while True:
        if os.access(os.path.join(cur, ".venv", "bin", "lnpl"), os.X_OK):
            return True
        parent = os.path.dirname(cur)
        if parent == cur:
            return False
        cur = parent


class ModuleFallbackTest(unittest.TestCase):
    """콘솔 스크립트가 없어도 소스가 있으면 모듈로 돈다 (해석 5단계).

    이 단계는 레포 안에서는 **절대 도달하지 않는다** — walk-up이 항상 먼저
    성공하기 때문이다. 그래서 레포 밖에 최소 패키지를 세워서 이 단계만
    단독으로 실행시킨다. 이걸 하지 않으면 5단계는 스위트 관점에서 죽은 코드다.
    """

    def setUp(self):
        self.root = outside_repo_dir("module")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(TMP, ignore_errors=True)

    def test_python_m_lnpl_runs_when_no_console_script_exists(self):
        pkg = os.path.join(self.root, "impl", "lnpl")
        put(os.path.join(pkg, "__init__.py"), "")
        put(os.path.join(pkg, "__main__.py"),
            "import sys\n"
            "sys.stderr.write('SENTINEL-MODULE ' + ' '.join(sys.argv[1:]) + '\\n')\n")
        src = put(os.path.join(self.root, "src", "x.lnpl"), CLEAN)
        if venv_above(src):
            self.skipTest("이 머신의 홈 위쪽에 .venv/bin/lnpl이 있어 격리 불가")

        home = os.path.join(self.root, "home")
        os.makedirs(home, exist_ok=True)
        proc = run_hook(src, session="module", inject_venv=False,
                        env={"HOME": home})

        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("SENTINEL-MODULE", proc.stderr)
        # PYTHONPATH와 인자 구성이 맞아야 `compile <파일>`이 그대로 도착한다.
        self.assertIn("compile", proc.stderr)
        self.assertIn(src, proc.stderr)


class MissingCliTest(unittest.TestCase):
    """CLI를 어디서도 못 찾을 때의 계약.

    예전에는 `PATH=/usr/bin:/bin`으로 이 상태를 만들었다. 폴백 체인이 생긴
    뒤로 그 전제는 거짓이다 — 파일 경로에서 위로 올라가면 워크트리의 venv가
    잡힌다. `LNPL_BIN`을 존재하지 않는 절대경로로 두는 것이 이제 이 경로에
    도달하는 결정적인 방법이다.
    """

    def tearDown(self):
        shutil.rmtree(TMP, ignore_errors=True)

    def test_missing_cli_notifies_once_then_stays_quiet(self):
        marker_home = os.path.join(TMP, "home")
        os.makedirs(marker_home, exist_ok=True)
        path = write("clean.lnpl", CLEAN)
        # 어디서도 찾지 못하게 한다: 오버라이드를 존재하지 않는 절대경로로 두고,
        # 마커가 쌓일 HOME도 격리한다.
        stripped = {"LNPL_BIN": "/nonexistent/lnpl", "HOME": marker_home}
        first = run_hook(path, session="missing-cli", inject_venv=False,
                         env=stripped)
        self.assertEqual(first.returncode, 2)
        self.assertIn("lnpl-doctor", first.stderr)
        second = run_hook(path, session="missing-cli", inject_venv=False,
                          env=stripped)
        self.assertEqual(second.returncode, 0,
                         "같은 세션에서 두 번째 안내가 나가면 소음이다")

    def test_missing_cli_notifies_again_in_a_different_session(self):
        marker_home = os.path.join(TMP, "home2")
        os.makedirs(marker_home, exist_ok=True)
        path = write("clean.lnpl", CLEAN)
        stripped = {"LNPL_BIN": "/nonexistent/lnpl", "HOME": marker_home}
        run_hook(path, session="sess-a", inject_venv=False, env=stripped)
        other = run_hook(path, session="sess-b", inject_venv=False, env=stripped)
        self.assertEqual(other.returncode, 2)


class HookWiringTest(unittest.TestCase):

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

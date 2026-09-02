"""`scripts/dev_doctor.sh`의 Linux 분기(steps 5-6, issue #161) 행동 검증.

steps 5("sysroot 정합")·6("SDK 경로")는 macOS 전용 문제(brew clang의
SDKROOT 무시)를 진단한다. Linux에는 그 문제 자체가 없으므로 `uname` 값에
따라 갈라져야 한다. 어느 호스트에서 실행되든 결과가 재현되도록, `uname`과
검사 대상 도구(mlir-opt/mlir-translate/clang)를 **실제 스텁 실행 파일**로
만들어 완전히 통제한 PATH 위에서 스크립트를 그대로 실행한다 — 셸 함수로
`command` 빌트인을 흉내 내는 방식은 시도했으나, `command -v a b c`가 인자
중 하나라도 찾으면 성공하는 실제 bash의 OR 의미론을 정확히 재현하지 못해
버그를 놓치는 것으로 확인되었다(아래 `LinuxBranchPartialToolchainTest`
참고). 진짜 실행 파일 존재 여부로 테스트하면 그런 오차가 없다.
"""
import os
import stat
import tempfile
import unittest
from subprocess import run

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCTOR = os.path.join(REPO, "scripts", "dev_doctor.sh")
CLAUDE_TMP = os.path.join(REPO, ".claude", "tmp")


def _make_stub_bin(test, scripts):
    """`{이름: 셸 본문}`으로 실행 가능한 스텁들을 담은 임시 디렉터리를 만든다."""
    d = tempfile.mkdtemp(prefix="dev-doctor-stub-", dir=CLAUDE_TMP)
    test.addCleanup(_rmtree, d)
    for name, body in scripts.items():
        path = os.path.join(d, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\n%s\n" % body)
        mode = os.stat(path).st_mode
        os.chmod(path, mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return d


def _rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


def _run_doctor(test, os_name, tools=(), llvm_bin=None):
    """`uname`이 `os_name`을 answer하고, `tools`에 준 이름만 PATH에서 실행
    파일로 존재하는(그 밖에는 아무것도 없는) 상태로 `dev_doctor.sh`를 그대로
    실행한다. `command -v`가 진짜 실행 파일 탐색을 하므로, 오버라이드로 셸
    빌트인을 흉내 낼 때보다 정확하다.
    """
    stub_scripts = {"uname": "echo %s" % os_name}
    for t in tools:
        stub_scripts[t] = "exit 0"
    stub_dir = _make_stub_bin(test, stub_scripts)

    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([stub_dir, "/usr/bin", "/bin", "/usr/sbin", "/sbin"])
    if llvm_bin is None:
        env.pop("LNPL_LLVM_BIN", None)
    else:
        env["LNPL_LLVM_BIN"] = llvm_bin

    return run(["bash", DOCTOR], cwd=REPO, env=env,
               capture_output=True, text=True, check=False)


class LinuxBranchToolchainOnPathTest(unittest.TestCase):
    """정상 케이스: PATH 위에서 세 도구 모두 발견됨."""

    def test_reports_not_applicable_when_toolchain_resolves_on_path(self):
        proc = _run_doctor(self, "Linux", tools=("mlir-opt", "mlir-translate", "clang"))

        self.assertIn("sysroot 정합: n/a (Linux)", proc.stdout)
        self.assertIn("SDK 경로    : n/a (Linux)", proc.stdout)
        self.assertNotIn("툴체인을 못 찾음", proc.stdout)


class LinuxBranchMissingToolchainTest(unittest.TestCase):
    """에러 케이스: 툴체인이 PATH에도 LNPL_LLVM_BIN에도 없음."""

    def test_reports_a_problem_when_neither_path_nor_env_var_resolves(self):
        proc = _run_doctor(self, "Linux", tools=(), llvm_bin=None)

        self.assertIn("sysroot 정합: 툴체인을 못 찾음", proc.stdout)
        self.assertIn("SDK 경로    : 툴체인을 못 찾음", proc.stdout)
        self.assertIn("LNPL_LLVM_BIN", proc.stdout)
        self.assertNotEqual(proc.returncode, 0)


class LinuxBranchPartialToolchainTest(unittest.TestCase):
    """경계값: 흔한 부분 설치 — bare Linux에 clang은 있지만
    mlir-opt/mlir-translate는 없는 상태(LNPL_LLVM_BIN도 미설정).

    `command -v mlir-opt mlir-translate clang`처럼 세 이름을 한 호출에 OR로
    묶으면 clang 하나만으로 "찾음"이 되어 이 상태를 놓친다(#161 구현 중
    실제로 발견된 회귀) — steps 5/6은 반드시 step 4가 개별로 계산한
    `$MISSING_TOOLS`를 통해서만 판단해야 한다.
    """

    def test_clang_alone_on_path_is_still_reported_as_missing(self):
        proc = _run_doctor(self, "Linux", tools=("clang",), llvm_bin=None)

        self.assertIn("sysroot 정합: 툴체인을 못 찾음", proc.stdout)
        self.assertIn("SDK 경로    : 툴체인을 못 찾음", proc.stdout)
        self.assertNotIn("sysroot 정합: n/a (Linux)", proc.stdout)
        self.assertNotIn("SDK 경로    : n/a (Linux)", proc.stdout)


class LinuxBranchEnvVarOverrideTest(unittest.TestCase):
    """경계값: PATH에는 없지만 LNPL_LLVM_BIN이 (내용과 무관하게) 설정됨."""

    def test_llvm_bin_alone_satisfies_the_check(self):
        proc = _run_doctor(self, "Linux", tools=(), llvm_bin="/usr/lib/llvm-22/bin")

        self.assertIn("sysroot 정합: n/a (Linux)", proc.stdout)
        self.assertIn("SDK 경로    : n/a (Linux)", proc.stdout)
        self.assertNotIn("툴체인을 못 찾음", proc.stdout)

    def test_empty_llvm_bin_does_not_satisfy_the_check(self):
        # 빈 문자열은 `[ -n "${LNPL_LLVM_BIN:-}" ]`에서 참이 아니어야 한다.
        proc = _run_doctor(self, "Linux", tools=(), llvm_bin="")

        self.assertIn("sysroot 정합: 툴체인을 못 찾음", proc.stdout)
        self.assertIn("SDK 경로    : 툴체인을 못 찾음", proc.stdout)


class DarwinBranchUnchangedTest(unittest.TestCase):
    """회귀 가드: Darwin 분기는 이 변경으로 건드리지 않았다."""

    def test_darwin_never_prints_the_linux_wording(self):
        proc = _run_doctor(self, "Darwin", tools=())

        self.assertNotIn("n/a (Linux)", proc.stdout)
        self.assertNotIn("툴체인을 못 찾음", proc.stdout)


if __name__ == "__main__":
    unittest.main()

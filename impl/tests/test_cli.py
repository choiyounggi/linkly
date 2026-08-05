"""CLI arg-wiring smoke tests (issue #27).

The `lnpl diff` crash fixed in PR #22 (`verify() got an unexpected keyword
argument 'skip'`) shipped through a 402-test suite because every test called the
underlying functions directly — nothing drove a subcommand through argparse into
its `cmd_*` handler. These tests close that gap: each subcommand is exercised via
`cli.main([...])`, the same parse→dispatch path a user hits, so a signature drift
between the parser and a handler fails here instead of in the user's terminal.

Each command is asserted to return 0 on a valid invocation — proving the whole
wiring works, not merely that no exception is raised.
"""

import contextlib
import io
import os
import shutil
import unittest

import lnpl
from lnpl import backend, cli

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOGIN = os.path.join(REPO, "examples", "login.lnpl")
HAS_TOOLS = backend.toolchain_available()


def run_cli(argv):
    """Drive `cli.main(argv)` with stdout/stderr muted; return its exit code."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        return cli.main(argv)


class TestSubcommandWiring(unittest.TestCase):
    def setUp(self):
        self.workdir = os.path.join(REPO, ".claude", "tmp", "cli-smoke")

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def test_compile(self):
        self.assertEqual(run_cli(["compile", LOGIN]), 0)

    def test_run(self):
        self.assertEqual(run_cli(["run", LOGIN]), 0)

    def test_spec_run(self):
        self.assertEqual(run_cli(["spec", LOGIN, "--run"]), 0)

    def test_openapi(self):
        self.assertEqual(run_cli(["openapi", LOGIN]), 0)

    def test_kb_lint(self):
        self.assertEqual(run_cli(["kb", "--lint"]), 0)

    def test_agents(self):
        self.assertEqual(run_cli(["agents", LOGIN]), 0)

    @unittest.skipUnless(HAS_TOOLS, "MLIR/LLVM toolchain not installed")
    def test_build(self):
        self.assertEqual(run_cli(["build", LOGIN, "--workdir", self.workdir]), 0)

    @unittest.skipUnless(HAS_TOOLS, "MLIR/LLVM toolchain not installed")
    def test_diff(self):
        self.assertEqual(run_cli(["diff", LOGIN, "--workdir", self.workdir]), 0)


class TestVersionFlag(unittest.TestCase):
    """`--version`은 서브커맨드 없이도 통해야 한다 (`required=True`인데도).

    lnpl-doctor가 설치된 CLI와 플러그인의 버전을 맞춰보는 유일한 통로다.
    """

    def _version_output(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            with self.assertRaises(SystemExit) as caught:
                cli.main(["--version"])
        return caught.exception.code, buf.getvalue().strip()

    def test_exits_zero(self):
        code, _ = self._version_output()
        self.assertEqual(code, 0)

    def test_prints_package_version(self):
        _, text = self._version_output()
        self.assertEqual(text, "lnpl %s" % lnpl.__version__)

    def test_second_field_is_parseable_as_the_version(self):
        # doctor가 `cut -d' ' -f2`로 읽는다. 형식을 테스트로 고정한다.
        _, text = self._version_output()
        self.assertEqual(text.split()[1], lnpl.__version__)

    def test_subcommand_still_required_without_version(self):
        # --version을 추가하면서 서브커맨드 필수성을 잃지 않았는지 확인한다.
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            with self.assertRaises(SystemExit) as caught:
                cli.main([])
        self.assertNotEqual(caught.exception.code, 0)


if __name__ == "__main__":
    unittest.main()

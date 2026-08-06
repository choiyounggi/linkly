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


GUARDED = """entity Payment
    field
        id UUID
        amount Integer
workflow Approve
    find payment
    when payment.amount > 100
    create payment
"""

UNGUARDED = """entity Payment
    field
        id UUID
        amount Integer
workflow Approve
    find payment
    create payment
"""


def run_cli_err(argv):
    """Drive `cli.main(argv)`; return (rc, stdout+stderr)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = cli.main(argv)
    return rc, buf.getvalue()


class TestFieldNameValidation(unittest.TestCase):
    """`--field NAME=VALUE` must name a real comparison-guard field.

    Issue #45 t4 F-3 / t1 F-9: a mistyped NAME used to be dropped in silence,
    the guard then evaluated against the default 0, and the run reported
    success — the operator had no way to learn their flag did nothing. A name
    that matches nothing cannot influence the run under any circumstances, so
    it is always operator error: validated against a positive allowlist at the
    CLI boundary and rejected, before any native build is attempted.
    """

    def setUp(self):
        self.workdir = os.path.join(REPO, ".claude", "tmp", "cli-field")
        os.makedirs(self.workdir, exist_ok=True)
        self.guarded = os.path.join(self.workdir, "guarded.lnpl")
        with open(self.guarded, "w", encoding="utf-8") as fh:
            fh.write(GUARDED)
        self.unguarded = os.path.join(self.workdir, "unguarded.lnpl")
        with open(self.unguarded, "w", encoding="utf-8") as fh:
            fh.write(UNGUARDED)

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    # ---- error: the name matches nothing -----------------------------------
    def test_an_unmatched_field_name_is_rejected_with_the_candidates(self):
        rc, text = run_cli_err(["build", self.guarded, "--workdir", self.workdir,
                                "--run", "--field", "valu=150"])
        self.assertEqual(rc, 2)
        self.assertIn("valu", text)
        self.assertIn("payment.amount", text)      # the candidate it meant
        self.assertNotIn("native binary", text)    # rejected before building

    def test_every_unmatched_name_is_listed_in_one_message(self):
        rc, text = run_cli_err(["build", self.guarded, "--workdir", self.workdir,
                                "--run", "--field", "aaa=1", "--field", "bbb=2"])
        self.assertEqual(rc, 2)
        self.assertIn("aaa", text)
        self.assertIn("bbb", text)
        # One message, not one per bad field: a fix-resubmit loop is the bug.
        self.assertEqual(text.count("do not match"), 1)

    def test_validation_applies_without_run(self):
        """The typo is operator error whether or not the binary is executed."""
        rc, text = run_cli_err(["build", self.guarded, "--workdir", self.workdir,
                                "--field", "valu=150"])
        self.assertEqual(rc, 2)
        self.assertIn("valu", text)

    # ---- boundary: no comparison guard at all ------------------------------
    def test_a_workflow_with_no_comparison_guard_names_no_candidates(self):
        rc, text = run_cli_err(["build", self.unguarded, "--workdir", self.workdir,
                                "--run", "--field", "amount=1"])
        self.assertEqual(rc, 2)
        self.assertIn("amount", text)
        self.assertIn("(none)", text)

    # ---- boundary: nothing to validate -------------------------------------
    def test_no_field_flag_does_not_trigger_validation(self):
        rc, text = run_cli_err(["build", self.guarded, "--workdir", self.workdir])
        self.assertNotEqual(rc, 2, text)
        self.assertNotIn("do not match", text)

    # ---- the allowlist helper itself ---------------------------------------
    def test_helper_returns_empty_when_every_name_matches(self):
        doc = cli.compile_source(self.guarded)
        self.assertEqual(
            cli._unknown_condition_fields(doc, "wf.approve", {"payment.amount": 150}),
            [])

    def test_helper_returns_sorted_unknown_names(self):
        doc = cli.compile_source(self.guarded)
        self.assertEqual(
            cli._unknown_condition_fields(doc, "wf.approve",
                                          {"zzz": 1, "aaa": 2, "payment.amount": 3}),
            ["aaa", "zzz"])

    def test_helper_on_a_workflow_without_guards_rejects_every_name(self):
        doc = cli.compile_source(self.unguarded)
        self.assertEqual(
            cli._unknown_condition_fields(doc, "wf.approve", {"amount": 1}),
            ["amount"])

    def test_helper_on_an_empty_field_map_returns_empty(self):
        doc = cli.compile_source(self.guarded)
        self.assertEqual(cli._unknown_condition_fields(doc, "wf.approve", {}), [])


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

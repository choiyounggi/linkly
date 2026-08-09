"""`--backend` and `lnpl token` — choosing a capability backend from the CLI (#25).

Two properties carry this file. The first is that the default did not move: a
run with no `--backend` must produce exactly what it produced before the flag
existed, because every other test in the suite is a statement about that path.
The second is that a bad selector fails at the boundary, loudly, naming what it
would have accepted — the alternative is a store that silently is not the one
the operator asked for.
"""

import io
import json
import os
import shutil
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from lnpl import backend
from lnpl.cli import main
from lnpl.drivers import HmacTokenProvider, audience_for_path

from tests.fixtures import GUARDED_LNPL, SHORTEN_LNPL, VALUE_INVENTORY

SECRET = "0123456789abcdef0123456789abcdef"
SECRET_ENV = "LNPL_TEST_JWT_SECRET"

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Build workdirs stay inside the worktree: this repo does not write to `/tmp` or
# `$TMPDIR` (`test_tmp_hygiene.py` enforces both the `dir=` and the cleanup).
CLAUDE_TMP = os.path.join(REPO, ".claude", "tmp")

NEEDS_TOOLS = unittest.skipUnless(
    backend.toolchain_available(),
    "MLIR/LLVM toolchain not installed — see scripts/dev_doctor.sh")


class CliTestCase(unittest.TestCase):

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.dir = box.name
        self.source = os.path.join(self.dir, "inventory.lnpl")
        with open(self.source, "w", encoding="utf-8") as fh:
            fh.write(VALUE_INVENTORY)
        self.db = os.path.join(self.dir, "store.db")

    def payload_file(self, payload):
        path = os.path.join(self.dir, "payload-%d.json" % len(payload))
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return path

    def run_cli(self, argv):
        """-> (rc, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(argv)
        return rc, out.getvalue(), err.getvalue()

    def set_env(self, name, value):
        previous = os.environ.get(name)
        os.environ[name] = value

        def restore():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous

        self.addCleanup(restore)


class RunBackendTest(CliTestCase):

    def test_the_default_run_is_unchanged_by_the_new_flag(self):
        """`--backend fake` stated explicitly must equal the flag omitted.
        Everything else the suite asserts about `run` depends on this."""
        payload = self.payload_file({"id": "p-1", "stock": 9, "quantity": 4})

        implicit = self.run_cli(["run", self.source, "--payload", payload, "--json"])
        explicit = self.run_cli(["run", self.source, "--payload", payload,
                                 "--json", "--backend", "fake"])

        self.assertEqual(implicit[0], 0)
        self.assertEqual(explicit[0], 0)
        self.assertEqual(json.loads(implicit[1])["result"],
                         json.loads(explicit[1])["result"])

    def test_a_sqlite_run_completes_and_writes_its_store(self):
        payload = self.payload_file({"id": "p-1", "stock": 9, "quantity": 4})

        rc, out, _ = self.run_cli(["run", self.source, "--payload", payload,
                                   "--json", "--backend", "sqlite:" + self.db])

        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["result"]["status"], "completed")
        self.assertTrue(os.path.isfile(self.db))

    def test_a_second_sqlite_run_meets_the_first_runs_write(self):
        """The store outlives the run. The create the first run made is still
        there, so the second conflicts — which the fake, seeded fresh every
        time, never does."""
        payload = self.payload_file({"id": "p-1", "stock": 9, "quantity": 4})
        argv = ["run", self.source, "--payload", payload, "--json",
                "--backend", "sqlite:" + self.db]
        self.run_cli(argv)

        rc, out, _ = self.run_cli(argv)

        self.assertEqual(rc, 1)
        self.assertIn("create conflicts", json.loads(out)["result"]["failure_reason"])

    def test_the_fake_backend_is_the_negative_control_for_that(self):
        """Same command twice against the fake: rc 0 both times. Without this
        the rc 1 above would read as a workflow defect rather than as
        persistence."""
        payload = self.payload_file({"id": "p-1", "stock": 9, "quantity": 4})
        argv = ["run", self.source, "--payload", payload, "--json"]
        self.run_cli(argv)

        rc, out, _ = self.run_cli(argv)

        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["result"]["status"], "completed")

    def test_an_unknown_backend_is_an_operator_error(self):
        rc, out, err = self.run_cli(["run", self.source, "--backend", "redis://x"])

        self.assertEqual(rc, 2)
        self.assertEqual(out, "")            # a rejected run emits no result
        self.assertIn("redis://x", err)
        self.assertIn("fake", err)
        self.assertIn("sqlite", err)

    def test_a_store_path_whose_directory_is_missing_is_rejected(self):
        missing = os.path.join(self.dir, "no-such-dir", "store.db")

        rc, _, err = self.run_cli(["run", self.source,
                                   "--backend", "sqlite:" + missing])

        self.assertEqual(rc, 2)
        self.assertIn(missing, err)

    def test_a_store_path_that_cannot_be_written_is_rejected(self):
        locked = os.path.join(self.dir, "locked")
        os.mkdir(locked)
        os.chmod(locked, stat.S_IRUSR | stat.S_IXUSR)
        self.addCleanup(os.chmod, locked, stat.S_IRWXU)
        blocked = os.path.join(locked, "store.db")

        rc, _, err = self.run_cli(["run", self.source,
                                   "--backend", "sqlite:" + blocked])

        self.assertEqual(rc, 2)
        self.assertIn(blocked, err)

    def test_no_row_against_a_real_store_finds_nothing_to_read(self):
        """The boundary between "no store" and "an empty store": both read
        nothing, and the run fails the same way rather than crashing."""
        payload = self.payload_file({"id": "p-1", "stock": 9, "quantity": 4})

        rc, out, _ = self.run_cli(["run", self.source, "--payload", payload,
                                   "--json", "--no-row",
                                   "--backend", "sqlite:" + self.db])

        self.assertEqual(rc, 1)
        self.assertIn("found no row", json.loads(out)["result"]["failure_reason"])


class StoreLifetimeTest(CliTestCase):
    """The driver is released whichever way the run ends.

    A leaked connection is invisible in a one-shot CLI — the process exits and
    the OS cleans up — which is exactly why it needs a test here rather than a
    reviewer's attention: the same code path is what `lnpl serve` reuses per
    request, where a leak per request is the failure.
    """

    def _recording_open(self, calls):
        from lnpl import cli as cli_module
        real = cli_module.open_repository

        def opener(spec):
            driver = real(spec)
            if driver is None:
                return None
            close = driver.close

            def closing():
                calls.append("closed")
                return close()

            driver.close = closing
            return driver

        previous = cli_module.open_repository
        cli_module.open_repository = opener
        self.addCleanup(setattr, cli_module, "open_repository", previous)
        return calls

    def test_the_store_is_released_after_a_completing_run(self):
        calls = self._recording_open([])
        payload = self.payload_file({"id": "p-1", "stock": 9, "quantity": 4})

        rc, _, _ = self.run_cli(["run", self.source, "--payload", payload,
                                 "--json", "--backend", "sqlite:" + self.db])

        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["closed"])

    def test_the_store_is_released_after_a_failing_run(self):
        """The `finally` case: without it the release would be skipped exactly
        when the run went wrong."""
        calls = self._recording_open([])
        payload = self.payload_file({"id": "p-1", "stock": 9, "quantity": 4})

        rc, _, _ = self.run_cli(["run", self.source, "--payload", payload,
                                 "--json", "--no-row",
                                 "--backend", "sqlite:" + self.db])

        self.assertEqual(rc, 1)
        self.assertEqual(calls, ["closed"])


class TokenCommandTest(CliTestCase):

    def test_an_issued_token_verifies_against_the_same_secret(self):
        self.set_env(SECRET_ENV, SECRET)

        rc, out, _ = self.run_cli(["token", self.source,
                                   "--path", "/order-service/place-order",
                                   "--subject", "alice",
                                   "--secret-env", SECRET_ENV])

        self.assertEqual(rc, 0)
        token = out.strip()
        claims = HmacTokenProvider(SECRET).verify(
            token, audience_for_path("/order-service/place-order"))
        self.assertEqual(claims["sub"], "alice")
        # The CLI's own default, not the library's: argparse holds the "15m"
        # string, and it could be edited to anything while
        # `HmacTokenProvider`'s DEFAULT_TTL_MS stayed 15 minutes.
        self.assertEqual(claims["exp"] - claims["iat"], 15 * 60)

    def test_the_lifetime_flag_reaches_the_token(self):
        self.set_env(SECRET_ENV, SECRET)

        rc, out, _ = self.run_cli(["token", self.source,
                                   "--path", "/order-service/place-order",
                                   "--subject", "alice",
                                   "--secret-env", SECRET_ENV, "--ttl", "5m"])

        self.assertEqual(rc, 0)
        claims = HmacTokenProvider(SECRET).verify(
            out.strip(), audience_for_path("/order-service/place-order"))
        self.assertEqual(claims["exp"] - claims["iat"], 300)

    def test_an_unset_secret_variable_names_itself_and_not_its_value(self):
        rc, _, err = self.run_cli(["token", self.source,
                                   "--path", "/order-service/place-order",
                                   "--subject", "alice",
                                   "--secret-env", "LNPL_DEFINITELY_UNSET_XYZ"])

        self.assertEqual(rc, 2)
        self.assertIn("LNPL_DEFINITELY_UNSET_XYZ", err)

    def test_a_short_secret_is_refused_without_echoing_it(self):
        self.set_env(SECRET_ENV, "too-short")

        rc, _, err = self.run_cli(["token", self.source,
                                   "--path", "/order-service/place-order",
                                   "--subject", "alice",
                                   "--secret-env", SECRET_ENV])

        self.assertEqual(rc, 2)
        self.assertIn("32", err)
        self.assertNotIn("too-short", err)

    def test_an_unserved_path_lists_the_paths_that_are_served(self):
        self.set_env(SECRET_ENV, SECRET)

        rc, _, err = self.run_cli(["token", self.source, "--path", "/no/such",
                                   "--subject", "alice",
                                   "--secret-env", SECRET_ENV])

        self.assertEqual(rc, 2)
        self.assertIn("/no/such", err)
        self.assertIn("/order-service/place-order", err)

    def test_the_secret_never_reaches_stdout_or_stderr(self):
        """The token goes to stdout so it can be piped; the key must not."""
        self.set_env(SECRET_ENV, SECRET)

        _, out, err = self.run_cli(["token", self.source,
                                    "--path", "/order-service/place-order",
                                    "--subject", "alice",
                                    "--secret-env", SECRET_ENV])

        self.assertNotIn(SECRET, out)
        self.assertNotIn(SECRET, err)


class SurfaceDocumentationTest(unittest.TestCase):
    """`test_cli_surface_doc.py` gates the whole surface; this pins the entries
    this issue adds, so a later edit that drops one says which."""

    def test_every_new_flag_is_documented(self):
        from tests.test_cli_surface_doc import parse_cli_surface, read_doc

        subcommands, options = parse_cli_surface()
        text = read_doc()

        self.assertIn("token", subcommands)
        for flag in ("--backend", "--jwt-secret-env", "--secret-env",
                     "--subject", "--path", "--ttl"):
            self.assertIn(flag, options, "%s is not declared in cli.py" % flag)
            self.assertIn(flag, text, "%s is not documented" % flag)


class TestBuildSurfacesGuardSkips(CliTestCase):
    """Issue #55 (r1 N-2, r1 F-5): `build --run` must say what a guard refused.

    Measured before this change: the same false guard made `lnpl run` emit a
    `guard-skipped-steps` warning, a first-line count and a skip record, while
    `build --run` printed three step lines, `status completed`, `exit=0` — and
    nothing else. A caller could not tell that run from one that ran every step.

    The records come from `backend.restore_skips`, the reading RFC-0014 §2.6
    already made normative, so nothing about the compiled module changes.
    """

    def build(self, source, *extra):
        workdir = tempfile.mkdtemp(prefix="lnpl-i55-build-", dir=CLAUDE_TMP)
        self.addCleanup(shutil.rmtree, workdir, ignore_errors=True)
        return self.run_cli(["build", source, "--workdir", workdir] + list(extra))

    @NEEDS_TOOLS
    def test_a_false_comparison_guard_is_reported_with_its_condition(self):
        rc, out, err = self.build(GUARDED_LNPL, "--run",
                                  "--field", "token.retryBudget=0")

        self.assertEqual(0, rc, err)
        self.assertIn("(1 step(s) skipped by guard", out)
        self.assertIn("skipped by `when token.retryBudget > 0`: call token", out)
        self.assertIn("guard-skipped-steps", err)
        # The negative control rides along: the step really is absent from the
        # binary's own output, so the record is restored rather than echoed.
        self.assertNotIn("step 4 call token", out)

    @NEEDS_TOOLS
    def test_the_guard_true_run_says_nothing_about_skips(self):
        # The forcing input's control. Issue #44's completion criterion is that
        # these two runs no longer print the same thing.
        rc, out, err = self.build(GUARDED_LNPL, "--run",
                                  "--field", "token.retryBudget=1")

        self.assertEqual(0, rc, err)
        self.assertIn("step 4 call token", out)
        self.assertNotIn("skipped by", out)
        self.assertNotIn("guard-skipped-steps", err)

    @NEEDS_TOOLS
    def test_two_false_guards_are_counted_and_both_named(self):
        # `--skip` falsifies the Presence guard; `retryBudget=0` the comparison
        # one. Both peers of the count must appear, not just the first.
        rc, out, err = self.build(GUARDED_LNPL, "--run", "--skip",
                                  "--field", "token.retryBudget=0")

        self.assertEqual(0, rc, err)
        self.assertIn("(2 step(s) skipped by guard", out)
        self.assertIn("skipped by `when token.cachedAt exists`: cache token", out)
        self.assertIn("skipped by `when token.retryBudget > 0`: call token", out)

    @NEEDS_TOOLS
    def test_a_workflow_with_no_guard_stays_silent(self):
        # Boundary: `shorten.lnpl` declares no guard at all, so a run of it must
        # print exactly what it printed before this change.
        rc, out, err = self.build(SHORTEN_LNPL, "--run")

        self.assertEqual(0, rc, err)
        self.assertNotIn("skipped by", out)
        self.assertNotIn("skipped by guard", out)
        self.assertNotIn("guard-skipped-steps", err)

    @NEEDS_TOOLS
    def test_without_run_there_is_no_skip_report(self):
        # Boundary: nothing executed, so there is no absence to read.
        #
        # `@NEEDS_TOOLS` is load-bearing even though the binary is never run:
        # `build` still performs S4-S7, so `mlir-opt`/`mlir-translate`/`clang`
        # must exist. Without the gate this passes vacuously where they do not —
        # `cmd_build` returns rc 4 and prints nothing, which satisfies both
        # absence checks below while verifying nothing at all.
        rc, out, err = self.build(GUARDED_LNPL, "--field", "token.retryBudget=0")

        self.assertEqual(0, rc, err)
        # The positive half: the build really did happen, so the absences below
        # are the absence of a skip report rather than the absence of output.
        self.assertIn("native binary: ", out)
        # And the mechanism this boundary actually pins: the `--run` branch was
        # never entered, so nothing ran and there is no absence to restore.
        # `exit=` is printed only inside that branch.
        self.assertNotIn("exit=", out)
        self.assertNotIn("skipped by", out)
        self.assertNotIn("guard-skipped-steps", err)


class TestBuildDeclaresValidationDerivation(CliTestCase):
    """Issue #55 (r1 N-3): `--field` cannot reach the validation path, and the
    build must say so where the misreading happens.

    Measured before this change: `build --run` on `shorten.lnpl` — whose
    `validate input` enforces three refinement facets — reported `completed`, and
    `--field slug=1` was rejected with `valid: (none)`. Both statements are true
    and neither says WHY: mode B specialises at build time, so its Validation
    outcome comes from a derived sample payload that is valid by construction,
    and no `--field` value can make a refinement fail. A reader measuring
    refinement enforcement through mode B concluded it was not enforced.
    """

    def build(self, source, *extra):
        workdir = tempfile.mkdtemp(prefix="lnpl-i55-vsd-", dir=CLAUDE_TMP)
        self.addCleanup(shutil.rmtree, workdir, ignore_errors=True)
        return self.run_cli(["build", source, "--workdir", workdir] + list(extra))

    def no_validation_source(self):
        """A workflow with no `Validation` effect.

        Written here rather than taken from `examples/`: measured, all four
        shipped examples have one (`validate token` / `validate input` /
        `validate product` / `validate input`), so there is no example that can
        serve as this boundary.
        """
        path = os.path.join(self.dir, "novalidate.lnpl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("capability postgres\n"
                     "capability redis\n"
                     "\n"
                     "entity Thing\n"
                     "    field\n"
                     "        id UUID\n"
                     "\n"
                     "service ThingService\n"
                     "    performance\n"
                     "        cache 5m\n"
                     "\n"
                     "workflow Fetch\n"
                     "    find thing\n"
                     "    cache thing\n")
        return path

    @NEEDS_TOOLS
    def test_a_workflow_with_validation_declares_where_the_outcome_came_from(self):
        rc, out, err = self.build(SHORTEN_LNPL, "--run")

        self.assertEqual(0, rc, err)
        self.assertIn("validation-sample-derived", err)
        self.assertIn("info", err)
        # The subject names the Validation step, so the reader can tell WHICH
        # step's outcome was derived rather than only that one was.
        self.assertIn("validate input", err)

    def test_a_rejected_field_still_explains_the_channel(self):
        # r1 N-3's exact reproduction. rc 2 comes from the `--field` rejection,
        # which happens BEFORE any build — so this needs no toolchain, and the
        # explanation must still be printed rather than lost behind the error.
        rc, out, err = self.build(SHORTEN_LNPL, "--run", "--field", "slug=1")

        self.assertEqual(2, rc)
        self.assertIn("do not match any comparison-guard field", err)
        self.assertIn("validation-sample-derived", err)

    def test_the_declaration_does_not_need_run(self):
        # It is a property of the BUILD, not of the execution: mode B decides the
        # Validation outcome at compile time. No toolchain needed — the
        # diagnostic is emitted before `build_native` is reached.
        rc, out, err = self.build(SHORTEN_LNPL, "--field", "slug=1")

        self.assertEqual(2, rc)
        self.assertIn("validation-sample-derived", err)

    @NEEDS_TOOLS
    def test_a_workflow_without_validation_says_nothing(self):
        # Boundary, and the negative control for the three cases above: the
        # diagnostic must track the presence of a Validation effect, not fire on
        # every build.
        rc, out, err = self.build(self.no_validation_source(), "--run")

        self.assertEqual(0, rc, err)
        self.assertNotIn("validation-sample-derived", err)
        # ...and the build really happened, so the absence is meaningful.
        self.assertIn("native binary: ", out)
        self.assertIn("status completed", out)

    def test_the_field_help_states_the_reach(self):
        # The `--field` help is where a reader looks before running anything, so
        # the same fact must be there and not only in the diagnostic.
        #
        # `--help` makes argparse write to stdout and raise SystemExit(0), so the
        # exit is asserted through the exception rather than a return value.
        out = io.StringIO()
        with redirect_stdout(out):
            with self.assertRaises(SystemExit) as cm:
                main(["build", "--help"])

        self.assertEqual(0, cm.exception.code)
        help_text = out.getvalue()
        self.assertIn("Comparison guards only", help_text)
        self.assertIn("run --payload", help_text)


class TestValidationEffectSteps(unittest.TestCase):
    """`backend.validation_effect_steps` — the emitter's trigger, on its own.

    Pure: the CLI tests above need a toolchain, this does not, so the rule that
    decides whether the diagnostic fires stays covered without one.
    """

    def _doc(self, source, module="t"):
        from lnpl.lower import lower
        from lnpl.parser import parse
        return lower(parse(source), module).to_document()

    def test_a_validate_step_is_reported_by_name(self):
        with open(SHORTEN_LNPL, encoding="utf-8") as fh:
            doc = self._doc(fh.read(), "shorten")

        self.assertEqual(backend.validation_effect_steps(doc, "wf.shorten"),
                         ["validate input"])

    def test_a_workflow_with_no_validation_reports_none(self):
        doc = self._doc("capability postgres\n"
                        "capability redis\n"
                        "entity Thing\n"
                        "    field\n"
                        "        id UUID\n"
                        "service S\n"
                        "    performance\n"
                        "        cache 5m\n"
                        "workflow Fetch\n"
                        "    find thing\n"
                        "    cache thing\n")

        self.assertEqual(backend.validation_effect_steps(doc, "wf.fetch"), [])

    def test_a_repeated_validation_step_is_named_once(self):
        # Boundary: `repeat` unrolls the body, so the same step appears in the
        # plan more than once. The diagnostic names steps, not occurrences.
        doc = self._doc("capability postgres\n"
                        "entity Thing\n"
                        "    field\n"
                        "        id UUID\n"
                        "service S\n"
                        "workflow Fetch\n"
                        "    repeat 3\n"
                        "    validate thing\n")

        self.assertEqual(backend.validation_effect_steps(doc, "wf.fetch"),
                         ["validate thing"])

    def test_an_unknown_workflow_is_an_error_not_an_empty_list(self):
        # An empty list would read as "no Validation here", silencing the
        # diagnostic for a typo'd workflow id.
        doc = self._doc("capability postgres\n"
                        "entity Thing\n"
                        "    field\n"
                        "        id UUID\n"
                        "service S\n"
                        "workflow Fetch\n"
                        "    find thing\n")

        with self.assertRaises(backend.BackendError):
            backend.validation_effect_steps(doc, "wf.nosuch")


if __name__ == "__main__":
    unittest.main()

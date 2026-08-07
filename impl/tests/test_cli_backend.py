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
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from lnpl.cli import main
from lnpl.drivers import HmacTokenProvider, audience_for_path

from tests.fixtures import VALUE_INVENTORY

SECRET = "0123456789abcdef0123456789abcdef"
SECRET_ENV = "LNPL_TEST_JWT_SECRET"


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


if __name__ == "__main__":
    unittest.main()

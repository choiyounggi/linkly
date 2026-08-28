"""`lnpl.generators` SPI + `lnpl generate` (issue #139): a registered
generator turns the compiled IR into `{relative_path: bytes}`; the core
writer (not the generator) turns that map into files under `--out`. `openapi`
is the built-in generator and its own dogfood case (D5) — `lnpl generate
openapi --out` must produce output byte-identical to `lnpl openapi`'s.

Entry-point injection mirrors `test_driver_spi.py`/`test_cli_capabilities.py`:
`importlib.metadata.entry_points` is monkeypatched to a controlled, in-process
set, and `EntryPoint.load()` itself is never mocked — `generator_spi_fixture`
is a real, importable module, so the load-success path (and the deliberately
missing module for the load-failure path) are exercised for real.
"""

import contextlib
import io
import os
import shutil
import tempfile
import unittest
from importlib import metadata as importlib_metadata
from unittest import mock

from lnpl import cli
from lnpl import generators as generators_module
from lnpl.generators import (BUILTIN_GENERATORS, GeneratorError,
                             resolve_generator, run_generator)
from lnpl.openapi import generate_files
from lnpl.testing import GeneratorTCK

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(REPO, "examples", "login.lnpl")
SCRATCH = os.path.join(REPO, ".claude", "tmp")

GROUP = generators_module.GENERATORS_ENTRY_POINT_GROUP


def entry_point(name, value):
    return importlib_metadata.EntryPoint(name=name, value=value, group=GROUP)


def registered(*entry_points):
    """A patcher for `generators_module._generator_entry_points`'s only
    external call — `importlib_metadata.entry_points(group=...)` — same
    pattern `test_driver_spi.py` uses for `lnpl.drivers`."""
    return mock.patch.object(
        generators_module.importlib_metadata, "entry_points",
        lambda **_kwargs: list(entry_points))


def _main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


def _tmp_out_dir(test):
    """A fresh, empty output directory under `.claude/tmp`, removed on
    teardown — `test_repo_state.py`'s `_tmp_workdir` helper mirrored."""
    os.makedirs(SCRATCH, exist_ok=True)
    path = tempfile.mkdtemp(dir=SCRATCH)
    test.addCleanup(shutil.rmtree, path, True)
    return path


def _remove_if_present(path):
    if os.path.exists(path):
        os.remove(path)


DEMO_ENTRY_POINT = entry_point(
    "demo", "tests.generator_spi_fixture:generate")
ESCAPING_ENTRY_POINT = entry_point(
    "escaping", "tests.generator_spi_fixture:generate_escaping")
EMPTY_ENTRY_POINT = entry_point(
    "empty", "tests.generator_spi_fixture:generate_empty")


# ---- normal ----------------------------------------------------------------

class BuiltinOpenapiDifferentialTest(unittest.TestCase):
    """Normal: openapi re-entering the SPI as the built-in generator must
    still be exactly what `lnpl openapi` produces (D5's dogfood promise)."""

    def setUp(self):
        self.out_dir = _tmp_out_dir(self)

    def test_cli_generate_openapi_matches_cli_openapi_byte_for_byte(self):
        rc1, out1, err1 = _main(["openapi", SRC])
        self.assertEqual(rc1, 0)
        self.assertEqual(err1, "")

        rc2, _out2, err2 = _main(
            ["generate", "openapi", SRC, "--out", self.out_dir])
        self.assertEqual(rc2, 0)
        self.assertEqual(err2, "")

        with open(os.path.join(self.out_dir, "openapi.json"), "rb") as fh:
            written = fh.read()
        self.assertEqual(written, out1.encode("utf-8"))

    def test_resolve_generator_returns_the_builtin_callable_for_openapi(self):
        self.assertIs(resolve_generator("openapi"), generate_files)


class RegisteredGeneratorTest(unittest.TestCase):
    """Normal: a fixture generator registered under `lnpl.generators` is
    caught by name — no change to `resolve_generator` beyond the
    entry-points fallback itself."""

    def test_a_registered_generator_is_resolved_and_called(self):
        with registered(DEMO_ENTRY_POINT):
            generator = resolve_generator("demo")

        result = generator({"module": "widget"}, {})

        self.assertEqual(result, {"demo.txt": b"module=widget"})

    def test_the_loaded_generator_writes_through_the_core_writer(self):
        out_dir = _tmp_out_dir(self)
        with registered(DEMO_ENTRY_POINT):
            generator = resolve_generator("demo")

        written = run_generator(generator, {"module": "widget"}, {}, out_dir)

        self.assertEqual(written, ["demo.txt"])
        with open(os.path.join(out_dir, "demo.txt"), "rb") as fh:
            self.assertEqual(fh.read(), b"module=widget")


class DeterminismTest(unittest.TestCase):
    """Normal: the same document generates the same map twice."""

    def test_openapi_generate_files_is_deterministic(self):
        doc = cli.compile_source([SRC])

        first = generate_files(doc, {})
        second = generate_files(doc, {})

        self.assertEqual(first, second)


# ---- error -------------------------------------------------------------

class UnregisteredGeneratorTest(unittest.TestCase):
    """Error: a name neither built in nor registered is rejected, and the
    message names both closed-table halves (the "triple miss" open_repository
    already established: the name, the built-in set, the registered set)."""

    def test_names_the_name_and_the_built_in_set(self):
        with registered(DEMO_ENTRY_POINT):
            with self.assertRaises(GeneratorError) as caught:
                resolve_generator("nope")

        message = str(caught.exception)
        self.assertIn("nope", message)
        for name in BUILTIN_GENERATORS:
            self.assertIn(name, message)

    def test_names_the_registered_entry_point_name(self):
        with registered(DEMO_ENTRY_POINT):
            with self.assertRaises(GeneratorError) as caught:
                resolve_generator("nope")

        self.assertIn("demo", str(caught.exception))

    def test_zero_registered_entry_points_says_none_rather_than_an_empty_list(self):
        with registered():
            with self.assertRaises(GeneratorError) as caught:
                resolve_generator("nope")

        self.assertIn("none", str(caught.exception))


class EntryPointLoadFailureTest(unittest.TestCase):
    """Error: a registered name whose entry-point fails to import is a
    generator fault (`GeneratorError`), not a traceback out of
    `resolve_generator` — the module's own "one error type out" rule."""

    def test_an_import_failure_becomes_a_generator_error(self):
        broken = entry_point(
            "broken", "tests.no_such_fixture_module_xyz:generate")

        with registered(broken):
            with self.assertRaises(GeneratorError) as caught:
                resolve_generator("broken")

        self.assertIn("broken", str(caught.exception))
        self.assertIsInstance(caught.exception.__cause__, ImportError)


class BuiltinShadowingTest(unittest.TestCase):
    """Error (rejection, not silent acceptance): a package registering
    `openapi` can never shadow the built-in generator — the built-in check
    runs before entry-points are ever consulted."""

    def test_a_same_named_entry_point_never_shadows_builtin_openapi(self):
        shadow = entry_point("openapi", "tests.generator_spi_fixture:generate")

        with registered(shadow):
            generator = resolve_generator("openapi")

        self.assertIs(generator, generate_files)


class PathEscapeRejectionTest(unittest.TestCase):
    """Error: a returned key that escapes `--out` is rejected — at the CLI
    (rc 2, a reason on stderr, nothing written) and at the writer directly
    (an absolute path, checked without any entry-point involved)."""

    def setUp(self):
        self.out_dir = _tmp_out_dir(self)

    def test_cli_generate_rejects_an_escaping_key_with_rc_2_and_a_reason(self):
        with registered(ESCAPING_ENTRY_POINT):
            rc, _out, err = _main(
                ["generate", "escaping", SRC, "--out", self.out_dir])

        self.assertEqual(rc, 2)
        self.assertIn("escape", err)
        self.assertEqual(os.listdir(self.out_dir), [])

    def test_run_generator_rejects_an_absolute_path_key(self):
        def abs_generator(_document, _options):
            return {"/etc/passwd": b"x"}

        with self.assertRaises(GeneratorError):
            run_generator(abs_generator, {}, {}, self.out_dir)
        self.assertEqual(os.listdir(self.out_dir), [])

    def test_run_generator_rejects_an_empty_string_key(self):
        def empty_key_generator(_document, _options):
            return {"": b"x"}

        with self.assertRaises(GeneratorError):
            run_generator(empty_key_generator, {}, {}, self.out_dir)
        self.assertEqual(os.listdir(self.out_dir), [])

    def test_run_generator_rejects_an_empty_out_dir(self):
        # "" is a `--out` value argparse accepts as present, but
        # os.path.realpath("") resolves to the process cwd — exactly the
        # scatter `--out` being required exists to prevent.
        with self.assertRaises(GeneratorError):
            run_generator(lambda _d, _o: {"x.txt": b"x"}, {}, {}, "")

    def test_cli_generate_rejects_an_empty_out_value_with_rc_2(self):
        # Defensive cleanup only — this asserts nothing was written, but a
        # regression here would otherwise scatter openapi.json into the
        # process cwd (which may be the repo worktree root under `unittest
        # discover`).
        cwd_target = os.path.join(os.getcwd(), "openapi.json")
        self.addCleanup(_remove_if_present, cwd_target)

        rc, _out, err = _main(["generate", "openapi", SRC, "--out", ""])

        self.assertEqual(rc, 2)
        self.assertIn("--out", err)
        self.assertFalse(os.path.exists(cwd_target))

    def test_run_generator_rejects_a_symlink_hop_that_escapes_out_dir(self):
        secret_dir = _tmp_out_dir(self)
        os.symlink(secret_dir, os.path.join(self.out_dir, "escape"))

        def symlink_generator(_document, _options):
            return {"escape/leak.txt": b"secret"}

        with self.assertRaises(GeneratorError):
            run_generator(symlink_generator, {}, {}, self.out_dir)
        self.assertEqual(os.listdir(secret_dir), [])


# ---- boundary ----------------------------------------------------------

class EmptyReturnTest(unittest.TestCase):
    """Boundary: an empty map is a valid generator result — nothing is
    written and the CLI still reports success."""

    def setUp(self):
        self.out_dir = _tmp_out_dir(self)

    def test_cli_generate_with_an_empty_return_writes_nothing_and_rc_is_0(self):
        with registered(EMPTY_ENTRY_POINT):
            rc, _out, err = _main(
                ["generate", "empty", SRC, "--out", self.out_dir])

        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        self.assertEqual(os.listdir(self.out_dir), [])


class OpenApiGeneratorTCKTest(GeneratorTCK, unittest.TestCase):
    """The built-in `openapi` generator, proven against `GeneratorTCK`
    (issue #139 D6) — determinism plus the shared core-writer properties."""

    def make_generator(self):
        return generate_files

    def make_document(self):
        return cli.compile_source([SRC])

    def make_out_dir(self):
        return _tmp_out_dir(self)


if __name__ == "__main__":
    unittest.main()

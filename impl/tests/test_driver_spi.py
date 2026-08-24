"""`--backend`'s entry-points fallback (issue #75): a scheme not in the
built-in table (`BACKENDS`) is looked up in the `lnpl.drivers` entry-points
group before the selector is rejected, so an external package can register a
real driver without this module ever importing it.

Discovery (`importlib.metadata.entry_points(group=...)`) is monkeypatched to
a controlled, in-process set — installing a second distribution just to prove
group lookup works would need a package this repo does not ship
(`lnpl-dev-env`'s stdlib-only constraint). `EntryPoint.load()` itself is
never mocked: every case here constructs a real `EntryPoint` and lets it
really import `driver_spi_fixture` (or really fail to import a module that
does not exist), so the one part monkeypatching could paper over — does
`.load()` actually resolve the `module:attr` string — is exercised for real.
"""

import unittest
from importlib import metadata as importlib_metadata
from unittest import mock

from lnpl import drivers as drivers_module
from lnpl.drivers import BACKENDS, DriverError, SqliteRepositoryDriver, open_repository

from tests.driver_spi_fixture import DemoRepositoryDriver

GROUP = drivers_module.DRIVERS_ENTRY_POINT_GROUP


def entry_point(name, value):
    return importlib_metadata.EntryPoint(name=name, value=value, group=GROUP)


def registered(*entry_points):
    """A patcher for `drivers_module._driver_entry_points`'s only external
    call — `importlib_metadata.entry_points(group=...)` — returning exactly
    `entry_points` regardless of what is actually installed."""
    return mock.patch.object(
        drivers_module.importlib_metadata, "entry_points",
        lambda **_kwargs: list(entry_points))


DEMO_ENTRY_POINT = entry_point(
    "demo", "tests.driver_spi_fixture:make_demo_driver")


class RegisteredSchemeTest(unittest.TestCase):
    """Normal: a fixture driver registered under `lnpl.drivers` is caught by
    `--backend demo:<arg>` on registration alone — no change to
    `open_repository` beyond the entry-points fallback itself."""

    def test_a_registered_scheme_is_caught_and_the_arg_reaches_the_factory(self):
        with registered(DEMO_ENTRY_POINT):
            driver = open_repository("demo:hello")

        self.assertIsInstance(driver, DemoRepositoryDriver)
        self.assertEqual(driver.arg, "hello")

    def test_the_loaded_driver_behaves_like_a_repository_driver(self):
        with registered(DEMO_ENTRY_POINT):
            driver = open_repository("demo:unused")

        driver.seed({"widget": {"w1": {"id": "w1", "n": 1}}})
        self.assertEqual(driver.execute("widget", "read", "w1")["n"], 1)
        driver.close()


class UnregisteredSchemeTest(unittest.TestCase):
    """Error: a scheme neither built in nor registered is rejected, and the
    message names both closed-table halves so a typo is diagnosable."""

    def test_names_the_spec_and_the_built_in_set(self):
        with registered(DEMO_ENTRY_POINT):
            with self.assertRaises(ValueError) as caught:
                open_repository("nope:x")

        message = str(caught.exception)
        self.assertIn("nope:x", message)
        for name in BACKENDS:
            self.assertIn(name, message)

    def test_names_the_registered_entry_point_scheme(self):
        with registered(DEMO_ENTRY_POINT):
            with self.assertRaises(ValueError) as caught:
                open_repository("nope:x")

        self.assertIn("demo", str(caught.exception))

    def test_zero_registered_entry_points_says_none_rather_than_an_empty_list(self):
        with registered():
            with self.assertRaises(ValueError) as caught:
                open_repository("nope:x")

        self.assertIn("none", str(caught.exception))


class EntryPointLoadFailureTest(unittest.TestCase):
    """Error: a registered scheme whose entry-point fails to import is a
    driver fault (`DriverError`), not a traceback out of `open_repository` —
    the module's own "ONE ERROR TYPE OUT" rule applied to the new path."""

    def test_an_import_failure_becomes_a_driver_error(self):
        broken = entry_point(
            "broken", "tests.no_such_fixture_module_xyz:make_driver")

        with registered(broken):
            with self.assertRaises(DriverError) as caught:
                open_repository("broken:x")

        self.assertIn("broken", str(caught.exception))
        self.assertIsInstance(caught.exception.__cause__, ImportError)


class BuiltinShadowingTest(unittest.TestCase):
    """Boundary: a package registering `sqlite` or `fake` can never shadow
    the built-in driver — the built-in check runs before entry-points are
    ever consulted."""

    def setUp(self):
        import os
        import tempfile
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.path = os.path.join(box.name, "store.db")

    def test_a_same_named_entry_point_never_shadows_builtin_sqlite(self):
        shadow = entry_point("sqlite", "tests.driver_spi_fixture:make_demo_driver")

        with registered(shadow):
            driver = open_repository("sqlite:" + self.path)

        self.addCleanup(driver.close)
        self.assertIsInstance(driver, SqliteRepositoryDriver)

    def test_a_same_named_entry_point_never_shadows_builtin_fake(self):
        shadow = entry_point("fake", "tests.driver_spi_fixture:make_demo_driver")

        with registered(shadow):
            driver = open_repository("fake")

        self.assertIsNone(driver)

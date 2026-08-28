"""`--network`'s entry-points fallback (issue #132): a scheme not built in
(`fake`/`http`) is looked up in the `lnpl.networks` entry-points group before
the selector is rejected — the same shape `test_driver_spi.py` proves for
`lnpl.drivers` (issue #75).

Discovery (`importlib.metadata.entry_points(group=...)`) is monkeypatched to
a controlled, in-process set, same reasoning as `test_driver_spi.py`:
installing a second distribution just to prove group lookup works would need
a package this repo does not ship. `EntryPoint.load()` itself is never
mocked.
"""

import unittest
from importlib import metadata as importlib_metadata
from unittest import mock

from lnpl import drivers as drivers_module
from lnpl.drivers import HttpNetworkDriver, NETWORKS, DriverError, open_network

from tests.network_spi_fixture import DemoNetworkDriver

GROUP = drivers_module.NETWORKS_ENTRY_POINT_GROUP


def entry_point(name, value):
    return importlib_metadata.EntryPoint(name=name, value=value, group=GROUP)


def registered(*entry_points):
    """A patcher for `drivers_module._network_entry_points`'s only external
    call — `importlib_metadata.entry_points(group=...)` — returning exactly
    `entry_points` regardless of what is actually installed."""
    return mock.patch.object(
        drivers_module.importlib_metadata, "entry_points",
        lambda **_kwargs: list(entry_points))


DEMO_ENTRY_POINT = entry_point(
    "demo", "tests.network_spi_fixture:make_demo_network")


class RegisteredSchemeTest(unittest.TestCase):
    """Normal: a fixture driver registered under `lnpl.networks` is caught
    by `--network demo:<arg>` on registration alone — no change to
    `open_network` beyond the entry-points fallback itself."""

    def test_a_registered_scheme_is_caught_and_the_arg_reaches_the_factory(self):
        with registered(DEMO_ENTRY_POINT):
            driver = open_network("demo:hello")

        self.assertIsInstance(driver, DemoNetworkDriver)
        self.assertEqual(driver.arg, "hello")

    def test_the_loaded_driver_behaves_like_a_network_driver(self):
        with registered(DEMO_ENTRY_POINT):
            driver = open_network("demo:unused")

        status, body, _headers = driver.call("some-target", {}, 1000)
        self.assertEqual(status, 200)
        self.assertEqual(body, {"target": "some-target"})
        driver.close()


class BareBuiltinBackwardCompatTest(unittest.TestCase):
    """Regression: bare `fake`/`http` (no `:arg`) resolve exactly as before
    this issue — the untouched default path stays byte-identical."""

    def test_bare_fake_still_returns_none(self):
        self.assertIsNone(open_network("fake"))

    def test_bare_http_still_returns_an_http_network_driver(self):
        driver = open_network("http")

        self.assertIsInstance(driver, HttpNetworkDriver)


class UnregisteredSchemeTest(unittest.TestCase):
    """Error: a scheme neither built in nor registered is rejected, and the
    message names both closed-table halves so a typo is diagnosable."""

    def test_names_the_spec_and_the_built_in_set(self):
        with registered(DEMO_ENTRY_POINT):
            with self.assertRaises(ValueError) as caught:
                open_network("nope:x")

        message = str(caught.exception)
        self.assertIn("nope:x", message)
        for name in NETWORKS:
            self.assertIn(name, message)

    def test_names_the_registered_entry_point_scheme(self):
        with registered(DEMO_ENTRY_POINT):
            with self.assertRaises(ValueError) as caught:
                open_network("nope:x")

        self.assertIn("demo", str(caught.exception))

    def test_zero_registered_entry_points_says_none_rather_than_an_empty_list(self):
        with registered():
            with self.assertRaises(ValueError) as caught:
                open_network("nope:x")

        self.assertIn("none", str(caught.exception))


class EntryPointLoadFailureTest(unittest.TestCase):
    """Error: a registered scheme whose entry-point fails to import is a
    driver fault (`DriverError`), not a traceback out of `open_network` —
    the module's own "ONE ERROR TYPE OUT" rule applied to the new path."""

    def test_an_import_failure_becomes_a_driver_error(self):
        broken = entry_point(
            "broken", "tests.no_such_fixture_module_xyz:make_network")

        with registered(broken):
            with self.assertRaises(DriverError) as caught:
                open_network("broken:x")

        self.assertIn("broken", str(caught.exception))
        self.assertIsInstance(caught.exception.__cause__, ImportError)


class BuiltinShadowingTest(unittest.TestCase):
    """Boundary: a package registering `fake` or `http` can never shadow
    the built-ins — both built-in checks run before entry-points are ever
    consulted."""

    def test_a_same_named_entry_point_never_shadows_builtin_fake(self):
        shadow = entry_point("fake", "tests.network_spi_fixture:make_demo_network")

        with registered(shadow):
            driver = open_network("fake")

        self.assertIsNone(driver)

    def test_a_same_named_entry_point_never_shadows_builtin_http(self):
        shadow = entry_point("http", "tests.network_spi_fixture:make_demo_network")

        with registered(shadow):
            driver = open_network("http")

        self.assertIsInstance(driver, HttpNetworkDriver)
        self.assertNotIsInstance(driver, DemoNetworkDriver)


if __name__ == "__main__":
    unittest.main()

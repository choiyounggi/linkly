"""Issue #109, D6 — `path "<template>"` + `call ... with <ref>...` assembly at
the driver level: substituting `path_args` into a capability's declared
`path` template, escaped against path injection. Lowering-time grammar and
placeholder-count checks are `test_http_capability_lower.py`'s file; this one
is runtime only, exercised directly against both drivers (their parity is
what `NetworkDriverTCK` then re-checks structurally).
"""

import unittest

from lnpl.drivers import FakeNetworkDriver, HttpNetworkDriver

from tests.test_network_driver import _ServerTestCase, _make_handler


class HttpPathTemplateTest(_ServerTestCase):

    def test_one_path_arg_is_substituted_and_escaped(self):
        handler = _make_handler(status=200, body={})
        url = self.start(handler)
        driver = HttpNetworkDriver(
            endpoints={"Orders": url},
            capabilities={"Orders": {"method": "GET", "headers": {},
                                     "path": "/orders/{}"}})
        self.addCleanup(driver.close)

        driver.call("Orders", {}, 2000, path_args=["abc-123"])

        self.assertEqual(handler.received_paths[0], "/orders/abc-123")

    def test_two_path_args_fill_two_placeholders_in_order(self):
        handler = _make_handler(status=200, body={})
        url = self.start(handler)
        driver = HttpNetworkDriver(
            endpoints={"Orders": url},
            capabilities={"Orders": {"method": "GET", "headers": {},
                                     "path": "/orders/{}/items/{}"}})
        self.addCleanup(driver.close)

        driver.call("Orders", {}, 2000, path_args=["ord1", "sku2"])

        self.assertEqual(handler.received_paths[0], "/orders/ord1/items/sku2")

    def test_a_slash_in_an_argument_is_percent_encoded_not_a_new_segment(self):
        """Path injection boundary: an argument value that itself contains
        `/` (or `..`) must not be able to add or remove a path segment."""
        handler = _make_handler(status=200, body={})
        url = self.start(handler)
        driver = HttpNetworkDriver(
            endpoints={"Orders": url},
            capabilities={"Orders": {"method": "GET", "headers": {},
                                     "path": "/orders/{}"}})
        self.addCleanup(driver.close)

        driver.call("Orders", {}, 2000, path_args=["../../etc/passwd"])

        self.assertEqual(handler.received_paths[0],
                         "/orders/..%2F..%2Fetc%2Fpasswd")

    def test_no_path_args_leaves_the_endpoints_path_untouched(self):
        handler = _make_handler(status=200, body={})
        url = self.start(handler)
        driver = HttpNetworkDriver(
            endpoints={"Orders": url},
            capabilities={"Orders": {"method": "GET", "headers": {},
                                     "path": "/orders/{}"}})
        self.addCleanup(driver.close)

        driver.call("Orders", {}, 2000)

        self.assertEqual(handler.received_paths[0], "/")

    def test_path_args_without_a_declared_path_raises_driver_error(self):
        """Defense-in-depth (lowering already refuses this at compile time —
        this is the driver used directly, without going through `lower.py`)."""
        from lnpl.drivers import DriverError
        handler = _make_handler(status=200, body={})
        url = self.start(handler)
        driver = HttpNetworkDriver(
            endpoints={"Orders": url},
            capabilities={"Orders": {"method": "GET", "headers": {}}})
        self.addCleanup(driver.close)

        with self.assertRaises(DriverError):
            driver.call("Orders", {}, 2000, path_args=["x"])


class FakePathTemplateTest(unittest.TestCase):

    def test_fake_driver_assembles_the_same_escaped_path_as_http(self):
        driver = FakeNetworkDriver(
            capabilities={"Orders": {"method": "GET", "path": "/orders/{}"}})

        driver.call("Orders", {}, 1000, path_args=["../etc"])

        self.assertEqual(driver.received[-1]["path"], "/orders/..%2Fetc")

    def test_fake_driver_records_none_path_when_no_path_args_given(self):
        driver = FakeNetworkDriver(
            capabilities={"Orders": {"method": "GET", "path": "/orders/{}"}})

        driver.call("Orders", {}, 1000)

        self.assertIsNone(driver.received[-1]["path"])


if __name__ == "__main__":
    unittest.main()

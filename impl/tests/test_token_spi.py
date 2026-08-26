"""`--token-provider`'s entry-points fallback (issue #119b, Task 03): a name
not built in (`hmac`) is looked up in the `lnpl.tokens` entry-points group
before the selector is rejected — the same shape `test_driver_spi.py` proves
for `lnpl.drivers` (issue #75), with one deliberate difference: a same-named
entry-point does not lose silently to the built-in here, it is refused
loudly (D8) — token identity is the trust boundary `security role`
enforcement depends on (issue #119 A), so a shadowing attempt should be
visible, not quietly ineffective.

Discovery (`importlib.metadata.entry_points(group=...)`) is monkeypatched to
a controlled, in-process set, same reasoning as `test_driver_spi.py`:
installing a second distribution just to prove group lookup works would need
a package this repo does not ship. `EntryPoint.load()` itself is never
mocked.
"""

import http.client
import json
import os
import threading
import unittest
from importlib import metadata as importlib_metadata
from unittest import mock

from lnpl import drivers as drivers_module
from lnpl.drivers import (BUILTIN_TOKEN_PROVIDERS, DriverError,
                          HmacTokenProvider, TokenError, open_token_provider)
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.serve import serve
from lnpl.testing import TokenProviderTCK

from tests.token_spi_fixture import DEMO_SECRET, DemoTokenProvider

GROUP = drivers_module.TOKENS_ENTRY_POINT_GROUP
SECRET = "0123456789abcdef0123456789abcdef"

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHORTEN = os.path.join(REPO, "examples", "shorten.lnpl")
SHORTEN_PATH = "/shorten-service/shorten"
LINK_PAYLOAD = {
    "id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
    "slug": "abc-123",
    "target": "https://example.com/a",
    "owner": "3f2504e0-4f89-41d3-9a0c-0305e82c3302",
    "clicks": 0,
    "createdAt": "2026-07-31T09:00:00Z",
}


def compile_file(path):
    with open(path, encoding="utf-8") as fh:
        return lower(parse(fh.read()),
                     os.path.splitext(os.path.basename(path))[0]).to_document()


def entry_point(name, value):
    return importlib_metadata.EntryPoint(name=name, value=value, group=GROUP)


def registered(*entry_points):
    return mock.patch.object(
        drivers_module.importlib_metadata, "entry_points",
        lambda **_kwargs: list(entry_points))


DEMO_ENTRY_POINT = entry_point(
    "demo", "tests.token_spi_fixture:make_demo_token_provider")


class RegisteredProviderTest(unittest.TestCase):
    """Normal: a fixture provider registered under `lnpl.tokens` is caught by
    `--token-provider demo` on registration alone."""

    def test_a_registered_provider_is_caught_and_returned(self):
        with registered(DEMO_ENTRY_POINT):
            provider = open_token_provider("demo")

        self.assertIsInstance(provider, DemoTokenProvider)

    def test_the_loaded_provider_behaves_like_a_token_provider(self):
        with registered(DEMO_ENTRY_POINT):
            provider = open_token_provider("demo")

        token = provider.issue("alice", "some-service")
        self.assertEqual(provider.verify(token, "some-service")["sub"], "alice")


class UnregisteredProviderTest(unittest.TestCase):
    """Error: a name neither built in nor registered is rejected, and the
    message names both closed-table halves."""

    def test_names_the_name_and_the_built_in_set(self):
        with registered(DEMO_ENTRY_POINT):
            with self.assertRaises(ValueError) as caught:
                open_token_provider("nope")

        message = str(caught.exception)
        self.assertIn("nope", message)
        for name in BUILTIN_TOKEN_PROVIDERS:
            self.assertIn(name, message)

    def test_names_the_registered_entry_point_name(self):
        with registered(DEMO_ENTRY_POINT):
            with self.assertRaises(ValueError) as caught:
                open_token_provider("nope")

        self.assertIn("demo", str(caught.exception))

    def test_zero_registered_entry_points_says_none_rather_than_an_empty_list(self):
        with registered():
            with self.assertRaises(ValueError) as caught:
                open_token_provider("nope")

        self.assertIn("none", str(caught.exception))


class EntryPointLoadFailureTest(unittest.TestCase):
    """Error: a registered name whose entry-point fails to import is a
    `DriverError`, not a traceback out of `open_token_provider` — the same
    "ONE ERROR TYPE OUT" rule `open_repository` already applies."""

    def test_an_import_failure_becomes_a_driver_error(self):
        broken = entry_point(
            "broken", "tests.no_such_fixture_module_xyz:make_provider")

        with registered(broken):
            with self.assertRaises(DriverError) as caught:
                open_token_provider("broken")

        self.assertIn("broken", str(caught.exception))
        self.assertIsInstance(caught.exception.__cause__, ImportError)


class BuiltinShadowingTest(unittest.TestCase):
    """Boundary/negative control (D8): a package registering `hmac` cannot
    make `--token-provider hmac` load it — the request is refused outright,
    naming the conflicting entry-point and the module it points at."""

    def test_a_same_named_entry_point_never_shadows_builtin_hmac(self):
        shadow = entry_point(
            "hmac", "tests.token_spi_fixture:make_demo_token_provider")

        with registered(shadow):
            with self.assertRaises(TokenError) as caught:
                open_token_provider("hmac", secret=SECRET)

        message = str(caught.exception)
        self.assertIn("hmac", message)
        self.assertIn("tests.token_spi_fixture:make_demo_token_provider",
                      message)

    def test_with_no_shadow_registered_hmac_resolves_normally(self):
        with registered(DEMO_ENTRY_POINT):        # unrelated registration
            provider = open_token_provider("hmac", secret=SECRET)

        self.assertIsInstance(provider, HmacTokenProvider)
        self.assertNotIsInstance(provider, DemoTokenProvider)


class DefaultPathTest(unittest.TestCase):
    """Regression: an unspecified name resolves to the built-in `hmac`
    provider, byte-identical to before `--token-provider` existed."""

    def test_unspecified_name_defaults_to_the_builtin_hmac_provider(self):
        with registered(DEMO_ENTRY_POINT):
            provider = open_token_provider("hmac", secret=SECRET, issuer="lnpl")

        token = provider.issue("alice", "aud")
        claims = provider.verify(token, "aud")
        self.assertEqual(claims["iss"], "lnpl")

    def test_hmac_without_a_secret_is_a_clear_token_error_not_a_crash(self):
        with self.assertRaises(TokenError) as caught:
            open_token_provider("hmac")
        self.assertIn("secret", str(caught.exception))


class SpiProviderPassesTheTCKTest(TokenProviderTCK, unittest.TestCase):
    """The point of the SPI boundary: a provider the core module did not
    construct still has to pass the same contract the built-in one does — a
    provider that can't is proof the contract itself is unimplementable, not
    that the TCK is wrong (Task 03's own Verify note)."""

    def make_provider(self):
        return DemoTokenProvider(DEMO_SECRET)

    def make_foreign_issuer_provider(self):
        return DemoTokenProvider(DEMO_SECRET, issuer="somebody-else")


class ServedThroughAnSpiProviderTest(unittest.TestCase):
    """End-to-end: `serve()` wired with an entry-point-loaded provider (the
    shape `cli._token_provider` builds via `open_token_provider`) actually
    gates the route — proof the SPI boundary is a real verification path
    (DoD: "RS256/ES256 검증 경로가 존재한다 — lnpl.tokens SPI로"), not only a
    unit-level resolution function."""

    def setUp(self):
        self.doc = compile_file(SHORTEN)

    def start(self, token_provider):
        server = serve(self.doc, port=0, token_provider=token_provider)
        thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def post(self, port, token):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        self.addCleanup(conn.close)
        conn.request("POST", SHORTEN_PATH, body=json.dumps(LINK_PAYLOAD).encode(),
                     headers={"Authorization": "Bearer %s" % token})
        resp = conn.getresponse()
        return resp, resp.read()

    def test_a_token_from_the_registered_provider_is_served(self):
        with registered(DEMO_ENTRY_POINT):
            provider = open_token_provider("demo")
        port = self.start(provider)
        token = provider.issue("alice", "shorten-service")

        resp, _ = self.post(port, token)

        self.assertEqual(200, resp.status)

    def test_a_token_from_a_different_key_is_still_rejected(self):
        with registered(DEMO_ENTRY_POINT):
            provider = open_token_provider("demo")
        port = self.start(provider)
        rogue_token = HmacTokenProvider(SECRET).issue("alice", "shorten-service")

        resp, raw = self.post(port, rogue_token)

        self.assertEqual(401, resp.status)
        self.assertEqual("auth-invalid", json.loads(raw)["code"])


if __name__ == "__main__":
    unittest.main()

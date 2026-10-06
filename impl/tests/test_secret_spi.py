"""The `lnpl.secrets` SPI (issue #192): an external package registers a
`SecretProvider` factory under the `lnpl.secrets` entry-points group, and
`open_secret_provider(name)` finds it — the same discovery shape
`test_publisher_spi.py` proves for `lnpl.publishers` (issue #191).

The two built-in source names (`env`, `file`) are implemented inline by the
core and are never looked up as providers: a registration under either name
is refused outright (the `lnpl.tokens` `hmac` precedent), because the secret
source is a trust boundary. No driver exception's own text is ever copied
into an error — a factory may put a URL or a secret value in it.

Discovery (`importlib.metadata.entry_points(group=...)`) is monkeypatched to
a controlled, in-process set, group-filtered; `EntryPoint.load()` itself is
never mocked.
"""

import traceback
import unittest
from importlib import metadata as importlib_metadata
from unittest import mock

from lnpl import drivers as drivers_module
from lnpl.capabilities import capabilities_document
from lnpl.drivers import (BUILTIN_SECRET_SOURCES, DriverError, SecretProvider,
                          open_secret_provider)
from lnpl.testing import SecretProviderTCK

from tests import secret_spi_fixture
from tests.secret_spi_fixture import DemoSecretProvider

GROUP = drivers_module.SECRETS_ENTRY_POINT_GROUP
MARKER = "FAKE-SECRET-192"


def entry_point(name, value):
    return importlib_metadata.EntryPoint(name=name, value=value, group=GROUP)


def _secrets_registered(*entry_points):
    """Patch `importlib.metadata.entry_points` so the `lnpl.secrets` group
    returns exactly `entry_points` and every other group returns nothing,
    whatever is installed."""
    by_group = {}
    for ep in entry_points:
        by_group.setdefault(ep.group, []).append(ep)

    def fake_entry_points(**kwargs):
        return list(by_group.get(kwargs.get("group"), ()))

    return mock.patch.object(drivers_module.importlib_metadata,
                             "entry_points", fake_entry_points)


DEMO_ENTRY_POINT = entry_point(
    "demo", "tests.secret_spi_fixture:make_demo_secret_provider")
BROKEN_VALUE = "tests.no_such_module_t192:x"


def _formatted(exc):
    return "".join(traceback.format_exception(type(exc), exc,
                                              exc.__traceback__))


class _FixtureTest(unittest.TestCase):
    def setUp(self):
        secret_spi_fixture.INSTANCES.clear()


class SecretProviderContractTest(unittest.TestCase):
    """The bare contract class implements nothing: each of the three
    methods a driver must provide raises `NotImplementedError`."""

    def test_get_is_abstract(self):
        with self.assertRaises(NotImplementedError):
            SecretProvider().get("jwt")

    def test_get_previous_is_abstract(self):
        with self.assertRaises(NotImplementedError):
            SecretProvider().get_previous("jwt")

    def test_close_is_abstract(self):
        with self.assertRaises(NotImplementedError):
            SecretProvider().close()


class RegisteredProviderTest(_FixtureTest):

    def test_normal_registered_name_returns_the_factory_instance(self):
        with _secrets_registered(DEMO_ENTRY_POINT):
            provider = open_secret_provider("demo")

        self.assertEqual(len(secret_spi_fixture.INSTANCES), 1)
        self.assertIs(provider, secret_spi_fixture.INSTANCES[-1])
        self.assertIsInstance(provider, DemoSecretProvider)
        self.assertEqual(provider.get("jwt"), secret_spi_fixture.DEMO_SECRET_K0)


class UnregisteredProviderTest(_FixtureTest):

    def test_error_unknown_name_lists_builtins_and_registered(self):
        with _secrets_registered(DEMO_ENTRY_POINT):
            with self.assertRaises(ValueError) as caught:
                open_secret_provider("nope")

        text = str(caught.exception)
        self.assertIn("'nope'", text)
        self.assertIn("env, file", text)
        self.assertIn("demo", text)
        self.assertEqual(secret_spi_fixture.INSTANCES, [])

    def test_normal_registered_names_are_listed_sorted(self):
        with _secrets_registered(entry_point("zeta", "pkg_z:make"),
                                 entry_point("alpha", "pkg_a:make")):
            with self.assertRaises(ValueError) as caught:
                open_secret_provider("nope")

        self.assertTrue(str(caught.exception).endswith(
            "registered entry-points: alpha, zeta)"))

    def test_boundary_nothing_registered_says_none(self):
        with _secrets_registered():
            with self.assertRaises(ValueError) as caught:
                open_secret_provider("nope")

        self.assertEqual(
            str(caught.exception),
            "unknown secret provider 'nope' (built-in: env, file; "
            "registered entry-points: none)")


class EntryPointLoadFailureTest(_FixtureTest):

    def test_error_unimportable_value_becomes_driver_error(self):
        with _secrets_registered(entry_point("broken", BROKEN_VALUE)):
            with self.assertRaises(DriverError) as caught:
                open_secret_provider("broken")

        text = str(caught.exception)
        self.assertIn(BROKEN_VALUE, text)
        self.assertIn("ModuleNotFoundError", text)
        self.assertEqual(
            text,
            "secret provider 'broken' registered via entry-point %r failed "
            "to load (ModuleNotFoundError)" % BROKEN_VALUE)
        self.assertIsInstance(caught.exception.__cause__, ModuleNotFoundError)


class FactoryFailureTest(_FixtureTest):

    def test_error_raising_factory_names_only_the_exception_type(self):
        broken = entry_point(
            "broken", "tests.secret_spi_fixture:make_broken_factory")
        with _secrets_registered(broken):
            with self.assertRaises(DriverError) as caught:
                open_secret_provider("broken")

        exc = caught.exception
        self.assertEqual(
            str(exc), "secret provider 'broken' failed to start (RuntimeError)")
        self.assertIsNone(exc.__cause__)
        self.assertTrue(exc.__suppress_context__)
        self.assertNotIn(MARKER, _formatted(exc))


class BuiltinShadowingTest(_FixtureTest):
    """A registration named like a built-in source is refused — never
    loaded, never silently ignored."""

    def test_error_entry_point_named_file_is_refused(self):
        shadow = entry_point(
            "file", "tests.secret_spi_fixture:make_demo_secret_provider")
        with _secrets_registered(shadow):
            with self.assertRaises(DriverError) as caught:
                open_secret_provider("file")

        text = str(caught.exception)
        self.assertIn("tests.secret_spi_fixture:make_demo_secret_provider",
                      text)
        self.assertIn("attempts to shadow the built-in secret source 'file'",
                      text)
        self.assertEqual(secret_spi_fixture.INSTANCES, [])

    def test_error_entry_point_named_env_is_refused(self):
        shadow = entry_point(
            "env", "tests.secret_spi_fixture:make_demo_secret_provider")
        with _secrets_registered(shadow):
            with self.assertRaises(DriverError) as caught:
                open_secret_provider("env")

        text = str(caught.exception)
        self.assertIn("tests.secret_spi_fixture:make_demo_secret_provider",
                      text)
        self.assertIn("attempts to shadow the built-in secret source 'env'",
                      text)
        self.assertEqual(secret_spi_fixture.INSTANCES, [])

    def test_boundary_builtin_name_without_shadow_is_not_a_provider(self):
        with _secrets_registered(DEMO_ENTRY_POINT):
            with self.assertRaises(ValueError) as caught:
                open_secret_provider("file")

        self.assertEqual(
            str(caught.exception),
            "secret provider 'file' is a built-in source, not a registered "
            "provider — write jwt = \"ENV_NAME\" or jwt = { file = "
            "\"/absolute/path\" } instead")
        self.assertEqual(BUILTIN_SECRET_SOURCES, ("env", "file"))


class DemoSecretProviderTCKTest(SecretProviderTCK, unittest.TestCase):
    """The in-repo fake passes the full TCK — and is the positive control
    for `SecretProviderTCKDiscriminatesTest` below."""

    def make_provider(self, initial):
        return DemoSecretProvider({self.TCK_KEY: initial})

    def rotate(self, provider, new_value):
        provider.rotate(self.TCK_KEY, new_value)

    def break_provider(self, provider):
        provider.fail = True


class _StalePreviousProvider(DemoSecretProvider):
    """Known-bad: reports the CURRENT value as the previous one."""

    def get_previous(self, key):
        self._check(key)
        return self.values[key]


class _KeyErrorProvider(DemoSecretProvider):
    """Known-bad: an unknown key escapes as a raw `KeyError`."""

    def get(self, key):
        return self.values[key]

    def get_previous(self, key):
        if key not in self.values:
            raise KeyError(key)
        return self.previous.get(key)


def _run_one_secret_tck_case(provider_cls, case_name):
    """Run exactly one `SecretProviderTCK` method, in isolation, against
    `provider_cls`, and return the `unittest.TestResult` (the
    `_run_one_tck_case` shape of test_token_contract.py)."""

    class _OneCase(SecretProviderTCK, unittest.TestCase):
        def make_provider(self, initial):
            return provider_cls({self.TCK_KEY: initial})

        def rotate(self, provider, new_value):
            provider.rotate(self.TCK_KEY, new_value)

        def break_provider(self, provider):
            provider.fail = True

    result = unittest.TestResult()
    _OneCase(case_name).run(result)
    return result


class SecretProviderTCKDiscriminatesTest(unittest.TestCase):
    """`harness-reverse-controls`: a certifying TCK must fail a known-bad
    driver. Each negative control reports exactly one run (a silently
    skipped case would read as "no failures" for the wrong reason)."""

    ROTATION = "test_rotation_moves_current_to_previous"
    UNKNOWN = "test_an_unknown_key_raises_driver_error"

    def test_error_stale_previous_fails_the_rotation_case(self):
        result = _run_one_secret_tck_case(_StalePreviousProvider, self.ROTATION)

        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(result.failures), 1)

    def test_error_key_error_provider_fails_the_unknown_key_case(self):
        result = _run_one_secret_tck_case(_KeyErrorProvider, self.UNKNOWN)

        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(result.failures) + len(result.errors), 1)

    def test_normal_real_fake_passes_both_cases(self):
        for case in (self.ROTATION, self.UNKNOWN):
            with self.subTest(case=case):
                result = _run_one_secret_tck_case(DemoSecretProvider, case)

                self.assertEqual(result.testsRun, 1)
                self.assertEqual(result.failures, [])
                self.assertEqual(result.errors, [])


class SecretsSlotCatalogTest(unittest.TestCase):
    """`lnpl capabilities` lists the `secrets` slot: the two built-in
    sources and every registration, load failures included, never
    raising."""

    def _secrets_slot(self, *entry_points):
        with _secrets_registered(*entry_points):
            return capabilities_document()["slots"]["secrets"]

    def test_normal_builtins_are_env_and_file(self):
        slot = self._secrets_slot()

        self.assertEqual(slot, {"builtin": ["env", "file"], "registered": []})

    def test_normal_registered_demo_is_loadable(self):
        slot = self._secrets_slot(DEMO_ENTRY_POINT)

        self.assertEqual([(e["name"], e["loadable"]) for e in slot["registered"]],
                         [("demo", True)])

    def test_error_broken_registration_is_listed_not_raised(self):
        slot = self._secrets_slot(entry_point("broken", BROKEN_VALUE))

        self.assertEqual([(e["name"], e["loadable"]) for e in slot["registered"]],
                         [("broken", False)])

    def test_boundary_builtin_shadow_is_listed(self):
        shadow = entry_point(
            "file", "tests.secret_spi_fixture:make_demo_secret_provider")
        slot = self._secrets_slot(shadow)

        self.assertEqual(slot["builtin"], ["env", "file"])
        self.assertEqual([e["name"] for e in slot["registered"]], ["file"])


if __name__ == "__main__":
    unittest.main()

"""`lnpl.toml` 통합 — `cli.py`의 우선순위 헬퍼(D6/D7)와 `lnpl config check`(D8),
issue #114.

`config.py` 자체의 로딩/병합/검증은 `test_config.py`가 고정한다. 여기서 고정하는
것은 두 가지뿐이다: (1) CLI 플래그 > ENV > `lnpl.toml` > 내장 기본값 우선순위가
`cli.py`의 헬퍼 함수 수준에서 정확히 그 순서로 동작한다는 것(순수 함수라 서버를
띄우지 않고도 고정할 수 있다), (2) 그 배선이 실제 `cmd_serve`/`cmd_config_check`
안에서도 끊기지 않는다는 것(파일 하나가 제공하는 endpoint가 실제로 `_open_endpoints`
까지 도달하는지는, 서버를 성공적으로 띄우면 테스트가 막혀버리므로, 두 번째
NetworkCall 타깃을 일부러 안 맵핑해 rc 2 메시지에 어느 이름이 남는지로 관측한다).
"""

import os
import tempfile
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
import io

from lnpl.cli import (
    _merge_endpoint_args, _resolve_backend,
    _resolve_log_format, _resolve_trace_exporter, main,
)
from lnpl.wsgi import _resolve_jwt_secret_env
from lnpl.config import ResolvedConfig

from tests.fixtures import SHORTEN_LNPL
from tests.test_wsgi import NUL_PATH_TAIL, call_with_deadline

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLAUDE_TMP = os.path.join(REPO, ".claude", "tmp")


def _ns(**kw):
    return types.SimpleNamespace(**kw)


class ResolveScalarTest(unittest.TestCase):
    """D6: CLI 플래그 > `lnpl.toml` > 내장 기본값 — 서버 없이 고정."""

    def test_backend_falls_back_to_file_then_builtin(self):
        empty = ResolvedConfig()
        self.assertEqual(_resolve_backend(_ns(backend=None), empty), "fake")
        from_file = ResolvedConfig(backend="sqlite:./app.db")
        self.assertEqual(_resolve_backend(_ns(backend=None), from_file),
                         "sqlite:./app.db")

    def test_backend_cli_flag_wins_over_file(self):
        cfg = ResolvedConfig(backend="sqlite:./app.db")
        self.assertEqual(_resolve_backend(_ns(backend="fake"), cfg), "fake")

    def test_log_format_falls_back_to_file_then_text(self):
        self.assertEqual(_resolve_log_format(_ns(log_format=None), ResolvedConfig()), "text")
        cfg = ResolvedConfig(log_format="json")
        self.assertEqual(_resolve_log_format(_ns(log_format=None), cfg), "json")

    def test_log_format_cli_flag_wins_over_file(self):
        cfg = ResolvedConfig(log_format="json")
        self.assertEqual(_resolve_log_format(_ns(log_format="text"), cfg), "text")

    def test_trace_exporter_falls_back_to_file_then_none(self):
        self.assertIsNone(_resolve_trace_exporter(_ns(trace_exporter=None), ResolvedConfig()))
        cfg = ResolvedConfig(trace_exporter="stderr-json")
        self.assertEqual(_resolve_trace_exporter(_ns(trace_exporter=None), cfg),
                         "stderr-json")

    def test_trace_exporter_cli_flag_wins_over_file(self):
        cfg = ResolvedConfig(trace_exporter="stderr-json")
        self.assertEqual(_resolve_trace_exporter(_ns(trace_exporter="otlp"), cfg), "otlp")

    def test_jwt_secret_env_falls_back_to_file_secrets_jwt(self):
        self.assertIsNone(_resolve_jwt_secret_env(_ns(jwt_secret_env=None), ResolvedConfig()))
        cfg = ResolvedConfig(secrets={"jwt": "MY_JWT_SECRET"})
        self.assertEqual(_resolve_jwt_secret_env(_ns(jwt_secret_env=None), cfg),
                         "MY_JWT_SECRET")

    def test_jwt_secret_env_cli_flag_wins_over_file(self):
        cfg = ResolvedConfig(secrets={"jwt": "FILE_SECRET"})
        self.assertEqual(
            _resolve_jwt_secret_env(_ns(jwt_secret_env="CLI_SECRET"), cfg),
            "CLI_SECRET")


class MergeEndpointArgsTest(unittest.TestCase):
    """D6/D7: `--endpoint` > `LNPL_ENDPOINT_<NAME>` > `lnpl.toml` endpoints."""

    def setUp(self):
        self._backup = dict(os.environ)
        self.addCleanup(self._restore)

    def _restore(self):
        os.environ.clear()
        os.environ.update(self._backup)

    def test_no_file_endpoints_leaves_cli_args_untouched(self):
        self.assertEqual(_merge_endpoint_args(["a=cli-a"], {}), ["a=cli-a"])
        self.assertEqual(_merge_endpoint_args(None, {}), [])

    def test_file_endpoint_is_appended_when_nothing_else_covers_it(self):
        merged = _merge_endpoint_args([], {"a": "file-a"})
        self.assertEqual(merged, ["a=file-a"])

    def test_cli_endpoint_wins_over_file(self):
        merged = _merge_endpoint_args(["a=cli-a"], {"a": "file-a"})
        self.assertEqual(merged, ["a=cli-a"])

    def test_env_endpoint_wins_over_file(self):
        os.environ["LNPL_ENDPOINT_A"] = "env-a"
        merged = _merge_endpoint_args([], {"a": "file-a"})
        self.assertEqual(merged, [])

    def test_mixed_targets_each_resolve_independently(self):
        merged = _merge_endpoint_args(["a=cli-a"], {"a": "file-a", "b": "file-b"})
        self.assertEqual(merged, ["a=cli-a", "b=file-b"])


class _ConfigCliTestCase(unittest.TestCase):
    def setUp(self):
        os.makedirs(CLAUDE_TMP, exist_ok=True)
        box = tempfile.TemporaryDirectory(dir=CLAUDE_TMP)
        self.addCleanup(box.cleanup)
        self.dir = box.name
        self._env_backup = dict(os.environ)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        os.environ.clear()
        os.environ.update(self._env_backup)

    def write(self, name, content):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(argv)
        return rc, out.getvalue(), err.getvalue()


TWO_TARGET_SOURCE = """
entity Order
    field
        id UUID
service Checkout
workflow Pay
    call FileMapped as a
    call StillUnmapped as b
"""


class ServeUsesConfigFileTest(_ConfigCliTestCase):
    """`cmd_serve`가 실제로 `load_config`/`_merge_endpoint_args`를 거쳐
    `_open_endpoints`까지 파일 값을 전달하는지 — 성공 경로는 소켓을 잡고
    블로킹하므로 관측할 수 없어, 두 번째 타깃을 일부러 안 맵핑해 rc 2
    메시지에 어느 이름이 남는지로 배선을 증명한다."""

    def test_file_endpoint_resolves_leaving_only_the_unmapped_target_in_error(self):
        source = self.write("mod.lnpl", TWO_TARGET_SOURCE)
        toml = self.write("lnpl.toml", """
[default.endpoints]
FileMapped = "http://127.0.0.1:1/"
""")
        rc, _out, err = self.run_cli(
            ["serve", source, "--port", "0", "--network", "http",
             "--config", toml])
        self.assertEqual(rc, 2)
        self.assertIn("network target 'StillUnmapped' has no --endpoint mapping", err)
        self.assertNotIn("network target 'FileMapped' has no --endpoint mapping", err)

    def test_without_the_file_both_targets_are_unmapped(self):
        source = self.write("mod.lnpl", TWO_TARGET_SOURCE)
        rc, _out, err = self.run_cli(
            ["serve", source, "--port", "0", "--network", "http"])
        self.assertEqual(rc, 2)
        self.assertIn("FileMapped", err)
        self.assertIn("StillUnmapped", err)

    def test_profile_flag_selects_the_overlay_that_maps_the_target(self):
        source = self.write("mod.lnpl", TWO_TARGET_SOURCE)
        toml = self.write("lnpl.toml", """
[staging.endpoints]
FileMapped = "http://127.0.0.1:1/"
""")
        rc_no_profile, _out, err_no_profile = self.run_cli(
            ["serve", source, "--port", "0", "--network", "http",
             "--config", toml])
        self.assertEqual(rc_no_profile, 2)
        self.assertIn("network target 'FileMapped' has no --endpoint mapping",
                      err_no_profile)

        rc_profile, _out, err_profile = self.run_cli(
            ["serve", source, "--port", "0", "--network", "http",
             "--config", toml, "--profile", "staging"])
        self.assertEqual(rc_profile, 2)
        self.assertNotIn("network target 'FileMapped' has no --endpoint mapping",
                         err_profile)
        self.assertIn("network target 'StillUnmapped' has no --endpoint mapping",
                      err_profile)

    def test_explicit_missing_config_path_is_rejected_before_binding(self):
        source = self.write("mod.lnpl", TWO_TARGET_SOURCE)
        missing = os.path.join(self.dir, "nope.toml")
        rc, out, err = self.run_cli(
            ["serve", source, "--port", "0", "--config", missing])
        self.assertEqual(rc, 2)
        self.assertIn("no such file", err)
        self.assertNotIn("serving", out)


ONE_TARGET_SOURCE = """
entity Order
    field
        id UUID
service Checkout
workflow Pay
    call FileMapped as a
"""


class ServeSuccessPathUsesConfigTest(_ConfigCliTestCase):
    """The same claim `ServeUsesConfigFileTest` proves indirectly (via which
    name survives into an rc 2 error), proven directly on the actual success
    path — `lnpl.cli.serve` mocked out so `cmd_serve` runs to completion
    (backend probe, `_open_endpoints`, `_open_network`, `_open_log_format`,
    `_open_trace_exporter`, `_token_provider`) without binding a real socket,
    the same technique `test_serve.py::CmdServeTest` already uses for
    `--host`/`--port`."""

    def _mocked_serve(self, argv):
        from unittest import mock
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 0)
        server.serve_forever.side_effect = KeyboardInterrupt
        with mock.patch("lnpl.cli.serve", return_value=server) as factory:
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = main(argv)
        return rc, out.getvalue(), err.getvalue(), factory

    def test_every_resolved_value_reaches_serve_when_only_the_file_provides_it(self):
        from lnpl.wsgi import StderrJsonExporter

        source = self.write("mod.lnpl", ONE_TARGET_SOURCE)
        db_path = os.path.join(self.dir, "app.db")
        os.environ["LNPL_T114_SERVE_JWT"] = "a" * 32
        toml = self.write("lnpl.toml", """
[default]
backend = "sqlite:%s"
log_format = "json"
trace_exporter = "stderr-json"

[default.endpoints]
FileMapped = "http://127.0.0.1:1/"

[default.secrets]
jwt = "LNPL_T114_SERVE_JWT"
""" % db_path)

        rc, out, err, factory = self._mocked_serve(
            ["serve", source, "--network", "http", "--config", toml])

        self.assertEqual(rc, 0, err)
        self.assertIn("serving", out)
        factory.assert_called_once()
        kwargs = factory.call_args.kwargs

        self.assertEqual(kwargs["network"]._endpoints, {"FileMapped": "http://127.0.0.1:1/"})
        self.assertEqual(kwargs["jwt_secret_env"], "LNPL_T114_SERVE_JWT")
        self.assertEqual(kwargs["log_format"], "json")
        self.assertIsInstance(kwargs["exporter"], StderrJsonExporter)
        self.assertIsNotNone(kwargs["repository_factory"],
                             "backend='fake' would leave this None — the "
                             "file's sqlite backend must produce a factory")
        self.assertIsNotNone(kwargs["token_provider"],
                             "the file's [*.secrets].jwt must build a real "
                             "verifier, not leave the token presence-checked")

    def test_cli_flags_still_win_over_the_file(self):
        source = self.write("mod.lnpl", ONE_TARGET_SOURCE)
        os.environ["LNPL_T114_SERVE_JWT"] = "a" * 32
        os.environ["LNPL_T114_CLI_JWT"] = "b" * 32
        toml = self.write("lnpl.toml", """
[default]
log_format = "json"

[default.endpoints]
FileMapped = "http://127.0.0.1:1/"

[default.secrets]
jwt = "LNPL_T114_SERVE_JWT"
""")

        rc, _out, err, factory = self._mocked_serve(
            ["serve", source, "--network", "http", "--config", toml,
             "--log-format", "text",
             "--endpoint", "FileMapped=http://127.0.0.1:2/",
             "--jwt-secret-env", "LNPL_T114_CLI_JWT"])

        self.assertEqual(rc, 0, err)
        kwargs = factory.call_args.kwargs
        self.assertEqual(kwargs["network"]._endpoints, {"FileMapped": "http://127.0.0.1:2/"})
        self.assertEqual(kwargs["jwt_secret_env"], "LNPL_T114_CLI_JWT")
        self.assertEqual(kwargs["log_format"], "text")


CALL_SOURCE = """
entity Order
    field
        id UUID
service Checkout
workflow Pay
    call PaymentGateway as p
"""


class ConfigCheckTest(_ConfigCliTestCase):
    """D8: endpoint 완결성(a) / secrets ENV 존재(b) / jwt 매핑(c) — 문제 전부를
    한 번에 열거하는 것까지 포함."""

    # ---- (a) endpoint completeness ----

    def test_unmapped_network_target_is_reported(self):
        source = self.write("mod.lnpl", CALL_SOURCE)
        rc, out, err = self.run_cli(["config", "check", source])
        self.assertEqual(rc, 2)
        self.assertIn("PaymentGateway", err)
        self.assertNotIn("ok", out)

    def test_endpoint_mapped_via_env_passes(self):
        source = self.write("mod.lnpl", CALL_SOURCE)
        os.environ["LNPL_ENDPOINT_PAYMENTGATEWAY"] = "http://127.0.0.1:1/"
        rc, out, _err = self.run_cli(["config", "check", source])
        self.assertEqual(rc, 0)
        self.assertIn("ok", out)

    def test_endpoint_mapped_via_lnpl_toml_passes(self):
        source = self.write("mod.lnpl", CALL_SOURCE)
        toml = self.write("lnpl.toml", """
[default.endpoints]
PaymentGateway = "http://127.0.0.1:1/"
""")
        rc, out, _err = self.run_cli(
            ["config", "check", source, "--config", toml])
        self.assertEqual(rc, 0)
        self.assertIn("ok", out)

    # ---- (b) secrets ENV presence ----

    def test_secret_env_not_set_is_reported(self):
        source = self.write("mod.lnpl", CALL_SOURCE)
        os.environ["LNPL_ENDPOINT_PAYMENTGATEWAY"] = "http://127.0.0.1:1/"
        os.environ.pop("LNPL_T114_MISSING_SECRET", None)
        toml = self.write("lnpl.toml", """
[default.secrets]
db = "LNPL_T114_MISSING_SECRET"
""")
        rc, _out, err = self.run_cli(
            ["config", "check", source, "--config", toml])
        self.assertEqual(rc, 2)
        self.assertIn("LNPL_T114_MISSING_SECRET", err)

    def test_secret_env_set_passes(self):
        source = self.write("mod.lnpl", CALL_SOURCE)
        os.environ["LNPL_ENDPOINT_PAYMENTGATEWAY"] = "http://127.0.0.1:1/"
        os.environ["LNPL_T114_PRESENT_SECRET"] = "shh"
        toml = self.write("lnpl.toml", """
[default.secrets]
db = "LNPL_T114_PRESENT_SECRET"
""")
        rc, out, _err = self.run_cli(
            ["config", "check", source, "--config", toml])
        self.assertEqual(rc, 0)
        self.assertIn("ok", out)

    # ---- (c) jwt mapping ----

    def test_declared_security_jwt_with_no_mapping_is_reported(self):
        rc, _out, err = self.run_cli(["config", "check", SHORTEN_LNPL])
        self.assertEqual(rc, 2)
        self.assertIn("security jwt", err)

    def test_declared_security_jwt_with_mapping_passes(self):
        os.environ["LNPL_T114_JWT_SECRET"] = "shh"
        toml = self.write("lnpl.toml", """
[default.secrets]
jwt = "LNPL_T114_JWT_SECRET"
""")
        rc, out, _err = self.run_cli(
            ["config", "check", SHORTEN_LNPL, "--config", toml])
        self.assertEqual(rc, 0)
        self.assertIn("ok", out)

    # ---- every problem is enumerated, not just the first ----

    def test_multiple_problems_are_all_listed(self):
        toml = self.write("lnpl.toml", """
[default.secrets]
db = "LNPL_T114_ANOTHER_MISSING_SECRET"
""")
        os.environ.pop("LNPL_T114_ANOTHER_MISSING_SECRET", None)
        rc, _out, err = self.run_cli(
            ["config", "check", SHORTEN_LNPL, "--config", toml])
        self.assertEqual(rc, 2)
        self.assertIn("LNPL_T114_ANOTHER_MISSING_SECRET", err)
        self.assertIn("security jwt", err)

    def test_bad_config_file_itself_is_reported_and_not_a_traceback(self):
        source = self.write("mod.lnpl", CALL_SOURCE)
        toml = self.write("lnpl.toml", '[default.secrets]\ndb = "not an env name"\n')
        rc, _out, err = self.run_cli(
            ["config", "check", source, "--config", toml])
        self.assertEqual(rc, 2)
        self.assertIn("error:", err)


OPEN_SOURCE = """entity Report
    field
        id UUID

service Rollup

workflow GetReport
    read report
"""


class ServeErrorCharacterizationTest(_ConfigCliTestCase):
    """Issue #187 piece B: `lnpl serve`'s stderr text and exit code for five
    error paths, pinned byte-for-byte BEFORE the resolver move into wsgi.py
    and re-checked after it — `cmd_serve` must not change observably."""

    def _serve(self, *extra):
        from unittest import mock
        source = self.write("mod.lnpl", OPEN_SOURCE)
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 0)
        server.serve_forever.side_effect = KeyboardInterrupt
        with mock.patch("lnpl.cli.serve", return_value=server):
            return self.run_cli(["serve", source] + list(extra))

    def test_char_missing_secret_env_text_unchanged(self):
        os.environ.pop("LNPL_TEST_CHAR_MISSING", None)
        rc, _out, err = self._serve("--jwt-secret-env", "LNPL_TEST_CHAR_MISSING")
        self.assertEqual(rc, 2)
        self.assertEqual(err, "error: LNPL_TEST_CHAR_MISSING is not set in the environment\n")

    def test_char_short_secret_text_unchanged(self):
        os.environ["LNPL_TEST_CHAR_SHORT"] = "tooshort"
        rc, _out, err = self._serve("--jwt-secret-env", "LNPL_TEST_CHAR_SHORT")
        self.assertEqual(rc, 2)
        self.assertEqual(
            err,
            "error: the JWT signing secret must be at least 32 bytes, got 8 "
            "(from LNPL_TEST_CHAR_SHORT)\n")

    def test_char_unknown_token_provider_text_unchanged(self):
        rc, _out, err = self._serve("--token-provider", "bogus-provider")
        self.assertEqual(rc, 2)
        self.assertEqual(
            err,
            "error: unknown token provider 'bogus-provider' "
            "(built-in: hmac; registered entry-points: none)\n")

    def test_char_unknown_cache_text_unchanged(self):
        rc, _out, err = self._serve("--cache", "bogus-cache")
        self.assertEqual(rc, 2)
        self.assertEqual(
            err,
            "error: unknown cache 'bogus-cache' "
            "(built-in: fake; registered entry-points: none)\n")

    def test_char_unknown_network_text_unchanged(self):
        rc, _out, err = self._serve("--network", "bogus-network")
        self.assertEqual(rc, 2)
        self.assertEqual(
            err,
            "error: unknown network 'bogus-network' "
            "(built-in: fake, http; registered entry-points: none)\n")

    def test_normal_hmac_shadow_reported_as_provider_error_via_cli(self):
        """`cli._token_provider` is untouched by piece B: an `lnpl.tokens`
        entry-point named "hmac" is still refused as a shadow collision
        (not a secret error) when the secret itself is long enough."""
        from importlib import metadata as importlib_metadata
        from unittest import mock
        shadow = importlib_metadata.EntryPoint(
            name="hmac", value="tests.token_spi_fixture:make_demo_token_provider",
            group="lnpl.tokens")

        def entry_points_for(group=None, **_kwargs):
            return [shadow] if group == "lnpl.tokens" else []

        os.environ["LNPL_TEST_CHAR_SHADOW"] = "s" * 32
        with mock.patch.object(importlib_metadata, "entry_points", entry_points_for):
            rc, _out, err = self._serve("--jwt-secret-env", "LNPL_TEST_CHAR_SHADOW")
        self.assertEqual(rc, 2)
        self.assertEqual(
            err,
            "error: entry-point 'hmac' (registered via "
            "'tests.token_spi_fixture:make_demo_token_provider') attempts to "
            "shadow the built-in token provider 'hmac'; built-in names are "
            "reserved (lnpl.tokens SPI, docs/backends.md) (from "
            "LNPL_TEST_CHAR_SHADOW)\n")


# --- issue #192 piece A: `lnpl serve --jwt-secret-file` and the source
# precedence ----------------------------------------------------------------

JWT_SOURCE = """entity Report
    field
        id UUID

service Rollup
    security
        jwt

workflow GetReport
    read report
"""
JWT_AUDIENCE = "rollup"
FILE_SECRET = b"FAKE-SECRET-192-file-source-aaaaaaaaaaaa"     # 40 bytes
OTHER_SECRET = b"FAKE-SECRET-192-other-secret-bbbbbbbbbbb"    # 40 bytes


class _ServeSecretTestCase(_ConfigCliTestCase):
    """`lnpl.cli.serve` mocked, so `cmd_serve` runs its whole resolution
    and the built token provider is read from the call (the
    `ServeSuccessPathUsesConfigTest` technique)."""

    def _mocked_serve(self, *extra):
        from unittest import mock
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 0)
        server.serve_forever.side_effect = KeyboardInterrupt
        source = self.write("mod.lnpl", JWT_SOURCE)
        with mock.patch("lnpl.cli.serve", return_value=server) as factory:
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = main(["serve", source] + list(extra))
        return rc, out.getvalue(), err.getvalue(), factory

    def secret_file(self, data, name="jwt-secret"):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    @staticmethod
    def token(secret):
        from lnpl.drivers import HmacTokenProvider
        return HmacTokenProvider(secret).issue("u", JWT_AUDIENCE)

    def assert_verifies_only(self, provider, good, bad):
        from lnpl.drivers import TokenError
        self.assertIsNotNone(provider)
        provider.verify(self.token(good), JWT_AUDIENCE)
        with self.assertRaises(TokenError):
            provider.verify(self.token(bad), JWT_AUDIENCE)

    def assert_refused(self, rc, out, err, factory, path=None):
        """rc 2, serve never called, exactly one `error:` line (the compile
        diagnostics `cmd_serve` prints first are `info:` lines), no file
        byte and no path anywhere in the output. Returns that line."""
        self.assertEqual(rc, 2)
        factory.assert_not_called()
        errors = [line for line in err.splitlines() if line.startswith("error:")]
        self.assertEqual(len(errors), 1, err)
        self.assertNotIn("FAKE-SECRET-192", out + err)
        if path is not None:
            self.assertNotIn(path, out + err)
        return errors[0]


class ServeSecretFileTest(_ServeSecretTestCase):
    """D2/D3/D4/D8: `--jwt-secret-file PATH` builds a verifying provider;
    every failure is one `error:` line naming the flag, never the path or
    a file byte."""

    def test_normal_file_secret_verifies_a_token(self):
        rc, out, err, factory = self._mocked_serve(
            "--jwt-secret-file", self.secret_file(FILE_SECRET))
        self.assertEqual(rc, 0, err)
        self.assertIn("jwt=verified", out)
        kwargs = factory.call_args.kwargs
        self.assertIsNone(kwargs["jwt_secret_env"])
        self.assert_verifies_only(kwargs["token_provider"], FILE_SECRET, OTHER_SECRET)

    def test_normal_config_file_form_used_when_no_flag(self):
        toml = self.write("lnpl.toml", '[default.secrets]\njwt = { file = "%s" }\n'
                          % self.secret_file(FILE_SECRET))
        rc, _out, err, factory = self._mocked_serve("--config", toml)
        self.assertEqual(rc, 0, err)
        self.assertIsNone(factory.call_args.kwargs["jwt_secret_env"])
        self.assert_verifies_only(factory.call_args.kwargs["token_provider"],
                                  FILE_SECRET, OTHER_SECRET)

    def test_error_missing_file_rc2_names_role(self):
        path = os.path.join(self.dir, "absent")
        rc, out, err, factory = self._mocked_serve("--jwt-secret-file", path)
        line = self.assert_refused(rc, out, err, factory, path)
        self.assertEqual(line, "error: --jwt-secret-file names a file that does not exist")

    def test_error_config_missing_file_names_the_config_role(self):
        path = os.path.join(self.dir, "absent")
        toml = self.write("lnpl.toml", '[default.secrets]\njwt = { file = "%s" }\n' % path)
        rc, out, err, factory = self._mocked_serve("--config", toml)
        line = self.assert_refused(rc, out, err, factory, path)
        self.assertEqual(line, "error: lnpl.toml secrets.jwt.file names a file that does not exist")

    def test_error_empty_file(self):
        path = self.secret_file(b"")
        rc, out, err, factory = self._mocked_serve("--jwt-secret-file", path)
        line = self.assert_refused(rc, out, err, factory, path)
        self.assertEqual(line, "error: --jwt-secret-file names an empty file")

    def test_error_short_file_states_minimum(self):
        path = self.secret_file(b"FAKE-SEC")
        rc, out, err, factory = self._mocked_serve("--jwt-secret-file", path)
        self.assert_refused(rc, out, err, factory, path)
        self.assertIn("at least 32 bytes, got 8 (from --jwt-secret-file)", err)
        self.assertNotIn("FAKE-SEC", err)

    def test_error_directory_unreadable(self):
        rc, out, err, factory = self._mocked_serve("--jwt-secret-file", self.dir)
        line = self.assert_refused(rc, out, err, factory, self.dir)
        self.assertEqual(line, "error: --jwt-secret-file names a file that cannot be read")

    def test_error_oversize_file(self):
        path = self.secret_file(b"k" * 65537)
        rc, out, err, factory = self._mocked_serve("--jwt-secret-file", path)
        line = self.assert_refused(rc, out, err, factory, path)
        self.assertEqual(line, "error: --jwt-secret-file names a file larger than 65536 bytes")

    def test_error_fifo_flag_is_refused_without_blocking(self):
        fifo = os.path.join(self.dir, "jwt-fifo")
        os.mkfifo(fifo)
        rc, out, err, factory = call_with_deadline(
            self, lambda: self._mocked_serve("--jwt-secret-file", fifo), fifo)
        line = self.assert_refused(rc, out, err, factory, fifo)
        self.assertEqual(line, "error: --jwt-secret-file names a file that cannot be read")

    def test_error_nul_in_config_path_is_a_config_error(self):
        toml = self.write("lnpl.toml", '[default.secrets]\njwt = { file = "/run/%s" }\n'
                          % NUL_PATH_TAIL.replace("\x00", "\\u0000"))
        rc, out, err, factory = self._mocked_serve("--config", toml)
        line = self.assert_refused(rc, out, err, factory)
        self.assertEqual(
            line, "error: lnpl.toml secrets.jwt.file names a file that cannot be read")
        self.assertNotIn("Traceback", err)

    def test_error_relative_path_is_refused(self):
        rc, out, err, factory = self._mocked_serve("--jwt-secret-file", "rel/secret")
        line = self.assert_refused(rc, out, err, factory, "rel/secret")
        self.assertEqual(line, "error: --jwt-secret-file must be an absolute path")

    def test_boundary_empty_flag_is_not_absolute(self):
        rc, out, err, factory = self._mocked_serve("--jwt-secret-file", "")
        line = self.assert_refused(rc, out, err, factory)
        self.assertEqual(line, "error: --jwt-secret-file must be an absolute path")

    def test_boundary_trailing_lf_is_stripped(self):
        rc, _out, err, factory = self._mocked_serve(
            "--jwt-secret-file", self.secret_file(FILE_SECRET + b"\n"))
        self.assertEqual(rc, 0, err)
        self.assert_verifies_only(factory.call_args.kwargs["token_provider"],
                                  FILE_SECRET, FILE_SECRET + b"\n")

    def test_boundary_trailing_crlf_is_stripped(self):
        rc, _out, err, factory = self._mocked_serve(
            "--jwt-secret-file", self.secret_file(FILE_SECRET + b"\r\n"))
        self.assertEqual(rc, 0, err)
        self.assert_verifies_only(factory.call_args.kwargs["token_provider"],
                                  FILE_SECRET, FILE_SECRET + b"\r\n")

    def test_boundary_only_one_newline_is_stripped(self):
        rc, _out, err, factory = self._mocked_serve(
            "--jwt-secret-file", self.secret_file(FILE_SECRET + b"\n\n"))
        self.assertEqual(rc, 0, err)
        self.assert_verifies_only(factory.call_args.kwargs["token_provider"],
                                  FILE_SECRET + b"\n", FILE_SECRET)

    def test_boundary_non_hmac_token_provider_leaves_the_file_unread(self):
        from importlib import metadata as importlib_metadata
        from unittest import mock
        from tests.token_spi_fixture import DemoTokenProvider
        ext = importlib_metadata.EntryPoint(
            name="extprov", value="tests.token_spi_fixture:make_demo_token_provider",
            group="lnpl.tokens")

        def entry_points_for(group=None, **_kwargs):
            return [ext] if group == "lnpl.tokens" else []

        with mock.patch.object(importlib_metadata, "entry_points", entry_points_for):
            rc, _out, err, factory = self._mocked_serve(
                "--jwt-secret-file", os.path.join(self.dir, "absent"),
                "--token-provider", "extprov")
        self.assertEqual(rc, 0, err)
        self.assertIsInstance(factory.call_args.kwargs["token_provider"], DemoTokenProvider)


class ServeSecretPrecedenceTest(_ServeSecretTestCase):
    """D6: two explicit sources are refused; one explicit source beats
    lnpl.toml whatever the config entry's form."""

    def test_error_both_flags_refused(self):
        path = self.secret_file(FILE_SECRET)
        rc, out, err, factory = self._mocked_serve(
            "--jwt-secret-env", "LNPL_T192_ANY", "--jwt-secret-file", path)
        line = self.assert_refused(rc, out, err, factory, path)
        self.assertEqual(line, "error: --jwt-secret-env and --jwt-secret-file both "
                               "name the JWT signing secret — give exactly one")

    def test_boundary_empty_env_flag_still_counts_as_given(self):
        rc, out, err, factory = self._mocked_serve(
            "--jwt-secret-env", "", "--jwt-secret-file", self.secret_file(FILE_SECRET))
        self.assert_refused(rc, out, err, factory)
        self.assertIn("give exactly one", err)

    def test_normal_file_flag_beats_config_name(self):
        os.environ["LNPL_T192_CFG_SECRET"] = OTHER_SECRET.decode()
        toml = self.write("lnpl.toml", '[default.secrets]\njwt = "LNPL_T192_CFG_SECRET"\n')
        rc, _out, err, factory = self._mocked_serve(
            "--config", toml, "--jwt-secret-file", self.secret_file(FILE_SECRET))
        self.assertEqual(rc, 0, err)
        self.assertIsNone(factory.call_args.kwargs["jwt_secret_env"])
        self.assert_verifies_only(factory.call_args.kwargs["token_provider"],
                                  FILE_SECRET, OTHER_SECRET)

    def test_normal_env_flag_beats_config_file_form(self):
        os.environ["LNPL_T192_CLI_SECRET"] = OTHER_SECRET.decode()
        absent = os.path.join(self.dir, "absent")
        toml = self.write("lnpl.toml", '[default.secrets]\njwt = { file = "%s" }\n' % absent)
        rc, _out, err, factory = self._mocked_serve(
            "--config", toml, "--jwt-secret-env", "LNPL_T192_CLI_SECRET")
        self.assertEqual(rc, 0, err)
        self.assertEqual(factory.call_args.kwargs["jwt_secret_env"], "LNPL_T192_CLI_SECRET")
        self.assert_verifies_only(factory.call_args.kwargs["token_provider"],
                                  OTHER_SECRET, FILE_SECRET)


class ConfigCheckSecretFileTest(_ServeSecretTestCase):
    """D18: `lnpl config check` reads a `{ file }` secrets entry through the
    same `_read_secret_file` (role `lnpl.toml secrets.<key>.file`), lists
    every problem at once, and prints no file byte."""

    def _check(self, secrets_toml):
        source = self.write("mod.lnpl", JWT_SOURCE)
        toml = self.write("lnpl.toml", "[default.secrets]\n" + secrets_toml)
        rc, out, err = self.run_cli(["config", "check", source, "--config", toml])
        self.assertNotIn("FAKE-SECRET-192", out + err)
        self.assertNotIn(self.dir, out + err)
        return rc, out, err

    def test_normal_good_file_prints_ok(self):
        rc, out, err = self._check('jwt = { file = "%s" }\n' % self.secret_file(FILE_SECRET))
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "ok\n")

    def test_error_missing_file_and_missing_env_both_listed(self):
        os.environ.pop("LNPL_T192_UNSET", None)
        rc, out, err = self._check('jwt = { file = "%s" }\nother = "LNPL_T192_UNSET"\n'
                                   % os.path.join(self.dir, "absent"))
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")
        self.assertEqual(err.splitlines(), [
            "error: lnpl.toml secrets.jwt.file names a file that does not exist",
            "error: lnpl.toml secrets.other names LNPL_T192_UNSET, which is not "
            "set in the environment",
        ])

    def test_error_short_jwt_file(self):
        rc, _out, err = self._check('jwt = { file = "%s" }\n' % self.secret_file(b"FAKE-SEC"))
        self.assertEqual(rc, 2)
        self.assertEqual(err, "error: the JWT signing secret must be at least 32 bytes, "
                              "got 8 (from lnpl.toml secrets.jwt.file)\n")
        self.assertNotIn("FAKE-SEC", err)

    def test_boundary_short_file_under_another_key_is_ok(self):
        rc, out, err = self._check('jwt = { file = "%s" }\nother = { file = "%s" }\n'
                                   % (self.secret_file(FILE_SECRET),
                                      self.secret_file(b"FAKE-SEC", "other")))
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "ok\n")

    def test_boundary_exactly_32_byte_jwt_file_is_ok(self):
        rc, out, err = self._check('jwt = { file = "%s" }\n'
                                   % self.secret_file(b"k" * 32 + b"\n"))
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "ok\n")

    def test_error_empty_file(self):
        rc, _out, err = self._check('jwt = { file = "%s" }\n' % self.secret_file(b"\n"))
        self.assertEqual(rc, 2)
        self.assertEqual(err, "error: lnpl.toml secrets.jwt.file names an empty file\n")

    def test_error_nul_in_path_is_listed_not_raised(self):
        rc, out, err = self._check('jwt = { file = "%s" }\nother = { file = "/run/%s" }\n'
                                   % (self.secret_file(FILE_SECRET),
                                      NUL_PATH_TAIL.replace("\x00", "\\u0000")))
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")
        self.assertEqual(err, "error: lnpl.toml secrets.other.file names a file that "
                              "cannot be read\n")

    def test_error_fifo_is_listed_without_blocking(self):
        fifo = os.path.join(self.dir, "jwt-fifo")
        os.mkfifo(fifo)
        rc, _out, err = call_with_deadline(
            self, lambda: self._check('jwt = { file = "%s" }\n' % fifo), fifo)
        self.assertEqual(rc, 2)
        self.assertEqual(err, "error: lnpl.toml secrets.jwt.file names a file that "
                              "cannot be read\n")

    def test_error_unreadable_file_under_another_key(self):
        rc, _out, err = self._check('jwt = { file = "%s" }\nother = { file = "%s" }\n'
                                    % (self.secret_file(FILE_SECRET), self.dir))
        self.assertEqual(rc, 2)
        self.assertEqual(err, "error: lnpl.toml secrets.other.file names a file that "
                              "cannot be read\n")


SECRETS_GROUP = "lnpl.secrets"


def _secrets_registered(*named_factories):
    """Patch entry-point discovery group-aware: `lnpl.secrets` returns the
    given (name, fixture factory) registrations, every other group none."""
    from importlib import metadata as importlib_metadata
    from unittest import mock

    from lnpl import drivers as drivers_module
    eps = [importlib_metadata.EntryPoint(
        name=name, value="tests.secret_spi_fixture:%s" % factory,
        group=SECRETS_GROUP) for name, factory in named_factories]

    def entry_points(group=None, **_kwargs):
        return [ep for ep in eps if ep.group == group]

    return mock.patch.object(drivers_module.importlib_metadata,
                             "entry_points", entry_points)


DEMO_SECRET = ("demo", "make_demo_secret_provider")


class _SecretProviderFixtureCase(_ServeSecretTestCase):
    def setUp(self):
        super().setUp()
        from tests import secret_spi_fixture
        self.fixture = secret_spi_fixture
        secret_spi_fixture.INSTANCES.clear()

    def provider_toml(self, provider, key="jwt", extra=""):
        return self.write(
            "lnpl.toml", '[default.secrets]\njwt = { provider = "%s", key = "%s" }\n%s'
            % (provider, key, extra))


class ServeSecretProviderTest(_SecretProviderFixtureCase):
    """issue #192 D17 on the serve path: lnpl.toml's provider form builds a
    RotatingHmacTokenProvider, provider failures are one value-free
    `error:` line with rc 2, and the provider is closed at shutdown."""

    def test_normal_provider_secret_verifies_and_is_closed_at_shutdown(self):
        from lnpl.drivers import RotatingHmacTokenProvider
        from tests.secret_spi_fixture import DEMO_SECRET_K0
        with _secrets_registered(DEMO_SECRET):
            rc, out, err, factory = self._mocked_serve(
                "--config", self.provider_toml("demo"))
        self.assertEqual(rc, 0, err)
        self.assertIn("jwt=verified", out)
        kwargs = factory.call_args.kwargs
        self.assertIsNone(kwargs["jwt_secret_env"])
        self.assertIsInstance(kwargs["token_provider"], RotatingHmacTokenProvider)
        self.assert_verifies_only(kwargs["token_provider"], DEMO_SECRET_K0,
                                  OTHER_SECRET)
        self.assertEqual(self.fixture.INSTANCES[-1].close_calls, 1)

    def test_error_unregistered_provider_rc2(self):
        with _secrets_registered():
            rc, out, err, factory = self._mocked_serve(
                "--config", self.provider_toml("nope"))
        line = self.assert_refused(rc, out, err, factory)
        self.assertEqual(
            line, "error: lnpl.toml secrets.jwt: unknown secret provider 'nope' "
                  "(built-in: env, file; registered entry-points: none)")

    def test_error_shadowed_builtin_rc2(self):
        with _secrets_registered(("file", "make_demo_secret_provider")):
            rc, out, err, factory = self._mocked_serve(
                "--config", self.provider_toml("file"))
        line = self.assert_refused(rc, out, err, factory)
        self.assertIn("attempts to shadow the built-in secret source 'file'", line)
        self.assertEqual(self.fixture.INSTANCES, [])

    def test_error_raising_provider_rc2_value_free(self):
        with _secrets_registered(("raising", "make_raising_secret_provider")):
            rc, out, err, factory = self._mocked_serve(
                "--config", self.provider_toml("raising"))
        line = self.assert_refused(rc, out, err, factory)
        self.assertEqual(
            line, "error: the secret provider failed to return the secret "
                  "(from lnpl.toml secrets.jwt provider 'raising')")
        self.assertEqual(self.fixture.INSTANCES[-1].close_calls, 1)

    def test_boundary_flag_file_beats_config_provider(self):
        from lnpl.drivers import HmacTokenProvider
        with _secrets_registered(DEMO_SECRET):
            rc, _out, err, factory = self._mocked_serve(
                "--config", self.provider_toml("demo"),
                "--jwt-secret-file", self.secret_file(FILE_SECRET))
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.fixture.INSTANCES, [])
        provider = factory.call_args.kwargs["token_provider"]
        self.assertIs(type(provider), HmacTokenProvider)
        self.assert_verifies_only(provider, FILE_SECRET, OTHER_SECRET)


def make_short_previous_secret_provider():
    """A provider whose previous `jwt` value is too short (9 bytes)."""
    from tests import secret_spi_fixture
    provider = secret_spi_fixture.DemoSecretProvider(
        {"jwt": secret_spi_fixture.DEMO_SECRET_K0})
    provider.previous["jwt"] = b"FAKE-SECR"
    secret_spi_fixture.INSTANCES.append(provider)
    return provider


def make_str_secret_provider():
    """A provider that breaks the bytes-only contract (returns a str)."""
    from tests import secret_spi_fixture
    provider = secret_spi_fixture.DemoSecretProvider(
        {"jwt": "FAKE-SECRET-192-a-str-not-bytes-aaaaaaaaa"})
    secret_spi_fixture.INSTANCES.append(provider)
    return provider


class ConfigCheckSecretProviderTest(_SecretProviderFixtureCase):
    """issue #192 D18: `lnpl config check` opens, reads and closes every
    `{ provider, key }` entry, lists each problem by name only, and checks
    the length only for `jwt`."""

    def _check(self, toml, *registrations):
        source = self.write("mod.lnpl", JWT_SOURCE)
        with _secrets_registered(*registrations):
            rc, out, err = self.run_cli(["config", "check", source, "--config", toml])
        self.assertNotIn("FAKE-SECRET-192", out + err)
        return rc, out, err

    def test_normal_good_provider_prints_ok(self):
        rc, out, err = self._check(self.provider_toml("demo"), DEMO_SECRET)
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "ok\n")
        self.assertEqual(self.fixture.INSTANCES[-1].get_calls, 1)
        self.assertEqual(self.fixture.INSTANCES[-1].close_calls, 1)

    def test_error_unregistered_listed_with_other_problems(self):
        os.environ.pop("LNPL_T192_UNSET", None)
        rc, out, err = self._check(
            self.provider_toml("nope", extra='other = "LNPL_T192_UNSET"\n'))
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")
        self.assertEqual(err.splitlines(), [
            "error: lnpl.toml secrets.jwt: unknown secret provider 'nope' "
            "(built-in: env, file; registered entry-points: none)",
            "error: lnpl.toml secrets.other names LNPL_T192_UNSET, which is not "
            "set in the environment",
        ])

    def test_error_raising_provider_value_free(self):
        rc, _out, err = self._check(
            self.provider_toml("raising"),
            ("raising", "make_raising_secret_provider"))
        self.assertEqual(rc, 2)
        self.assertEqual(
            err, "error: the secret provider failed to return the secret "
                 "(from lnpl.toml secrets.jwt provider 'raising')\n")
        self.assertEqual(self.fixture.INSTANCES[-1].close_calls, 1)

    def test_error_short_jwt_value(self):
        rc, _out, err = self._check(
            self.provider_toml("short"), ("short", "make_short_secret_provider"))
        self.assertEqual(rc, 2)
        self.assertEqual(
            err, "error: the JWT signing secret must be at least 32 bytes, got 21 "
                 "(from lnpl.toml secrets.jwt provider 'short')\n")
        self.assertEqual(self.fixture.INSTANCES[-1].close_calls, 1)

    def _local(self, name, factory):
        """Register a factory defined in this module (not the fixture)."""
        from importlib import metadata as importlib_metadata
        from unittest import mock

        from lnpl import drivers as drivers_module
        ep = importlib_metadata.EntryPoint(
            name=name, value="%s:%s" % (__name__, factory), group=SECRETS_GROUP)
        return mock.patch.object(
            drivers_module.importlib_metadata, "entry_points",
            lambda group=None, **_kw: [ep] if group == SECRETS_GROUP else [])

    def test_error_short_previous_jwt_value(self):
        source = self.write("mod.lnpl", JWT_SOURCE)
        with self._local("prev", "make_short_previous_secret_provider"):
            rc, out, err = self.run_cli(["config", "check", source, "--config",
                                         self.provider_toml("prev")])
        self.assertEqual(rc, 2)
        self.assertEqual(
            err, "error: the previous JWT signing secret must be at least 32 "
                 "bytes, got 9 (from lnpl.toml secrets.jwt provider 'prev')\n")
        self.assertNotIn("FAKE-SECR", out + err)
        self.assertEqual(self.fixture.INSTANCES[-1].close_calls, 1)

    def test_error_non_bytes_value(self):
        source = self.write("mod.lnpl", JWT_SOURCE)
        with self._local("strs", "make_str_secret_provider"):
            rc, out, err = self.run_cli(["config", "check", source, "--config",
                                         self.provider_toml("strs")])
        self.assertEqual(rc, 2)
        self.assertEqual(
            err, "error: the secret provider returned a value that is not bytes "
                 "(from lnpl.toml secrets.jwt provider 'strs')\n")
        self.assertNotIn("FAKE-SECRET-192", out + err)

    def test_boundary_short_value_under_another_key_is_ok(self):
        toml = self.write(
            "lnpl.toml", '[default.secrets]\njwt = { file = "%s" }\n'
            'other = { provider = "short", key = "jwt" }\n'
            % self.secret_file(FILE_SECRET))
        rc, out, err = self._check(toml, ("short", "make_short_secret_provider"))
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, "ok\n")
        self.assertEqual(self.fixture.INSTANCES[-1].close_calls, 1)


if __name__ == "__main__":
    unittest.main()

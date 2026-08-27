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
    _merge_endpoint_args, _resolve_backend, _resolve_jwt_secret_env,
    _resolve_log_format, _resolve_trace_exporter, main,
)
from lnpl.config import ResolvedConfig

from tests.fixtures import SHORTEN_LNPL

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


if __name__ == "__main__":
    unittest.main()

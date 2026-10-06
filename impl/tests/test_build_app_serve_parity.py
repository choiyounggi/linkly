"""issue #187: `lnpl serve` and `build_app()` are two entry points to one app
object, so an option one has and the other silently lacks is a production
surprise (the gunicorn path could not turn on `/-/metrics` at all).

Forward: every entry of the live `serve` parser — the positional and the
auto `-h/--help` included — has a `build_app` environment variable
(`PARITY_MAP`), a reason it has none (`EXCLUDED`), or is named as still
pending (`PENDING_T187`).

Reverse: every mapped `LNPL_*` name is actually READ by `build_app`. The
scan walks `build_app`'s AST and collects only string constants passed to
the environment readers, because `build_app`'s docstring names every
variable and a substring search over the source would pass on prose alone.

Each direction has its own negative control (`test_error_*`).
"""

import ast
import contextlib
import inspect
import io
import os
import re
import tempfile
import unittest
from unittest import mock

from lnpl import cli, wsgi
from lnpl.drivers import HmacTokenProvider, TokenError

PARITY_MAP = {
    ("source",): "LNPL_SOURCE",
    ("--backend",): "LNPL_BACKEND",
    ("--endpoint",): "LNPL_ENDPOINT_<NAME>",
    ("--jwt-secret-env",): "LNPL_JWT_SECRET_ENV",
    ("--jwt-secret-file",): "LNPL_JWT_SECRET_FILE",
    ("--log-format",): "LNPL_LOG_FORMAT",
    ("--trace-exporter",): "LNPL_TRACE_EXPORTER",
    ("--trust-incoming-trace",): "LNPL_TRUST_INCOMING_TRACE",
    ("--metrics",): "LNPL_METRICS",
    ("--idempotency-ttl",): "LNPL_IDEMPOTENCY_TTL_S",
    ("--capture-on-failure",): "LNPL_CAPTURE_ON_FAILURE",
    ("--rate-limit",): "LNPL_RATE_LIMIT",
    ("--cache",): "LNPL_CACHE",
    ("--network",): "LNPL_NETWORK",
    ("--config",): "LNPL_CONFIG",
    ("--profile",): "LNPL_PROFILE",
    ("--jwt-issuer",): "LNPL_JWT_ISSUER",
    ("--token-provider",): "LNPL_TOKEN_PROVIDER",
}
EXCLUDED = {
    ("-h", "--help"): "argparse auto-added; not an operational option",
    ("--host",): "gunicorn owns bind address",
    ("--port",): "gunicorn owns port",
    ("--grace-period",): "gunicorn --graceful-timeout owns shutdown grace",
}
PENDING_T187 = {}
REVERSE_ONLY = {
    "LNPL_CLOCK": ("no serve --clock flag exists; serve's embedded dev "
                   "server always runs the virtual clock, LNPL_CLOCK is "
                   "a gunicorn-worker-only convenience"),
}
ENV_READER_CALLS = ("os.environ.get", "_env_or_none")
ENV_NAME_RE = re.compile(r"^LNPL_[A-Z0-9_]+$")


def _action_key(action):
    return tuple(action.option_strings) if action.option_strings else (action.dest,)


def _dotted_call_name(func):
    if isinstance(func, ast.Name):
        return func.id
    parts = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
        return ".".join(reversed(parts))
    return ""


def _read_env_names(source):
    tree = ast.parse(source)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _dotted_call_name(node.func) in ENV_READER_CALLS and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str) \
               and ENV_NAME_RE.match(first.value):
                names.add(first.value)
    return names


def _forward_violations(parity_map, excluded, pending, actions):
    violations = []
    for action in actions:
        key = _action_key(action)
        if key not in parity_map and key not in excluded and key not in pending:
            violations.append(
                "serve entry %r has no build_app variable, exclusion "
                "reason, or pending-t187 entry" % (key,))
    return violations


def _reverse_violations(parity_map, reverse_only, read_names):
    violations = []
    for key, env_var in parity_map.items():
        if env_var == "LNPL_ENDPOINT_<NAME>":
            continue
        if env_var not in read_names:
            violations.append(
                "%s (mapped from %r) is never read by build_app" % (env_var, key))
    for env_var in reverse_only:
        if env_var not in read_names:
            violations.append("%s (REVERSE_ONLY) is never read by build_app" % (env_var,))
    return violations


class ParityTest(unittest.TestCase):
    def _serve_actions(self):
        registry = {}
        cli._build_parser(registry)
        return registry["serve"]._actions

    def _read_names(self):
        return _read_env_names(inspect.getsource(wsgi.build_app))

    def test_normal_parity_map_matches_the_live_serve_parser(self):
        violations = _forward_violations(
            PARITY_MAP, EXCLUDED, PENDING_T187, self._serve_actions())
        self.assertEqual([], violations)

    def test_error_parity_map_catches_a_removed_mapping(self):
        mutated = dict(PARITY_MAP)
        del mutated[("--rate-limit",)]
        violations = _forward_violations(
            mutated, EXCLUDED, PENDING_T187, self._serve_actions())
        self.assertEqual(
            ["serve entry ('--rate-limit',) has no build_app variable, "
             "exclusion reason, or pending-t187 entry"],
            violations)

    def test_normal_every_mapped_env_var_and_reverse_only_name_is_read_by_build_app(self):
        violations = _reverse_violations(PARITY_MAP, REVERSE_ONLY, self._read_names())
        self.assertEqual([], violations)

    def test_error_scan_catches_a_name_build_app_never_reads(self):
        # LNPL_EXAMPLE_UNUSED occurs in build_app's docstring and nowhere
        # else in it (a permanent placeholder) — the case a substring search
        # over the source would wave through.
        self.assertIn("LNPL_EXAMPLE_UNUSED", wsgi.build_app.__doc__)
        mutated = dict(PARITY_MAP)
        mutated[("--rate-limit",)] = "LNPL_EXAMPLE_UNUSED"
        violations = _reverse_violations(mutated, REVERSE_ONLY, self._read_names())
        self.assertEqual(
            ["LNPL_EXAMPLE_UNUSED (mapped from ('--rate-limit',)) is never read by build_app"],
            violations)

    def test_boundary_the_three_lists_are_disjoint_and_name_no_stale_entry(self):
        # A key in two lists, or a key the parser no longer has, would let
        # the forward check pass while the lists drift from the parser.
        live = {_action_key(a) for a in self._serve_actions()}
        listed = list(PARITY_MAP) + list(EXCLUDED) + list(PENDING_T187)
        self.assertEqual(len(listed), len(set(listed)))
        self.assertEqual(live, set(listed))

    def test_boundary_scan_ignores_docstrings_and_comments(self):
        source = (
            'def f():\n'
            '    """reads LNPL_DOC_ONLY via os.environ.get("LNPL_DOC_ONLY")."""\n'
            '    # os.environ.get("LNPL_COMMENT_ONLY")\n'
            '    a = os.environ.get("LNPL_REAL_A", "x")\n'
            '    b = _env_or_none("LNPL_REAL_B")\n'
            '    c = other("LNPL_NOT_A_READER")\n'
            '    return a, b, c\n')
        self.assertEqual({"LNPL_REAL_A", "LNPL_REAL_B"}, _read_env_names(source))


REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
JWT_SRC = """entity Report
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
ENV_SECRET = b"FAKE-SECRET-192-env-source-ccccccccccccc"      # 40 bytes
CFG_ENV = "LNPL_T192_PARITY_SECRET"


class SecretSourceParityTest(unittest.TestCase):
    """issue #192 D7: the same secret-source combination driven through
    `lnpl serve` and `build_app` gives the same outcome — the same accepted
    token, or the same error once the serve flag names are mapped to their
    PARITY_MAP variables."""

    ROLE_MAP = {"--jwt-secret-env": "LNPL_JWT_SECRET_ENV",
                "--jwt-secret-file": "LNPL_JWT_SECRET_FILE"}

    def setUp(self):
        saved = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        for name in ("LNPL_JWT_SECRET_ENV", "LNPL_JWT_SECRET_FILE", "LNPL_CONFIG",
                     "LNPL_PROFILE", "LNPL_TOKEN_PROVIDER", "LNPL_JWT_ISSUER"):
            os.environ.pop(name, None)
        os.environ[CFG_ENV] = ENV_SECRET.decode()
        tmp_root = os.path.join(REPO, ".claude", "tmp")
        os.makedirs(tmp_root, exist_ok=True)
        box = tempfile.TemporaryDirectory(dir=tmp_root)
        self.addCleanup(box.cleanup)
        self.dir = box.name
        self.src = self._write("mod.lnpl", JWT_SRC.encode())

    def _write(self, name, data):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def _config_name(self):
        return self._write("lnpl.toml", ('[default.secrets]\njwt = "%s"\n' % CFG_ENV).encode())

    def _serve(self, *extra):
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 0)
        server.serve_forever.side_effect = KeyboardInterrupt
        err = io.StringIO()
        with mock.patch("lnpl.cli.serve", return_value=server) as factory, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = cli.main(["serve", self.src] + list(extra))
        provider = factory.call_args.kwargs["token_provider"] if factory.called else None
        # Only the `error:` lines: cmd_serve prints the compile's `info:`
        # diagnostics first, which build_app has no counterpart for.
        errors = "".join(line + "\n" for line in err.getvalue().splitlines()
                         if line.startswith("error:"))
        return rc, errors, provider

    def _build(self, **kwargs):
        with contextlib.redirect_stderr(io.StringIO()):
            return wsgi.build_app(sources=[self.src], **kwargs).token_provider

    def _build_error(self, **kwargs):
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            self._build(**kwargs)
        return str(cm.exception)

    def _mapped(self, serve_err):
        text = serve_err
        for flag, var in self.ROLE_MAP.items():
            text = text.replace(flag, var)
        return text

    @staticmethod
    def _accepts(provider, secret):
        token = HmacTokenProvider(secret).issue("u", JWT_AUDIENCE)
        try:
            provider.verify(token, JWT_AUDIENCE)
        except TokenError:
            return False
        return True

    def test_error_env_and_file_together_refused_identically(self):
        path = self._write("jwt", FILE_SECRET)
        rc, err, _p = self._serve("--jwt-secret-env", CFG_ENV, "--jwt-secret-file", path)
        text = self._build_error(jwt_secret_env=CFG_ENV, jwt_secret_file=path)
        self.assertEqual(rc, 2)
        self.assertIn("give exactly one", text)
        self.assertEqual(self._mapped(err), "error: %s\n" % text)

    def test_normal_explicit_file_beats_config_name_on_both(self):
        path = self._write("jwt", FILE_SECRET)
        toml = self._config_name()
        rc, err, serve_p = self._serve("--config", toml, "--jwt-secret-file", path)
        build_p = self._build(config=toml, jwt_secret_file=path)
        self.assertEqual(rc, 0, err)
        for provider in (serve_p, build_p):
            self.assertTrue(self._accepts(provider, FILE_SECRET))
            self.assertFalse(self._accepts(provider, ENV_SECRET))

    def test_normal_config_name_only_is_unchanged_on_both(self):
        toml = self._config_name()
        rc, err, serve_p = self._serve("--config", toml)
        build_p = self._build(config=toml)
        self.assertEqual(rc, 0, err)
        for provider in (serve_p, build_p):
            self.assertTrue(self._accepts(provider, ENV_SECRET))
            self.assertFalse(self._accepts(provider, FILE_SECRET))

    def test_error_missing_file_fails_identically(self):
        path = os.path.join(self.dir, "absent")
        rc, err, _p = self._serve("--jwt-secret-file", path)
        text = self._build_error(jwt_secret_file=path)
        self.assertEqual(rc, 2)
        self.assertEqual(text, "LNPL_JWT_SECRET_FILE names a file that does not exist")
        self.assertEqual(self._mapped(err), "error: %s\n" % text)

    def test_error_short_file_fails_identically(self):
        path = self._write("jwt", b"FAKE-SEC")
        rc, err, _p = self._serve("--jwt-secret-file", path)
        text = self._build_error(jwt_secret_file=path)
        self.assertEqual(rc, 2)
        self.assertIn("at least 32 bytes, got 8", text)
        self.assertEqual(self._mapped(err), "error: %s\n" % text)


if __name__ == "__main__":
    unittest.main()

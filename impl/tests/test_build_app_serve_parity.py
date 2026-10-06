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
import inspect
import re
import unittest

from lnpl import cli, wsgi

PARITY_MAP = {
    ("source",): "LNPL_SOURCE",
    ("--backend",): "LNPL_BACKEND",
    ("--endpoint",): "LNPL_ENDPOINT_<NAME>",
    ("--jwt-secret-env",): "LNPL_JWT_SECRET_ENV",
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


if __name__ == "__main__":
    unittest.main()

"""`lnpl.wsgi.build_app()` — the env-var-driven factory a WSGI host calls
with no arguments (issue #80, D1): `gunicorn "lnpl.wsgi:build_app()"`.

Normal: an explicit `sources` list builds a callable; `LNPL_SOURCE`/
`LNPL_BACKEND`/`LNPL_JWT_SECRET_ENV`/`LNPL_CLOCK`/`LNPL_ENDPOINT_<NAME>` env
fallbacks resolve the same configuration `cli.cmd_serve`'s CLI flags already
resolve. Error: a missing/unreadable `LNPL_SOURCE`, an unknown `LNPL_BACKEND`,
a too-short/missing JWT secret, and an unmapped `NetworkCall` target are all a
failed launch (`WsgiConfigError`) raised before any request is served — never
a failed first request (D6). Boundary: multi-file `LNPL_SOURCE` (t77's
`load_sources`, `os.pathsep`-joined) and a `wsgiref.validate` smoke pass over
the built callable — the D5 substitute for a real gunicorn startup log on a
machine gunicorn is not installed on.
"""

import contextlib
import io
import os
import unittest
from importlib import metadata as importlib_metadata
from unittest import mock
from wsgiref.validate import validator

from lnpl import wsgi
from lnpl import diagnostics as diagnostics_module
from lnpl.diagnostics import ExtensionDiagnosticsError
from lnpl.drivers import HmacTokenProvider

EXT_GROUP = diagnostics_module.DIAGNOSTICS_ENTRY_POINT_GROUP


def _entry_point(name, value):
    return importlib_metadata.EntryPoint(name=name, value=value, group=EXT_GROUP)


KAFKA_EP = _entry_point("kafka", "tests.diagnostics_ext_fixture:register_kafka")


def registered(*entry_points):
    """Patch `diagnostics_module.importlib_metadata.entry_points` — same
    fixture-injection pattern `test_extension_diagnostics.py`/
    `test_mcp_server.py` use — so `build_app`'s extension pass sees exactly
    `entry_points`, regardless of what is actually installed."""
    return mock.patch.object(
        diagnostics_module.importlib_metadata, "entry_points",
        lambda **_kwargs: list(entry_points))

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHORTEN = os.path.join(REPO, "examples", "shorten.lnpl")
LINKHUB_SINGLE = os.path.join(REPO, "examples", "linkhub.lnpl")
LINKHUB_SPLIT_DIR = os.path.join(REPO, "impl", "tests", "lnpl_fixtures", "linkhub")
LINKHUB_ENTITY_FILE = os.path.join(LINKHUB_SPLIT_DIR, "01_entity.lnpl")
LINKHUB_WORKFLOW_FILE = os.path.join(LINKHUB_SPLIT_DIR, "02_workflow.lnpl")

PAYMENT_TOKEN_ENV = "LNPL_TEST_WSGI_PAYMENT_TOKEN"

# Mirrors test_cli_capability_http.py's fixture — a logical `call` target
# behind a `capability http` declaration with a bearer auth header, the
# exact shape `_resolve_network`'s endpoint/auth resolution has to handle.
CALL_SOURCE = """
capability http PaymentGateway
    method post
    auth bearer from %s
entity Order
    field
        id UUID
service Checkout
workflow Pay
    call PaymentGateway as p
""" % PAYMENT_TOKEN_ENV

UNBOUND_CALL_SOURCE = """
entity Order
    field
        id UUID
service Checkout
workflow Pay
    call PaymentGateway as p
"""


def _environ(method="GET", path="/", query=""):
    body = b""
    return {
        "REQUEST_METHOD": method,
        "SCRIPT_NAME": "",
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
        "wsgi.errors": io.StringIO(),
        "wsgi.version": (1, 0),
        "wsgi.multithread": True,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
        "wsgi.url_scheme": "http",
        "SERVER_NAME": "test",
        "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1",
    }


def _write(directory, name, text):
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


class _EnvIsolatedTest(unittest.TestCase):
    """Every `LNPL_*` env var `build_app()` reads, cleared before each test
    and restored after — a stray var from another test/the OS environment
    must never leak into a resolution this test is trying to pin."""

    _ENV_KEYS = ("LNPL_SOURCE", "LNPL_BACKEND", "LNPL_JWT_SECRET_ENV",
                "LNPL_CLOCK", PAYMENT_TOKEN_ENV)

    def setUp(self):
        self._saved = {k: os.environ.pop(k, None) for k in self._ENV_KEYS}
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class BuildAppNormalTest(_EnvIsolatedTest):

    def test_normal_explicit_sources_builds_a_working_callable(self):
        app = wsgi.build_app(sources=[SHORTEN])
        self.assertIsInstance(app, wsgi.LnplWsgiApp)
        self.assertIn("/shorten-service/shorten", app.routes)

    def test_normal_lnpl_source_env_var_is_used_when_sources_omitted(self):
        os.environ["LNPL_SOURCE"] = SHORTEN
        app = wsgi.build_app()
        self.assertIn("/shorten-service/shorten", app.routes)

    def test_normal_lnpl_backend_env_var_opens_a_real_store(self):
        import tempfile
        tmp_root = os.path.join(REPO, ".claude", "tmp")
        os.makedirs(tmp_root, exist_ok=True)
        box = tempfile.TemporaryDirectory(dir=tmp_root)
        self.addCleanup(box.cleanup)
        db = os.path.join(box.name, "store.db")
        os.environ["LNPL_BACKEND"] = "sqlite:%s" % db
        app = wsgi.build_app(sources=[SHORTEN])
        self.assertIsNotNone(app.repository_factory)
        repo = app.repository_factory()
        self.addCleanup(repo.close)

    def test_normal_lnpl_jwt_secret_env_turns_on_verification(self):
        os.environ["LNPL_JWT_SECRET_ENV"] = "LNPL_TEST_WSGI_SECRET"
        os.environ["LNPL_TEST_WSGI_SECRET"] = "x" * 32
        self.addCleanup(os.environ.pop, "LNPL_TEST_WSGI_SECRET", None)
        app = wsgi.build_app(sources=[SHORTEN])
        self.assertIsInstance(app.token_provider, HmacTokenProvider)

    def test_normal_lnpl_clock_env_selects_real_clock(self):
        os.environ["LNPL_CLOCK"] = "real"
        app = wsgi.build_app(sources=[SHORTEN])
        self.assertIsNotNone(app.clock)

    def test_normal_default_clock_stays_virtual_none(self):
        # Byte-identical to before issue #80: nothing set -> Interpreter
        # builds its own virtual Clock().
        app = wsgi.build_app(sources=[SHORTEN])
        self.assertIsNone(app.clock)

    def test_normal_endpoints_argument_resolves_a_declared_network_call(self):
        os.environ[PAYMENT_TOKEN_ENV] = "secret-token-value"
        app = wsgi.build_app(sources=[_write_tmp(self, CALL_SOURCE)],
                             endpoints={"PaymentGateway": "http://example.invalid/pay"})
        self.assertIsNotNone(app.network)

    def test_normal_registered_extension_diagnostic_is_printed_to_stderr(self):
        # RFC-0042, issue #140: `build_app` never surfaces its compiled
        # module's own diagnostics anywhere, so there is no existing sink to
        # merge the extension pass into — it prints to stderr instead, the
        # same `format_lines_from_records` rendering `lnpl compile` uses.
        err = io.StringIO()
        with registered(KAFKA_EP), contextlib.redirect_stderr(err):
            app = wsgi.build_app(sources=[SHORTEN])
        self.assertIsInstance(app, wsgi.LnplWsgiApp)
        self.assertIn("info: kafka/at-least-once", err.getvalue())


def _write_tmp(testcase, text, name="mod.lnpl"):
    import tempfile
    tmp_root = os.path.join(REPO, ".claude", "tmp")
    os.makedirs(tmp_root, exist_ok=True)
    box = tempfile.TemporaryDirectory(dir=tmp_root)
    testcase.addCleanup(box.cleanup)
    return _write(box.name, name, text)


class BuildAppErrorTest(_EnvIsolatedTest):

    def test_error_no_sources_and_no_lnpl_source_env_fails_the_launch(self):
        with self.assertRaises(wsgi.WsgiConfigError):
            wsgi.build_app()

    def test_error_nonexistent_source_path_fails_the_launch(self):
        with self.assertRaises(wsgi.WsgiConfigError):
            wsgi.build_app(sources=[os.path.join(REPO, "examples", "does-not-exist.lnpl")])

    def test_error_unknown_backend_selector_fails_the_launch(self):
        with self.assertRaises(wsgi.WsgiConfigError):
            wsgi.build_app(sources=[SHORTEN], backend="not-a-real-backend")

    def test_error_lnpl_backend_env_unknown_selector_fails_the_launch(self):
        os.environ["LNPL_BACKEND"] = "not-a-real-backend"
        with self.assertRaises(wsgi.WsgiConfigError):
            wsgi.build_app(sources=[SHORTEN])

    def test_error_jwt_secret_env_names_an_unset_variable(self):
        with self.assertRaises(wsgi.WsgiConfigError):
            wsgi.build_app(sources=[SHORTEN], jwt_secret_env="LNPL_TEST_WSGI_UNSET_SECRET")

    def test_error_jwt_secret_too_short_fails_the_launch(self):
        os.environ["LNPL_TEST_WSGI_SHORT_SECRET"] = "too-short"
        self.addCleanup(os.environ.pop, "LNPL_TEST_WSGI_SHORT_SECRET", None)
        with self.assertRaises(wsgi.WsgiConfigError):
            wsgi.build_app(sources=[SHORTEN],
                           jwt_secret_env="LNPL_TEST_WSGI_SHORT_SECRET")

    def test_error_unknown_clock_selector_fails_the_launch(self):
        with self.assertRaises(wsgi.WsgiConfigError):
            wsgi.build_app(sources=[SHORTEN], clock="not-a-real-clock")

    def test_error_unmapped_network_call_target_fails_the_launch(self):
        path = _write_tmp(self, UNBOUND_CALL_SOURCE)
        with self.assertRaises(wsgi.WsgiConfigError):
            wsgi.build_app(sources=[path])

    def test_error_declared_auth_env_unset_fails_the_launch(self):
        path = _write_tmp(self, CALL_SOURCE)
        # PAYMENT_TOKEN_ENV deliberately left unset by _EnvIsolatedTest.
        with self.assertRaises(wsgi.WsgiConfigError):
            wsgi.build_app(sources=[path],
                           endpoints={"PaymentGateway": "http://example.invalid/pay"})

    def test_error_invalid_extension_registration_fails_the_launch(self):
        # A load-time RFC-0042 violation raises `ExtensionDiagnosticsError`
        # from the shared helper — `build_app` joins it to the same except
        # tuple as LowerError/ParseError/etc., so it becomes the same failed-
        # launch `WsgiConfigError`, never a request-time crash (D6).
        with mock.patch("lnpl.diagnostics.load_extensions",
                        side_effect=ExtensionDiagnosticsError("boom")):
            with self.assertRaises(wsgi.WsgiConfigError) as caught:
                wsgi.build_app(sources=[SHORTEN])
        self.assertIn("boom", str(caught.exception))


class BuildAppBoundaryTest(_EnvIsolatedTest):

    def test_boundary_multi_file_lnpl_source_via_pathsep(self):
        joined = os.pathsep.join([LINKHUB_ENTITY_FILE, LINKHUB_WORKFLOW_FILE])
        os.environ["LNPL_SOURCE"] = joined
        app = wsgi.build_app()
        single_app = wsgi.build_app(sources=[LINKHUB_SINGLE])
        self.assertEqual(set(single_app.routes), set(app.routes))

    def test_boundary_no_registered_extensions_prints_nothing_extra(self):
        # Zero extensions installed — the extension pass appends nothing:
        # `build_app`'s stderr is byte-identical to before this pass
        # existed (here, only the pre-existing Idempotency-Key notice from
        # the `fake` backend — unrelated to extension diagnostics).
        baseline_err = io.StringIO()
        with contextlib.redirect_stderr(baseline_err):
            wsgi.build_app(sources=[SHORTEN])
        ext_err = io.StringIO()
        with registered(), contextlib.redirect_stderr(ext_err):
            app = wsgi.build_app(sources=[SHORTEN])
        self.assertIsInstance(app, wsgi.LnplWsgiApp)
        self.assertEqual(ext_err.getvalue(), baseline_err.getvalue())

    def test_boundary_wsgiref_validate_accepts_the_built_callable(self):
        """D5: no gunicorn on this machine — `wsgiref.validate`'s strict
        PEP-3333 conformance wrapper is the substitute evidence that the
        callable `build_app()` hands a WSGI host is actually well-formed
        (correct `start_response` signature, an iterable of `bytes`, no
        writes after the app returns, etc.)."""
        app = wsgi.build_app(sources=[SHORTEN])
        validated = validator(app)

        captured = {}

        def start_response(status, headers, exc_info=None):
            captured["status"] = status
            captured["headers"] = headers

        result = validated(_environ(path="/no/such/path"), start_response)
        try:
            body = b"".join(result)
        finally:
            if hasattr(result, "close"):
                result.close()
        self.assertTrue(captured["status"].startswith("404"))
        self.assertIn(b"not-found", body)


if __name__ == "__main__":
    unittest.main()

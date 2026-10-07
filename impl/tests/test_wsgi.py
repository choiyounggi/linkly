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
import json
import os
import threading
import traceback
import unittest
from importlib import metadata as importlib_metadata
from unittest import mock
from wsgiref.validate import validator

from lnpl import wsgi
from lnpl import diagnostics as diagnostics_module
from lnpl.diagnostics import ExtensionDiagnosticsError
from lnpl.drivers import HmacTokenProvider

from tests.cache_spi_fixture import DemoCacheDriver
from tests.network_spi_fixture import DemoNetworkDriver
from tests.test_network_driver import _ServerTestCase
from tests.test_network_resilience import _make_fail_n_handler
from tests.test_wsgi_contract import call_wsgi
from tests.token_spi_fixture import DemoTokenProvider

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

# issue #176: retry/breaker/path all declared, to prove all three reach
# HttpNetworkDriver through build_app()/make_wsgi_app the same way
# test_cli_capability_http.py proves it for the CLI path.
RETRY_CALL_SOURCE = """
capability http PaymentGateway
    method post
    retry 2 backoff 1ms
    breaker after 5 within 1m
    path "/pay/{}"
entity Order
    field
        id UUID
service Checkout
workflow Pay
    call PaymentGateway with input.id as p
"""

# Named DEAD_ENDPOINT_FAIL_SOURCE, distinct from the EXISTING
# UNBOUND_CALL_SOURCE (which has no `capability http` declaration at all
# and fails at BUILD time). This fixture DECLARES the capability and
# fails at REQUEST time because its endpoint is unreachable -- the one
# failure build_app can produce without a custom repository_factory.
# No `as p`: an unbound `call` re-raises a transport failure as RunError
# (a 500), where a bound one turns it into a value the guard can branch on.
DEAD_ENDPOINT_FAIL_SOURCE = """
capability http PaymentGateway
    method post
    auth bearer from %s
entity Order
    field
        id UUID
service Checkout
workflow Pay
    call PaymentGateway
""" % PAYMENT_TOKEN_ENV

# issue #187: mirrors test_trace_canonical_line.py's fixture.
VALID = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

TRACE_SOURCE = """
capability postgres
entity Order
    field
        id UUID
service Checkout
    policy
        retry 0
workflow Ping
    find order
"""


def _raw_get(app, path):
    environ = {
        "REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": "",
        "wsgi.input": io.BytesIO(b""), "wsgi.errors": io.StringIO(),
        "wsgi.version": (1, 0), "wsgi.multithread": True,
        "wsgi.multiprocess": False, "wsgi.run_once": False,
        "wsgi.url_scheme": "http", "SERVER_NAME": "test", "SERVER_PORT": "80",
        "SERVER_PROTOCOL": "HTTP/1.1", "SCRIPT_NAME": "",
    }
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = dict(headers)

    result = app(environ, start_response)
    raw = b"".join(result)
    status_code = int(captured["status"].split(" ", 1)[0])
    return status_code, captured["headers"], raw


def _post_json_lines(app, path, headers=None, body=None):
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        status, _headers, _body = call_wsgi(
            app, "POST", path,
            body=body if body is not None else json.dumps(
                {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301"}).encode("utf-8"),
            headers=headers or {})
    lines = []
    for ln in buf.getvalue().splitlines():
        if not ln.strip():
            continue
        try:
            lines.append(json.loads(ln))
        except ValueError:
            continue
    return status, lines


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
                "LNPL_CLOCK", PAYMENT_TOKEN_ENV, "LNPL_METRICS",
                "LNPL_CAPTURE_ON_FAILURE", "LNPL_TRUST_INCOMING_TRACE",
                "LNPL_CACHE", "LNPL_NETWORK", "LNPL_TOKEN_PROVIDER",
                "LNPL_JWT_ISSUER", "LNPL_CONFIG", "LNPL_PROFILE",
                "LNPL_JWT_SECRET_FILE")

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
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[SHORTEN], backend="not-a-real-backend")
        self.assertEqual(str(cm.exception),
                         "LNPL_BACKEND is not a recognized selector")

    def test_error_lnpl_backend_env_unknown_selector_fails_the_launch(self):
        os.environ["LNPL_BACKEND"] = "not-a-real-backend"
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[SHORTEN])
        self.assertEqual(str(cm.exception),
                         "LNPL_BACKEND is not a recognized selector")

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


class BuildAppMetricsTest(_EnvIsolatedTest):
    """issue #187: `metrics` / LNPL_METRICS on the build_app path."""

    def test_normal_lnpl_metrics_env_var_exposes_metrics_endpoint(self):
        os.environ["LNPL_METRICS"] = "1"
        app = wsgi.build_app(sources=[SHORTEN])
        status, _headers, raw = _raw_get(app, "/-/metrics")
        self.assertEqual(200, status)
        self.assertTrue(len(raw) > 0)

    def test_normal_lnpl_metrics_absent_by_default_returns_404(self):
        app = wsgi.build_app(sources=[SHORTEN])
        status, _headers, _raw = _raw_get(app, "/-/metrics")
        self.assertEqual(404, status)

    def test_normal_explicit_false_metrics_overrides_lnpl_metrics_env(self):
        os.environ["LNPL_METRICS"] = "1"
        app = wsgi.build_app(sources=[SHORTEN], metrics=False)
        self.assertIsNone(app.metrics)
        status, _headers, _raw = _raw_get(app, "/-/metrics")
        self.assertEqual(404, status)

    def test_boundary_lnpl_metrics_empty_string_behaves_as_unset(self):
        os.environ["LNPL_METRICS"] = ""
        app = wsgi.build_app(sources=[SHORTEN])
        self.assertIsNone(app.metrics)

    def test_boundary_lnpl_metrics_false_spellings_keep_the_endpoint_off(self):
        for value in ("0", "false", "No", " off "):
            with self.subTest(value=value):
                os.environ["LNPL_METRICS"] = value
                app = wsgi.build_app(sources=[SHORTEN])
                self.assertIsNone(app.metrics)

    def test_error_lnpl_metrics_malformed_value_fails_the_launch(self):
        os.environ["LNPL_METRICS"] = "maybe"
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[SHORTEN])
        self.assertIn("LNPL_METRICS", str(cm.exception))

    def test_error_explicit_metrics_non_bool_argument_raises_typeerror(self):
        with self.assertRaises(TypeError) as cm:
            wsgi.build_app(sources=[SHORTEN], metrics="0")
        self.assertIn("metrics", str(cm.exception))


def _dead_endpoint_url():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    dead_port = s.getsockname()[1]
    s.close()
    return "http://127.0.0.1:%d/" % dead_port


class BuildAppCaptureOnFailureTest(_EnvIsolatedTest):
    """issue #187: `capture_on_failure` / LNPL_CAPTURE_ON_FAILURE on the
    build_app path. The failure is a refused connection to a closed port."""

    PAY_BODY = json.dumps({"id": "11111111-1111-1111-1111-111111111111"}).encode("utf-8")

    def test_normal_on_and_failed_includes_the_masked_input(self):
        os.environ[PAYMENT_TOKEN_ENV] = "secret-token-value"
        app = wsgi.build_app(sources=[_write_tmp(self, DEAD_ENDPOINT_FAIL_SOURCE)],
                             endpoints={"PaymentGateway": _dead_endpoint_url()},
                             capture_on_failure=True, log_format="json")
        status, lines = _post_json_lines(app, "/checkout/pay", body=self.PAY_BODY)
        self.assertEqual(500, status)
        self.assertIn("input", lines[0])

    def test_normal_off_and_failed_omits_the_input(self):
        os.environ[PAYMENT_TOKEN_ENV] = "secret-token-value"
        app = wsgi.build_app(sources=[_write_tmp(self, DEAD_ENDPOINT_FAIL_SOURCE)],
                             endpoints={"PaymentGateway": _dead_endpoint_url()},
                             log_format="json")
        status, lines = _post_json_lines(app, "/checkout/pay", body=self.PAY_BODY)
        self.assertEqual(500, status)
        self.assertNotIn("input", lines[0])

    def test_normal_lnpl_capture_on_failure_env_var_includes_the_masked_input(self):
        os.environ[PAYMENT_TOKEN_ENV] = "secret-token-value"
        os.environ["LNPL_CAPTURE_ON_FAILURE"] = "true"
        app = wsgi.build_app(sources=[_write_tmp(self, DEAD_ENDPOINT_FAIL_SOURCE)],
                             endpoints={"PaymentGateway": _dead_endpoint_url()},
                             log_format="json")
        status, lines = _post_json_lines(app, "/checkout/pay", body=self.PAY_BODY)
        self.assertEqual(500, status)
        self.assertEqual({"id": "11111111-1111-1111-1111-111111111111"},
                         lines[0]["input"])

    def test_normal_explicit_false_overrides_lnpl_capture_on_failure_env(self):
        os.environ["LNPL_CAPTURE_ON_FAILURE"] = "1"
        app = wsgi.build_app(sources=[SHORTEN], capture_on_failure=False)
        self.assertFalse(app.capture_on_failure)

    def test_boundary_lnpl_capture_on_failure_empty_string_behaves_as_unset(self):
        os.environ["LNPL_CAPTURE_ON_FAILURE"] = ""
        app = wsgi.build_app(sources=[SHORTEN])
        self.assertFalse(app.capture_on_failure)

    def test_error_lnpl_capture_on_failure_malformed_value_fails_the_launch(self):
        os.environ["LNPL_CAPTURE_ON_FAILURE"] = "maybe"
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[SHORTEN])
        self.assertIn("LNPL_CAPTURE_ON_FAILURE", str(cm.exception))

    def test_error_explicit_capture_on_failure_non_bool_argument_raises_typeerror(self):
        with self.assertRaises(TypeError) as cm:
            wsgi.build_app(sources=[SHORTEN], capture_on_failure="0")
        self.assertIn("capture_on_failure", str(cm.exception))


class BuildAppTrustIncomingTraceTest(_EnvIsolatedTest):
    """issue #187: `trust_incoming_trace` / LNPL_TRUST_INCOMING_TRACE on the
    build_app path."""

    def test_normal_on_adopts_the_inbound_trace_id(self):
        app = wsgi.build_app(sources=[_write_tmp(self, TRACE_SOURCE)],
                             trust_incoming_trace=True, log_format="json")
        status, lines = _post_json_lines(app, "/checkout/ping",
                                         headers={"traceparent": VALID})
        self.assertEqual(200, status)
        self.assertEqual("4bf92f3577b34da6a3ce929d0e0e4736", lines[0]["trace_id"])

    def test_normal_off_default_mints_a_fresh_trace_id(self):
        app = wsgi.build_app(sources=[_write_tmp(self, TRACE_SOURCE)],
                             log_format="json")
        status, lines = _post_json_lines(app, "/checkout/ping",
                                         headers={"traceparent": VALID})
        self.assertEqual(200, status)
        self.assertNotEqual("4bf92f3577b34da6a3ce929d0e0e4736", lines[0]["trace_id"])

    def test_normal_lnpl_trust_incoming_trace_env_var_adopts_the_inbound_trace_id(self):
        os.environ["LNPL_TRUST_INCOMING_TRACE"] = "ON"
        app = wsgi.build_app(sources=[_write_tmp(self, TRACE_SOURCE)],
                             log_format="json")
        status, lines = _post_json_lines(app, "/checkout/ping",
                                         headers={"traceparent": VALID})
        self.assertEqual(200, status)
        self.assertEqual("4bf92f3577b34da6a3ce929d0e0e4736", lines[0]["trace_id"])

    def test_normal_explicit_false_overrides_lnpl_trust_incoming_trace_env(self):
        os.environ["LNPL_TRUST_INCOMING_TRACE"] = "1"
        app = wsgi.build_app(sources=[_write_tmp(self, TRACE_SOURCE)],
                             trust_incoming_trace=False, log_format="json")
        status, lines = _post_json_lines(app, "/checkout/ping",
                                         headers={"traceparent": VALID})
        self.assertEqual(200, status)
        self.assertNotEqual("4bf92f3577b34da6a3ce929d0e0e4736", lines[0]["trace_id"])

    def test_boundary_lnpl_trust_incoming_trace_empty_string_behaves_as_unset(self):
        os.environ["LNPL_TRUST_INCOMING_TRACE"] = ""
        app = wsgi.build_app(sources=[SHORTEN])
        self.assertFalse(app.trust_incoming_trace)

    def test_error_lnpl_trust_incoming_trace_malformed_value_fails_the_launch(self):
        os.environ["LNPL_TRUST_INCOMING_TRACE"] = "maybe"
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[SHORTEN])
        self.assertIn("LNPL_TRUST_INCOMING_TRACE", str(cm.exception))

    def test_error_explicit_trust_incoming_trace_non_bool_argument_raises_typeerror(self):
        with self.assertRaises(TypeError) as cm:
            wsgi.build_app(sources=[SHORTEN], trust_incoming_trace="0")
        self.assertIn("trust_incoming_trace", str(cm.exception))


class RetryPassthroughWsgiTest(_ServerTestCase):
    """issue #176: retry/breaker/path reach HttpNetworkDriver through
    build_app()/make_wsgi_app, mirroring test_cli_capability_http.py's
    CLI-side proof of the same fix."""

    def test_a_declared_retry_recovers_after_two_failures_through_build_app(self):
        handler = _make_fail_n_handler(fail_count=2, fail_status=500)
        url = self.start(handler)
        source = _write_tmp(self, RETRY_CALL_SOURCE)
        app = wsgi.build_app(sources=[source],
                             endpoints={"PaymentGateway": url})

        body = json.dumps({"id": "11111111-1111-1111-1111-111111111111"}).encode("utf-8")
        status, _headers, parsed = call_wsgi(app, "POST", "/checkout/pay",
                                             body=body)

        self.assertEqual(status, 200, parsed)
        self.assertEqual(parsed["status"], "completed")
        self.assertEqual(len(handler.calls), 3)

    def test_a_declared_breaker_and_path_reach_the_built_apps_network_driver(self):
        source = _write_tmp(self, RETRY_CALL_SOURCE, name="mod2.lnpl")
        app = wsgi.build_app(sources=[source],
                             endpoints={"PaymentGateway": "http://example.invalid/"})

        cap = app.network._capabilities["PaymentGateway"]

        self.assertEqual(cap["breaker"], {"threshold": 5, "window_ms": 60000})
        self.assertEqual(cap["path"], "/pay/{}")


# --- issue #187 piece B: cache / network / token_provider / jwt_issuer /
# config / profile on the build_app() path --------------------------------

OPEN_SRC = """entity Report
    field
        id UUID

service Rollup

workflow GetReport
    read report
"""

GUARDED = os.path.join(REPO, "examples", "guarded.lnpl")

CALL_SRC = """
capability http PaymentGateway
    method post
entity Order
    field
        id UUID
service Checkout
workflow Pay
    call PaymentGateway as p
"""

SHORT_SECRET_CANARY = "LEAK9f3a"                      # 8 bytes
DSN_CANARY = "LEAK-DSN-9f3a1b2c"                       # 17 bytes
SUCCESS_SECRET = "LEAK-SUCCESS-" + "x" * 20            # 33 bytes


def _spi_registered(*entry_points):
    """Patch `importlib.metadata.entry_points` group-aware: unlike
    `registered()` above, a cache/network/token entry-point must not also
    show up in `build_app`'s extension-diagnostics pass (same module
    object, different group)."""
    def entry_points_for(group=None, **_kwargs):
        return [ep for ep in entry_points if ep.group == group]
    return mock.patch.object(importlib_metadata, "entry_points", entry_points_for)


def _spi_entry_point(name, value, group):
    return importlib_metadata.EntryPoint(name=name, value=value, group=group)


def _tmp_dir(testcase):
    import tempfile
    tmp_root = os.path.join(REPO, ".claude", "tmp")
    os.makedirs(tmp_root, exist_ok=True)
    box = tempfile.TemporaryDirectory(dir=tmp_root)
    testcase.addCleanup(box.cleanup)
    return box.name


def _write_toml(testcase, text, name="lnpl.toml"):
    return _write(_tmp_dir(testcase), name, text)


class RecordingCacheDriver(DemoCacheDriver):
    """A registered cache whose `close()` is observable, so a later build
    failure can be shown to release it."""

    instances = []

    def __init__(self, arg=None):
        super().__init__(arg)
        self.closed = False
        RecordingCacheDriver.instances.append(self)

    def close(self):
        self.closed = True


def make_recording_cache(arg=None):
    return RecordingCacheDriver(arg)


def make_angry_cache(arg=None):
    raise ConnectionError("refused: cache host unreachable")


def make_failing_token_provider():
    raise ConnectionError("refused: tokens host secret=FAKE-MARKER-187")


CACHE_GROUP = "lnpl.caches"
NETWORK_GROUP = "lnpl.networks"
TOKEN_GROUP = "lnpl.tokens"
DEMO_CACHE_EP = _spi_entry_point(
    "demo", "tests.cache_spi_fixture:make_demo_cache", CACHE_GROUP)
RECORDING_CACHE_EP = _spi_entry_point(
    "recording", "%s:make_recording_cache" % __name__, CACHE_GROUP)
ANGRY_CACHE_EP = _spi_entry_point(
    "angry", "%s:make_angry_cache" % __name__, CACHE_GROUP)
CUSTOM_NETWORK_EP = _spi_entry_point(
    "customnet", "tests.network_spi_fixture:make_demo_network", NETWORK_GROUP)
BROKEN_NETWORK_EP = _spi_entry_point(
    "brokennet", "tests.no_such_fixture_module:make_network", NETWORK_GROUP)
EXT_TOKEN_EP = _spi_entry_point(
    "extprov", "tests.token_spi_fixture:make_demo_token_provider", TOKEN_GROUP)
FAILING_TOKEN_EP = _spi_entry_point(
    "failprov", "%s:make_failing_token_provider" % __name__, TOKEN_GROUP)


class BuildAppPieceBEnvKeysTest(_EnvIsolatedTest):

    def test_normal_env_isolation_covers_the_six_new_variables(self):
        for name in ("LNPL_CACHE", "LNPL_NETWORK", "LNPL_TOKEN_PROVIDER",
                     "LNPL_JWT_ISSUER", "LNPL_CONFIG", "LNPL_PROFILE"):
            self.assertIn(name, self._ENV_KEYS)


class BuildAppImportTest(unittest.TestCase):

    def test_normal_fresh_subprocess_import_succeeds(self):
        # The config -> serve -> wsgi cycle only shows on a module's FIRST
        # import, so this one must run in a fresh interpreter.
        import subprocess
        import sys
        result = subprocess.run(
            [sys.executable, "-c", "import lnpl.wsgi"],
            env={**os.environ, "PYTHONPATH": os.path.join(REPO, "impl")},
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")


class BuildAppConfigTest(_EnvIsolatedTest):

    def _src(self):
        return _write_tmp(self, OPEN_SRC)

    def test_normal_build_app_lnpl_config_backend_overlay(self):
        toml = _write_toml(self, '[default]\nbackend = "doesnotexist:spec"\n')
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[self._src()], config=toml)
        self.assertEqual(str(cm.exception), "LNPL_BACKEND is not a recognized selector")

    def test_normal_lnpl_config_loads_the_file(self):
        from lnpl import config as config_module
        toml = _write_toml(self, '[default]\nlog_format = "json"\n')
        with mock.patch("lnpl.config.load_config",
                        wraps=config_module.load_config) as spy:
            wsgi.build_app(sources=[self._src()], config=toml)
        self.assertEqual(spy.call_count, 1)

    def test_normal_lnpl_config_env_loads_the_file(self):
        from lnpl import config as config_module
        toml = _write_toml(self, '[default]\nlog_format = "json"\n')
        os.environ["LNPL_CONFIG"] = toml
        with mock.patch("lnpl.config.load_config",
                        wraps=config_module.load_config) as spy:
            wsgi.build_app(sources=[self._src()])
        self.assertEqual(spy.call_args_list, [mock.call(toml, "default")])

    def test_boundary_lnpl_config_unset_cwd_lnpl_toml_not_read(self):
        source = self._src()
        cwd = _tmp_dir(self)
        _write(cwd, "lnpl.toml", '[default]\nbackend = "doesnotexist:spec"\n')
        previous = os.getcwd()
        os.chdir(cwd)
        self.addCleanup(os.chdir, previous)
        app = wsgi.build_app(sources=[source])
        self.assertIsNone(app.repository_factory)

    def test_boundary_lnpl_profile_empty_with_config_set_is_default(self):
        toml = _write_toml(self, '[default]\nlog_format = "json"\n')
        os.environ["LNPL_PROFILE"] = ""
        app = wsgi.build_app(sources=[self._src()], config=toml)
        self.assertIsInstance(app, wsgi.LnplWsgiApp)

    def test_boundary_lnpl_profile_alone_without_lnpl_config_is_ignored(self):
        os.environ["LNPL_PROFILE"] = "ghost-profile-nothing-here"
        app = wsgi.build_app(sources=[self._src()])
        self.assertIsInstance(app, wsgi.LnplWsgiApp)

    def test_error_lnpl_config_malformed_toml_names_config(self):
        toml = _write_toml(self, "[default\nbackend = \n")
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[self._src()], config=toml, profile="prod")
        self.assertEqual(str(cm.exception), "LNPL_CONFIG is not a valid configuration file")

    def test_error_lnpl_config_missing_file_names_config(self):
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[self._src()], config="/no/such/file.toml",
                           profile="prod")
        self.assertEqual(str(cm.exception), "LNPL_CONFIG is not a valid configuration file")

    def test_error_lnpl_profile_missing_from_valid_file_names_profile(self):
        toml = _write_toml(self, '[default]\nlog_format = "json"\n')
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[self._src()], config=toml, profile="ghost")
        self.assertEqual(str(cm.exception), "LNPL_PROFILE is not a recognized profile")

    def test_error_lnpl_profile_env_missing_from_valid_file_names_profile(self):
        toml = _write_toml(self, '[default]\nlog_format = "json"\n')
        os.environ["LNPL_CONFIG"] = toml
        os.environ["LNPL_PROFILE"] = "ghost"
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[self._src()])
        self.assertEqual(str(cm.exception), "LNPL_PROFILE is not a recognized profile")

    def test_error_lnpl_config_directory_path_wrapped(self):
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[self._src()], config=_tmp_dir(self))
        self.assertEqual(str(cm.exception), "LNPL_CONFIG is not a valid configuration file")

    def test_error_lnpl_config_bad_utf8_wrapped(self):
        path = os.path.join(_tmp_dir(self), "lnpl.toml")
        with open(path, "wb") as fh:
            fh.write(b'[default]\nlog_format = "\xff\xfe"\n')
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[self._src()], config=path)
        self.assertEqual(str(cm.exception), "LNPL_CONFIG is not a valid configuration file")

    def test_normal_config_argument_beats_invalid_env(self):
        toml = _write_toml(self, '[default]\nlog_format = "json"\n')
        os.environ["LNPL_CONFIG"] = "/no/such/env/config.toml"
        app = wsgi.build_app(sources=[self._src()], config=toml)
        self.assertIsInstance(app, wsgi.LnplWsgiApp)

    def test_normal_profile_argument_beats_env(self):
        toml = _write_toml(self, '[default]\nlog_format = "json"\n')
        os.environ["LNPL_PROFILE"] = "ghost-env-profile"
        app = wsgi.build_app(sources=[self._src()], config=toml, profile="default")
        self.assertIsInstance(app, wsgi.LnplWsgiApp)

    def test_normal_config_empty_string_explicit_arg_is_unset(self):
        from lnpl import config as config_module
        with mock.patch("lnpl.config.load_config",
                        wraps=config_module.load_config) as spy:
            app = wsgi.build_app(sources=[self._src()], config="")
        self.assertEqual(spy.call_count, 0)
        self.assertIsInstance(app, wsgi.LnplWsgiApp)

    def test_normal_profile_empty_string_explicit_arg_is_default(self):
        toml = _write_toml(self, '[default]\nlog_format = "json"\n')
        app = wsgi.build_app(sources=[self._src()], config=toml, profile="")
        self.assertIsInstance(app, wsgi.LnplWsgiApp)

    def test_normal_cfg_endpoints_reaches_resolve_network(self):
        os.environ.pop("LNPL_ENDPOINT_PAYMENTGATEWAY", None)
        toml = _write_toml(
            self, '[default.endpoints]\nPaymentGateway = "http://cfg-endpoint.example/pay"\n')
        app = wsgi.build_app(sources=[_write_tmp(self, CALL_SRC)], config=toml)
        self.assertIsNotNone(app.network)

    def test_normal_cfg_secrets_jwt_tier_turns_on_verification(self):
        os.environ["LNPL_TEST_T187_CFG_SECRET"] = "c" * 32
        self.addCleanup(os.environ.pop, "LNPL_TEST_T187_CFG_SECRET", None)
        toml = _write_toml(self, '[default.secrets]\njwt = "LNPL_TEST_T187_CFG_SECRET"\n')
        app = wsgi.build_app(sources=[self._src()], config=toml)
        self.assertIsInstance(app.token_provider, HmacTokenProvider)
        self.assertEqual(app.jwt_secret_env, "LNPL_TEST_T187_CFG_SECRET")

    def _two_profile_toml(self):
        db = os.path.join(_tmp_dir(self), "prod.db")
        return _write_toml(
            self, '[default]\nbackend = "fake"\n\n[prod]\nbackend = "sqlite:%s"\n' % db)

    def test_normal_default_profile_keeps_the_default_backend(self):
        app = wsgi.build_app(sources=[self._src()], config=self._two_profile_toml())
        self.assertIsNone(app.repository_factory)

    def test_normal_profile_argument_applies_its_overlay(self):
        app = wsgi.build_app(sources=[self._src()], config=self._two_profile_toml(),
                             profile="prod")
        self.assertIsNotNone(app.repository_factory)
        repo = app.repository_factory()
        self.addCleanup(repo.close)

    def test_normal_lnpl_profile_env_applies_its_overlay(self):
        os.environ["LNPL_PROFILE"] = "prod"
        app = wsgi.build_app(sources=[self._src()], config=self._two_profile_toml())
        self.assertIsNotNone(app.repository_factory)
        repo = app.repository_factory()
        self.addCleanup(repo.close)


NOTICE_PREFIX = "lnpl build_app: LNPL_CONFIG sets "


class BuildAppConfigIgnoredKeysTest(_EnvIsolatedTest):
    """The file's `log_format`/`trace_exporter` are not applied on the
    build_app() path (only backend / secrets.jwt / endpoints are); that
    scope cut is announced on stderr, naming keys, never values."""

    def _build(self, toml_text):
        toml = _write_toml(self, toml_text)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            app = wsgi.build_app(sources=[_write_tmp(self, OPEN_SRC)], config=toml)
        notices = [line for line in err.getvalue().splitlines()
                   if line.startswith(NOTICE_PREFIX)]
        return app, notices

    def test_normal_notice_names_both_ignored_keys_and_their_env_vars(self):
        app, notices = self._build(
            '[default]\nlog_format = "json"\ntrace_exporter = "stderr-json"\n')
        self.assertEqual(len(notices), 1)
        for name in ("log_format", "trace_exporter",
                     "LNPL_LOG_FORMAT", "LNPL_TRACE_EXPORTER"):
            self.assertIn(name, notices[0])
        self.assertNotIn("json", notices[0])
        self.assertEqual(app.log_format, "text")
        self.assertIsNone(app.exporter)

    def test_boundary_notice_names_only_the_key_the_file_sets(self):
        app, notices = self._build('[default]\ntrace_exporter = "stderr-json"\n')
        self.assertEqual(len(notices), 1)
        self.assertIn("trace_exporter", notices[0])
        self.assertNotIn("log_format", notices[0])
        self.assertIsNone(app.exporter)

    def test_boundary_no_notice_when_the_file_sets_neither_key(self):
        app, notices = self._build('[default]\nbackend = "fake"\n')
        self.assertEqual(notices, [])
        self.assertEqual(app.log_format, "text")

    def test_error_notice_never_carries_the_values(self):
        _app, notices = self._build(
            '[default]\nlog_format = "json"\ntrace_exporter = "no-such-exporter-x9"\n')
        self.assertEqual(len(notices), 1)
        self.assertNotIn("no-such-exporter-x9", notices[0])


class BuildAppBackendOverlayTest(_EnvIsolatedTest):

    def test_normal_explicit_backend_beats_config_file(self):
        toml = _write_toml(self, '[default]\nbackend = "doesnotexist:spec"\n')
        app = wsgi.build_app(sources=[_write_tmp(self, OPEN_SRC)], config=toml,
                             backend="fake")
        self.assertIsNone(app.repository_factory)


class BuildAppCacheTest(_EnvIsolatedTest):

    def setUp(self):
        super().setUp()
        RecordingCacheDriver.instances.clear()

    def _src(self):
        return _write_tmp(self, OPEN_SRC)

    def test_normal_registered_cache_driver_receives_a_write(self):
        import socket
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]
        probe.close()
        with _spi_registered(DEMO_CACHE_EP):
            app = wsgi.build_app(
                sources=[GUARDED],
                endpoints={"token": "http://127.0.0.1:%d/" % dead_port},
                cache="demo:hello")
        self.assertIsInstance(app.cache, DemoCacheDriver)
        body = json.dumps({"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
                           "cachedAt": "2026-07-31T09:00:00Z",
                           "retryBudget": 1}).encode("utf-8")
        call_wsgi(app, "POST", "/token-service/retrieve-with-cache", body=body)
        self.assertTrue(app.cache.store, "the registered cache never received a write")

    def test_normal_lnpl_cache_env_selects_the_registered_driver(self):
        os.environ["LNPL_CACHE"] = "demo:from-env"
        with _spi_registered(DEMO_CACHE_EP):
            app = wsgi.build_app(sources=[self._src()])
        self.assertIsInstance(app.cache, DemoCacheDriver)
        self.assertEqual(app.cache.arg, "from-env")

    def test_error_unknown_cache_selector_fails_the_launch(self):
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[self._src()], cache="redis:host")
        self.assertEqual(str(cm.exception), "LNPL_CACHE is not a recognized selector")

    def test_error_lnpl_cache_env_unknown_selector_fails_the_launch(self):
        os.environ["LNPL_CACHE"] = "redis:host"
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[self._src()])
        self.assertEqual(str(cm.exception), "LNPL_CACHE is not a recognized selector")

    def test_error_broken_cache_factory_wrapped_value_free(self):
        with _spi_registered(ANGRY_CACHE_EP):
            with self.assertRaises(wsgi.WsgiConfigError) as cm:
                wsgi.build_app(sources=[self._src()], cache="angry:x")
        self.assertEqual(str(cm.exception), "LNPL_CACHE is not a recognized selector")

    def test_boundary_lnpl_cache_empty_string_is_unset(self):
        app = wsgi.build_app(sources=[self._src()], cache="")
        self.assertIsNone(app.cache)

    def test_boundary_lnpl_cache_env_empty_string_is_unset(self):
        os.environ["LNPL_CACHE"] = ""
        app = wsgi.build_app(sources=[self._src()])
        self.assertIsNone(app.cache)

    def test_normal_cache_argument_beats_invalid_env(self):
        os.environ["LNPL_CACHE"] = "also-nonexistent"
        app = wsgi.build_app(sources=[self._src()], cache="fake")
        self.assertIsNone(app.cache)

    def test_normal_cache_closed_on_later_build_failure(self):
        with _spi_registered(RECORDING_CACHE_EP):
            with self.assertRaises(wsgi.WsgiConfigError) as cm:
                wsgi.build_app(sources=[self._src()], cache="recording:x",
                               network="bogus-selector")
        self.assertEqual(str(cm.exception), "LNPL_NETWORK is not a recognized selector")
        self.assertEqual(len(RecordingCacheDriver.instances), 1)
        self.assertIs(RecordingCacheDriver.instances[0].closed, True)

    def test_normal_cache_left_open_on_a_successful_build(self):
        with _spi_registered(RECORDING_CACHE_EP):
            app = wsgi.build_app(sources=[self._src()], cache="recording:x")
        self.assertIs(app.cache, RecordingCacheDriver.instances[0])
        self.assertIs(app.cache.closed, False)


class BuildAppNetworkTest(_EnvIsolatedTest):

    def setUp(self):
        super().setUp()
        os.environ.pop("LNPL_ENDPOINT_PAYMENTGATEWAY", None)

    def test_normal_lnpl_network_fake_skips_endpoint_validation_even_with_declared_targets(self):
        app = wsgi.build_app(sources=[_write_tmp(self, UNBOUND_CALL_SOURCE)],
                             network="fake")
        self.assertIsNone(app.network)

    def test_normal_lnpl_network_env_fake_skips_endpoint_validation(self):
        os.environ["LNPL_NETWORK"] = "fake"
        app = wsgi.build_app(sources=[_write_tmp(self, UNBOUND_CALL_SOURCE)])
        self.assertIsNone(app.network)

    def test_normal_unset_lnpl_network_still_validates_unmapped_targets(self):
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[_write_tmp(self, UNBOUND_CALL_SOURCE)])
        self.assertIn("PaymentGateway", str(cm.exception))
        self.assertIn("LNPL_ENDPOINT_PAYMENTGATEWAY", str(cm.exception))

    def test_normal_network_http_explicit_with_endpoints(self):
        app = wsgi.build_app(sources=[_write_tmp(self, UNBOUND_CALL_SOURCE)],
                             network="http",
                             endpoints={"PaymentGateway": "http://example.invalid/pay"})
        self.assertIsInstance(app.network, wsgi.HttpNetworkDriver)

    def test_error_network_http_explicit_still_validates_unmapped_targets(self):
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[_write_tmp(self, UNBOUND_CALL_SOURCE)],
                           network="http")
        self.assertIn("LNPL_ENDPOINT_PAYMENTGATEWAY", str(cm.exception))

    def test_normal_registered_network_entrypoint_beyond_fake(self):
        with _spi_registered(CUSTOM_NETWORK_EP):
            app = wsgi.build_app(sources=[_write_tmp(self, OPEN_SRC)],
                                 network="customnet:myarg")
        self.assertIsInstance(app.network, DemoNetworkDriver)
        self.assertEqual(app.network.arg, "myarg")

    def test_error_unknown_network_selector_fails_the_launch(self):
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[_write_tmp(self, OPEN_SRC)], network="bogus:spec")
        self.assertEqual(str(cm.exception), "LNPL_NETWORK is not a recognized selector")

    def test_error_lnpl_network_env_unknown_selector_fails_the_launch(self):
        os.environ["LNPL_NETWORK"] = "bogus:spec"
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[_write_tmp(self, OPEN_SRC)])
        self.assertEqual(str(cm.exception), "LNPL_NETWORK is not a recognized selector")

    def test_error_broken_network_entrypoint_wrapped_value_free(self):
        with _spi_registered(BROKEN_NETWORK_EP):
            with self.assertRaises(wsgi.WsgiConfigError) as cm:
                wsgi.build_app(sources=[_write_tmp(self, OPEN_SRC)],
                               network="brokennet:arg")
        self.assertEqual(str(cm.exception), "LNPL_NETWORK is not a recognized selector")

    def test_boundary_lnpl_network_empty_string_is_unset(self):
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[_write_tmp(self, UNBOUND_CALL_SOURCE)], network="")
        self.assertIn("PaymentGateway", str(cm.exception))
        self.assertIn("LNPL_ENDPOINT_PAYMENTGATEWAY", str(cm.exception))

    def test_normal_network_argument_beats_invalid_env(self):
        os.environ["LNPL_NETWORK"] = "bogus-network-invalid"
        app = wsgi.build_app(sources=[_write_tmp(self, OPEN_SRC)], network="fake")
        self.assertIsNone(app.network)


class BuildAppTokenProviderTest(_EnvIsolatedTest):

    def _src(self):
        return _write_tmp(self, OPEN_SRC)

    def _secret(self, name, value="k" * 32):
        os.environ[name] = value
        self.addCleanup(os.environ.pop, name, None)
        return name

    def _iss(self, app):
        token = app.token_provider.issue("alice", "aud")
        return app.token_provider.verify(token, "aud")["iss"]

    def test_normal_external_token_provider_builds_with_secret_env_unset(self):
        with _spi_registered(EXT_TOKEN_EP):
            app = wsgi.build_app(sources=[self._src()], token_provider="extprov")
        self.assertIsInstance(app.token_provider, DemoTokenProvider)

    def test_normal_lnpl_token_provider_env_selects_the_external_provider(self):
        os.environ["LNPL_TOKEN_PROVIDER"] = "extprov"
        with _spi_registered(EXT_TOKEN_EP):
            app = wsgi.build_app(sources=[self._src()])
        self.assertIsInstance(app.token_provider, DemoTokenProvider)

    def test_normal_hmac_with_secret_env_unset_builds_with_no_token_provider(self):
        app = wsgi.build_app(sources=[self._src()], token_provider="hmac")
        self.assertIsNone(app.token_provider)

    def test_error_lnpl_token_provider_missing_secret_byte_identical(self):
        os.environ.pop("LNPL_TEST_T187_SECRET_MISSING", None)
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[self._src()],
                           jwt_secret_env="LNPL_TEST_T187_SECRET_MISSING")
        self.assertEqual(str(cm.exception),
                         "LNPL_TEST_T187_SECRET_MISSING is not set in the environment")

    def test_error_lnpl_token_provider_short_secret_byte_identical(self):
        name = self._secret("LNPL_TEST_T187_SHORT", "short")
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[self._src()], jwt_secret_env=name)
        self.assertEqual(
            str(cm.exception),
            "the JWT signing secret must be at least 32 bytes, got 5 "
            "(from LNPL_TEST_T187_SHORT)")

    def test_boundary_lnpl_jwt_secret_env_empty_string_is_unset(self):
        os.environ["LNPL_JWT_SECRET_ENV"] = ""
        app = wsgi.build_app(sources=[self._src()])
        self.assertIsNone(app.token_provider)
        os.environ.pop("LNPL_JWT_SECRET_ENV")
        app = wsgi.build_app(sources=[self._src()], jwt_secret_env="")
        self.assertIsNone(app.token_provider)

    def test_normal_positive_jwt_issuer_reaches_minted_token(self):
        name = self._secret("LNPL_TEST_K5_SECRET")
        app = wsgi.build_app(sources=[self._src()], jwt_secret_env=name,
                             jwt_issuer="my-custom-issuer")
        self.assertEqual(self._iss(app), "my-custom-issuer")

    def test_normal_lnpl_jwt_issuer_env_reaches_minted_token(self):
        name = self._secret("LNPL_TEST_K5_ENV_SECRET")
        os.environ["LNPL_JWT_ISSUER"] = "env-issuer"
        app = wsgi.build_app(sources=[self._src()], jwt_secret_env=name)
        self.assertEqual(self._iss(app), "env-issuer")

    def test_boundary_lnpl_jwt_issuer_empty_is_default_issuer(self):
        name = self._secret("LNPL_TEST_K5_SECRET_2", "m" * 32)
        app = wsgi.build_app(sources=[self._src()], jwt_secret_env=name, jwt_issuer="")
        self.assertEqual(self._iss(app), "lnpl")

    def test_boundary_lnpl_jwt_issuer_env_empty_is_default_issuer(self):
        name = self._secret("LNPL_TEST_K5_SECRET_3", "n" * 32)
        os.environ["LNPL_JWT_ISSUER"] = ""
        app = wsgi.build_app(sources=[self._src()], jwt_secret_env=name)
        self.assertEqual(self._iss(app), "lnpl")

    def test_boundary_lnpl_token_provider_empty_is_hmac_default(self):
        name = self._secret("LNPL_TEST_T187_TP_EMPTY")
        app = wsgi.build_app(sources=[self._src()], jwt_secret_env=name,
                             token_provider="")
        self.assertIsInstance(app.token_provider, HmacTokenProvider)

    def test_boundary_resolve_token_provider_empty_name_is_hmac_default(self):
        # build_app's inline "" collapse already hands None here; this pins
        # the resolver's own guard, which the build_app-level test above
        # cannot see on its own.
        name = self._secret("LNPL_TEST_T187_TP_RESOLVER")
        self.assertIsNone(wsgi._resolve_token_provider(None, provider_name=""))
        self.assertIsInstance(wsgi._resolve_token_provider(name, provider_name=""),
                              HmacTokenProvider)

    def test_boundary_lnpl_token_provider_env_empty_is_hmac_default(self):
        name = self._secret("LNPL_TEST_T187_TP_ENV_EMPTY")
        os.environ["LNPL_TOKEN_PROVIDER"] = ""
        app = wsgi.build_app(sources=[self._src()], jwt_secret_env=name)
        self.assertIsInstance(app.token_provider, HmacTokenProvider)

    def test_error_unknown_token_provider_fails_the_launch(self):
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[self._src()], token_provider="bogus")
        self.assertEqual(str(cm.exception),
                         "LNPL_TOKEN_PROVIDER is not a recognized token provider")

    def test_error_lnpl_token_provider_env_unknown_fails_the_launch(self):
        os.environ["LNPL_TOKEN_PROVIDER"] = "bogus"
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[self._src()])
        self.assertEqual(str(cm.exception),
                         "LNPL_TOKEN_PROVIDER is not a recognized token provider")

    def test_normal_token_provider_argument_beats_invalid_env(self):
        name = self._secret("LNPL_TEST_T187_TP_ARG")
        os.environ["LNPL_TOKEN_PROVIDER"] = "bogus-provider-invalid"
        app = wsgi.build_app(sources=[self._src()], jwt_secret_env=name,
                             token_provider="hmac")
        self.assertIsInstance(app.token_provider, HmacTokenProvider)

    def test_normal_jwt_issuer_argument_beats_env(self):
        name = self._secret("LNPL_TEST_T187_ISS_ARG")
        os.environ["LNPL_JWT_ISSUER"] = "env-issuer-should-be-overridden"
        app = wsgi.build_app(sources=[self._src()], jwt_secret_env=name,
                             jwt_issuer="arg-issuer")
        self.assertEqual(self._iss(app), "arg-issuer")

    def test_error_broken_token_provider_factory_wrapped_value_free(self):
        import traceback
        with _spi_registered(FAILING_TOKEN_EP):
            with self.assertRaises(wsgi.WsgiConfigError) as cm:
                wsgi.build_app(sources=[self._src()], token_provider="failprov")
        exc = cm.exception
        self.assertEqual(str(exc),
                         "LNPL_TOKEN_PROVIDER is not a recognized token provider")
        formatted = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self.assertNotIn("FAKE-MARKER-187", formatted)


class SecretLeakTest(_EnvIsolatedTest):
    """No secret value — the JWT secret, a DSN password inside LNPL_BACKEND
    or LNPL_CACHE — reaches an error's text, its FULL formatted traceback
    (a chained `__cause__` would carry it there), captured stderr, or a
    /-/readyz body."""

    def _src(self):
        return _write_tmp(self, OPEN_SRC)

    def _failing_build(self, **kwargs):
        import traceback
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            with self.assertRaises(wsgi.WsgiConfigError) as cm:
                wsgi.build_app(sources=[self._src()], **kwargs)
        exc = cm.exception
        formatted = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        return exc, formatted, err.getvalue()

    def test_error_canary_absent_from_secret_short_failure(self):
        os.environ["LNPL_TEST_LEAK_SECRET"] = SHORT_SECRET_CANARY
        self.addCleanup(os.environ.pop, "LNPL_TEST_LEAK_SECRET", None)
        exc, formatted, err = self._failing_build(jwt_secret_env="LNPL_TEST_LEAK_SECRET")
        self.assertIn("LNPL_TEST_LEAK_SECRET", str(exc))
        self.assertNotIn(SHORT_SECRET_CANARY, str(exc))
        self.assertNotIn(SHORT_SECRET_CANARY, formatted)
        self.assertNotIn(SHORT_SECRET_CANARY, err)

    def test_error_canary_absent_from_backend_dsn_failure(self):
        exc, formatted, err = self._failing_build(
            backend="postgres://user:%s@nonexistent-host/db" % DSN_CANARY)
        self.assertEqual(str(exc), "LNPL_BACKEND is not a recognized selector")
        self.assertIsNone(exc.__cause__)
        self.assertNotIn(DSN_CANARY, formatted)
        self.assertNotIn(DSN_CANARY, err)

    def test_error_canary_absent_from_cache_spec_failure(self):
        exc, formatted, err = self._failing_build(
            cache="redis://:%s@nonexistent-host:1/0" % DSN_CANARY)
        self.assertEqual(str(exc), "LNPL_CACHE is not a recognized selector")
        self.assertIsNone(exc.__cause__)
        self.assertNotIn(DSN_CANARY, formatted)
        self.assertNotIn(DSN_CANARY, err)

    def test_normal_canary_absent_from_readyz_200_then_503(self):
        os.environ["LNPL_TEST_LEAK_SUCCESS"] = SUCCESS_SECRET
        self.addCleanup(os.environ.pop, "LNPL_TEST_LEAK_SUCCESS", None)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            app = wsgi.build_app(sources=[self._src()],
                                 jwt_secret_env="LNPL_TEST_LEAK_SUCCESS")
            status, _headers, body = call_wsgi(app, "GET", "/-/readyz")
            self.assertEqual(status, 200)
            self.assertNotIn(SUCCESS_SECRET, json.dumps(body))
            del os.environ["LNPL_TEST_LEAK_SUCCESS"]
            status, _headers, body = call_wsgi(app, "GET", "/-/readyz")
        self.assertEqual(status, 503)
        self.assertEqual(body["checks"], ["jwt-secret-env"])
        self.assertNotIn(SUCCESS_SECRET, json.dumps(body))
        self.assertNotIn(SUCCESS_SECRET, err.getvalue())


# --- issue #192 piece A: the JWT secret from a file, and the source
# precedence shared by serve, build_app and `lnpl config check` -----------

FILE_SECRET = b"FAKE-SECRET-192-file-source-aaaaaaaaaaaa"     # 40 bytes
OTHER_SECRET = b"FAKE-SECRET-192-other-secret-bbbbbbbbbbb"    # 40 bytes

JWT_SRC = """entity Report
    field
        id UUID

service Rollup
    security
        jwt

workflow GetReport
    read report
"""
JWT_PATH = "/rollup/get-report"


NUL_PATH_TAIL = "FAKE-SECRET-192-nul\x00tail"


def _fifo(testcase):
    """A FIFO with no writer: `open()` on it blocks until one appears."""
    path = os.path.join(_tmp_dir(testcase), "jwt-fifo")
    os.mkfifo(path)
    return path


def call_with_deadline(testcase, fn, fifo, timeout=5.0):
    """issue #192 r1 F2: run `fn()` in a daemon thread and fail — instead of
    hanging the suite — when it is still running after `timeout` seconds,
    i.e. when it blocked opening `fifo`. A blocked reader is released by
    opening the FIFO for writing so the thread can finish. Returns
    `fn()`'s result, or re-raises its exception."""
    box = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:  # re-raised in the test thread
            box["exc"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        try:
            os.close(os.open(fifo, os.O_WRONLY | os.O_NONBLOCK))
        except OSError:
            pass
        thread.join(timeout)
        testcase.fail("blocked on a FIFO for more than %.0f s" % timeout)
    if "exc" in box:
        raise box["exc"]
    return box.get("value")


def _secret_file(testcase, data, name="jwt-secret"):
    path = os.path.join(_tmp_dir(testcase), name)
    with open(path, "wb") as fh:
        fh.write(data)
    return path


class SecretFileReaderTest(unittest.TestCase):
    """D3/D4: `_read_secret_file` returns the bytes minus ONE trailing
    newline, or a WsgiConfigError naming only the caller's role."""

    def _refused(self, path):
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi._read_secret_file(path, "ROLE-X")
        exc = cm.exception
        self.assertIsNone(exc.__cause__)
        self.assertNotIn(path, str(exc))
        self.assertNotIn("FAKE-SECRET-192", str(exc))
        return str(exc)

    def test_normal_returns_the_bytes(self):
        path = _secret_file(self, FILE_SECRET)
        self.assertEqual(wsgi._read_secret_file(path, "ROLE-X"), FILE_SECRET)

    def test_boundary_one_trailing_lf_is_stripped(self):
        path = _secret_file(self, FILE_SECRET + b"\n")
        self.assertEqual(wsgi._read_secret_file(path, "ROLE-X"), FILE_SECRET)

    def test_boundary_one_trailing_crlf_is_stripped(self):
        path = _secret_file(self, FILE_SECRET + b"\r\n")
        self.assertEqual(wsgi._read_secret_file(path, "ROLE-X"), FILE_SECRET)

    def test_boundary_only_one_newline_is_stripped(self):
        path = _secret_file(self, FILE_SECRET + b"\n\n")
        self.assertEqual(wsgi._read_secret_file(path, "ROLE-X"), FILE_SECRET + b"\n")

    def test_boundary_lone_cr_is_kept(self):
        path = _secret_file(self, FILE_SECRET + b"\r")
        self.assertEqual(wsgi._read_secret_file(path, "ROLE-X"), FILE_SECRET + b"\r")

    def test_boundary_tilde_path_is_expanded(self):
        path = _secret_file(self, FILE_SECRET)
        home = os.path.dirname(path)
        with mock.patch.dict(os.environ, {"HOME": home}):
            self.assertEqual(wsgi._read_secret_file("~/jwt-secret", "ROLE-X"),
                             FILE_SECRET)

    def test_error_missing(self):
        path = os.path.join(_tmp_dir(self), "absent")
        self.assertEqual(self._refused(path), "ROLE-X names a file that does not exist")

    def test_error_directory_cannot_be_read(self):
        path = _tmp_dir(self)
        self.assertEqual(self._refused(path), "ROLE-X names a file that cannot be read")

    def test_error_permission_denied_cannot_be_read(self):
        if os.geteuid() == 0:
            self.skipTest("root reads a mode-000 file")
        path = _secret_file(self, FILE_SECRET)
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o600)
        self.assertEqual(self._refused(path), "ROLE-X names a file that cannot be read")

    def test_error_empty_file(self):
        path = _secret_file(self, b"")
        self.assertEqual(self._refused(path), "ROLE-X names an empty file")

    def test_boundary_only_a_newline_is_empty(self):
        path = _secret_file(self, b"\n")
        self.assertEqual(self._refused(path), "ROLE-X names an empty file")

    def test_boundary_exactly_the_cap_is_read(self):
        data = b"k" * wsgi.MAX_SECRET_FILE_BYTES
        path = _secret_file(self, data)
        self.assertEqual(wsgi._read_secret_file(path, "ROLE-X"), data)

    def test_error_oversize(self):
        path = _secret_file(self, b"k" * (wsgi.MAX_SECRET_FILE_BYTES + 1))
        self.assertEqual(self._refused(path),
                         "ROLE-X names a file larger than 65536 bytes")

    def test_error_relative_path(self):
        self.assertEqual(self._refused("rel/secret"), "ROLE-X must be an absolute path")

    def test_error_fifo_is_refused_without_blocking(self):
        fifo = _fifo(self)
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            call_with_deadline(self, lambda: wsgi._read_secret_file(fifo, "ROLE-X"), fifo)
        self.assertEqual(str(cm.exception), "ROLE-X names a file that cannot be read")
        self.assertIsNone(cm.exception.__cause__)

    def test_error_character_device_is_refused(self):
        # /dev/null used to read as 0 bytes ("empty file"); a device is not
        # a regular file, so it is refused before any read.
        self.assertEqual(self._refused("/dev/null"),
                         "ROLE-X names a file that cannot be read")

    def test_error_nul_in_path_is_a_config_error(self):
        path = os.path.join(_tmp_dir(self), NUL_PATH_TAIL)
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi._read_secret_file(path, "ROLE-X")
        self.assertEqual(str(cm.exception), "ROLE-X names a file that cannot be read")
        self.assertIsNone(cm.exception.__cause__)
        self.assertNotIn("FAKE-SECRET-192", str(cm.exception))

    def test_normal_symlink_to_a_regular_file_is_followed(self):
        target = _secret_file(self, FILE_SECRET + b"\n")
        link = os.path.join(os.path.dirname(target), "jwt-link")
        os.symlink(target, link)
        self.assertEqual(wsgi._read_secret_file(link, "ROLE-X"), FILE_SECRET)

    def test_error_symlink_to_a_directory_is_refused(self):
        box = _tmp_dir(self)
        link = os.path.join(box, "dir-link")
        os.symlink(_tmp_dir(self), link)
        self.assertEqual(self._refused(link), "ROLE-X names a file that cannot be read")

    def test_error_dangling_symlink_does_not_exist(self):
        box = _tmp_dir(self)
        link = os.path.join(box, "dangling")
        os.symlink(os.path.join(box, "absent"), link)
        self.assertEqual(self._refused(link), "ROLE-X names a file that does not exist")

    def test_boundary_empty_path_is_not_absolute(self):
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi._read_secret_file("", "ROLE-X")
        self.assertEqual(str(cm.exception), "ROLE-X must be an absolute path")


class SecretSourceResolverTest(unittest.TestCase):
    """D6: the two-tier rule — explicit env-name + explicit file refused;
    one explicit kind beats lnpl.toml; else the config form decides."""

    def _cfg(self, jwt):
        from lnpl.config import ResolvedConfig
        return ResolvedConfig(secrets={} if jwt is None else {"jwt": jwt})

    def _resolve(self, env_name, file_path, cfg):
        return wsgi._resolve_jwt_secret_source(env_name, file_path, cfg, "ENV-ROLE", "FILE-ROLE")

    def test_error_both_given_refused(self):
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            self._resolve("SOME_ENV", "/run/secrets/jwt", None)
        self.assertEqual(str(cm.exception), "ENV-ROLE and FILE-ROLE both name the JWT "
                                            "signing secret — give exactly one")
        self.assertIsNone(cm.exception.__cause__)

    def test_boundary_empty_env_counts_as_given(self):
        with self.assertRaises(wsgi.WsgiConfigError):
            self._resolve("", "/run/secrets/jwt", None)

    def test_normal_env_only(self):
        self.assertEqual(self._resolve("SOME_ENV", None, self._cfg("CFG_ENV")),
                         wsgi.JwtSecretSource("env", "SOME_ENV", "ENV-ROLE"))

    def test_normal_file_only_beats_config(self):
        self.assertEqual(self._resolve(None, "/run/secrets/jwt", self._cfg("CFG_ENV")),
                         wsgi.JwtSecretSource("file", "/run/secrets/jwt", "FILE-ROLE"))

    def test_normal_config_name(self):
        self.assertEqual(self._resolve(None, None, self._cfg("CFG_ENV")),
                         wsgi.JwtSecretSource("env", "CFG_ENV", "lnpl.toml secrets.jwt"))

    def test_normal_config_file_ref(self):
        from lnpl.config import SecretFileRef
        self.assertEqual(
            self._resolve(None, None, self._cfg(SecretFileRef("/run/secrets/jwt"))),
            wsgi.JwtSecretSource("file", "/run/secrets/jwt", "lnpl.toml secrets.jwt.file"))

    def test_boundary_nothing_is_none(self):
        self.assertIsNone(self._resolve(None, None, None))
        self.assertIsNone(self._resolve(None, None, self._cfg(None)))

    def test_boundary_env_resolver_ignores_a_file_ref(self):
        import types as _types
        from lnpl.config import SecretFileRef
        cfg = self._cfg(SecretFileRef("/run/secrets/jwt"))
        self.assertIsNone(wsgi._resolve_jwt_secret_env(
            _types.SimpleNamespace(jwt_secret_env=None), cfg))


class BuildAppSecretFileTest(_EnvIsolatedTest):
    """D5/D6/D8 on the build_app path: `jwt_secret_file` argument,
    LNPL_JWT_SECRET_FILE and lnpl.toml `jwt = { file }` each yield a
    verifying provider; errors name LNPL_JWT_SECRET_FILE, never the path."""

    def _src(self):
        return _write_tmp(self, JWT_SRC)

    def _post(self, app, secret):
        from lnpl.drivers import audience_for_path
        token = HmacTokenProvider(secret).issue("u", audience_for_path(JWT_PATH))
        return call_wsgi(app, "POST", JWT_PATH, body=b"{}",
                         headers={"Authorization": "Bearer " + token,
                                  "Content-Type": "application/json"})

    def _assert_verifies_only(self, app, secret):
        status, _h, _body = self._post(app, secret)
        self.assertEqual(status, 200)
        status, _h, body = self._post(app, OTHER_SECRET if secret != OTHER_SECRET else FILE_SECRET)
        self.assertEqual(status, 401)
        self.assertEqual(body["code"], "auth-invalid")

    def _refused(self, **kwargs):
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            wsgi.build_app(sources=[self._src()], **kwargs)
        exc = cm.exception
        self.assertIsNone(exc.__cause__)
        self.assertNotIn("FAKE-SECRET-192", str(exc))
        return str(exc)

    def test_normal_argument_verifies(self):
        app = wsgi.build_app(sources=[self._src()],
                             jwt_secret_file=_secret_file(self, FILE_SECRET + b"\n"))
        self.assertIsInstance(app.token_provider, HmacTokenProvider)
        self._assert_verifies_only(app, FILE_SECRET)

    def test_normal_env_var_verifies(self):
        os.environ["LNPL_JWT_SECRET_FILE"] = _secret_file(self, FILE_SECRET)
        app = wsgi.build_app(sources=[self._src()])
        self._assert_verifies_only(app, FILE_SECRET)

    def test_normal_config_file_form_verifies(self):
        path = _secret_file(self, FILE_SECRET)
        toml = _write_toml(self, '[default.secrets]\njwt = { file = "%s" }\n' % path)
        app = wsgi.build_app(sources=[self._src()], config=toml)
        self._assert_verifies_only(app, FILE_SECRET)

    def test_normal_argument_beats_env(self):
        os.environ["LNPL_JWT_SECRET_FILE"] = _secret_file(self, OTHER_SECRET, "other")
        app = wsgi.build_app(sources=[self._src()],
                             jwt_secret_file=_secret_file(self, FILE_SECRET))
        self._assert_verifies_only(app, FILE_SECRET)

    def test_normal_explicit_file_beats_config_name(self):
        os.environ["LNPL_T192_CFG_SECRET"] = OTHER_SECRET.decode()
        self.addCleanup(os.environ.pop, "LNPL_T192_CFG_SECRET", None)
        toml = _write_toml(self, '[default.secrets]\njwt = "LNPL_T192_CFG_SECRET"\n')
        app = wsgi.build_app(sources=[self._src()], config=toml,
                             jwt_secret_file=_secret_file(self, FILE_SECRET))
        self._assert_verifies_only(app, FILE_SECRET)

    def test_boundary_empty_argument_is_unset(self):
        app = wsgi.build_app(sources=[self._src()], jwt_secret_file="")
        self.assertIsNone(app.token_provider)
        self.assertIsNone(app.jwt_secret_env)

    def test_boundary_empty_env_var_is_unset(self):
        os.environ["LNPL_JWT_SECRET_FILE"] = ""
        app = wsgi.build_app(sources=[self._src()])
        self.assertIsNone(app.token_provider)

    def test_error_env_and_file_both_given_refused(self):
        text = self._refused(jwt_secret_env="LNPL_T192_ANY",
                             jwt_secret_file=_secret_file(self, FILE_SECRET))
        self.assertEqual(text, "LNPL_JWT_SECRET_ENV and LNPL_JWT_SECRET_FILE both name "
                               "the JWT signing secret — give exactly one")

    def test_error_env_vars_both_set_refused(self):
        os.environ["LNPL_JWT_SECRET_ENV"] = "LNPL_T192_ANY"
        os.environ["LNPL_JWT_SECRET_FILE"] = _secret_file(self, FILE_SECRET)
        self.assertIn("give exactly one", self._refused())

    def test_error_missing_file_names_the_variable(self):
        path = os.path.join(_tmp_dir(self), "absent")
        text = self._refused(jwt_secret_file=path)
        self.assertEqual(text, "LNPL_JWT_SECRET_FILE names a file that does not exist")
        self.assertNotIn(path, text)

    def test_error_relative_path_names_the_variable(self):
        text = self._refused(jwt_secret_file="rel/secret")
        self.assertEqual(text, "LNPL_JWT_SECRET_FILE must be an absolute path")
        self.assertNotIn("rel/secret", text)

    def test_error_config_missing_file_names_the_config_role(self):
        path = os.path.join(_tmp_dir(self), "absent")
        toml = _write_toml(self, '[default.secrets]\njwt = { file = "%s" }\n' % path)
        text = self._refused(config=toml)
        self.assertEqual(text, "lnpl.toml secrets.jwt.file names a file that does not exist")

    def test_error_short_file_states_minimum(self):
        path = _secret_file(self, b"FAKE-SEC")
        text = self._refused(jwt_secret_file=path)
        self.assertIn("at least 32 bytes, got 8 (from LNPL_JWT_SECRET_FILE)", text)
        self.assertNotIn(path, text)

    def test_boundary_non_hmac_token_provider_leaves_the_file_unread(self):
        path = os.path.join(_tmp_dir(self), "absent")
        with _spi_registered(EXT_TOKEN_EP):
            app = wsgi.build_app(sources=[self._src()], jwt_secret_file=path,
                                 token_provider="extprov")
        self.assertIsInstance(app.token_provider, DemoTokenProvider)

    def test_error_fifo_argument_is_refused_without_blocking(self):
        fifo = _fifo(self)
        src = self._src()
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            call_with_deadline(
                self, lambda: wsgi.build_app(sources=[src], jwt_secret_file=fifo), fifo)
        self.assertEqual(str(cm.exception),
                         "LNPL_JWT_SECRET_FILE names a file that cannot be read")
        self.assertIsNone(cm.exception.__cause__)

    def test_error_nul_in_config_path_is_a_config_error(self):
        toml = _write_toml(self, '[default.secrets]\njwt = { file = "/run/%s" }\n'
                           % NUL_PATH_TAIL.replace("\x00", "\\u0000"))
        text = self._refused(config=toml)
        self.assertEqual(text, "lnpl.toml secrets.jwt.file names a file that cannot be read")

    def test_boundary_file_source_disables_readyz_check_3(self):
        app = wsgi.build_app(sources=[self._src()],
                             jwt_secret_file=_secret_file(self, FILE_SECRET))
        self.assertIsNone(app.jwt_secret_env)
        status, _h, body = call_wsgi(app, "GET", "/-/readyz")
        self.assertEqual(status, 200)
        self.assertNotIn("jwt-secret-env", json.dumps(body))


SECRETS_GROUP = "lnpl.secrets"


def _secret_ep(name, factory):
    return _spi_entry_point(
        name, "tests.secret_spi_fixture:%s" % factory, SECRETS_GROUP)


DEMO_SECRET_EP = _secret_ep("demo", "make_demo_secret_provider")


class BuildAppSecretProviderTest(_EnvIsolatedTest):
    """issue #192 D17 on the build_app path: lnpl.toml `jwt = { provider,
    key }` builds a RotatingHmacTokenProvider that verifies the provider's
    current and previous keys; every provider failure is a value-free
    WsgiConfigError with no cause; an explicit file still wins."""

    def setUp(self):
        super().setUp()
        from tests import secret_spi_fixture
        self.fixture = secret_spi_fixture
        secret_spi_fixture.INSTANCES.clear()

    def _toml(self, provider):
        return _write_toml(
            self, '[default.secrets]\njwt = { provider = "%s", key = "jwt" }\n'
            % provider)

    def _build(self, provider, *entry_points, **kwargs):
        with _spi_registered(*entry_points):
            return wsgi.build_app(sources=[_write_tmp(self, JWT_SRC)],
                                  config=self._toml(provider), **kwargs)

    def _refused(self, provider, *entry_points):
        with self.assertRaises(wsgi.WsgiConfigError) as cm:
            self._build(provider, *entry_points)
        exc = cm.exception
        self.assertIsNone(exc.__cause__)
        formatted = "".join(traceback.format_exception(type(exc), exc,
                                                       exc.__traceback__))
        self.assertNotIn("FAKE-SECRET-192", formatted)
        return str(exc)

    def _status(self, app, secret):
        from lnpl.drivers import audience_for_path
        token = HmacTokenProvider(secret).issue("u", audience_for_path(JWT_PATH))
        status, _h, _body = call_wsgi(
            app, "POST", JWT_PATH, body=b"{}",
            headers={"Authorization": "Bearer " + token,
                     "Content-Type": "application/json"})
        return status

    def test_normal_current_and_previous_keys_verify(self):
        from lnpl.drivers import RotatingHmacTokenProvider
        from tests.secret_spi_fixture import (DEMO_SECRET_K0, DEMO_SECRET_K1,
                                              DEMO_SECRET_K2)
        app = self._build("demo", DEMO_SECRET_EP)
        self.assertIsInstance(app.token_provider, RotatingHmacTokenProvider)
        self.assertIsNone(app.jwt_secret_env)
        self.assertEqual(self._status(app, DEMO_SECRET_K0), 200)

        self.fixture.INSTANCES[-1].rotate("jwt", DEMO_SECRET_K1)
        app.token_provider.refresh_keys()

        self.assertEqual(self._status(app, DEMO_SECRET_K1), 200)
        self.assertEqual(self._status(app, DEMO_SECRET_K0), 200)
        self.assertEqual(self._status(app, DEMO_SECRET_K2), 401)

    def test_error_unregistered_provider(self):
        text = self._refused("nope")
        self.assertIn("lnpl.toml secrets.jwt: unknown secret provider 'nope'", text)
        self.assertIn("env, file", text)

    def test_error_raising_provider_is_value_free(self):
        text = self._refused(
            "raising", _secret_ep("raising", "make_raising_secret_provider"))
        self.assertEqual(
            text, "the secret provider failed to return the secret "
                  "(from lnpl.toml secrets.jwt provider 'raising')")
        self.assertEqual(self.fixture.INSTANCES[-1].close_calls, 1)

    def test_error_short_provider_value(self):
        text = self._refused(
            "short", _secret_ep("short", "make_short_secret_provider"))
        self.assertEqual(
            text, "the JWT signing secret must be at least 32 bytes, got 21 "
                  "(from lnpl.toml secrets.jwt provider 'short')")
        self.assertEqual(self.fixture.INSTANCES[-1].close_calls, 1)

    def test_error_broken_factory(self):
        text = self._refused("broken", _secret_ep("broken", "make_broken_factory"))
        self.assertIn("failed to start (RuntimeError)", text)
        self.assertEqual(self.fixture.INSTANCES, [])

    def test_normal_explicit_file_beats_config_provider(self):
        app = self._build("demo", DEMO_SECRET_EP,
                          jwt_secret_file=_secret_file(self, FILE_SECRET))
        self.assertEqual(self.fixture.INSTANCES, [])
        self.assertIs(type(app.token_provider), HmacTokenProvider)
        self.assertEqual(self._status(app, FILE_SECRET), 200)
        self.assertEqual(self._status(app, OTHER_SECRET), 401)

    def test_boundary_non_hmac_token_provider_leaves_provider_unopened(self):
        app = self._build("demo", DEMO_SECRET_EP, EXT_TOKEN_EP,
                          token_provider="extprov")
        self.assertIsInstance(app.token_provider, DemoTokenProvider)
        self.assertEqual(self.fixture.INSTANCES, [])


if __name__ == "__main__":
    unittest.main()

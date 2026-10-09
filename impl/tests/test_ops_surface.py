"""Issue #110: `/-/healthz` + `/-/readyz` (k8s liveness/readiness).

`lnpl serve` opened zero operations surface before this — no way to attach
a k8s probe, so a rolling update sends traffic to a pod that has not
finished loading (`build_routes` raising, a store that failed to open) and
no way to tell a live-but-degraded pod from a dead one (D3's whole reason
for splitting healthz from readyz).

Task 01: normal — healthz always 200 and never touches a repository; readyz
200 when `_readyz_broken`'s closed list of four comes back empty, and
passes even on a `security jwt`+`security role` service without a token
(D2 — unconditional exemption, not auth that happens to pass). Error:
readyz 503 (with the broken check named in the body) when the configured
repository cannot open, or when `--jwt-secret-env` names a variable that is
not actually set. Boundary: a document with no routes at all still serves
both paths, and `/-/healthz`/`/-/readyz` existing never trips
`build_routes`'s routes==OpenAPI-contract assertion (D12 — the mechanism
this whole design depends on).

Task 02 (`ShutdownTest`): SIGTERM flips readyz to 503 and leaves healthz at
200 (D11) — normal is pre-SIGTERM readyz 200 (regression), error is the
503 + `shutting-down` check name post-SIGTERM, boundary is healthz's total
indifference to the flag (getting this backwards makes k8s restart a pod
that is already draining).
"""

import contextlib
import io
import json
import os
import signal
import unittest
from unittest import mock

from lnpl.drivers import (READYZ_REFRESH_FLOOR_S, DriverError,
                          HmacTokenProvider, RotatingHmacTokenProvider,
                          audience_for_path)
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.serve import serve
from lnpl.wsgi import (ServeError, build_app, build_ops_routes, build_routes,
                       make_wsgi_app)

from tests.secret_spi_fixture import (DEMO_SECRET_K0, DEMO_SECRET_K1,
                                      DemoSecretProvider)
from tests.test_wsgi_contract import call_wsgi

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHORTEN = os.path.join(REPO, "examples", "shorten.lnpl")

# No `security` clause at all — the plain case for the assertions that are
# not about auth.
OPEN_SRC = """entity Report
    field
        id UUID

service Rollup

workflow GetReport
    read report
"""

# `security jwt` + `security role admin` together (D2's exemption has to
# hold even here, or `/-/readyz` becomes unreachable to a kubelet that
# never carries a bearer token).
ROLE_GATED_SRC = """entity Report
    field
        id UUID

service Rollup
    security
        jwt
        role admin

workflow GetReport
    read report
"""

# No service/workflow/entity at all — the zero-route boundary case (D12).
EMPTY_SRC = """entity Report
    field
        id UUID
"""

SECRET = b"0123456789abcdef0123456789abcdef"          # exactly 32 bytes


def _doc(src, module="m110ops"):
    return lower(parse(src), module).to_document()


class _RecordingRepository:
    """A repository whose every call is appended to a shared list — proof
    that a code path touched (or, for healthz, never touched) storage."""

    def __init__(self, calls):
        self.calls = calls

    def execute(self, *args, **kwargs):
        self.calls.append("execute")
        return None

    def query_sorted(self, *args, **kwargs):
        self.calls.append("query_sorted")
        return []

    def close(self):
        self.calls.append("close")


def _recording_factory(calls):
    def factory():
        calls.append("open")
        return _RecordingRepository(calls)
    return factory


def _failing_factory():
    def factory():
        raise DriverError("store unreachable")
    return factory


class NormalTest(unittest.TestCase):

    def test_normal_healthz_is_200_and_touches_no_repository(self):
        calls = []
        app = make_wsgi_app(_doc(OPEN_SRC),
                            repository_factory=_recording_factory(calls))

        status, _headers, body = call_wsgi(app, "GET", "/-/healthz")

        self.assertEqual(200, status)
        self.assertEqual({"status": "ok"}, body)
        self.assertEqual([], calls, "healthz must not touch the repository")

    def test_normal_readyz_is_200_with_no_backend_configured(self):
        app = make_wsgi_app(_doc(OPEN_SRC))

        status, _headers, body = call_wsgi(app, "GET", "/-/readyz")

        self.assertEqual(200, status)
        self.assertEqual({"status": "ok"}, body)

    def test_normal_readyz_is_200_with_a_healthy_backend(self):
        calls = []
        app = make_wsgi_app(_doc(OPEN_SRC),
                            repository_factory=_recording_factory(calls))

        status, _headers, body = call_wsgi(app, "GET", "/-/readyz")

        self.assertEqual(200, status)
        self.assertEqual(["open", "close"], calls)

    def test_normal_healthz_needs_no_token_on_a_role_gated_service(self):
        provider = HmacTokenProvider(SECRET)
        app = make_wsgi_app(_doc(ROLE_GATED_SRC), token_provider=provider)

        status, _headers, body = call_wsgi(app, "GET", "/-/healthz")

        self.assertEqual(200, status)
        self.assertEqual({"status": "ok"}, body)

    def test_normal_readyz_needs_no_token_on_a_role_gated_service(self):
        provider = HmacTokenProvider(SECRET)
        app = make_wsgi_app(_doc(ROLE_GATED_SRC), token_provider=provider)

        status, _headers, body = call_wsgi(app, "GET", "/-/readyz")

        self.assertEqual(200, status)
        self.assertEqual({"status": "ok"}, body)

    def test_normal_readyz_is_200_when_jwt_secret_env_is_actually_set(self):
        # The positive twin of the error-case unset test below — proves the
        # check reads the variable's presence, not just whether the flag was
        # given (a check that always reported "broken" whenever the flag was
        # configured, regardless of the variable's value, would slip past
        # the unset-only case alone).
        os.environ["LNPL_TEST_JWT_SECRET"] = "present"
        self.addCleanup(os.environ.pop, "LNPL_TEST_JWT_SECRET", None)
        app = make_wsgi_app(_doc(OPEN_SRC), jwt_secret_env="LNPL_TEST_JWT_SECRET")

        status, _headers, body = call_wsgi(app, "GET", "/-/readyz")

        self.assertEqual(200, status)
        self.assertEqual({"status": "ok"}, body)

    # issue #187: the build_app-path twins of the readyz check 3 cases.
    # `build_app` used to drop `jwt_secret_env` before `make_wsgi_app`, so
    # the check never evaluated behind gunicorn.

    def test_normal_readyz_stays_200_on_a_source_and_backend_only_build_app_deployment(self):
        with mock.patch.dict(os.environ, {"LNPL_TEST_R9_SECRET": "x" * 32}):
            app = build_app(sources=[SHORTEN], jwt_secret_env="LNPL_TEST_R9_SECRET")

            status, _headers, body = call_wsgi(app, "GET", "/-/readyz")

        self.assertEqual("LNPL_TEST_R9_SECRET", app.jwt_secret_env)
        self.assertEqual(200, status)
        self.assertEqual({"status": "ok"}, body)

    def test_normal_readyz_stays_200_when_no_jwt_secret_env_is_configured_at_all(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("LNPL_JWT_SECRET_ENV", None)
            app = build_app(sources=[SHORTEN])

            status, _headers, body = call_wsgi(app, "GET", "/-/readyz")

        self.assertIsNone(app.jwt_secret_env)
        self.assertEqual(200, status)
        self.assertEqual({"status": "ok"}, body)


class ErrorTest(unittest.TestCase):

    def test_error_readyz_is_503_when_the_backend_cannot_open(self):
        app = make_wsgi_app(_doc(OPEN_SRC), repository_factory=_failing_factory())

        status, _headers, body = call_wsgi(app, "GET", "/-/readyz")

        self.assertEqual(503, status)
        self.assertEqual("not-ready", body["code"])
        self.assertIn("repository", body["checks"])

    def test_error_readyz_is_503_when_jwt_secret_env_is_unset(self):
        app = make_wsgi_app(_doc(OPEN_SRC), jwt_secret_env="LNPL_NO_SUCH_VAR")
        self.assertNotIn("LNPL_NO_SUCH_VAR", os.environ)

        status, _headers, body = call_wsgi(app, "GET", "/-/readyz")

        self.assertEqual(503, status)
        self.assertEqual("not-ready", body["code"])
        self.assertIn("jwt-secret-env", body["checks"])

    def test_error_readyz_reports_every_broken_check_at_once(self):
        app = make_wsgi_app(_doc(OPEN_SRC), repository_factory=_failing_factory(),
                            jwt_secret_env="LNPL_NO_SUCH_VAR")

        status, _headers, body = call_wsgi(app, "GET", "/-/readyz")

        self.assertEqual(503, status)
        self.assertEqual(["repository", "jwt-secret-env"], body["checks"])

    def test_error_readyz_is_503_when_jwt_secret_env_is_removed_after_build_on_build_app_path(self):
        # issue #187: built with the secret present, then the variable goes
        # away (a rotated/unmounted secret) — readyz must report it.
        with mock.patch.dict(os.environ, {"LNPL_TEST_R9_SECRET": "x" * 32}):
            app = build_app(sources=[SHORTEN], jwt_secret_env="LNPL_TEST_R9_SECRET")
            os.environ.pop("LNPL_TEST_R9_SECRET")

            status, _headers, body = call_wsgi(app, "GET", "/-/readyz")

        self.assertEqual(503, status)
        self.assertEqual("not-ready", body["code"])
        self.assertEqual(["jwt-secret-env"], body["checks"])
        self.assertNotIn("x" * 32, json.dumps(body))


class BoundaryTest(unittest.TestCase):

    def test_boundary_a_routeless_document_still_serves_both_paths(self):
        doc = _doc(EMPTY_SRC)
        self.assertEqual({}, build_routes(doc))
        app = make_wsgi_app(doc)

        healthz_status, _h1, _b1 = call_wsgi(app, "GET", "/-/healthz")
        readyz_status, _h2, _b2 = call_wsgi(app, "GET", "/-/readyz")

        self.assertEqual(200, healthz_status)
        self.assertEqual(200, readyz_status)

    def test_boundary_ops_routes_never_trip_the_openapi_contract_assertion(self):
        # D12: `/-/healthz`/`/-/readyz` are excluded from build_routes's own
        # routes==contract check by construction — they are merged in only
        # AFTER that assertion runs (build_ops_routes, called from
        # make_wsgi_app). Folding them into build_routes's own dict would
        # raise ServeError for every document; this pins that it does not.
        doc = _doc(OPEN_SRC)
        try:
            make_wsgi_app(doc)
        except ServeError as exc:
            self.fail("ops routes must not trip the OpenAPI contract "
                     "assertion: %s" % exc)

    def test_boundary_build_ops_routes_is_disjoint_from_the_openapi_contract(self):
        doc = _doc(OPEN_SRC)
        ops_paths = set(build_ops_routes(doc))
        self.assertEqual({"/-/healthz", "/-/readyz"}, ops_paths)
        self.assertTrue(ops_paths.isdisjoint(build_routes(doc)))


class ShutdownTest(unittest.TestCase):
    """issue #110, Task 02, D11: SIGTERM -> `/-/readyz` 503, `/-/healthz`
    unaffected. `serve()` installs the SIGTERM handler itself, so these
    drive the real `serve()`/`signal` wiring rather than the flag alone —
    `test_ops_surface`'s Task 01 classes already cover the flag/readyz
    contract in isolation via `app.shutting_down` directly."""

    def _serve(self, src):
        server = serve(_doc(src), port=0)
        self.addCleanup(server.server_close)
        return server

    def test_normal_readyz_is_200_before_any_signal(self):
        server = self._serve(OPEN_SRC)

        status, _headers, body = call_wsgi(server.get_app(), "GET", "/-/readyz")

        self.assertEqual(200, status)
        self.assertEqual({"status": "ok"}, body)

    def test_error_sigterm_flips_readyz_to_503_with_the_check_named(self):
        server = self._serve(OPEN_SRC)
        old_handler = signal.getsignal(signal.SIGTERM)
        self.addCleanup(signal.signal, signal.SIGTERM, old_handler)

        os.kill(os.getpid(), signal.SIGTERM)
        status, _headers, body = call_wsgi(server.get_app(), "GET", "/-/readyz")

        self.assertEqual(503, status)
        self.assertEqual("not-ready", body["code"])
        self.assertEqual(["shutting-down"], body["checks"])

    def test_boundary_sigterm_leaves_healthz_at_200(self):
        server = self._serve(OPEN_SRC)
        old_handler = signal.getsignal(signal.SIGTERM)
        self.addCleanup(signal.signal, signal.SIGTERM, old_handler)

        os.kill(os.getpid(), signal.SIGTERM)
        status, _headers, body = call_wsgi(server.get_app(), "GET", "/-/healthz")

        self.assertEqual(200, status)
        self.assertEqual({"status": "ok"}, body)


# issue #192: a jwt-gated service (POST /rollup/get-report) for the
# provider-sourced readyz check 5.
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


class ReadyzSecretProviderTest(unittest.TestCase):
    """issue #192 D16 + review C1: with a provider-sourced JWT secret, a
    readyz probe re-reads current+previous unless the last provider read
    (success or failure) is younger than `READYZ_REFRESH_FLOOR_S`, in which
    case it reports that read's result without calling the provider. A
    failure is 503 naming only `secret-provider`, recovery is 200, and a
    rotation becomes visible after one probe past the floor. The clock is
    injected (`now`), so nothing sleeps."""

    FLOOR = READYZ_REFRESH_FLOOR_S

    def setUp(self):
        self.now = [0.0]
        self.source = DemoSecretProvider({"jwt": DEMO_SECRET_K0})
        self.app = make_wsgi_app(
            _doc(JWT_SRC),
            token_provider=RotatingHmacTokenProvider(
                self.source, "jwt", monotonic=lambda: self.now[0]))

    def _probe(self, at):
        self.now[0] = at
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            status, _headers, body = call_wsgi(self.app, "GET", "/-/readyz")
        return status, body, err.getvalue()

    def _post_status(self, secret):
        token = HmacTokenProvider(secret).issue("u", audience_for_path(JWT_PATH))
        status, _headers, _body = call_wsgi(
            self.app, "POST", JWT_PATH, body=b"{}",
            headers={"Authorization": "Bearer " + token,
                     "Content-Type": "application/json"})
        return status

    def test_error_failing_provider_is_503_naming_the_check(self):
        self.source.fail = True

        status, body, err = self._probe(self.FLOOR)

        self.assertEqual(503, status)
        self.assertEqual("not-ready", body["code"])
        self.assertEqual(["secret-provider"], body["checks"])
        self.assertNotIn("FAKE-SECRET-192", json.dumps(body))
        self.assertNotIn("FAKE-SECRET-192", err)
        self.assertEqual(200, self._post_status(DEMO_SECRET_K0))

    def test_normal_recovery_is_200(self):
        self.source.fail = True
        self.assertEqual(503, self._probe(self.FLOOR)[0])
        self.source.fail = False

        status, body, _err = self._probe(2 * self.FLOOR)

        self.assertEqual(200, status)
        self.assertEqual({"status": "ok"}, body)

    def test_normal_rotation_visible_after_one_probe(self):
        self.source.rotate("jwt", DEMO_SECRET_K1)
        self.assertEqual(401, self._post_status(DEMO_SECRET_K1))
        calls = self.source.get_calls

        status, _body, _err = self._probe(self.FLOOR)

        self.assertEqual(200, status)
        self.assertEqual(calls + 1, self.source.get_calls)
        self.assertEqual(200, self._post_status(DEMO_SECRET_K1))
        self.assertEqual(200, self._post_status(DEMO_SECRET_K0))

    def test_boundary_probes_within_the_floor_read_the_provider_once(self):
        calls = self.source.get_calls

        statuses = [self._probe(at)[0] for at in
                    (self.FLOOR, self.FLOOR + 1.0, self.FLOOR + 2.5,
                     2 * self.FLOOR - 0.1)]

        self.assertEqual([200, 200, 200, 200], statuses)
        self.assertEqual(calls + 1, self.source.get_calls)

    def test_normal_probe_after_the_floor_reads_again(self):
        calls = self.source.get_calls

        self._probe(self.FLOOR)
        self._probe(2 * self.FLOOR)

        self.assertEqual(calls + 2, self.source.get_calls)

    def test_boundary_probe_right_after_startup_reports_the_startup_read(self):
        status, body, _err = self._probe(self.FLOOR - 0.1)

        self.assertEqual(200, status)
        self.assertEqual({"status": "ok"}, body)
        self.assertEqual(1, self.source.get_calls)

    def test_error_failure_is_reported_until_the_floor_passes(self):
        self.source.fail = True
        self.assertEqual(503, self._probe(self.FLOOR)[0])
        self.source.fail = False
        calls = self.source.get_calls

        status, body, _err = self._probe(2 * self.FLOOR - 0.1)

        self.assertEqual(503, status)
        self.assertEqual(["secret-provider"], body["checks"])
        self.assertEqual(calls, self.source.get_calls)
        self.assertEqual(200, self._probe(2 * self.FLOOR)[0])

    def test_boundary_env_sourced_app_keeps_its_exact_check_list(self):
        app = make_wsgi_app(_doc(JWT_SRC), jwt_secret_env="LNPL_NO_SUCH_VAR")
        self.assertNotIn("LNPL_NO_SUCH_VAR", os.environ)

        status, _headers, body = call_wsgi(app, "GET", "/-/readyz")

        self.assertEqual(503, status)
        self.assertEqual(["jwt-secret-env"], body["checks"])


if __name__ == "__main__":
    unittest.main()

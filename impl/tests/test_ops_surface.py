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

import json
import os
import signal
import unittest

from lnpl.drivers import DriverError, HmacTokenProvider
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.serve import serve
from lnpl.wsgi import ServeError, build_ops_routes, build_routes, make_wsgi_app

from tests.test_wsgi_contract import call_wsgi

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


if __name__ == "__main__":
    unittest.main()

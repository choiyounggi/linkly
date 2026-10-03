"""Issue #119 A-part, Task 03/04 — the service-level `security role <r>`
gate, and its observable effects on the rest of the diagnostics/matrix/
OpenAPI surface once it is real:

  Task 03: deny by default (D5), a strict 401-before-403 judgment order, a
  startup refusal when the gate could never actually check anything (D6),
  and a 403 that never leaks which role it wanted (D8).
  Task 04: `declared-not-enforced` stops firing for `security role` (the
  matrix moved it to `enforced`), `authorization-not-verified` is graded
  `warning` and `--strict=warning` gates on it, and OpenAPI carries the
  requirement as `x-lnpl-roles`.

Before this: `security role` was parsed and stored, but nothing ever read it
back — `diagnostics.py`'s own `ENFORCEMENT` table said so in plain words
("the role is never checked against anything"). A request with any role, or
none, ran exactly the same workflow.
"""

import base64
import contextlib
import hashlib
import hmac
import io
import json
import os
import shutil
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout

from lnpl import cli
from lnpl.drivers import HmacTokenProvider
from lnpl.lower import lower
from lnpl.openapi import generate
from lnpl.parser import parse
from lnpl.wsgi import WsgiConfigError, build_routes, make_wsgi_app

from tests.fixtures import CHECKOUT_LNPL, SHORTEN_LNPL
from tests.test_wsgi_contract import call_wsgi

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOGIN_LNPL = os.path.join(REPO_ROOT, "examples", "login.lnpl")

SECRET = b"0123456789abcdef0123456789abcdef"          # exactly 32 bytes
AUDIENCE = "order-service"
PATH = "/order-service/approve-order"
CLAUDE_TMP = os.path.join(REPO_ROOT, ".claude", "tmp")
SECRET_ENV = "LNPL_I202_TEST_JWT_SECRET"
ORDER_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"

ROLE_GATED_SRC = """capability postgres

entity Order
    field
        id UUID
        approvals Integer

service OrderService
    security
        jwt
        role admin
    policy
        timeout 5s

workflow ApproveOrder
    read order
    set order.approvals to order.approvals + 1
"""

NO_ROLE_SRC = """capability postgres

entity Order
    field
        id UUID
        approvals Integer

service OrderService
    security
        jwt
    policy
        timeout 5s

workflow ApproveOrder
    read order
    set order.approvals to order.approvals + 1
"""

ROLE_GATED_ESC_SRC = ROLE_GATED_SRC.replace("role admin", "role a\x1bb")
ROLE_GATED_ZWSP_SRC = ROLE_GATED_SRC.replace("role admin", "role a\u200bb")
ROLE_GATED_ESC_PATH_SRC = ROLE_GATED_SRC.replace("OrderService", "Order\x1bService")
ROLE_GATED_ZWSP_PATH_SRC = ROLE_GATED_SRC.replace("OrderService", "Order\u200bService")
ROLE_GATED_ESC_PATH = "/order\x1b-service/approve-order"
ROLE_GATED_ZWSP_PATH = "/order\u200b-service/approve-order"


def compile_doc(source, module="m119role"):
    return lower(parse(source), module).to_document()


def _b64u(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def forge(role=None, **overrides):
    """A genuinely-signed HS256 token (same shape `test_token_provider.py`
    forges), with an optional `role` claim, built by hand against the same
    signing key so the verify side is exercised independently of
    `HmacTokenProvider.issue(role=...)` (issue #202)."""
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    claims = {"iss": "lnpl", "aud": AUDIENCE, "sub": "u1", "jti": "j-1",
              "iat": now, "nbf": now, "exp": now + 900}
    if role is not None:
        claims["role"] = role
    claims.update(overrides)
    signing_input = "%s.%s" % (_b64u(json.dumps(header).encode("utf-8")),
                               _b64u(json.dumps(claims).encode("utf-8")))
    sig = hmac.new(SECRET, signing_input.encode("ascii"), hashlib.sha256).digest()
    return "%s.%s" % (signing_input, _b64u(sig))


def make_app(source=ROLE_GATED_SRC):
    return make_wsgi_app(compile_doc(source), token_provider=HmacTokenProvider(SECRET))


def post(app, token=None):
    headers = {"Authorization": "Bearer " + token} if token is not None else {}
    return call_wsgi(app, "POST", PATH, body=('{"id": "%s", "approvals": 0}' % ORDER_ID).encode(),
                     headers=headers)


class RoleGateTest(unittest.TestCase):
    """D5 (deny by default) + D9 (M3b sits after M3a in judgment order)."""

    def setUp(self):
        self.app = make_app()

    def test_normal_matching_role_runs_the_workflow(self):
        status, _, body = post(self.app, forge(role="admin"))
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "completed")

    def test_error_mismatched_role_is_403_not_401(self):
        status, _, body = post(self.app, forge(role="user"))
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "forbidden")

    def test_error_no_role_claim_is_403_deny_by_default(self):
        # D5's sharpest case: a VALID, verified token that simply carries no
        # role must not pass — deny by default means absence is a denial,
        # not an unencumbered pass.
        status, _, body = post(self.app, forge(role=None))
        self.assertEqual(status, 403)

    def test_error_ambiguous_roles_array_is_403(self):
        # D3's ambiguity rule composes with D5: 2+ roles resolves to no role
        # in caller_view, and no role is 403 here, same as an absent one.
        status, _, body = post(self.app, forge(roles=["admin", "ops"]))
        self.assertEqual(status, 403)

    def test_order_invalid_token_is_401_not_403(self):
        # D9: judgment order is strictly M3a (token validity) before M3b
        # (role match) — an invalid token never even reaches the role check.
        status, _, body = post(self.app, "not-a-real-token")
        self.assertEqual(status, 401)
        self.assertEqual(body["code"], "auth-invalid")

    def test_order_missing_auth_header_is_401_not_403(self):
        status, _, body = post(self.app, token=None)
        self.assertEqual(status, 401)
        self.assertEqual(body["code"], "auth-missing")

    def test_boundary_no_security_role_declared_never_gates(self):
        app = make_app(NO_ROLE_SRC)
        # A token with no role claim at all still runs — this service never
        # declared `security role`, so there is nothing to check against.
        status, _, body = post(app, forge(role=None))
        self.assertEqual(status, 200)


class Role403BodyAndStderrTest(unittest.TestCase):
    """D8: the 403 body never names which role was required; the operator's
    stderr line carries the correlation id and both the required and actual
    role, the same shape `_token_accepted`'s M3a rejection already uses."""

    def setUp(self):
        self.app = make_app()

    def test_error_the_403_body_never_names_the_required_role(self):
        status, _, body = post(self.app, forge(role="user"))
        self.assertEqual(status, 403)
        rendered = json.dumps(body)
        self.assertNotIn("admin", rendered)

    def test_error_stderr_carries_correlation_id_and_both_roles(self):
        buf = io.StringIO()
        with redirect_stderr(buf):
            status, _, body = post(self.app, forge(role="user"))
        self.assertEqual(status, 403)
        stderr_text = buf.getvalue()
        self.assertIn("correlation_id=%s" % body["correlation_id"], stderr_text)
        self.assertIn("admin", stderr_text)     # required
        self.assertIn("user", stderr_text)      # actual


class StartupRc2Test(unittest.TestCase):
    """D6: presence-checking dressed up as RBAC is refused at construction,
    not discovered on the first request."""

    def test_error_security_role_without_token_provider_fails_the_launch(self):
        doc = compile_doc(ROLE_GATED_SRC)
        with self.assertRaises(WsgiConfigError) as ctx:
            make_wsgi_app(doc)                    # no token_provider
        self.assertIn("--jwt-secret-env", str(ctx.exception))

    def test_normal_security_role_with_token_provider_launches_fine(self):
        doc = compile_doc(ROLE_GATED_SRC)
        app = make_wsgi_app(doc, token_provider=HmacTokenProvider(SECRET))
        self.assertIsNotNone(app)

    def test_boundary_no_security_role_never_needs_a_token_provider(self):
        doc = compile_doc(NO_ROLE_SRC)
        app = make_wsgi_app(doc)                  # no token_provider, no role -> fine
        self.assertIsNotNone(app)


class CmdServeRc2Test(unittest.TestCase):
    """D6's requirement is a PROCESS exit code, not just a Python exception
    type — `make_wsgi_app` raising `WsgiConfigError` only satisfies D6 if
    `lnpl serve` (via `cli.main`) actually maps it to rc 2 rather than
    escaping uncaught with a bare traceback and Python's default exit code.
    Drives the real CLI path end to end, mirroring `test_serve.py`'s own
    `CmdServeTest._main` idiom for the existing (`ParseError`-> rc 2) case —
    `serve()` is NOT mocked here: `make_wsgi_app` (and this refusal) runs
    inside it, before any socket is ever bound, so there is nothing to mock
    around.
    """

    def setUp(self):
        import contextlib
        import io
        import shutil
        self.workdir = os.path.join(REPO_ROOT, ".claude", "tmp", "cli-serve-role-gate")
        os.makedirs(self.workdir, exist_ok=True)
        self._io = io
        self._contextlib = contextlib
        self.addCleanup(shutil.rmtree, self.workdir, ignore_errors=True)

    def _write(self, name, text):
        path = os.path.join(self.workdir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def _main(self, argv):
        from lnpl import cli
        out, err = self._io.StringIO(), self._io.StringIO()
        with self._contextlib.redirect_stdout(out), \
                self._contextlib.redirect_stderr(err):
            rc = cli.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_error_security_role_without_jwt_secret_env_is_rc_2_via_cli(self):
        src = self._write("role-gated.lnpl", ROLE_GATED_SRC)
        rc, _, err = self._main(["serve", src])       # no --jwt-secret-env
        self.assertEqual(2, rc)
        self.assertIn("--jwt-secret-env", err)


class ExistingExamplesUnaffectedTest(unittest.TestCase):
    """D14: the regression bar is that examples declaring only `security
    jwt` (no `role`) are byte-identical — proven at the exact point the new
    mechanism would have to fire for a regression to be possible: no route
    it serves ends up with a required role."""

    def _assert_no_route_requires_a_role(self, path, module):
        with open(path, encoding="utf-8") as fh:
            doc = lower(parse(fh.read()), module).to_document()
        routes = build_routes(doc)
        self.assertTrue(routes, "expected at least one route")
        for route in routes.values():
            self.assertIsNone(route.get("role"))

    def test_regression_login_declares_no_role(self):
        self._assert_no_route_requires_a_role(LOGIN_LNPL, "login")

    def test_regression_checkout_declares_no_role(self):
        self._assert_no_route_requires_a_role(CHECKOUT_LNPL, "checkout")

    def test_regression_shorten_declares_no_role(self):
        self._assert_no_route_requires_a_role(SHORTEN_LNPL, "shorten")


AUTHORIZE_STEP_SRC = """capability postgres

entity User
    field
        id UUID

workflow Login
    authorize admin
"""


def run_cli(argv):
    """Drive `cli.main(argv)`, keeping stdout and stderr apart — the same
    idiom `test_cli_diagnostics.py`'s own `run_cli_split` uses."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cli.main(argv)
    return rc, out.getvalue(), err.getvalue()


def write_tmp(text, name):
    workdir = os.path.join(REPO_ROOT, ".claude", "tmp", "test-role-gate")
    os.makedirs(workdir, exist_ok=True)
    path = os.path.join(workdir, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


class EnforcementMatrixTest(unittest.TestCase):
    """Task 04: `security role` moved to `enforced` in the matrix — the
    observable consequence is that `declared-not-enforced` stops firing for
    it. A diagnostic that still says "declared, and nothing checks it" about
    a mechanism this task made enforced would be exactly issue #38's failure
    mode reappearing one row over."""

    def test_normal_security_role_no_longer_reports_declared_not_enforced(self):
        mod = lower(parse(ROLE_GATED_SRC), "m119matrix")
        offenders = [d for d in mod.diagnostics.all()
                    if d.code == "declared-not-enforced"
                    and d.subject == "security role"]
        self.assertEqual(offenders, [])

    def test_boundary_security_jwt_alone_still_reports_declared_not_enforced(self):
        # Negative control: the diagnostic mechanism itself is intact — only
        # `role`'s status changed, not the reporting machinery.
        mod = lower(parse(NO_ROLE_SRC), "m119matrixctrl")
        subjects = [d.subject for d in mod.diagnostics.all()
                   if d.code == "declared-not-enforced"]
        self.assertIn("security jwt", subjects)


class StrictWarningGatesAuthorizeTest(unittest.TestCase):
    """Task 04, D10: `authorization-not-verified` graded `warning` means
    `--strict=warning` now gates a program that executes an `authorize` step
    — that grade promotion is the whole point of D10 (an author has a real
    fix available: move the requirement to `security role`)."""

    def test_error_strict_warning_gates_an_executed_authorize_step(self):
        src = write_tmp(AUTHORIZE_STEP_SRC, "authorize-strict.lnpl")
        rc, _, err = run_cli(["run", src, "--strict=warning"])
        self.assertEqual(rc, 2)
        self.assertIn("authorization-not-verified", err)

    def test_boundary_strict_info_still_gates_it_too(self):
        # `warning` sits above `info` on the ladder (RFC-0021) — a coarser
        # gate does not stop catching what a finer one already caught.
        src = write_tmp(AUTHORIZE_STEP_SRC, "authorize-strict-info.lnpl")
        rc, _, err = run_cli(["run", src, "--strict=info"])
        self.assertEqual(rc, 2)

    def test_normal_without_strict_the_same_program_exits_0(self):
        src = write_tmp(AUTHORIZE_STEP_SRC, "authorize-no-strict.lnpl")
        rc, _, err = run_cli(["run", src])
        self.assertEqual(rc, 0)
        self.assertIn("authorization-not-verified", err)


class OpenApiRoleExtensionTest(unittest.TestCase):
    """Task 04, D12: `x-lnpl-roles`, not an OAuth2 scope — and the routing
    table this task's own `build_routes` computes stays contract-identical
    to what `openapi.generate` publishes (both walk the same `security role`
    declaration; a drift here is exactly the class of bug `build_routes`'s
    own internal assertion exists to catch)."""

    def test_normal_the_role_gated_workflow_carries_x_lnpl_roles(self):
        doc = compile_doc(ROLE_GATED_SRC, "m119openapi")
        spec = generate(doc)
        op = spec["paths"][PATH]["post"]
        self.assertEqual(op["x-lnpl-roles"], ["admin"])
        self.assertIn("403", op["responses"])

    def test_boundary_a_jwt_only_workflow_carries_no_x_lnpl_roles(self):
        doc = compile_doc(NO_ROLE_SRC, "m119openapictrl")
        spec = generate(doc)
        op = spec["paths"][PATH]["post"]
        self.assertNotIn("x-lnpl-roles", op)
        self.assertNotIn("403", op["responses"])

    def test_normal_routing_and_contract_agree_on_the_role_gated_service(self):
        doc = compile_doc(ROLE_GATED_SRC, "m119crosscheck")
        spec = generate(doc)
        routes = build_routes(doc)   # raises ServeError on a path-set mismatch
        self.assertEqual(set(spec["paths"]), set(routes))


SCHEDULE_ROLE_GATED_SRC = """capability postgres

entity Order
    field
        id UUID
        approvals Integer

service OrderService
    security
        jwt
        role admin
    policy
        timeout 5s

event DailyRollup on schedule daily at 00:00 UTC

workflow ApproveOrder
    read order
    set order.approvals to order.approvals + 1
"""

SCHEDULE_NO_ROLE_SRC = """capability postgres

entity Order
    field
        id UUID
        approvals Integer

service OrderService
    security
        jwt
    policy
        timeout 5s

event DailyRollup on schedule daily at 00:00 UTC

workflow ApproveOrder
    read order
    set order.approvals to order.approvals + 1
"""

SCHEDULE_PATH = "/-/schedules/daily-rollup"


def post_schedule(app, token=None):
    headers = {"Authorization": "Bearer " + token} if token is not None else {}
    return call_wsgi(app, "POST", SCHEDULE_PATH,
                     body=('{"id": "%s", "approvals": 0}' % ORDER_ID).encode(),
                     headers=headers)


class ScheduleTriggerRoleGateTest(unittest.TestCase):
    """r1 review F1: `build_schedule_routes` carries `role` from the owning
    service's `Security` node (mirrors `build_routes` — a `security role`
    service's `/-/schedules/<slug>` trigger is not a side door around its
    own role requirement). That claim needs its own test: nothing in
    `test_wsgi_schedule_trigger.py` looks at the `role` key at all, so a
    future edit that drops `"role": role` from `build_schedule_routes`
    would leave the suite green while quietly reopening an unauthenticated
    path into a role-gated service through the scheduler route."""

    def setUp(self):
        self.app = make_wsgi_app(compile_doc(SCHEDULE_ROLE_GATED_SRC, "m119sched"),
                                 token_provider=HmacTokenProvider(SECRET))

    def _forge_schedule(self, role):
        # Schedule routes are audience `-` (the second path segment of
        # `/-/schedules/<slug>` is literally `-`), not the service slug —
        # `forge`'s `**overrides` lets this override the default `AUDIENCE`.
        return forge(role=role, aud="-")

    def test_normal_matching_role_runs_the_scheduled_workflow(self):
        status, _, body = post_schedule(self.app, self._forge_schedule("admin"))
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "completed")

    def test_error_mismatched_role_is_403_on_the_schedule_route(self):
        status, _, body = post_schedule(self.app, self._forge_schedule("user"))
        self.assertEqual(status, 403)
        self.assertEqual(body["code"], "forbidden")

    def test_error_no_role_claim_is_403_deny_by_default_on_the_schedule_route(self):
        status, _, body = post_schedule(self.app, self._forge_schedule(None))
        self.assertEqual(status, 403)

    def test_boundary_a_service_without_security_role_is_not_gated_on_the_schedule_route(self):
        # Negative control: this fixture declares only `security jwt` on the
        # SAME schedule-triggered service shape — the existing behaviour
        # (`test_wsgi_schedule_trigger.py`'s own coverage) must survive
        # untouched. A bearer token with no role claim at all still runs.
        app = make_wsgi_app(compile_doc(SCHEDULE_NO_ROLE_SRC, "m119schedctrl"),
                            token_provider=HmacTokenProvider(SECRET))
        status, _, body = post_schedule(app, forge(role=None, aud="-"))
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "completed")



class CliMintedTokenAcceptedTest(unittest.TestCase):
    """Issue #202 — the DoD's own accept/reject matrix, minted by the
    real CLI, verified by the real WSGI app."""

    def setUp(self):
        self._prev_secret = os.environ.get(SECRET_ENV)
        os.environ[SECRET_ENV] = SECRET.decode()
        self.addCleanup(self._restore_secret)
        self.app = make_app()

    def _restore_secret(self):
        if self._prev_secret is None:
            os.environ.pop(SECRET_ENV, None)
        else:
            os.environ[SECRET_ENV] = self._prev_secret

    def mint_via_cli(self, source_text, *extra_args):
        """Mint through the real CLI (`cli.main`), never `forge()` — the
        mandatory discriminator between 'the constant matches' and 'the
        system actually mints and verifies'. Returns (rc, stdout_stripped,
        stderr)."""
        os.makedirs(CLAUDE_TMP, exist_ok=True)
        workdir = tempfile.mkdtemp(prefix="lnpl-i202-", dir=CLAUDE_TMP)
        self.addCleanup(shutil.rmtree, workdir, ignore_errors=True)
        src_path = os.path.join(workdir, "svc.lnpl")
        with open(src_path, "w", encoding="utf-8") as fh:
            fh.write(source_text)
        out, err = io.StringIO(), io.StringIO()
        argv = ["token", src_path, "--path", PATH, "--subject", "u1",
                "--secret-env", SECRET_ENV] + list(extra_args)
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(argv)
        return rc, out.getvalue().strip(), err.getvalue()

    def test_normal_a_cli_minted_matching_role_is_accepted(self):
        rc, token, err = self.mint_via_cli(ROLE_GATED_SRC, "--role", "admin")
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        self.assertNotIn("\n", token)
        self.assertTrue(token)
        status, _, body = post(self.app, token)
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "completed")

    def test_error_a_cli_minted_token_without_role_is_rejected_and_warned(self):
        rc, token, err = self.mint_via_cli(ROLE_GATED_SRC)
        self.assertEqual(rc, 0)
        self.assertEqual(
            err,
            "warning: the service at %r requires role %r; this token "
            "carries no role, so the request will be refused with 403\n"
            % (PATH, "admin"))
        status, _, _ = post(self.app, token)
        self.assertEqual(status, 403)

    def test_error_a_cli_minted_token_with_a_different_role_is_rejected(self):
        rc, token, err = self.mint_via_cli(ROLE_GATED_SRC, "--role", "ops")
        self.assertEqual(
            err,
            "warning: the service at %r requires role %r; this token "
            "carries role %r, so the request will be refused with 403\n"
            % (PATH, "admin", "ops"))
        status, _, _ = post(self.app, token)
        self.assertEqual(status, 403)

    def test_boundary_role_flag_on_a_service_without_security_role_is_unaffected(self):
        app2 = make_app(NO_ROLE_SRC)
        rc, token, err = self.mint_via_cli(NO_ROLE_SRC, "--role", "x")
        self.assertEqual(err, "")
        status, _, _ = post(app2, token)
        self.assertEqual(status, 200)

    def test_error_a_unicode_lookalike_role_is_rejected_at_verify(self):
        rc, token, err = self.mint_via_cli(ROLE_GATED_SRC, "--role", "\u0430dmin")
        self.assertEqual(rc, 0)
        status, _, _ = post(self.app, token)
        self.assertEqual(status, 403)

    def test_normal_the_secret_never_reaches_stdout_or_stderr_through_the_cli_mint_chain(self):
        rc, token, err = self.mint_via_cli(ROLE_GATED_SRC, "--role", "admin")
        self.assertNotIn(SECRET.decode(), token)
        self.assertNotIn(SECRET.decode(), err)

    def test_error_a_case_different_role_is_rejected_and_warned(self):
        rc, token, err = self.mint_via_cli(ROLE_GATED_SRC, "--role", "Admin")
        self.assertEqual(
            err,
            "warning: the service at %r requires role %r; this token "
            "carries role %r, so the request will be refused with 403\n"
            % (PATH, "admin", "Admin"))
        status, _, _ = post(self.app, token)
        self.assertEqual(status, 403)

    def test_normal_a_declared_role_containing_control_or_zero_width_characters_still_mints_and_verifies(self):
        for source, declared in ((ROLE_GATED_ESC_SRC, "a\x1bb"),
                                 (ROLE_GATED_ZWSP_SRC, "a\u200bb")):
            with self.subTest(declared=repr(declared)):
                app = make_app(source)
                rc, token, err = self.mint_via_cli(source, "--role", declared)
                self.assertEqual(rc, 0)
                self.assertNotIn(declared, err)
                status, _, _ = post(app, token)
                self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()

"""Issue #119 A-part, Task 01 — claims stop being discarded and reach a new
read-only `caller` scope guards can reference.

Before this: `verify()` (`drivers.py`) already returned claims, but
`wsgi.py:674` discarded the return value, and the interpreter had no `caller`
scope for a guard to read at all — a workflow could never see who called it.

The named trap (Task 01 Step 1): an empty claims dict is falsy in Python. If
"auth passed with claims" and "auth failed" were folded onto one return value
checked for truthiness, a verified token that happens to carry no extra
claims would misread as rejected — or worse, collapsing the other way, a
rejected token could misread as a pass. `_check_auth`/`_token_accepted`
return a 2-tuple instead, so failure is always the second slot and is never
inferred from whether `claims` is truthy. `TokenAcceptedFalsyTrapTest` pins
this directly; `WorkflowDoesNotRunOnRejectedTokenTest` pins the consequence
end to end.
"""

import json
import unittest
from unittest import mock

from lnpl.drivers import HmacTokenProvider
from lnpl.interp import Interpreter, caller_view
from lnpl.lower import LowerError, lower
from lnpl.parser import parse
from lnpl.repo_policy import row_key
from lnpl.wsgi import make_wsgi_app

from tests.test_wsgi_contract import call_wsgi

SECRET = b"0123456789abcdef0123456789abcdef"          # exactly 32 bytes

# One entity, one guarded workflow: `read order` binds the row the request
# payload seeds (wsgi.default_rows — a fresh in-memory copy of the payload
# per request), the guard reads `caller.role` with a Presence check (this
# language's Comparison grammar is Integer/Instant-only — RFC-0015 — so a
# guard cannot compare `caller.role` against a string literal; `exists` is
# the form D1-D3's contract is actually reachable through), and the
# Assignment proves whether the guarded item ran.
SRC = """capability postgres

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
    when caller.role exists
    set order.approvals to order.approvals + 1
"""

PATH = "/order-service/approve-order"
AUDIENCE = "order-service"


def compile_doc(source=SRC, module="m119"):
    return lower(parse(source), module).to_document()


def make_app(secret=SECRET, **kwargs):
    return make_wsgi_app(compile_doc(), token_provider=HmacTokenProvider(secret),
                         **kwargs)


class CallerViewTest(unittest.TestCase):
    """`caller_view` in isolation (D2/D3) — no token, no HTTP, no interpreter."""

    def test_normal_subject_and_role_read_from_claims(self):
        self.assertEqual(caller_view({"sub": "alice", "role": "admin"}),
                         {"subject": "alice", "role": "admin"})

    def test_normal_a_single_element_roles_array_is_used(self):
        self.assertEqual(caller_view({"sub": "x", "roles": ["ops"]}),
                         {"subject": "x", "role": "ops"})

    def test_error_two_element_roles_array_resolves_to_no_role(self):
        self.assertEqual(caller_view({"sub": "x", "roles": ["ops", "admin"]}),
                         {"subject": "x", "role": None})

    def test_error_empty_roles_array_resolves_to_no_role(self):
        self.assertEqual(caller_view({"sub": "x", "roles": []}),
                         {"subject": "x", "role": None})

    def test_normal_a_string_role_wins_over_a_roles_array(self):
        self.assertEqual(
            caller_view({"sub": "x", "role": "admin", "roles": ["ops"]}),
            {"subject": "x", "role": "admin"})

    def test_error_a_malformed_role_does_not_fall_back_to_roles(self):
        # D3: `role` wins outright when present, valid or not — a wrong-typed
        # `role` claim is not the same as an absent one.
        self.assertEqual(
            caller_view({"sub": "x", "role": 5, "roles": ["ops"]}),
            {"subject": "x", "role": None})

    def test_boundary_no_sub_and_no_role_are_both_none_without_raising(self):
        self.assertEqual(caller_view({}), {"subject": None, "role": None})

    def test_boundary_no_claims_at_all_is_none_not_a_dict(self):
        # Distinct from `caller_view({})`: `None` means no verified token was
        # ever presented for this run (no token_provider, or auth not
        # required) — an empty dict means a token verified with no extra
        # claims. The two must not collapse into the same shape.
        self.assertIsNone(caller_view(None))

    def test_boundary_a_non_string_non_list_roles_value_resolves_to_no_role(self):
        self.assertEqual(caller_view({"sub": "x", "roles": "admin"}),
                         {"subject": "x", "role": None})


class TokenAcceptedFalsyTrapTest(unittest.TestCase):
    """`_check_auth`/`_token_accepted` return `(claims, response)`, never a
    single value whose truthiness decides pass/fail."""

    def setUp(self):
        self.app = make_app()

    def test_error_a_rejected_token_yields_none_claims_and_a_response(self):
        captured = {}

        def start_response(status, headers, exc_info=None):
            captured["status"] = status
        claims, response = self.app._token_accepted(
            start_response, "Bearer not-a-real-token", PATH)
        self.assertIsNone(claims)
        self.assertIsNotNone(response)
        self.assertTrue(captured["status"].startswith("401"))

    def test_normal_a_verified_token_with_no_extra_claims_is_not_read_as_rejected(self):
        # `HmacTokenProvider.issue` mints only its own fixed claim set (no
        # `role`) — the resulting claims dict is non-empty (iss/aud/sub/...)
        # but carries nothing `caller_view` turns into a role. The point of
        # this case is the RETURN SHAPE, not the role value: success must
        # read as success regardless of what caller_view later does with it.
        token = self.app.token_provider.issue("alice", AUDIENCE)
        captured = {}

        def start_response(status, headers, exc_info=None):
            captured["status"] = status
        claims, response = self.app._token_accepted(
            start_response, "Bearer " + token, PATH)
        self.assertIsNone(response)
        self.assertIsNotNone(claims)
        self.assertEqual(claims["sub"], "alice")
        self.assertNotIn("status", captured)         # start_response never called

    def test_boundary_claims_that_happen_to_be_empty_are_still_not_a_rejection(self):
        # The trap in its purest form: a `claims` dict that IS falsy
        # (`{}`) must still be distinguishable from rejection, because the
        # signal is the second tuple slot, not `bool(claims)`.
        with mock.patch.object(self.app.token_provider, "verify", return_value={}):
            captured = {}

            def start_response(status, headers, exc_info=None):
                captured["status"] = status
            claims, response = self.app._token_accepted(
                start_response, "Bearer whatever", PATH)
            self.assertEqual(claims, {})
            self.assertIsNone(response)
            self.assertNotIn("status", captured)


class WorkflowDoesNotRunOnRejectedTokenTest(unittest.TestCase):
    """The consequence the falsy trap guards against, proven end to end: a
    rejected token returns 401 and the workflow's `_run` is never reached —
    a failed auth cannot be read as a pass that merely carries no claims."""

    def setUp(self):
        self.app = make_app()

    def test_error_401_and_run_never_called_for_a_garbage_token(self):
        with mock.patch.object(self.app, "_run",
                               wraps=self.app._run) as spy_run:
            status, _, body = call_wsgi(
                self.app, "POST", PATH, body=b'{"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301", "approvals": 0}',
                headers={"Authorization": "Bearer garbage"})
            self.assertEqual(status, 401)
            spy_run.assert_not_called()

    def test_normal_200_and_run_called_once_for_a_valid_token(self):
        token = self.app.token_provider.issue("alice", AUDIENCE)
        with mock.patch.object(self.app, "_run",
                               wraps=self.app._run) as spy_run:
            status, _, body = call_wsgi(
                self.app, "POST", PATH, body=b'{"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301", "approvals": 0}',
                headers={"Authorization": "Bearer " + token})
            self.assertEqual(status, 200)
            spy_run.assert_called_once()


class GuardReadsCallerTest(unittest.TestCase):
    """End to end through the real WSGI request path: a guard's `caller.role
    exists` / `caller.subject exists` genuinely reads the verified token's
    claims, not a stub."""

    def setUp(self):
        self.app = make_app()

    def _post(self, headers):
        return call_wsgi(self.app, "POST", PATH,
                         body=b'{"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301", "approvals": 0}', headers=headers)

    def test_normal_a_token_carrying_role_lets_the_guarded_step_run(self):
        # `issue()` mints only the fixed claim set — forge the role claim by
        # hand the same way test_token_provider.py's own tests do, using the
        # provider's real signing key so verification genuinely succeeds.
        import base64, hmac, hashlib, time
        now = int(time.time())
        header = {"alg": "HS256", "typ": "JWT"}
        claims = {"iss": "lnpl", "aud": AUDIENCE, "sub": "alice", "role": "admin",
                  "jti": "j-1", "iat": now, "nbf": now, "exp": now + 900}
        def b64u(raw):
            return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
        signing_input = "%s.%s" % (b64u(json.dumps(header).encode()),
                                   b64u(json.dumps(claims).encode()))
        sig = hmac.new(SECRET, signing_input.encode(), hashlib.sha256).digest()
        token = "%s.%s" % (signing_input, b64u(sig))

        status, _, body = self._post({"Authorization": "Bearer " + token})
        self.assertEqual(status, 200)
        # The run's own body (M9 — `skipped[]` rides the response): a role
        # claim present -> `caller.role exists` holds -> the guarded
        # Assignment ran -> nothing skipped.
        self.assertEqual(body["skipped"], [])

    def test_normal_a_token_with_no_role_claim_skips_the_guarded_step(self):
        token = self.app.token_provider.issue("alice", AUDIENCE)
        status, _, body = self._post({"Authorization": "Bearer " + token})
        self.assertEqual(status, 200)
        # `caller.role` resolves to None (no `role` claim) -> `exists` is
        # False -> the guard skips the Assignment.
        self.assertEqual(len(body["skipped"]), 1)


class CallerUnavailableWithoutAuthTest(unittest.TestCase):
    """Boundary: no `token_provider` configured at all -> `caller` is None
    throughout, and a guard reading it evaluates to "does not exist" rather
    than raising."""

    def setUp(self):
        self.doc = compile_doc()

    def test_boundary_no_token_provider_caller_is_none_no_exception(self):
        payload = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301", "approvals": 0}
        rows = {"entity.order": {row_key("entity.order", payload):
                                 {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301", "approvals": 0}}}
        interp = Interpreter(self.doc, repo_rows=rows)
        self.assertIsNone(interp.caller)
        result = interp.run_workflow("wf.approve.order", payload)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["skipped"]), 1)


class CallerIsReadOnlyTest(unittest.TestCase):
    """Task 02: `caller.*` as a `set`/`format` TARGET is a compile error —
    the same reason `input` is (RFC-0015 §G15.2 / D4): this is not state the
    workflow owns, it is the caller's identity. Extends the SAME check
    `input` already goes through in `_derive_assignment`/`_derive_format`,
    not a second one."""

    def test_error_set_caller_role_fails_to_compile_and_names_caller(self):
        bad_src = SRC.replace(
            "    set order.approvals to order.approvals + 1",
            "    set caller.role to order.approvals")
        with self.assertRaises(LowerError) as ctx:
            compile_doc(bad_src, "m119bad1")
        self.assertIn("caller scope", str(ctx.exception))
        self.assertIn("not state this workflow owns", str(ctx.exception))

    def test_error_set_caller_subject_fails_to_compile(self):
        bad_src = SRC.replace(
            "    set order.approvals to order.approvals + 1",
            "    set caller.subject to order.approvals")
        with self.assertRaises(LowerError) as ctx:
            compile_doc(bad_src, "m119bad2")
        self.assertIn("caller scope", str(ctx.exception))

    def test_error_format_into_caller_subject_fails_to_compile(self):
        bad_src = SRC.replace(
            "    set order.approvals to order.approvals + 1",
            '    format caller.subject from "{}" with order.approvals')
        with self.assertRaises(LowerError) as ctx:
            compile_doc(bad_src, "m119bad3")
        self.assertIn("caller scope", str(ctx.exception))

    def test_normal_reading_caller_role_in_a_guard_still_compiles(self):
        # Negative control (Task 02 Verify): the write-rejection must not
        # have collaterally broken Task 01's read access.
        doc = compile_doc(SRC, "m119negctrl")
        self.assertTrue(any(n["kind"] == "Workflow" for n in doc["nodes"]))

    def test_regression_the_input_target_message_is_byte_identical(self):
        # Same check, extended — not a rewrite. `input`'s own wording must
        # not have shifted by a single character.
        bad_src = SRC.replace(
            "    set order.approvals to order.approvals + 1",
            "    set input.foo to order.approvals")
        with self.assertRaises(LowerError) as ctx:
            compile_doc(bad_src, "m119inputregress")
        self.assertEqual(
            str(ctx.exception),
            "line 17: 'set input.foo to order.approvals' assigns to the "
            "run's input, which is not state — assign to a row this "
            "workflow read (`<binding>.foo`)")


if __name__ == "__main__":
    unittest.main()

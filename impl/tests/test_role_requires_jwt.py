"""issue #213: `security role <r>` without `security jwt` does not compile.

Before #213 such a service compiled, and `serve` answered 200 to a request
with no Authorization header because route auth keys on `jwt` alone. The
rejection is a `LowerError` raised by `lower()` whose message leads with
`role-requires-jwt`, so every entry point that lowers source refuses it.
"""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from lnpl import wsgi
from lnpl.cli import main
from lnpl.lower import LowerError, lower
from lnpl.parser import parse

from tests.test_mcp_server import call
from tests.test_role_gate import NO_ROLE_SRC, ROLE_GATED_SRC

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLAUDE_TMP = os.path.join(REPO, ".claude", "tmp")

# The issue's own reproduction, verbatim: `role admin` is line 8.
ISSUE_SRC = """capability postgres
entity Order
    field
        id UUID
        approvals Integer
service OrderService
    security
        role admin
    policy
        timeout 5s
workflow CreateOrder
    create order
"""

ISSUE_MESSAGE = ("role-requires-jwt: line 8: service OrderService declares "
                 "`role admin` without `jwt`; role requires jwt: add 'jwt' "
                 "to this service's security block")

# Two services; only AuditService lacks `jwt`. Its `role ops` is line 21.
TWO_SERVICES_SRC = """capability postgres

entity Order
    field
        id UUID
        approvals Integer

service OrderService
    database
        postgres
    security
        jwt
        role admin
workflow ApproveOrder
    read order

service AuditService
    database
        postgres
    security
        role ops
workflow AuditOrder
    read order
"""


def security_mechanisms(source):
    doc = lower(parse(source), "t").to_document()
    return [n["mechanisms"] for n in doc["nodes"] if n["kind"] == "Security"]


class RoleRequiresJwtLoweringTest(unittest.TestCase):

    def test_normal_jwt_and_role_still_lowers_unchanged(self):
        module = lower(parse(ROLE_GATED_SRC), "t")
        doc = module.to_document()
        mechs = [n["mechanisms"] for n in doc["nodes"] if n["kind"] == "Security"]
        self.assertEqual(mechs, [["jwt", "role admin"]])
        subjects = [d.subject for d in module.diagnostics.all()
                    if d.code == "declared-not-enforced"]
        self.assertEqual(subjects, ["security jwt"])

    def test_error_issue_source_does_not_lower(self):
        with self.assertRaises(LowerError) as cm:
            lower(parse(ISSUE_SRC), "t")
        self.assertEqual(str(cm.exception), ISSUE_MESSAGE)

    def test_boundary_role_written_before_jwt_lowers(self):
        source = ISSUE_SRC.replace("        role admin\n",
                                   "        role admin\n        jwt\n")
        self.assertNotEqual(source, ISSUE_SRC)
        self.assertEqual(security_mechanisms(source), [["role admin", "jwt"]])

    def test_boundary_jwt_only_lowers(self):
        self.assertEqual(security_mechanisms(NO_ROLE_SRC), [["jwt"]])

    def test_boundary_only_the_service_without_jwt_is_named(self):
        with self.assertRaises(LowerError) as cm:
            lower(parse(TWO_SERVICES_SRC), "t")
        message = str(cm.exception)
        self.assertTrue(message.startswith(
            "role-requires-jwt: line 21: service AuditService declares `role ops`"),
            message)
        self.assertNotIn("OrderService", message)

    def test_boundary_two_role_lines_name_the_first(self):
        source = ISSUE_SRC.replace("        role admin\n",
                                   "        role admin\n        role ops\n")
        with self.assertRaises(LowerError) as cm:
            lower(parse(source), "t")
        self.assertTrue(str(cm.exception).startswith(
            "role-requires-jwt: line 8: service OrderService declares `role admin`"))

    def test_boundary_bare_role_keeps_its_arity_error(self):
        source = ISSUE_SRC.replace("        role admin\n", "        role\n")
        with self.assertRaises(LowerError) as cm:
            lower(parse(source), "t")
        self.assertIn("needs one argument", str(cm.exception))
        self.assertNotIn("role-requires-jwt", str(cm.exception))


class RoleRequiresJwtEntryPointTest(unittest.TestCase):

    def setUp(self):
        os.makedirs(CLAUDE_TMP, exist_ok=True)
        self.dir = tempfile.mkdtemp(prefix="lnpl-i213-", dir=CLAUDE_TMP)
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def write_source(self, text, name):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_normal_cli_compile_of_jwt_and_role_exits_0(self):
        path = self.write_source(ROLE_GATED_SRC, "gated.lnpl")
        rc, out, err = self.run_cli(["compile", path])
        self.assertEqual(rc, 0, err)
        self.assertNotIn("role-requires-jwt", err)

    def test_error_cli_compile_exits_2(self):
        path = self.write_source(ISSUE_SRC, "order.lnpl")
        rc, out, err = self.run_cli(["compile", path])
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")
        self.assertEqual(err, "compile error: %s\n" % ISSUE_MESSAGE)

    def test_error_cli_compile_json_prints_the_null_document(self):
        path = self.write_source(ISSUE_SRC, "order.lnpl")
        rc, out, err = self.run_cli(["compile", path, "--json"])
        self.assertEqual(rc, 2)
        self.assertEqual(json.loads(out), {"lir_version": None, "module": None,
                                           "nodes": None, "diagnostics": []})
        self.assertIn("role-requires-jwt", err)

    def test_error_build_app_refuses_to_start(self):
        path = self.write_source(ISSUE_SRC, "order.lnpl")
        with mock.patch.dict(os.environ):
            for key in ("LNPL_SOURCE", "LNPL_BACKEND", "LNPL_JWT_SECRET_ENV", "LNPL_CLOCK"):
                os.environ.pop(key, None)
            with self.assertRaises(wsgi.WsgiConfigError) as cm:
                wsgi.build_app(sources=[path])
        self.assertIn("role-requires-jwt", str(cm.exception))

    def test_error_mcp_compile_tool_returns_is_error(self):
        res = call("lnpl_compile", {"text": ISSUE_SRC})
        self.assertIs(res["result"]["isError"], True)
        self.assertIn("LowerError: role-requires-jwt", res["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()

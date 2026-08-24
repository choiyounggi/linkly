"""`--endpoint`/`LNPL_ENDPOINT_*` + `capability http` from the CLI (issue #101).

Three properties carry this file, one per DoD line: a logical `call` target
reaches a real server once mapped; a declared `auth` sends its header and a
missing env var is a failed launch (rc 2), same as `--jwt-secret-env`; an
unmapped logical name under `--network http` is also a failed launch. A
fourth pins the untouched path: a URL literal target and `--network fake`
are both unaffected by any of this — the pre-#101 behaviour, byte-identical.
"""

import http.client
import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout

from lnpl.cli import main
from lnpl.serve import serve

from tests.test_network_driver import _ServerTestCase, _make_handler
from tests.test_serve import compile_src

PAYMENT_TOKEN_ENV = "LNPL_TEST_PAYMENT_TOKEN"

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

URL_LITERAL_SOURCE_TEMPLATE = """
entity Order
    field
        id UUID
service Checkout
workflow Pay
    call %s as p
"""


class CapabilityHttpCliTest(_ServerTestCase):

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.dir = box.name

    def write_source(self, text, name="mod.lnpl"):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(argv)
        return rc, out.getvalue(), err.getvalue()

    def set_env(self, name, value):
        previous = os.environ.get(name)
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

        def restore():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous

        self.addCleanup(restore)

    # ---- normal: mapped logical name calls out for real ----

    def test_a_mapped_logical_name_reaches_the_mock_server(self):
        handler = _make_handler(status=200, body={"ok": True})
        url = self.start(handler)
        source = self.write_source(CALL_SOURCE)
        self.set_env(PAYMENT_TOKEN_ENV, "tok-xyz")

        rc, out, err = self.run_cli(
            ["run", source, "--network", "http",
             "--endpoint", "PaymentGateway=%s" % url, "--json"])

        self.assertEqual(rc, 0, err)
        result = json.loads(out)
        self.assertEqual(result["result"]["status"], "completed")
        self.assertEqual(result["result"]["bindings"]["p"]["ok"], True)

    def test_a_declared_bearer_auth_sends_the_authorization_header(self):
        handler = _make_handler(status=200, body={})
        url = self.start(handler)
        source = self.write_source(CALL_SOURCE)
        self.set_env(PAYMENT_TOKEN_ENV, "tok-xyz")

        rc, _out, err = self.run_cli(
            ["run", source, "--network", "http",
             "--endpoint", "PaymentGateway=%s" % url])

        self.assertEqual(rc, 0, err)
        self.assertEqual(handler.received_headers[0].get("Authorization"),
                         "Bearer tok-xyz")

    def test_cli_endpoint_wins_over_the_environment_variable(self):
        """D2: an explicit --endpoint beats LNPL_ENDPOINT_* for the same name."""
        cli_handler = _make_handler(status=200, body={"via": "cli"})
        cli_url = self.start(cli_handler)
        env_handler = _make_handler(status=200, body={"via": "env"})
        env_url = self.start(env_handler)
        source = self.write_source(CALL_SOURCE)
        self.set_env(PAYMENT_TOKEN_ENV, "tok-xyz")
        self.set_env("LNPL_ENDPOINT_PAYMENTGATEWAY", env_url)

        rc, out, err = self.run_cli(
            ["run", source, "--network", "http",
             "--endpoint", "PaymentGateway=%s" % cli_url, "--json"])

        self.assertEqual(rc, 0, err)
        self.assertEqual(cli_handler.received_methods, ["POST"])
        self.assertEqual(env_handler.received_methods, [])

    def test_the_environment_variable_is_used_when_no_cli_flag_is_given(self):
        handler = _make_handler(status=200, body={})
        url = self.start(handler)
        source = self.write_source(CALL_SOURCE)
        self.set_env(PAYMENT_TOKEN_ENV, "tok-xyz")
        self.set_env("LNPL_ENDPOINT_PAYMENTGATEWAY", url)

        rc, _out, err = self.run_cli(["run", source, "--network", "http"])

        self.assertEqual(rc, 0, err)
        self.assertEqual(handler.received_methods, ["POST"])

    # ---- error: missing auth env / unmapped name -> startup rc 2 ----

    def test_a_missing_auth_env_var_is_a_startup_failure(self):
        handler = _make_handler(status=200, body={})
        url = self.start(handler)
        source = self.write_source(CALL_SOURCE)
        self.set_env(PAYMENT_TOKEN_ENV, None)

        rc, _out, err = self.run_cli(
            ["run", source, "--network", "http",
             "--endpoint", "PaymentGateway=%s" % url])

        self.assertEqual(rc, 2)
        self.assertIn(PAYMENT_TOKEN_ENV, err)
        self.assertEqual(handler.received_methods, [],
                         "a failed launch must not reach the network")

    def test_an_unmapped_logical_name_under_network_http_is_a_startup_failure(self):
        source = self.write_source(UNBOUND_CALL_SOURCE)

        rc, _out, err = self.run_cli(["run", source, "--network", "http"])

        self.assertEqual(rc, 2)
        self.assertIn("PaymentGateway", err)
        self.assertIn("--endpoint", err)

    # ---- boundary: URL literal and --network fake are untouched ----

    def test_a_url_literal_target_needs_no_endpoint_mapping(self):
        handler = _make_handler(status=200, body={"ok": True})
        url = self.start(handler)
        source = self.write_source(URL_LITERAL_SOURCE_TEMPLATE % url)

        rc, out, err = self.run_cli(
            ["run", source, "--network", "http", "--json"])

        self.assertEqual(rc, 0, err)
        result = json.loads(out)
        self.assertEqual(result["result"]["status"], "completed")

    def test_network_fake_needs_no_mapping_even_for_a_logical_name(self):
        source = self.write_source(UNBOUND_CALL_SOURCE)

        rc, out, err = self.run_cli(["run", source, "--json"])

        self.assertEqual(rc, 0, err)
        result = json.loads(out)
        self.assertEqual(result["result"]["status"], "completed")


class CapabilityHttpServeTest(_ServerTestCase):
    """`serve`'s startup path (D3: run and serve both) — `--network`/
    `--endpoint` wired the same way `run` is, since `serve` had no outbound
    network path at all before issue #101 (it built no `network=` kwarg)."""

    def start_lnpl_server(self, doc, **kwargs):
        server = serve(doc, port=0, **kwargs)
        thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def post_json(self, port, path, payload):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        self.addCleanup(conn.close)
        conn.request("POST", path, body=json.dumps(payload).encode(),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        raw = resp.read()
        return resp, json.loads(raw)

    def test_a_shared_http_network_driver_serves_a_mapped_logical_name(self):
        """Unit level: `serve()`'s `network=` kwarg reaches a real request,
        auth header included — the wiring `_respond` needs, independent of
        the CLI's `--network`/`--endpoint` flag parsing."""
        from lnpl.drivers import HttpNetworkDriver

        outbound = _make_handler(status=200, body={"ok": True})
        outbound_url = self.start(outbound)
        doc = compile_src(CALL_SOURCE, "mod")
        driver = HttpNetworkDriver(
            endpoints={"PaymentGateway": outbound_url},
            capabilities={"PaymentGateway": {
                "method": "POST", "headers": {"Authorization": "Bearer tok-xyz"}}})
        self.addCleanup(driver.close)
        port = self.start_lnpl_server(doc, network=driver)

        resp, body = self.post_json(port, "/checkout/pay", {})

        self.assertEqual(resp.status, 200)
        self.assertEqual(body["status"], "completed")
        self.assertEqual(outbound.received_headers[0].get("Authorization"),
                         "Bearer tok-xyz")

    def test_cli_serve_rejects_an_unmapped_logical_name_before_binding(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        source = os.path.join(box.name, "mod.lnpl")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write(UNBOUND_CALL_SOURCE)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(["serve", source, "--port", "0", "--network", "http"])

        self.assertEqual(rc, 2)
        self.assertIn("PaymentGateway", err.getvalue())
        self.assertNotIn("serving", out.getvalue())

    def test_cli_serve_rejects_a_missing_auth_env_before_binding(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        source = os.path.join(box.name, "mod.lnpl")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write(CALL_SOURCE)
        previous = os.environ.pop(PAYMENT_TOKEN_ENV, None)
        if previous is not None:
            self.addCleanup(os.environ.__setitem__, PAYMENT_TOKEN_ENV, previous)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(["serve", source, "--port", "0", "--network", "http",
                      "--endpoint", "PaymentGateway=http://127.0.0.1:1/"])

        self.assertEqual(rc, 2)
        self.assertIn(PAYMENT_TOKEN_ENV, err.getvalue())
        self.assertNotIn("serving", out.getvalue())

    def test_cli_serve_with_network_fake_needs_no_mapping(self):
        """Boundary: `--network` omitted (default `fake`) on `serve` needs no
        `--endpoint` even for a logical-name target — unaffected by #101."""
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        source = os.path.join(box.name, "mod.lnpl")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write(UNBOUND_CALL_SOURCE)
        doc = compile_src(UNBOUND_CALL_SOURCE, "mod")
        port = self.start_lnpl_server(doc)

        resp, body = self.post_json(port, "/checkout/pay", {})

        self.assertEqual(resp.status, 200)
        self.assertEqual(body["status"], "completed")


if __name__ == "__main__":
    unittest.main()

"""Issue #26: `lnpl serve` — HTTP binding over mode A execution.

The status-code mapping table (M1–M9) lives in docs/serving.md and the plan;
every row is covered here. Unit tests bind the pure mapping logic
(`map_result`, `build_routes`, `problem`); `ServeHttpTest` and friends drive
the real socket round trip the issue's third completion criterion demands.
"""

import concurrent.futures
import http.client
import json
import os
import threading
import unittest

from lnpl.lower import lower
from lnpl.openapi import generate
from lnpl.parser import parse
from lnpl.serve import ServeError, build_routes, map_result, problem, serve


def compile_src(source, module="mod"):
    return lower(parse(source), module).to_document()


def compile_file(path):
    with open(path, encoding="utf-8") as fh:
        return compile_src(fh.read(), "shorten")


def result_stub(status="completed", failed_step=None, failure_reason=None,
                steps=(), skipped=(), failure_kind=None):
    """A `run_workflow` result with only the keys `map_result` reads."""
    result = {"status": status, "failed_step": failed_step,
              "failure_reason": failure_reason, "steps": list(steps),
              "skipped": list(skipped), "bindings": {}, "duration_ms": 5,
              "correlation_id": "cid-test"}
    if failure_kind is not None:
        result["failure_kind"] = failure_kind
    return result


class MapResultTest(unittest.TestCase):
    """One test per mapping-table row M6–M9 (M1–M5 are pre-run, HTTP-level)."""

    def test_m9_completed_maps_to_200(self):
        self.assertEqual((200, None), map_result(result_stub()))

    def test_m9_completed_with_guard_skips_still_200(self):
        # D2: a guard doing its job is not a failure (RFC-0014 status-orthogonal
        # signal); the skipped[] record travels in the 200 body, not the status.
        result = result_stub(skipped=[{"guard": "wf.g", "mode": "when",
                                       "condition": "x <= 1", "steps": ["update"]}])
        self.assertEqual((200, None), map_result(result))

    def test_m6_deadline_after_step_maps_to_504(self):
        result = result_stub(status="failed", failed_step="update",
                             failure_reason="deadline exceeded after step 'update'",
                             failure_kind="deadline",
                             steps=[{"step": "update", "effects": ["RepositoryCall"]}])
        self.assertEqual((504, "deadline-exceeded"), map_result(result))

    def test_m6_wins_over_m7_when_deadline_hits_a_validation_step(self):
        # Deadline exhausted *before* the validate step is a timeout, not a
        # payload rejection — M6 is decided before M7.
        result = result_stub(
            status="failed", failed_step="validate input",
            failure_reason="deadline exhausted before step 'validate input'",
            failure_kind="deadline",
            steps=[{"step": "validate input", "effects": ["Validation"]}])
        self.assertEqual((504, "deadline-exceeded"), map_result(result))

    def test_m7_validation_failure_maps_to_400(self):
        result = result_stub(
            status="failed", failed_step="validate input",
            failure_reason="field 'slug' does not match Slug's pattern",
            steps=[{"step": "validate input", "effects": ["Validation"]}])
        self.assertEqual((400, "validation-failed"), map_result(result))

    def test_m8_other_failure_maps_to_500(self):
        result = result_stub(
            status="failed", failed_step="cache link",
            failure_reason="cache set without a TTL",
            steps=[{"step": "cache link", "effects": ["CacheAccess"]}])
        self.assertEqual((500, "workflow-failed"), map_result(result))


class ProblemTest(unittest.TestCase):
    def test_problem_carries_the_stable_contract_fields(self):
        body = problem(400, "validation-failed", "field 'slug' rejected",
                       correlation_id="req-1", skipped=[])
        self.assertEqual(400, body["status"])
        self.assertEqual("validation-failed", body["code"])
        self.assertEqual("field 'slug' rejected", body["detail"])
        self.assertEqual("req-1", body["correlation_id"])
        self.assertIn("title", body)


REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHORTEN = os.path.join(REPO, "examples", "shorten.lnpl")


class BuildRoutesTest(unittest.TestCase):
    def test_shorten_route_matches_the_openapi_contract(self):
        doc = compile_file(SHORTEN)
        routes = build_routes(doc)
        self.assertIn("/shorten-service/shorten", routes)
        entry = routes["/shorten-service/shorten"]
        self.assertTrue(entry["auth"])          # `security jwt` is declared
        workflows = {n["id"] for n in doc["nodes"] if n["kind"] == "Workflow"}
        self.assertIn(entry["workflow"], workflows)
        # Drift guard: the served paths ARE the published contract's paths.
        self.assertEqual(set(routes), set(generate(doc)["paths"]))

    def test_document_without_workflows_yields_empty_routes(self):
        doc = compile_src("capability postgres\n"
                          "entity Thing\n"
                          "    field\n"
                          "        id UUID\n")
        self.assertEqual({}, build_routes(doc))


# A full, valid Link payload — every field explicit so a reader can tell why
# the run completes from the values alone (clicks 0 is ClickCount's boundary:
# `refine ClickCount of Integer / min 0` admits a brand-new link).
LINK_PAYLOAD = {
    "id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
    "slug": "abc-123",
    "target": "https://example.com/a",
    "owner": "3f2504e0-4f89-41d3-9a0c-0305e82c3302",
    "clicks": 0,
    "createdAt": "2026-07-31T09:00:00Z",
}

SHORTEN_PATH = "/shorten-service/shorten"


class ServerTestCase(unittest.TestCase):
    """Boots one server per test on an ephemeral port; teardown always runs."""

    def start(self, doc, **kwargs):
        server = serve(doc, port=0, **kwargs)
        thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def request(self, port, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        self.addCleanup(conn.close)
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        raw = resp.read()
        return resp, raw

    def post_json(self, port, path, payload, headers=None):
        headers = dict(headers or {})
        headers.setdefault("Authorization", "Bearer test-token")
        resp, raw = self.request(port, "POST", path,
                                 body=json.dumps(payload).encode(), headers=headers)
        return resp, json.loads(raw)


class ServeHttpTest(ServerTestCase):
    """M1–M5 + the shorten end-to-end round trip (issue #26 criteria 1 and 3)."""

    def setUp(self):
        self.port = self.start(compile_file(SHORTEN))

    def test_shorten_round_trip_completes_with_200(self):
        resp, body = self.post_json(self.port, SHORTEN_PATH, LINK_PAYLOAD)
        self.assertEqual(200, resp.status)
        self.assertEqual("application/json", resp.getheader("Content-Type"))
        self.assertEqual("completed", body["status"])
        self.assertTrue(body["correlation_id"].startswith("req-"))
        self.assertIn("bindings", body)
        self.assertEqual([], body["skipped"])

    def test_m3_missing_authorization_is_401(self):
        resp, raw = self.request(
            self.port, "POST", SHORTEN_PATH,
            body=json.dumps(LINK_PAYLOAD).encode())
        body = json.loads(raw)
        self.assertEqual(401, resp.status)
        self.assertEqual("auth-missing", body["code"])
        self.assertEqual("application/problem+json",
                         resp.getheader("Content-Type"))

    def test_m1_unknown_path_is_404(self):
        resp, raw = self.request(self.port, "POST", "/nope",
                                 headers={"Authorization": "Bearer x"})
        self.assertEqual(404, resp.status)
        self.assertEqual("not-found", json.loads(raw)["code"])

    def test_m2_wrong_method_is_405_with_allow(self):
        resp, raw = self.request(self.port, "GET", SHORTEN_PATH)
        self.assertEqual(405, resp.status)
        self.assertEqual("POST", resp.getheader("Allow"))
        self.assertEqual("method-not-allowed", json.loads(raw)["code"])

    def test_m5_unparseable_body_is_400(self):
        resp, raw = self.request(self.port, "POST", SHORTEN_PATH,
                                 body=b"{not json",
                                 headers={"Authorization": "Bearer x"})
        self.assertEqual(400, resp.status)
        self.assertEqual("body-unreadable", json.loads(raw)["code"])

    def test_m5_non_object_json_body_is_400(self):
        resp, raw = self.request(self.port, "POST", SHORTEN_PATH,
                                 body=b"[1, 2]",
                                 headers={"Authorization": "Bearer x"})
        self.assertEqual(400, resp.status)
        self.assertEqual("body-unreadable", json.loads(raw)["code"])

    def test_m4_oversized_content_length_is_413(self):
        # The header alone triggers the rejection — the body is never read, so
        # sending none must not hang the request.
        resp, raw = self.request(self.port, "POST", SHORTEN_PATH,
                                 headers={"Authorization": "Bearer x",
                                          "Content-Length": "2000000"})
        self.assertEqual(413, resp.status)
        self.assertEqual("body-too-large", json.loads(raw)["code"])

    def test_empty_body_fails_the_workflows_own_validation_as_400(self):
        # No special case: an empty body runs as payload {} and the workflow's
        # Validation effect rejects it (M7) — the boundary does not re-validate.
        resp, raw = self.request(self.port, "POST", SHORTEN_PATH,
                                 headers={"Authorization": "Bearer x"})
        body = json.loads(raw)
        self.assertEqual(400, resp.status)
        self.assertEqual("validation-failed", body["code"])
        self.assertIn("missing required field", body["detail"])


# Inline fixtures for the post-run mapping rows. Vocabulary reused from
# qa/cases/payment-refund via test_masking_channels.py (closed lexicon —
# nothing invented). The canary is the canonical test PAN.
CARD = "4111111111111111"

MASK_SRC = """
capability postgres
entity Payment
    field
        id UUID
        cardNumber Password
        amountCents Integer
service PaymentService
    policy
        retry 0
workflow Approval
    validate payment
    find payment
    when payment.amountCents <= 1000000
    update payment
"""

PAYMENT = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
           "cardNumber": CARD, "amountCents": 500}

# 3 steps x 5ms fake-clock cost > the 10ms deadline -> M6 over the socket.
DEADLINE_SRC = """
capability postgres
entity Payment
    field
        id UUID
        amountCents Integer
service SlowService
    policy
        timeout 10ms
workflow Crawl
    validate payment
    find payment
    update payment
"""

# `cache` with no `performance cache` TTL budget raises RunError at run time —
# a failure that is neither validation nor deadline -> M8.
CACHE_SRC = """
capability postgres
capability redis
entity Payment
    field
        id UUID
        amountCents Integer
service CacheService
    policy
        retry 0
workflow Warm
    find payment
    cache payment
"""

SMALL_PAYMENT = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3301", "amountCents": 5}


class ServeSemanticsTest(ServerTestCase):
    """M6/M8, the guard-rejection contract (D2), masking (D7), concurrency (D5)."""

    def test_m6_deadline_exceeded_maps_to_504_over_http(self):
        port = self.start(compile_src(DEADLINE_SRC, "slow"))
        resp, body = self.post_json(port, "/slow-service/crawl", SMALL_PAYMENT)
        self.assertEqual(504, resp.status)
        self.assertEqual("deadline-exceeded", body["code"])
        self.assertIn("deadline", body["detail"])
        self.assertIn("failed_step", body)

    def test_m8_non_validation_failure_maps_to_500_over_http(self):
        port = self.start(compile_src(CACHE_SRC, "cachy"))
        resp, body = self.post_json(port, "/cache-service/warm", SMALL_PAYMENT)
        self.assertEqual(500, resp.status)
        self.assertEqual("workflow-failed", body["code"])
        self.assertEqual("cache payment", body["failed_step"])
        self.assertIn("correlation_id", body)
        self.assertNotIn("Traceback", json.dumps(body))

    def test_guard_rejection_is_200_with_skipped_in_the_body(self):
        # D2: RFC-0014's status-orthogonal signal — the guard doing its job is
        # not an HTTP failure; the observation contract rides skipped[].
        port = self.start(compile_src(MASK_SRC, "pay"))
        over_limit = dict(PAYMENT, amountCents=2000000)
        resp, body = self.post_json(port, "/payment-service/approval", over_limit)
        self.assertEqual(200, resp.status)
        self.assertEqual("completed", body["status"])
        skipped_steps = [s for rec in body["skipped"] for s in rec["steps"]]
        self.assertEqual(["update payment"], skipped_steps)

    def test_masking_holds_on_the_200_response_channel(self):
        # D7: the HTTP response is a NEW output channel — sweep it: raw canary
        # absent, mask present, and an unmasked control field present so the
        # absence is not vacuous.
        port = self.start(compile_src(MASK_SRC, "pay"))
        resp, raw = self.request(
            port, "POST", "/payment-service/approval",
            body=json.dumps(PAYMENT).encode(),
            headers={"Authorization": "Bearer x"})
        self.assertEqual(200, resp.status)
        self.assertNotIn(CARD.encode(), raw)
        self.assertIn(b"***", raw)
        self.assertIn(PAYMENT["id"].encode(), raw)     # negative control
        body = json.loads(raw)
        self.assertEqual("***", body["bindings"]["payment"]["cardNumber"])

    def test_masking_holds_on_the_400_response_channel(self):
        port = self.start(compile_src(MASK_SRC, "pay"))
        bad = dict(PAYMENT, amountCents="not-a-number")
        resp, raw = self.request(
            port, "POST", "/payment-service/approval",
            body=json.dumps(bad).encode(),
            headers={"Authorization": "Bearer x"})
        self.assertEqual(400, resp.status)
        self.assertEqual("validation-failed", json.loads(raw)["code"])
        self.assertNotIn(CARD.encode(), raw)
        self.assertIn(b"amountCents", raw)             # negative control

    def test_concurrent_requests_stay_isolated(self):
        # D5's measurement: 8 parallel runs, each with its own payload; every
        # response must carry its own row (no cross-talk) under a fresh
        # correlation id (no shared Interpreter state).
        port = self.start(compile_src(MASK_SRC, "pay"))

        def post(i):
            payload = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c33%02x" % i,
                       "cardNumber": CARD, "amountCents": 1000 + i}
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            try:
                conn.request("POST", "/payment-service/approval",
                             body=json.dumps(payload).encode(),
                             headers={"Authorization": "Bearer x"})
                resp = conn.getresponse()
                return payload, resp.status, json.loads(resp.read())
            finally:
                conn.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(post, range(8)))
        correlation_ids = set()
        for payload, status, body in outcomes:
            self.assertEqual(200, status)
            self.assertEqual(payload["amountCents"],
                             body["bindings"]["payment"]["amountCents"])
            self.assertEqual(payload["id"], body["bindings"]["payment"]["id"])
            correlation_ids.add(body["correlation_id"])
        self.assertEqual(8, len(correlation_ids))


class CmdServeTest(unittest.TestCase):
    """`lnpl serve` wiring: argparse defaults, SIGINT exit, and the rc contract
    (0 clean exit / 1 nothing to serve / 2 compile error), via cli.main like
    every other subcommand (issue #27's lesson)."""

    def setUp(self):
        import contextlib
        import io
        self.workdir = os.path.join(REPO, ".claude", "tmp", "cli-serve")
        os.makedirs(self.workdir, exist_ok=True)
        self._io = io
        self._contextlib = contextlib

    def tearDown(self):
        import shutil
        shutil.rmtree(self.workdir, ignore_errors=True)

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

    def test_sigint_shuts_down_cleanly_with_rc_0(self):
        # KeyboardInterrupt out of serve_forever is the SIGINT path (D10):
        # rc 0 and the socket closed, no traceback.
        from unittest import mock
        src = self._write("ok.lnpl", MASK_SRC)
        server = mock.Mock()
        server.server_address = ("127.0.0.1", 8080)
        server.serve_forever.side_effect = KeyboardInterrupt
        with mock.patch("lnpl.cli.serve", return_value=server) as factory:
            rc, out, err = self._main(["serve", src])
        self.assertEqual(0, rc)
        server.server_close.assert_called_once()
        factory.assert_called_once()
        args, _ = factory.call_args
        self.assertEqual(("127.0.0.1", 8080), args[1:3])   # argparse defaults
        self.assertIn("http://127.0.0.1:8080", out)

    def test_host_and_port_flags_reach_the_server(self):
        from unittest import mock
        src = self._write("ok.lnpl", MASK_SRC)
        server = mock.Mock()
        server.server_address = ("0.0.0.0", 9999)
        server.serve_forever.side_effect = KeyboardInterrupt
        with mock.patch("lnpl.cli.serve", return_value=server) as factory:
            rc, _, _ = self._main(["serve", src, "--host", "0.0.0.0",
                                   "--port", "9999"])
        self.assertEqual(0, rc)
        self.assertEqual(("0.0.0.0", 9999), factory.call_args[0][1:3])

    def test_source_without_workflows_is_rc_1(self):
        src = self._write("empty.lnpl",
                          "capability postgres\n"
                          "entity Thing\n"
                          "    field\n"
                          "        id UUID\n")
        rc, _, err = self._main(["serve", src])
        self.assertEqual(1, rc)
        self.assertIn("no workflow to serve", err)

    def test_compile_error_is_rc_2(self):
        from unittest import mock
        # A nameless entity is a ParseError. serve is mocked anyway so that a
        # fixture that unexpectedly compiles can never boot a real server and
        # block the suite on serve_forever.
        src = self._write("broken.lnpl", "entity\n")
        with mock.patch("lnpl.cli.serve") as factory:
            rc, _, err = self._main(["serve", src])
        self.assertEqual(2, rc)
        self.assertIn("compile error", err)
        factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()

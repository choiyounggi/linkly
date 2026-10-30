"""The MCP Streamable HTTP transport (issue #250) over real sockets.

Every server here binds 127.0.0.1 port 0 and is shut down by addCleanup.
The request gate has a fixed order — Origin (403), path (404), Bearer token
(401), MCP-Protocol-Version (400) — and each test that pins one step sends a
request that would also fail a LATER step, so a reordering turns it red.

Tool calls run in a child process with time, memory and result-size limits.
Those tests start real children and wait for them, with client-side
deadlines so a broken limit fails instead of hanging the suite.
"""
import hmac
import http.client
import io
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

from lnpl import mcp_http, mcp_server
from tests.test_mcp_server import CLEAN, INITIALIZE, REPO, converse

IMPL = os.path.join(REPO, "impl")
TOKEN = "test-token-" + "x" * 32
TOOLS_LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}
# `read note` inside the loop keeps it running: a `create note` runaway
# finishes at once, so it would test nothing.
RUNAWAY = ("entity Note\n    field\n        id UUID\n\n"
           "workflow Save\n    validate note\n    repeat 999999999999\n    read note\n")


def repeat_read(n):
    return ("entity Note\n    field\n        id UUID\n\n"
            "workflow Save\n    validate note\n    repeat %d\n    read note\n" % n)


def run_call(text, mid=3):
    return {"jsonrpc": "2.0", "id": mid, "method": "tools/call",
            "params": {"name": "lnpl_run", "arguments": {"text": text}}}


def compile_call(args, mid=4):
    return {"jsonrpc": "2.0", "id": mid, "method": "tools/call",
            "params": {"name": "lnpl_compile", "arguments": args}}


def result_of(body):
    return json.loads(body)["result"]


def tool_text(body):
    return result_of(body)["content"][0]["text"]


class HttpServerCase(unittest.TestCase):

    def start_server(self, **options):
        server = mcp_http.make_server("127.0.0.1", 0, TOKEN, **options)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def stop():
            server.shutdown()
            thread.join(5)
            server.server_close()
        self.addCleanup(stop)
        self.port = server.server_address[1]
        return server

    def request(self, method, body=None, headers=None, path="/mcp", auth=True, timeout=5):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            all_headers = {}
            if auth:
                all_headers["Authorization"] = "Bearer " + TOKEN
            all_headers.update(headers or {})
            conn.request(method, path, body=body, headers=all_headers)
            resp = conn.getresponse()
            return resp.status, resp.headers, resp.read()
        finally:
            conn.close()

    def post(self, message, sid=None, headers=None, raw=None, timeout=5, auth=True, path="/mcp"):
        body = raw if raw is not None else json.dumps(message)
        all_headers = {"Content-Type": "application/json",
                       "Accept": "application/json, text/event-stream"}
        if sid is not None:
            all_headers["Mcp-Session-Id"] = sid
        all_headers.update(headers or {})
        return self.request("POST", body=body, headers=all_headers, timeout=timeout,
                            auth=auth, path=path)

    def initialize(self):
        status, headers, body = self.post(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(status, 200, body)
        return headers["Mcp-Session-Id"]

    def headers_only_post(self, header_pairs, auth=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.putrequest("POST", "/mcp")
            for name, value in header_pairs:
                conn.putheader(name, value)
            if auth:
                conn.putheader("Authorization", "Bearer " + TOKEN)
            conn.endheaders()
            resp = conn.getresponse()
            return resp.status, resp.headers, resp.read()
        finally:
            conn.close()

    def error_of(self, body):
        return json.loads(body)["error"]


# --- Task 04: the request gate -------------------------------------------


class OriginTest(HttpServerCase):

    def setUp(self):
        self.start_server()

    def test_a_foreign_origin_is_403(self):
        status, _, body = self.request("GET", headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        self.assertEqual(self.error_of(body)["message"], "origin not allowed")

    def test_a_loopback_origin_and_no_origin_pass_the_gate(self):
        for headers in ({"Origin": "http://localhost:5173"}, {"Origin": "http://127.0.0.1"},
                        {"Origin": "http://[::1]:3000"}, {}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("GET", headers=headers)[0], 405)

    def test_lookalike_origins_are_403(self):
        for origin in ("null", "http://localhost.evil.example", "http://127.0.0.1.evil.example",
                       "http://localhost:abc", "http://evil.example@localhost",
                       "http://localhost/x", "http://localhost?q", "https://localhost", ""):
            with self.subTest(origin=origin):
                self.assertEqual(self.request("GET", headers={"Origin": origin})[0], 403)

    def test_origin_is_checked_before_path_and_auth(self):
        bad = {"Origin": "https://evil.example"}
        self.assertEqual(self.request("GET", headers=bad, path="/other")[0], 403)
        self.assertEqual(self.request("GET", headers=bad, auth=False)[0], 403)

    def test_origin_allowed_unit(self):
        self.assertTrue(mcp_http.origin_allowed("http://[::1]:3000"))
        self.assertTrue(mcp_http.origin_allowed("http://LOCALHOST"))
        self.assertFalse(mcp_http.origin_allowed("http://[::1"))


class PathTest(HttpServerCase):

    def setUp(self):
        self.start_server()

    def test_other_paths_are_404_before_auth(self):
        self.assertEqual(self.request("GET", path="/other")[0], 404)
        self.assertEqual(self.request("GET", path="/other", auth=False)[0], 404)
        self.assertEqual(self.request("GET", path="/mcp/")[0], 404)

    def test_the_query_string_does_not_change_routing(self):
        self.assertEqual(self.request("GET", path="/mcp?x=1")[0], 405)


class AuthTest(HttpServerCase):

    def setUp(self):
        self.start_server()

    def test_no_token_is_401_with_a_challenge(self):
        status, headers, _ = self.request("GET", auth=False)
        self.assertEqual(status, 401)
        self.assertEqual(headers["WWW-Authenticate"], 'Bearer realm="lnpl-mcp"')

    def test_every_bad_credential_gets_the_same_401(self):
        bodies = [self.request("GET", auth=False)[2]]
        for value in ("Basic xyz", "Bearer wrong", "Bearer ", "Bearer " + TOKEN + "x",
                      "Bearer  " + TOKEN, TOKEN):
            with self.subTest(value=value):
                status, _, body = self.request("GET", auth=False,
                                               headers={"Authorization": value})
                self.assertEqual(status, 401)
                bodies.append(body)
        self.assertEqual(len(set(bodies)), 1, bodies)

    def test_the_scheme_is_case_insensitive(self):
        status = self.request("GET", auth=False, headers={"Authorization": "bearer " + TOKEN})[0]
        self.assertEqual(status, 405)

    def test_a_token_in_the_query_string_is_ignored(self):
        self.assertEqual(self.request("GET", auth=False, path="/mcp?access_token=" + TOKEN)[0], 401)

    def test_the_comparison_is_constant_time(self):
        with mock.patch.object(hmac, "compare_digest", wraps=hmac.compare_digest) as spy:
            self.assertEqual(self.request("GET")[0], 405)
        spy.assert_called_once_with(TOKEN.encode(), TOKEN.encode())


class ProtocolHeaderTest(HttpServerCase):

    def setUp(self):
        self.start_server()

    def test_an_unsupported_version_is_400(self):
        status, _, body = self.request("GET", headers={"MCP-Protocol-Version": "1999-01-01"})
        self.assertEqual(status, 400)
        self.assertEqual(self.error_of(body)["message"], "unsupported MCP-Protocol-Version")

    def test_supported_or_absent_versions_pass(self):
        self.assertEqual(self.request("GET", headers={"MCP-Protocol-Version": "2025-06-18"})[0], 405)
        self.assertEqual(self.request("GET")[0], 405)

    def test_auth_comes_before_the_version_check(self):
        status = self.request("GET", auth=False, headers={"MCP-Protocol-Version": "1999-01-01"})[0]
        self.assertEqual(status, 401)


class MethodTest(HttpServerCase):

    def setUp(self):
        self.start_server()

    def test_get_is_405_with_allow(self):
        status, headers, body = self.request("GET")
        self.assertEqual(status, 405)
        self.assertEqual(headers["Allow"], "POST, DELETE")
        self.assertEqual(self.error_of(body)["code"], mcp_server.INVALID_REQUEST)

    def test_head_is_405_without_a_body(self):
        status, _, body = self.request("HEAD")
        self.assertEqual(status, 405)
        self.assertEqual(body, b"")

    def test_put_patch_options_are_405(self):
        for method in ("PUT", "PATCH", "OPTIONS"):
            with self.subTest(method=method):
                self.assertEqual(self.request(method)[0], 405)

    def test_options_without_a_token_is_401_not_a_cors_answer(self):
        status, headers, _ = self.request("OPTIONS", auth=False,
                                          headers={"Origin": "http://localhost:5173"})
        self.assertEqual(status, 401)
        self.assertIsNone(headers.get("Access-Control-Allow-Origin"))


class HeadersTest(HttpServerCase):

    def setUp(self):
        self.start_server()

    def test_every_response_has_the_hardening_headers(self):
        for kwargs in ({}, {"auth": False}, {"path": "/x"}):
            with self.subTest(**kwargs):
                _, headers, _ = self.request("GET", **kwargs)
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(headers["Server"], "lnpl-mcp")


class ServerConstructionTest(unittest.TestCase):

    def test_bad_tokens_refuse_construction(self):
        for token, needle in ((None, "LNPL_MCP_TOKEN is not set"), ("", "LNPL_MCP_TOKEN is not set"),
                              ("x" * 31, "at least 32 bytes"),
                              ("x" * 31 + "\n", "visible ASCII"),
                              ("x" * 32 + " ", "visible ASCII"),
                              ("é" * 20, "visible ASCII")):
            with self.subTest(token=token):
                with self.assertRaises(ValueError) as ctx:
                    mcp_http.make_server("127.0.0.1", 0, token)
                self.assertIn(needle, str(ctx.exception))
                if token:
                    self.assertNotIn(token, str(ctx.exception))

    def test_a_32_byte_token_is_the_minimum(self):
        self.assertIsNone(mcp_http.check_token("x" * 32))
        server = mcp_http.make_server("127.0.0.1", 0, "x" * 32)
        self.addCleanup(server.server_close)
        self.assertEqual(server.server_address[0], "127.0.0.1")

    def test_session_tables_are_per_instance(self):
        a = mcp_http.make_server("127.0.0.1", 0, TOKEN)
        self.addCleanup(a.server_close)
        b = mcp_http.make_server("127.0.0.1", 0, TOKEN)
        self.addCleanup(b.server_close)
        self.assertIsNot(a.sessions, b.sessions)
        self.assertIsNot(a.lock, b.lock)


class IdleClientTest(HttpServerCase):

    def test_an_idle_connection_is_dropped(self):
        self.start_server(request_timeout=0.2)
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=3)
        self.addCleanup(sock.close)
        self.assertEqual(sock.recv(1), b"")


# --- Task 05: POST pipeline and sessions ----------------------------------


class MessageFlowTest(HttpServerCase):

    def setUp(self):
        self.start_server()

    def test_initialize_returns_json_and_a_session_id(self):
        status, headers, body = self.post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                           "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertRegex(headers["Mcp-Session-Id"], r"^[0-9a-f]{32}$")
        self.assertEqual(result_of(body)["protocolVersion"], "2025-06-18")

    def test_notifications_and_client_responses_are_202_empty(self):
        sid = self.initialize()
        for message in (INITIALIZED, {"jsonrpc": "2.0", "id": 7, "result": {}},
                        {"jsonrpc": "2.0", "id": 8, "error": {"code": 1, "message": "x"}}):
            with self.subTest(message=message):
                status, headers, body = self.post(message, sid=sid)
                self.assertEqual(status, 202)
                self.assertEqual(body, b"")
                self.assertEqual(headers["Content-Length"], "0")

    def test_tools_list_and_a_tool_call(self):
        sid = self.initialize()
        status, _, body = self.post(TOOLS_LIST, sid=sid)
        self.assertEqual(status, 200)
        self.assertEqual([t["name"] for t in result_of(body)["tools"]],
                         [t["name"] for t in mcp_server.TOOLS])
        status, _, body = self.post(compile_call({"text": CLEAN}), sid=sid, timeout=30)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(tool_text(body))["unknown_verbs"], 0)

    def test_a_missing_accept_header_is_tolerated(self):
        sid = self.initialize()
        status, _, _ = self.request("POST", body=json.dumps(TOOLS_LIST),
                                    headers={"Content-Type": "application/json",
                                             "Mcp-Session-Id": sid})
        self.assertEqual(status, 200)

    def test_path_arguments_are_refused_over_http(self):
        sid = self.initialize()
        status, _, body = self.post(compile_call({"path": "/etc/hosts"}), sid=sid, timeout=30)
        self.assertEqual(status, 200)
        self.assertIs(result_of(body)["isError"], True)
        self.assertIn("`path`", tool_text(body))

    def test_an_unknown_method_is_a_jsonrpc_error(self):
        sid = self.initialize()
        status, _, body = self.post({"jsonrpc": "2.0", "id": 9, "method": "nope"}, sid=sid)
        self.assertEqual(status, 200)
        self.assertEqual(self.error_of(body)["code"], mcp_server.METHOD_NOT_FOUND)

    def test_a_failed_initialize_creates_no_session(self):
        status, headers, body = self.post({"jsonrpc": "1.0", "id": 1, "method": "initialize"})
        self.assertEqual(status, 200)
        self.assertIn("error", json.loads(body))
        self.assertIsNone(headers.get("Mcp-Session-Id"))


class SessionTest(HttpServerCase):

    def test_session_rules(self):
        self.start_server()
        missing = self.post(TOOLS_LIST)
        self.assertEqual(missing[0], 400)
        self.assertEqual(self.error_of(missing[2])["message"], "missing Mcp-Session-Id header")
        self.assertEqual(self.post(INITIALIZED)[0], 400)
        unknown = self.post(TOOLS_LIST, sid="nope")
        self.assertEqual(unknown[0], 404)
        self.assertEqual(self.error_of(unknown[2])["message"], "unknown or terminated session")

    def test_delete_ends_a_session(self):
        self.start_server()
        sid = self.initialize()
        self.assertEqual(self.post(TOOLS_LIST, sid=sid)[0], 200)
        status, _, body = self.request("DELETE", headers={"Mcp-Session-Id": sid})
        self.assertEqual((status, body), (204, b""))
        self.assertEqual(self.post(TOOLS_LIST, sid=sid)[0], 404)
        self.assertEqual(self.request("DELETE", headers={"Mcp-Session-Id": sid})[0], 404)
        self.assertEqual(self.request("DELETE")[0], 400)
        self.assertEqual(self.request("DELETE", auth=False, headers={"Mcp-Session-Id": sid})[0], 401)

    def test_a_client_chosen_session_id_is_ignored(self):
        self.start_server()
        status, headers, _ = self.post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                        "params": {}},
                                       headers={"Mcp-Session-Id": "attacker-chosen"})
        self.assertEqual(status, 200)
        self.assertNotEqual(headers["Mcp-Session-Id"], "attacker-chosen")
        self.assertEqual(self.post(TOOLS_LIST, sid="attacker-chosen")[0], 404)

    def test_the_oldest_session_is_evicted(self):
        self.start_server(max_sessions=2)
        first, second, third = self.initialize(), self.initialize(), self.initialize()
        self.assertEqual(self.post(TOOLS_LIST, sid=first)[0], 404)
        self.assertEqual(self.post(TOOLS_LIST, sid=second)[0], 200)
        self.assertEqual(self.post(TOOLS_LIST, sid=third)[0], 200)


class BodyLimitTest(HttpServerCase):

    def setUp(self):
        self.start_server()

    def test_an_oversized_body_is_413_without_reading_it(self):
        started = time.monotonic()
        status, _, body = self.headers_only_post(
            [("Content-Type", "application/json"),
             ("Content-Length", str(mcp_http.MAX_BODY_BYTES + 1))])
        self.assertEqual(status, 413)
        self.assertEqual(self.error_of(body)["message"], "request body too large")
        self.assertLess(time.monotonic() - started, 5)

    def test_auth_is_checked_before_the_body(self):
        status = self.headers_only_post([("Content-Type", "application/json"),
                                         ("Content-Length", str(mcp_http.MAX_BODY_BYTES + 1))],
                                        auth=False)[0]
        self.assertEqual(status, 401)

    def test_length_and_encoding_errors_are_411(self):
        for pairs in ([("Content-Type", "application/json")],
                      [("Content-Type", "application/json"), ("Content-Length", "abc")],
                      [("Content-Type", "application/json"), ("Content-Length", "-1")],
                      [("Content-Type", "application/json"), ("Content-Length", "1_0")],
                      [("Content-Type", "application/json"), ("Content-Length", "+5")],
                      [("Content-Type", "application/json"), ("Transfer-Encoding", "chunked"),
                       ("Content-Length", "2")]):
            with self.subTest(pairs=pairs):
                self.assertEqual(self.headers_only_post(pairs)[0], 411)

    def test_content_type_must_be_json(self):
        sid = self.initialize()
        self.assertEqual(self.post(TOOLS_LIST, sid=sid,
                                   headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.post(TOOLS_LIST, sid=sid,
                                   headers={"Content-Type": "Application/JSON; charset=utf-8"})[0],
                         200)

    def test_malformed_bodies_are_400(self):
        for raw, code in (("{", mcp_server.PARSE_ERROR),
                          ("[" * 100000 + "]" * 100000, mcp_server.PARSE_ERROR),
                          (b"\xff", mcp_server.PARSE_ERROR),
                          ("", mcp_server.PARSE_ERROR),
                          ("[]", mcp_server.INVALID_REQUEST),
                          ("null", mcp_server.INVALID_REQUEST)):
            with self.subTest(raw=raw[:10]):
                status, _, body = self.post(None, raw=raw)
                self.assertEqual(status, 400)
                self.assertEqual(self.error_of(body)["code"], code)

    def test_a_body_of_exactly_the_cap_is_accepted(self):
        sid = self.initialize()
        data = json.dumps(compile_call({"text": CLEAN})).encode("utf-8")
        data += b" " * (mcp_http.MAX_BODY_BYTES - len(data))
        self.assertEqual(len(data), mcp_http.MAX_BODY_BYTES)
        status, _, body = self.post(None, raw=data, sid=sid, timeout=30)
        self.assertEqual(status, 200)
        self.assertIs(result_of(body)["isError"], False)


class InternalErrorTest(HttpServerCase):

    def test_an_unexpected_fault_is_a_generic_32603(self):
        self.start_server()
        sid = self.initialize()
        with mock.patch("lnpl.mcp_server.handle", side_effect=RuntimeError("/secret/dir boom")), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            status, _, body = self.post(TOOLS_LIST, sid=sid)
        self.assertEqual(status, 200)
        error = self.error_of(body)
        self.assertEqual(error["code"], mcp_server.INTERNAL_ERROR)
        self.assertEqual(error["message"], "internal error")
        self.assertEqual(json.loads(body)["id"], TOOLS_LIST["id"])
        self.assertNotIn(b"Traceback", body)
        self.assertNotIn(b"/secret/dir", body)
        self.assertIn("/secret/dir boom", err.getvalue())


class LogTest(HttpServerCase):

    def test_the_access_log_drops_queries_and_headers(self):
        self.start_server()
        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            status, _, body401 = self.post(INITIALIZED, auth=False, path="/mcp?access_token=" + TOKEN)
            self.assertEqual(status, 401)
            status, _, body200 = self.post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                            "params": {}})
            self.assertEqual(status, 200)
        log = err.getvalue()
        self.assertNotIn(TOKEN, log)
        self.assertIn("lnpl-mcp: POST /mcp 401", log)
        self.assertIn("lnpl-mcp: POST /mcp 200", log)
        self.assertNotIn(TOKEN.encode(), body401 + body200)


# --- Task 06: tool calls in a bounded child --------------------------------


class TimeLimitTest(HttpServerCase):

    def test_a_runaway_call_is_stopped_and_does_not_block_others(self):
        self.start_server(tool_timeout=1.0, child_memory_bytes=4 << 30)
        sid = self.initialize()
        done = {}

        def runaway():
            status, _, body = self.post(run_call(RUNAWAY), sid=sid, timeout=30)
            done["result"] = (status, body, time.monotonic())

        t0 = time.monotonic()
        thread = threading.Thread(target=runaway, daemon=True)
        thread.start()
        time.sleep(0.3)
        started = time.monotonic()
        status, _, _ = self.post(TOOLS_LIST, sid=sid)
        self.assertEqual(status, 200)
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertNotIn("result", done)
        thread.join(10)
        self.assertFalse(thread.is_alive())
        status, body, finished = done["result"]
        self.assertEqual(status, 200)
        self.assertIs(result_of(body)["isError"], True)
        self.assertIn("ran longer than the 1 s limit", tool_text(body))
        self.assertLess(finished - t0, 6)


# A fresh interpreter whose ONLY child is the tool child: RUSAGE_CHILDREN is
# the max over every reaped child of a process, so measuring in the test
# runner itself would include every other test's children.
MEMORY_SCENARIO = r"""
import http.client, json, resource, sys, threading
sys.path.insert(0, sys.argv[1])
from lnpl import mcp_http
token, runaway = sys.argv[2], sys.argv[3]
server = mcp_http.make_server("127.0.0.1", 0, token, tool_timeout=30.0,
                              child_memory_bytes=256 << 20)
threading.Thread(target=server.serve_forever, daemon=True).start()
port = server.server_address[1]

def post(message, sid=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    if sid:
        headers["Mcp-Session-Id"] = sid
    conn.request("POST", "/mcp", body=json.dumps(message), headers=headers)
    resp = conn.getresponse()
    out = (resp.headers.get("Mcp-Session-Id"), json.loads(resp.read()))
    conn.close()
    return out

sid, _ = post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
_, response = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "lnpl_run", "arguments": {"text": runaway}}}, sid)
server.shutdown()
server.server_close()
r = response["result"]
unit = 1 if sys.platform == "darwin" else 1024
print(json.dumps({"text": r["content"][0]["text"], "is_error": r["isError"],
                  "maxrss_bytes": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * unit}))
"""


class MemoryLimitTest(unittest.TestCase):

    def test_a_runaway_call_is_stopped_near_the_memory_cap(self):
        proc = subprocess.run([sys.executable, "-I", "-c", MEMORY_SCENARIO, IMPL, TOKEN, RUNAWAY],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertIs(out["is_error"], True)
        self.assertIn("memory limit", out["text"])
        self.assertIn("256 MiB", out["text"])
        self.assertLessEqual(out["maxrss_bytes"], (256 << 20) + (64 << 20))


class ResultLimitTest(HttpServerCase):

    def test_the_default_cap_stops_a_huge_result(self):
        self.start_server()
        sid = self.initialize()
        status, _, body = self.post(run_call(repeat_read(20000)), sid=sid, timeout=30)
        self.assertEqual(status, 200)
        self.assertIs(result_of(body)["isError"], True)
        self.assertIn("the HTTP transport limit is 4194304 bytes", tool_text(body))
        self.assertEqual(json.loads(body)["id"], 3)

    def test_a_small_cap_boundary(self):
        self.start_server(max_result_bytes=4096)
        sid = self.initialize()
        status, _, body = self.post(run_call(CLEAN), sid=sid, timeout=30)
        self.assertIs(result_of(body)["isError"], False, body)
        status, _, body = self.post(run_call(repeat_read(10)), sid=sid, timeout=30)
        self.assertIs(result_of(body)["isError"], True)
        self.assertIn("limit is 4096 bytes", tool_text(body))


class BusyTest(HttpServerCase):

    def test_calls_beyond_the_concurrency_cap_are_refused(self):
        self.start_server(max_tool_calls=1, tool_timeout=3.0, child_memory_bytes=4 << 30)
        sid = self.initialize()
        thread = threading.Thread(
            target=lambda: self.post(run_call(RUNAWAY), sid=sid, timeout=30), daemon=True)
        thread.start()
        time.sleep(0.3)
        started = time.monotonic()
        status, _, body = self.post(run_call(CLEAN, mid=11), sid=sid, timeout=30)
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(status, 200)
        self.assertIs(result_of(body)["isError"], True)
        self.assertIn("server busy", tool_text(body))
        thread.join(10)
        self.assertFalse(thread.is_alive())
        # the slot is released once the runaway is stopped
        status, _, body = self.post(run_call(CLEAN, mid=12), sid=sid, timeout=30)
        self.assertIs(result_of(body)["isError"], False, body)


class NotificationToolCallTest(HttpServerCase):

    def test_a_tool_call_notification_spawns_nothing(self):
        self.start_server()
        sid = self.initialize()
        with mock.patch("lnpl.mcp_http.subprocess.Popen") as popen:
            status, _, body = self.post({"jsonrpc": "2.0", "id": None, "method": "tools/call",
                                         "params": {"name": "lnpl_vocabulary"}}, sid=sid)
        self.assertEqual((status, body), (202, b""))
        popen.assert_not_called()


class ChildFailureTest(HttpServerCase):

    def test_a_child_that_cannot_start_is_a_generic_32603(self):
        self.start_server()
        sid = self.initialize()
        with mock.patch("lnpl.mcp_http.subprocess.Popen", side_effect=OSError("no fork")), \
                mock.patch("sys.stderr", new_callable=io.StringIO):
            status, _, body = self.post(run_call(CLEAN), sid=sid)
        self.assertEqual(status, 200)
        self.assertEqual(self.error_of(body)["code"], mcp_server.INTERNAL_ERROR)
        self.assertNotIn(b"no fork", body)


class ChildEnvTest(HttpServerCase):

    def test_the_tool_child_never_receives_the_token(self):
        self.start_server()
        sid = self.initialize()
        marker = {"LNPL_MCP_TOKEN": TOKEN, "LNPL_T7_ENV_MARKER": "kept"}
        with mock.patch.dict(os.environ, marker), \
                mock.patch("lnpl.mcp_http.subprocess.Popen", wraps=subprocess.Popen) as popen:
            status, _, body = self.post(run_call(CLEAN), sid=sid, timeout=30)
        self.assertEqual(status, 200)
        self.assertIs(result_of(body)["isError"], False, body)
        popen.assert_called_once()
        env = popen.call_args.kwargs.get("env")
        self.assertIsInstance(env, dict, "the child must get an explicit environment, "
                                         "not an inherited one")
        # assertFalse with a fixed message: assertNotIn would print the whole
        # environment of the test host into the failure output.
        self.assertFalse("LNPL_MCP_TOKEN" in env, "the bearer token reached the tool child")
        self.assertFalse(TOKEN in env.values(), "the token value reached the tool child")
        self.assertEqual(env.get("LNPL_T7_ENV_MARKER"), "kept")


class ChildHelpersTest(unittest.TestCase):

    def test_the_child_environment_drops_the_token(self):
        self.assertEqual(mcp_http._child_env({"LNPL_MCP_TOKEN": "t", "HOME": "/h"}), {"HOME": "/h"})
        self.assertEqual(mcp_http._child_env({}), {})

    def test_child_output_parsing(self):
        bad = mcp_http._parse_child_output(b"not json", 0, 5)
        self.assertEqual((bad["error"]["code"], bad["id"]), (mcp_server.INTERNAL_ERROR, 5))
        self.assertEqual(mcp_http._parse_child_output(b"{}", 1)["error"]["code"],
                         mcp_server.INTERNAL_ERROR)
        self.assertEqual(mcp_http._parse_child_output(b"[]", 0)["error"]["code"],
                         mcp_server.INTERNAL_ERROR)
        self.assertEqual(mcp_http._parse_child_output(b"", 0)["error"]["code"],
                         mcp_server.INTERNAL_ERROR)
        good = {"jsonrpc": "2.0", "id": 5, "result": {}}
        self.assertEqual(mcp_http._parse_child_output(json.dumps(good).encode(), 0, 5), good)

    def test_guarded_handle_keeps_stdout_clean(self):
        def noisy(_message, allow_paths):
            print("noise")
            return {"ok": allow_paths}
        with mock.patch("lnpl.mcp_server.handle", side_effect=noisy), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            result = mcp_http._guarded_handle({"jsonrpc": "2.0", "id": 1, "method": "x"})
            self.assertIs(sys.stdout, out)
        self.assertEqual(result, {"ok": False})
        self.assertEqual(out.getvalue(), "")
        self.assertIn("noise", err.getvalue())

    def test_guarded_handle_turns_a_crash_into_32603(self):
        with mock.patch("lnpl.mcp_server.handle", side_effect=RuntimeError("boom")), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            result = mcp_http._guarded_handle({"jsonrpc": "2.0", "id": 6, "method": "x"})
        self.assertEqual((result["id"], result["error"]["code"]), (6, mcp_server.INTERNAL_ERROR))
        self.assertIn("boom", err.getvalue())

    def test_without_the_resource_module_tool_calls_fail_closed(self):
        env = {"message": {"jsonrpc": "2.0", "id": 4, "method": "tools/list"}}
        with mock.patch.dict(sys.modules, {"resource": None}), \
                mock.patch("lnpl.mcp_server.handle", side_effect=AssertionError("ran")):
            data = mcp_http._child_response(env)
        result = json.loads(data)["result"]
        self.assertIs(result["isError"], True)
        self.assertIn("resource module is unavailable", result["content"][0]["text"])


# --- Task 07: entry point and the Inspector stand-in ------------------------


class MainRefusalTest(unittest.TestCase):

    def refused(self, environ, argv=("--port", "0")):
        with mock.patch("lnpl.mcp_http.make_server") as ms, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            rc = mcp_http.main(list(argv), environ=environ)
        ms.assert_not_called()
        return rc, err.getvalue()

    def test_no_token_no_start(self):
        for environ in ({}, {"LNPL_MCP_TOKEN": ""}):
            with self.subTest(environ=environ):
                rc, err = self.refused(environ)
                self.assertEqual(rc, 2)
                self.assertIn("LNPL_MCP_TOKEN is not set", err)

    def test_a_short_token_is_refused_without_echoing_it(self):
        rc, err = self.refused({"LNPL_MCP_TOKEN": "y" * 31})
        self.assertEqual(rc, 2)
        self.assertIn("at least 32 bytes", err)
        self.assertNotIn("y" * 31, err)

    def test_a_token_with_whitespace_is_refused(self):
        rc, err = self.refused({"LNPL_MCP_TOKEN": "y" * 31 + "\n"})
        self.assertEqual(rc, 2)
        self.assertIn("visible ASCII", err)

    def test_there_is_no_allow_origin_flag(self):
        with mock.patch("sys.stderr", new_callable=io.StringIO), \
                mock.patch("lnpl.mcp_http.make_server") as ms:
            with self.assertRaises(SystemExit) as ctx:
                mcp_http.main(["--allow-origin", "x"], environ={"LNPL_MCP_TOKEN": TOKEN})
        self.assertEqual(ctx.exception.code, 2)
        ms.assert_not_called()


class MainStartTest(unittest.TestCase):

    def started(self, argv, address):
        ms = mock.MagicMock()
        ms.return_value.server_address = address
        with mock.patch("lnpl.mcp_http.make_server", ms), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            rc = mcp_http.main(argv, environ={"LNPL_MCP_TOKEN": TOKEN})
        return rc, ms, err.getvalue()

    def test_the_default_start_binds_loopback_and_announces(self):
        rc, ms, err = self.started(["--port", "0"], ("127.0.0.1", 4321))
        self.assertEqual(rc, 0)
        ms.assert_called_once_with("127.0.0.1", 0, TOKEN)
        ms.return_value.serve_forever.assert_called_once_with()
        ms.return_value.server_close.assert_called_once_with()
        self.assertEqual(err.splitlines()[0], "lnpl-mcp: http listening on 127.0.0.1:4321")
        self.assertNotIn("warning", err)

    def test_the_default_port_is_8765(self):
        rc, ms, _ = self.started([], ("127.0.0.1", 8765))
        self.assertEqual(rc, 0)
        ms.assert_called_once_with("127.0.0.1", 8765, TOKEN)

    def test_a_non_loopback_host_warns(self):
        rc, _, err = self.started(["--host", "0.0.0.0", "--port", "0"], ("0.0.0.0", 4321))
        self.assertEqual(rc, 0)
        self.assertIn("lnpl-mcp: warning: 0.0.0.0 is not loopback", err)

    def test_ctrl_c_closes_the_server_and_returns_0(self):
        ms = mock.MagicMock()
        ms.return_value.server_address = ("127.0.0.1", 1)
        ms.return_value.serve_forever.side_effect = KeyboardInterrupt
        with mock.patch("lnpl.mcp_http.make_server", ms), \
                mock.patch("sys.stderr", new_callable=io.StringIO):
            rc = mcp_http.main([], environ={"LNPL_MCP_TOKEN": TOKEN})
        self.assertEqual(rc, 0)
        ms.return_value.server_close.assert_called_once_with()

    def test_a_bind_failure_is_rc_2(self):
        with mock.patch("lnpl.mcp_http.make_server",
                        side_effect=OSError(48, "Address already in use")), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            rc = mcp_http.main(["--port", "0"], environ={"LNPL_MCP_TOKEN": TOKEN})
        self.assertEqual(rc, 2)
        self.assertIn("lnpl-mcp: cannot listen on 127.0.0.1:0: Address already in use",
                      err.getvalue())


class InspectorFlowTest(HttpServerCase):

    def test_inspector_flow_initialize_list_and_run_over_http(self):
        self.start_server()
        sid = self.initialize()
        self.assertEqual(self.post(INITIALIZED, sid=sid)[0], 202)
        status, _, body = self.post(TOOLS_LIST, sid=sid)
        self.assertEqual(status, 200)
        names = [t["name"] for t in result_of(body)["tools"]]
        self.assertEqual(len(names), 8)
        self.assertEqual(names, [t["name"] for t in mcp_server.TOOLS])
        stdio = converse({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})[0]
        self.assertEqual(names, [t["name"] for t in stdio["result"]["tools"]])
        status, _, body = self.post(run_call(CLEAN), sid=sid, timeout=30)
        self.assertEqual(status, 200)
        self.assertIs(result_of(body)["isError"], False, body)
        payload = json.loads(tool_text(body))
        self.assertIn("diagnostics", payload)
        self.assertIsInstance(payload["diagnostics"], list)


class EntryPointProcessTest(HttpServerCase):

    def test_python_m_lnpl_mcp_http_serves(self):
        env = dict(os.environ, LNPL_MCP_TOKEN=TOKEN, PYTHONPATH=IMPL)
        proc = subprocess.Popen([sys.executable, "-m", "lnpl.mcp_http", "--port", "0"],
                                cwd=IMPL, env=env, stderr=subprocess.PIPE, text=True)

        def stop():
            proc.terminate()
            proc.wait(5)
            proc.stderr.close()
        self.addCleanup(stop)
        first = {}
        reader = threading.Thread(target=lambda: first.update(line=proc.stderr.readline()),
                                  daemon=True)
        reader.start()
        reader.join(10)
        match = re.match(r"^lnpl-mcp: http listening on 127\.0\.0\.1:([0-9]+)$",
                         first.get("line", "").rstrip("\n"))
        self.assertIsNotNone(match, first)
        self.port = int(match.group(1))
        self.assertRegex(self.initialize(), r"^[0-9a-f]{32}$")

    def test_python_m_lnpl_mcp_http_refuses_without_a_token(self):
        env = {k: v for k, v in os.environ.items() if k != "LNPL_MCP_TOKEN"}
        env["PYTHONPATH"] = IMPL
        proc = subprocess.run([sys.executable, "-m", "lnpl.mcp_http", "--port", "0"],
                              cwd=IMPL, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("LNPL_MCP_TOKEN", proc.stderr)
        self.assertNotIn("listening", proc.stderr)


class StdioEntryUnchangedTest(unittest.TestCase):

    def test_python_m_lnpl_mcp_server_is_still_stdio(self):
        proc = subprocess.run([sys.executable, "-m", "lnpl.mcp_server"], cwd=IMPL,
                              env=dict(os.environ, PYTHONPATH=IMPL), input=INITIALIZE,
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1, proc.stdout)
        self.assertEqual(json.loads(lines[0])["result"]["serverInfo"]["name"], "lnpl")


if __name__ == "__main__":
    unittest.main()

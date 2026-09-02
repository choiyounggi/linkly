"""MCP stdio 서버의 계약 테스트.

`handle()`을 직접 부르지 않고 **`serve()` 루프를 통째로** 돌린다. 이 서버의
계약은 함수 반환값이 아니라 stdin/stdout 위의 줄들이기 때문이다 — 알림에
응답하지 않는 것, 깨진 줄에도 죽지 않는 것, 한 줄에 한 메시지를 쓰는 것은
루프를 돌려야만 관측된다.

두 종류의 실패를 구분하는 것이 이 파일의 핵심이다:

  * **프로토콜 오류**(`error`) — 클라이언트가 이 서버가 모르는 것을 요구했다.
  * **도구 오류**(`isError: true`) — 요구는 정당했고 실행이 실패했다. 모델이
    읽고 고칠 수 있어야 하므로 결과로 되돌린다.

둘을 뒤섞으면 모델은 자기가 고칠 수 있는 실패와 고칠 수 없는 실패를 구별하지
못한다.
"""
import io
import json
import os
import subprocess
import unittest
from importlib import metadata as importlib_metadata
from unittest import mock

from lnpl import __version__
from lnpl import diagnostics as diagnostics_module
from lnpl.diagnostics import ExtensionDiagnosticsError
from lnpl.mcp_server import (INVALID_PARAMS, INVALID_REQUEST, METHOD_NOT_FOUND,
                             PARSE_ERROR, PROTOCOL_VERSION, TOOLS, serve)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLUGIN = os.path.join(REPO, "plugins", "lnpl-mcp")

EXT_GROUP = diagnostics_module.DIAGNOSTICS_ENTRY_POINT_GROUP


def _entry_point(name, value):
    return importlib_metadata.EntryPoint(name=name, value=value, group=EXT_GROUP)


KAFKA_EP = _entry_point("kafka", "tests.diagnostics_ext_fixture:register_kafka")


def registered(*entry_points):
    """Patch `diagnostics_module.importlib_metadata.entry_points` — same
    fixture-injection pattern `test_extension_diagnostics.py` uses — so
    `lnpl_compile`'s extension pass sees exactly `entry_points`, regardless
    of what is actually installed."""
    return mock.patch.object(
        diagnostics_module.importlib_metadata, "entry_points",
        lambda **_kwargs: list(entry_points))

NOISY = ("entity Note\n    field\n        id UUID\n\n"
         "workflow Save\n    validate note\n    return note\n")
CLEAN = ("entity Note\n    field\n        id UUID\n\n"
         "workflow Save\n    validate note\n    create note\n")
# RFC-0026: `persist` is a `VERB_ALIASES` entry (tier 1, a semantic near-synonym
# of `create`) — unlike NOISY's `return`, which is unrelated to every
# VERB_LEXICON verb and gets no suggestion at all.
ALIASED = ("entity Note\n    field\n        id UUID\n\n"
          "workflow Save\n    validate note\n    persist note\n")
# `steps 99`는 실제 스텝 수(2)와 어긋나도록 고정한 것 — 실패 케이스가
# 기대/실측을 병기하는지 결정적으로 확인하기 위함.
BAD_SPEC = ("entity Note\n    field\n        id UUID\n        title Text\n\n"
           "workflow SaveNote\n    validate input\n    create note\n"
           "    spec\n        given\n            empty repository\n"
           "        when\n            saveNote\n        expect\n"
           "            completed\n            steps 99\n")


def converse(*messages):
    """메시지들을 줄로 넣고 나온 줄들을 파싱해 돌려준다."""
    lines = "".join(json.dumps(m) + "\n" for m in messages)
    out = io.StringIO()
    serve(stdin=io.StringIO(lines), stdout=out)
    return [json.loads(line) for line in out.getvalue().splitlines() if line]


def call(tool, arguments, mid=9):
    return converse({"jsonrpc": "2.0", "id": mid, "method": "tools/call",
                     "params": {"name": tool, "arguments": arguments}})[0]


def payload_of(response):
    """`content[0].text`의 JSON. 도구가 성공했을 때만 의미가 있다."""
    return json.loads(response["result"]["content"][0]["text"])


class HandshakeTest(unittest.TestCase):

    def test_initialize_reports_the_real_compiler_version(self):
        res = converse({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2025-06-18"}})[0]
        self.assertEqual(res["result"]["serverInfo"],
                         {"name": "lnpl", "version": __version__})
        self.assertEqual(res["result"]["capabilities"], {"tools": {}})

    def test_it_echoes_the_protocol_version_the_client_asked_for(self):
        res = converse({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2024-11-05"}})[0]
        self.assertEqual(res["result"]["protocolVersion"], "2024-11-05")

    def test_it_falls_back_to_its_own_version_when_none_is_asked_for(self):
        res = converse({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {}})[0]
        self.assertEqual(res["result"]["protocolVersion"], PROTOCOL_VERSION)

    def test_a_notification_gets_no_reply(self):
        # 알림에 응답하면 클라이언트의 id 대응이 어긋난다.
        out = converse({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(out, [])

    def test_any_id_less_message_gets_no_reply_not_just_the_known_one(self):
        """알림 규칙은 메서드 이름이 아니라 `id` 부재로 정해진다.

        `notifications/initialized` 하나만 테스트하면, 그 이름을 특별 취급하는
        분기가 규칙 전체를 대신하고 있어도 초록이다. JSON-RPC에서 id 없는
        메시지에 응답하면 클라이언트의 id 대응이 어긋난다 — 이름과 무관하게.
        """
        out = converse({"jsonrpc": "2.0", "method": "notifications/progress",
                        "params": {"token": 1}},
                       {"jsonrpc": "2.0", "method": "some/unknown/notice"})
        self.assertEqual(out, [])

    def test_one_line_per_response_in_order(self):
        out = converse(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual([r["id"] for r in out], [1, 2])


class ToolsListTest(unittest.TestCase):

    def test_every_tool_is_listed_with_a_schema(self):
        res = converse({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})[0]
        listed = res["result"]["tools"]
        self.assertEqual([t["name"] for t in listed],
                         [t["name"] for t in TOOLS])
        for tool in listed:
            with self.subTest(tool=tool["name"]):
                self.assertEqual(tool["inputSchema"]["type"], "object")
                self.assertTrue(tool["description"].strip())


class CompileToolTest(unittest.TestCase):

    def test_it_returns_diagnostics_as_records_not_prose(self):
        res = call("lnpl_compile", {"text": NOISY})
        self.assertIs(res["result"]["isError"], False)
        body = payload_of(res)
        self.assertEqual(body["unknown_verbs"], 1)
        self.assertEqual(body["counts"]["unknown-verb"], 1)
        record = body["diagnostics"][0]
        # 코드와 등급으로 분기할 수 있어야 한다 — message를 정규식으로 긁는 것이
        # 아니라.
        self.assertEqual(record["code"], "unknown-verb")
        self.assertEqual(record["severity"], "warning")
        self.assertEqual(record["subject"], "return")

    def test_a_clean_source_reports_nothing(self):
        body = payload_of(call("lnpl_compile", {"text": CLEAN}))
        self.assertEqual(body["diagnostics"], [])
        self.assertEqual(body["unknown_verbs"], 0)
        self.assertGreater(body["nodes"], 0)

    def test_an_enforcement_diagnostic_carries_its_declaration_line(self):
        # RFC-0024 (issue #67): the record's `line` is what an agent jumps to
        # without grepping the source for the subject's text a second time.
        path = os.path.join(REPO, "examples", "shorten.lnpl")
        body = payload_of(call("lnpl_compile", {"path": path}))
        by_code = {r["code"]: r for r in body["diagnostics"]}
        self.assertEqual(by_code["declared-not-enforced"]["line"], 46)
        self.assertEqual(by_code["declared-measured-only"]["line"], 48)

    def test_an_unknown_verb_record_carries_its_line_as_an_int(self):
        # RFC-0026 widens RFC-0024's `line` coverage to `unknown-verb`: an
        # agent jumps to the source without regexing `where` a second time.
        record = payload_of(call("lnpl_compile", {"text": NOISY}))["diagnostics"][0]
        self.assertIsInstance(record["line"], int)
        self.assertEqual(record["line"], 7)

    def test_an_unrelated_verb_gets_no_suggestion(self):
        # `return` is not close to any VERB_LEXICON verb by alias or by
        # spelling — the key exists but stays null, and the message carries no
        # suffix (RFC-0026: a wrong suggestion is worse than none).
        record = payload_of(call("lnpl_compile", {"text": NOISY}))["diagnostics"][0]
        self.assertIn("suggestion", record)
        self.assertIsNone(record["suggestion"])
        self.assertNotIn("did you mean", record["message"])

    def test_a_semantic_alias_suggests_its_lexicon_verb_both_places(self):
        # RFC-0026 D2: `persist` is a VERB_ALIASES entry for `create` — the
        # suggestion must show up in both the structured field and the
        # message suffix, not just one.
        record = payload_of(call("lnpl_compile", {"text": ALIASED}))["diagnostics"][0]
        self.assertEqual(record["suggestion"], "create")
        self.assertIn("did you mean 'create'?", record["message"])

    def test_it_compiles_a_committed_example_by_path(self):
        path = os.path.join(REPO, "examples", "checkout.lnpl")
        body = payload_of(call("lnpl_compile", {"path": path}))
        self.assertEqual(body["source"], path)
        self.assertEqual(body["unknown_verbs"], 0)

    def test_giving_both_text_and_path_is_a_tool_error(self):
        res = call("lnpl_compile", {"text": CLEAN, "path": "x.lnpl"})
        self.assertIs(res["result"]["isError"], True)
        self.assertIn("정확히 하나", res["result"]["content"][0]["text"])

    def test_giving_neither_text_nor_path_is_a_tool_error(self):
        res = call("lnpl_compile", {})
        self.assertIs(res["result"]["isError"], True)

    def test_a_missing_file_is_a_tool_error_not_a_crash(self):
        res = call("lnpl_compile",
                   {"path": os.path.join(REPO, "no-such-file.lnpl")})
        self.assertIs(res["result"]["isError"], True)
        self.assertIn("파일이 없다", res["result"]["content"][0]["text"])

    def test_source_that_cannot_compile_is_a_tool_error(self):
        # `if`는 예약어다. 컴파일 거부는 도구의 실패이지 프로토콜의 실패가 아니다.
        res = call("lnpl_compile",
                   {"text": "entity N\n    field\n        id UUID\n\n"
                            "workflow S\n    if x\n"})
        self.assertIs(res["result"]["isError"], True)
        self.assertNotIn("error", res)

    def test_a_registered_extension_diagnostic_is_appended_after_core_ones(self):
        # Normal (RFC-0042, issue #140): a registered `lnpl.diagnostics`
        # extension's finding rides along in `lnpl_compile`'s own
        # `diagnostics` array, `<prefix>/<code>` normalized, core records
        # first — same merge order as `lnpl compile --json`.
        with registered(KAFKA_EP):
            res = call("lnpl_compile", {"text": CLEAN})
        self.assertIs(res["result"]["isError"], False)
        body = payload_of(res)
        self.assertEqual(len(body["diagnostics"]), 1)
        record = body["diagnostics"][0]
        self.assertEqual(record["code"], "kafka/at-least-once")
        self.assertEqual(record["severity"], "info")
        self.assertEqual(set(record.keys()),
                         {"code", "severity", "where", "subject", "message",
                          "line", "hint"})

    def test_an_rfc_0043_enforcement_diagnostic_rides_the_same_shared_pass(self):
        # RFC-0043 (issue #138/#140 follow-up, t-wire's shared layer): the
        # driver-enforcement bridge lives in
        # `diagnostics.extension_diagnostic_records` — the exact function
        # `lnpl_compile` already calls for the RFC-0042 case above — so it
        # needs no `mcp_server.py` changes to reach this tool.
        source = ("capability postgres\n"
                  "entity Payment\n    field\n        id UUID\n\n"
                  "event userCreated on Payment create\n"
                  "service Checkout\n    database\n        postgres\n"
                  "workflow Approve\n    create payment\n    emit userCreated\n")
        driver_ep = importlib_metadata.EntryPoint(
            name="kafka",
            value="tests.enforcement_spi_fixture:DeliveryReportingDriver",
            group="lnpl.drivers")

        def fake_entry_points(**kwargs):
            group = kwargs.get("group")
            return [driver_ep] if group == "lnpl.drivers" else []

        with mock.patch.object(importlib_metadata, "entry_points", fake_entry_points):
            res = call("lnpl_compile", {"text": source})

        self.assertIs(res["result"]["isError"], False)
        body = payload_of(res)
        by_code = {r["code"]: r for r in body["diagnostics"]}
        self.assertIn("kafka/delivery-at-least-once", by_code)
        record = by_code["kafka/delivery-at-least-once"]
        self.assertEqual(record["severity"], "info")
        self.assertIn("more than once", record["message"])

    def test_an_invalid_extension_registration_is_a_tool_error_not_a_crash(self):
        # Error: a load-time RFC-0042 violation raises
        # `ExtensionDiagnosticsError` from the shared helper — `tools/call`'s
        # existing generic except (the same one ParseError/LowerError hit)
        # turns it into `isError`, never a server crash.
        with mock.patch("lnpl.diagnostics.load_extensions",
                        side_effect=ExtensionDiagnosticsError("boom")):
            res = call("lnpl_compile", {"text": CLEAN})
        self.assertIs(res["result"]["isError"], True)
        self.assertIn("boom", res["result"]["content"][0]["text"])

    def test_no_registered_extensions_leaves_diagnostics_unchanged(self):
        # Boundary: zero extensions installed — the extension pass appends
        # nothing, so `lnpl_compile`'s response is exactly what it was
        # before this pass existed.
        with registered():
            body = payload_of(call("lnpl_compile", {"text": CLEAN}))
        self.assertEqual(body["diagnostics"], [])


class VocabularyToolTest(unittest.TestCase):

    def test_it_returns_the_same_document_the_cli_prints(self):
        from lnpl.vocab import vocabulary_document
        body = payload_of(call("lnpl_vocabulary", {}))
        self.assertEqual(body, vocabulary_document())

    def test_it_needs_no_arguments(self):
        res = call("lnpl_vocabulary", {})
        self.assertIs(res["result"]["isError"], False)

    def test_diagnostics_carries_all_18_codes(self):
        from lnpl.diagnostics import CODES
        body = payload_of(call("lnpl_vocabulary", {}))
        self.assertEqual(len(body["diagnostics"]), len(CODES))


class CapabilitiesToolTest(unittest.TestCase):

    def test_it_returns_the_same_document_the_cli_prints(self):
        from lnpl.capabilities import capabilities_document
        body = payload_of(call("lnpl_capabilities", {}))
        self.assertEqual(body, capabilities_document())

    def test_it_needs_no_arguments(self):
        res = call("lnpl_capabilities", {})
        self.assertIs(res["result"]["isError"], False)

    def test_it_reports_the_eight_contract_slots(self):
        body = payload_of(call("lnpl_capabilities", {}))
        self.assertEqual(set(body["slots"]),
                         {"repository", "cache", "network", "token",
                          "exporter", "kb", "generators", "diagnostics"})


class KbRouteToolTest(unittest.TestCase):

    def test_it_routes_a_task_to_kb_documents(self):
        body = payload_of(call("lnpl_kb_route",
                               {"task": "choose a postgres index"}))
        self.assertIn("database-postgres-index-selection", body["route"])

    def test_a_missing_task_is_a_tool_error(self):
        res = call("lnpl_kb_route", {})
        self.assertIs(res["result"]["isError"], True)


class SpecToolTest(unittest.TestCase):

    def test_it_reports_every_case_pass_for_a_committed_example(self):
        path = os.path.join(REPO, "examples", "linkhub.lnpl")
        body = payload_of(call("lnpl_spec", {"path": path}))
        self.assertTrue(body["spec_present"])
        self.assertEqual([c["status"] for c in body["cases"]],
                         ["pass", "pass", "pass", "pass"])
        self.assertEqual(body["summary"]["failed"], 0)
        self.assertGreater(body["summary"]["passed"], 0)

    def test_a_failing_case_reports_expected_and_actual(self):
        body = payload_of(call("lnpl_spec", {"text": BAD_SPEC}))
        self.assertTrue(body["spec_present"])
        case = body["cases"][0]
        self.assertEqual(case["status"], "fail")
        self.assertEqual(body["summary"]["failed"], 1)
        fail_line = next(l for l in case["lines"] if l.startswith("FAIL"))
        # 실측(got)과 기대(want)가 한 줄에 같이 있어야 한다 — 둘 중 하나만
        # 보고 고칠 수는 없다.
        self.assertIn("steps=2", fail_line)
        self.assertIn("want=99", fail_line)

    def test_source_without_a_spec_block_is_not_an_error(self):
        # 없음은 에러가 아니라 데이터다 — MCP 소비자는 rc=1 대신 이 필드로
        # "spec이 없다"를 받는다.
        body = payload_of(call("lnpl_spec", {"text": CLEAN}))
        self.assertIs(body["spec_present"], False)
        self.assertEqual(body["cases"], [])
        self.assertEqual(body["summary"], {"passed": 0, "failed": 0})


class ProtocolErrorTest(unittest.TestCase):
    """도구 오류와 달리, 이쪽은 `error`로 나가야 한다."""

    def test_an_unknown_tool_is_a_protocol_error_and_lists_what_exists(self):
        res = call("no_such_tool", {})
        self.assertEqual(res["error"]["code"], INVALID_PARAMS)
        self.assertIn("lnpl_compile", res["error"]["message"])

    def test_an_unknown_method_is_a_protocol_error(self):
        res = converse({"jsonrpc": "2.0", "id": 6,
                        "method": "resources/list"})[0]
        self.assertEqual(res["error"]["code"], METHOD_NOT_FOUND)

    def test_a_wrong_jsonrpc_version_is_refused(self):
        res = converse({"jsonrpc": "1.0", "id": 7, "method": "tools/list"})[0]
        self.assertEqual(res["error"]["code"], INVALID_REQUEST)

    def test_a_malformed_line_does_not_kill_the_loop(self):
        out = io.StringIO()
        serve(stdin=io.StringIO(
            "{not json\n"
            "\n"                       # 빈 줄은 건너뛴다
            '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'),
            stdout=out)
        responses = [json.loads(l) for l in out.getvalue().splitlines() if l]
        self.assertEqual(responses[0]["error"]["code"], PARSE_ERROR)
        self.assertIn("tools", responses[1]["result"],
                      "깨진 줄 하나가 이후 요청을 삼켰다")


LAUNCHER = os.path.join(PLUGIN, "server.py")
INITIALIZE = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {}}) + "\n"


def run_launcher(env, cwd):
    """런처를 실제 프로세스로 띄우고 initialize 한 줄을 넣는다.

    `serve()`를 직접 부르면 런처가 하는 유일한 일 — 패키지를 **찾는 것** —
    을 건너뛴다. 그 해석이 이 파일의 전부이므로 프로세스로 돌려야 한다.
    설치된 lnpl을 우연히 집지 않도록 PATH와 PYTHONPATH를 비운 환경에서 돈다.
    """
    base = {"PATH": "/usr/bin:/bin"}
    base.update(env)
    return subprocess.run(["python3", LAUNCHER], input=INITIALIZE,
                          capture_output=True, text=True, env=base, cwd=cwd)


class LauncherResolutionTest(unittest.TestCase):
    """런처의 세 해석 분기와 fail-loud 경로.

    감사가 지적한 공백이다: `.mcp.json`이 이 파일을 가리킨다는 것만 확인하고
    **이 파일이 실제로 무엇을 하는지**는 아무 테스트도 보지 않았다. 여기가
    깨지면 서버는 뜨지 않고, 클라이언트는 "연결 실패"만 본다.
    """

    def _initialized(self, proc):
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(proc.stdout.strip(), "런처가 아무것도 내지 않았다")
        return json.loads(proc.stdout.splitlines()[0])["result"]

    def test_it_uses_lnpl_impl_when_given(self):
        proc = run_launcher({"LNPL_IMPL": os.path.join(REPO, "impl")}, cwd="/")
        result = self._initialized(proc)
        self.assertEqual(result["serverInfo"]["name"], "lnpl")
        self.assertEqual(result["serverInfo"]["version"], __version__)

    def test_it_walks_up_from_the_working_directory(self):
        # LNPL_IMPL 없이, 레포 안의 하위 디렉터리에서 띄운다.
        proc = run_launcher({}, cwd=os.path.join(REPO, "examples"))
        result = self._initialized(proc)
        self.assertEqual(result["serverInfo"]["version"], __version__)

    def test_walk_up_beats_nothing_but_lnpl_impl_beats_walk_up(self):
        # 둘 다 가능한 자리에서 LNPL_IMPL이 이겨야 한다 — 명시가 추론을 이긴다.
        proc = run_launcher({"LNPL_IMPL": os.path.join(REPO, "impl")},
                            cwd=os.path.join(REPO, "examples"))
        self._initialized(proc)

    def test_it_fails_loudly_when_the_package_cannot_be_found(self):
        # 어디서도 못 찾는 자리. 조용히 죽으면 클라이언트는 이유를 모른다.
        proc = run_launcher({}, cwd="/")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("could not locate", proc.stderr)
        self.assertIn("LNPL_IMPL", proc.stderr,
                      "무엇을 시도했는지 말하지 않으면 고칠 수가 없다")

    def test_a_bad_lnpl_impl_does_not_pretend_to_work(self):
        proc = run_launcher({"LNPL_IMPL": "/nonexistent/impl"}, cwd="/")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("could not locate", proc.stderr)


class PluginPackagingTest(unittest.TestCase):

    def test_the_mcp_config_points_at_the_shipped_launcher(self):
        with open(os.path.join(PLUGIN, ".mcp.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        server = cfg["lnpl"]
        self.assertEqual(server["command"], "python3")
        self.assertEqual(server["args"], ["${CLAUDE_PLUGIN_ROOT}/server.py"])
        # 절대 경로를 박으면 설치된 위치에서 깨진다.
        self.assertTrue(os.path.isfile(os.path.join(PLUGIN, "server.py")))

    def test_it_declares_no_environment_passthrough(self):
        """`env` 로 변수를 되넘기지 않는다.

        stdio 서버는 자식 프로세스라 부모 환경을 그대로 물려받는다. 그래서
        `"env": {"LNPL_IMPL": "${LNPL_IMPL}"}` 같은 passthrough는 사용자가
        `export` 했을 때 얻는 것이 없고, 그 변수가 보통 설정돼 있지 않다는
        점에서 실패 모드만 하나 늘린다. 런처는 `os.environ` 에서 직접 읽는다.
        """
        with open(os.path.join(PLUGIN, ".mcp.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        self.assertNotIn(
            "env", cfg["lnpl"],
            "설정돼 있지 않은 변수를 되넘기면 서버 기동만 위태로워진다")

    def test_the_plugin_manifest_names_itself(self):
        with open(os.path.join(PLUGIN, ".claude-plugin", "plugin.json"),
                  encoding="utf-8") as fh:
            manifest = json.load(fh)
        self.assertEqual(manifest["name"], "lnpl-mcp")
        self.assertEqual(manifest["version"], __version__)


if __name__ == "__main__":
    unittest.main()

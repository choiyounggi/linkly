"""LNPL을 MCP 툴로 노출하는 stdio 서버.

왜 있는가: `lnpl compile`은 진단을 **stderr로 내보내고 종료 코드 0**으로 끝난다.
셸을 통해 부르는 쪽은 그래서 세 가지를 직접 해야 한다 — 리디렉션 순서를 맞추고
(`2>&1 >/dev/null`), 사람이 읽으라고 만든 줄글을 다시 파싱하고, PATH에서 CLI를
찾는다. 셋 다 조용히 틀릴 수 있고, 틀리면 진단이 사라진다(issue #36의 훅이 정확히
그렇게 죽어 있었다).

MCP 툴은 그 셋을 없앤다. 호출자는 구조화된 `diagnostics` 배열을 그대로 받고,
서버는 이미 임포트된 컴파일러를 직접 부른다 — 셸도, 스트림도, PATH도 없다.

**의존성을 추가하지 않는다.** MCP의 stdio 전송은 줄 단위로 구분된 JSON-RPC 2.0이고,
이 서버가 쓰는 메서드는 셋뿐이라 표준 라이브러리로 충분하다. 이 레포의 런타임
의존성은 `jsonschema` 하나이며 이 파일이 그것을 늘리지 않는다.

프로토콜 표면(의도적으로 최소):

    initialize                -> serverInfo + capabilities.tools
    notifications/initialized -> 응답 없음 (알림)
    tools/list                -> 툴 목록과 inputSchema
    tools/call                -> content[] (+ 실패 시 isError)

그 밖의 메서드는 JSON-RPC 오류 -32601로 답한다. 조용히 무시하지 않는다 —
클라이언트가 무엇을 기대했는지 모르는 채로 멈추는 것이 가장 나쁜 실패다.
"""

import json
import os
import sys
import traceback

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "lnpl"

# JSON-RPC 2.0 표준 오류 코드.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def _lnpl():
    """컴파일러 모듈들. 임포트는 호출 시점으로 미룬다.

    서버가 뜨는 것과 컴파일러를 찾는 것은 다른 실패다. 임포트를 모듈 최상단에
    두면 `lnpl`이 sys.path에 없을 때 서버가 **핸드셰이크 전에** 죽고, 클라이언트는
    "서버가 시작되지 않았다"만 본다. 여기서 잡으면 그 사실이 툴 호출의 오류
    메시지로 전달된다.
    """
    from lnpl import __version__
    from lnpl.diagnostics import to_records
    from lnpl.lower import lower
    from lnpl.parser import parse
    return __version__, parse, lower, to_records


def _read_source(arguments):
    """`text`(그대로) 또는 `path`(읽어서). 정확히 하나여야 한다."""
    text = arguments.get("text")
    path = arguments.get("path")
    if (text is None) == (path is None):
        raise ValueError("`text` 또는 `path` 중 정확히 하나를 주어야 한다 "
                         "(둘 다 주거나 둘 다 빠뜨렸다)")
    if text is not None:
        return text, "<text>"
    if not os.path.isfile(path):
        raise ValueError("파일이 없다: %s" % path)
    with open(path, encoding="utf-8") as fh:
        return fh.read(), path


def tool_compile(arguments):
    """진단을 구조로 돌려준다 — 줄글이 아니라.

    `unknown-verb`가 하나라도 있으면 그 스텝은 **아무 효과도 내지 않는다.**
    종료 코드는 그 사실을 담지 않으므로, 여기서는 개수를 요약에 함께 싣는다.
    """
    _version, parse, lower, to_records = _lnpl()
    source, origin = _read_source(arguments)
    module = lower(parse(source), arguments.get("module") or "mcp")
    records = to_records(module.diagnostics)
    by_code = {}
    for rec in records:
        by_code[rec["code"]] = by_code.get(rec["code"], 0) + 1
    return {
        "source": origin,
        "nodes": len(module.to_document()["nodes"]),
        "diagnostics": records,
        "counts": by_code,
        "unknown_verbs": by_code.get("unknown-verb", 0),
    }


def tool_kb_route(arguments):
    """작업 서술 하나를 KB 문서로 라우팅한다 (RFC-0005)."""
    from lnpl import kb as kb_mod
    task = arguments.get("task")
    if not task:
        raise ValueError("`task`가 필요하다 — 라우팅할 작업 서술 한 줄")
    base = kb_mod.KnowledgeBase(root=arguments.get("root"))
    return {"task": task, "route": base.route(task)}


def tool_spec(arguments):
    """`spec` 블록을 추출해 가짜 백엔드 위에서 실행하고, 케이스별 결과를 돌려준다.

    spec.py는 수정하지 않는다 — 공개 API(`extract`, `run_manifest`)만 쓴다.
    케이스별 상태는 그 케이스 하나만 담은 매니페스트를 `run_manifest`에 따로
    넣어 얻는다: `run_manifest`는 케이스가 아니라 expectation 단위로 세므로,
    케이스 전체를 한 번에 돌리면 실패한 expectation이 어느 케이스 것인지
    구분할 수 없다.
    """
    from lnpl.spec import extract, run_manifest
    _version, parse, lower, to_records = _lnpl()
    source, origin = _read_source(arguments)
    module_name = arguments.get("module") or "mcp"
    decls = parse(source)
    module = lower(decls, module_name)
    document = module.to_document()
    diagnostics = to_records(module.diagnostics)
    manifest = extract(decls, module_name)
    if not manifest["cases"]:
        return {
            "spec_present": False,
            "cases": [],
            "summary": {"passed": 0, "failed": 0},
            "diagnostics": diagnostics,
        }
    cases = []
    total_passed = total_failed = 0
    for case in manifest["cases"]:
        case_passed, case_failed, lines = run_manifest(
            {**manifest, "cases": [case]}, document)
        total_passed += case_passed
        total_failed += case_failed
        cases.append({
            "name": case["name"],
            "status": "pass" if case_failed == 0 else "fail",
            "lines": lines,
        })
    return {
        "spec_present": True,
        "cases": cases,
        "summary": {"passed": total_passed, "failed": total_failed},
        "diagnostics": diagnostics,
    }


TOOLS = [
    {
        "name": "lnpl_compile",
        "description": (
            "Compile LNPL source to the Semantic IR and return its diagnostics "
            "as structured records. Use this instead of shelling out to `lnpl "
            "compile`: that command writes diagnostics to stderr and exits 0, so "
            "an exit-code check misses every warning. An `unknown-verb` record "
            "means that step derives no effect and does nothing at runtime."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string",
                         "description": "LNPL source as text. Use this to check "
                                        "a draft before writing it to disk."},
                "path": {"type": "string",
                         "description": "Path to a .lnpl file. Give either "
                                        "`text` or `path`, not both."},
                "module": {"type": "string",
                           "description": "Module name for the lowered IR "
                                          "(default: mcp)."},
            },
        },
    },
    {
        "name": "lnpl_kb_route",
        "description": (
            "Route one task description to the knowledge-base documents that "
            "govern it (RFC-0005). Consult this before making an architecture, "
            "naming, performance, security, or database choice in LNPL."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string",
                         "description": "One-line description of the decision "
                                        "you are about to make."},
                "root": {"type": "string",
                         "description": "Knowledge-base root (default: the "
                                        "bundled kb/)."},
            },
            "required": ["task"],
        },
    },
    {
        "name": "lnpl_spec",
        "description": (
            "Extract `spec` blocks from LNPL source and run them against the "
            "deterministic fake backend (no real I/O, no side effects — the "
            "same fake backend `lnpl spec --run` uses). Returns one status "
            "per case, with the expected-vs-actual detail for any case that "
            "fails. Source with no `spec` block is not an error: the "
            "response reports `spec_present: false` with an empty case list."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string",
                         "description": "LNPL source as text. Use this to check "
                                        "a draft before writing it to disk."},
                "path": {"type": "string",
                         "description": "Path to a .lnpl file. Give either "
                                        "`text` or `path`, not both."},
                "module": {"type": "string",
                           "description": "Module name for the lowered IR "
                                          "(default: mcp)."},
            },
        },
    },
]

HANDLERS = {
    "lnpl_compile": tool_compile,
    "lnpl_kb_route": tool_kb_route,
    "lnpl_spec": tool_spec,
}


def _text_content(payload):
    return [{"type": "text", "text": json.dumps(payload, ensure_ascii=False,
                                                indent=2, sort_keys=True)}]


def handle(message):
    """요청 하나를 처리한다. 알림이면 None을 돌려 아무것도 쓰지 않게 한다."""
    if message.get("jsonrpc") != "2.0":
        return _error(message.get("id"), INVALID_REQUEST,
                      "jsonrpc must be \"2.0\"")
    method = message.get("method")
    mid = message.get("id")

    if method == "notifications/initialized":
        return None
    if mid is None:
        return None                      # 그 밖의 알림도 응답하지 않는다

    if method == "initialize":
        try:
            version = _lnpl()[0]
        except Exception:                # 컴파일러가 없어도 핸드셰이크는 된다
            version = "unknown"
        requested = (message.get("params") or {}).get("protocolVersion")
        return _ok(mid, {
            "protocolVersion": requested or PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": version},
        })

    if method == "tools/list":
        return _ok(mid, {"tools": TOOLS})

    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        handler = HANDLERS.get(name)
        if handler is None:
            return _error(mid, INVALID_PARAMS,
                          "unknown tool %r (have: %s)"
                          % (name, ", ".join(sorted(HANDLERS))))
        try:
            payload = handler(params.get("arguments") or {})
        except Exception as exc:
            # 도구 실행의 실패는 프로토콜 오류가 아니다 — 모델이 읽고 고칠 수
            # 있도록 isError로 되돌린다(MCP 규약).
            return _ok(mid, {
                "content": [{"type": "text",
                             "text": "%s: %s" % (type(exc).__name__, exc)}],
                "isError": True,
            })
        return _ok(mid, {"content": _text_content(payload), "isError": False})

    return _error(mid, METHOD_NOT_FOUND, "unknown method %r" % method)


def _ok(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid, code, message):
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": code, "message": message}}


def serve(stdin=None, stdout=None):
    """줄 단위 JSON-RPC 루프. EOF에서 끝난다."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError as exc:
            response = _error(None, PARSE_ERROR, "invalid JSON: %s" % exc)
        else:
            try:
                response = handle(message)
            except Exception:
                response = _error(message.get("id"), INTERNAL_ERROR,
                                  traceback.format_exc(limit=3))
        if response is None:
            continue
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()


if __name__ == "__main__":
    serve()

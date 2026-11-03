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

import contextlib
import io
import json
import os
import sys
import traceback

PROTOCOL_VERSION = "2025-06-18"
# Versions this server answers with (MCP lifecycle: echo a supported request,
# otherwise answer our own). The HTTP transport rejects any other
# MCP-Protocol-Version header with 400.
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")

# Every tool argument that names a server-side file or directory. Refused when
# the caller is remote (handle(..., allow_paths=False)); the census test in
# tests/test_mcp_exec_tools.py fails when a new argument is not classified.
FILESYSTEM_ARGUMENTS = ("path", "root")
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


def _load_document(arguments):
    """`text` or `path` -> (IR document, compile diagnostics, origin) for the
    execution tools. `path` may be a file or a directory (RFC-0031), and the
    module name defaults to the CLI's rule so openapi/k8s output matches
    `lnpl openapi` / `lnpl generate` byte for byte."""
    text = arguments.get("text")
    path = arguments.get("path")
    if (text is None) == (path is None):
        raise ValueError("`text` 또는 `path` 중 정확히 하나를 주어야 한다 "
                         "(둘 다 주거나 둘 다 빠뜨렸다)")
    if not isinstance(text if text is not None else path, str):
        raise ValueError("`text` and `path` must be strings")
    _version, parse, lower, _to_records = _lnpl()
    if text is not None:
        decls = parse(text)
        name = arguments.get("module") or "mcp"
        origin = "<text>"
    else:
        if not os.path.exists(path):
            raise ValueError("파일이 없다: %s" % path)
        from lnpl.lower import load_sources
        # Private cli helper, imported on purpose (D17): openapi `info.title`
        # and the k8s object name embed the module name, so parity with the
        # CLI depends on this exact rule. The parity tests in
        # tests/test_mcp_exec_tools.py fail if cli.py changes it.
        from lnpl.cli import _module_name
        decls = load_sources([path])
        name = arguments.get("module") or _module_name([path])
        origin = path
    module = lower(decls, name)
    return module.to_document(), module.diagnostics, origin


def tool_compile(arguments):
    """진단을 구조로 돌려준다 — 줄글이 아니라.

    `unknown-verb`가 하나라도 있으면 그 스텝은 **아무 효과도 내지 않는다.**
    종료 코드는 그 사실을 담지 않으므로, 여기서는 개수를 요약에 함께 싣는다.

    `path`가 디렉터리면 RFC-0031의 단일 정본 로더(`load_sources`)로 그 안의
    `*.lnpl`을 병합한다(issue #77) — `text`/`path` 파일 하나는 오늘과
    바이트 동일(`_read_source`가 그대로 처리한다).

    확장 진단(RFC-0042, issue #140): `lnpl compile`과 같은 순서로 —
    코어 진단 뒤에 `<prefix>/<code>` 레코드를 이어붙인다. 레지스트리 로드가
    RFC-0042를 어기면 `ExtensionDiagnosticsError`가 그대로 올라가고,
    `handle()`의 `tools/call` 공통 except가 다른 컴파일 실패(ParseError/
    LowerError)와 똑같이 `isError` 응답으로 번역한다 — 여기서 따로 잡지 않는다.
    """
    _version, parse, lower, to_records = _lnpl()
    from lnpl.capabilities import capabilities_document
    from lnpl.diagnostics import extension_diagnostic_records
    path = arguments.get("path")
    if path is not None and arguments.get("text") is None and os.path.isdir(path):
        from lnpl.lower import load_sources
        decls = load_sources([path])
        origin = path
    else:
        source, origin = _read_source(arguments)
        decls = parse(source)
    module = lower(decls, arguments.get("module") or "mcp")
    document = module.to_document()
    records = to_records(module.diagnostics) + extension_diagnostic_records(document)
    by_code = {}
    for rec in records:
        by_code[rec["code"]] = by_code.get(rec["code"], 0) + 1
    # issue #205: which compiler answered — same values `lnpl_capabilities` reports.
    caps = capabilities_document()
    return {
        "source": origin,
        "nodes": len(document["nodes"]),
        "diagnostics": records,
        "counts": by_code,
        "unknown_verbs": by_code.get("unknown-verb", 0),
        "vocabulary_digest": caps["vocabulary_digest"],
        "package_path": caps["package_path"],
    }


def tool_vocabulary(_arguments):
    """벤더 중립 어휘 매니페스트를 돌려준다 — 입력 없음 (issue #135)."""
    from lnpl.vocab import vocabulary_document
    return vocabulary_document()


def tool_capabilities(_arguments):
    """설치 확장 카탈로그를 돌려준다 — 입력 없음 (issue #134)."""
    from lnpl.capabilities import capabilities_document
    return capabilities_document()


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


def tool_run(arguments):
    """Run one workflow on the fake backend + virtual clock (issue #250).
    Repository, network, cache and clock are never passed to Interpreter,
    so it builds its in-memory fakes and the virtual Clock(); the tool has
    no argument that could select a real one."""
    from lnpl.interp import Interpreter, refinement_index, sample_payload
    from lnpl.repo_policy import default_rows
    payload = arguments.get("payload")
    if payload is not None and not isinstance(payload, dict):
        raise ValueError("`payload` must be a JSON object")
    no_row = arguments.get("no_row", False)
    if not isinstance(no_row, bool):
        raise ValueError("`no_row` must be true or false")
    requested = arguments.get("workflow")
    if requested is not None and not isinstance(requested, str):
        raise ValueError("`workflow` must be a string")
    document, diagnostics, _origin = _load_document(arguments)
    to_records = _lnpl()[3]
    ids = [n["id"] for n in document["nodes"] if n["kind"] == "Workflow"]
    if not ids:
        raise ValueError("no workflow to run: the source declares no workflow")
    if not requested:
        target = ids[0]
    elif requested in ids:
        target = requested
    else:
        raise ValueError("`workflow` %r is not a workflow of this source "
                         "(valid: %s)" % (requested, ", ".join(ids)))
    if payload is None:
        entities = [n for n in document["nodes"] if n["kind"] == "Entity"]
        payload = sample_payload(entities, refinement_index(document))
    rows = {} if no_row else default_rows(document, target, payload)
    interp = Interpreter(document, repo_rows=rows)
    result = interp.run_workflow(target, payload)
    return {"result": result,
            "trace": interp.trace.to_dict(),
            "diagnostics": to_records(list(diagnostics) + list(interp.diagnostics))}


def tool_openapi(arguments):
    """The OpenAPI document as TEXT — the exact bytes `lnpl openapi` prints."""
    from lnpl.openapi import generate
    document, _diagnostics, _origin = _load_document(arguments)
    return json.dumps(generate(document), indent=2, ensure_ascii=False) + "\n"


GENERATE_NAMES = ("compose", "k8s")


def tool_generate(arguments):
    """compose/k8s files as text; nothing is written (no run_generator, no
    --out, no entry-point generators). stderr is captured so a skipped
    capability's warning reaches the caller; redirect_stderr is process-wide,
    which is safe because stdio serve() is single-threaded and every HTTP
    tools/call runs in its own child process."""
    from lnpl import deploy_gen
    name = arguments.get("generator")
    if name not in GENERATE_NAMES:
        raise ValueError("`generator` must be one of: compose, k8s (got %r)" % (name,))
    options = arguments.get("options")
    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise ValueError("`options` must be a JSON object of string values")
    for key, value in options.items():
        if not isinstance(value, str):
            raise ValueError("`options.%s` must be a string" % key)
    document, _diagnostics, _origin = _load_document(arguments)
    generator = deploy_gen.generate_compose if name == "compose" else deploy_gen.generate_k8s
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        files = generator(document, dict(options))
    return {"generator": name,
            "files": {fname: data.decode("utf-8") for fname, data in files.items()},
            "warnings": [line for line in buf.getvalue().splitlines() if line.strip()]}


_TEXT_ARGUMENT = {"type": "string",
                  "description": "LNPL source as text. Use this to check "
                                 "a draft before writing it to disk."}
_SOURCE_PATH_ARGUMENT = {"type": "string",
                         "description": "Path to a .lnpl file or a directory "
                                        "of them. Give either `text` or "
                                        "`path`, not both."}
_MODULE_ARGUMENT = {"type": "string",
                    "description": "Module name for the lowered IR "
                                   "(default: mcp for `text`, the file or "
                                   "directory name for `path`)."}


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
                         "description": "Path to a .lnpl file, or to a "
                                        "directory (its *.lnpl are merged in "
                                        "filename-sorted order — RFC-0031, "
                                        "issue #77). Give either `text` or "
                                        "`path`, not both."},
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
    {
        "name": "lnpl_vocabulary",
        "description": (
            "Return the vendor-neutral vocabulary manifest — verbs, keywords, "
            "semantic types, declaration clauses, the enforcement matrix, "
            "diagnostic codes, and reserved words. Use this instead of the "
            "Claude Code plugin's Korean reference markdown when no plugin is "
            "loaded: the closed lexicon is not in any model's training data, "
            "so a plausible-sounding verb parses and silently does nothing "
            "(issue #36) unless it is checked against this manifest first."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "lnpl_capabilities",
        "description": (
            "Return the installed-extension catalog: for each of the ten "
            "slots (repository, cache, network, token, exporter, generators, "
            "diagnostics, kb, publishers, secrets), the "
            "built-in names and every registered entry-point name with "
            "whether it actually loads. Use this instead of trying a "
            "`--backend`/`--cache`/`--network`/`--token-provider`/"
            "`--trace-exporter` value and reading the failure — discovery "
            "here never fails: a broken registration is listed "
            "`loadable: false` rather than raising (issue #134)."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "lnpl_run",
        "description": (
            "Run one workflow of LNPL source on the interpreter's deterministic "
            "fake backend — in-memory repository, fake network, fake cache, "
            "virtual clock; no real I/O and nothing written — and return the "
            "same {result, trace, diagnostics} document `lnpl run --json` "
            "prints. `diagnostics` is always present (an empty list when "
            "clean). Use this instead of shelling out to `lnpl run`, whose "
            "diagnostics go to stderr."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": _TEXT_ARGUMENT,
                "path": _SOURCE_PATH_ARGUMENT,
                "module": _MODULE_ARGUMENT,
                "workflow": {"type": "string",
                             "description": "Workflow node id to run, e.g. "
                                            "wf.save (default: the first "
                                            "workflow)."},
                "payload": {"type": "object",
                            "description": "Input payload (default: a sample "
                                           "payload derived from the "
                                           "entities)."},
                "no_row": {"type": "boolean",
                           "description": "Start from an empty repository "
                                          "instead of the default seeded rows "
                                          "(default: false)."},
            },
        },
    },
    {
        "name": "lnpl_openapi",
        "description": (
            "Return the OpenAPI 3.1 document of LNPL source as text — "
            "byte-identical to what `lnpl openapi <path>` prints for the same "
            "file. Nothing is written."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": _TEXT_ARGUMENT,
                "path": _SOURCE_PATH_ARGUMENT,
                "module": _MODULE_ARGUMENT,
            },
        },
    },
    {
        "name": "lnpl_generate",
        "description": (
            "Run the built-in `compose` or `k8s` deployment generator on LNPL "
            "source and return {generator, files: {name: text}, warnings} — "
            "the same bytes `lnpl generate <name> --out DIR` writes, plus any "
            "skipped-capability warnings. Nothing is written. `options` takes "
            "the `--set` keys as strings (compose: image, port, source, "
            "postgres_image, redis_image; k8s: image, name, replicas, "
            "cpu_request, cpu_limit, memory, ingress_host, hpa_min, hpa_max, "
            "hpa_cpu, pdb, network_policy, egress_cidrs)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "generator": {"type": "string", "enum": ["compose", "k8s"],
                              "description": "Which generator to run."},
                "text": _TEXT_ARGUMENT,
                "path": _SOURCE_PATH_ARGUMENT,
                "module": _MODULE_ARGUMENT,
                "options": {"type": "object",
                            "additionalProperties": {"type": "string"},
                            "description": "Generator options as strings, the "
                                           "keys `--set` accepts."},
            },
            "required": ["generator"],
        },
    },
]

HANDLERS = {
    "lnpl_compile": tool_compile,
    "lnpl_kb_route": tool_kb_route,
    "lnpl_spec": tool_spec,
    "lnpl_vocabulary": tool_vocabulary,
    "lnpl_capabilities": tool_capabilities,
    "lnpl_run": tool_run,
    "lnpl_openapi": tool_openapi,
    "lnpl_generate": tool_generate,
}


def _text_content(payload):
    if isinstance(payload, str):
        return [{"type": "text", "text": payload}]
    return [{"type": "text", "text": json.dumps(payload, ensure_ascii=False,
                                                indent=2, sort_keys=True)}]


def handle(message, *, allow_paths=True):
    """요청 하나를 처리한다. 알림이면 None을 돌려 아무것도 쓰지 않게 한다.

    `allow_paths=False` (the HTTP transport) refuses every argument in
    `FILESYSTEM_ARGUMENTS` before any tool runs."""
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
            "protocolVersion": (requested if requested in SUPPORTED_PROTOCOL_VERSIONS
                                else PROTOCOL_VERSION),
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
        arguments = params.get("arguments") or {}
        if not allow_paths:
            for key in FILESYSTEM_ARGUMENTS:
                if key in arguments:
                    return _ok(mid, {
                        "content": [{"type": "text",
                                     "text": "ValueError: argument `%s` is disabled on the "
                                             "HTTP transport; send the source as `text`" % key}],
                        "isError": True,
                    })
        try:
            payload = handler(arguments)
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

#!/usr/bin/env python3
"""`lnpl-mcp` 플러그인의 실행 진입점 — 얇은 런처.

로직은 `lnpl.mcp_server`에 있다. 그래야 레포의 스위트가 그것을 직접 돌릴 수
있다. 이 파일이 하는 일은 하나뿐이다: 그 패키지를 **찾는 것**.

플러그인은 `~/.claude/plugins/cache/...` 아래에 설치되므로, 여기서 위로 올라가도
레포는 나오지 않는다. 그리고 cwd나 `CLAUDE_PROJECT_DIR`에서 위로 올라가며
`impl/lnpl`을 찾아 임포트하는 것은 그 자체로 보안 구멍이다 — 그 디렉터리를
여는 누구든 `impl/lnpl/__init__.py`를 심어 이 서버 프로세스 안에서 자기
코드를 돌릴 수 있다. 그래서 사용자가 **명시적으로 설정한** 값만 쓴다:

  1. `$LNPL_IMPL_PATH` — 사용자가 설정한 절대 경로. 상대 경로이거나
     `lnpl/__init__.py`가 없으면 무시한다 — 치명적이지 않다, stderr에
     이유만 남기고 다음 단계로 넘어간다.
  2. `import lnpl`           — `pip install .` 로 설치된 경우

cwd, `CLAUDE_PROJECT_DIR`, 또는 열린 파일에서 경로를 유도하지 않는다 — 전부
프로젝트가 통제할 수 있는 입력이라 신뢰할 수 없다.

둘 다 실패해도 **서버는 죽지 않는다.** 연결 자체를 실패시키면 클라이언트는
"연결 실패"만 보고 이유를 전혀 알 수 없다 — 대신 핸드셰이크는 정상적으로
답하고, 모든 툴 호출이 설치 방법을 설명하는 구조화된 에러로 답한다.

성공하면 어느 단계가 어느 경로를 골랐는지 stderr에 한 줄 남기고, 같은 내용과
어휘 digest를 상태 파일(`$LNPL_MCP_STATE`, 기본 `~/.claude/lnpl-plugin/
mcp-last-start.json`)에 적는다 — `lnpl-doctor`가 CLI와 비교한다(issue #205).
stdout은 MCP 프로토콜 채널이라 아무것도 쓰지 않는다.
"""

import json
import os
import sys

DEFAULT_STATE_PATH = os.path.join(os.path.expanduser("~"), ".claude",
                                  "lnpl-plugin", "mcp-last-start.json")

# tools/list가 fallback에서도 이 이름들을 내보낸다 — `lnpl.mcp_server.TOOLS`를
# 임포트할 수 없는 상태이므로(그 모듈 자체가 lnpl 패키지 안에 있다) 이름만 복제한다.
_FALLBACK_TOOL_NAMES = ("lnpl_compile", "lnpl_kb_route", "lnpl_spec",
                       "lnpl_vocabulary", "lnpl_capabilities")

_NOT_FOUND_REASON = (
    "lnpl-mcp: could not locate the `lnpl` package. Set LNPL_IMPL_PATH to an "
    "absolute impl/ directory containing lnpl/__init__.py, or `pip install .` "
    "the linkly checkout so `import lnpl` works.")


def _add_impl(path):
    if path and os.path.isfile(os.path.join(path, "lnpl", "__init__.py")):
        if path not in sys.path:
            sys.path.insert(0, path)
        return True
    return False


def _resolve_lnpl_impl_path():
    """`$LNPL_IMPL_PATH` 하나만 본다 — 사용자가 직접 설정한 값.

    상대 경로이거나 가리키는 디렉터리에 `lnpl/__init__.py`가 없으면 무시하고
    stderr에 한 줄 남긴다. 이 함수가 cwd나 프로젝트 디렉터리를 전혀 보지
    않는 것이 보안 경계다.
    """
    explicit = os.environ.get("LNPL_IMPL_PATH")
    if not explicit:
        return None
    if not os.path.isabs(explicit):
        sys.stderr.write(
            "lnpl-mcp: $LNPL_IMPL_PATH=%r is not an absolute path; ignoring.\n"
            % explicit)
        return None
    if not _add_impl(explicit):
        sys.stderr.write(
            "lnpl-mcp: $LNPL_IMPL_PATH=%r has no lnpl/__init__.py; ignoring.\n"
            % explicit)
        return None
    return explicit


def _write_state_file(method, path):
    state_path = os.environ.get("LNPL_MCP_STATE") or DEFAULT_STATE_PATH
    # A state file the launcher cannot write must never keep the server from
    # starting: the client would only see "connection failed". `lnpl-doctor`
    # treats an absent file as "nothing to compare".
    try:
        from lnpl import __version__, provenance
        document = {
            "discovery": method,
            "path": path,
            "lnpl_version": __version__,
            "vocabulary_digest": provenance._current_vocabulary_digest(),
        }
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as fh:
            json.dump(document, fh)
    except Exception:
        pass


def _fallback_serve(reason):
    """`lnpl`을 못 찾아도 서버는 뜬다.

    `lnpl.mcp_server`를 임포트할 수 없는 상태이므로(그 모듈 자체가 찾는
    패키지 안에 있다) 최소한의 JSON-RPC stdio 루프를 여기서 직접 구현한다.
    initialize/tools/list는 정상 응답하고, tools/call은 어느 툴을 불러도
    `reason`을 담은 isError로 답한다.
    """
    tools = [{"name": name,
             "description": "unavailable: " + reason,
             "inputSchema": {"type": "object"}}
            for name in _FALLBACK_TOOL_NAMES]
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("top-level JSON-RPC message must be an object")
        except ValueError as exc:
            response = {"jsonrpc": "2.0", "id": None,
                       "error": {"code": -32700,
                                "message": "invalid JSON: %s" % exc}}
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
            continue
        method = message.get("method")
        mid = message.get("id")
        if method == "notifications/initialized" or mid is None:
            continue
        if method == "initialize":
            requested = (message.get("params") or {}).get("protocolVersion")
            response = {"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": requested or "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "lnpl", "version": "unavailable"}}}
        elif method == "tools/list":
            response = {"jsonrpc": "2.0", "id": mid,
                       "result": {"tools": tools}}
        elif method == "tools/call":
            # 이 fallback은 설치/설정을 고치라고 말하는 것이 유일한 목적이라
            # 툴 이름을 검증하지 않는다 — 어느 이름으로 불러도 같은 isError를
            # 돌려준다. 실제 서버(`lnpl.mcp_server.handle`)는 모르는 툴 이름을
            # 프로토콜 오류(INVALID_PARAMS)로 거부하지만, 여기서는 그 구분이
            # 메시지의 가치를 더하지 않는다.
            response = {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": reason}],
                "isError": True}}
        else:
            response = {"jsonrpc": "2.0", "id": mid,
                       "error": {"code": -32601,
                                "message": "unknown method %r" % method}}
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def main():
    resolved = _resolve_lnpl_impl_path()
    if resolved:
        method, resolved_path = "$LNPL_IMPL_PATH", resolved
    else:
        try:
            import lnpl
            method = "import lnpl (installed)"
            resolved_path = os.path.dirname(os.path.abspath(lnpl.__file__))
        except ImportError:
            method = None
            resolved_path = None

    if method is None:
        sys.stderr.write(_NOT_FOUND_REASON + "\n")
        _fallback_serve(_NOT_FOUND_REASON)
        return 0

    sys.stderr.write("lnpl-mcp: resolved via %s -> %s\n" % (method, resolved_path))
    _write_state_file(method, resolved_path)
    from lnpl.mcp_server import serve
    serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())

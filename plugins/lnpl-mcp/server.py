#!/usr/bin/env python3
"""`lnpl-mcp` 플러그인의 실행 진입점 — 얇은 런처.

로직은 `lnpl.mcp_server`에 있다. 그래야 레포의 스위트가 그것을 직접 돌릴 수
있다. 이 파일이 하는 일은 하나뿐이다: 그 패키지를 **찾는 것**.

플러그인은 `~/.claude/plugins/cache/...` 아래에 설치되므로, 여기서 위로 올라가도
레포는 나오지 않는다. 그래서 세 가지를 순서대로 시도한다:

  1. `$LNPL_IMPL`            — 레포의 `impl/` 경로를 명시적으로 준다
  2. `import lnpl`           — `pip install .` 로 설치된 경우
  3. cwd에서 위로 올라가며 찾은 `impl/lnpl/__init__.py`
                             — Claude Code가 레포 안에서 서버를 띄운 경우

셋 다 실패하면 **조용히 죽지 않는다.** stderr에 무엇을 시도했는지 적고 나간다 —
서버가 시작되지 않으면 클라이언트는 "연결 실패"만 보고, 이유는 여기서만 말할 수
있다.

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


def _add_impl(path):
    if path and os.path.isfile(os.path.join(path, "lnpl", "__init__.py")):
        if path not in sys.path:
            sys.path.insert(0, path)
        return True
    return False


def _walk_up_for_impl(start):
    cur = os.path.abspath(start)
    while True:
        candidate = os.path.join(cur, "impl")
        if _add_impl(candidate):
            return candidate
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


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


def main():
    tried = []

    explicit = os.environ.get("LNPL_IMPL")
    tried.append("$LNPL_IMPL=%r" % explicit)
    if _add_impl(explicit):
        method = "$LNPL_IMPL"
        resolved_path = os.path.abspath(explicit)
    else:
        try:
            import lnpl
            tried.append("import lnpl (installed)")
            method = "import lnpl (installed)"
            resolved_path = os.path.dirname(os.path.abspath(lnpl.__file__))
        except ImportError:
            tried.append("import lnpl -> not installed")
            resolved_path = _walk_up_for_impl(os.getcwd())
            if resolved_path is None:
                sys.stderr.write(
                    "lnpl-mcp: could not locate the `lnpl` package.\n"
                    "tried: %s, then walked up from cwd=%s for impl/lnpl.\n"
                    "Set LNPL_IMPL to the repo's impl/ directory, or "
                    "`pip install .` in the linkly checkout.\n"
                    % ("; ".join(tried), os.getcwd()))
                return 1
            method = "cwd walk-up"

    sys.stderr.write("lnpl-mcp: resolved via %s -> %s\n" % (method, resolved_path))
    _write_state_file(method, resolved_path)
    from lnpl.mcp_server import serve
    serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())

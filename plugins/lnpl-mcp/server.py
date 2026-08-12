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
"""

import os
import sys


def _add_impl(path):
    if path and os.path.isfile(os.path.join(path, "lnpl", "__init__.py")):
        if path not in sys.path:
            sys.path.insert(0, path)
        return True
    return False


def _walk_up_for_impl(start):
    cur = os.path.abspath(start)
    while True:
        if _add_impl(os.path.join(cur, "impl")):
            return True
        parent = os.path.dirname(cur)
        if parent == cur:
            return False
        cur = parent


def main():
    tried = []

    explicit = os.environ.get("LNPL_IMPL")
    tried.append("$LNPL_IMPL=%r" % explicit)
    if _add_impl(explicit):
        pass
    else:
        try:
            import lnpl  # noqa: F401
            tried.append("import lnpl (installed)")
        except ImportError:
            tried.append("import lnpl -> not installed")
            if not _walk_up_for_impl(os.getcwd()):
                sys.stderr.write(
                    "lnpl-mcp: could not locate the `lnpl` package.\n"
                    "tried: %s, then walked up from cwd=%s for impl/lnpl.\n"
                    "Set LNPL_IMPL to the repo's impl/ directory, or "
                    "`pip install .` in the linkly checkout.\n"
                    % ("; ".join(tried), os.getcwd()))
                return 1

    from lnpl.mcp_server import serve
    serve()
    return 0


if __name__ == "__main__":
    sys.exit(main())

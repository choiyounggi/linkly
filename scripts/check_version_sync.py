#!/usr/bin/env python3
"""루트 `pyproject.toml`과 이 저장소의 버전 지점 전부가 일치하는지 검사한다.

    python scripts/check_version_sync.py

버전 소스(issue #153 — `VERSION_SITES`가 정본): 루트 `pyproject.toml`의
`[project] version` ↔ `impl/lnpl/__init__.py`의 `__version__` ↔
`plugins/*/.claude-plugin/plugin.json`의 `.version` 전부 ↔
`.claude-plugin/marketplace.json`의 `.plugins[].version` 전부. 불일치하거나
지점이 결손·손상됐으면 그 목록과 함께 exit 1(issue #141: v0.6.0 릴리스 때
plugin.json 드리프트가 실제로 발생했고, v0.7.0 때는 `__version__` 드리프트를
이 스크립트의 옛 버전이 놓쳤다).
"""
import ast
import glob
import json
import os
import sys
import tomllib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPROJECT_PATH = os.path.join(REPO, "pyproject.toml")
DUNDER_PATH = os.path.join(REPO, "impl", "lnpl", "__init__.py")
PLUGIN_GLOB = os.path.join(REPO, "plugins", "*", ".claude-plugin", "plugin.json")
MARKETPLACE_PATH = os.path.join(REPO, ".claude-plugin", "marketplace.json")

# 이 저장소의 버전 지점 4종의 정본 목록(issue #153). `check()`가 여기 등록된
# 기본 경로들(REPO/DUNDER_PATH/PLUGIN_GLOB/MARKETPLACE_PATH) 위에서 돈다 —
# `impl/tests/test_packaging.py`·`impl/tests/test_plugin_manifest.py`가
# 하드코딩한 지점과 이 목록이 갈라지면 안 된다(결합 테스트로 고정).
VERSION_SITES = (
    ("pyproject.toml [project] version", "toml", PYPROJECT_PATH),
    ("impl/lnpl/__init__.py __version__", "dunder", DUNDER_PATH),
    ("plugins/*/.claude-plugin/plugin.json", "plugin_json", PLUGIN_GLOB),
    (".claude-plugin/marketplace.json .plugins[]", "marketplace", MARKETPLACE_PATH),
)


class VersionSyncError(Exception):
    """루트 버전을 아예 읽을 수 없을 때 — 비교할 기준이 없으니 검사를 계속할
    수 없다."""


def root_version(pyproject_path=PYPROJECT_PATH):
    with open(pyproject_path, "rb") as fh:
        data = tomllib.load(fh)
    try:
        return data["project"]["version"]
    except KeyError as exc:
        raise VersionSyncError(
            "%s: [project] version 없음" % pyproject_path) from exc


def plugin_version(plugin_json_path):
    """plugin.json 하나의 (version, error) — 결손·손상은 예외로 던지지 않고
    사유 문자열로 돌려준다. 하나가 깨졌다고 나머지 플러그인 검사를 중단하면
    안 되므로(check()가 전부 모아 한 번에 보고한다)."""
    try:
        with open(plugin_json_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return None, "파일 없음"
    except json.JSONDecodeError as exc:
        return None, "JSON 파싱 실패: %s" % exc
    if "version" not in data:
        return None, "version 필드 없음"
    return data["version"], None


def dunder_version(dunder_path):
    """`impl/lnpl/__init__.py`의 최상위 `__version__` 대입값 — (version, error).

    **`ast`로만 읽는다. `import lnpl`은 쓰지 않는다.** 저장소 루트에서
    `import lnpl`은 소스 트리가 아니라 설치된 패키지를 집는다 — issue #141이
    기록한 v0.6.0 사고("설치된 콘솔 스크립트는 0.5.0인데 플러그인만
    0.6.0")가 정확히 그 드리프트이므로, import로 읽으면 이 스크립트가
    잡아야 할 드리프트를 구조적으로 못 본다.

    결손·손상은 `plugin_version`과 같은 규약으로 사유 문자열로 돌려준다.
    """
    try:
        with open(dunder_path, encoding="utf-8") as fh:
            source = fh.read()
    except FileNotFoundError:
        return None, "파일 없음"
    try:
        tree = ast.parse(source, filename=dunder_path)
    except SyntaxError as exc:
        return None, "파싱 실패: %s" % exc
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id == "__version__":
                value = node.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    return value.value, None
    return None, "__version__ 대입 없음"


def marketplace_entry_versions(marketplace_path):
    """`.claude-plugin/marketplace.json`의 `.plugins[]` 항목별 (label, version,
    error) 리스트.

    파일 결손·손상, 그리고 `.plugins`가 없거나 빈 배열인 경우 모두 문제로
    보고한다(`check()`의 기존 빈 글롭 규약과 동일 — issue #141 r1: 검사
    대상이 조용히 사라지면 게이트가 소리 없이 통과해 버린다).
    """
    try:
        with open(marketplace_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return [(marketplace_path, None, "파일 없음")]
    except json.JSONDecodeError as exc:
        return [(marketplace_path, None, "JSON 파싱 실패: %s" % exc)]
    plugins = data.get("plugins")
    if not plugins:
        return [(marketplace_path, None,
                  "0 plugins — .plugins가 없거나 빈 배열이다")]
    results = []
    for i, entry in enumerate(plugins):
        label = "%s#plugins[%d](%s)" % (marketplace_path, i, entry.get("name", "?"))
        if "version" not in entry:
            results.append((label, None, "version 필드 없음"))
        else:
            results.append((label, entry["version"], None))
    return results


def _resolve_sites(pyproject_path, plugin_paths, dunder_path, marketplace_path):
    """이번 호출에서 실제로 비교할 (plugin_paths, dunder_path, marketplace_path,
    discovered)를 정한다.

    `dunder_path`/`marketplace_path`가 명시되지 않았으면(`None`) 기본적으로
    이 저장소의 실제 위치(`DUNDER_PATH`/`MARKETPLACE_PATH`)를 쓴다 — 단,
    `pyproject_path`도 기본 위치(`PYPROJECT_PATH`)가 아니면 건너뛴다. 그
    경우 호출자는 합성 트리로 검사 중인 것이라, 이 저장소의 실제 파일과
    비교하면 무관한 실패만 만든다(`plugin_paths`를 명시적으로 넘기면 글롭
    발견을 건너뛰는 기존 규약과 같은 이유).
    """
    discovered = plugin_paths is None
    if discovered:
        plugin_paths = sorted(glob.glob(PLUGIN_GLOB))
    is_default_root = os.path.abspath(pyproject_path) == PYPROJECT_PATH
    if dunder_path is None and is_default_root:
        dunder_path = DUNDER_PATH
    if marketplace_path is None and is_default_root:
        marketplace_path = MARKETPLACE_PATH
    return plugin_paths, dunder_path, marketplace_path, discovered


def check(pyproject_path=PYPROJECT_PATH, plugin_paths=None,
          dunder_path=None, marketplace_path=None):
    """(root_version, [(site_path, problem_message)]) — problem은 불일치
    아니면 결손 사유. `VERSION_SITES`의 네 지점(pyproject/dunder/plugin_json
    ×N/marketplace 엔트리 ×N) 전부를 root(`pyproject.toml`)와 비교한다.

    `plugin_paths=None`(기본 글롭 발견)일 때 매치가 0건이면 그 자체를 문제로
    보고한다 — `plugins/` 경로가 개편되어 글롭이 조용히 아무것도 찾지 못하면
    검사할 대상이 사라져 버전 드리프트 게이트가 소리 없이 통과해 버리기
    때문이다(issue #141 r1). 호출자가 명시적으로 빈 리스트를 넘긴 경우는
    그 의도를 그대로 존중해 문제로 보지 않는다.

    `dunder_path`/`marketplace_path`는 `None`이면 기본 위치를 쓰되, `_resolve_sites`의
    규약에 따라 `pyproject_path`가 기본 위치가 아닐 때는(합성 트리 검사)
    건너뛴다 — 명시적으로 넘기면 항상 그 경로로 검사한다."""
    root = root_version(pyproject_path)
    plugin_paths, dunder_path, marketplace_path, discovered = _resolve_sites(
        pyproject_path, plugin_paths, dunder_path, marketplace_path)
    problems = []
    if discovered and not plugin_paths:
        problems.append((PLUGIN_GLOB,
                          "0 plugin manifests found — glob matched nothing "
                          "(plugins/ 경로가 옮겨졌나?)"))
    for path in plugin_paths:
        version, error = plugin_version(path)
        if error:
            problems.append((path, error))
        elif version != root:
            problems.append((path, "버전 %s (루트는 %s)" % (version, root)))
    if dunder_path is not None:
        version, error = dunder_version(dunder_path)
        if error:
            problems.append((dunder_path, error))
        elif version != root:
            problems.append((dunder_path, "버전 %s (루트는 %s)" % (version, root)))
    if marketplace_path is not None:
        for label, version, error in marketplace_entry_versions(marketplace_path):
            if error:
                problems.append((label, error))
            elif version != root:
                problems.append((label, "버전 %s (루트는 %s)" % (version, root)))
    return root, problems


def count_sites(pyproject_path=PYPROJECT_PATH, plugin_paths=None,
                 dunder_path=None, marketplace_path=None):
    """이번 호출이 실제로 비교하는 지점 수 — 성공 출력에 몇 개를 봤는지
    찍기 위함(issue #153: v0.7.0의 실패 모드는 '초록인데 절반만 봤다'였다.
    몇 개를 봤는지 찍지 않으면 사람이 그 사실을 알 방법이 없다)."""
    plugin_paths, dunder_path, marketplace_path, _ = _resolve_sites(
        pyproject_path, plugin_paths, dunder_path, marketplace_path)
    n = len(plugin_paths)
    if dunder_path is not None:
        n += 1
    if marketplace_path is not None:
        n += len(marketplace_entry_versions(marketplace_path))
    return n


def main(pyproject_path=PYPROJECT_PATH, plugin_paths=None,
         dunder_path=None, marketplace_path=None):
    root, problems = check(pyproject_path, plugin_paths, dunder_path, marketplace_path)
    if problems:
        print("버전 불일치 — 루트 pyproject.toml [project] version = %s" % root)
        for path, msg in problems:
            print("  %s: %s" % (path, msg))
        print("\n%d problem(s)" % len(problems))
        return 1
    n = count_sites(pyproject_path, plugin_paths, dunder_path, marketplace_path)
    print("버전 일치: %s (%d개 지점)" % (root, n))
    return 0


if __name__ == "__main__":
    sys.exit(main())

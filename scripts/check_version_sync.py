#!/usr/bin/env python3
"""루트 `pyproject.toml`과 각 플러그인 manifest의 버전이 일치하는지 검사한다.

    python scripts/check_version_sync.py

버전 소스: 루트 `pyproject.toml`의 `[project] version` ↔
`plugins/*/.claude-plugin/plugin.json`의 `.version` 전부. 불일치하거나 파일이
결손·손상된 플러그인이 있으면 그 목록과 함께 exit 1(issue #141: v0.6.0 릴리스
때 이 드리프트가 실제로 발생했다).
"""
import glob
import json
import os
import sys
import tomllib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPROJECT_PATH = os.path.join(REPO, "pyproject.toml")
PLUGIN_GLOB = os.path.join(REPO, "plugins", "*", ".claude-plugin", "plugin.json")


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


def check(pyproject_path=PYPROJECT_PATH, plugin_paths=None):
    """(root_version, [(plugin_path, problem_message)]) — problem은 불일치
    아니면 결손 사유.

    `plugin_paths=None`(기본 글롭 발견)일 때 매치가 0건이면 그 자체를 문제로
    보고한다 — `plugins/` 경로가 개편되어 글롭이 조용히 아무것도 찾지 못하면
    검사할 대상이 사라져 버전 드리프트 게이트가 소리 없이 통과해 버리기
    때문이다(issue #141 r1). 호출자가 명시적으로 빈 리스트를 넘긴 경우는
    그 의도를 그대로 존중해 문제로 보지 않는다."""
    root = root_version(pyproject_path)
    discovered = plugin_paths is None
    if discovered:
        plugin_paths = sorted(glob.glob(PLUGIN_GLOB))
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
    return root, problems


def main(pyproject_path=PYPROJECT_PATH, plugin_paths=None):
    root, problems = check(pyproject_path, plugin_paths)
    if problems:
        print("버전 불일치 — 루트 pyproject.toml [project] version = %s" % root)
        for path, msg in problems:
            print("  %s: %s" % (path, msg))
        print("\n%d problem(s)" % len(problems))
        return 1
    print("버전 일치: %s" % root)
    return 0


if __name__ == "__main__":
    sys.exit(main())

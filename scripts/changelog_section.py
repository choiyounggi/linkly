#!/usr/bin/env python3
"""`CHANGELOG.md`에서 한 버전 절의 본문 또는 제목을 뽑는다.

    python scripts/changelog_section.py v0.7.0            # 본문을 stdout으로
    python scripts/changelog_section.py v0.7.0 --title    # 제목 한 줄을 stdout으로

절 경계: `## [<version>]`로 시작하는 줄부터 다음 `## [` 직전까지(다음 헤딩이
없으면 참조식 링크 정의 블록(`[x.y.z]: https://...`) 직전까지, 그마저
없으면 파일 끝까지). 헤딩 줄 자체는 본문에서 제외하고, 앞뒤 빈 줄을
잘라낸다. 버전 인자는 `vX.Y.Z`와 `X.Y.Z`를 둘 다 받는다(선행 `v` 하나를
벗긴다) — 태그 표기(`github.ref_name`)와 CHANGELOG 표기가 다르기 때문이다.

절을 찾지 못하면(오타, 아직 릴리스되지 않은 버전, 또는 `Unreleased`처럼
애초에 버전이 아닌 절 이름) exit 1이고 stdout에는 아무것도 쓰지 않는다 —
issue #154: 조용히 빈 릴리스 노트를 발행하지 않기 위함이다. stderr에는
파일에 실제로 있는 버전 목록을 함께 적는다.
"""
import argparse
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHANGELOG_PATH = os.path.join(REPO, "CHANGELOG.md")

HEADER_RE = re.compile(r'^## \[([^\]]+)\].*\n?', re.MULTILINE)
VERSION_RE = re.compile(r'^\d+\.\d+\.\d+$')
# Keep a Changelog의 참조식 링크 정의(`[0.7.0]: https://...`) 줄. 모든 버전
# 절 바깥, 파일 맨 끝에 몰려 있다 — 마지막 절의 본문이 파일 끝까지 뻗어
# 나가면 이 블록까지 삼킨다(r1 F1).
LINK_DEF_RE = re.compile(r'^\[[^\]]+\]:\s', re.MULTILINE)


class SectionNotFound(Exception):
    """요청한 버전 절이 CHANGELOG에 없다."""

    def __init__(self, requested, available):
        self.requested = requested
        self.available = available
        super().__init__(
            "no changelog section for version %r (available versions: %s)"
            % (requested, ", ".join(available) or "(none)"))


def _normalize(version):
    return version[1:] if version.startswith("v") else version


def _trim_blank_lines(text):
    lines = text.split("\n")
    while lines and lines[0].strip() == "":
        lines.pop(0)
    while lines and lines[-1].strip() == "":
        lines.pop()
    return "\n".join(lines)


def _headers(text):
    """파일에 있는 모든 `## [...]` 헤딩을 (절 이름, 헤딩 줄 시작, 본문 시작)
    순서로 돌려준다. `Unreleased`처럼 버전이 아닌 헤딩도 다음 헤딩 경계
    탐지에는 참여해야 하므로 여기서는 걸러내지 않는다."""
    return [(m.group(1), m.start(), m.end()) for m in HEADER_RE.finditer(text)]


def extract_section(text, version):
    """`version`(`vX.Y.Z` 또는 `X.Y.Z`) 절의 본문을 돌려준다. 없으면
    `SectionNotFound`."""
    target = _normalize(version)
    headers = _headers(text)
    available = [v for v, _start, _body in headers if VERSION_RE.match(v)]
    for i, (v, _line_start, body_start) in enumerate(headers):
        if VERSION_RE.match(v) and v == target:
            if i + 1 < len(headers):
                body_end = headers[i + 1][1]
            else:
                link_defs = LINK_DEF_RE.search(text, body_start)
                body_end = link_defs.start() if link_defs else len(text)
            return _trim_blank_lines(text[body_start:body_end])
    raise SectionNotFound(target, available)


def extract_title(tag, text, version):
    """`linkly <tag> — <절의 따옴표 테마>`, 테마가 없으면 `linkly <tag>`.

    `tag`는 호출자가 넘긴 원문(예: `v0.7.0`)을 그대로 쓴다 — GitHub Release
    제목은 태그 표기를 그대로 보여줘야 하므로 여기서 정규화하지 않는다."""
    body = extract_section(text, version)
    first_line = body.splitlines()[0] if body else ""
    match = re.match(r'^"([^"]*)"', first_line)
    if match:
        return "linkly %s — %s" % (tag, match.group(1))
    return "linkly %s" % tag


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="vX.Y.Z 또는 X.Y.Z")
    parser.add_argument("--title", action="store_true",
                         help="본문 대신 릴리스 제목 한 줄을 출력한다")
    parser.add_argument("--changelog", default=CHANGELOG_PATH,
                         help="CHANGELOG.md 경로(기본: 저장소 루트)")
    args = parser.parse_args(argv)

    with open(args.changelog, encoding="utf-8") as fh:
        text = fh.read()

    try:
        if args.title:
            print(extract_title(args.version, text, args.version))
        else:
            print(extract_section(text, args.version))
    except SectionNotFound as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

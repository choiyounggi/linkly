#!/usr/bin/env python3
"""RFC-0007의 기계적으로 검사 가능한 조항을 검사한다.

    python scripts/rfc_lint.py            # 사람이 읽는 보고 + 문제가 있으면 exit 1
    python scripts/rfc_lint.py --quiet    # 문제만 출력

검사하는 것(전부 RFC-0007 조항):
  §3 번호 체계   파일명 `NNNN-<kebab-slug>.md`, 번호 중복 없음, 번호 공백 없음,
                 제목 줄의 번호가 파일명과 일치
  §2.1 수명주기  Status가 있고 어휘(Draft/Review/Accepted/Superseded) 안에 있음
  §7 템플릿      설계 RFC의 섹션이 고정 7개와 **이름·순서까지** 일치
                 (§7은 추가·삭제·개명을 명시적으로 금지한다)

검사하지 않는 것: 내용의 정합성, Supersedes/Updates가 가리키는 대상의 존재
여부(§2.2는 연쇄 갱신까지 요구해서 기계적 판정이 모호하다), 골든 시나리오 사용.

이 스크립트는 테스트 스위트에 걸려 있지 않다 — 기여자가 손으로 돌리는 도구다.
검사 로직 자체는 `impl/tests/test_rfc_lint.py`가 합성 입력으로 검증한다.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RFC_DIR = os.path.join(REPO, "rfcs")

FILENAME_RE = re.compile(r"^(\d{4})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
TITLE_RE = re.compile(r"^#\s*RFC-(\d{4}):\s*\S")
# 두 형식을 모두 받는다: `> Status: X` (RFC-0000)과 `- Status: X` (RFC-0001 이후).
STATUS_RE = re.compile(r"^[>\-]\s*Status:\s*\*{0,2}(\w+)\*{0,2}")

STATUSES = ("Draft", "Review", "Accepted", "Superseded")

# RFC-0007 §7이 요구하는 고정 섹션.
REQUIRED_SECTIONS = ("Status", "Motivation", "Guide-level Explanation",
                     "Reference-level Specification", "Examples",
                     "Alternatives", "Open Questions")

# RFC-0007 §1의 "프로세스 RFC 면제" — 프로세스 자체를 규정하는 문서는 §7 템플릿과
# §6 골든 시나리오 규칙을 적용받지 않는다. 기계적으로 판정할 수 없어 명시한다.
PROCESS_RFCS = ("0000", "0007")


def sections(text):
    """문서의 `## ` 제목 목록. 코드 펜스 안은 세지 않는다 — 프로세스 RFC는
    템플릿을 펜스 안에 인용하므로, 세면 자기 템플릿을 자기 섹션으로 오인한다."""
    out, fenced = [], False
    for line in text.split("\n"):
        if line.startswith("```"):
            fenced = not fenced
            continue
        if not fenced and line.startswith("## "):
            out.append(line[3:].strip())
    return out


def status_of(text):
    """첫 번째 Status 선언. 없으면 None.

    코드 펜스 안(프로세스 RFC가 인용한 템플릿)은 건너뛴다.
    """
    fenced = False
    for line in text.split("\n"):
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = STATUS_RE.match(line.strip())
        if m:
            return m.group(1)
    return None


def check_document(filename, text):
    """한 문서의 문제 목록. 각 항목은 (조항, 메시지)."""
    problems = []
    m = FILENAME_RE.match(filename)
    if not m:
        problems.append(("§3", "파일명이 `NNNN-<kebab-slug>.md` 형식이 아니다"))
        return problems
    number = m.group(1)

    first = next((l for l in text.split("\n") if l.strip()), "")
    title = TITLE_RE.match(first.strip())
    if not title:
        problems.append(("§3", "첫 줄이 `# RFC-NNNN: <제목>` 형식이 아니다"))
    elif title.group(1) != number:
        problems.append(("§3", "제목의 번호 RFC-%s가 파일명 %s와 다르다"
                         % (title.group(1), number)))

    status = status_of(text)
    if status is None:
        problems.append(("§2.1", "Status 선언이 없다"))
    elif status not in STATUSES:
        problems.append(("§2.1", "Status `%s`가 어휘(%s) 밖이다"
                         % (status, " / ".join(STATUSES))))

    if number not in PROCESS_RFCS:
        problems.extend(check_sections(sections(text)))
    return problems


def check_sections(have):
    """§7: 7개 섹션의 이름과 순서가 고정이고 추가·삭제·개명이 금지된다.

    누락 / 초과 / 순서를 따로 보고한다 — 한 줄로 뭉치면 무엇을 고쳐야 하는지
    읽히지 않는다.
    """
    problems = []
    missing = [s for s in REQUIRED_SECTIONS if s not in have]
    if missing:
        problems.append(("§7", "템플릿 섹션 누락: %s" % ", ".join(missing)))

    extra = [s for s in have if s not in REQUIRED_SECTIONS]
    if extra:
        problems.append(("§7", "템플릿에 없는 섹션: %s — §7은 섹션 추가를 "
                         "금지한다(내용은 기존 7섹션 안으로 옮겨라)"
                         % ", ".join(extra)))

    # 순서는 누락·초과가 없을 때만 판정한다. 그 둘이 있으면 순서 지적이 소음이다.
    if not missing and not extra and list(have) != list(REQUIRED_SECTIONS):
        problems.append(("§7", "섹션 순서가 템플릿과 다르다: %s" % " → ".join(have)))
    return problems


def check_numbering(filenames):
    """번호 중복과 공백. 각 항목은 (조항, 메시지)."""
    problems, seen = [], {}
    for name in filenames:
        m = FILENAME_RE.match(name)
        if not m:
            continue
        seen.setdefault(m.group(1), []).append(name)
    for number, names in sorted(seen.items()):
        if len(names) > 1:
            problems.append(("§3", "번호 %s가 중복이다: %s"
                             % (number, ", ".join(sorted(names)))))
    if seen:
        numbers = sorted(int(n) for n in seen)
        gaps = [n for n in range(numbers[0], numbers[-1]) if n not in numbers]
        if gaps:
            problems.append(("§3", "번호 공백: %s — 재사용 금지이므로 삭제된 "
                             "문서가 있는지 확인하라"
                             % ", ".join("%04d" % g for g in gaps)))
    return problems


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    quiet = "--quiet" in argv

    names = sorted(n for n in os.listdir(RFC_DIR) if n.endswith(".md"))
    findings = [("(전체)", clause, msg)
                for clause, msg in check_numbering(names)]
    tally = {}
    for name in names:
        with open(os.path.join(RFC_DIR, name), encoding="utf-8") as fh:
            text = fh.read()
        tally[status_of(text) or "(없음)"] = tally.get(status_of(text) or "(없음)", 0) + 1
        findings.extend((name, clause, msg)
                        for clause, msg in check_document(name, text))

    if not quiet:
        print("RFC lint — %d개 문서" % len(names))
        print("상태: " + ", ".join("%s %d" % (k, v) for k, v in sorted(tally.items())))
        print()

    for where, clause, msg in findings:
        print("%-46s %-6s %s" % (where, clause, msg))

    if findings:
        print("\n%d problem(s)" % len(findings))
        return 1
    if not quiet:
        print("문제 없음.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

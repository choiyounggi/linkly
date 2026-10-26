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
  §2.1 출하 기록 CHANGELOG.md(Unreleased와 모든 릴리스 절)가 `RFC-NNNN`
                 (빗금 꼴 `RFC-NNNN/NNNN` 포함)으로 인용한 RFC는 rfcs/에 문서가
                 있고 Accepted 또는 Superseded여야 함 (issue #249)
  §2.2 역링크    Accepted RFC의 `- Updates:` 항목(이어지는 줄 포함)이 괄호 밖에서
                 지목한 `RFC-NNNN`마다 대상 문서의 `- Updated-by:` 항목에
                 `RFC-<갱신>`이 있어야 함. 괄호 안 이름은 직전 갱신(규칙 5)이라
                 대상이 아니고, `없음`으로 시작하는 항목은 대상이 없다. Draft·
                 Review·Superseded 갱신 RFC는 건너뛴다(규칙 6) (issue #263)

검사하지 않는 것: 내용의 정합성, 절 머리 포인터 줄(`> 갱신됨:`)과 절 이름,
연쇄(괄호 안 직전 갱신)의 정확성, 규칙 7의 누적 길이, Supersedes 대상,
골든 시나리오 사용.

CI(`.github/workflows/ci.yml`)가 blocking 게이트로 돌린다. 검사 로직은
`impl/tests/test_rfc_lint.py`가 합성 입력으로 검증하고, §2.2 역링크만은 실제
rfcs/에도 돌려 0건을 요구한다.
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

# CHANGELOG 인용 검사(issue #249): 출하 기록에 오른 RFC는 계약(Accepted)이어야 한다.
CHANGELOG_PATH = os.path.join(REPO, "CHANGELOG.md")
SHIPPED_STATUSES = ("Accepted", "Superseded")
# `RFC-0044/0045`처럼 빗금으로 이은 꼴도 인용이다 — 둘째 번호가 숨지 않게 꼬리까지 잡는다.
CITATION_RE = re.compile(r"RFC-(\d{4})((?:/\d{4})*)(?!\d)")


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

    first = next((line for line in text.split("\n") if line.strip()), "")
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


def cited_numbers(text):
    """CHANGELOG 본문이 인용한 RFC 번호 집합. `RFC-0044/0045`는 두 번호를 다 센다.

    `RFC-` 접두가 없는 맨 번호(예: `0000–0008`)는 인용으로 보지 않는다.
    """
    numbers = set()
    for head, tail in CITATION_RE.findall(text):
        numbers.add(head)
        numbers.update(n for n in tail.split("/") if n)
    return numbers


def collect_statuses(named_texts):
    """(파일명, 본문) 쌍에서 {번호: Status}. 형식 밖 파일명은 건너뛴다 —
    그 문서는 check_document가 이미 §3으로 보고한다."""
    statuses = {}
    for name, text in named_texts:
        m = FILENAME_RE.match(name)
        if m:
            statuses[m.group(1)] = status_of(text)
    return statuses


def check_changelog_citations(text, statuses):
    """CHANGELOG가 인용한 RFC의 문제 목록. 각 항목은 (조항, 메시지).

    같은 번호를 여러 번 인용해도 한 번만, 번호 순으로 보고한다.
    """
    problems = []
    for number in sorted(cited_numbers(text)):
        if number not in statuses:
            problems.append(("§3", "CHANGELOG가 인용한 RFC-%s의 문서가 rfcs/에 없다"
                             % number))
        elif statuses[number] not in SHIPPED_STATUSES:
            problems.append(("§2.1", "CHANGELOG가 RFC-%s를 인용하는데 Status가 %s다 — "
                             "출하 기록에 오른 RFC는 Accepted 또는 Superseded여야 한다"
                             % (number, statuses[number] or "(없음)")))
    return problems


def check_changelog_file(path, statuses):
    """CHANGELOG 파일의 인용 검사. 파일이 없으면 그것 자체를 보고한다."""
    if not os.path.isfile(path):
        return [("§2.1", "%s가 없다 — CHANGELOG 인용 검사를 할 수 없다"
                 % os.path.basename(path))]
    with open(path, encoding="utf-8") as fh:
        return check_changelog_citations(fh.read(), statuses)


# 역링크 검사(RFC-0007 §2.2, issue #263): Accepted 갱신 RFC가 `Updates:`로 지목한 대상은
# 자기 머리의 `Updated-by:`로 그 RFC를 되짚어야 한다(RFC-0007 §2.2 표).
ENTRY_RE = re.compile(r"^-\s*(Updates|Updated-by):\s*(.*)$")
RFC_REF_RE = re.compile(r"RFC-(\d{4})(?!\d)")


def header_entries(text, key):
    """`- <key>:` 항목 본문의 목록. `key`는 "Updates" 또는 "Updated-by".

    항목은 그 줄과 이어지는 줄이다 — 빈 줄, `- `·`#`·`>`로 시작하는 줄, 코드 펜스
    줄에서 끝난다. 펜스 안(프로세스 RFC가 인용한 템플릿)은 건너뛴다.
    """
    out, fenced, current = [], False, None
    for line in text.split("\n"):
        stripped = line.strip()
        if line.startswith("```"):
            fenced = not fenced
            if current is not None:
                out.append(current)
                current = None
            continue
        if fenced:
            continue
        m = ENTRY_RE.match(stripped)
        if m:
            if current is not None:
                out.append(current)
            current = m.group(2) if m.group(1) == key else None
            continue
        if current is None:
            continue
        if not stripped or stripped.startswith(("- ", "#", ">")):
            out.append(current)
            current = None
        else:
            current += " " + stripped
    if current is not None:
        out.append(current)
    return out


def outside_parens(text):
    """괄호 밖 글자만 남긴다(중첩 허용). 괄호 안 RFC 이름은 직전 갱신(규칙 5)이다."""
    depth, kept = 0, []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            kept.append(ch)
    return "".join(kept)


def update_targets(number, text):
    """RFC `number`의 `Updates:` 항목이 괄호 밖에서 지목한 RFC 번호 집합.

    `없음`으로 시작하는 항목은 대상이 없다. 자기 번호는 대상이 아니다.
    """
    targets = set()
    for entry in header_entries(text, "Updates"):
        if entry.lstrip("* ").startswith("없음"):
            continue
        targets.update(RFC_REF_RE.findall(outside_parens(entry)))
    targets.discard(number)
    return targets


def back_link_sources(text):
    """`Updated-by:` 항목이 이름을 댄 RFC 번호 집합(괄호 안 절 이름은 보지 않는다)."""
    sources = set()
    for entry in header_entries(text, "Updated-by"):
        sources.update(RFC_REF_RE.findall(entry))
    return sources


def check_back_links(named_texts):
    """§2.2 역링크 누락. 각 항목은 (파일명, 조항, 메시지), (대상, 갱신) 번호 순.

    Accepted 갱신 RFC만 본다 — Draft·Review·Superseded는 규칙 6에 따라 효력이 없다.
    """
    docs = {}
    for name, text in named_texts:
        m = FILENAME_RE.match(name)
        if m:
            docs[m.group(1)] = (name, text)
    keyed = []
    for updater in sorted(docs):
        name, text = docs[updater]
        if status_of(text) != "Accepted":
            continue
        for target in sorted(update_targets(updater, text)):
            if target not in docs:
                keyed.append(((target, updater), (
                    name, "§2.2", "RFC-%s의 Updates가 지목한 RFC-%s의 문서가 rfcs/에 없다"
                    % (updater, target))))
            elif updater not in back_link_sources(docs[target][1]):
                keyed.append(((target, updater), (
                    docs[target][0], "§2.2",
                    "RFC-%s가 RFC-%s를 Updates로 지목했는데 RFC-%s 머리에 "
                    "`Updated-by: RFC-%s`가 없다" % (updater, target, target, updater))))
    return [finding for _, finding in sorted(keyed)]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    quiet = "--quiet" in argv

    names = sorted(n for n in os.listdir(RFC_DIR) if n.endswith(".md"))
    findings = [("(전체)", clause, msg)
                for clause, msg in check_numbering(names)]
    tally = {}
    named = []
    for name in names:
        with open(os.path.join(RFC_DIR, name), encoding="utf-8") as fh:
            text = fh.read()
        named.append((name, text))
        tally[status_of(text) or "(없음)"] = tally.get(status_of(text) or "(없음)", 0) + 1
        findings.extend((name, clause, msg)
                        for clause, msg in check_document(name, text))
    findings.extend(("CHANGELOG.md", clause, msg)
                    for clause, msg in check_changelog_file(
                        CHANGELOG_PATH, collect_statuses(named)))
    findings.extend(check_back_links(named))

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

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
  §2.2 역링크    Accepted RFC의 `## Status` 절 `- Updates:` 항목(이어지는 줄 포함)이
                 괄호 밖에서 지목한 `RFC-NNNN`마다 대상 문서의 `- Updated-by:` 항목에
                 `RFC-<갱신>`이 있어야 함. 괄호 안 이름은 직전 갱신(규칙 5)이라
                 대상이 아니고, 값이 `없음`·`해당 없음`·`none`·`N/A`(강조·괄호 표기
                 포함)로 시작하는 항목은 대상이 없다. Draft·Review·Superseded 갱신
                 RFC는 건너뛴다(규칙 6) (issue #263, #268)
  §2.2 규칙 7    Accepted RFC의 한 절을 읽으려고 여는 문서(대상 + 대상 머리의
                 `Updated-by:`가 그 절 이름으로 묶은 Accepted 갱신)가 2개 이하이고,
                 Accepted 갱신의 `Updated-by:`마다 절 이름 묶음 `(§…)`이 있음 (issue #268)

검사하지 않는 것: 내용의 정합성, 절 머리 포인터 줄(`> 갱신됨:`)과 절 이름,
연쇄(괄호 안 직전 갱신)의 정확성, Supersedes 대상, 골든 시나리오 사용.

CI(`.github/workflows/ci.yml`)가 blocking 게이트로 돌린다. 검사 로직은
`impl/tests/test_rfc_lint.py`가 합성 입력으로 검증하고, §2.2 역링크와 규칙 7은 실제
rfcs/에도 돌려 0건을 요구한다.
"""
import os
import re
import sys
import unicodedata

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
# `Updates:` 값이 "대상 없음"을 뜻하는 철자(issue #268 §3). 강조·괄호 표기를 벗긴 낱말이
# 값의 끝, 공백, 또는 — – : , . ; 앞에서 끝나야 한다 — `없음없는`·`none-such`는 빈 값이 아니다.
EMPTY_VALUE_RE = re.compile(r"[\s*_`(]*(?:없음|해당 없음|none|n/a)[*_`)]*(?=$|[\s—–:,.;])",
                            re.IGNORECASE)


def status_section(text):
    """`## Status` 절의 줄만 남긴다 — 그 제목 줄 다음부터 펜스 밖 다음 `## ` 제목 앞까지.

    펜스 안의 `## Status`(프로세스 RFC가 인용한 템플릿)는 절을 열지 않는다. 절 안의 펜스
    줄은 남겨 header_entries가 펜스 안을 계속 건너뛰게 한다. 절이 없으면 빈 문자열이다.
    """
    kept, fenced, inside = [], False, False
    for line in text.split("\n"):
        if line.startswith("```"):
            fenced = not fenced
            if inside:
                kept.append(line)
            continue
        if not fenced and line.startswith("## "):
            inside = line[3:].strip() == "Status"
            continue
        if inside:
            kept.append(line)
    return "\n".join(kept)


def header_entries(text, key):
    """`## Status` 절 안의 `- <key>:` 항목 본문의 목록. `key`는 "Updates" 또는 "Updated-by".

    항목은 그 줄과 이어지는 줄이다 — 빈 줄, `- `·`#`·`>`로 시작하는 줄, 코드 펜스
    줄에서 끝난다. 펜스 안(프로세스 RFC가 인용한 템플릿)은 건너뛰고, `## Status`
    절이 없는 문서(프로세스 RFC)는 항목이 없다.
    """
    out, fenced, current = [], False, None
    for line in status_section(text).split("\n"):
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

    값이 빈 값 철자(EMPTY_VALUE_RE)로 시작하는 항목은 대상이 없다. 자기 번호는 대상이 아니다.
    """
    targets = set()
    for entry in header_entries(text, "Updates"):
        if EMPTY_VALUE_RE.match(unicodedata.normalize("NFC", entry)):
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


# 규칙 7(RFC-0007 §2.2, issue #268): 한 절을 읽으려고 여는 문서 = 대상 1개 + 그 절을 갱신한
# Accepted RFC 수. 2개를 넘으면 Updates를 더 쌓지 말고 통합 Supersedes를 쓴다.
# 출처는 대상 머리 `Updated-by: RFC-NNNN (§절, …)`의 절 이름 묶음이다(RFC-0007 §2.2 표).
RULE7_LIMIT = 2
SECTION_SEP_RE = re.compile(r"\s*[,·/]\s*§")
SECTION_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)*)(?=[.\s]|$)")
NUMBERED_KEY_RE = re.compile(r"\d+(?:\.\d+)*")
REFERENCE_PREFIX = "Reference-level Specification/"


def section_groups(entry):
    """`Updated-by:` 항목 하나에서 (갱신 번호, 절 이름 묶음 또는 None) 목록.

    괄호 밖 `RFC-NNNN`마다 하나다. 바로 뒤(공백 허용)에 괄호가 열리면 짝이 맞는 닫는
    괄호까지가 묶음이다 — `코드 → 등급 (정본)`처럼 이름 안의 괄호도 묶음에 남는다.
    괄호가 열리지 않으면 묶음은 None이다.
    """
    out, depth, i = [], 0, 0
    while i < len(entry):
        ch = entry[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            m = RFC_REF_RE.match(entry, i)
            if m:
                j = m.end()
                while entry[j:j + 1] == " ":
                    j += 1
                if entry[j:j + 1] != "(":
                    out.append((m.group(1), None))
                    i = m.end()
                    continue
                level, k = 0, j
                while k < len(entry):
                    if entry[k] == "(":
                        level += 1
                    elif entry[k] == ")":
                        level -= 1
                        if level == 0:
                            break
                    k += 1
                out.append((m.group(1), entry[j + 1:k]))
                i = k + 1
                continue
        i += 1
    return out


def section_key(name):
    """절 이름의 비교 키. 갱신 RFC마다 같은 절을 다르게 적는 철자를 하나로 모은다.

    NFC 정규화, 공백 접기, 앞의 `§`와 `Reference-level Specification/` 제거. 그 뒤가
    점 찍힌 절 번호(`3`, `2.1`)로 시작하면 번호만 남긴다(`3. 피연산자의 차원 규칙` → `3`).
    """
    key = " ".join(unicodedata.normalize("NFC", name).split()).lstrip("§").strip()
    if key.startswith(REFERENCE_PREFIX):
        key = key[len(REFERENCE_PREFIX):]
    m = SECTION_NUMBER_RE.match(key)
    return m.group(1) if m else key


def updated_sections(text):
    """`Updated-by:` 항목에서 (갱신 번호, 절 키) 목록. 묶음이 없는 갱신은 절 키가 None이다.

    한 묶음의 여러 절은 `, §`·`·§`·`/§`로 나뉜다. `노드 카탈로그/Guard`처럼 `§`가 뒤따르지
    않는 빗금이나 쉼표는 이름의 일부다.
    """
    out = []
    for entry in header_entries(text, "Updated-by"):
        for updater, group in section_groups(entry):
            if group is None:
                out.append((updater, None))
            else:
                out.extend((updater, section_key(name)) for name in SECTION_SEP_RE.split(group))
    return out


def _numbered(named_texts):
    """(파일명, 본문) 쌍에서 {번호: (파일명, 본문)}. 형식 밖 파일명은 건너뛴다."""
    docs = {}
    for name, text in named_texts:
        m = FILENAME_RE.match(name)
        if m:
            docs[m.group(1)] = (name, text)
    return docs


def rule7_violations(named_texts):
    """규칙 7 위반 절. 각 항목은 (대상 번호, 절 키, 열 문서 수, 갱신 번호 튜플), 대상·절 키 순.

    Accepted 대상만 보고, 자기 상태가 Accepted인 갱신만 센다(규칙 6). 절 키가 점 찍힌 번호면
    같은 대상의 상위 번호 절(`2` → `2.1`)을 갱신한 RFC도 센다. 빗금 경로(`노드 카탈로그/Guard`)는
    상위 절을 물려받지 않는다.
    """
    docs = _numbered(named_texts)
    statuses = {number: status_of(text) for number, (_, text) in docs.items()}
    rows = []
    for target in sorted(docs):
        if statuses[target] != "Accepted":
            continue
        by_key = {}
        for updater, key in updated_sections(docs[target][1]):
            if key is None or updater == target or statuses.get(updater) != "Accepted":
                continue
            by_key.setdefault(key, set()).add(updater)
        for key in sorted(by_key):
            updaters = set(by_key[key])
            if NUMBERED_KEY_RE.fullmatch(key):
                for other, more in by_key.items():
                    if (other != key and NUMBERED_KEY_RE.fullmatch(other)
                            and key.startswith(other + ".")):
                        updaters |= more
            documents = 1 + len(updaters)
            if documents > RULE7_LIMIT:
                rows.append((target, key, documents, tuple(sorted(updaters))))
    return rows


def ungrouped_updaters(named_texts):
    """절 이름 묶음 없이 `Updated-by:`에 오른 갱신. 각 항목은 (대상 번호, 갱신 번호), 번호 순.

    Accepted 대상의 Accepted 갱신만 본다 — 규칙 7은 그 갱신을 어느 절에 셀지 알 수 없다.
    """
    docs = _numbered(named_texts)
    statuses = {number: status_of(text) for number, (_, text) in docs.items()}
    pairs = set()
    for target in docs:
        if statuses[target] != "Accepted":
            continue
        for updater, key in updated_sections(docs[target][1]):
            if key is None and updater != target and statuses.get(updater) == "Accepted":
                pairs.add((target, updater))
    return sorted(pairs)


def rule7_check(named_texts):
    """§2.2 규칙 7. 각 항목은 (대상 파일명, 조항, 메시지), 대상 번호 순.

    한 대상 안에서는 절 위반(절 키 순)이 먼저, 묶음 없는 갱신(갱신 번호 순)이 뒤다.
    """
    docs = _numbered(named_texts)
    keyed = []
    for target, key, documents, updaters in rule7_violations(named_texts):
        keyed.append(((target, 0, key), (
            docs[target][0], "§2.2",
            "RFC-%s §%s: 읽으려면 문서 %d개를 열어야 한다(RFC-%s + 갱신 %s) — 규칙 7의 "
            "문턱 %d개를 넘는다. Updates를 더 쌓지 말고 통합 Supersedes를 써라"
            % (target, key, documents, target,
               ", ".join("RFC-" + u for u in updaters), RULE7_LIMIT))))
    for target, updater in ungrouped_updaters(named_texts):
        keyed.append(((target, 1, updater), (
            docs[target][0], "§2.2",
            "RFC-%s 머리의 `Updated-by: RFC-%s`에 절 이름 묶음 `(§…)`이 없다 — 규칙 7이 "
            "그 갱신을 어느 절에 셀지 알 수 없다" % (target, updater))))
    return [finding for _, finding in sorted(keyed)]


# docs/CI-GATES.md 게이트 로스터의 `RFC lint(`rfc_lint.py`)` 행이 main()이 부르는 검사마다
# 지녀야 하는 표기(issue #268 §3). impl/tests/test_rfc_lint.py의 RosterPinTest가 양쪽을
# 대조한다 — main()에 검사를 더하면 여기와 그 행에 표기를 함께 더한다.
ROSTER_TOKENS = {
    "check_numbering": ("§3 번호 중복·공백",),
    "check_document": ("§3 번호·제목", "§2.1 Status 어휘", "§7 템플릿 섹션"),
    "check_changelog_file": ("§2.1 CHANGELOG 인용",),
    "check_back_links": ("§2.2 `Updated-by:` 역링크",),
    "rule7_check": ("§2.2 규칙 7 문서 수",),
}


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
    findings.extend(rule7_check(named))

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

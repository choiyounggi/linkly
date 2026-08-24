#!/usr/bin/env python3
"""플러그인 스킬이 읽을 어휘 문서를 `impl/lnpl/`의 상수에서 생성한다.

정본은 소스다. 이 스크립트의 출력은 산출물이고, 손으로 고치면
`impl/tests/test_plugin_references.py`가 실패한다.

    python scripts/gen_plugin_references.py            # 쓴다
    python scripts/gen_plugin_references.py --check    # 다르면 exit 1
"""
import glob
import inspect
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "impl"))

from lnpl import __version__                                    # noqa: E402
from lnpl.diagnostics import CODES, ENFORCEMENT, SEVERITY_OF     # noqa: E402
from lnpl.lexer import (ARITH_OPS, ASSIGN_KEYWORDS, COMPARATORS,  # noqa: E402
                        DURATION_UNITS, GUARD_ALT_KEYWORD, KEYWORDS_CLAUSE,
                        KEYWORDS_CONTROL, KEYWORDS_TOP, LOGICAL_OPS,
                        PAYLOAD_NAMESPACE, RESERVED, SCHEDULE_AT,
                        SCHEDULE_KEYWORD, SCHEDULE_RECURRENCES, SCHEDULE_ZONES)
from lnpl.lower import (ARGUMENT_MECHANISMS, KIND_PREFIX, KIND_WORD,  # noqa: E402
                        PERF_METRICS, POLICY_NAMES, READ_VERBS,
                        SECURITY_MECHANISMS, VALUELESS_PERF, VERB_LEXICON,
                        derive_id, split_pascal)
from lnpl.refinements import BASE_CATEGORY, CATEGORY_FACETS, PRESETS  # noqa: E402
from lnpl.spec import EXPECTATIONS, GIVEN_FORMS                  # noqa: E402
from lnpl.types import SEMANTIC_TYPES                            # noqa: E402

OUT_DIR = os.path.join(REPO, "plugins", "lnpl", "skills",
                       "lnpl-authoring", "references")

SOURCE_CANON = "impl/lnpl/의 모듈 상수"

BANNER = ("<!-- 생성물 — 손으로 고치지 마라. 정본은 %s이고, "
          "이 파일은 `python scripts/gen_plugin_references.py`의 출력이다. "
          "고치면 impl/tests/test_plugin_references.py가 실패한다. -->\n")


def _doc(title, body, canon=SOURCE_CANON):
    return "%s\n# %s\n\n> lnpl %s 기준.\n\n%s" % (BANNER % canon, title,
                                                 __version__, body)


def render_grammar():
    lines = ["LNPL은 닫힌 키워드 집합을 쓴다. 아래에 없는 키워드는 문법이 아니다.\n"]
    lines.append("## 최상위 선언\n")
    lines.append(" ".join("`%s`" % k for k in KEYWORDS_TOP) + "\n")
    lines.append("## 절(clause)\n")
    lines.append(" ".join("`%s`" % k for k in KEYWORDS_CLAUSE) + "\n")
    lines.append("## 제어 어휘\n")
    lines.append(" ".join("`%s`" % k for k in KEYWORDS_CONTROL) + "\n")
    lines.append("## 예약어 — 사용 불가\n")
    lines.append(" ".join("`%s`" % k for k in RESERVED) + "\n")
    lines.append("이 넷은 **문법적으로 표현 불가능**하다. 쓰면 렉서가 거부한다. "
                 "분기가 필요하면 `when`, 반복이 필요하면 `repeat`/`until`을 쓴다.\n")
    lines.append("## 리터럴\n")
    lines.append("기간 단위: " + " ".join("`%s`" % u for u in DURATION_UNITS))
    lines.append("\n비교 연산자: " + " ".join("`%s`" % c for c in COMPARATORS) + "\n")
    lines.append("## 값 표현식 (RFC-0015)\n")
    lines.append("산술 연산자: " + " ".join("`%s`" % o for o in ARITH_OPS))
    lines.append("\n논리 결합: " + " ".join("`%s`" % o for o in LOGICAL_OPS)
                 + " — `or`·`not`·괄호는 없다.")
    lines.append("\n할당: " + " ".join("`%s`" % k for k in ASSIGN_KEYWORDS)
                 + " (`set <바인딩>.<필드> to <값>`)")
    lines.append("\n입력 네임스페이스: `%s` (`input.quantity` — 실행 payload의 필드)\n"
                 % PAYLOAD_NAMESPACE)
    lines.append("가드 조건은 `<값> <비교연산자> <값>`이고 항은 `and`로만 잇는다. "
                 "값은 참조·정수·기간이며 이항 산술 **1개**까지 붙일 수 있다"
                 "(`product.stock - input.quantity`). 중첩·괄호는 문법에 없다.\n")
    lines.append("## 대안 가드 (RFC-0028)\n")
    lines.append("`when` 뒤에 `%s` 줄을 이어 쓰면 대안 가드다 — 조건이나 그 "
                 "대안 중 하나라도 참이면 피가드 항목을 실행한다"
                 "(`when input.channel == 1` 다음 줄 "
                 "`%s input.amount <= 100`). `%s` 자체는 `Condition` 문법에 "
                 "들어가지 않는다 — 위 절이 말하는 대로 `and`만 여전히 항을 "
                 "잇는다. `until`/`repeat` 뒤에는 쓸 수 없다.\n"
                 % (GUARD_ALT_KEYWORD, GUARD_ALT_KEYWORD, GUARD_ALT_KEYWORD))
    # r3 N-2: the rule existed only in the refusal. `create report` then
    # `set report.orderCount to …` is rejected, and nothing in the references
    # said why — so the author had to reverse-engineer "read-family only" from
    # a diagnostic that additionally called the step a guard condition.
    # `lower.READ_VERBS` rather than a recomputation from `operation`: it is
    # the SAME tuple `_check_scoped_conditions` builds `read_entities` from
    # (RFC-0025 §5/§6.1), so a future verb that changes single-row binding
    # eligibility moves this document instead of quietly making it a lie —
    # which is exactly what happened here once (`list` reused the `query`
    # operation this section used to lump in with `read` via `repo_policy
    # .READ_OPS`, a table this document's own binding rule does not read).
    reads = list(READ_VERBS)
    writes = [v for v, (kind, attrs) in VERB_LEXICON.items()
             if kind == "RepositoryCall"
             and attrs.get("operation") in ("create", "update", "delete")]
    rowset_verbs = [v for v, (kind, attrs) in VERB_LEXICON.items()
                    if kind == "RepositoryCall" and v not in READ_VERBS
                    and attrs.get("operation") not in ("create", "update", "delete")]
    lines.append("## 할당(`set`)의 대상\n")
    lines.append("`set <바인딩>.<필드> to <값>`의 바인딩은 이 워크플로가 **읽은** 행이다. "
                 "스텝이 엔티티를 읽으면 그 행이 실행 스코프에 바인딩되고(RFC-0012), "
                 "`set`은 그렇게 생긴 바인딩에만 쓴다.\n")
    lines.append("읽기 동사: " + " ".join("`%s`" % v for v in reads)
                 + " — 이 동사들만 단일 행 바인딩을 만든다.")
    lines.append("\n바인딩을 만들지 않는 동사: " + " ".join("`%s`" % v for v in writes)
                 + " — 만든 행은 실행 스코프에 들어오지 않는다.\n")
    if rowset_verbs:
        lines.append("행 집합(RowSet) 동사: " + " ".join("`%s`" % v for v in rowset_verbs)
                     + " — 단일 행이 아니라 RowSet을 별개 이름공간에 바인딩한다.")
        lines.append("\n`set`의 대상이 될 수 없다 — 집계 표현식으로만 "
                     "소비된다(RFC-0025 §2/§5).\n")
    lines.append("그래서 `create report` 다음의 `set report.total to 1`은 거부된다.\n")
    lines.append("`input.<필드>`는 할당의 **대상이 될 수 없다** — 입력은 이 워크플로가 "
                 "소유한 상태가 아니다. 값 쪽에는 쓸 수 있다"
                 "(`set product.stock to product.stock - input.quantity`).\n")
    lines.append("고치는 법: 쓰기 전에 그 엔티티를 " + " / ".join("`%s`" % v for v in reads)
                 + " 중 하나로 먼저 읽는다. 읽을 수 없는 엔티티라면 그 값은 이 "
                   "워크플로가 바꿀 수 있는 상태가 아니다.\n")
    lines.append("## 가드의 스코프\n")
    lines.append("가드는 **바로 다음 항목 하나**를 소유한다. 그 항목은 스텝 한 줄이거나 "
                 "`parallel`/`pipeline` 블록 하나다. 뒤따르는 블록 전체를 감싸지 "
                 "**않는다** — 가드 다음 스텝 하나만 조건 아래 들어간다.\n")
    lines.append("```")
    lines.append("when product.stock > 0")
    lines.append("create order          # 가드 안")
    lines.append("update product        # 가드 밖 — 조건과 무관하게 늘 실행된다")
    lines.append("```")
    lines.append("\n두 스텝을 함께 감싸려면 둘 중 하나를 쓴다:\n")
    lines.append("```")
    lines.append("when product.stock > 0    # ① 가드 줄을 스텝마다 반복한다")
    lines.append("create order")
    lines.append("when product.stock > 0")
    lines.append("update product")
    lines.append("```")
    lines.append("```")
    lines.append("when product.stock > 0    # ② 블록으로 묶으면 블록 전체가 가드 안이다")
    lines.append("parallel")
    lines.append("create order")
    lines.append("update product")
    lines.append("merge")
    lines.append("```")
    lines.append("\n가드를 두 줄 잇달아 쓰면 **파싱 에러**다 — 조건 두 개는 `and`로 이어 "
                 "한 가드로 쓴다. 선언이 가드로 끝나도(감쌀 항목이 없어도) 에러다.\n")
    lines.append("가드 조건이 참조하는 필드는 **Integer 또는 DateTime**이어야 한다 — "
                 "존재 검사(`exists`/`missing`)도 마찬가지다. `Text`·`Money` 필드에 "
                 "가드를 걸면 lowering이 거부한다(RFC-0016).\n")
    # r1 N-5: the only block example here was `parallel … merge`, so an author
    # who wrote `pipeline … merge` learned "merge is parallel-only" from a
    # refusal and never learned where a pipeline actually ends.
    closers = [k for k in KEYWORDS_CONTROL if k != "merge"]
    lines.append("\n## 블록의 시작과 종결\n")
    lines.append("블록은 들여쓰기가 아니라 **키워드**로 끝난다(RFC-0002 §Block "
                 "structure). 다만 두 블록의 종결 방식이 서로 다르다.\n")
    lines.append("`parallel`은 `merge`로 닫는다. 닫지 않은 채 선언이 끝나면 거부된다:\n")
    lines.append("```")
    lines.append("declaration Checkout ends with an unclosed `parallel` block "
                 "(missing `merge`)")
    lines.append("```")
    lines.append("\n`pipeline`은 `merge`로 닫지 않는다 — 다음 제어 키워드가 나오거나 "
                 "선언이 끝나는 자리에서 저절로 닫힌다. 사이에 낀 스텝들은 그 "
                 "`pipeline` 안이다.\n")
    lines.append("암묵 종결: " + " ".join("`%s`" % k for k in closers) + "\n")
    lines.append("그래서 `pipeline` 뒤에 `merge`를 쓰면 닫을 `parallel`이 없어 "
                 "거부된다 — 이 문면이 나오면 블록을 잘못 닫은 것이다:\n")
    lines.append("```")
    lines.append("`merge` closes a `parallel` block, but none is open")
    lines.append("```")
    lines.append("\n이름: `pipeline`은 이름을 하나까지 받고(`pipeline enrich`), "
                 "`parallel`은 이름을 받지 않는다.\n")
    lines.append("중첩: 깊이는 2까지다 — `parallel` 안에는 다른 블록도, 가드도 "
                 "들어갈 수 없다(가드를 쓰려면 `merge`로 먼저 닫는다).\n")
    lines.append("```")
    lines.append("pipeline")
    lines.append("find order")
    lines.append("when order.total > 0    <- 여기서 pipeline이 닫힌다")
    lines.append("create order            <- 가드가 소유하는 스텝")
    lines.append("```")
    lines.append("## 이벤트 소스 (RFC-0016)\n")
    lines.append("`event <이름>`은 소스를 붙일 수 있다. 두 형태뿐이다:\n")
    lines.append("- `on <Entity> create|update|delete`")
    lines.append("- `on %s <주기> %s <HH:MM> <존>` — 주기: %s / 존: %s"
                 % (SCHEDULE_KEYWORD, SCHEDULE_AT,
                    " ".join("`%s`" % r for r in SCHEDULE_RECURRENCES),
                    " ".join("`%s`" % z for z in SCHEDULE_ZONES)))
    lines.append("\n예: `event DailyRollup on schedule daily at 00:00 UTC`\n")
    lines.append("스케줄 트리거는 **집행되지 않는다** — IR과 OpenAPI의 "
                 "`x-lnpl-schedules`까지만 도달하고 실행기는 없다. 선언하면 "
                 "`declared-not-enforced` 진단이 나온다(집행 매트릭스 참조).\n")
    lines.append("들여쓰기는 의미가 없다(4칸은 스타일 규약일 뿐). 블록은 키워드로 "
                 "구분된다 — 그래서 괄호 짝이나 들여쓰기 오류가 문법적으로 "
                 "표현되지 않는다.\n")
    return _doc("문법 — 키워드와 예약어", "\n".join(lines))


def render_verbs():
    lines = ["워크플로 스텝의 **첫 낱말**이 동사다. 아래 표에 없는 동사는 "
             "에러가 아니라 **효과 없는 no-op**으로 실행된다 — 파일은 컴파일되고, "
             "런타임은 아무것도 하지 않는다(issue #36). 진단 코드 "
             "`unknown-verb`가 그때 발생한다.\n",
             "| 동사 | 파생되는 Effect | 속성 |",
             "|------|-----------------|------|"]
    for verb, (effect, attrs) in VERB_LEXICON.items():
        attr = ", ".join("%s=%s" % (k, v) for k, v in attrs.items()) or "—"
        lines.append("| `%s` | `%s` | %s |" % (verb, effect, attr))
    lines.append("\n`return`, `log`, `send`, `notify`, `verify` 같은 낱말은 "
                 "이 표에 **없다**. 자연스러워 보여도 아무 효과가 없다.\n")
    lines.append("`create`가 언제 충돌하고 그 충돌을 spec으로 어디까지 계약할 수 "
                 "있는지는 [spec.md](spec.md)의 \"저장소 시드와 `create` 충돌\"에 "
                 "있다. `set`의 대상이 될 수 있는 바인딩을 어떤 동사가 만드는지는 "
                 "[grammar.md](grammar.md)의 \"할당(`set`)의 대상\"에 있다.\n")
    return _doc("동사 어휘 (VERB_LEXICON)", "\n".join(lines))


def render_declarations():
    lines = ["선언했다고 집행되는 것이 아니다. 아래 표가 정본이다 — "
             "`enforced`만 실행을 바꾼다. `measured`는 관측·보고하되 막지 않고, "
             "`unenforced`는 런타임이 완전히 무시한다(issue #38).\n",
             "## 절별 허용 이름\n",
             "- `policy`: " + " ".join("`%s`" % n for n in POLICY_NAMES),
             "- `security`: " + " ".join("`%s`" % n for n in SECURITY_MECHANISMS),
             "- `performance`: " + " ".join("`%s`" % n for n in PERF_METRICS),
             "",
             "인자를 받는 security 기제: " +
             (" ".join("`%s`" % n for n in ARGUMENT_MECHANISMS) or "—"),
             "값 없이 쓰는 performance 지표: " +
             (" ".join("`%s`" % n for n in VALUELESS_PERF) or "—"),
             "",
             "## 집행 매트릭스\n",
             "| 선언 | 상태 | 런타임이 실제로 하는 일 |",
             "|------|------|--------------------------|"]
    for (clause, name), (status, why) in ENFORCEMENT.items():
        lines.append("| `%s %s` | **%s** | %s |" % (clause, name, status, why))
    lines.append("\n## 진단 코드\n")
    lines.append("등급은 `--strict[=LEVEL]`이 무엇을 게이팅하는지를 정한다"
                 "(RFC-0021). `warning`은 프로그램을 고치면 사라지는 것이고, "
                 "`info`는 고쳐도 사라지지 않는 플랫폼 상태의 진술이다.\n")
    lines.append("| 코드 | 등급 |")
    lines.append("|------|------|")
    for code in CODES:
        lines.append("| `%s` | **%s** |" % (code, SEVERITY_OF[code]))
    lines.append("")
    return _doc("선언과 집행 (ENFORCEMENT)", "\n".join(lines))


def render_types():
    lines = ["## 의미 타입\n",
             "필드 타입은 아래 집합에서 고른다.\n",
             "| 타입 | 예시 값 |",
             "|------|---------|"]
    for name, meta in SEMANTIC_TYPES.items():
        lines.append("| `%s` | `%s` |" % (name, meta["sample"]))
    lines.append("\n## Refinement 프리셋\n")
    lines.append("선언 없이 바로 쓰면 emit-on-use로 문서에 실린다.\n")
    lines.append("| 프리셋 | base | facet |")
    lines.append("|--------|------|-------|")
    for name, spec in PRESETS.items():
        facets = ", ".join("%s=%s" % (k, v) for k, v in sorted(spec["facets"].items()))
        lines.append("| `%s` | `%s` | %s |" % (name, spec["base"], facets))
    lines.append("\n## 직접 선언하는 refinement\n")
    lines.append("`refine <PascalName> of <base>` 뒤에 facet을 둔다. "
                 "base별로 허용되는 facet이 다르다.\n")
    lines.append("| base | 허용 facet |")
    lines.append("|------|------------|")
    for base in BASE_CATEGORY:
        facets = CATEGORY_FACETS[BASE_CATEGORY[base]]
        lines.append("| `%s` | %s |" %
                     (base, " ".join("`%s`" % f for f in sorted(facets)) or "—"))
    lines.append("")
    return _doc("타입과 Refinement", "\n".join(lines))


def _expect_format_cell(key, handler):
    """`EXPECTATIONS[key]`의 docstring 첫 문단을 표 한 칸으로 만든다.

    첫 문단이 없거나(docstring 결손) 백틱 형식 시그니처가 하나도 없으면
    fail-closed로 거부한다 — 새 expect 키가 문서화 없이 조용히 통과하는
    것을 issue #61이 막으려는 바로 그 구멍이다.
    """
    doc = inspect.getdoc(handler)
    if not doc:
        raise RuntimeError(
            "expect key %r (%s)에 docstring이 없다 — references/spec.md에 "
            "실리려면 형식 시그니처를 담은 docstring이 필요하다" % (key, handler.__name__))
    first_para = doc.split("\n\n", 1)[0]
    cell = " ".join(line.strip() for line in first_para.splitlines())
    if "`" not in cell:
        raise RuntimeError(
            "expect key %r (%s)의 docstring 첫 문단에 백틱 형식 시그니처가 "
            "없다 — references/spec.md에 실리려면 필요하다" % (key, handler.__name__))
    return cell.replace("|", "\\|")


def _effects_opt_in_note():
    """`_expect_effects` docstring에서 opt-in 근거 문단만 뽑아 인용한다."""
    doc = inspect.getdoc(EXPECTATIONS["effects"])
    for para in doc.split("\n\n"):
        if para.startswith("It is opt-in rather than"):
            return " ".join(line.strip() for line in para.splitlines())
    raise RuntimeError(
        "`_expect_effects`의 docstring에서 opt-in 근거 문단을 찾지 못했다 — "
        "render_spec()의 인용 로직이나 docstring 둘 중 하나가 어긋났다")


def render_spec():
    lines = ["워크플로 안의 `spec` 블록은 `given` / `when` / `expect` 세 절을 갖는다.",
             "워크플로당 블록 여러 개를 선언할 수 있고 블록마다 독립 케이스 하나가 된다 —",
             "정상/에러/경계 시나리오는 블록을 나눠 쓴다. 한 블록 안에서 같은 절을 두 번",
             "열면 파싱 에러다 (issue #46).\n",
             "## `expect`가 받는 키\n",
             "| 키 | 형식·의미 |",
             "|------|-----------|"]
    for key, handler in EXPECTATIONS.items():
        lines.append("| `%s` | %s |" % (key, _expect_format_cell(key, handler)))
    lines.append("\n> " + _effects_opt_in_note())
    lines.append("\n## `given`이 알아듣는 형식\n")
    for _key, form, doc in GIVEN_FORMS:
        lines.append("- `%s` — %s" % (form, doc))
    lines.append("\n선언되지 않은 이름을 쓰면 거부된다 — `--run` 없이 `lnpl spec`만 "
                 "돌려도 매니페스트 단계에서 거부되고, 진단이 어느 워크플로의 어느 "
                 "블록인지와 수용되는 이름 전체를 댄다 (issue #54).\n")
    lines.append("\n## 입력 네임스페이스\n")
    lines.append("필드 형식은 **선언된 전 엔티티 필드의 합집합**에서 이름을 찾는다 "
                 "(RFC-0015 §G15.2). 맨이름과 `input.<field>`는 같은 것을 가리키며, "
                 "새로 쓰는 spec은 `input.`을 쓴다.\n")
    lines.append("단, 기본 payload는 그 합집합이 아니다 — 첫 엔티티와 `validate`가 "
                 "지목한 엔티티의 필드만 샘플로 채운다 (issue #48: 전 엔티티를 채우면 "
                 "다른 엔티티의 부재 필드를 읽는 Presence 가드가 뒤집힌다). 그래서 그 "
                 "밖의 입력 필드는 `input.<field> <value>`로 **명시해야** 하고, "
                 "read-행 참조 가드를 참으로 만드는 정상 경로도 그렇게 계약화한다 "
                 "(issue #54).\n")
    lines.append("\n## `given no`의 스코프\n")
    lines.append("- 입력 payload에서 그 필드를 뺀다")
    lines.append("- 기본 시드 행은 그 payload의 복사본이므로, 그 행에서도 사라진다")
    lines.append("- `stored`는 시드 이후에 덮어쓰므로 `no`보다 뒤에 적용된다 — "
                 "둘을 같이 쓰면 `stored`가 이긴다")
    lines.append("- 이미 없는 필드를 빼는 것은 부재를 단언하는 no-op이며 에러가 아니다 "
                 "— `when <field> missing` 같은 Presence 가드가 계약하는 상태다\n")

    # r2 N-3: `given stored Payment id <the same uuid>` then `create payment`
    # finished `completed`, and neither the output nor any document said whether
    # that was an upsert, a different key, or a seed that never happened. It was
    # the third: the seed rule leaves a create-only entity empty, so `stored`
    # has no row to write into. Recording that honestly — including that the
    # scenario is NOT expressible — is the whole point; claiming otherwise would
    # be the over-promise this run is trying to stop repeating.
    lines.append("\n## 저장소 시드와 `create` 충돌\n")
    lines.append("`create`는 같은 키의 행이 이미 있으면 실패한다. 행은 엔티티마다 "
                 "`<entity_id>#<payload의 id 또는 '-'>` 키 아래 사니까, 충돌은 "
                 "엔티티 단위가 아니라 **(엔티티, 키)** 단위다.\n")
    lines.append("그런데 기본 시드는 이 워크플로가 읽는 엔티티만 채운다. "
                 "`create`만 하고 읽지 않는 엔티티는 빈 채로 시작하므로 첫 "
                 "`create`는 늘 삽입된다.\n")
    lines.append("`stored <엔티티> <필드> <값>`은 **이미 시드된 행의 필드를 "
                 "덮어쓸 뿐**이다. 읽지 않는 엔티티에는 행을 만들지 않고, 그 사실을 "
                 "알리는 진단도 없다 — 조용히 무시된다.\n")
    lines.append("그래서 \"사전 행이 있어서 `create`가 충돌한다\"는 시나리오는 "
                 "`given`으로 **세울 수 없다**. 표현 수단이 없어서가 아니라 시드 "
                 "규칙이 그 행을 만들지 않기 때문이다.\n")
    lines.append("충돌은 그 키에 **이미 행이 있을 때** 난다. 실행 중에 행이 생기는 "
                 "경로는 둘이다 — 그래서 관측 가능한 형태도 그 둘이다:\n")
    lines.append("- **시드** — 이 워크플로가 그 엔티티를 읽는다. 읽는 엔티티는 "
                 "payload의 복사본으로 채워지므로, `find order` 다음의 "
                 "`create order`는 충돌한다.")
    lines.append("- **앞선 `create`** — 같은 실행에서 그 엔티티를 이미 만들었다. "
                 "`create order`를 두 번 쓰면 두 번째가 충돌한다.\n")
    lines.append("둘 다 같은 실패로 끝나고, 그 실패는 spec으로 계약할 수 있다:\n")
    lines.append("```")
    lines.append("expect")
    lines.append("    failed")
    lines.append("    error reason conflicts")
    lines.append("```")
    lines.append("\n그때 run의 `failure_reason`은 이렇게 된다:\n")
    lines.append("```")
    lines.append("repository create conflicts: entity.order already exists")
    lines.append("```")
    lines.append("\n읽기가 실패하는 에러 경로를 계약하고 싶으면 `empty repository`를 "
                 "쓴다 — 시드가 없으니 `find`/`load`가 행을 못 찾고 그 스텝이 "
                 "실패한다.\n")
    lines.append("이 \"엔티티당 행 하나\" 불변식이 어디서 오는지는 "
                 "`rfcs/0015-value-semantics.md` §Alternatives에 있다: 한 실행은 "
                 "payload 하나를 가지므로 엔티티 E의 테이블에는 행이 최대 하나다.\n")
    return _doc("spec 블록", "\n".join(lines))


# One sample declaration name per kind. The id column beside each is NOT written
# out — it is `derive_id()` called at render time, so a change to the derivation
# rule moves this document instead of silently making it a lie (issue #50).
SAMPLE_NAMES = {
    "Entity": "DailyReport",
    "Service": "LoginService",
    "Workflow": "GetReport",
    "Event": "UserCreated",
    "Capability": "Postgres",
    "Refinement": "ClickCount",
    "Policy": "Retry",
    "Security": "Jwt",
    "Performance": "Response",
}

# What a step writes to name each sample entity: the same derivation the lowerer
# compares against (`lower._resolve_entity`), computed rather than transcribed.
def _object_form(name):
    return "".join(split_pascal(name))


def render_naming():
    entity = SAMPLE_NAMES["Entity"]
    obj = _object_form(entity)
    wf = SAMPLE_NAMES["Workflow"]
    lines = ["선언에 붙인 이름은 곧 **노드 id**가 되고, 스텝이 엔티티를 가리킬 때 쓰는 "
             "철자도 그 규칙에서 나온다. 둘 다 기계적이고, 둘 다 틀리면 조용히 "
             "실패하지 않고 **컴파일이 거부한다** — 다만 에러가 이유를 말해주지 "
             "않아서 규칙을 모르면 빠져나올 수 없다(이슈 #50).\n"]

    lines.append("## 선언명 → 노드 id\n")
    lines.append("| kind | 접두사 | 예 |")
    lines.append("|------|--------|-----|")
    for kind, prefix in KIND_PREFIX.items():
        sample = SAMPLE_NAMES[kind]
        lines.append("| `%s` | `%s` | `%s` → `%s` |"
                     % (kind, prefix, sample, derive_id(sample, kind)))
    lines.append("\nPascalCase는 낱말마다 점으로 끊긴다. 대문자 연속은 한 낱말이고"
                 "(`APIKey` → `api.key`), 숫자는 앞 낱말에 붙는다.\n")

    lines.append("## 후행 kind 낱말은 지워진다\n")
    lines.append("이름의 **마지막** 낱말이 kind와 같으면 중복이므로 제거된다. "
                 "해당 kind는 " + " ".join("`%s`" % k for k in KIND_WORD) + "다.\n")
    lines.append("- `%s` → `%s` (후행 `Workflow`가 지워진다)"
                 % ("ProbeWorkflow", derive_id("ProbeWorkflow", "Workflow")))
    lines.append("- `%s` → `%s` (선행은 지워지지 않는다)"
                 % ("WorkflowProbe", derive_id("WorkflowProbe", "Workflow")))
    lines.append("")

    lines.append("## 스텝 객체로 엔티티를 가리키는 법\n")
    lines.append("스텝의 두 번째 낱말(객체)은 **선언명이 아니라 그 소문자 연결형**이다 "
                 "— PascalCase의 낱말 경계를 지우고 전부 소문자로 내린 형태다. "
                 "`entity %s`를 가리키려면 `%s`라고 쓴다.\n" % (entity, obj))
    lines.append("| 스텝에 쓴 것 | 결과 |")
    lines.append("|--------------|------|")
    lines.append("| `validate %s` | **해석된다** — 소문자 연결형 |" % obj)
    lines.append("| `validate %s` | 거부 — camelCase는 이 규칙이 아니다 |"
                 % (entity[0].lower() + entity[1:]))
    lines.append("| `validate %s` | 거부 (엔티티를 둘 이상 선언했을 때) — 선언과 같은 "
                 "표기여도 안 된다; 하나뿐이면 대신 `unknown-entity` 경고로 컴파일된다 "
                 "(아래 참조) |" % entity)
    lines.append("| `validate %ss` | 거부 — 복수형을 단수로 되돌리지 않는다 |" % obj)
    lines.append("| `validate order` | 해석된다 — `entity Order`의 소문자 연결형 |")
    lines.append("\n두 가지 예외가 있다:\n")
    lines.append("- 모듈이 엔티티를 **정확히 하나** 선언하면 객체를 생략할 수 있다.")
    lines.append("- 객체가 어떤 엔티티의 **필드명**과 같으면 그 엔티티로 해석된다.\n")

    lines.append("## 선언되지 않은 명사를 쓰면 — `unknown-entity`\n")
    lines.append("스텝 객체가 위 표의 어느 형태로도 매칭되지 않을 때, 모듈이 엔티티를 "
                 "**정확히 하나** 선언했으면 컴파일은 계속된다 — `_resolve_entity`가 "
                 "그 하나를 그대로 쓴다(런타임 동작은 바뀌지 않는다, 이슈 #91 §4). "
                 "대신 `unknown-verb`(#36→#82)와 대칭인 `unknown-entity` "
                 "**warning** 진단이 하나 실린다:\n")
    lines.append("```")
    lines.append("warning: unknown-entity [line 8] find user — 'user' names no "
                 "declared entity; declared: customer — did you mean 'customer'?")
    lines.append("```")
    lines.append("\n형식은 `unknown-verb`가 확정한 구조 그대로다 — 구조화 `line`, "
                 "did-you-mean 제안(RFC-0026). 엔티티가 **하나뿐이면** 제안은 늘 "
                 "그 하나다. `--strict=warning`으로 게이트할 수 있다(RFC-0021). "
                 "엔티티를 둘 이상 선언한 모듈에서 객체가 매칭에 실패하면 이 진단이 "
                 "아니라 바로 아래의 모호성 에러가 난다 — 그 경로는 이미 조용하지 "
                 "않으므로 이슈 #91의 범위가 아니다. `<명사>.<필드>` Reference의 "
                 "명사부(가드·`set` 대상)는 이 진단의 범위가 아니다 — 선언되지 않은 "
                 "바인딩을 쓰면 이미 컴파일 에러이므로(#45), 무진단으로 통과하는 "
                 "구멍이 없다.\n")

    lines.append("## 이 에러가 나면\n")
    lines.append("```")
    lines.append("`validate %s` does not say which entity it means, and this "
                 "module declares 2 (...)." % entity)
    lines.append("Name the entity as the step's object.")
    lines.append("```")
    lines.append("\n지시를 그대로 따라 **정확한 선언명**을 써도 같은 에러가 반복된다. "
                 "이 에러가 말하는 \"the entity as the step's object\"는 이 언어에서 "
                 "`%s`를 뜻한다 — 위 표의 소문자 연결형이다. 다단어 엔티티를 쓸 "
                 "거면 그 연결형이 읽히는지 먼저 확인하라.\n" % obj)

    lines.append("## `--workflow`가 요구하는 것\n")
    lines.append("CLI의 `--workflow`는 **선언명이 아니라 노드 id**를 받는다. "
                 "`workflow %s`를 지정하려면 `--workflow %s`라고 쓴다. "
                 "잘못된 id를 주면 유효한 id 전부가 에러에 나열된다.\n"
                 % (wf, derive_id(wf, "Workflow")))
    return _doc("이름과 참조 — 선언명·노드 id·스텝 객체", "\n".join(lines))


RFC_DIR = os.path.join(REPO, "rfcs")

# Which authoring question sends you to which RFC, and — where the answer is one
# section rather than the whole document — the heading lines that hold it.
#
# The questions are curated: a mechanical scan of `rfcs/` can list the documents
# but cannot say which one answers "why can I not sum these rows", and that gap
# is exactly what the re-measurement found (r2 N-4, r3 §D12: zero pointers from
# the authoring surface to the aggregation roadmap). What is NOT curated is anything a
# machine can check — the titles, the paths, and the existence of every heading
# named here are resolved at render time, so a route that stops being true stops
# the generator instead of quietly misdirecting an author.
#
# A process RFC that no authoring question reaches carries the sentinel `—`
# rather than an empty cell: "no route" and "nobody wrote one yet" have to stay
# distinguishable.
SENTINEL = "—"

RFC_ROUTES = {
    "0000": (SENTINEL, ()),
    "0001": ("컴파일 산출물(IR)의 노드가 어떻게 생겼는지 읽어야 한다", ()),
    "0002": ("문법 생산규칙 전체와 문법에서 IR로 내려가는 대응이 궁금하다", ()),
    "0003": ("실행기가 정책·동시성·관측을 어떻게 다루는지", ()),
    "0004": ("mode B(MLIR/LLVM)가 무엇을 관측하고 어디까지 내려가는지", ()),
    "0005": ("kb 라우팅이 어떤 카테고리로 나뉘는지", ()),
    "0006": ("에이전트 역할과 JSON-RPC 메서드", ()),
    "0007": (SENTINEL, ()),
    "0008": ("가드 조건의 두 형태(존재 검사·비교)가 각각 무엇을 받는지", ()),
    "0009": ("가드 문법의 미결 질문이 왜 닫혔는지", ()),
    "0010": ("에이전트가 자기 소유가 아닌 노드를 어떻게 붙이는지", ()),
    "0011": ("refinement 이름이 어디까지 합법이고 충돌하면 어떻게 되는지", ()),
    "0012": ("가드가 무엇을 이름 지을 수 있는지, 스텝 결과가 다음 스텝에 "
             "어떻게 바인딩되는지 — `set` 대상 규칙의 정본", ()),
    "0013": ("retry 예산을 잃어도 왜 무한 루프가 되지 않는지", ()),
    "0014": ("스킵된 스텝이 완료로 보이지 않게 하는 계약", ()),
    "0015": ("값 표현식과 산술, 그리고 집계(`sum`/`count`)가 왜 아직 없고 "
             "로드맵이 어디 있는지 — §Alternatives",
             ("## Alternatives",
              "### 집계(`sum`/`count`)를 이번 개정에 넣지 않는 이유")),
    "0016": ("기간·시각을 비교하거나 스케줄로 트리거하고 싶다", ()),
    "0017": ("동봉된 `guarded.lnpl` 예제가 왜 그렇게 고쳐졌는지", ()),
    "0018": ("`repeat`/`until`의 반복이 관측에서 어떻게 접히는지", ()),
    "0019": ("들여쓰기가 의미 없다면서 왜 어떤 들여쓰기는 거부되는지", ()),
    "0020": ("spec의 `given`에서 입력 필드를 어떻게 지목하는지", ()),
    "0021": ("`--strict`가 무엇을 게이팅하는지, 진단 등급이 무엇인지", ()),
    "0022": ("mode B가 스킵과 `--field`를 어떻게 드러내는지", ()),
    "0023": ("가드 뒤의 스텝이 왜 가드 밖인지, 그리고 컴파일러가 그걸 언제 "
             "경고하는지", ()),
    "0024": ("집행 진단이 노드 id에 더해 소스 line을 왜, 어떻게 싣는지 — "
             "`lnpl compile`과 `lnpl run`이 나눠 가진 진단 범위도 함께", ()),
    "0025": ("`list`로 엔티티의 전 행을 읽고 `sum`/`count`로 집계하고 싶다 — "
             "RowSet이 단일 행 바인딩과 왜 별개 이름공간인지, mode B가 왜 "
             "집계 값을 전혀 계산하지 않는지", ()),
    "0026": ("`unknown-verb`/`guard-orphaned-steps`가 왜 구조화 `line`을 갖는지, "
             "did-you-mean 제안이 별칭과 철자 오타를 어떻게 나눠 잡는지", ()),
    "0027": ("`call`/`request ... as <name>`로 네트워크 응답을 바인딩하고 "
             "실패를 status 값으로 분기하고 싶다 — `--network`의 fake/http "
             "선택이 무엇을 고르는지, 접속 실패가 왜 예외가 아니라 값인지", ()),
    "0028": ("`*`/`/`를 쓰고 싶다, 또는 `when A` / `or B`로 대안 가드를 쓰고 "
             "싶다 — 0 나눗셈이 왜 컴파일 에러가 아니라 RunError인지, mode B가 "
             "왜 그 실패에 합의할 의무가 없는지", ()),
    "0029": ("`CacheAccess` TTL을 벽시계 경과에 묶고 싶다 — `--clock real`이 "
             "무엇을 바꾸고 무엇을 바꾸지 않는지, `diff`/`spec`이 왜 이 "
             "선택자를 받지 않는지", ()),
}

TITLE_RE = re.compile(r"^# RFC-(\d{4}): (.+)$")


def render_rfcs():
    """RFC 포인터 표. 큐레이션된 질문 + 렌더 시점에 해석되는 사실.

    이 렌더러는 조용히 성공하지 않는다. 라우트와 `rfcs/`가 어긋나거나, 제목을
    못 읽거나, 지목한 절이 그 문서에 없으면 `RuntimeError`로 생성을 세운다 —
    닿지 않는 포인터는 없는 포인터보다 나쁘고, 그 상태로 커밋되면 저자는
    "여기 있다"는 말을 믿고 헤맨다.
    """
    paths = {os.path.basename(p)[:4]: p
             for p in glob.glob(os.path.join(RFC_DIR, "[0-9][0-9][0-9][0-9]-*.md"))}
    if len(paths) < 20:
        raise RuntimeError(
            "RFC 문서를 %d건만 찾았다 — rfcs/ 경로(%s)가 맞는지 확인하라. "
            "소스 목록이 비면 아래 집합 비교가 무엇과도 성립해서 커버리지가 "
            "헛되이 통과한다." % (len(paths), RFC_DIR))

    unrouted = sorted(set(paths) - set(RFC_ROUTES))
    dangling = sorted(set(RFC_ROUTES) - set(paths))
    if unrouted or dangling:
        raise RuntimeError(
            "RFC_ROUTES가 rfcs/와 어긋난다 — 라우트 없는 RFC: %s / 문서 없는 "
            "라우트: %s. 새 RFC가 생기면 여기에 질문 한 줄을 더해야 한다."
            % (", ".join(unrouted) or "없음", ", ".join(dangling) or "없음"))

    # No count of the sibling references here ("옆의 다섯 참조"): the set grows,
    # and a number baked into prose is the drift this whole file exists to stop
    # — `AGENTS.md` still says five when there are more.
    lines = ["`.lnpl`을 쓰다 막혔을 때 **어느 RFC를 열지**만 답하는 표다. "
             "규칙의 정본은 이 디렉터리의 다른 참조들이고, RFC는 그 규칙이 **왜 그런지**와 "
             "**아직 없는 것의 로드맵**을 갖는다. 아직 없는 어휘를 만났을 때 "
             "(`sum`/`count` 같은) \"없다\"에서 멈추지 않으려면 여기를 본다.\n",
             "경로는 레포 루트 기준이다.\n",
             "| RFC | 이 질문이면 여기 | 경로 |",
             "|-----|------------------|------|"]

    for number in sorted(paths):
        path = paths[number]
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        match = TITLE_RE.match(text.split("\n", 1)[0])
        if match is None or match.group(1) != number:
            raise RuntimeError(
                "%s의 첫 줄에서 `# RFC-%s: <제목>`을 읽지 못했다 — 제목 형식이 "
                "바뀌었으면 이 렌더러도 같이 고쳐야 한다"
                % (os.path.basename(path), number))
        question, anchors = RFC_ROUTES[number]
        body = text.split("\n")
        for anchor in anchors:
            if anchor not in body:
                raise RuntimeError(
                    "RFC-%s에 %r 절이 없다 — 포인터가 가리키는 곳이 사라졌다"
                    % (number, anchor))
        lines.append("| RFC-%s %s | %s | `%s` |"
                     % (number, match.group(2), question,
                        os.path.relpath(path, REPO)))

    lines.append("")
    lines.append("Accepted RFC는 직접 편집하지 않는다 — 개정 절차는 "
                 "`rfcs/0007-rfc-process-v2.md`에 있다.\n")
    return _doc("RFC 포인터 — 규칙의 근거와 로드맵", "\n".join(lines),
                canon="rfcs/와 이 스크립트의 RFC_ROUTES")


RENDERERS = {
    "rfcs.md": render_rfcs,
    "grammar.md": render_grammar,
    "naming.md": render_naming,
    "verbs.md": render_verbs,
    "declarations.md": render_declarations,
    "types.md": render_types,
    "spec.md": render_spec,
}


def render_all():
    return {name: fn() for name, fn in RENDERERS.items()}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    check = "--check" in argv
    rendered = render_all()
    if not check:
        os.makedirs(OUT_DIR, exist_ok=True)
    stale = []
    for name, text in rendered.items():
        path = os.path.join(OUT_DIR, name)
        if check:
            try:
                with open(path, encoding="utf-8") as fh:
                    current = fh.read()
            except FileNotFoundError:
                stale.append("%s: 없음" % name)
                continue
            if current != text:
                stale.append("%s: 소스와 다름" % name)
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
    if check:
        if stale:
            for line in stale:
                print(line, file=sys.stderr)
            print("`python scripts/gen_plugin_references.py`로 재생성하라.",
                  file=sys.stderr)
            return 1
        return 0
    print("wrote %d files to %s" % (len(rendered), OUT_DIR))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""플러그인 스킬이 읽을 어휘 문서를 `impl/lnpl/`의 상수에서 생성한다.

정본은 소스다. 이 스크립트의 출력은 산출물이고, 손으로 고치면
`impl/tests/test_plugin_references.py`가 실패한다.

    python scripts/gen_plugin_references.py            # 쓴다
    python scripts/gen_plugin_references.py --check    # 다르면 exit 1
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "impl"))

from lnpl import __version__                                    # noqa: E402
from lnpl.diagnostics import CODES, ENFORCEMENT, SEVERITY_OF     # noqa: E402
from lnpl.lexer import (ARITH_OPS, ASSIGN_KEYWORDS, COMPARATORS,  # noqa: E402
                        DURATION_UNITS, KEYWORDS_CLAUSE, KEYWORDS_CONTROL,
                        KEYWORDS_TOP, LOGICAL_OPS, PAYLOAD_NAMESPACE, RESERVED,
                        SCHEDULE_AT, SCHEDULE_KEYWORD, SCHEDULE_RECURRENCES,
                        SCHEDULE_ZONES)
from lnpl.lower import (ARGUMENT_MECHANISMS, KIND_PREFIX, KIND_WORD,  # noqa: E402
                        PERF_METRICS, POLICY_NAMES, SECURITY_MECHANISMS,
                        VALUELESS_PERF, VERB_LEXICON, derive_id, split_pascal)
from lnpl.refinements import BASE_CATEGORY, CATEGORY_FACETS, PRESETS  # noqa: E402
from lnpl.spec import EXPECTATIONS                               # noqa: E402
from lnpl.types import SEMANTIC_TYPES                            # noqa: E402

OUT_DIR = os.path.join(REPO, "plugins", "lnpl", "skills",
                       "lnpl-authoring", "references")

BANNER = ("<!-- 생성물 — 손으로 고치지 마라. 정본은 impl/lnpl/의 모듈 상수이고, "
          "이 파일은 `python scripts/gen_plugin_references.py`의 출력이다. "
          "고치면 impl/tests/test_plugin_references.py가 실패한다. -->\n")


def _doc(title, body):
    return "%s\n# %s\n\n> lnpl %s 기준.\n\n%s" % (BANNER, title, __version__, body)


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


def render_spec():
    lines = ["워크플로 안의 `spec` 블록은 `given` / `when` / `expect` 세 절을 갖는다.",
             "워크플로당 블록 여러 개를 선언할 수 있고 블록마다 독립 케이스 하나가 된다 —",
             "정상/에러/경계 시나리오는 블록을 나눠 쓴다. 한 블록 안에서 같은 절을 두 번",
             "열면 파싱 에러다 (issue #46).\n",
             "## `expect`가 받는 키\n"]
    for key in EXPECTATIONS:
        lines.append("- `%s`" % key)
    lines.append("\n## `given`이 알아듣는 형식\n")
    lines.append("- `valid <아무 명사>` — 서사용 표지, 필드에 영향 없음")
    lines.append("- `empty repository` — 빈 저장소로 실행")
    lines.append("- `<field> <value>` — 선언된 필드를 설정. 기본 payload(샘플 값) 위에 "
                 "필드 단위로 덮어쓰며, Integer 계열 필드는 int로 변환된다 (issue #46)")
    lines.append("- `no <field>` — 선언된 필드를 뺌")
    lines.append("- `stored <entity> <field> <value>` — 사전 저장소 상태 (issue #39). "
                 "엔티티는 선언명(`Product`)과 바인딩명(`product`) 둘 다 받는다 (issue #46)")
    lines.append("\n선언되지 않은 필드를 쓰면 거부된다.\n")
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
    lines.append("| `validate %s` | 거부 — 선언과 같은 표기여도 안 된다 |" % entity)
    lines.append("| `validate %ss` | 거부 — 복수형을 단수로 되돌리지 않는다 |" % obj)
    lines.append("| `validate order` | 해석된다 — `entity Order`의 소문자 연결형 |")
    lines.append("\n두 가지 예외가 있다:\n")
    lines.append("- 모듈이 엔티티를 **정확히 하나** 선언하면 객체를 생략할 수 있다.")
    lines.append("- 객체가 어떤 엔티티의 **필드명**과 같으면 그 엔티티로 해석된다.\n")

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


RENDERERS = {
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

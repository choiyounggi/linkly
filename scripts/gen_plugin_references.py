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
from lnpl.diagnostics import CODES, ENFORCEMENT                  # noqa: E402
from lnpl.lexer import (COMPARATORS, DURATION_UNITS, KEYWORDS_CLAUSE,  # noqa: E402
                        KEYWORDS_CONTROL, KEYWORDS_TOP, RESERVED)
from lnpl.lower import (ARGUMENT_MECHANISMS, PERF_METRICS, POLICY_NAMES,  # noqa: E402
                        SECURITY_MECHANISMS, VALUELESS_PERF, VERB_LEXICON)
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
    for code in CODES:
        lines.append("- `%s`" % code)
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
    lines = ["워크플로 안의 `spec` 블록은 `given` / `when` / `expect` 세 절을 갖는다.\n",
             "## `expect`가 받는 키\n"]
    for key in EXPECTATIONS:
        lines.append("- `%s`" % key)
    lines.append("\n## `given`이 알아듣는 형식\n")
    lines.append("- `valid <아무 명사>` — 서사용 표지, 필드에 영향 없음")
    lines.append("- `empty repository` — 빈 저장소로 실행")
    lines.append("- `<field> <value>` — 선언된 필드를 설정")
    lines.append("- `no <field>` — 선언된 필드를 뺌")
    lines.append("- `stored <entity> <field> <value>` — 사전 저장소 상태 (issue #39)")
    lines.append("\n선언되지 않은 필드를 쓰면 거부된다.\n")
    return _doc("spec 블록", "\n".join(lines))


RENDERERS = {
    "grammar.md": render_grammar,
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

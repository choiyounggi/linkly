# Task 03: 어휘 레퍼런스를 소스에서 생성하고 drift를 테스트로 막는다

> 실행자에게: 이 태스크는 `superpowers:subagent-driven-development` 또는
> `superpowers:executing-plans`로 수행한다. 각 Step은 체크박스 단위다.

## Objective
스킬이 읽을 어휘 문서 5종을 `impl/lnpl/`의 모듈 상수에서 **생성**하고, 손으로 고치면
테스트가 RED가 되게 한다.

이게 없으면 플러그인은 문제를 고치는 게 아니라 **틀린 어휘를 권위 있게 가르치는**
물건이 된다(A3). 정본은 언제나 소스 코드다.

## Files
- Create: `scripts/gen_plugin_references.py`
- Create: `impl/tests/test_plugin_references.py`
- Create(생성물): `plugins/lnpl/skills/lnpl-authoring/references/grammar.md`
- Create(생성물): `plugins/lnpl/skills/lnpl-authoring/references/verbs.md`
- Create(생성물): `plugins/lnpl/skills/lnpl-authoring/references/declarations.md`
- Create(생성물): `plugins/lnpl/skills/lnpl-authoring/references/types.md`
- Create(생성물): `plugins/lnpl/skills/lnpl-authoring/references/spec.md`

## Interfaces
- Consumes: 없음 (Task 01·02와 병렬 가능)
- Produces:
  - `python scripts/gen_plugin_references.py` — 5개 파일을 쓴다
  - `python scripts/gen_plugin_references.py --check` — 디스크와 생성물이 다르면
    차이를 stderr에 찍고 **exit 1**, 같으면 exit 0
  - `references/*.md` 5종 — Task 04의 `SKILL.md`가 이 파일명들을 링크한다

## References
- `impl/lnpl/lexer.py:9-16` — `KEYWORDS_TOP`, `KEYWORDS_CLAUSE`, `KEYWORDS_CONTROL`,
  `RESERVED`, `DURATION_UNITS`, `COMPARATORS`
- `impl/lnpl/lower.py:66-95` — `VERB_LEXICON`, `POLICY_NAMES`, `SECURITY_MECHANISMS`,
  `PERF_METRICS`, `VALUELESS_PERF`, `ARGUMENT_MECHANISMS`
- `impl/lnpl/types.py:26` — `SEMANTIC_TYPES`
- `impl/lnpl/diagnostics.py:35-80` — `CODES`, `ENFORCEMENT`
- `impl/lnpl/refinements.py:28-66` — `FACET_NAMES`, `CATEGORY_FACETS`, `BASE_CATEGORY`, `PRESETS`
- `impl/lnpl/spec.py:252` — `EXPECTATIONS`
- `impl/tests/test_golden.py:108` — 스크립트를 `subprocess.run([sys.executable, SCRIPT, ...])`로
  구동하는 이 레포의 방식. 그대로 따른다.
- `impl/tests/test_enforcement_matrix.py` — 문서와 소스의 drift를 막는 기존 패턴.

## Steps

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`impl/tests/test_plugin_references.py`:

```python
"""플러그인 어휘 문서가 소스에서 생성된 그대로인지 검사한다.

정본은 `impl/lnpl/`의 모듈 상수다. `references/*.md`는 산출물이고, 사람이
고치면 안 된다. 고치면 플러그인이 틀린 어휘를 권위 있게 가르치게 된다 —
`docs/ENFORCEMENT-MATRIX.md`가 `test_enforcement_matrix.py`로 고정된 것과
같은 이유, 같은 장치다.
"""
import os
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GEN = os.path.join(REPO, "scripts", "gen_plugin_references.py")
REFS = os.path.join(REPO, "plugins", "lnpl", "skills", "lnpl-authoring", "references")
EXPECTED = ("grammar.md", "verbs.md", "declarations.md", "types.md", "spec.md")


def run_gen(*args):
    env = dict(os.environ, PYTHONPATH=os.path.join(REPO, "impl"))
    return subprocess.run([sys.executable, GEN, *args], cwd=REPO, env=env,
                          capture_output=True, text=True)


class GeneratorTest(unittest.TestCase):
    def test_generator_exists(self):
        self.assertTrue(os.path.isfile(GEN))

    def test_all_reference_files_present(self):
        for name in EXPECTED:
            self.assertTrue(os.path.isfile(os.path.join(REFS, name)),
                            "%s가 없다 — 생성기를 돌려라" % name)

    def test_no_drift_between_source_and_committed_files(self):
        proc = run_gen("--check")
        self.assertEqual(proc.returncode, 0,
                         "어휘 문서가 소스와 어긋났다. `python scripts/"
                         "gen_plugin_references.py`로 재생성하라.\n%s" % proc.stderr)

    def test_check_mode_detects_a_hand_edit(self):
        # 게이트가 실제로 잡는지 증명한다 — 통과만으로는 잠자는 테스트와 구별되지 않는다.
        target = os.path.join(REFS, "verbs.md")
        with open(target, encoding="utf-8") as fh:
            original = fh.read()
        try:
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(original + "\n손으로 덧붙인 줄\n")
            proc = run_gen("--check")
            self.assertEqual(proc.returncode, 1)
            self.assertIn("verbs.md", proc.stderr)
        finally:
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(original)

    def test_check_mode_reports_a_missing_file(self):
        target = os.path.join(REFS, "spec.md")
        with open(target, encoding="utf-8") as fh:
            original = fh.read()
        try:
            os.remove(target)
            proc = run_gen("--check")
            self.assertEqual(proc.returncode, 1)
            self.assertIn("spec.md", proc.stderr)
        finally:
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(original)

    def test_generated_files_carry_the_do_not_edit_banner(self):
        for name in EXPECTED:
            with open(os.path.join(REFS, name), encoding="utf-8") as fh:
                head = fh.readline()
            self.assertIn("생성물", head, "%s에 경고 배너가 없다" % name)

    def test_every_verb_in_the_lexicon_reaches_the_document(self):
        from lnpl.lower import VERB_LEXICON
        with open(os.path.join(REFS, "verbs.md"), encoding="utf-8") as fh:
            text = fh.read()
        for verb in VERB_LEXICON:
            self.assertIn("`%s`" % verb, text)

    def test_every_enforcement_row_reaches_the_document(self):
        from lnpl.diagnostics import ENFORCEMENT
        with open(os.path.join(REFS, "declarations.md"), encoding="utf-8") as fh:
            text = fh.read()
        for clause, name in ENFORCEMENT:
            self.assertIn("`%s %s`" % (clause, name), text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패를 확인한다**

```bash
PYTHONPATH=impl .venv/bin/python -m unittest impl.tests.test_plugin_references -v 2>&1 | tail -15
```
Expected: FAIL — 생성기가 없다.

- [ ] **Step 3: 생성기를 만든다**

`scripts/gen_plugin_references.py`:

```python
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
        facets = ", ".join("%s=%s" % (k, v) for k, v in spec["facets"].items())
        lines.append("| `%s` | `%s` | %s |" % (name, spec["base"], facets))
    lines.append("\n## 직접 선언하는 refinement\n")
    lines.append("`refine <PascalName> of <base>` 뒤에 facet을 둔다. "
                 "base별로 허용되는 facet이 다르다.\n")
    lines.append("| base | 허용 facet |")
    lines.append("|------|------------|")
    for base in BASE_CATEGORY:
        facets = CATEGORY_FACETS[BASE_CATEGORY[base]]
        lines.append("| `%s` | %s |" %
                     (base, " ".join("`%s`" % f for f in facets) or "—"))
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
```

- [ ] **Step 4: 생성한다**

```bash
mkdir -p plugins/lnpl/skills/lnpl-authoring/references && \
PYTHONPATH=impl .venv/bin/python scripts/gen_plugin_references.py
```
Expected: `wrote 5 files to .../references`

- [ ] **Step 5: 생성물을 눈으로 확인한다**

```bash
head -20 plugins/lnpl/skills/lnpl-authoring/references/verbs.md
wc -l plugins/lnpl/skills/lnpl-authoring/references/*.md
```
Expected: 배너 + 16개 동사 표. 표에 `return`이 **없어야** 한다.

- [ ] **Step 6: 테스트 통과를 확인한다**

```bash
PYTHONPATH=impl .venv/bin/python -m unittest impl.tests.test_plugin_references -v 2>&1 | tail -12
```
Expected: PASS (8 tests)

- [ ] **Step 7: drift 게이트가 실제로 잡는지 손으로 확인한다**

`test_check_mode_detects_a_hand_edit`가 자동으로 하지만, 한 번은 직접 본다:

```bash
echo "손으로 덧붙임" >> plugins/lnpl/skills/lnpl-authoring/references/types.md && \
PYTHONPATH=impl .venv/bin/python scripts/gen_plugin_references.py --check; echo "exit=$?"; \
PYTHONPATH=impl .venv/bin/python scripts/gen_plugin_references.py
```
Expected: `types.md: 소스와 다름` / `exit=1`, 그다음 재생성으로 복구.

- [ ] **Step 8: 전체 스위트 무회귀**

```bash
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl 2>&1 | tail -5
```
Expected: OK

- [ ] **Step 9: 커밋**

```bash
git add scripts/gen_plugin_references.py impl/tests/test_plugin_references.py \
        plugins/lnpl/skills/lnpl-authoring/references/
git commit -m "feat(plugin): generate the vocabulary references from source, gate drift

어휘를 문서로 옮겨 적는 순간 lower.py와 갈라지고, 그러면 플러그인이 틀린
어휘를 권위 있게 가르치게 된다. ENFORCEMENT-MATRIX.md + test_enforcement_matrix.py가
세운 패턴을 그대로 쓴다 — 정본은 소스, 문서는 산출물, drift는 RED."
```

## Deliverables
- `scripts/gen_plugin_references.py` — 기본 생성 / `--check` 검증
- `impl/tests/test_plugin_references.py` — 8건
- `references/` 5종 생성물

## Acceptance
1. `--check`가 무변경 상태에서 exit 0.
2. 파일을 한 글자 고치면 exit 1이고 stderr에 파일명이 나온다(테스트로 실증).
3. 파일을 지워도 exit 1.
4. `VERB_LEXICON`의 16개 동사와 `ENFORCEMENT`의 모든 행이 문서에 도달한다.
5. 5개 파일 전부 "생성물" 배너로 시작한다.
6. 전체 스위트 무회귀.

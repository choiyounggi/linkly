# Task 04: `lnpl-authoring` 스킬을 만든다

> 실행자에게: 이 태스크는 `superpowers:subagent-driven-development` 또는
> `superpowers:executing-plans`로 수행한다. 각 Step은 체크박스 단위다.

## Objective
`.lnpl`을 쓰려는 모델이 **닫힌 어휘로 라우팅되는** 진입점을 만든다. `SKILL.md`는
라우팅 표와 증상만 담고, 어휘 본문은 Task 03이 생성한 `references/`로 내린다(A4).

## Files
- Create: `plugins/lnpl/skills/lnpl-authoring/SKILL.md`
- Modify: `impl/tests/test_plugin_references.py` (스킬 구조 검사 클래스 추가)
- 이미 존재(Task 03 생성물): `plugins/lnpl/skills/lnpl-authoring/references/*.md`

## Interfaces
- Consumes: Task 03의 `references/` 5종 — `grammar.md` `verbs.md` `declarations.md`
  `types.md` `spec.md`
- Produces: 스킬 디렉터리 `plugins/lnpl/skills/lnpl-authoring/`. Task 07의
  `plugin.json`이 이 경로를 담는 플러그인 루트를 가리킨다.

## References
- `kb/INDEX.md` — 이 레포가 쓰는 라우팅 표의 형태. "언제 여기로 오는가"를 열로 둔다.
- `rfcs/0005-knowledge-base.md` — 3단 progressive disclosure. 같은 원리를 스킬에 적용한다.
- `examples/shorten.lnpl` 주석 — 기계(집행되는 선언)와 서술(집행 안 되는 선언)을
  가르는 실제 사례.

## Steps

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`impl/tests/test_plugin_references.py` 끝에 추가한다:

```python
SKILL_DIR = os.path.join(REPO, "plugins", "lnpl", "skills", "lnpl-authoring")
SKILL_MD = os.path.join(SKILL_DIR, "SKILL.md")


def read_frontmatter(path):
    """`---`로 감싼 YAML 머리말을 아주 단순하게 읽는다 (key: value만)."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    if lines[0].strip() != "---":
        raise AssertionError("%s가 `---`로 시작하지 않는다" % path)
    out = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
    return out


class AuthoringSkillTest(unittest.TestCase):
    def test_skill_file_exists(self):
        self.assertTrue(os.path.isfile(SKILL_MD))

    def test_frontmatter_name_matches_directory(self):
        meta = read_frontmatter(SKILL_MD)
        self.assertEqual(meta.get("name"), "lnpl-authoring")

    def test_frontmatter_has_a_triggering_description(self):
        meta = read_frontmatter(SKILL_MD)
        desc = meta.get("description", "")
        self.assertGreater(len(desc), 40, "description이 너무 짧아 트리거되지 않는다")
        self.assertIn(".lnpl", desc)

    def test_every_reference_file_is_linked(self):
        with open(SKILL_MD, encoding="utf-8") as fh:
            text = fh.read()
        for name in EXPECTED:
            self.assertIn("references/%s" % name, text,
                          "%s로 가는 경로가 SKILL.md에 없다" % name)

    def test_skill_body_stays_a_routing_layer(self):
        # A4: 어휘를 SKILL.md에 인라인하면 .lnpl을 안 쓰는 세션까지 비용을 낸다.
        with open(SKILL_MD, encoding="utf-8") as fh:
            text = fh.read()
        self.assertLess(len(text), 4000,
                        "SKILL.md가 라우팅 계층을 넘어섰다 — 본문은 references/로")

    def test_skill_does_not_inline_the_verb_table(self):
        from lnpl.lower import VERB_LEXICON
        with open(SKILL_MD, encoding="utf-8") as fh:
            text = fh.read()
        hits = sum(1 for verb in VERB_LEXICON if "`%s`" % verb in text)
        self.assertLessEqual(hits, 4,
                             "동사 표가 SKILL.md에 복사됐다 — verbs.md로 라우팅만 하라")

    def test_reserved_keywords_are_called_out_at_the_routing_layer(self):
        # if/for/while/switch는 LLM의 기본 반사라 라우팅 단계에서 막아야 한다.
        with open(SKILL_MD, encoding="utf-8") as fh:
            text = fh.read()
        for word in ("if", "for", "while", "switch"):
            self.assertIn("`%s`" % word, text)
```

- [ ] **Step 2: 실패를 확인한다**

```bash
PYTHONPATH=impl .venv/bin/python -m unittest impl.tests.test_plugin_references.AuthoringSkillTest -v 2>&1 | tail -12
```
Expected: FAIL — `SKILL.md`가 없다.

- [ ] **Step 3: `SKILL.md`를 쓴다**

`plugins/lnpl/skills/lnpl-authoring/SKILL.md`:

````markdown
---
name: lnpl-authoring
description: Use when writing, editing, or reviewing `.lnpl` sources for the linkly platform — entity/service/workflow declarations, guard conditions, spec blocks, refinements. LNPL uses closed vocabularies that are not in your training data; a plausible-looking file compiles and then silently does nothing. Route here before writing any `.lnpl` line.
---

# `.lnpl` 작성

LNPL은 **의도(what)를 선언**하는 언어다. 구현(how)은 컴파일러와 에이전트가 정한다.

이 언어의 어휘는 **닫혀 있고, 당신의 학습 데이터에 없다.** 그럴듯해 보이는 낱말을
쓰면 대개 파싱은 성공하고 런타임이 아무것도 하지 않는다. 그래서 추측 대신
아래 표로 라우팅한다.

## 무엇을 쓰기 전에 어디를 읽는가

| 지금 하려는 일 | 읽을 것 |
|----------------|---------|
| 워크플로 스텝을 쓴다 (`validate input`, `cache user` …) | [references/verbs.md](references/verbs.md) |
| `policy` / `security` / `performance`를 선언한다 | [references/declarations.md](references/declarations.md) |
| 필드 타입이나 `refine`을 정한다 | [references/types.md](references/types.md) |
| 블록 구조·제어 흐름·키워드가 헷갈린다 | [references/grammar.md](references/grammar.md) |
| `spec` 블록으로 검증을 붙인다 | [references/spec.md](references/spec.md) |

## 먼저 알아야 할 세 가지 함정

**1. 사전에 없는 동사는 에러가 아니라 no-op이다.**
`return token`, `log event`, `send email` 같은 스텝은 컴파일에 성공하고 아무 효과도
내지 않는다. 동사는 반드시 `references/verbs.md`의 표에서 고른다.

**2. 선언했다고 집행되는 게 아니다.**
`security jwt`는 토큰을 발급하지도 검증하지도 않는다. `policy rollback`은 아무것도
되돌리지 않는다. `performance response`는 측정만 하고 초과를 막지 않는다.
무엇이 실제로 실행을 바꾸는지는 `references/declarations.md`의 집행 매트릭스가 정본이다.
집행되지 않는 선언을 **의도적으로** 쓰는 것은 괜찮다 — 모른 채 쓰는 것이 문제다.

**3. `if` / `for` / `while` / `switch`는 문법적으로 표현 불가능하다.**
예약어라 렉서가 거부한다. 분기는 `when`, 반복은 `repeat` / `until`을 쓴다.

## 쓴 다음에 반드시 한다

```
lnpl compile <파일>
```

진단은 **stderr로 나가고 종료 코드는 0**이다. 즉 보지 않으면 사라진다.
`unknown-verb`, `declared-not-enforced`, `declared-measured-only`,
`authorization-not-verified` 중 하나라도 나오면, 그게 의도한 것인지 사용자에게
확인하고 넘어간다. 조용히 무시하지 않는다.

`lnpl`이 없다는 오류가 나면 `lnpl-doctor` 스킬을 쓴다.
````

- [ ] **Step 4: 테스트 통과를 확인한다**

```bash
PYTHONPATH=impl .venv/bin/python -m unittest impl.tests.test_plugin_references -v 2>&1 | tail -12
```
Expected: PASS (8 + 7 = 15 tests)

- [ ] **Step 5: 링크가 실제로 존재하는 파일을 가리키는지 확인한다**

```bash
cd plugins/lnpl/skills/lnpl-authoring && \
grep -o 'references/[a-z]*\.md' SKILL.md | sort -u | while read p; do
  [ -f "$p" ] && echo "OK  $p" || echo "MISSING  $p"
done; cd - >/dev/null
```
Expected: 5줄 전부 `OK`

- [ ] **Step 6: 전체 스위트 무회귀**

```bash
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl 2>&1 | tail -5
```
Expected: OK

- [ ] **Step 7: 커밋**

```bash
git add plugins/lnpl/skills/lnpl-authoring/SKILL.md impl/tests/test_plugin_references.py
git commit -m "feat(plugin): add the lnpl-authoring skill as a routing layer

SKILL.md는 라우팅 표와 세 가지 함정만 담고 어휘 본문은 references/로
내린다 — RFC-0005가 KB에 쓴 progressive disclosure와 같은 이유다.
어휘 전체를 인라인하면 .lnpl을 안 쓰는 세션까지 비용을 낸다."
```

## Deliverables
- `plugins/lnpl/skills/lnpl-authoring/SKILL.md`
- `impl/tests/test_plugin_references.py`에 `AuthoringSkillTest` 7건

## Acceptance
1. 머리말의 `name`이 디렉터리명과 같고, `description`이 `.lnpl`을 포함한다.
2. `references/` 5종 전부가 `SKILL.md`에서 링크되고, 그 경로가 실재한다.
3. `SKILL.md`가 4000바이트 미만이고 동사 표를 인라인하지 않는다(A4).
4. 예약어 넷이 라우팅 단계에서 명시된다.
5. 전체 스위트 무회귀.

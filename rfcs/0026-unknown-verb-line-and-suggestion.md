# RFC-0026: `unknown-verb`/`guard-orphaned-steps`/`guard-skipped-steps`의 `line`과 `suggestion`

## Status

- Status: **Accepted** (RFC-0026, 2026-08-18)
- Updates: RFC-0024 §Reference-level Specification/3. 집행 진단 3종의 `line`,
  RFC-0024 §Examples/바뀌지 않는다

RFC-0007 §2.2 규칙 1·2에 따라 절을 이름으로 지목한다. RFC-0024 §Reference-level
Specification/3은 "이 3종 밖의 진단(`unknown-verb`, `guard-skipped-steps`,
`guard-orphaned-steps`, `validation-sample-derived`)은 `line`을 넘기지 않는다"고
적었고, §Examples/바뀌지 않는다는 그중 `unknown-verb`와 `guard-orphaned-steps`가
"이 RFC 이전과 바이트 단위로 같은 형식"이라고 못박았다 — 이 RFC는 정확히 그
서술을 개정한다. 지목하지 않은 절과는 모순이 없다: `validation-sample-derived`
(mode B)는 이 RFC의 범위 밖으로 그대로 남는다.

## Motivation

이슈 #82: MCP `lnpl_compile`이 돌려주는 `unknown-verb` 레코드는 `where`
(`"line 8"` 같은 문자열)만 가지고, RFC-0024가 집행 진단 3종에 준 구조화 `line`
(정수)이 없다. MCP 소비자(주로 에이전트)가 소스로 점프하려면 `where` 문자열을
정규식으로 긁어야 한다 — RFC-0024 자체가 §Alternatives (b)에서 "문자열에 줄을
섞으면 소비자가 다시 정규식을 써야 한다"고 거부한 바로 그 패턴을 `unknown-verb`
가 여전히 겪고 있는 것이다. `guard-orphaned-steps`(RFC-0023)도 같은 결함이고,
`guard-skipped-steps`(RFC-0014, 런타임)도 마찬가지다.

두 번째 결함은 7차 프로덕션 감사가 관측한 것이다: 닫힌 어휘의 실제 실패 모드는
철자 오타보다 **의미상 근접한 동의어**다 — `persist note`나 `fetch order`는
그럴듯하게 파싱되고 `Effect`를 파생하지 않는 no-op이 되며, `unknown-verb`
진단은 "무엇이 잘못됐는지"만 말하고 "무엇으로 고치는지"는 말하지 않는다.

## Guide-level Explanation

`Diagnostic.line`(RFC-0024가 신설, `Optional[int]`)의 채움 범위가 넓어진다.
지금까지 이 필드를 채우던 것은 `declared-not-enforced` /
`declared-measured-only` / `authorization-not-verified` 3종뿐이었다. 이 RFC부터
`unknown-verb`와 `guard-orphaned-steps`도 채우고(둘 다 lowering이 이미 소스 줄을
손에 쥔 컴파일 타임 진단이다), `guard-skipped-steps`도 계약상 채우는 대상에
들어간다(런타임 진단 — 구체적 유도는 RFC-0024 §3이 `authorization-not-verified`
에 이미 세운 패턴, 즉 lowering이 Effect 노드에 적어 둔 `line`을 실행 시점에
되짚는 방식을 그대로 따른다). 세 코드 모두 기존 `where` 문자열 표면은 바뀌지
않는다 — `line`은 그 옆에 나란히 놓이는 구조화 필드일 뿐이다.

새 필드 `Diagnostic.suggestion`(`Optional[str]`)도 이 RFC가 신설한다.
`unknown-verb`만 채운다: 2단 판정이다 — 1단은 수제 별칭 표
(`lower.py::VERB_ALIASES`)로 의미상 동의어(`persist`→`create`)를 잡고, 1단이
미스면 2단 `difflib.get_close_matches`(cutoff 0.6)로 철자 오타
(`craete`→`create`)를 잡는다. 둘 다 미스면 `suggestion`은 `None`이고 메시지에
suffix가 없다 — 키 자체는 항상 존재해서, 소비자가 값이 아니라 키 존재로
분기하는 실수를 만들지 않는다(RFC-0024 §3이 `line`에 이미 세운 것과 같은
규율). `guard-orphaned-steps`/`guard-skipped-steps`는 `suggestion`을 채우지
않는다 — 오탈자를 낼 "동사"가 없는 진단이라 대상이 아니다.

## Reference-level Specification

### 1. `line` 확장 — RFC-0024 §Reference-level Specification/3 갱신 (치환 후 최종 텍스트)

> 집행 진단 3종에 더해, `unknown-verb`와 `guard-orphaned-steps`(둘 다 컴파일
> 타임)도 `line`을 넘긴다 — 둘 다 lowering이 소스 줄을 이미 손에 쥔 시점에
> 진단을 낸다:
>
> - `unknown-verb` (`lower.py::_WfContext._step`) — 그 스텝의 `line.lineno`.
> - `guard-orphaned-steps` (`lower.py::_check_guard_scope`) — 그 고아 스텝의
>   줄(`step_lines.get(step["id"])`, 이미 `where`가 같은 값을 문자열로 쓰던
>   자리다). 스텝이 `step_lines`에 없으면(워크플로 이름으로 폴백하는 경우)
>   `line`도 `None`이다 — §4의 로 폴백 규칙과 같다.
>
> `guard-skipped-steps`(런타임, `interp.py`)도 채우는 대상에 들어간다 — 구체적
> 유도는 `authorization-not-verified`가 이미 쓰는 패턴(lowering이 Effect 노드에
> 적어 둔 `line`을 실행 시점에 `self.nodes[...].get("line")`으로 되짚는 것)을
> 그대로 따른다. 이 RFC는 계약만 정하고, `interp.py`의 구현은 별도 변경으로
> 착지한다.
>
> 이 4종 밖의 진단(`validation-sample-derived`, mode B)은 여전히 `line`을
> 넘기지 않는다 — RFC-0024 §Reference-level Specification/2가 정한 대로 대응하는
> 단일 소스 줄이 없는 노드에서 나오기 때문이다.

### 2. RFC-0024 §Examples/바뀌지 않는다 갱신 (치환 후 최종 텍스트)

> `validation-sample-derived`(mode B)는 이 RFC 이전과 바이트 단위로 같은
> 형식이다 — 대응하는 단일 소스 줄이 없어 `line`을 넘기지 않는다(§1). `where`
> 문자열의 표면(`"line N"` 또는 워크플로/노드 id)은 4종 전부에서 바뀌지 않는다
> — `line`은 그 문자열을 대체하지 않고 나란히 추가되는 구조화 필드다.

### 3. `suggestion` 필드 (신설)

`diagnostics.py`의 `Diagnostic`에 필드 `suggestion: str = None`을 추가하고,
`Diagnostics.add(*, code, where, subject, message, line=None, suggestion=None)`
으로 받는다. `to_records`는 `"suggestion"` 키를 항상 담아 반환한다(값이 `None`
이어도) — RFC-0024 §3이 `line`에 세운 것과 같은 규율.

`unknown-verb`(`lower.py::_WfContext._step`)만 채운다:

1. **1단 — `VERB_ALIASES`.** `lower.py`에 `VERB_LEXICON` 옆의 수제 표:
   `persist`/`save`→`create`, `fetch`/`get`/`retrieve`/`lookup`→`read`,
   `remove`/`erase`→`delete`, `modify`/`change`→`update`, `notify`→`emit`. 이
   표는 **제안 전용이며 어휘 확장이 아니다** — `VERB_LEXICON`에 없는 동사는
   여전히 `unknown-verb`를 내고 `Effect`를 파생하지 않는다(R1은 바뀌지 않는다).
   `scripts/gen_plugin_references.py::render_verbs`는 `VERB_LEXICON`만 읽으므로
   이 표는 생성된 `references/verbs.md`에 나타나지 않는다. 두 동사에 걸치는
   모호한 후보(`store`, `send` 등)는 의도적으로 넣지 않는다 — 오제안이 무제안
   보다 나쁘다.
2. **2단 — `difflib.get_close_matches`.** 1단이 미스면
   `difflib.get_close_matches(verb, VERB_LEXICON, n=1, cutoff=0.6)`. 철자
   오타(`craete`→`create`)를 잡는다. 0.6은 낮추지 않는다 — 그 값 아래로는
   무관한 동사가 후보로 올라온다(예: `zzz`는 어떤 cutoff에서도 최선의 후보가
   ratio 0.17 미만이라 실질적으로 노이즈).
3. 둘 다 미스면 `suggestion`은 `None`이고 메시지에 suffix가 없다.

메시지: 제안이 있으면 기존 메시지 끝에 정확히
`" — did you mean '<verb>'?"`를 붙인다(작은따옴표). 제안이 없으면 메시지는
이 RFC 이전과 바이트 단위로 같다.

`guard-orphaned-steps`/`guard-skipped-steps`는 `suggestion`을 채우지 않는다 —
`Diagnostics.add`가 기본값 `None`을 그대로 쓴다.

## Examples

### 발화 — 1단 별칭

```
$ lnpl compile — workflow에 `persist note`
warning: unknown-verb [line 8] persist — `persist note` is outside VERB_LEXICON: this step
derives no Effect and runs as a descriptive no-op — did you mean 'create'?
```

MCP `lnpl_compile` 레코드: `{"code": "unknown-verb", "line": 8, "subject": "persist",
"suggestion": "create", ...}`.

### 발화 — 2단 오타

```
$ lnpl compile — workflow에 `craete note`
warning: unknown-verb [line 7] craete — ... — did you mean 'create'?
```

레코드의 `"suggestion"`은 `"create"`.

### 발화하지 않는다(제안) — 무관 단어

```
$ lnpl compile — workflow에 `zzz note`
warning: unknown-verb [line 8] zzz — `zzz note` is outside VERB_LEXICON: this step derives
no Effect and runs as a descriptive no-op
```

레코드의 `"suggestion"`은 `null`(키는 존재), 메시지에 suffix 없음.

### 발화 — `guard-orphaned-steps`의 `line`

`impl/tests/lnpl_fixtures/guard_orphan_fail.lnpl`을 컴파일하면 레코드에
`"line": 16`이 실린다 — `where`는 이 RFC 이전과 같은 `"line 16"` 문자열 그대로.

## Alternatives

**(a) 의미 유사도 모델(임베딩 등)로 1단을 대체한다.** 닫힌 18동사 어휘에는
과한 의존성이고, 모델 버전에 따라 제안이 흔들리는 비결정성을 들인다. 이 표는
작고 고정돼 있어 손으로 짜는 편이 검증 가능하고 재현 가능하다. 채택하지 않았다.

**(b) `difflib` cutoff를 낮춰 별칭 표 없이 `persist`→`create`를 잡는다.**
수학적으로 불가능하다: 어떤 cutoff에서도 `persist`는 `list`/`emit`
(ratio 0.545)이 `create`(ratio 0.308)보다 먼저 걸린다 — cutoff을 낮춰도
`create`가 최선의 후보가 되는 지점은 없고, 그 지점까지 낮추면 무관한 동사도
대거 통과한다. 채택하지 않았다.

**(c) `guard-skipped-steps`의 `line` 구현을 이 RFC와 같은 변경에 넣는다.**
`interp.py`는 다른 트랙이 소유한다 — 이 RFC는 계약(§1)만 정하고, 구현은 그
트랙의 변경으로 별도 착지한다.

## Open Questions

1. `VERB_ALIASES`의 항목이 실측에서 부족하거나 넘치면(예: 실제로 자주 보이는
   오타/동의어가 빠졌거나, 두 동사에 걸치는 후보를 넣어야 할 근거가 쌓이면)
   표를 갱신한다 — 이 RFC는 지금 시점의 관측(7차 감사)을 반영한 초기 집합이다.
2. `guard-skipped-steps`의 `line`이 실제로 착지하면, 이 RFC가 §1에서 세운
   계약(런타임 되짚기 패턴)과 실제 구현이 일치하는지 별도로 확인해야 한다 —
   이 RFC 자체는 코드를 갖지 않는다.

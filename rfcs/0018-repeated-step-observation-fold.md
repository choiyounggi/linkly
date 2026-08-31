# RFC-0018: 반복 스텝 관측의 fold 규칙

## Status

- Status: **Accepted** (RFC-0018, 2026-08-07)
- Updates: RFC-0017 §Open Questions 1: 차등 관측 맵의 스텝 이름 키

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목한다. 이 문서는 RFC-0017이
**미결로 남긴 질문 하나만** 닫는다. 예제 목록(RFC-0017 §Guide-level Explanation),
가드의 문법·실행 의미(RFC-0008, RFC-0014·0015·0016이 갱신), RFC-0004의 4분류
자체는 지목하지 않으며 어느 것도 바꾸지 않는다 — 이 개정은 그 4분류 중 **3번을
계산하는 방법**이 두 모드에서 서로 달랐던 것을 하나로 정한다(규칙 2).

번호가 0018인 이유: 0017까지 점유되어 있다. RFC-0007 §3은 번호 재사용을 금지한다.

## Motivation

이슈 #51이 보고한 `lnpl diff` DIVERGENT의 근인이다.

**이슈가 지목한 층은 원인이 아니었다.** 이슈 #51은 "`until` 조건이 진입 시점에
이미 참이면 mode A는 0라운드, mode B는 상한(16)까지 실행"이라고 적었다. 실측은
그것을 반증한다 — 진입-참에서 네이티브 바이너리가 찍는 `step` 줄은 정확히 **1줄**
(= 루프 본문 0라운드)이다. 이슈가 명시한 비교연산자 3종(`== 0` / `< 1` / `> 5`),
조건 소스 2종(저장 행 `token.x` / 실행 입력 `input.x`), 피가드 스텝의 효과 유무
2종 — **6/6 진입-참 케이스가 이미 EQUIVALENT**였다. RFC-0008 G10의 `scf.if` 부정
가드와 `differential.step_plan` 기반 스킵 복원이 제 몫을 하고 있었다.

**실제 발산은 관측기 층에서, 진입-거짓 경로에서 났다.** 양 모드가 똑같이 상한까지
도는 입력에서 분류 1/4(실행 순서)는 17스텝 동일로 PASS인데 분류 3/4가 FAIL한다.
기전은 두 줄이다.

- `observe_mode_a`가 `{s["step"]: s["effects"] for s in steps}` — dict
  comprehension이라 **같은 이름의 마지막 것만 남긴다**(덮어쓰기).
- `observe_mode_b`는 `setdefault(step_name, []).append(kind)` — **전부 누적**한다.

같은 스텝 이름이 N번 나오면 두 모드가 **동일한 일을 해도** 맵이 달라진다.
RFC-0017 §Reference-level Specification 제약 2가 이 두 줄을 이미 지목했고,
§Open Questions 1은 "맵을 스텝 이름으로 키잡는 것이 의도된 설계인지, 스텝 id로
잡아야 하는지 정해진 바가 없다 — 정해지지 않은 채 두 모드가 **서로 다르게** 접고
있다는 것이 문제의 핵심"이라고 기록한 뒤, 수리를 별도 추적 이슈로 넘겼다.
이 RFC가 그 질문을 닫는다.

**`until`만의 결함이 아니다.** `repeat`도 본문을 되풀이하며 같은 스텝 이름을 N번
방출하므로 동일하게 걸린다(실측). 결함은 `until`의 실행 의미가 아니라 **반복
일반**의 관측이다.

`UNTIL_COUNTER` 픽스처가 이것을 가렸다. 그 워크플로의 피가드 스텝은 효과를 갖지
않아 양 모드가 다 빈 리스트로 접힌다 — 어떻게 접든 같아진다. 효과를 가진 피가드
스텝이 이 결함을 드러내는 변수다.

## Guide-level Explanation

관측 맵의 값은 이렇게 읽는다.

> **그 이름의 스텝이 그 run에서 수행한 효과 전부를, 실행 순서대로 이어붙인
> 리스트.**

`until`이 16라운드를 돌며 매 라운드 `RepositoryCall` 하나를 냈다면 값은
`['RepositoryCall'] × 16`이다. `× 1`이 아니다. 양 모드가 같은 규칙을 쓴다.

읽는 사람이 가져가야 할 것은 둘이다.

1. 스텝 이름이 워크플로 안에서 유일하지 않아도 된다. `until`·`repeat` 아래의
   스텝은 본래 이름이 반복되며, 그것이 정상이다.
2. 두 모드의 effects 맵을 나란히 놓고 `==`로 비교해도 된다 — 접는 방식이 같아졌기
   때문이다.

## Reference-level Specification

**(a) 누적으로 통일한다.** `impl/lnpl/differential.py`의 `observe_mode_a`와
`observe_mode_b`는 둘 다 스텝 이름당 효과를 **누적**한다. `observe_mode_a`는
`setdefault(name, []).extend(...)`로 구현하며, 이는 `observe_mode_b`가 이미 쓰던
`setdefault(name, []).append(...)`와 같은 fold다.

**(b) 중복 이름을 접는 정규화를 금지한다.** 이 맵은 RFC-0004 분류 3
(observability signals)의 비교 대상이다. 차등 비교에서 정규화 하나마다 탐지력이
깎이므로, 각 정규화에는 그것을 허용하는 계약 조항이 필요하다. 16회 수행된 효과를
1회로 접는 조항은 없다 — 그렇게 접으면 **mode B가 저장소 호출 15회를 빼먹어도 검사가
통과한다.** 그래서 통일 방향은 누적이며, mode B를 덮어쓰기로 낮추는 것은 금지한다.

**(c) 스텝 인덱스를 키에 넣지 않는다.** 이름 대신 (이름, 라운드 인덱스)로 키를
잡는 대안은 채택하지 않는다. 네이티브 런타임이 찍는 효과 줄은
`effect <step name> <Kind>`이며 **인덱스를 싣지 않는다** — mode B는 어떤 효과가
몇 번째 라운드의 것인지 관측할 수 없다. 인덱스를 실으려면 방출 MLIR을 바꿔야 하고,
그것은 동결 골든 `impl/tests/golden/*.std.mlir`("Do not regenerate" 헤더)를 깬다.
라운드별 귀속이 필요하면 그것은 분류 1(실행 순서)의 `order` 리스트가 이미 담고
있다 — `order`는 양 모드 모두 매 occurrence를 보존한다.

**(d) 회귀 고정.** 이 규칙은 `impl/tests/test_until_mode_equivalence.py`의
`TestUntilRepeatedStepObservation`(진입-참·진입-거짓 양방향 × 비교연산자 3종 +
`repeat`)과 `TestRepeatedStepFoldDetectsRealDivergence`(음성 대조 — 반복 스텝에서
진짜 발산이 나면 분류 3/4가 여전히 빨개진다)가 고정한다. 후자는 툴체인을 요구하지
않는다.

## Examples

이슈 #51 본문의 재현이다.

<!-- lnpl-check: skip — fragment: 조각: entity Token 선언 없이 재현 스텝만 보여줌(컴파일러: `find` needs an entity in scope) -->
```lnpl
workflow Repro
    find token
    until token.retryBudget == 0
    read token
```

`retryBudget=9`(진입-거짓 → 양 모드 16라운드)로 실행한 `lnpl diff`.

**수리 전** (`impl/lnpl/differential.py`만 되돌린 트리, rc=1):

```
PASS 1/4 execution order — 17 step(s): find token -> read token -> ... | 0 skip(s)
PASS 2/4 policy outcome — status=completed
FAIL 3/4 observability signals
  mode A: {'find token': ['RepositoryCall'], 'read token': ['RepositoryCall']}
  mode B: {'find token': ['RepositoryCall'], 'read token': ['RepositoryCall', ... ×16]}
PASS 4/4 masking — no secret marker in either mode's output
differential: DIVERGENT
```

실행 순서는 갈리지 않았다(1/4 PASS, 양 모드 17스텝). 갈린 것은 관측 맵뿐이다.

**수리 후** (rc=0):

```
PASS 1/4 execution order — 17 step(s): find token -> read token -> ... | 0 skip(s)
PASS 2/4 policy outcome — status=completed
PASS 3/4 observability signals — 17 effect(s) per step match
PASS 4/4 masking — no secret marker in either mode's output
differential: EQUIVALENT
```

진입-참(`retryBudget=0`)은 수리 전후 모두 EQUIVALENT다 — 0라운드, 양 모드
`rounds: 0` 스킵 레코드 1건(RFC-0014 동형 기록). 이 경로는 회귀 대조군이다.

`repeat`도 같은 결함이었다.

```
workflow Repro
    validate token
    repeat 3
    read token
```

수리 전 mode A `['RepositoryCall']` vs mode B `['RepositoryCall'] × 3` → DIVERGENT.
수리 후 양쪽 `× 3` → EQUIVALENT.

## Alternatives

**mode B를 덮어쓰기로 낮춘다.** 기각. 두 모드는 합의하지만, 합의의 대가가 탐지력
전부다 — 반복 스텝에서 mode B가 효과를 몇 개 빠뜨리든 맵은 한 개짜리로 접혀 같아
보인다. 차등 검사가 존재하는 이유를 지우는 통일이다. §Reference-level
Specification (b)의 근거가 이것이다.

**(이름, 라운드 인덱스)로 키를 잡는다.** 기각. mode B가 관측할 수 없다 — 효과 줄에
인덱스가 없다. 실으려면 동결 골든이 깨진다. (c) 참조.

**스텝 이름의 유일성을 문법에서 강제한다.** 기각. `until`·`repeat`의 정상적인
사용을 금지하게 된다 — 반복 가드의 본문은 본래 같은 스텝을 되풀이한다. 관측기의
결함을 문법 제약으로 옮기는 것이고, RFC-0017이 예제에서 `until`을 빼야 했던
바로 그 제약을 언어 전체로 승격시킨다.

**아무것도 하지 않고 예제에서 `until`을 계속 뺀다.** 기각. RFC-0017이 그 임시
조치를 취하면서 "이 수리는 이 RFC의 범위가 아니다 — 별도 추적 이슈로 올린다"고
적었다. 이 문서가 그 추적의 종결이다.

## Open Questions

1. **`until` 예제의 복귀.** RFC-0017 §Open Questions 2가 남긴 질문 — 이 수리로
   `examples/guarded.lnpl`에 `until`을 다시 실을 수 있게 됐지만, **이 RFC는 그것을
   닫지 않는다.** RFC-0017이 적은 대로 그 문서를 Updates하는 후속 RFC의 일이고,
   예제 파일 변경은 이 개정의 범위 밖이다.
2. **자기 본문의 바인딩을 읽는 `until`.** 조건이 루프 **안**의 스텝이 만드는 행
   바인딩을 읽으면 다른 발산이 남는다(실측): 진입 시점에 바인딩이 없어 mode A는
   1라운드를 돌고, mode B는 시드에서 값을 정적 투영해 0라운드를 돈다 →
   **분류 1/4** FAIL. 근인이 다르다 — mode B가 저장소 상태를 모델링하지 않는 기지의
   한계(RFC-0012 §G12.6, `examples/guarded.lnpl` 헤더의 KNOWN LIMITATION)이고,
   이 fold 규칙으로는 닫히지 않는다. 별도 이슈로 추적한다.
3. **분류 3의 순서 민감도.** 누적 리스트는 순서를 보존하므로 두 모드가 효과를 다른
   순서로 낸다면 `==`가 빨개진다. 지금은 양 모드가 실행 순서대로 내므로 문제가
   없지만, RFC-0004가 분류 3에 대해 순서를 요구하는지 집합을 요구하는지는 명시한
   바가 없다. 순서가 갈리는 사례가 실제로 나오면 그때 정한다.

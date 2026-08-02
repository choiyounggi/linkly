# RFC-0009: Guard Condition Open Question 정리

## Status

- Status: **Accepted** (RFC-0009, 2026-08-02)
- Updates: RFC-0002 §Open Questions, RFC-0002 §Workflow body & control/가드 라인

## Motivation

RFC-0008이 `Condition`을 `Presence | Comparison`으로 확정하면서 평가기 없는
`Word Word? Word? Word?` 대안을 제거했다. 그런데 RFC-0002 §Open Questions ②는
여전히 이렇게 말한다:

> `Condition`은 현재 비교식+1~4토큰 구가 전부다.

**이 문장은 지금 거짓이다.** 그리고 RFC-0008의 `Updates:` 목록은
`RFC-0002 §Full grammar`와 `RFC-0003 §Guard`만 지목하며 §Open Questions를 지목하지
않는다. RFC-0007 §2.2 규칙 2는 이 상황을 명확히 규정한다:

> 지목하지 않은 절과 모순되면 안 된다. 모순이 필요하면 그 절도 `Updates:` 목록에
> 지목해야 한다. **지목 없는 모순은 개정이 아니라 결함이다.**

즉 이것은 미결 사항이 아니라 **결함**이다. 이 RFC가 빠진 `Updates` 관계를 보충해
해소한다.

**같은 결함이 한 곳 더 있다.** RFC-0002 §Workflow body & control의 가드 라인 항목도
`Condition`은 비교식 또는 1~4토큰 구다라고 서술한다. 이 절 역시 어느 `Updates:`
목록도 지목하지 않았으므로 규칙 2의 같은 판정을 받는다. 미결 목록만 고치고 이쪽을
남기면 같은 파일 안에 폐기된 문법이 그대로 남는다 — 그래서 두 절을 함께 지목한다.
절 안의 한 항목만 바뀌므로 RFC-0007 §2.2 규칙 1이 예시하는 경로 표기
(`RFC-NNNN §<절 이름>/<하위 항목>`)를 써서 범위를 정확히 좁힌다.

**RFC-0008 자체는 수정하지 않는다.** 그 본문은 여전히 옳고, `Accepted` RFC의
`Updates:` 목록에 절을 추가하는 것은 실질 변경이다 — RFC-0007 §2.2 규칙 3이
"효력 있는 계약 = 대상 RFC 본문에서, 지목된 각 절을 최신 갱신 RFC의 본문으로 치환한
것"으로 정의하므로, 목록에 절을 더하면 계약의 범위가 달라진다. RFC-0007 §2.1에 따라
그런 변경은 본문 편집이 아니라 새 RFC로 한다.

**전면 대체(Supersedes)가 아닌 이유**는 §Alternatives에 적는다.

## Guide-level Explanation

가드 조건에 쓸 수 있는 것은 두 가지다.

```
when token missing        # Presence — 필드가 있는가 / 없는가
until counter >= 10       # Comparison — 필드를 값과 비교
```

한때 문법에는 세 번째 대안이 있었다. `Word Word? Word? Word?` — 임의의 1~4토큰
구다. `when latency exceeds budget` 같은 것을 쓸 수 있었다. 문제는 **어느 평가기도
그것을 구현하지 않았다는 것**이다. 그런 조건을 쓴 프로그램은 파싱은 통과하고 런타임에
반드시 실패했다. RFC-0008이 그 대안을 제거해, 지금은 파서가 파스 시점에 거부한다.

이 RFC는 문법을 바꾸지 않는다. RFC-0002의 미결 목록이 아직 옛 문법을 서술하고 있어,
그 목록을 현재 계약과 일치시키는 것이 전부다. 새 규칙은 없다.

한 가지는 여전히 열려 있고, 그것을 어디서 추적하는지도 아래에 적는다 —
**멤버십 검사**는 지금 어느 RFC도 추적하지 않으므로 이 항목에 남긴다.

## Reference-level Specification

### RFC-0002 §Open Questions (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래는 "무엇을 바꾼다"가 아니라 **치환 후의 최종
텍스트**다. 항목 1·3·4·5는 RFC-0002 원문 그대로이며 이 RFC가 손대지 않는다.

1. **step 토큰 상한은 실측 없는 설계 가설이다** — "동사+목적어 2~4토큰 권장,
   단독 동사 허용, 상한 4토큰"은 LLM 생성 품질·표현력에 대한 실측 없이 정한
   값이다. 골든 시나리오의 `authenticate`(1토큰)와 계획 규정(2~4토큰)의
   충돌을 "동사 선두 1~4토큰 허용 + 2~4토큰 권장"으로 조정한 것도 같은 가설의
   일부다. 참조 인터프리터(plan.md D14·D20) 단계에서 실측 후 재검토한다.
2. **가드 조건식의 표현력 — 해소됨(RFC-0008).** `Condition`은
   `Presence | Comparison`이다(RFC-0008 §Full grammar). 평가기가 없던
   `Word Word? Word? Word?` 대안은 제거됐고, 파서가 파스 시점에 거부한다.
   남은 확장 여지는 두 갈래로 갈린다:
   - **부정·논리 결합(and/or)** — RFC-0008 §Open Questions 3(논리 결합의
     표현력)이 이어받는다. 이 항목에서는 다루지 않는다.
   - **멤버십 검사** — 어느 RFC도 추적하지 않으므로 **이 항목에 남긴다.**
     필요해지면 문법 확장이 필요하다.
3. **refinement 타입의 표면 표기** — RFC-0001은 사용자 정의 타입을 기존 18종
   base의 제약 강화(refinement)로만 허용하는데, 그 표면 문법(`field age
   Integer …범위…` 류)은 미정이다.
4. **Duration 단위 확장과 필드 optional 표기** — 단위는 실증 3종(`ms`/`s`/
   `m`)만 규정했다(`h`/`d` 등 확장 미정). `FieldLine`의 required 기본 true에
   대한 optional 표기도 미정이다.
5. **goal 절의 lowering 대상** — `goal` 절이 IR의 어느 노드(BusinessRule?
   Workflow 자동 합성?)로 lowering되는지는 후속 lowering 매핑 표(태스크 04)로
   넘긴다.

### RFC-0002 §Workflow body & control / 가드 라인 (치환 후 최종 텍스트)

절 안의 이 항목만 갱신한다. 같은 절의 다른 항목(StepLine·`parallel` 블록·`pipeline`
블록)은 RFC-0002 원문이 그대로 유효하며 이 RFC가 손대지 않는다.

- **가드 라인** — `when <Condition>`·`repeat <Integer>`·`until <Condition>`은
  **직후 1개의** step 또는 parallel/pipeline 블록에 적용되는 접두 가드다.
  별도 블록을 열지 않으므로 적용 범위가 항상 명확하다. `Condition`은
  `Presence | Comparison`이다(RFC-0008 §Full grammar). 가드의 실행 의미(조건
  평가·반복 종료)는 RFC-0003 소유다.

### 항목 ②를 삭제하지 않고 남긴 이유

이슈 #3의 수용 기준은 "RFC-0002 Open Questions ②가 **제거**된다(편집이 아니라)"로
적혀 있었다. 그 문구는 전면 대체만 존재하던 RFC-0000 시절에 쓰였다. `Updates`
관계에서는 대상 RFC가 본문을 그대로 두고 갱신 RFC의 절이 이긴다(RFC-0007 §2.2
규칙 3). 항목을 통째로 없애면 멤버십 검사가 추적처를 잃으므로, 해소로 표시하고
남은 부분만 명시하는 편이 정확하다.

## Examples

골든 시나리오 "Login"(정본: `plans/rfc-suite/plan.md` §골든 시나리오)은 가드를 쓰지
않는다. RFC-0007 §6은 그런 경우 **골든을 확장해 기능을 넣지 말고 골든 인접 예제를
따로 제시하라**고 규정하므로, 아래는 `examples/login.lnpl`을 그대로 두고 별도
워크플로우로 보인다. 골든의 `entity User`는 `id`/`email`/`password`/`createdAt`
네 필드이며 여기에 필드를 추가하지 않는다.

**허용** — 조건이 참조하는 필드를 선언한 인접 예제:

```
entity Session
    field
        id UUID
        token Text

workflow Refresh
    load session
    when token missing
    issue token
```

`token missing`은 `Presence ::= CamelName ('exists' | 'missing')`에 해당하므로
파서가 받아들이고, 모드 A·B 양쪽에 평가기가 있다.

**거부** — 옛 구 대안을 따르는 조건:

```
    when latency exceeds budget
```

실측 결과(전문):

```
ParseError: line 10: invalid condition: invalid comparator 'exceeds': 'latency exceeds budget'
```

RFC-0008 이전에는 이 프로그램이 파싱을 통과한 뒤 런타임에 반드시 실패했다. 지금은
파스 시점에 멈춘다 — 항목 ②가 서술하던 "1~4토큰 구"가 계약에서 사라졌다는 것의
관측 가능한 형태가 이것이다.

## Alternatives

| # | 검토한 대안 | 기각 사유 |
|---|------------|----------|
| 1 | RFC-0008을 직접 수정해 `Updates:` 목록에 `RFC-0002 §Open Questions`를 추가 | RFC-0008은 `Accepted`다. RFC-0007 §2.2 규칙 3이 효력 있는 계약을 "지목된 각 절을 갱신 RFC 본문으로 치환한 것"으로 정의하므로 목록 추가는 계약 범위를 바꾸는 실질 변경이고, §2.1이 그런 변경을 본문 편집에서 배제한다. 규칙 4도 걸린다 — 절을 지목하려면 그 절의 치환 후 텍스트를 담아야 하는데 RFC-0008에는 그 내용이 없다 |
| 2 | RFC-0002를 전면 대체(Supersedes) | RFC-0007 §2.2가 `Updates`를 신설한 이유와 정면으로 어긋난다 — "생산 규칙 한 줄이나 한 절을 고치려 해도 [전면 대체가 필요했다]"는 문제를 풀려고 만든 관계다. 바뀌는 것은 한 절이고 나머지는 여전히 유효한 계약이므로 RFC-0002는 `Accepted`를 유지한다 |
| 3 | 문법을 다시 확장해 항목 ②를 "미결"로 유지 | 평가기 없는 생산 규칙을 되살리는 것이다. RFC-0008이 그것을 제거한 이유가 "그 규칙을 따르는 프로그램은 런타임에 반드시 실패한다"였다 |

## Open Questions

없음. 이 RFC는 기록상의 결함 하나를 해소하며 새로 여는 것이 없다.

멤버십 검사는 위 §Reference-level Specification 항목 ②에 남아 RFC-0002의 미결로
계속 추적된다 — 이 RFC의 미결이 아니다.

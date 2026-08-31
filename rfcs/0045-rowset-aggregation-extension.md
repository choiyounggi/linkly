# RFC-0045: RowSet 집계 확장 — avg/min/max

## Status

- Status: **Accepted** (RFC-0045, 2026-08-30)
- Updates: RFC-0025 §Reference-level Specification/2. 집계 표현식 문법,
  RFC-0025 §Reference-level Specification/3. 정적 거부

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목한다. RFC-0025 §2의 `AggFunc`
생산 규칙(`'sum' | 'count'`)을 이 RFC가 처음으로 다시 넓힌다. RFC-0028의 Status는
`RFC-0025 §Reference-level Specification/2. 집계 표현식 문법`을 Updates 대상으로
**지목**하지만, 그것은 §2의 `AggFunc`/`Aggregate` 생산 규칙을 실제로 개정했기
때문이 아니다 — RFC-0028 자신의 본문이 "RFC-0025 §2는 `ArithOp`/`Condition`/
`Operand` 등 다른 생산 규칙은 손대지 않는다고 명시적으로 적었다 — 그 원문이
여전히 유효한 기준선이다"라고 못박는다. RFC-0028이 §2를 지목한 이유는 RFC-0015
§1(`ArithOp`/`Guard`)이라는 **다른** 생산 규칙을 개정하면서, 그 §1과 같은 절
안에 있는 `AssignStep`을 RFC-0025 §2가 이미 넓힌 적이 있어 그 계보를 함께
밝히려는 것이었다(RFC-0028 §Status 원문) — `AggFunc`/`Aggregate` 자체의
"치환 후 최종 텍스트"는 RFC-0028 어디에도 없다. RFC-0038의 Updates는
`RFC-0025 §Reference-level Specification/1. VERB_LEXICON과 표면 문법`을
지목한다 — `list`의 `ListTail`(`where`/`order by`/`limit`) 확장이고, 이 역시
§2가 아니다. 그러므로 `AggFunc`/`Aggregate`의 생산 규칙(§2)과 정적 거부 표(§3)는
RFC-0025 이후 **어느 RFC도 그 텍스트를 실제로 개정한 적이 없다** — 이 RFC가 둘
다 첫 실질 개정이라, 직전 갱신 RFC를 추가로 지목할 필요가 없다(RFC-0007 §2.2
규칙 5는 "이미 갱신된 절"에만 적용된다). 지목하지 않는 것: RFC-0025 §5(실행
스코프)·§10(모드 B) — 이 둘의 기존 판정("RowSet 값은 모드 B의 관측 대상이 아니다")은
avg/min/max에도 텍스트 변경 없이 그대로 적용된다(아래 §Reference-level
Specification/7). RFC-0044(Money 산술)는 Supersede도 Update도 하지 않는다 —
이 RFC는 그 RFC §4(반올림 정책)·§5(통화 규칙)가 정의한 함수를 **부르는 첫
호출자**일 뿐이다(References).

번호가 0045인 이유: 0044까지 점유됐다(RFC-0044, 이 RFC와 같은 런에서 번호를
받은 Money 코덱 RFC). RFC-0007 §3은 번호 재사용을 금지한다.

**구현은 후속이다.** 이 RFC는 문법·정적 거부·실행 의미 계약만 확정한다 —
`lower.py`의 `AggFunc` 처리, `interp.py`의 `avg`/`min`/`max` 평가, `diagnostics.py`
갱신 등 실제 코드는 이 RFC가 만들지 않는다(RFC-0043·RFC-0044와 같은 위상).

## Motivation

이슈 #145가 여는 질문은 두 RFC가 이미 이월해 둔 것이다. RFC-0025 §Open
Questions 3:

> **`min`/`max`/`avg`.** 이슈 #65는 `sum`/`count`만 요구한다. 셋 다 mode B가
> 값을 전혀 모델링하지 않는 같은 지형(§10) 위에서 자연스럽게 확장되지만,
> 요구되지 않은 표면을 먼저 여는 것은 이 RFC의 범위가 아니다.

그리고 RFC-0038 §Open Questions 1:

> **avg/min/max/group by.** 이슈 #116 §4가 명시적으로 범위 밖에 둔다 — 집계
> 함수를 `sum`/`count`(RFC-0025) 이상으로 넓히는 것과 `group by`는 별개
> 설계 질문이라 후속 이슈로 이월한다.

이슈 #145가 이제 그 표면을 요구한다. 이 RFC는 `avg`/`min`/`max`를 연다 —
`group by`는 여전히 열지 않는다(§Alternatives 1, RFC-0038 §Open Questions 1의
그 절반은 그대로 남는다). `qa/rerun/REPORT.md` §4(t3 F-1)가 실측한 잔존도
정확히 이 표면이다: "행 집합 집계(sum/count)·Money 산술 잔존 — 금액 합산
리포트는 스펙 이탈 없이 표현 불가"(§6.1) — RFC-0044가 Money에 평가기를 주고,
이 RFC가 그 평가기를 `sum`(기존)과 `avg`/`min`/`max`(신설) 양쪽에 실제로
연결한다.

## Guide-level Explanation

저자가 새로 쓸 수 있게 되는 것은 세 집계 함수다. 문법 자리는 기존 `sum`/`count`와
완전히 같다 — `set <target> to <func> <ref>`.

<!-- lnpl-check: skip — fragment: 조각: entity Report/Payment 선언 없이 워크플로 본문만 보여줌(컴파일러: `find` needs an entity in scope) -->
```lnpl
workflow SummarizePayments
    find report
    list payment
    set report.totalAmount to sum payment.amount
    set report.averageAmount to avg payment.amount
    set report.largestAmount to max payment.amount
    set report.smallestAmount to min payment.amount
    set report.paymentCount to count payment
    update report
```

**어느 함수가 어느 타입을 받는가**는 함수마다 다르다 — 무엇을 계산하는지가
타입마다 의미가 있는지 없는지를 가른다:

| AggFunc | Integer | DateTime | Money(같은 통화) |
|---------|:-------:|:--------:|:-----------------:|
| `sum`   | ✓ | ✗ (거부) | ✓ (RFC-0044 §5) |
| `avg`   | ✓ (half-to-even, RFC-0044 §4) | ✗ (거부) | ✓ (half-to-even, RFC-0044 §4) |
| `min`/`max` | ✓ | ✓ (신설) | ✓ (신설, RFC-0044 §5) |
| `count` | 필드 타입과 무관 — `Reference`가 엔티티 자체를 센다(RFC-0025 §2 원문 불변) |||

`sum`(DateTime)이 거부되는 이유는 RFC-0016 §3이 이미 `instant + instant`를
컴파일 거부로 정한 것과 같다 — 두 시각을 더한 값은 의미가 없다. 반면
`min`/`max`(DateTime)는 "가장 이른/가장 늦은 이벤트"라는 흔한 질의 형태이므로
이번에 연다. **`avg`(DateTime)는 이번에 열지 않는다** — "평균 시각"이 실무에서
무엇에 쓰이는지 이슈 #145도 실측도 요구하지 않았다(§Alternatives 2, RFC-0038
§Open Questions 1의 그 조각은 그대로 유예한다). `Decimal` 필드는 여전히 어느
함수도 받지 않는다 — RFC-0044가 푼 것은 Money(고정 소수 자릿수)뿐이다.

**Money의 `sum`/`avg`/`min`/`max`는 같은 통화끼리만 정의된다.** RowSet 안의
모든 행이 같은 통화 코드를 쓰지 않으면(예: 한 `Payment` 행은 USD, 다른 행은
EUR) 그 스텝은 `RunError`로 실패한다 — RFC-0044 §5가 정의한 규칙 그대로다.
이것은 컴파일 시점 검사가 아니다: 통화는 필드 선언이 아니라 행 데이터이므로,
서로 다른 통화가 섞였는지는 실행 중에만 안다.

**빈 RowSet.** `sum`은 0, `count`는 0(RFC-0025 §Guide-level Explanation 원문
불변). `avg`/`min`/`max`는 다르다 — 빈 집합의 평균이나 최댓값은 수학적으로
정의되지 않으므로, 이 RFC는 그 셋을 `RunError`로 정의한다(§Reference-level
Specification/3). "0을 낸다"거나 "조용히 무시한다"는 §Motivation이 RFC-0044부터
이어 온 "무음 실패를 만들지 않는다" 원칙과 어긋난다 — `list` 없이 쓴 집계가 이미
경고를 내는 것(`aggregation-orphaned-list`, RFC-0025 §4)과 같은 맥락에서, 실제로
빈 RowSet에 도달했을 때도 침묵보다 명시적 실패를 택한다.

**쓸 수 없는 것**은 §Reference-level Specification/2의 확장된 표에 있다. 문법
형태(`AggFunc Reference`, `Value`와 결합하지 않음)는 RFC-0025 §2 원문 그대로다
— `avg link.clicks + 1`은 여전히 파싱되지 않는다.

## Reference-level Specification

### 1. `AggFunc` 문법 — RFC-0025 §2 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0025 §Reference-level Specification/2의
`AggFunc` 생산 규칙에 대한 **치환 후 최종 텍스트**다. 같은 절의 `AssignStep`·
`Aggregate` 생산 규칙과 "정규화" 문단은 RFC-0025 원문 그대로 유효하며 이 RFC가
손대지 않는다 — `Aggregate`가 `Value`와 결합하지 않는다는 문장도 불변이다.

```
AggFunc      ::= 'sum' | 'count' | 'avg' | 'min' | 'max'
```

**Old (RFC-0025 §2):**
```
AggFunc      ::= 'sum' | 'count'
```

`count link`·`sum link.clicks`처럼 `avg link.clicks`·`min link.clicks`·
`max link.clicks`도 `Reference`가 두 조각(RowSet 바인딩 이름 + 필드)이다.
정규화 문자열(`Assignment.expression`에 싣는 `<func> <ref>`)의 `<func>` 자리에
`avg`/`min`/`max`가 그대로 들어간다 — 새 정규화 규칙이 필요 없다.

### 2. 정적 거부 — RFC-0025 §3 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0025 §Reference-level Specification/3의
**치환 후 최종 텍스트**다. `lower`에서 판정한다는 원칙(RFC-0025 §3 원문)은
불변이다.

| 거부 | 사유 |
|------|------|
| `count`의 `Reference`가 두 조각(`count link.clicks`) | `count`는 행 수를 세지 필드를 보지 않는다. 필드를 쓰고 싶다면 `sum`/`avg`/`min`/`max`다 |
| `sum`/`avg`/`min`/`max`의 `Reference`가 한 조각(`sum link`) | 넷 다 대상 필드가 필요하다 |
| `Aggregate`의 `Reference`가 가리키는 엔티티가 이 모듈에 선언되지 않음 | §4의 진단과는 다른 판정이다(RFC-0025 §4 원문 불변) — 여기서는 이름 자체가 미선언이라 어떤 `list`로도 결코 채울 수 없다 |
| **(갱신)** `sum`/`avg`의 필드 선언 타입이 Integer도 Money도 아님(Decimal, DateTime 등) | Decimal은 평가기가 없다(RFC-0015 §3과 동일 사유). DateTime의 합·평균은 이 RFC가 범위 밖에 둔다(§Guide-level Explanation, §Alternatives 2) |
| **(신설)** `min`/`max`의 필드 선언 타입이 Integer·DateTime·Money가 아님 | 순서 비교 평가기가 없다(RFC-0016 §3·RFC-0044 §5와 같은 사유) |
| `Aggregate` 할당 대상(`report.totalAmount`)의 엔티티를 워크플로가 `read`하지 않음 | RFC-0025 §3의 기존 규칙 그대로 — 바인딩이 존재할 수 없다 |
| `list`의 대상이 선언되지 않은 엔티티 | 여느 `RepositoryCall`과 같은 기존 판정 |

**변경 요약**: `sum`의 필드 타입 제약이 "Integer만"에서 "Integer 또는 Money"로
넓어졌고(RFC-0044가 Money에 평가기를 줬으므로), `avg`가 같은 제약을 새로
받으며, `min`/`max`는 Integer·DateTime·Money 셋을 받는 완전히 새로운 행이다.
`Aggregate`의 대상 엔티티 미선언·워크플로 미보유·`list` 대상 미선언 세 행은
문면 그대로 승계했다 — 이 RFC가 바꾸는 것이 아니다.

### 3. `avg`의 실행 의미 — RFC-0044 §4 소비

`avg <ref>`의 값은 `avg_round(sum(<ref>의 모든 값), count(RowSet))`이다 —
`avg_round`는 RFC-0044 §Reference-level Specification/4가 정의한 그 함수이고,
분자의 `sum`은 이 RFC §2가 확장한 그 `sum`과 같은 덧셈 규칙(Integer는 평범한
정수 덧셈, Money는 RFC-0044 §5의 같은-통화 규칙)을 쓴다.

**빈 RowSet(`count == 0`).** `avg_round`의 정의역 밖이다(RFC-0044 §4). 이 RFC는
그 경계를 `RunError`(`avg-of-empty-rowset`)로 실패시킨다 — `status: failed`,
`failed at: <스텝명>`, rc=1(RFC-0015 §4의 기존 실패 클래스).

### 4. `min`/`max`의 실행 의미 (신설)

`min <ref>`/`max <ref>`는 RowSet의 그 필드 값 중 가장 작은/큰 값이다. 순서는
필드의 선언 타입이 정한다 — Integer는 정수 순서, DateTime은 RFC-0016 §2의 i64
epoch-ms 인코딩을 통한 순서, Money는 RFC-0044 §5의 같은-통화 순서 비교(다른
통화가 섞이면 `RunError money-currency-mismatch`).

**빈 RowSet.** 최솟값·최댓값은 원소가 없으면 정의되지 않는다. `RunError`
(`min-max-of-empty-rowset`)로 실패시킨다 — `avg-of-empty-rowset`과 같은 층위의
결정이고, 같은 이유(§Guide-level Explanation의 "무음 실패를 만들지 않는다")다.

### 5. `sum`의 Money 확장

`sum <ref>`가 Money 필드를 가리킬 때, 값은 RowSet의 모든 행에서 그 필드의
minor-unit 정수(RFC-0044 §1)를 더한 합이다 — 통화는 첫 행이 정하고, 이후
행이 다른 통화를 내면 `RunError money-currency-mismatch`(RFC-0044 §5)다.
빈 RowSet은 RFC-0025 §Guide-level Explanation 원문 그대로 `0`이다 — 다만
Money의 "0"은 통화가 없으므로, 이 RFC는 그 경우의 결과 타입을 `{"amount":
"0", "currency": null}`로 정의한다(대상 필드가 이미 Money로 선언됐으므로
`update`가 그 값을 쓰는 것 자체는 §Reference-level Specification의 다른
규칙을 어기지 않는다 — 저장소 스키마가 `currency`의 널을 받아들이는지는
구현이 결정할 저장 계층의 문제이지 이 RFC가 여는 새 의미가 아니다).

### 6. spec 단언 — 새 어휘 없음

집계 결과는 `set`이 이미 출력 필드에 쓰므로, RFC-0025 §9가 세운 그대로 기존
`expect result <Reference> <op> <value>`(RFC-0012 §G12.7)가 단언한다 — 이
RFC가 여는 것은 그 `<value>` 자리에 쓰는 `MoneyLiteral`(RFC-0044 §3)뿐이다:

```
expect
    result report.totalAmount == 100.50USD
    result report.averageAmount == 50.25USD
```

### 7. 모드 B — 관측되지 않는 차원 (RFC-0025 §10 재확인, 갱신 없음)

RFC-0025 §10이 이미 세운 판단 — RowSet 값(그리고 그로부터 계산되는 집계 결과)은
RFC-0004의 네 관측 클래스 중 어느 것도 아니다 — 은 텍스트 변경 없이 `avg`/
`min`/`max`에도 그대로 적용된다. `_render_std`가 `Assignment` 효과를 이름
포인터로만 방출한다는 사실은 함수가 몇 개든 바뀌지 않는다(RFC-0025 §Alternatives
6이 이미 이 이유로 "모드 B가 집계 값을 계산한다"를 기각했다 — 그 기각은 `sum`/
`count`뿐 아니라 이 RFC가 여는 세 함수에도 그대로 성립한다). 그래서 이 절은
RFC-0025 §10을 **지목하지 않는다** — 지목은 텍스트를 바꿀 때만 필요하고, 이
RFC는 그 텍스트를 한 글자도 바꾸지 않는다.

## Examples

### 골든 시나리오 "Login" (RFC-0007 §6)

`Login` 워크플로는 `list`도 집계도 쓰지 않는다 — 정본을 참조만 하고 재정의하지
않는다. 골든 자체는 바뀌지 않는다(`examples/login.lir.json` 불변).

### 골든 인접 예제 — 결제 집계 (RFC-0007 §6, 골든이 다루지 않는 기능)

<!-- lnpl-check: skip — drift: RFC가 여는 `avg`/`min`/`max` 집계 문법이 컴파일러에 구현돼 있지 않다(컴파일러: "unsupported operand form 'avg payment.amount' ... a value is `<operand>` or `<operand> +|- <operand>` — RFC-0015 does not nest arithmetic"). `sum`/`count`만 피연산자 형태로 인식되고 avg/min/max는 문법 자체가 없다 — 조각도 자리표시자도 아니다, RFC가 주장하는 문법을 컴파일러가 아직 못 받는다. 독립 재현: entity를 온전히 선언한 별도 스니펫으로도 `max`/`min`이 같은 "unsupported operand form" 오류로 거부됨을 확인(.orchestration/verify/t2-doc-snippet-gate.md 참조) -->
```lnpl
capability postgres

entity Payment
    field
        id UUID
        amount Money

entity Report
    field
        id UUID
        totalAmount Money
        averageAmount Money
        largestAmount Money
        paymentCount Integer

service Analytics
    policy
        timeout 5s

workflow SummarizePayments
    find report
    list payment
    set report.totalAmount to sum payment.amount
    set report.averageAmount to avg payment.amount
    set report.largestAmount to max payment.amount
    set report.paymentCount to count payment
    update report
    spec
        given
            stored Report id 1
            stored Payment[0] amount 100.00USD
            stored Payment[1] amount 50.50USD
            stored Payment[2] amount 33.75USD
        when
            summarizePayments
        expect
            completed
            result report.totalAmount == 184.25USD
            result report.averageAmount == 61.42USD
            result report.largestAmount == 100.00USD
            result report.paymentCount == 3
```

`184.25 / 3 = 61.41666...` → minor units `6141.666...` → half-to-even이
`6142`로 반올림한다(`.666`은 동점이 아니라 5보다 크므로 올림 — half-to-even과
"5보다 크면 올림"이 갈리는 것은 정확히 동점(`.5`)일 때뿐이다).

### 동점 반올림 — half-to-even이 절삭과 갈리는 지점

<!-- lnpl-check: skip — fragment: 조각: workflow 선언 없이 spec의 given/expect 자리만 보여줌(컴파일러: 'spec' appears before any declaration) -->
```lnpl
    spec
        given
            stored Report id 2
            stored Payment[0] amount 1.00USD
            stored Payment[1] amount 2.00USD
        when
            summarizePayments
        expect
            completed
            result report.averageAmount == 1.50USD
```

`3.00 / 2`는 정확히 `1.50`이므로 반올림 자체가 필요 없다 — half-to-even의
동점 규칙이 실제로 갈리는 자리는 minor-unit 몫이 `.5`로 끝날 때다(예: 총합
`101` minor units를 `2`로 나누면 `50.5` → 짝수인 `50`으로). 그 케이스는
구현의 계약 스위트가 실측한다(이 RFC는 규칙만 정한다).

### 빈 RowSet — `avg`/`min`/`max`는 실패, `sum`/`count`는 0

<!-- lnpl-check: skip — fragment: 조각: workflow 선언 없이 spec의 given/expect 자리만 보여줌(컴파일러: 'spec' appears before any declaration) -->
```lnpl
    spec
        given
            stored Report id 3
        when
            summarizePayments
        expect
            failed
```

`Payment`를 하나도 시드하지 않으면 `list payment`가 빈 RowSet을 바인딩하고,
`sum`(0)·`count`(0)는 계산되지만 그다음 `avg`가 `avg-of-empty-rowset`으로
실패한다 — 워크플로 전체가 `failed`로 끝난다(RFC-0015 §4의 기존 실패 계약,
새 결과 클래스 없음).

### 정적 거부 — DateTime `sum`, 미지원 타입의 `min`/`max`

<!-- lnpl-check: skip — fragment: 조각: entity Session은 선언되지만 집계 대상 entity Report가 선언되지 않음(컴파일러: assignment target 'report.total' names 'report', which is not a declared entity) -->
```lnpl
entity Session
    field
        id UUID
        startedAt DateTime
        label Text

workflow BadSummary
    list session
    set report.total to sum session.startedAt      # DateTime sum — 거부
    set report.first to min session.label           # Text min — 거부
```

두 거부 다 §Reference-level Specification/2의 표대로 — 앞은 "합이 의미 없음",
뒤는 "순서 비교 평가기가 없음"(RFC-0016 §3과 같은 사유, Text에는 순서가 없다).

## Alternatives

| # | 검토한 대안 | 기각 사유 |
|---|------------|----------|
| 1 | **`group by`를 함께 연다** | 이슈 #145는 avg/min/max만 요구한다. `group by`는 다중 그룹의 RowSet 표현이라는 별도 설계 질문이고(RFC-0038 §Open Questions 1이 이미 이렇게 갈라 적었다), 그룹 경계를 나누는 새 IR 개념이 필요하다 — 이번 RFC의 크기를 넘는다. RFC-0038 §Open Questions 1의 그 절반은 그대로 이월한다 |
| 2 | **`avg`(DateTime)도 함께 연다** | "평균 시각"의 소비 시나리오가 이슈에도 실측에도 없다 — `min`/`max`(DateTime)는 "가장 이른/늦은 이벤트"라는 흔한 질의 형태가 명확하지만, `avg`(DateTime)는 요구가 측정되지 않았다(measured-need 게이트, RFC-0025 §Alternatives 6과 같은 태도: "세우지도 않은 요구를 충족시키는 일이다"). 요구가 생기면 §Reference-level Specification/2의 표에 행 하나를 더하는 작은 후속 RFC로 충분하다 |
| 3 | **빈 RowSet의 `avg`/`min`/`max`가 0(또는 부재)을 낸다** | `sum`/`count`의 0은 "더할 것도 셀 것도 없다"는 자연스러운 항등원이지만, 평균·최댓값·최솟값에는 그런 항등원이 없다 — 0을 반환하면 "평균이 실제로 0인 행 집합"과 "행 집합이 비었다"를 구별할 수 없게 된다. `list` 없는 집계가 이미 경고를 내는 것(RFC-0025 §4)과 같은 원칙 — 조용한 오해를 부르는 값보다 명시적 실패를 택한다 |
| 4 | **`avg`도 `/`(RFC-0028)와 같은 절삭 규칙을 쓴다** | RFC-0044 §Reference-level Specification/4·§Alternatives 6이 기각한 것과 같은 이유 — 절삭은 평균을 체계적으로 낮추는 편향을 만들고, 금융 집계의 실무 관행은 half-to-even이다 |
| 5 | **`min`/`max`가 Money를 받되 통화 불일치를 컴파일 타임에 거부** | RFC-0044 §Reference-level Specification/5·§Alternatives 5가 이미 기각한 것과 같다 — 통화는 행 데이터이므로 정적으로 알 수 없다 |

## Open Questions

1. **`group by`.** §Alternatives 1이 이월한 것 그대로 — RFC-0038 §Open
   Questions 1의 나머지 절반이다. 다중 그룹의 RowSet 표현(그룹 경계를 어느
   IR 개념으로 표시할지, `Aggregate`가 그룹마다 하나씩 결과를 내는 형태를
   어떻게 `set`의 단일 값 계약과 조화시킬지)이 먼저 정해져야 한다.
2. **`avg`(DateTime).** §Alternatives 2가 이월한 것 그대로 — 소비 시나리오가
   실측되면 §Reference-level Specification/2의 표에 행을 더하는 것으로 닫힌다.

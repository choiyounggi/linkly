# RFC-0056: 가드의 Text·enum 등가 비교

## Status

- Status: Draft
- Updates: RFC-0016 §Reference-level Specification/3. 피연산자의 차원 규칙,
  RFC-0038 §Reference-level Specification/3. 등가 비교의 타입 규칙,
  RFC-0015 §Reference-level Specification/3. 정적 거부,
  RFC-0001 §노드 카탈로그/Guard

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목하고, 규칙 5(연쇄 갱신)에 따라 이미
갱신된 절은 대상과 **직전 갱신 RFC를 모두** 지목한다. 이 RFC는 Draft이므로 대상
RFC에 `Updated-by:` 포인터를 달지 않는다(Accepted가 되는 시점의 일이다).

- **차원 규칙(RFC-0016 §3)과 등가 비교의 타입 규칙(RFC-0038 §3).** RFC-0038 §3이 3.1을
  붙였고, Draft RFC-0051 §1이 본문을, Draft RFC-0055 §6이 3.2를 갱신하는 중이다. 아래
  §6의 최종 텍스트는 RFC-0055 §6의 최종 텍스트 **위에** 3.3 한 항을 더하고, 이 RFC로
  거짓이 되는 두 문장(합성 타입 문단의 "여전히 컴파일 거부", 3.1 끝 문단의 "가드에서
  비교하면 여전히 컴파일 거부")을 고친 것이다. 3.1을 고치므로 RFC-0038 §3도 지목한다.
- **정적 거부(RFC-0015 §3).** Draft RFC-0051 §2와 Draft RFC-0055 §7이 갱신하는 중이다.
  아래 §7의 최종 텍스트는 RFC-0055 §7의 표 **위에** 한 행을 고치고 세 행을 더한 것이다.
- **노드 카탈로그/Guard(RFC-0001).** RFC-0028 §3이 갱신한 행이다(RFC-0001 머리의
  `Updated-by: RFC-0028 (§노드 카탈로그/Guard)`). 이 RFC가 Guard 노드에 선택 필드
  `textEqualityOperands`를 더하므로 RFC-0001과 RFC-0028을 함께 지목한다. 아래 §2가 그
  행의 치환 후 최종 텍스트다.

Draft끼리의 순서: 위 Draft 중 먼저 Accepted되는 쪽이 직전 갱신이 되고, 나중 쪽이 승격할
때 그 사실을 `Updates:`에 반영한다(RFC-0051·RFC-0052 선례와 같다).

지목하지 **않는** 것:

- RFC-0015 §4 / RFC-0028 §2(값 도메인과 실패 표). Text 등가 항은 수치 평가기를 거치지
  않으므로 "비수치 값의 비교 → `RunError`" 행의 대상이 아니다 — 그 행은 수치 비교에
  그대로 남는다. 한쪽 참조가 해소되지 않으면 그 비교는 거짓이라는 행이 Text 등가 항에도
  똑같이 적용된다. 새 실패 클래스는 없다.
- RFC-0028 §6(Mode B). 모드 B가 이 비교를 담은 워크플로를 거부하는 것은 RFC-0055 §10과
  같은 방식으로 이 RFC의 §5에 둔다 — 모드 B가 컴파일하는 가드의 규칙은 바뀌지 않는다.
- RFC-0012 §G12.1(참조의 해소). 맨이름이 payload 필드라는 규칙은 그대로다. 이 RFC가
  더하는 것은 "Text류 필드와 짝지어진 등가 항 안의 맨이름"이라는 한 자리뿐이고, 그 자리는
  `Condition`이 아니라 §6 3.3이 정한다.

## Motivation

issue #207. 주문 상태처럼 문자열 열거값으로 흐름을 가르는 것 — 상태 전이 — 을 가드로
쓸 수 없었다. 2026-10-02 QA에서 `CancelOrder`가 이미 취소된 주문을 다시 취소해도 막을
수 없었다(200 `cancelled`가 두 번). "pending일 때만 결제", "paid일 때만 환불" 같은 규칙을
쓸 자리가 없었다.

```
compile error: workflow CancelOrder: 'order.status == input.expected' uses order.status, whose declared type OrderStatus is neither Integer nor DateTime — RFC-0016 computes over whole numbers and instants only (...)
```

우회는 상태를 정수 코드(0/1/2)로 선언하는 것이었는데, 그러면 `enum` refinement의 검증·
OpenAPI 열거·가독성을 잃는다. `spec`도 같은 제약이었다: `result o.status == paid`가
`Cannot compare non-numeric o.status='pending'`으로 실패해 상태값을 단언할 수 없었다.

같은 비교가 `list where`에서는 이미 된다. RFC-0038이 등가를 `list where`에 한해
열면서 이유를 적었다 — 순서 비교에는 평가기가 필요하지만(Text에 `<`가 없다) 등가는
두 값이 같은지만 묻는다. 그리고 범위를 명시했다: "이 좁힘은 **`list where`에만**
적용된다 — 가드 조건의 등가(…)는 위 표(차원 규칙)로만 판정되고, Text 필드를 가드에서
비교하면 여전히 컴파일 거부다." 가드 쪽은 미뤄 둔 것이지 기각한 것이 아니다. 이 RFC가 그
유보를 가드에 대해 푼다.

## Guide-level Explanation

가드(`when`/`until`, `or` 대안 포함)는 이제 Text류 필드를 `==`/`!=`로 비교할 수 있다.
Text류는 선언 타입의 base가 `UUID`, `Email`, `Phone`, `Currency`, `Html`, `Markdown`,
`Text` 중 하나인 필드다 — 그런 base의 `enum` refinement도 포함된다. `Password`는 빠진다:
가드가 건너뛰어지면 스킵 레코드(`skipped[].evaluations`)가 비교한 두 값을 싣는데,
RFC-0001은 Password 값을 어디서든 가리라고 요구한다. 비교 자체를 막는 것이 그 값이 새
출력 채널로 나가지 않게 하는 가장 단순한 방법이다. `DateTime`은 이미 자기 차원(`instant`)이
있으므로 이 RFC와 무관하다.

```lnpl
refine OrderStatus of Text
    enum pending paid cancelled

entity Order
    field
        id UUID
        status OrderStatus

workflow CancelOrder
    find order
    when order.status != cancelled
    pipeline
    format order.status from "cancelled"
    update order
```

가드는 다음 항목 하나만 소유하므로 두 스텝을 `pipeline`으로 묶었다. 이미 `cancelled`인
주문에서는 둘 다 건너뛴다.

비교의 상대쪽은 둘 중 하나다.

- **참조** — `input.<field>` 또는 `<binding>.<field>`. 둘 다 선언 타입을 알면 base가 같아야
  한다(RFC-0038 D2와 같은 규칙). `order.status == customer.id`(Text 대 UUID)는 거부다.
- **맨이름 리터럴** — `paid`처럼 점이 없는 이름. 상대쪽이 선언 타입을 아는 Text류 필드일
  때만 리터럴이고, 그 이름의 글자 그대로와 비교된다. 상대쪽 필드가 `enum` refinement면
  리터럴은 그 멤버여야 한다:

  ```
  when order.status == shipped
  → compile error: workflow CancelOrder: 'order.status == shipped' compares with 'shipped', which is not a member of the enum OrderStatus (members: pending, paid, cancelled) (RFC-0056)
  when order.status == paidd
  → ... which is not a member of the enum OrderStatus (members: pending, paid, cancelled) — did you mean 'paid'? (RFC-0056)
  ```

  멤버 목록은 항상 나온다. `did you mean`은 가까운 멤버가 있을 때만 붙는다. 평범한
  `Text`(enum 아님)면 어떤 맨이름도 리터럴로 받는다.

맨이름이 리터럴이 되는 자리는 이 하나뿐이다. 그 밖의 모든 자리에서 맨이름은 오늘과 똑같이
payload 필드다 — `when stock == available`은 두 payload 값을 숫자로 비교한다. 그래서 Text
등가 항 안에서 payload를 읽으려면 `input.<field>`로 쓴다(`order.status == input.expected`).
이 판정은 컴파일러가 한 번 내리고 IR에 적는다(§2). 런타임은 그 기록을 읽을 뿐 값을 보고
다시 추측하지 않는다.

순서 비교(`<`, `<=`, `>`, `>=`)는 Text류에서 여전히 컴파일 거부다. Text류 필드는 산술의
피연산자도 될 수 없다. `and`로 다른 항(숫자·시각·Money)과 잇는 것과, `or` 대안 줄에 쓰는
것은 다른 항과 똑같이 된다.

`spec`의 `result <ref> == <값>`과 `!=`도 같은 규칙으로 평가된다 — `result order.status ==
cancelled`가 저장된 상태를 단언한다. 모드 B(`lnpl build`, `lnpl diff`)는 이런 가드를 담은
워크플로를 RFC-0056을 대며 거부한다. Text 값에는 i64 인코딩이 없다.

덧붙여 `set order.status to paid`(또는 `to "paid"`)의 거부 문면이 Text를 쓰는 방법을
알려 준다: `write a Text field with format order.status from "..."`. 동작은 그대로
거부다(`set`에는 Text 평가기가 없다). 이 안내는 base가 정확히 `Text`인 필드에만 붙는다 —
`format`도 그 필드만 쓸 수 있다.

## Reference-level Specification

### 1. 대상 타입

Text류 base 집합 = `refinements.BASE_CATEGORY`가 `"text"`인 base에서 `DateTime`과
`Password`를 뺀 것 = `UUID`, `Email`, `Phone`, `Currency`, `Html`, `Markdown`, `Text`.
필드의 base는 선언 타입이 refinement면 그 refinement의 base다(한 단계, `base_of`). 이
집합은 컴파일러(`lower.TEXT_EQUALITY_EXCLUDED_BASES`), 모드 B 검출
(`backend._TEXT_EQUALITY_BASES`), `spec` 판정(`spec._TEXT_EQUALITY_BASES`)에서 같다.

### 2. 노드 카탈로그 `Guard` 행 — RFC-0001 §노드 카탈로그/Guard 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0001 "### 노드 카탈로그" 절 **Behavior** 표의
`Guard` 행에 대한 치환 후 최종 텍스트다(RFC-0028 §3의 텍스트 포함). 다른 kind의 행과 표
서두의 산문은 그대로다.

| kind | 필수 필드 | 선택 필드 | children 허용 |
|------|----------|----------|--------------|
| Guard | `mode`(`when`\|`until`\|`repeat` — 닫힌 enum) | `condition`(`when`·`until` 전용 — 조건 서술), `count`(`repeat` 전용 — 1 이상 정수), `alternatives`(`when` 전용, 배열, 1개 이상의 문자열 — `or`로 이어지는 대안 조건 서술. RFC-0028 신설), `textEqualityOperands`(배열의 배열 — `[condition, *alternatives]`와 같은 순서로 각 서술마다 하나, Text 등가 항(RFC-0016 §3 3.3)의 피연산자 이름을 중복 없이 정렬한 문자열 배열. 그런 항이 없는 서술은 빈 배열. 어느 서술에도 없으면 필드 자체가 없다. RFC-0056 신설) | 피가드 항목 1개(WorkflowStep, Concurrency, Pipeline 중 하나). 실행 의미는 RFC-0014 §2. 2026-07-31 신설(RFC-0002 부록 A.4-① 해소), 2026-08-24 `alternatives` 추가(RFC-0028, 이슈 #93), 2026-10-04 `textEqualityOperands` 추가(RFC-0056, 이슈 #207) |

`textEqualityOperands`는 컴파일러가 쓰는 필드다. 그 안의 이름은 참조(`order.status`,
`input.expected`)이거나 맨이름 리터럴(`paid`)이다 — 어느 쪽인지는 이름에 점이 있는지로
갈린다. Text 등가를 쓰지 않는 가드의 IR은 이 RFC 전과 바이트 단위로 같다.
`schemas/lir.schema.json`의 `nodeGuard`가 이 필드를 선택 속성으로 받는다.

### 3. 모드 A 평가

가드의 `==`/`!=` 항은 그 서술의 `textEqualityOperands` 항목에 피연산자 이름이 하나라도
있으면 Text 등가 항이다. 그 항은:

- 맨이름 피연산자를 그 이름의 글자 그대로 읽고, 점 있는 피연산자를 `resolve_reference`로
  해소한다(가드가 쓰는 같은 해소기, RFC-0012 §G12.1).
- 두 값을 그대로 비교한다 — `==`는 같을 때, `!=`는 다를 때 참이다. 수치 평가기
  (`eval_value`)를 거치지 않는다.
- 한쪽이라도 해소되지 않으면(`null`) 거짓이다. `==`와 `!=` 모두 같다 — 수치 비교의 "참조
  미해소 → 양쪽 다 거짓" 규칙(RFC-0015 §4)과 같다.
- 스킵 레코드의 `evaluations`에 다른 비교와 같은 모양 `{"ref", "value", "op", "expected",
  "holds"}`로 들어간다. `ref`는 왼쪽 피연산자의 글자, `value`/`expected`는 왼쪽/오른쪽의
  읽은 값이다. 마스킹은 다른 항목과 같은 경로를 지난다 — Password는 컴파일 단계에서
  빠지므로 이 경로에 가릴 값이 오지 않는다.

`textEqualityOperands`가 없는 가드의 평가는 이 RFC 전과 같다.

### 4. `spec`의 `result`

`result` 서술에는 Guard 노드가 없으므로 기록을 읽을 수 없다. 그래서 `spec`은 같은 짝짓기를
문서에서 판정한다: `==`/`!=` 항의 피연산자 중 **점 있는** 참조가 문서에서 Text류 필드로
해소되면(§1, `input.<field>`는 마지막으로 선언한 엔티티 기준) 그 항은 Text 등가 항이고 §3과
같이 평가된다. 맨이름만으로는 Text 등가 항이 되지 않는다 — `result qty == cap`은 두 payload
값의 수치 비교로 남는다. Text 등가 항의 상대쪽이 참조가 아니면(숫자 리터럴, 산술식) 그
기대는 `unsupported result expectation`으로 실패한다. `result`에는 enum 멤버 검사가 없다 —
멤버가 아닌 리터럴은 그냥 거짓이다.

### 5. 모드 B

모드 B(`lnpl build`, `lnpl diff`)는 가드(서술이든 `or` 대안이든)가 Text류 필드를 읽는
워크플로를 RFC-0056을 대며 거부한다. Text 값에는 모드 B가 조건 필드를 받는 i64 인코딩이
없다. 검출은 문서에서 한다: 엔티티의 기본 바인딩과 `create ... as <이름>` 별칭의 Text류
필드, 그리고 마지막으로 선언한 엔티티 기준 Text류인 `input.<field>`(컴파일러의
`declared_fields`와 같은 규칙)를 읽는 가드다. 컴파일러가 가드에서 Text류 필드를 받는 자리는
§6 3.3의 등가 항뿐이므로 이 검출은 그 항과 같다.

거부 순서는 `build`와 `diff`가 같다(issue #185): Money 가드(RFC-0051) → 조회 키(RFC-0052)
→ `optional` 필드 가드(RFC-0055) → Text 등가 가드(이 RFC). 앞선 것이 먼저 거부한다. 모드 B
도구가 없어도 같은 거부가 먼저 나온다.

### 6. 피연산자의 차원 규칙 — RFC-0016 §3 / RFC-0038 §3 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래 인용은 RFC-0016 §Reference-level Specification/3의
치환 후 최종 텍스트다(RFC-0038이 붙인 3.1, Draft RFC-0051 §1, Draft RFC-0055 §6의 텍스트
포함). 인용 안의 "RFC-0015"는 RFC-0015 §3을 가리킨다. RFC-0055 §6의 인용과 다른 곳은
셋이다: 합성 타입 문단 끝에 한 문장을 더했고, 3.1 끝 문단의 "Text 필드를 가드에서 비교하면
여전히 컴파일 거부다"를 3.3을 가리키는 문장으로 고쳤고, 3.3을 새로 붙였다.

> RFC-0015의 "Integer 한정"을 **차원 규칙**이 대체한다.
>
> - `instant` — 선언 타입이 `DateTime`이거나 base가 `DateTime`인 refinement
> - `scalar` — `Integer`, base가 `Integer`인 refinement, 정수 리터럴, **Duration 리터럴**
> - `money` — 선언 타입이 `Money`이거나 base가 `Money`인 refinement (RFC-0051)
>
> | 식 | 결과 |
> |----|------|
> | `instant - instant` | `scalar` (경과 밀리초) |
> | `instant + scalar`, `instant - scalar` | `instant` |
> | `scalar ± scalar` | `scalar` |
> | `instant + instant` | **컴파일 거부** |
> | `money ± money` | `money` |
> | `money * scalar`, `scalar * money` | `money` |
> | `money * money`, `money / X`, `X / money` | **컴파일 거부** |
> | `money ± scalar`, `money ± instant`, `scalar ± money`, `instant ± money` | **컴파일 거부** |
> | `<X> <cmp> <Y>`, `dim(X) == dim(Y)` | 허용 |
> | `<X> <cmp> <Y>`, `dim(X) != dim(Y)` | **컴파일 거부** |
> | `set <T> to <E>`, `dim(T)`와 `dim(E)`가 둘 다 정해지고 다르다 | **컴파일 거부** (RFC-0051) |
>
> 선언 타입을 문서에서 알 수 없는 피연산자(맨이름, 네트워크 결과 참조)는 어느
> 차원도 아니며, 오늘과 같이 정적 검사를 통과하고 런타임이 판정한다. 이 규칙이
> 기존에 컴파일되던 프로그램에 만드는 **신규 거부는 표의 마지막 행 하나뿐이다** —
> `set` 대상과 값의 차원이 다른 경우(예: DateTime 필드에 Integer 식을 넣는
> 것)로, 이전에는 정적 검사를 통과한 뒤 런타임에 잘못된 값을 저장했다. RFC-0051
> 시점에 저장소의 모든 `set` 줄(`examples/*.lnpl`, `impl/tests/*.py`, 50건)을 전수
> 분류해 이 행에 걸리는 기존 프로그램이 0건임을 확인했다.
>
> 이 규칙이 t2 F-5 ③(`payment.createdAt <= 43200m`)을 `instant` vs `scalar`로 거부한다.
> RFC-0015도 이 형태를 거부했으나 사유가 "DateTime은 평가기가 없다"였다. 이제 평가기가
> 있으므로, 거부 사유는 **두 양이 같은 종류가 아니라는 것**이다. `money`도 같다:
> `when payment.fee > 0`은 "평가기 없음"이 아니라 `money` 대 `scalar` 불일치로 거부된다.
>
> `Money`의 통화는 타입이 아니라 행 데이터이므로 **정적 차원은 통화를 구분하지
> 않는다** — 같은 `money` 차원의 두 값이 다른 통화인지는 런타임이 판정한다
> (RFC-0044 §5).
>
> `Decimal`·`Text`·`Password`와 그 밖의 합성 타입은 여전히 어느 차원도 아니며 컴파일
> 거부다(RFC-0015 §D6 유지, Decimal은 RFC-0044 §Open Questions 3). 단 가드의
> `==`/`!=`는 Text류 필드에 대해 아래 3.3이 연다.
>
> #### 3.1 `list where`의 등가 비교 (RFC-0038)
>
> 위 표의 마지막 두 비교 행(`dim(X) == dim(Y)`이면 허용, 다르면 거부)은 `list
> where`에서는 **좌변이 Integer나 DateTime일 때**의 규칙이다. `list <Entity> where
> <cond>`(RFC-0038)의 좌변은 나열 대상 엔티티 자신의 선언 필드이므로 항상 구체적인
> 선언 타입을 갖는다 — 그 타입이 Integer도 DateTime도 아닐 때(UUID, Text, Email,
> Money 등), 순서 비교(`<`/`<=`/`>`/`>=`)는 컴파일 거부다(등가와 달리 순서에는
> 평가기가 필요하다 — Text에 `<`가 없다는 원 규칙의 근거는 그대로 유효하고, Money의
> 순서 평가기는 드라이버 푸시다운에 없다). RFC-0051의 `money` 차원은 가드와 `set`에만
> 열린다 — `list where`와 `expose list ... by`는 Money를 이 RFC 이전과 똑같이 다룬다.
>
> 하지만 등가(`==`/`!=`)는 평가기를 요구하지 않는다 — 두 값이 같은지는 비교
> 연산자 없이도 판정된다. 그래서 `list where`의 등가는 차원이 아니라 **선언
> 타입 자체의 일치**로 판정한다: 좌변 필드의 base 타입과 우변이 이름하는
> 필드의 base 타입이 같으면(둘 다 Text든, 둘 다 UUID든) 허용, 다르면 거부.
> 우변이 정적으로 알 수 없는 것(맨 `input.<field>`처럼 선언 타입이 문서에
> 없는 경우)은 원 규칙과 같이 판정을 런타임으로 미룬다.
>
> 이 좁힘은 **`list where`에만** 적용된다 — 가드 조건의 등가는 위 표(차원 규칙)와
> 아래 3.3으로 판정된다. 3.3은 같은 base 일치 규칙을 가드로 가져오지만 대상 base를
> 더 좁게 잡는다(Money·Password 제외). `list where`는 `Condition` 문법을 재사용하지만,
> 그 판정 함수(`lower._check_list_predicate`)는 가드의 판정 함수
> (`lower._check_dimensions`)와 별개이므로 한쪽을 넓혀도 다른 쪽은 조용히 넓어지지
> 않는다.
>
> #### 3.2 `optional` 필드의 존재 검사 (RFC-0055)
>
> `exists`/`missing`은 값을 평가하지 않고 키가 있는지만 본다. 그래서 피연산자가
> `optional`로 선언된 필드(RFC-0001 §노드 카탈로그/Entity)이면 **선언 타입과 무관하게**
> 존재 검사를 허용한다 — Text·Money·합성 타입도 포함된다. 값이 `null`이면 키가 없는
> 것과 같이 `missing`이다. `optional`이 아닌 필드의 존재 검사는 위 규칙 그대로다.
> 이 예외는 존재 검사에만 있다. `optional` 필드를 비교·산술에 쓰는 것은 위 표가
> 그 선언 타입대로 판정한다.
>
> #### 3.3 가드 조건의 Text 등가 비교 (RFC-0056)
>
> `when`/`until` 서술과 `or` 대안의 `==`/`!=` 항은, 한쪽 피연산자가 base가 Text류(UUID,
> Email, Phone, Currency, Html, Markdown, Text — 그 base의 refinement 포함)인 선언 필드를
> 직접(산술식 밖에서) 가리키면 **Text 등가 항**이다. 그 항은 이렇게 판정한다:
>
> - 상대쪽이 선언 타입을 아는 참조면 두 base가 같아야 한다(3.1과 같은 규칙). 선언 타입을
>   문서에서 알 수 없는 참조(네트워크 결과 등)는 판정을 런타임으로 미룬다.
> - 상대쪽이 맨이름(점 없는 이름)이면 그것은 **리터럴**이고 이름의 글자 그대로와
>   비교한다. 이 자리 밖의 맨이름은 오늘과 같이 payload 필드다. Text류 필드의 선언 타입이
>   `enum` refinement면 리터럴은 그 멤버여야 하며, 아니면 컴파일 거부다(멤버 목록을 대고,
>   가까운 멤버가 있으면 제안한다).
> - 상대쪽이 숫자 리터럴이거나 Text류가 아닌 차원의 참조면 컴파일 거부다(같은 종류가
>   아니다).
> - 어느 쪽이든 산술식이면 컴파일 거부다 — Text에는 산술이 없다.
>
> `Password` base 필드는 이 항에 쓸 수 없다(RFC-0001의 마스킹 의무 — 가드 스킵 레코드가
> 비교한 값을 싣는다). `DateTime`은 `instant` 차원 그대로다. 순서 비교(`<`/`<=`/`>`/`>=`)는
> Text류에서 위 규칙대로 컴파일 거부다. Text 등가 항은 `and`로 다른 항과 이을 수 있고 `or`
> 대안에도 쓸 수 있다.

### 7. 정적 거부 — RFC-0015 §3 갱신 (치환 후 최종 텍스트)

> 문법이 받되 문서를 보면 거부되는 형태들이다. 전부 `lower`에서 판정한다 — 문서만으로
> 결정 가능한 것을 런타임까지 미루면 t2 F-4처럼 인터프리터 내부의 원시 예외가 조작자에게
> 샌다.
>
> | 거부 | 사유 |
> |------|------|
> | 양변이 모두 리터럴(`1 < 2`) | 아무것도 결정하지 않는 가드는 저작 오류다 |
> | 선언 타입이 어느 차원(RFC-0016 §3: Integer·DateTime·Money)도 아닌 피연산자 | 평가기가 없다. 실측: `payment.amount`(Money) 가드가 경고 없이 컴파일된 뒤 `TypeError: '<=' not supported between instances of 'dict' and 'int'`로 죽었다(t2 F-4). Money는 RFC-0051부터 차원이 있으므로 이 행이 아니라 차원 불일치 행으로 판정된다. Decimal은 여전히 이 행이다. 가드 `==`/`!=`의 Text류 필드는 이 행이 아니라 RFC-0016 §3 3.3으로 판정된다(RFC-0056) |
> | 차원 규칙(RFC-0016 §3)이 거부하는 식·비교·할당 | 두 양이 같은 종류가 아니다 — 인스턴트와 숫자, Money와 숫자, Money와 Money의 곱·몫 |
> | `optional`이 아닌 선언된 Money 필드에 `exists`/`missing` | RFC-0051이 여는 부분집합은 비교와 산술이다. 존재 검사는 열지 않는다(RFC-0051 §Reference-level Specification/7). `optional` Money 필드의 존재 검사는 RFC-0016 §3 3.2가 연다(RFC-0055) |
> | `input.<field>`의 `<field>`를 어떤 엔티티도 선언하지 않음 | payload는 선언된 전 엔티티 필드의 합집합이다. 그 밖의 이름은 오타다 |
> | 엔티티명 `Input` | 바인딩 이름이 `input` 네임스페이스와 충돌한다 |
> | 할당 대상이 `input.…` 또는 맨이름 | 입력은 이 워크플로가 소유한 상태가 아니다 |
> | 할당 대상 엔티티를 워크플로가 read하지 않음 | 바인딩이 존재할 수 없다(RFC-0012 §G12.5와 같은 사유) |
> | 앞선 스텝이 할당한 Reference를 뒤의 가드가 읽음 | 모드 B는 조건 필드를 진입 시 i64 파라미터로 고정 받는다. 그런 프로그램은 두 모드가 다른 값을 본다 |
> | `and` 안의 `exists`/`missing` | §1의 두 채널 사유 |
> | `input.<field>`에 `exists`/`missing`, 그 `<field>`를 선언한 엔티티가 둘 이상인데 `optional` 표시가 엇갈림 | 존재 검사의 허용 여부(RFC-0016 §3 3.2)가 엔티티마다 다르다. 어느 엔티티의 선언을 따를지 정할 근거가 없으므로 선언한 엔티티를 모두 대고 거부한다(RFC-0055) |
> | `Password` base 필드를 가드의 `==`/`!=`에 씀 | RFC-0001의 마스킹 의무 — 가드 스킵 레코드가 비교한 값을 싣는다(RFC-0056) |
> | 가드 등가의 맨이름 리터럴이 상대쪽 `enum` refinement의 멤버가 아님 | enum은 닫힌 값 집합이다(RFC-0011) — 멤버가 아닌 리터럴은 항상 거짓이므로 저작 오류다(RFC-0056) |
> | 가드의 Text 등가 항 어느 쪽이든 산술식 | RFC-0016은 Text에 산술을 주지 않는다 — 평가기가 없다(RFC-0056) |

바뀐 것은 넷이다: "어느 차원도 아닌 피연산자" 행의 사유 끝에 3.3을 가리키는 문장을
더했고, 맨 아래 세 행이 새로 생겼다. 나머지 행은 RFC-0055 §7과 글자 단위로 같다.

## Examples

### 골든 시나리오 "Login" (RFC-0007 §6)

골든 시나리오는 Text 등가 가드를 쓰지 않는다. 이 RFC 뒤에도 `examples/login.lnpl`의 IR,
OpenAPI, 모드 B 출력은 바이트 단위로 같다.

### 골든 인접 예제 — issue #207 주문 취소 (RFC-0007 §6, 골든이 다루지 않는 기능)

커밋되는 예제 파일이 아니라 이 RFC 본문의 설계 예시다. 값은 모두 지어낸 것이다. issue의
원문 소스와 다른 점은 `Order`가 `expected` 필드를 하나 더 선언한다는 것뿐이다 —
`input.expected`의 `expected`를 어떤 엔티티도 선언하지 않으면 RFC-0015 §3의 "`input.<field>`의
`<field>`를 어떤 엔티티도 선언하지 않음" 행이 먼저 거부한다. issue 원문 그대로의 소스는 이제
타입 규칙이 아니라 그 행의 문면으로 거부된다:

```
compile error: workflow CancelOrder: 'order.status == input.expected' names input field 'expected', which no entity declares (declared fields: id, status)
```

```lnpl
refine OrderStatus of Text
    enum pending paid cancelled

entity Order
    field
        id UUID
        status OrderStatus
        expected OrderStatus

service OrderService

workflow CancelOrder
    find order
    when order.status == input.expected
    update order
```

컴파일된 Guard 노드(발췌):

```json
{"kind": "Guard", "mode": "when", "condition": "order.status == input.expected",
 "textEqualityOperands": [["input.expected", "order.status"]]}
```

| 저장된 `status` | payload `expected` | 결과 |
|-----------------|--------------------|------|
| `pending` | `pending` | 가드 참, `update order` 실행 |
| `cancelled` | `pending` | 가드 거짓, `skipped[0].evaluations = [{"ref": "order.status", "value": "cancelled", "op": "==", "expected": "pending", "holds": false}]` |
| `pending` | (없음) | 가드 거짓 — 해소되지 않은 참조 |

`spec` 블록 — Guide-level Explanation의 `CancelOrder`(상태를 `cancelled`로 쓰는 쪽) 안에 둔다:

```
    spec
        given
            valid order
            stored order status pending
        when
            cancel order
        expect
            result order.status == cancelled
```

### 컴파일 거부

```
when order.status < paid              → ... declared type OrderStatus is neither Integer nor DateTime ...
when order.status == shipped          → ... not a member of the enum OrderStatus (members: pending, paid, cancelled) (RFC-0056)
when order.status == order.ownerId    → ... equality needs the same declared type on both sides (RFC-0038 D2, extended to guard conditions by RFC-0056)
when order.status == 5                → ... RFC-0016 compares like with like ...
when order.status == order.stock + 1  → ... compares a Text-family field with an arithmetic expression ... (RFC-0056)
when order.secret == hunter           → ... compares order.secret, a Password field (declared type Password) — its value is masked everywhere it is reported (RFC-0001), so a guard may not compare it
set order.status to paid              → ... `set` has no evaluator for Text ...; write a Text field with `format order.status from "..."` (issue #94)
```

## Alternatives

### `list where`와 같은 폭으로 열기 (기각)

RFC-0038의 `list where` 등가는 Integer·DateTime이 아닌 모든 base(Money, Password 포함)를
선언 타입 일치로 판정한다. 가드는 새 문법 자리이므로 더 좁게 열 수 있다. Password는 스킵
레코드가 값을 싣는 새 출력 채널 때문에 뺐고(RFC-0038 §Alternatives 3이 마스킹 문제를 열린
채로 남겼다), Money는 이미 RFC-0051의 `money` 차원으로 가드에서 비교된다.

### 따옴표 문자열 리터럴 (`"paid"`) 문법 (기각)

`Condition` 문법에 문자열 리터럴 산출 규칙을 새로 넣어야 하고, 모드 B 인코딩·`list where`의
우변·`spec`의 리터럴까지 함께 정해야 한다. 맨이름은 이미 파싱되고(`Ref`), 컴파일러가 상대쪽
선언 타입을 알기 때문에 그 자리의 맨이름이 리터럴인지 한 번에 판정할 수 있다. 공백이 든
값은 맨이름으로 쓸 수 없다 — enum 멤버는 원래 낱말이다.

### 런타임에서 맨이름의 의미를 추측하기 (기각)

"payload에 그 키가 없으면 리터럴" 같은 규칙은 같은 소스가 요청마다 다른 뜻이 된다.
`when stock == available`처럼 지금 payload 비교인 프로그램의 의미가 바뀔 수도 있다. 판정은
컴파일러가 한 번 내리고 IR(`textEqualityOperands`)에 적는다.

### did-you-mean의 기준을 낮추기 (기각)

`shipped`는 `pending`/`paid`/`cancelled` 어느 것과도 비슷하지 않다(difflib 비율 0.43 이하).
기준(0.6)을 낮추면 엉뚱한 제안이 나온다. 컴파일러의 다른 제안(`unknown-verb`)과 같은 기준을
쓰고, 멤버 목록을 항상 보여 준다.

## Open Questions

없음.

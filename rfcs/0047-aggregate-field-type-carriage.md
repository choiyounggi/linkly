# RFC-0047: 집계 필드 타입의 IR 전달 (`agg_field_type`)

## Status

- Status: **Accepted** (RFC-0047, 2026-09-02)
- Updates: RFC-0045 §Reference-level Specification/1. `AggFunc` 문법, RFC-0045 §Reference-level Specification/5. `sum`의 Money 확장

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목한다. `nodeAssignment`가 선택
필드 하나(`agg_field_type`)를 새로 실을 수 있다는 사실을 §1이 명시하지
않으면, 그 절이 보존한 "스키마 변경 불필요" 판단과 이 RFC의 스키마 개정이
같은 자리를 놓고 다르게 읽힐 여지가 남는다. §5는 빈 RowSet Money `sum`의
결과 타입(`{"amount": "0", "currency": null}`)을 이미 정의했지만 그 값을
실행까지 실어 나르는 메커니즘은 정의하지 않았다 — 이 RFC가 그 메커니즘을
codify한다. 둘 다 지목하지 않으면 RFC-0007 §2.2 규칙 1(누락 없는 지목)
위반이다.

번호가 0047인 이유: 0046까지 점유됐다. RFC-0007 §3은 번호 재사용을 금지한다.

언어 워킹네임은 **LNPL**(소스 확장자 `.lnpl`)이다.

## Motivation

issue #158: 빈 RowSet에서 Money 필드를 `sum`하면 `interp.eval_aggregate`가
정수 `0`을 돌려준다. RFC-0045 §Reference-level Specification/5는 이미 그
결과 타입을 `{"amount": "0", "currency": null}`로 정의했으므로 이것은 새
설계 결정이 아니라 **계약 미달**이다 — Money로 선언된 출력 필드에 정수가
들어가 와이어 모양이 깨진다. `impl/tests/test_row_sets_runtime.py`의
`test_an_empty_money_rowsets_sum_is_plain_integer_zero`가 이 미달을 고정해
왔고, `eval_aggregate`의 docstring이 "load-bearing decision"이라는 표현으로
그 이유를 적어 두었다.

**왜 생기는가.** `eval_aggregate(agg, expression, rowsets)`는 문서/타입
정보를 받지 않는다 — 행 값의 Python 모양으로 타입을 분간한다(`dict` →
Money, `str` → DateTime, `int` → Integer). 행이 0개면 볼 것이 없어서 Money
선언 필드와 Integer 선언 필드를 구별할 수 없다. `lower.py`의
`_check_aggregate`는 이 구별을 **정적으로** 이미 안다(집계 대상 필드의
선언 타입을 조회해 `sum`/`avg`는 Integer-or-Money, `min`/`max`는
Integer/DateTime/Money 중 하나임을 lowering 시점에 검사한다) — 문제는 그
정보가 IR을 건너 실행까지 전달되지 않는다는 것뿐이다.

**issue #145(RFC-0045 구현) 태스크에서 고치지 않은 이유 — 두 대안의 기각
실측:**

1. **IR 노드에 필드 타입을 실어 나르는 길.** `schemas/lir.schema.json`의
   `nodeAssignment`는 `"additionalProperties": false`다. 키 하나를 더하려면
   **LIR 스키마(공개 계약 표면) 개정**이 필요하고, 그것은 RFC-0007 §2.1이
   막는 "Accepted RFC의 본문 직접 편집"에 해당해 RFC 갱신 없이는 할 수 없는
   변경이다 — 즉 스키마를 만지려면 애초에 이 RFC 같은 문서가 선행돼야
   했다. (issue #158 본문은 이 배제를 "RFC-0045 §1이 명시적으로 배제했다"고
   적었지만, 실측하면 "`MoneyLiteral`은 문법이지 새 IR 노드가 아니다"라는
   정확한 문구는 RFC-0044 §Reference-level Specification/1에 있다 — 그
   문구 자체는 이 RFC가 여는 변경과 무관하다. issue가 실제로 짚은 자리는
   RFC-0045 §1이 그대로 보존한 RFC-0025 §Reference-level Specification/2의
   "정규화" 문단, "정규화된 새 형태를 싣는 데 스키마 변경이 필요 없다"다.
   그 문단은 `AggFunc` **문법**의 정규화 표현에 한정된 판단이라 이 RFC가
   여는 필드-타입 전달과 범위가 겹치지 않지만, 같은 절 안에서 두 관심사가
   섞여 읽히므로 §1을 갱신해 경계를 명시한다 — §Reference-level
   Specification/1 참조.)
2. **런타임에 타입을 되찾는 길.** 호출부(`interp.py`의 `_run_effect`)는
   `self.nodes`를 갖지만 `Assignment` 노드는 **타깃** 엔티티(`entity`)만
   들고 있고 집계의 **소스** 엔티티는 없다. `lower.py`의 `by_binding` 결정
   (어떤 바인딩 이름이 어떤 엔티티를 가리키는가)을 런타임에 복제해야
   하는데, 그것은 issue #151(`resolve.py`)이 정확히 없애려 했던 종류의
   중복이다 — 같은 판단을 두 곳에서 서로 다른 코드로 다시 내리면 그 둘이
   갈릴 때(예: `lower.py`가 먼저 바뀌고 런타임 쪽 복제를 깜빡할 때)
   드러나지 않는 결함이 된다.

**Fix.** `lower.py`가 이미 정적으로 아는 필드 타입을 실행까지 전달한다.
최소 변경은 `nodeAssignment`에 선택 필드 하나(`agg_field_type`)를 추가하고
`_check_aggregate`가 계산한 base 타입을 거기 싣는 것이다 — 대안 1을
다시 선택하되, 이번에는 그 변경을 여는 RFC 갱신을 먼저 하고서.

**모드 범위.** 이 RFC는 모드 A(`interp.py`)에만 적용된다. `backend.py`
(모드 B)는 `Assignment` 노드 kind를 어디서도 패턴매치하지 않는다 — 실측
(`grep -n "Assignment" impl/lnpl/backend.py`가 0건을 반환한다) — 이는
RFC-0045 §Reference-level Specification/7이 이미 세운 판단("RowSet 값과
그로부터 계산되는 집계 결과는 RFC-0004의 네 관측 클래스 중 어느 것도
아니다")과 일치한다. `agg_field_type`은 모드 B가 관측하지 않는 노드의
관측하지 않는 부가 필드이므로, 모드 B 코드는 이 RFC로 수정하지 않는다 —
AGENTS.md의 "무음 스킵 금지" 원칙에 따라 이 사실을 침묵으로 남기지 않고
여기 명시한다.

## Guide-level Explanation

`.lnpl` 작성자에게는 아무것도 바뀌지 않는다 — 문법도, `sum`/`avg`/`min`/
`max`의 표면 어휘도 그대로다. 바뀌는 것은 컴파일러 내부의 배관뿐이다:
`lower.py`가 `set report.totalAmount to sum payment.amount`를 IR로
내릴 때, 이제 `payment.amount`의 선언 타입(`Money`)을 그 `Assignment`
노드 자신에 함께 적어 둔다. 실행기는 RowSet이 비어 있어 행을 볼 수 없을
때 이 표기를 읽고 "이 sum의 대상은 Money였다"를 알 수 있다.

바뀌지 않는 것: 행이 하나라도 있으면 여전히 그 행의 값 모양으로 타입을
분간한다(이 RFC가 여는 새 표기는 **빈 RowSet일 때만** 쓰인다). `sum`/
`count`가 아닌 보통 `set x to y + 1`류의 `Assignment`에는 이 필드가
아예 없다 — 집계가 아닌 대입에는 필요도, 의미도 없다. 옛 컴파일러가 낸
IR 문서(이 필드가 없는 문서)는 새 실행기에서도 그대로 돌아간다 — 다만
빈 Money `sum`은 재컴파일 전까지 옛 동작(정수 `0`)을 유지한다(§Reference-
level Specification/5의 하위호환 조항).

## Reference-level Specification

### 1. `AggFunc` 문법과 IR 표면 — RFC-0045 §1 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0045 §Reference-level
Specification/1 전체에 대한 **치환 후 최종 텍스트**다.

```
AggFunc      ::= 'sum' | 'count' | 'avg' | 'min' | 'max'
```

(RFC-0045가 RFC-0025 §2에 대해 정의한 그 생산 규칙 그대로 — 이 갱신은
문법을 한 글자도 바꾸지 않는다.) `count link`·`sum link.clicks`처럼
`avg link.clicks`·`min link.clicks`·`max link.clicks`도 `Reference`가
두 조각(RowSet 바인딩 이름 + 필드)이다. 정규화 문자열
(`Assignment.expression`에 싣는 `<func> <ref>`)의 `<func>` 자리에
`avg`/`min`/`max`가 그대로 들어간다 — RFC-0025 §2의 "정규화" 문단이 세운
"정규화된 새 형태를 싣는 데 스키마 변경이 필요 없다"는 판단은 **이
정규화 표현에 한정해서** 지금도 유효하다: `expression`은 여전히
`"type": "string"`, 패턴 제약 없는 자유 문자열이고, `avg`/`min`/`max`를
그 문자열에 싣는 데 스키마 변경이 필요 없었다는 사실은 바뀌지 않는다.

**새로 여는 것 — `nodeAssignment.agg_field_type` (RFC-0047).** 위
정규화 판단과는 **별개의 관심사**로, `nodeAssignment`가 선택 필드 하나를
새로 받는다:

```json
"agg_field_type": {"enum": ["Integer", "DateTime", "Money"]}
```

- **새 IR 노드가 아니다** — `kind: "Assignment"`는 그대로다. 기존
  `nodeAssignment`가 선택 키 하나를 더 받을 뿐이다.
- **필수 필드가 아니다** — `required`에 들어가지 않는다. 집계가 아닌
  `Assignment`(보통의 산술 `set`, `format`)와 `count`(필드가 아니라
  엔티티를 세므로 base 타입이 없다)에는 이 키가 없다. 옛 컴파일러가 낸
  문서에도 없다 — §5가 그 부재를 하위호환 계약으로 다룬다.
- **`additionalProperties: false`는 그대로다** — `nodeAssignment`가
  받는 키의 전체 집합에 하나를 더할 뿐, 스키마의 폐쇄성 자체는 이 RFC가
  건드리지 않는다.
- 값은 `_check_aggregate`(lower.py)가 정적으로 판정하는 base 타입과
  같은 어휘(`Integer`/`DateTime`/`Money`) — `sum`/`avg`는 그중
  Integer·Money만, `min`/`max`는 셋 다 받을 수 있다는 §Reference-level
  Specification/2의 표는 이 RFC가 바꾸지 않는다. `agg_field_type`은 그
  표가 이미 내린 판정을 실행까지 나르는 채널일 뿐, 새 판정을 더하지
  않는다.

### 2. `nodeAssignment` 계산 — `lower.py` (신설, RFC-0047)

`_check_aggregate`(lower.py)는 `sum`/`avg`/`min`/`max`마다 집계 대상
필드의 선언 base 타입을 이미 계산한다(§Reference-level Specification/2의
표를 판정하는 바로 그 값). 이 RFC는 그 계산 결과가 함수를 벗어나
호출부까지 돌아오게 반환 계약을 넓힌다: `_check_aggregate`는 이제
`(entity_id, base_or_None)`을 반환한다 — `count`(base가 없는 경로)는
`base_or_None`이 `None`, `sum`/`avg`/`min`/`max`는 계산된 base(`Integer`
/`DateTime`/`Money`)다. 호출부는 `base_or_None`이 `None`이 아닐 때만
그 `Assignment` 노드에 `agg_field_type: base_or_None`을 싣는다 — `count`
Assignment와 비집계 `Assignment`에는 여전히 이 키가 없다.

### 3. `sum`의 Money 확장과 결과 전달 — RFC-0045 §5 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0045 §Reference-level
Specification/5 전체에 대한 **치환 후 최종 텍스트**다.

`sum <ref>`가 Money 필드를 가리킬 때, 값은 RowSet의 모든 행에서 그 필드의
minor-unit 정수(RFC-0044 §1)를 더한 합이다 — 통화는 첫 행이 정하고, 이후
행이 다른 통화를 내면 `RunError money-currency-mismatch`(RFC-0044 §5)다.
이 규칙은 RFC-0045 원문 그대로이며 이 RFC가 손대지 않는다.

**빈 RowSet — 결과 타입.** 빈 RowSet은 RFC-0025 §Guide-level Explanation
원문 그대로 `0`이다 — 다만 Money의 "0"은 통화가 없으므로, 결과 타입을
`{"amount": "0", "currency": null}`로 정의한다(RFC-0045가 이미 정의한
계약, 바뀌지 않는다).

**빈 RowSet — 전달 메커니즘 (신설, RFC-0047).** 위 결과 타입을 실제로
내려면 실행기가 "이 `sum`의 대상 필드가 Money로 선언됐다"를 빈 RowSet
에서도 알아야 한다 — §Reference-level Specification/1·2가 여는
`agg_field_type`이 그 정보다. `eval_aggregate`(interp.py)는 이제 선택
키워드 인자 `agg_field_type=None`을 받는다(기존 호출은 무변경 — 위치
인자 3개짜리 호출은 그대로 유효하다). `_run_effect`(interp.py)는 그
`Assignment` effect가 `agg_field_type` 키를 가지고 있으면
`effect.get("agg_field_type")`을 그대로 넘긴다 — 없으면 `None`이 넘어가고,
아래 부재 규칙이 적용된다.

빈 RowSet에서 `func == "sum"`이고 `agg_field_type == "Money"`일 때만
결과는 `{"amount": "0", "currency": None}`다. 그 밖의 모든 경로는 이
RFC 이전과 완전히 같다:

| 경로 | 결과 |
|------|------|
| 빈 RowSet, `sum`, `agg_field_type` 없음(구 IR) 또는 `"Integer"` | 정수 `0` |
| 빈 RowSet, `count` | 정수 `0`(RFC-0025 §5, 불변) |
| 빈 RowSet, `avg` | `RunError avg-of-empty-rowset`(RFC-0045 §3, 불변) |
| 빈 RowSet, `min`/`max` | `RunError min-max-of-empty-rowset`(RFC-0045 §4, 불변) |
| 행이 있는 `sum`(Integer/Money 무관) | 기존 값 모양 분기 그대로(불변 — 행이 있으면 첫 행의 Python 타입으로 이미 구별 가능했다) |

**하위호환 (신설, RFC-0047).** `agg_field_type`이 없는 `Assignment`
Effect(이 RFC 이전에 컴파일된 IR 문서)는 빈 Money `sum`에서 계속 정수
`0`을 낸다 — 재컴파일 전까지는 §5가 원래 정의한 `{"amount": "0",
"currency": null}` 계약을 만족하지 못한다는 뜻이다. 이것은 §5의 계약을
어기는 것이 아니라 **이 계약을 지키려면 `agg_field_type`을 실어 나르는
컴파일러가 필요하다는 사실을 명시한 것**이다 — 언어 의미는 이 RFC로
확정되고, 이미 컴파일된 산출물이 그 의미를 실제로 관측하려면 재컴파일이
필요하다. 새 규칙 없이 옛 문서가 실행 자체를 거부당하지 않는다는 점(하위
호환의 핵심)은 지켜진다.

### 4. spec 단언 — 새 어휘 없음 (RFC-0045 §6, 갱신 없음)

이 RFC는 표면 문법도, `expect` 어휘도 열지 않는다 — `agg_field_type`은
IR 전용 필드이고 `.lnpl` 소스에도 spec 단언에도 나타나지 않는다.
RFC-0045 §6은 이 RFC가 지목하지 않으므로 원문 그대로 유효하다.

## Examples

### 골든 시나리오 "Login" (RFC-0007 §6)

`Login` 워크플로는 `list`도 집계도 쓰지 않는다 — 정본을 참조만 하고
재정의하지 않는다. 골든 자체는 바뀌지 않는다(`examples/login.lir.json`
불변).

### 골든 인접 예제 — 결제 집계 (RFC-0007 §6, 골든이 다루지 않는 기능)

RFC-0045 §Examples의 결제 집계 예제를 그대로 재사용한다 — 이 RFC는
`.lnpl` 표면을 열지 않으므로 컴파일되는 프로그램 자체는 바뀌지 않는다.

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

행이 있는 경로다 — 컴파일된 `Assignment` 노드가 `agg_field_type: "Money"`
를 새로 신지만, 실행기는 첫 행의 Python 모양(`dict`)으로 이미 Money를
구별할 수 있었으므로 이 예제의 결과는 RFC-0045 이전과 완전히 같다.

### 빈 RowSet Money `sum` — 이 RFC가 고치는 경로

<!-- lnpl-check: skip — fragment: 조각: workflow 선언 없이 spec의 given/expect 자리만 보여줌(컴파일러: 'spec' appears before any declaration) -->
```lnpl
    spec
        given
            stored Report id 4
        when
            summarizePayments
        expect
            completed
```

`Payment`를 하나도 시드하지 않고 `avg`/`min`/`max` 없이 `sum`만 쓰는
변형(위 워크플로에서 그 세 스텝을 뺀 것)을 돌리면 워크플로는
`completed`로 끝난다(`count`도 0이므로 `avg`가 없으면 실패할 이유가
없다). 이 RFC 이전에는 `report.totalAmount`가 정수 `0`이었다; 이 RFC
이후에는 `{"amount": "0", "currency": None}`이다 — 와이어로 나가는
JSON에서는 `{"amount": "0", "currency": null}`. `expect result ==`로
이 값을 단언하는 문법은 이 RFC가 열지 않는다(§Reference-level
Specification/4) — 계약 구현 스위트가 인터프리터 반환값을 직접
검사한다(`impl/tests/test_row_sets_runtime.py`).

## Alternatives

| # | 검토한 대안 | 기각 사유 |
|---|------------|----------|
| 1 | **런타임에 `by_binding`을 재구성해 타입을 되찾는다**(issue #158의 대안 2) | `interp.py`가 `lower.py`의 바인딩 판단을 복제해야 한다 — issue #151(`resolve.py`)이 정확히 없애려 한 종류의 중복이다. 같은 판단을 두 곳에서 다시 내리면 한쪽만 바뀌었을 때 드러나지 않는 결함이 된다 |
| 2 | **집계 전용 새 IR 노드 kind(`Aggregate`)를 만든다** | `Assignment`가 이미 `target`/`expression`/`entity`를 다 갖고 있다 — 없는 것은 필드 타입 하나뿐이다. 새 kind를 만들면 `kind == "Assignment"`를 패턴매치하는 모든 소비자(`lower.py`의 검사 패스, `interp.py`의 `_run_effect`, 이 문서가 다루지 않는 모드 B 관측 판정)가 그 kind를 추가로 알아야 한다 — 스칼라 값 하나를 나르려고 소비자 표면 전체를 넓히는 비용이 이 문제의 크기에 비해 크다 |
| 3 | **`agg_field_type`을 필수 필드로 만든다** | 집계가 아닌 `Assignment`(보통의 산술 `set`, `format`)와 `count`에는 base 타입이 없다 — 필수로 만들면 그 경로들이 존재하지 않는 값을 채워 넣어야 하고, 옛 컴파일러가 낸 문서는 전부 스키마 검증에서 거부된다. 선택 필드는 하위호환을 스키마 수준에서부터 지킨다(§Reference-level Specification/5의 하위호환 조항과 정합) |
| 4 | **필드 타입을 `expression` 문자열에 인코딩한다**(예: `"sum:Money link.clicks"`) | `expression`은 이미 정규화된 표면 문법 표현이고(RFC-0025 §2), 그 문자열의 문법은 `.lnpl` 소스가 재구성 가능해야 한다는 계약을 진다. 타입 태그를 섞으면 그 문자열을 다시 파싱하는 소비자마다 새 문법을 배워야 하고, 원래 `AggFunc` 문법에 없는 토큰이 IR에서만 나타나는 비대칭이 생긴다. 별도 키가 관심사를 분리한다 |

## Open Questions

1. **모드 B가 언젠가 `Assignment`를 관측하게 되면.** 이 RFC는 모드 B가
   `Assignment`를 전혀 컴파일하지 않는 현재 상태(§Motivation의 실측)를
   전제로 `agg_field_type`을 모드 A 전용으로 다룬다. 모드 B가 나중에
   집계 `Assignment`를 관측하는 쪽으로 넓어지면, 그 MLIR 방출이
   `agg_field_type`을 그대로 속성으로 실어야 하는지, 아니면 모드 B 자신의
   타입 추론으로 재도출해야 하는지는 이 RFC가 답하지 않는다 — RFC-0045
   §Reference-level Specification/7이 이미 세운 "모드 B는 RowSet/집계
   값을 관측하지 않는다"는 판단이 뒤집히는 후속 RFC가 있어야 다시 열
   질문이다.
2. **비집계 `Assignment`로의 일반화.** `format`이나 보통의 산술 `set`도
   대상 필드의 선언 타입을 이미 정적으로 안다 — 지금은 그 정보를 실을
   이유가 없어서(값 모양이 항상 행 데이터로부터 구별 가능하다) 열지
   않는다. 빈 RowSet처럼 "볼 행이 없는" 다른 경로가 생기면 그때 다시
   검토할 문제이고, 지금은 이 RFC의 범위 밖이다.

# RFC-0028: 산술 연산자 확장과 대안 가드

## Status

- Status: **Accepted** (RFC-0028, 2026-08-24)
- Updates: RFC-0015 §1, RFC-0025 §Reference-level Specification/2. 집계 표현식 문법,
  RFC-0015 §4, RFC-0001 §노드 카탈로그/Guard,
  RFC-0014 §Reference-level Specification/2. Guard Runtime Semantics,
  RFC-0027 §Reference-level Specification/6. 관측

RFC-0007 §2.2 규칙 5(연쇄 갱신)에 따라 대상 RFC와 **직전 갱신 RFC를 모두** 지목한다.

`ArithOp` 생산 규칙은 RFC-0015 §1에 있고 RFC-0025 §2가 같은 §1의 `AssignStep`
생산 규칙을 이미 갱신했으므로(단, RFC-0025 §2는 `ArithOp`/`Condition`/`Operand` 등
다른 생산 규칙은 "손대지 않는다"고 명시적으로 적었다 — 그 원문이 여전히 유효한
기준선이다), 이 문서는 RFC-0015와 RFC-0025 둘 다 지목해 어느 텍스트가 §1의 최신
계약인지 기계적으로 확인 가능하게 한다.

가드 런타임 의미론(§2.1 `when` 모드, §2.4 스킵 레코드, §2.6 모드 A/B 동등성)은
RFC-0014 §2가 이미 RFC-0008 §2를 갱신했고, RFC-0027 §6이 §2.4의 마스킹 범위만 다시
갱신했다. 이 문서는 §2 전체(§2.1~§2.6)를 치환하므로 두 문서를 함께 지목한다.

값 도메인과 실패 표(RFC-0015 §4)와 노드 카탈로그의 `Guard` 행(RFC-0001 §노드
카탈로그/Guard)은 이번이 첫 갱신이다 — 지목할 직전 갱신 RFC가 없다.

지목하지 **않는** 것: RFC-0015 §2(IR 조건은 정규화 문자열로 남는다는 원칙 — 이
문서는 새 필드를 추가할 뿐 그 원칙을 바꾸지 않는다), RFC-0015 §3(정적 거부 표 —
괄호·중첩 거부는 그대로 유지되고, 이 문서가 추가하는 유일한 정적 거부는 §1
생산 규칙 자체가 문법으로 막는다), RFC-0015 §5(Differential Equivalence — 관측
클래스는 늘지 않는다, RFC-0014 §2.6이 이미 규정한 비교 그대로 이행한다).

## Motivation

이슈 #93이 실측한 두 공백은 RFC-0015가 남긴 것이다.

**공백 ① — 곱셈이 없어 단가 계산이 안 된다.**

```
$ lnpl compile p1_mult.lnpl
compile error: line 8: invalid arithmetic operator '*': 'set product.price to
product.price * 2' (RFC-0015 supports `+` and `-` only)
```

`total = price × quantity`는 커머스의 최소 단위 계산인데, RFC-0015 §Alternatives는
곱셈·나눗셈을 "이슈 #47의 다섯 요구 중 어느 것도 요구하지 않는다"는 이유로
기각했다. 이슈 #93은 그 요구가 이제 실제로 있다고 보고한다 — `total=price×qty`는
연쇄 `+`/`-`로 우회할 수 없다.

나눗셈이 요구했던 "0 나눗셈과 반올림 의미를 두 런타임에서 동시에 정의"하는 비용은
이 RFC가 냈다: 정수 나눗셈으로 좁히고(Decimal 없음, RFC-0015 §Open Questions 4가
이미 그 경계를 그어 두었다), 0 나눗셈은 §4의 기존 `RunError` 클래스에 새 행 하나로
얹는다 — RFC-0015가 이미 세운 "새 결과 클래스를 만들지 않는다"는 원칙 그대로다.

**공백 ② — 대안 조건을 한 가드에 쓸 수 없다.**

```
$ lnpl compile p2_or.lnpl
compile error: line 9: invalid condition: more than one comparator in
'item.a > 0 or item.b > 0'
```

RFC-0015 §Alternatives는 `or`/`not`을 "표현력이 높아질수록 네이티브 평가 경로가
복잡해진다"는 이유로 미뤘다. 이 RFC는 그 순서를 따른다 — `or`를 **연산자로**
넣지 않는다. 대신 이슈 #93이 제안한 Rego 패턴을 쓴다: OPA/Rego는 논리를 표현식이
아니라 **구조**로 밀어낸다(같은 헤드의 별도 규칙 = OR). 이 언어에는 그 자리가
이미 있다 — 가드 두 줄이 연속하면 지금은 파싱 에러다(이슈 #45가 막은 자리). 그
자리를 "같은 피가드 항목을 갖는 대안 가드"로 승격하면 `Condition` 문법은 한 글자도
안 바뀐다.

`not`은 넣지 않는다 — `!=`·`missing`이 이미 있다(`not exists` == `missing`,
`not (a == b)` == `a != b`). §Alternatives에 이 등가를 기록한다.

넣지 않는 것은 이슈 #93이 명시한 그대로다: 괄호, 연산 중첩, 삼항, 부동소수.
JSONata가 "함수 호출만"에서 "완전한 표현식 언어"로 흘러간 전철(§Alternatives의
표)의 첫 계단이므로, "표현식으로 안 되는 계산은 동사로 흡수한다"는 RFC-0015의
설계 규칙을 이 문서도 지킨다.

## Guide-level Explanation

저자가 새로 쓸 수 있게 되는 것은 둘이다.

**1. 곱셈·나눗셈.**

```
workflow PlaceOrder
    read product
    when product.stock >= input.quantity
    create order
    when product.stock >= input.quantity
    set order.total to product.price * input.quantity
    set product.stock to product.stock - input.quantity
```

`/`는 **정수 나눗셈**이다(버림, Python의 `//`가 아니라 C 스타일 truncating
division — 피연산자가 모두 음이 아닌 이 언어의 실측 범위에서는 두 방식이
일치하므로 아래 §Reference-level Specification/1에서 정확히 고정한다). `0`으로
나누면 `RunError`가 나고 워크플로는 `failed`로 끝난다 — 컴파일 에러가 아니라
**런타임** 실패다. 나누는 값이 리터럴 `0`이면 lower가 즉시 정적 거부한다(항상
실패하는 프로그램을 굳이 실행까지 보내지 않는다); 필드·참조가 런타임에 0으로
평가되면 `RunError`다.

**2. 대안 가드(`or`).**

```
workflow Approve
    when input.channel == 1
    or input.amount <= 100
    create payment
```

`input.channel == 1`이 거짓이어도 `input.amount <= 100`이 참이면 `create payment`가
실행된다. 어느 쪽도 참이 아니면 스텝은 건너뛰고, 스킵 레코드가 RFC-0014의 계약
그대로 관측 가능하다(§Reference-level Specification/3). 대안은 몇 개든 이어 쓸 수
있다(`or` 줄을 계속 추가):

```
    when tier == 1
    or tier == 2
    or tier == 3
    create discount
```

각 대안은 **독립적으로 완결된** `Condition`이다 — `and`로 여러 항을 묶을 수도
있다(`or input.amount <= 100 and input.currency == 1`). 대안끼리는 `or`로,
대안 내부는 `and`로 묶이며, 이 둘은 섞이지 않는다(`Condition` 문법 자체가 원래도
`and`만 허용했고, 그 규칙은 바뀌지 않는다 — 대안 가드는 `Condition` 여러 개를
구조로 나열하는 것이지, `Condition` 문법에 `or`를 넣는 것이 아니다).

**대안 가드는 `when`에만 붙는다.** `until`은 반복 종료 조건이 하나뿐이고,
이슈 #93도 `until or`를 요구하지 않는다 — 최소 표면 원칙 그대로다(아래
§Alternatives). `repeat`에는 애초에 조건이 없다.

**쓸 수 없는 것**은 여전히 §3(정적 거부, RFC-0015 원문 불변)이 정한 그대로다:
괄호·중첩·삼항·부동소수, 그리고 이 RFC가 추가하는 것 — `until`/`repeat` 뒤의
`or`.

## Reference-level Specification

### 1. Full Grammar — RFC-0015 §1 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0015 §1의 `ArithOp`·`Guard` 생산 규칙에
대한 **치환 후 최종 텍스트**다. 이 절의 다른 생산 규칙(`Condition`/`Presence`/
`Comparison`/`Comparator`/`Operand`/`Reference`/`Namespace`/`Integer`/`Duration`
및 RFC-0025 §2가 갱신한 `AssignStep`/`Aggregate`/`AggFunc`의 최종형)은 RFC-0015·
RFC-0025 원문이 그대로 유효하며 이 RFC가 손대지 않는다.

```
Guard        ::= 'when' Condition AltGuard* | 'until' Condition
AltGuard     ::= 'or' Condition

ArithOp      ::= '+' | '-' | '*' | '/'
```

**Old (RFC-0015 §1):**
```
Guard    ::= ('when' | 'until') Condition
ArithOp  ::= '+' | '-'
```

`AltGuard`는 `Condition`을 그대로 재사용한다 — 새 생산 규칙이 아니라 **기존
`Condition` 하나를 여러 번 쓰는 구조**다. `and`가 `Comparison`을 묶듯, `or`는
`Condition` 전체(대안 하나)를 묶는다. 그래서 대안 하나가 `and`로 여러 항을 가질
수 있으면서도(`Condition`의 기존 정의 그대로), 대안끼리는 절대 한 `Condition`
안에서 섞이지 않는다 — `or`가 `Condition` 문법 안으로 들어가는 경로가 애초에
없기 때문이다. 이것이 §Motivation이 말한 "연산자가 아니라 구조"의 문법적 근거다.

`Guard`가 `('when'|'until') Condition` 하나의 생산 규칙에서 두 갈래로 갈라진
것은 실질 변경이지만, 두 갈래 모두 `Condition`을 정확히 한 번 요구하는 것은
그대로다 — `until`이 잃는 것은 없다.

**리터럴은 부호가 없다** (RFC-0015 §1 불변, 재확인). `/`의 나눗셈 결과가
음수일 수 있는 것은 계산 **결과**이지 리터럴이 아니므로 이 제약과 모순하지
않는다 — `-3`을 나눗셈으로 만드는 것과 `product.price * -1`처럼 리터럴 자리에
음수를 직접 쓰는 것은 다르다. 후자는 여전히 거부된다(모드 B가 `%c<value>_i64`로
상수를 선언하므로 `%c-3_i64`는 유효한 SSA 이름이 아니다 — RFC-0015 §1 원문의
사유 그대로 `*`/`/`에도 적용된다).

**나눗셈은 절삭(truncating)이다.** `a / b`는 `int(a / b)`가 아니라 C의 정수
나눗셈과 같은 절삭 방식으로 정의한다: 몫을 0 방향으로 자른다. 이 언어의 값
도메인(§4)은 부호 있는 64비트 정수이고 피연산자가 음수일 수 있으므로(계산
결과가 음수일 수 있다는 §1 원문이 이미 인정한 사실), "버림"(floor, `-7 // 2
== -4`)과 "절삭"(truncate, `-7 / 2 == -3`)이 갈린다. 절삭을 고른 이유는 모드
B가 컴파일하는 `arith.divsi`(MLIR standard dialect의 부호 있는 정수 나눗셈)가
바로 이 의미론이기 때문이다 — 모드 A가 다른 규칙(Python `//`, floor)을 쓰면
`stock=-7, batch=2`류의 입력에서 두 모드가 다른 몫을 내고, `EQUIVALENT`가 그
차이를 조용히 넘기게 된다. 모드 A는 Python에서 `math.trunc(a / b)`가 아니라
`int(a / b)`가 이미 절삭이 아니라 0을 향한 버림과 다르게 동작할 수 있는 함정이
있어(부동소수 경유), 정수 전용 절삭 연산(`-(-a // b) if (a < 0) != (b < 0) else
a // b`류, 또는 동등한 정수 전용 절삭식)으로 구현해야 한다 — 실측 요구 조건은
"모드 A/B가 같은 몫을 낸다"이지 "Python이나 C 중 어느 쪽 관용구를 쓰는가"가
아니다.

### 2. 값 도메인과 실패 — RFC-0015 §4 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0015 §4의 런타임 값 실패 표에 대한
**치환 후 최종 텍스트**다. 표의 다른 행(참조 미해소, 비수치 비교, 범위 초과,
가드 거짓)은 RFC-0015 원문 그대로다.

| 상황 | 판정 |
|------|------|
| 참조가 아무것도 가리키지 않음(바인딩 없음·필드 없음·payload 키 없음) | 그 비교는 **거짓**. 예외가 아니다(RFC-0008 이전과 동일) |
| 비수치 값의 비교 | `RunError` — `cannot compare non-numeric <ref>=<value>` |
| 산술 결과 또는 피연산자가 i64 범위 밖 | `RunError` — `value out of the 64-bit range` |
| **`/`의 오른쪽 피연산자가 0으로 평가됨 (신설)** | `RunError` — `division by zero: <a> / <b> (in <조건 또는 대입식>)` |
| 가드가 거짓이어서 할당이 실행되지 않음 | RFC-0014의 거부 클래스. `completed` 유지 + `skipped` 레코드 + 진단 `guard-skipped-steps` + `--strict` rc=2 |

0 나눗셈이 `RunError`인 것은 새 결과 클래스가 아니다 — RFC-0015가 이미 세운
"런타임 값 실패는 새 결과 클래스를 만들지 않는다"는 원칙을 그대로 잇는다(§4
원문 첫 문장 불변).

**정적 거부(lower 시점) — 나눗셈의 오른쪽이 리터럴 `0`인 경우.** 이는 §3(정적
거부, RFC-0015 원문 불변)에 새 행을 더하지 않는다 — §3은 "문법이 받되 문서를
보면 거부되는 형태"를 다루는데, `x / 0`은 리터럴 검사만으로 판정 가능한
**항상 실패하는 프로그램**이다. `lower.py`의 기존 "양변이 모두 리터럴(`1 < 2`)"
행과 같은 층위의 판단(작성자 오류를 실행까지 보내지 않는다)이므로, 구현은
그 옆에 `<a> / 0`(우변이 리터럴 0)을 컴파일 에러로 추가한다. `product.stock / 0`
처럼 우변이 **참조**면 값은 런타임에만 알 수 있으므로 정적으로 거부할 수
없고, 위 표의 `RunError` 행이 적용된다.

### 3. 노드 카탈로그 `Guard` 행 — RFC-0001 §노드 카탈로그/Guard 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0001 "### 노드 카탈로그" 절
**Behavior** 표의 `Guard` 행에 대한 치환 후 최종 텍스트다. 다른 20개 kind의
행과 표 서두의 산문(공통 필드 설명)은 RFC-0001 원문 그대로다.

| kind | 필수 필드 | 선택 필드 | children 허용 |
|------|----------|----------|--------------|
| Guard | `mode`(`when`\|`until`\|`repeat` — 닫힌 enum) | `condition`(`when`·`until` 전용 — 조건 서술), `count`(`repeat` 전용 — 1 이상 정수), `alternatives`(`when` 전용, 배열, 1개 이상의 문자열 — `or`로 이어지는 대안 조건 서술. RFC-0028 신설) | 피가드 항목 1개(WorkflowStep, Concurrency, Pipeline 중 하나). 실행 의미는 RFC-0014 §2. 2026-07-31 신설(RFC-0002 부록 A.4-① 해소), 2026-08-24 `alternatives` 추가(RFC-0028, 이슈 #93) |

`alternatives`가 `mode: "until"`이나 `mode: "repeat"`인 Guard 노드에 있으면
스키마가 거부한다(`schemas/lir.schema.json`의 `nodeGuard`에 조건부 제약을
둔다 — §Reference-level Specification/6). `condition`이 정규화된 하나의
`Condition` 문자열이듯, `alternatives`의 각 원소도 같은 정규화 규칙(RFC-0015
§1 "정규화" 문단)을 따르는 독립된 `Condition` 문자열이다 — 원소들 사이에
`or` 토큰을 끼워 넣은 하나의 문자열이 아니다(그런 문자열은 `parse_condition`이
이해하지 못한다 — SSOT는 하나이고, 대안 각각이 그 SSOT를 그대로 통과한다).

### 4. Guard Runtime Semantics — RFC-0014 §2 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0014 §Reference-level Specification/2
(Guard Runtime Semantics) 전체의 치환 후 최종 텍스트다. §2.2(`until` 모드)·
§2.3(실행 의미 표)·§2.5(진단과 종료 코드)는 RFC-0014 원문 그대로이므로 다시
싣지 않는다 — 이 RFC가 손대는 것은 §2.1·§2.4·§2.6뿐이다.

**상수 정의 (RFC-0014 원문 불변):**
```
_UNTIL_ROUND_CAP = 16
```

#### 2.1 `when` 모드 (갱신)

조건을 **1회 평가**한다. 대안 가드가 없으면(§Reference-level Specification/1의
`AltGuard*`가 0개) RFC-0014 원문 그대로 — 조건이 참이면 피가드 항목을 실행하고,
거짓이면 건너뛴다.

**대안 가드가 있으면**, 조건과 모든 대안을 소스 순서대로 **전부 평가**한다
(단락 평가 없음 — RFC-0014가 `and`의 각 항을 전부 평가하는 것과 같은 이유:
조건은 순수하므로 결과는 같고, 트레이스는 평가되지 않은 항이 있으면 그 항의
값을 영영 보여줄 수 없다). **하나라도 참이면** 피가드 항목을 실행한다. 실행되는
경우, 트레이스는 참으로 판정된 첫 항이 조건 자신인지 몇 번째 대안인지를
`INFO` 레벨로 남긴다(§2.4에서 정의하는 스킵 레코드와는 다른 채널 — 스킵이
아니라 **실행됐다**는 사실의 관측이므로):

```
guard alternative matched: alt=0 condition="input.channel == 1"
```

조건 자신이 참이면 `alt=<primary>`로 남긴다(대안 번호가 아니라 원 조건이
참이었다는 뜻) — 이 경우는 대안 가드가 없는 기존 프로그램과 관측이 달라지지
않는다는 것을 보장하기 위한 표기이지, 새 요구 사항이 아니다: **대안이 없는
`when`은 이 로그를 전혀 내지 않는다**(하위 호환. `evaluations`가 issue #83에서
그랬듯, 새 신호는 그것을 켠 프로그램에서만 나타난다).

**전부 거짓이면**(대안 가드가 없을 때의 "거짓"과 동형), 건너뛴 사실은 trace에
기록되며, §2.4의 스킵 레코드 하나를 남긴다.

#### 2.4 스킵 레코드 (갱신)

실행 결과는 **스킵 매니페스트**를 가진다. 피가드 항목을 실행하지 않은 가드마다
레코드가 하나씩, 가드를 만난 순서대로 들어간다.

| 필드 | 의미 |
|------|------|
| `guard` | 가드 노드의 IR id. 모드 A 전용 — 모드 간 비교에서 제외한다 |
| `mode` | `"when"` 또는 `"until"` |
| `condition` | **갱신**: 대안이 없으면 정규화된 조건 문자열 그대로(RFC-0008 §4 불변). 대안이 있으면 조건과 모든 대안을 소스 순서대로 `" or "`로 이어붙인 문자열 — `"input.channel == 1 or input.amount <= 100"`. 이 결합은 **표시/비교 전용**이며 `parse_condition`으로 재파싱되지 않는다(§Reference-level Specification/3) |
| `steps` | 그 가드가 감싼 **모든 WorkflowStep의 이름**, 선언 순서. 중첩 블록(`Concurrency`·`Pipeline`)까지 하강해 수집한다 |
| `rounds` | `when`이면 없음(`null`), `until` 0라운드면 `0` |
| `evaluations` | (issue #83, RFC-0014 원문 불변 필드) **갱신**: 대안이 있으면 조건 자신의 항들에 이어 각 대안의 항들도 소스 순서대로 같은 리스트에 담는다 — 어느 항이 어느 대안 소속인지는 이 리스트의 위치가 아니라 `ref`가 가리키는 값으로 읽는다(추가 태깅 없음, RFC-0014가 이미 "다섯 키는 불변"이라 적은 원칙을 존중해 `evaluations`의 원소 shape을 넓히지 않는다) |

`condition`의 결합 표기는 `restore_skips`(모드 B 재구성)와 `_skip_record`(모드
A 실측)가 **같은 함수**로 만든다 — 이름은 §Reference-level Specification/5가
고정한다. 두 모드가 각자 결합하면 공백 하나의 실수가 `differential.verify`를
거짓 양성/거짓 음성으로 만든다.

**status 어휘는 변경되지 않는다** (RFC-0014 원문 불변).

#### 2.6 모드 A/B 동등성 (갱신)

두 모드는 스킵을 **같게** 관측해야 한다. 비교는 `guard`를 제외하고 스텝 단위로
편 투영 위에서 이루어진다 — `{mode, condition, step, rounds}`(RFC-0014 원문
불변, `evaluations`는 원문대로 계속 제외). `condition`이 대안을 포함한 결합
문자열일 때도 이 넷은 그대로 비교 대상이다 — §2.4가 두 모드에게 같은 결합
규칙을 강제하므로 새 비교 클래스나 새 필드가 필요 없다.

모드 B에서 대안 가드는 `arith.ori`로 각 대안의 `arith.cmpi` 결과를 접어
하나의 i1로 만든다(§Reference-level Specification/6). `until`은 대안 가드를
가질 수 없으므로(§Reference-level Specification/1), 이 접기는 `negate`
경로와 만나지 않는다 — RFC-0014 원문의 드모르간 우려(`and`의 `until` 부정)는
대안 가드에는 적용되지 않는다.

### 5. `guard_condition_text` — 신설 SSOT (`impl/lnpl/condition.py`)

모드 A(`interp._skip_record`)와 모드 B(`backend.restore_skips`) 양쪽이 §2.4의
`condition` 결합 표기를 만들 때 부르는 하나의 함수다:

```
guard_condition_text(condition: str, alternatives: Sequence[str] | None) -> str
```

`alternatives`가 없거나 빈 시퀀스면 `condition`을 그대로 반환한다(기존 단일
가드와 바이트 단위로 동일 — 이것이 하위 호환의 근거다). 있으면
`" or ".join([condition, *alternatives])`를 반환한다. 이 함수는 파싱하지
않는다 — 순수 문자열 결합이며, `parse_condition`의 문법에 `or`를 추가하지
않는다는 §Motivation의 결정을 코드 층위에서 지킨다.

### 6. Mode B — MLIR 표현식 lowering (신설, 표현식 부분만)

이 절은 `impl/lnpl/backend.py`의 **표현식 lowering**(S4/S5, `arith`/`scf`
방출)만을 규정한다 — clang 호출부·`tool()`·툴체인 경로(S7)는 이 RFC의 범위
밖이다(이슈 #93 dependencies, t104 소유).

**`*`/`/`는 가드 조건에만 닿는다 — Assignment 표현식에는 닿지 않는다.**
`_emit_operand`(`Arith` 분기가 사는 자리)의 유일한 호출자는
`_emit_condition`이고, `_emit_condition`의 유일한 호출자는 `_render_std`의
`when`/`until` 처리다. `Assignment.expression`은 `_lnpl_ops`가 `"lnpl.effect"`
마커 하나로만 방출하며 — 이름 그대로 문자열 하나, 파싱도 산술도 없다 — 이
경로는 RFC-0015가 `+`/`-`를 넣을 때도 손대지 않았다(§Differential
Equivalence "할당이 만든 값은 허용된 차이 — 모드 B는 저장소를 모형화하지
않는다"). 이 RFC도 그 경계를 넓히지 않는다: **DoD 1번의 예제
(`set order.total to product.price * input.quantity`)는 Assignment이므로,
모드 B에서의 EQUIVALENT는 여전히 "그 이름의 Assignment 효과가 있었다"는
사실만 검증한다 — 계산된 값(200)은 여전히 모드 A 단독 단언이다.** 이것은
새 제약이 아니라 `-`가 이미 서 있던 자리를 `*`가 그대로 따르는 것이다.

가드 조건 안에서 쓰인 `*`/`/`(예: `when product.stock * 2 >= input.min`)는
다르다 — 조건은 `condition_field_names`가 모든 참조를 i64 파라미터로
승격하므로(RFC-0008 G8), 그 필드가 저장 행에서 왔든 payload에서 왔든 모드 B
바이너리는 **실행 시점**에 실제 값을 받아 실제로 계산·비교한다. `_emit_
operand`의 `Arith` 분기(RFC-0015가 `+`/`-`에 이미 세운 것과 같은 자리)에
두 연산을 더한다: `*` → `arith.muli`, `/` → `arith.divsi`(부호 있는 절삭
나눗셈 — §Reference-level Specification/1의 "나눗셈은 절삭이다"가 바로 이
선택으로 실현된다).

**가드 조건에서 나눗셈이 0으로 평가되면.** `arith.divsi`는 0 나눗셈에 대해
정의되지 않은 동작이다(LLVM `sdiv`와 동형). 이것을 그대로 방출하면 컴파일된
바이너리가 크래시하거나 미정의 값을 낼 수 있다. 그런데 RFC-0015 §5가 이미
그은 경계 — **"값 차원은 모드 A가 단독으로 단언한다"** — 는 이 신설 값
실패에도 그대로 적용된다: 모드 B가 이 실패를 `RunError`/`failed`로
**보고할 의무는 없다**(오늘도 산술 오버플로·비수치 비교 같은 다른 값 실패를
보고하지 않는다 — 이 RFC 이전부터 있던 차동 경계이지, 이 RFC가 새로 뚫는
자리가 아니다). 모드 B의 유일한 의무는 **정의되지 않은 동작을 만들지
않는 것**이다: `/`를 방출하기 전에 오른쪽 피연산자가 0인지
`arith.cmpi eq`로 검사하고, 0이면 그 비교 항을 **거짓**으로 접어 넣는다
(참조가 아무것도 가리키지 않을 때 `false`로 접히는 §Reference-level
Specification/2의 "참조 미해소" 행과 같은 안전한 기본값 — 실패를 신호하는
값이 아니라 UB를 피하는 값이다). 이 분기는 `scf.if`로 `arith.divsi`
자체를 감싸 실행하지 않는 쪽을 택한다 — 정의되지 않은 연산은 계산 후 버리는
것이 아니라 애초에 실행하지 않아야 UB가 없다.

**따라서 DoD 2번(0 나눗셈 → RunError, status failed)의 차동 커버리지는
경계가 있다.** 정상 분모(0이 아닌)에서는 `*`/`/`를 쓴 가드 조건이 두 모드
합의를 내는지 차동으로 검증한다(§Reference-level Specification/7 D5).
분모가 실제로 0인 케이스는 — Assignment 경로든 가드 조건 경로든 — 모드 A만
`RunError`/`failed`를 단언하는 테스트로 남는다(오늘의 오버플로·비수치
RunError 테스트가 이미 그런 것과 같은 층위). 이것은 이 RFC의 결정이지
누락이 아니다 — §Alternatives에 기록한다.

**대안 가드.** `_emit_condition`은 단일 조건일 때 완전히 불변이다(SSA 이름
`%cond<idx>`/`%ucond<idx>`가 그대로 유지되어 `impl/tests/golden/*.std.mlir`의
동결 픽스처가 움직이지 않는다). 대안이 있을 때만 새 경로를 탄다: 조건과 각
대안을 독립적으로 `_emit_condition`에 태워 `%cond<idx>_0`, `%cond<idx>_1`, …
i1 SSA 이름을 얻고, `arith.ori`로 순서대로 접어 하나의 i1을 만든다. 대안 중
하나라도 `_emit_condition`이 `None`을 반환하면(Presence — 컴파일된 평가기가
없다, RFC-0015 §1 원문 불변) 전체가 `None`이 되어 기존 런타임 `%skip` 플래그
경로로 떨어진다 — OR의 한쪽이 컴파일 불가능한데 다른 쪽만 컴파일하면 그
쪽만 평가하고 트레이스가 조용해지는 결과를 낳는다(§2.1의 "전부 평가" 원칙과
모순). `condition_field_names`는 조건과 모든 대안의 참조 합집합을 모은다
(정렬 순서는 RFC-0008 G8 불변). `_render_std`의 리터럴 상수 수집(`cond_i64_
values`)도 조건과 모든 대안을 스윕한다. `_walk_markers`/`emit_lnpl_mlir`의
`lnpl.guard` 마커는 `lnpl.guard_alternatives`(문자열 배열, 대안이 없으면
생략) 속성을 추가로 싣는다 — `_mlir_attr`은 이미 리스트/튜플을 렌더링하므로
새 직렬화 코드가 필요 없다.

## Examples

### 골든 시나리오 "Login" (RFC-0007 §6)

`Login` 워크플로(`validate input` → `authenticate` → `generate token` →
`audit login` → `return token`)는 이 RFC가 다루는 기능(산술, 대안 가드)을 쓰지
않는다. RFC-0007 §6이 요구하는 대로 정본을 참조만 하고 재정의하지 않는다.
골든 자체는 바뀌지 않는다(`examples/login.lir.json` 불변).

### 골든 인접 예제 — 단가 계산 (RFC-0007 §6, 골든이 다루지 않는 기능)

```
capability postgres

entity Product
    field
        id UUID
        stock Integer
        price Integer

entity Order
    field
        id UUID
        quantity Integer
        total Integer

service OrderService
    policy
        timeout 5s

workflow PlaceOrder
    read product
    when product.stock >= input.quantity
    create order
    when product.stock >= input.quantity
    set order.total to product.price * input.quantity
    set product.stock to product.stock - input.quantity
```

`stock=5, price=100, quantity=2` → 5스텝 completed, `order.total == 200`,
`product.stock == 3`. 모드 A/B 차동 EQUIVALENT(실행 순서·정책 결과·관측
신호가 일치 — 할당이 만든 **값**은 RFC-0015 §5가 이미 "허용된 차이"로 적어
둔 대로 모드 A만 단언한다).

**0 나눗셈:**

```
    set order.total to order.total / input.quantity
```

`input.quantity == 0`으로 실행하면 그 스텝에서 `RunError: division by zero`,
`status: failed`, `failed at: set order.total to order.total / input.quantity`.

### 골든 인접 예제 — 대안 가드 (RFC-0007 §6, 골든이 다루지 않는 기능)

```
capability postgres

entity Payment
    field
        id UUID
        channel Integer
        amount Integer

service PaymentService
    policy
        timeout 5s

workflow Approve
    when input.channel == 1
    or input.amount <= 100
    create payment
```

- `channel=1, amount=5000` → 대안 없이 조건 자신이 참, `create payment` 실행,
  트레이스에 새 로그 없음(기존 `when`과 관측이 동일).
- `channel=2, amount=50` → 조건 거짓, 대안(`amount <= 100`) 참, `create
  payment` 실행, 트레이스에 `guard alternative matched: alt=0
  condition="input.amount <= 100"`.
- `channel=2, amount=5000` → 조건과 대안 둘 다 거짓, `create payment`
  건너뜀, `skipped[0]`:
  ```json
  {"mode": "when",
   "condition": "input.channel == 1 or input.amount <= 100",
   "steps": ["create payment"], "rounds": null,
   "evaluations": [
     {"ref": "input.channel", "value": 2, "op": "==", "expected": 1, "holds": false},
     {"ref": "input.amount", "value": 5000, "op": "<=", "expected": 100, "holds": false}
   ]}
  ```
  세 번째 evaluations 항목이 대안(`amount <= 100`) 소속임은 그 `ref`로 읽는다
  — §Reference-level Specification/4가 적은 그대로다.

### 컴파일 거부 — 괄호·중첩 (기존과 동일, RFC-0015 §3 불변)

```
    when (product.stock - input.quantity) > 0
```

→ `unsupported operand form ...` (RFC-0015 does not nest arithmetic) — 이
RFC는 §3을 손대지 않았으므로 메시지도 인용도 그대로다.

### 컴파일 거부 — `until` 뒤의 `or`

```
    until stock >= 10
    or stock >= 20
    step Wait
```

→ `line 9: `or` continues a `when` guard's alternatives, but the pending
guard on line 8 is `until` (RFC-0028: alternative guards apply to `when`
only)`.

### 컴파일 거부 — 리터럴 0 나눗셈

```
    set order.total to order.total / 0
```

→ 컴파일 에러(정적 거부, §Reference-level Specification/2) — `division by
zero is not a runtime input here: the right operand is the literal 0`.

## Alternatives

### 곱셈·나눗셈을 이번에 넣는 이유 (RFC-0015 §Alternatives의 기각을 뒤집는다)

RFC-0015 §Alternatives("곱셈·나눗셈을 넣지 않는 이유")는 "이슈 #47의 다섯
요구 중 어느 것도 요구하지 않는다"를 근거로 기각했다. 그 근거 자체는 그때
맞았다 — 이슈 #47은 그것을 요구하지 않았다. 이슈 #93이 새로 요구한다(단가
계산의 실측 공백). RFC-0007 §5의 "구현을 명세에 맞춘다" 원칙과 §2.1의
"Accepted RFC는 본문을 편집하지 않는다"는 이 상황을 위한 것이다 — RFC-0015의
그 문단은 **역사적으로 정확한 기록**으로 남고, 이 문서가 새 사실(이슈 #93)
아래 새 결정을 얹는다.

나눗셈이 그때 우려했던 "반올림 의미"는 Decimal에서만 발생한다 — Integer
나눗셈은 절삭 하나로 고정되므로(§Reference-level Specification/1) 반올림
정책을 고를 필요가 없다. "0 나눗셈을 두 런타임에서 동시에 정의"하는 비용은
§Reference-level Specification/2·6이 냈다 — 다만 그 정의가 **양쪽이 같은
결과를 낸다**는 뜻은 아니다. 다음 항이 그 경계를 적는다.

### 0 나눗셈에서 모드 B에게 `RunError` 합의를 요구하지 않는 이유

처음에는 가드 조건의 `/`가 0으로 나뉘면 모드 B도 실패를 신호해야 한다고
설계했다(방출된 `arith.divsi` 앞에 `func.call`류의 실패 경로를 두는 안).
`Assignment.expression`이 모드 B에서 애초에 계산되지 않는다는 사실(§6) —
RFC-0015가 `+`/`-`를 넣을 때 이미 그은 경계 — 을 다시 확인하면서 이 안을
기각했다: DoD 1번이 요구하는 예제(`set order.total to product.price *
input.quantity`)는 Assignment이므로, 그 나눗셈 사촌(`set ... to ... / ...`)
역시 모드 B가 값을 계산하지 않는 경로에 있다. **모드 B에게 없는 계산의
실패를 모드 B가 보고하라고 요구할 수 없다.**

가드 조건 안의 `/`(모드 B가 실제로 계산하는 유일한 자리)에서도 같은
경계를 유지하기로 한 것은 일관성이다: RFC-0015 §5가 이미 "값 차원은 모드
A가 단독으로 단언한다"고 적어 두었고, 그 문장은 산술 오버플로·비수치
비교에도 적용되며 지금까지 그 어느 것도 모드 B 차동 테스트가 없다. 0
나눗셈만 예외로 승격할 근거가 없다 — 오히려 `arith.divsi`가 정의하지 않은
동작이라는 사실은 "합의하라"가 아니라 "크래시하지 않게 만들라"는 더 약하고
더 정확한 요구를 가리킨다(§Reference-level Specification/6).

### `not`을 넣지 않는 이유 (이슈 #93 제안 그대로)

`!=`와 `missing`이 이미 `not ==`과 `not exists`의 등가를 표현한다. 별도
`not` 연산자는 그 등가의 **두 번째 스펠링**일 뿐이라 언어 표면을 넓히는
비용에 비해 표현력을 더하지 않는다.

### `until`/`repeat`에 대안 가드를 넣지 않는 이유

이슈 #93은 `when A or B`만 요구했다. `until`의 "OR 종료 조건"(`until A or B`
= A 또는 B가 참이 될 때까지 반복)은 자연스러운 일반화지만, 모드 B의 부정
경로가 대안 가드와 만나면 드모르간을 OR-접기 결과에 다시 적용해야 한다
(`NOT (A or B) = NOT A and NOT B`) — 이는 §Reference-level Specification/6이
지금 쓰는 "OR-접고 끝"보다 한 겹 더 복잡한 방출기 분기이고, 아무 요구도
없는 표면을 위해 두 번째 De Morgan 자리를 여는 것은 이 RFC가 §Motivation에서
따르기로 한 최소 표면 원칙과 충돌한다. `repeat`에는 애초에 `Condition`이
없다.

### 대안 가드를 `Condition` 문법 안의 `or` 연산자로 넣는 안 (기각)

`Condition ::= ... | Condition 'or' Condition`처럼 넣으면 한 줄로 끝나지만,
§Motivation이 인용한 Rego의 교훈과 정확히 반대 방향이다 — 표현식에 `or`가
들어가면 다음은 괄호(`(a or b) and c`), 그다음은 우선순위 규칙이다. `Value`의
"이항 1개, 중첩 없음" 제한과 같은 이유로, 구조로 미는 쪽을 택한다.

### 스킵 레코드에 대안별 전용 필드를 추가하는 안 (기각)

`{"condition": "...", "alternative_results": [{"condition": "...", "holds":
false}, ...]}`처럼 대안마다 독립된 서브레코드를 만드는 안을 검토했다.
`evaluations`가 issue #83에서 이미 "다섯 키는 불변, 이 필드만 additive"라고
정한 계약을 지키는 쪽(§Reference-level Specification/4)이 더 작은 표면
변경이고, `ref`로 항을 식별하는 기존 관례와도 맞는다. 소비자가 "어느 대안"을
알고 싶으면 `ref`가 속한 조건 텍스트를 §Reference-level Specification/5의
`guard_condition_text`로 재구성된 원본과 대조하면 된다(§4의 `condition`
필드가 이미 `" or "`로 이어붙인 전체 텍스트를 싣는다).

## Open Questions

1. **`until`/`repeat`의 대안 가드.** §Alternatives가 미룬 대로, 요구가
   생기면 후속 이슈로 다룬다. 그때 모드 B의 부정 경로가 어떻게 OR-접기와
   상호작용하는지(드모르간을 언제 펴는가)를 다시 설계해야 한다.

2. **Decimal 나눗셈과 반올림 정책.** RFC-0015 §Open Questions 4가 이미 적어
   둔 "통화 산술은 타입 시스템의 개정"이라는 경계는 이 RFC가 그대로 잇는다.
   Integer `/`의 절삭 규칙이 Decimal에도 그대로 적용될지는 그 개정의 몫이다.

3. **`guard_condition_text`의 재파싱 가능성.** 지금은 표시/비교 전용이라
   `" or "`로 이어붙인 텍스트를 다시 파싱하지 않는다. 만약 향후 어떤 소비자가
   스킵 레코드의 `condition`만 보고 원래 대안 목록을 복원해야 한다면(예:
   LLM 자가수정이 스킵 레코드만 읽고 프로그램을 고치는 시나리오), 결합
   대신 구조화된 표현이 필요해진다 — RFC-0015 §Open Questions 5(IR 조건의
   구조화)와 같은 긴장이다.

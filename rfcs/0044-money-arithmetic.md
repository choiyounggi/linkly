# RFC-0044: Money 산술 — minor-unit 코덱과 반올림 정책

## Status

- Status: **Accepted** (RFC-0044, 2026-08-30)

이 RFC는 기존 Accepted RFC의 어떤 절도 Supersede·Update하지 않는다 — 독립 신규
RFC다. Money(RFC-0001 §Semantic Type 시스템)는 지금까지 "평가기가 없다"는 사유로
비교·산술 어디에도 참여하지 못했다(RFC-0015 §3, RFC-0016 §3, RFC-0025 §3가 각자
맥락에서 같은 사유를 반복한다). 이 RFC는 그 거부를 뒤집지 않는다 — 대신 Money가
참여할 **새 문법 위치**(집계, 자매 RFC-0045가 여는 자리)가 요구하는 평가기(코덱 +
반올림 정책)를 **처음으로** 정의할 뿐, 기존 `Value`/`Operand`(가드 조건·평범한
`set` 산술)에는 Money를 들이지 않는다 — 그 문법은 RFC-0016 §3·RFC-0015 §3 원문
그대로 유효하며 이 RFC가 손대지 않는다. References: RFC-0001(§Semantic Type 시스템 —
Money/Decimal/Currency 정의 불변), RFC-0015(§Open Questions 4 — "통화 산술은 타입
시스템의 개정"이 가리키던 그 개정), RFC-0016(§Reference-level Specification/2 —
i64 evaluation-channel 코덱의 선례, 이 RFC의 모델), RFC-0028(§Reference-level
Specification/1 — Integer 나눗셈 절삭 규칙, 이 RFC가 보존하는 불변식), RFC-0025
(§Reference-level Specification/3 — Money 필드 집계 거부, 그 거부를 좁히는 것은
자매 RFC-0045의 몫).

번호가 0044인 이유: 0043까지 점유됐다(RFC-0043, 드라이버 집행 신고). RFC-0007 §3은
번호 재사용을 금지한다.

**구현은 후속이다.** 이 RFC는 계약(코덱·리터럴 문법·반올림 정책)만 확정한다 —
`impl/lnpl/money.py`의 `CURRENCY_EXPONENT`·`encode_money`·`avg_round` 등 실제
코드는 이 RFC가 만들지 않는다(RFC-0043이 "구현·문서 반영은 t-enf의 몫이다.
이 RFC는 계약만 확정한다"고 적은 것과 같은 위상).

## Motivation

`qa/rerun/REPORT.md` §4(blocker t3 F-1)의 재측정이 정확히 이 공백을 실측했다:
"잔존: Money 산술 rc=2(`"Integer nor DateTime"` 진단 — evidence/04-probe-a2-
compile.log 시도 2)". `report.total`처럼 파생 Money 값을 계산하려던 프로그램은
그 진단으로 막히고, 원문은 결제 총액 리포트가 "스펙 이탈 없이 표현 불가"라고
적는다(§6.1 r3 F-1 행). 같은 공백은 그 이전부터 문서에 남아 있었다: RFC-0015
§Open Questions 4가 "통화 산술은 반올림 정책과 통화 일치 규칙을 함께 요구하므로
값 문법이 아니라 타입 시스템의 개정이다"라고 유예했고, RFC-0028 §Open Questions 2가
"그 개정의 몫"이라고 다시 미뤘으며, RFC-0025 §3은 Money 필드 집계를 "평가기가
없다"는 같은 사유로 거부했다. 세 유예가 가리키는 개정이 이것이다.

이슈 #145가 요구하는 것은 세 가지다: **(1)** Money를 minor-unit 정수로 인코딩하는
코덱 — "이진 부동소수점 표현 금지"(RFC-0001 §Semantic Type 시스템의 Money 행)라는 기존
제약을 실제 평가기로 실현한다. **(2)** 나눗셈·반올림 정책 — 평균 등 통화 산술이
필연적으로 만나는 나눗셈에 단일 규칙을 준다. **(3)** 그 위에서 `avg`/`min`/`max`가
Money를 포함하도록 집계를 넓힌다. 이 문서는 (1)·(2)를 정의한다 — Money의 **평가기
자체**(어떻게 인코딩되고, 어떻게 반올림되는가). (3)은 자매 RFC-0045(§Reference-
level Specification)가 정의한다 — 그 RFC가 실제로 `AggFunc` 문법과 RFC-0025 §3의
거부 표를 넓히는 절 단위 갱신을 진다. 이 분리는 RFC-0016이 "시간 값의 인코딩"(자신의
§2)과 "피연산자의 차원 규칙"(자신의 §3)을 한 문서 안에서도 사유를 나눠 적은 것과
같은 이유다 — 코덱은 **무엇이 계산 가능해지는가**의 전제이고, 그 전제를 어느 문법
위치에서 실제로 소비하는가는 별개 결정이다.

## Guide-level Explanation

Money 필드는 오늘과 똑같이 선언한다 — `{amount: Decimal, currency: Currency}`라는
와이어·저장 표면은 이 RFC가 손대지 않는다(RFC-0001 §Semantic Type 시스템 그대로, 아래
§Reference-level Specification/1).

```lnpl
entity Payment
    field
        id UUID
        amount Money
```

새로 쓸 수 있게 되는 것은 `spec`의 `given`/`expect` 자리에 쓰는 **Money 리터럴**
하나다 — RFC-0016이 기간에 `30d`를 준 것과 같은 자리, 같은 모양의 결정이다.

```lnpl
    spec
        given
            stored Payment id 1
            stored Payment amount 100.50USD
        when
            findPayment
        expect
            completed
            result payment.amount == 100.50USD
```

`100.50USD`는 `<정수부>.<소수부><ISO 4217 alpha-3>` 한 토큰이다. 소수부 자릿수는
그 통화의 **exponent**(ISO 4217이 정의하는 소수 자릿수, 아래 §Reference-level
Specification/2)와 정확히 일치해야 한다 — `USD`는 2자리이므로 `100.5USD`나
`100.500USD`는 거부되고, `JPY`(exponent 0)는 소수점 자체를 거부한다(`100JPY`는
유효, `100.00JPY`는 무효). 리터럴은 **계산 결과가 아니라 저작자가 쓴 값**이므로
반올림이 적용되지 않는다 — 자릿수가 틀리면 저작자가 의도한 값을 추측하지 않고
거부한다(닫힌 어휘 원칙과 같은 태도).

위 `expect result ... == 100.50USD`가 새로 통하는 이유는 두 갈래다. **등가**는
사실 새 평가기를 요구하지 않는다 — RFC-0038 §3.1이 이미 세운 원칙("등가는
평가기가 필요 없다 — 두 값이 같은지는 비교 연산자 없이도 판정된다")이 여기서도
성립한다: `payment.amount`와 `100.50USD`가 정규화한 `{amount, currency}` 두
JSON이 완전히 같은지 구조적으로 비교할 뿐이다. 이 RFC가 새로 여는 것은 그
비교의 **오른쪽 리터럴을 쓰는 문법**(`MoneyLiteral`)이지, 등가 평가기 자체가
아니다. 반면 **순서·산술**(`<`/`>`, 덧셈, 나눗셈)은 진짜 평가기가 필요하다 —
그것이 이 RFC가 §Reference-level Specification/1·4·5에서 실제로 주는 것이고,
그 문법을 여는 것은 RFC-0045다.

**이 RFC가 열지 않는 것**은 명시적이다: Money는 가드 조건(`when`/`until`)이나
평범한 `set ... to <산술>`의 피연산자로 여전히 쓸 수 없다 — RFC-0016 §3의 차원
표("Money와 합성 타입은 여전히 어느 차원도 아니며 컴파일 거부다")가 그대로
유효하다. 이 RFC가 주는 순서·산술 평가기는 오직 **집계**(RFC-0025의 `Aggregate`
생산 규칙, RFC-0045가 여는 문법)만 쓴다. `product.price * input.quantity`류의
일반 산술에 Money를 들이는 것은 이 RFC의 범위 밖이다(§Alternatives 1).

## Reference-level Specification

### 1. Money의 두 표현 — 와이어/저장은 불변, 평가 채널만 신설

RFC-0016 §2가 DateTime에 세운 패턴을 그대로 따른다: **선언·저장·와이어 표면은
바뀌지 않는다.** Money는 계속 RFC-0001 §Semantic Type 시스템의 `{amount!: Decimal,
currency!: Currency}`이고, `Decimal`은 계속 OpenAPI `string`으로 인코딩된다
(RFC-0001 §Open Questions 5). 이진 부동소수점을 쓰지 않는다는 그 절의 제약을
이 RFC의 인코딩이 실제로 지킨다 — 부동소수점을 한 번도 거치지 않는다.

**평가 채널**(RFC-0045가 여는 집계 평가기가 실제로 계산하는 자리)에서만 Money는
**부호 있는 64비트 정수 하나(minor units) + 통화 코드 하나**로 인코딩된다:

```
encode_money(amount: <decimal-string>, currency: <alpha-3>) -> (minor: i64, currency: str)
minor = amount × 10^exponent(currency)
```

인코딩 대상은 언제나 저작자가 쓴 리터럴(§3)이거나 저장소가 이미 들고 있는 값이고,
§3의 자릿수 일치 규칙이 소수부를 정확히 exponent 자리로 고정하므로 `amount ×
10^exponent`는 **언제나 정수**다 — 이 함수는 반올림을 수행하지 않는다(반올림이
필요한 유일한 자리는 §4의 나눗셈이지, 인코딩이 아니다). 이 불변식을 어긴 입력
(예: 스펙 밖에서 임의 정밀도로 채워진 저장소 값)은 RFC-0016 §2의 "소수 초는
밀리초로 절단한다"처럼 조용히 절단하지 않고, `RunError`(`money-encode-precision`)
로 명시 거부한다 — RFC-0015 §4의 기존 실패 클래스(`failed`, rc=1)를 그대로 쓴다.

### 2. ISO 4217 exponent — 닫힌 3버킷 규칙

exponent는 통화마다 다르다 — ISO 4217이 정의하는 소수 자릿수다([ISO 4217 공식
안내](https://www.iso.org/iso-4217-currency-codes.html): "For currencies
having minor units, ISO 4217:2015 also shows the relationship between the
minor unit and the currency itself"). 실측 표([currencyconversion.org](
https://currencyconversion.org/guides/currency-codes-iso-4217),
[docs.datatrans.ch](https://docs.datatrans.ch/docs/currency-codes))가 합의하는
세 버킷:

| exponent | 통화 | 의미 |
|----------|------|------|
| 0 | `BIF` `CLP` `DJF` `GNF` `ISK` `JPY` `KMF` `KRW` `PYG` `RWF` `UGX` `VND` `VUV` `XAF` `XOF` `XPF` | 소수 자릿수 없음 — 정수 단위가 곧 minor unit |
| 3 | `BHD` `IQD` `JOD` `KWD` `LYD` `OMR` `TND` | 3자리 소수 |
| 2 (기본) | 위 두 버킷에 없는 그 밖의 활성 ISO 4217 코드(`USD` `EUR` `GBP` `CNY` `INR` 등, 절대다수) | 2자리 소수 — 가장 흔한 경우 |

이 세 버킷이 **닫힌 표**다(`impl/lnpl/money.py`의 `CURRENCY_EXPONENT` 딕셔너리가
정본 — 구현이 소유). 표에 없는 문자열(가상 통화 코드, 폐기된 코드, 오타)은
exponent가 정의되지 않으므로 **거부**한다 — 3버킷 규칙이 exponent를 몰라서 2로
어림짐작하는 조용한 오판을 만들지 않는다는 뜻이다. `Currency` 타입 자체의 형태
검사(ISO 4217 alpha-3, 정확히 3자, RFC-0001 §Semantic Type 시스템)는 이 RFC가 손대지
않는다 — 형태가 유효해도 활성 통화 표에 없으면 exponent 조회가 실패한다.

전 ISO 4217 활성 코드(약 180개)의 전체 목록을 이 RFC 본문에 그대로 옮기지
않는다 — 위 두 버킷의 **예외 소속**만 계약하고(닫힌 목록, additive하게만 갱신
가능), 그 밖의 활성 코드가 전부 exponent 2라는 규칙이 나머지를 완전히 결정한다.
`CURRENCY_EXPONENT`의 전체 항목 생성은 ISO 4217 공식 데이터를 스냅샷으로 박아
넣는 구현의 몫이다(스냅샷 날짜를 코드 주석에 남긴다) — 이 레포가 이미
`scripts/gen_plugin_references.py`로 생성 산출물과 정본을 분리하는 것과 같은
원칙이다.

### 3. Money 리터럴 — 새 생산 규칙 (신설, 기존 문법 불변)

```
MoneyLiteral  ::= Integer ('.' Digit+)? CurrencyCode
CurrencyCode  ::= UpperAlpha UpperAlpha UpperAlpha
```

이 생산 규칙은 RFC-0015 §1의 `Value`/`Operand`/`ArithOp`에 **추가되지 않는다**
— `MoneyLiteral`은 그 문법 트리에 속하지 않는, `spec`의 `given`/`expect` 단일
토큰 자리(RFC-0020의 `<value>`)에서만 유효한 새 어휘다. `Duration`이 `Value`의
`Operand`로 들어간 것(RFC-0015 §1)과 달리, `MoneyLiteral`은 **어떤 `Operand`
자리에도 나타나지 않는다** — Money가 가드·`set` 산술에 참여하지 않는다는
§Guide-level Explanation의 결정이 문법 층위에서 그대로 반영된 것이다.

RFC-0020의 `<value>` 토큰 파서(`stored`/`input.<field>`/`expect result`가 공유
하는 단일 토큰 값 해석)는 대상 필드의 선언 타입이 `Money`일 때 이 생산 규칙으로
토큰을 해석한다 — 그 상위 문법(phrase 형태, `stored <entity> <field> <value>`의
4토큰 구조)은 RFC-0020·RFC-0025 §8 원문 그대로이며 이 RFC가 손대지 않는다:
바뀌는 것은 `<value>` 자리가 Money 필드를 만났을 때의 **의미**뿐이다.

**소수 자릿수 = exponent, 정확히.** `<정수부>.<소수부>`의 소수부 길이가 그
`CurrencyCode`의 exponent와 다르면 컴파일 거부(exponent 0이면 `.`이 아예 없어야
한다). 저작자가 쓴 리터럴은 계산 결과가 아니라 입력이므로, 반올림으로 자릿수를
맞추지 않는다 — RFC-0015 §1이 "리터럴은 부호가 없다"고 고정한 것과 같은 태도:
리터럴은 계산되지 않고 그대로 읽힌다.

**정규화.** IR에 싣는 형태는 `{"amount": "<정수부>.<소수부 또는 생략>",
"currency": "<코드>"}` — RFC-0001의 기존 Money JSON shape 그대로다. 새 필드도
새 스키마도 없다: `MoneyLiteral`은 **문법**이지 새 IR 노드가 아니다.

### 4. 나눗셈·반올림 정책 — half-to-even (신설)

Money 평가기가 나눗셈을 계산할 때는 **half-to-even**(round half to even,
"banker's rounding")을 쓴다 — 5로 끝나는 동점을 가장 가까운 **짝수**로 반올림
한다. IEEE 754는 이것을 기본 반올림 모드로 정의한다([round-to-nearest
ties-to-even이 IEEE 754의 기본값](
https://wiert.me/2014/05/08/net-uses-bankers-rounding-as-default-as-it-follows-ieee-754-via-stack-overflow/)
— Java·C#·Python `round()`가 채택). 반올림은 항상 **minor unit** 정수 자리에서
멈춘다 — Money는 그 아래 정밀도를 갖지 않는다(§1).

```
avg_round(total: i64, count: i64) -> i64      # count > 0 요구, 계약은 이 절이 정한다
```

`count == 0`은 이 함수의 정의역 밖이다 — 호출자(이 함수를 실제로 부르는 자리는
RFC-0045의 `avg` AggFunc 하나뿐이다)가 그 경계를 어떻게 실패시키는지는 RFC-0045
§Reference-level Specification/3이 정한다. 이 절은 함수의 **반올림 규칙**만
계약한다.

**Integer 나눗셈(`/` 연산자, RFC-0028)은 이 정책의 적용을 받지 않는다 — 절삭
그대로다.** 이것은 비대칭이고, 의도적이다:

1. **기존 계약 보존.** `/`는 RFC-0028 §Reference-level Specification/1이 이미
   `arith.divsi`(모드 B가 실제로 컴파일하는 부호 있는 정수 나눗셈, 몫을 0
   방향으로 자른다)로 고정했고, 그 절을 "`stock=-7, batch=2` 같은 입력에서
   두 모드가 다른 몫을 내는 것을 피하기 위한 선택"이라고 근거까지 적었다.
   그 계약을 오늘 바꾸면 이미 절삭으로 합의된 프로그램이 조용히 다른 값을
   내는 **행위 변경**이 된다 — RFC-0007 §2.2 규칙 2(모순 금지)를 어기지
   않으려면 새 RFC가 그 계약을 재확인할지언정 바꿀 수는 없다.
2. **금융 표준과의 정합.** `avg`가 새로 여는 나눗셈은 기존 계약이 없는 **새
   자리**이므로, `/`의 절삭을 그대로 물려받을 의무가 없다 — 그리고 금융
   집계(평균 잔액, 평균 청구액)의 실무 관행은 절삭이 아니라 half-to-even이다.
   [Modern Treasury의 정수-우선 원칙](
   https://www.moderntreasury.com/journal/floats-dont-work-for-storing-cents)이
   부동소수점 대신 minor-unit 정수를 쓰는 이유를 세웠고, 그 정수 나눗셈이
   만나는 반올림 질문에 이 RFC가 half-to-even으로 답한다.
3. **Integer avg도 같은 정책을 쓴다** — Money 전용 규칙이 아니라 **집계
   나눗셈** 전반의 정책이다. Integer 필드의 `avg`와 Money 필드의 `avg`는 같은
   `avg_round(total, count)` 함수를 부른다(RFC-0045 §Reference-level
   Specification). 그래서 Integer 필드의 `avg`가 같은 필드의 `/` 연산자와
   다른 반올림을 낼 수 있다 — 두 연산이 다른 자리(하나는 저작자가 쓴 산술식,
   하나는 집계가 대신 계산하는 통계량)이므로 같은 규칙일 필요가 없다는 것이
   이 RFC의 판단이다.

### 5. 순서·산술의 통화 규칙 — 같은 통화만, 그 밖은 RunError

Money 값 두 개를 **순서 비교**(`<`/`<=`/`>`/`>=`)하거나 **더하는** 평가기는
양쪽의 통화 코드가 같을 때만 정의된다. RowSet의 각 행은 저장소 데이터이므로,
두 행의 `currency`가 같은지는 **런타임에만** 안다 — Money 필드는 통화를 타입
파라미터가 아니라 행 데이터로 갖는다(RFC-0001 §Semantic Type 시스템, 이 RFC가 바꾸지
않는다). 컴파일 시점에 통화 일치를 검사하려면 필드 선언에 통화를 고정하는 새
refinement 표기가 필요한데, 그것은 RFC-0001 §Open Questions ⑤(복합류 base의
refinement — 내부 필드를 지목할 표기가 아직 없다)가 이미 미정으로 남긴 자리다.
이 RFC는 그 미정을 해소하지 않는다(§Alternatives 5) — 대신 RFC-0028의 0 나눗셈과
같은 패턴을 따른다: **순서·산술 평가기가 실제로 서로 다른 통화의 두 값을
만나면** `RunError`(`money-currency-mismatch`)로 그 스텝을 실패시킨다 —
`status: failed`, `failed at: <스텝명>`, rc=1(RFC-0015 §4의 기존 실패 클래스,
새 결과 클래스를 만들지 않는다).

**등가(`==`/`!=`)는 이 규칙의 대상이 아니다** — §Guide-level Explanation이 이미
적은 대로, 등가는 구조적 비교이지 이 평가기를 거치지 않는다. 통화가 다른 두
Money는 등가 비교에서 그냥 "같지 않다"(`false`)이지 실패가 아니다.

**이 순서·산술 평가기를 실제로 부르는 자리는 이 RFC에 없다** — Money는 가드·
`set` 산술의 `Operand`가 아니므로(§Guide-level Explanation), 이 RFC 혼자서는
이 규칙이 관측되는 프로그램을 만들 수 없다. RFC-0045의 `sum`/`avg`/`min`/`max`
(Money 필드에 적용될 때)가 이 규칙의 유일한 호출자다.

## Examples

### 골든 시나리오 "Login" (RFC-0007 §6)

`Login` 워크플로는 Money 필드를 선언하지 않는다 — 정본을 참조만 하고 재정의하지
않는다. 골든 자체는 바뀌지 않는다.

### 골든 인접 예제 — Payment 시드·단언 (RFC-0007 §6, 골든이 다루지 않는 기능)

```lnpl
capability postgres

entity Payment
    field
        id UUID
        amount Money

service PaymentService
    policy
        timeout 5s

workflow FindPayment
    find payment
    spec
        given
            stored Payment id 1
            stored Payment amount 100.50USD
        when
            findPayment
        expect
            completed
            result payment.amount == 100.50USD
```

`100.50USD`는 minor units로 `10050`(exponent 2)으로 평가될 **수 있는** 리터럴
이다 — 이 예제 자체는 등가 비교만 쓰므로(§Guide-level Explanation), 평가 채널은
전혀 관여하지 않는다. IR에는 `{"amount": "100.50", "currency": "USD"}`로 실린다
(§Reference-level Specification/3).

거부되는 리터럴:

```
stored Payment amount 100.5USD    # USD는 exponent 2 — 소수 한 자리는 거부
stored Payment amount 100.00JPY   # JPY는 exponent 0 — 소수점 자체가 거부
stored Payment amount 100.50XYZ   # XYZ는 활성 ISO 4217 표에 없음 — exponent 미정
```

## Alternatives

| # | 검토한 대안 | 기각 사유 |
|---|------------|----------|
| 1 | **Money를 가드·`set` 산술의 `Operand`로 즉시 연다**(`when payment.amount > 100USD`, `set order.tax to order.total * taxRate`) | RFC-0016 §3의 차원 표를 갱신해야 하는 별도 설계 결정이다 — 등가 비교뿐 아니라 순서 비교·산술 결합까지 다시 규정해야 하고, 이슈 #145는 avg/min/max 집계만 요구한다(§Motivation). 요구되지 않은 표면을 먼저 여는 것은 RFC-0025 §Alternatives 6이 이미 세운 "세우지도 않은 요구를 충족시키는 일이다"는 기각 원칙과 같은 방향이다. §Open Questions 1로 이월 |
| 2 | **부동소수점(float64) 코덱** | RFC-0001 §Semantic Type 시스템이 Money에 이미 "이진 부동소수점 표현 금지(합산 오차)"를 못박았다 — [Modern Treasury의 정수-우선 원칙](https://www.moderntreasury.com/journal/floats-dont-work-for-storing-cents)이 실측으로 보이는 그 오차(0.1+0.2 != 0.3류)를 그대로 상속한다 |
| 3 | **`Decimal`(임의 정밀도)을 두 런타임에 함께 구현** | RFC-0015 §Open Questions 4·RFC-0028 §Open Questions 2가 이미 미룬 자리다 — Decimal 평가기는 모드 A/B 양쪽에 임의 정밀도 십진 연산을 새로 들이는 별도 크기의 작업이고, minor-unit i64는 기존 i64 값 도메인(RFC-0015 §4)을 재사용해 그 비용을 피한다. Money가 요구하는 것은 "통화의 고정 소수 자릿수 정수"이지 임의 정밀도가 아니다 |
| 4 | **exponent를 통화 코드마다 손으로 판정하는 대신 IANA/ICU류 라이브러리 조회** | RFC-0016 §Alternatives 4가 IANA 존 이름을 기각한 것과 같은 이유 — 최소 컨테이너 이미지에 그런 조회 라이브러리가 없으면 컴파일러가 빌드 기계마다 다른 언어를 받아들이게 된다. 닫힌 표(§Reference-level Specification/2)는 그 조회를 빌드 시점에 스냅샷으로 고정한다 |
| 5 | **통화 불일치를 컴파일 타임에 판정** | §Reference-level Specification/5가 적은 대로, 통화는 필드 선언이 아니라 행 데이터다. 정적 판정을 하려면 Money에 통화를 고정하는 refinement 표기가 필요한데, 그것은 RFC-0001 §Open Questions ⑤가 아직 답하지 않은 질문이다 — 이 RFC 하나로 그 표기 체계를 새로 여는 것은 범위를 넘는다 |
| 6 | **`avg`의 반올림도 절삭으로 통일**(Integer `/`와 대칭) | 금융 집계의 실무 관행과 어긋난다(§Reference-level Specification/4의 Modern Treasury·IEEE 754 인용) — 절삭은 체계적으로 값을 낮춰 평균이 편향된다. half-to-even은 동점을 짝수로 나눠 그 편향을 없앤다 |

## Open Questions

1. **Money를 가드·`set` 산술로 여는 것.** §Alternatives 1이 이월한 것 그대로.
   요구가 생기면 RFC-0016 §3의 차원 표를 갱신하는 후속 RFC가 필요하다 — 등가·
   순서·산술 결합 규칙을 각각 다시 정해야 한다.
2. **Money base의 refinement(통화 고정).** RFC-0001 §Open Questions ⑤가 이미
   미정으로 남긴 것과 같은 질문이다 — `Money currency USD` 같은 표기가 생기면
   §Reference-level Specification/5의 통화 불일치를 컴파일 타임으로 당길 수
   있다.
3. **Decimal 산술 일반.** RFC-0015 §Open Questions 4·RFC-0028 §Open Questions 2가
   이미 미룬 것 — 이 RFC는 Money(고정 소수 자릿수)만 풀었고, 임의 정밀도 Decimal
   필드의 산술은 여전히 정적 거부다.

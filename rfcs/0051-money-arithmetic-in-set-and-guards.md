# RFC-0051: `set`·가드의 Money 산술 — 같은 통화 부분집합

## Status

- Status: Draft
- Updates: RFC-0016 §Reference-level Specification/3. 피연산자의 차원 규칙,
  RFC-0038 §Reference-level Specification/3. 등가 비교의 타입 규칙,
  RFC-0015 §Reference-level Specification/3. 정적 거부,
  RFC-0044 §Reference-level Specification/5. 순서·산술의 통화 규칙,
  RFC-0016 §Reference-level Specification/5. mode A/B 등가,
  RFC-0028 §Reference-level Specification/6. Mode B

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목하고, 규칙 5(연쇄 갱신)에 따라 이미
갱신된 절은 대상과 **직전 갱신 RFC를 모두** 지목한다.

- **차원 규칙(RFC-0016 §3).** RFC-0038 §3이 이미 갱신한 절이다(RFC-0016 머리의
  `Updated-by: RFC-0038 (§Reference-level Specification/3)`). 그래서 RFC-0016 §3과
  RFC-0038 §3을 함께 지목하고, 아래 §1은 RFC-0038의 3.1까지 포함한 치환 후 최종
  텍스트다.
- **정적 거부(RFC-0015 §3).** RFC-0015 머리의 `Updated-by:`는 §1과 §4만 가리킨다 —
  §3은 이번이 첫 갱신이라 지목할 직전 갱신 RFC가 없다.
- **통화 규칙(RFC-0044 §5).** RFC-0044는 어떤 갱신도 받은 적이 없다. §5의 마지막
  문단("이 순서·산술 평가기를 실제로 부르는 자리는 이 RFC에 없다")이 이 RFC로
  거짓이 되므로 §5를 지목하고, 같은 RFC의 §Open Questions 1("Money를 가드·`set`
  산술로 여는 것")은 이 RFC가 답이다 — Open Questions는 계약 절이 아니므로
  지목하지 않고 포인터로 닫는다(§Open Questions 1).
- **등가 표(RFC-0016 §5)와 Mode B(RFC-0028 §6).** 모드 B가 Money 가드를 거부하는
  새 행과 문단이 들어간다. RFC-0016 §5는 첫 갱신이다. RFC-0028 §6은 Accepted
  갱신이 아직 없다 — RFC-0050(Draft)이 같은 절을 갱신하는 중이므로, 아래 §6의 최종
  텍스트는 RFC-0050 §5의 최종 텍스트 **위에** 이 RFC의 문단 하나를 더한 것이다.
  두 Draft 중 먼저 Accepted되는 쪽이 직전 갱신이 되고, 나중 쪽이 승격할 때 그
  사실을 `Updates:`에 반영한다.

지목하지 **않는** 것:

- RFC-0015 §4 / RFC-0028 §2(값 도메인과 실패 표). 새 실패 클래스가 없다 — 통화
  불일치는 RFC-0044 §5의 기존 `money-currency-mismatch` `RunError`, 범위 초과는
  기존 "value out of the 64-bit range" `RunError`다(§4). 비수치 값 비교의
  `RunError` 행도 그대로다.
- RFC-0044 §Guide-level Explanation의 "이 RFC가 열지 않는 것" 문단. RFC-0044
  시점의 상태를 설명하는 산문이고, 그 규범적 짝은 §5의 마지막 문단이다 — 그 문단을
  지목해 갱신한다. RFC-0044 §3(`MoneyLiteral`은 어떤 `Operand` 자리에도 나타나지
  않는다)은 이 RFC 뒤에도 참이다: 문법 델타가 없다(§Guide-level Explanation).
- RFC-0025 §3 / RFC-0045 §2(집계의 필드 타입 표). 집계는 이미 Money를 받는다.

이 RFC는 Draft다. RFC-0007 §2.2 규칙 6에 따라 Updates RFC는 Accepted가 되는 순간
효력이 생기므로, 대상 RFC의 `Updated-by:` 줄과 절 머리 포인터 줄은 **승격 시점에**
단다(RFC-0049·RFC-0050 선례와 같다).

번호가 0051인 이유: 0050까지 점유됐다(RFC-0050, 숫자 형태 가드 술어). RFC-0007
§3은 번호 재사용을 금지한다.

## Motivation

probe-v0.8의 세 케이스가 같은 벽에 부딪혔다(이슈 #172).

- **s1 F-1(blocker).** 주문 라인 금액 `set line.lineTotal to line.unitPrice * line.qty`
  (단가 Money × 수량 Integer)가 `declared type Money is neither Integer nor DateTime`
  으로 컴파일 거부됐다. 저자는 금액을 센트 정수 필드로 바꿔 우회했다.
- **s3 F-1(major).** 정산 리포트의 `set report.net to report.gross - report.fees`
  (Money − Money)는 물론, 연산자 없는 복사 `set report.net to input.net`까지 같은
  메시지로 거부됐다. 수수료·순액 계산 전체가 언어 밖(glue.py)으로 나갔다.
- **s2 F-1(blocker)**은 `Decimal × Decimal`(환율)이다 — 이 RFC의 범위 밖이다
  (§Reference-level Specification/7).

원인은 한 줄이다. RFC-0016 §3이 Money를 "어느 차원도 아니며 컴파일 거부"로 두었고,
RFC-0044가 Money 평가기(minor-unit 코덱, 같은 통화 순서·덧셈)를 만들었지만 그것을
부르는 자리는 집계(RFC-0045)뿐이었다. RFC-0044 §Open Questions 1이 바로 이 후속을
예고했다: "RFC-0016 §3의 차원 표를 갱신하는 후속 RFC가 필요하다 — 등가·순서·산술
결합 규칙을 각각 다시 정해야 한다."

Gate-1 판정(이슈 #172 조정)이 범위를 고정했다: **복사, Money ± Money,
Money × Integer, 가드·`set`의 Money 비교.** Decimal과 나눗셈은 거부로 남고, 모드 B는
진단과 함께 거부하며 차동 하네스는 그 예외를 기록한다. 이 RFC는 그 부분집합의
계약이다.

## Guide-level Explanation

이제 이렇게 쓸 수 있다:

```
set line.lineTotal to line.unitPrice * line.qty     # Money × Integer
set line.lineTotal to line.unitPrice * 3            # 리터럴도 된다
set report.net to report.gross - report.fees        # Money − Money
set report.total to report.net + report.tax         # Money + Money
set report.net to input.net                         # 복사
when order.total > order.creditLimit                # Money 대 Money 비교
```

`12.50 USD × 3`은 `37.50 USD`, `1.250 KWD + 0.750 KWD`는 `2.000 KWD`다. 계산은
통화의 minor 단위 정수(RFC-0044 §1)로 하므로 반올림이 일어나지 않는다 — 나눗셈이
없기 때문이다. 결과는 저장소에 기존 Money 와이어 모양
`{"amount": "37.50", "currency": "USD"}` 그대로 들어간다.

두 값의 통화가 다르면 어떻게 되나: `set`의 덧셈·뺄셈은 그 스텝을
`money-currency-mismatch`로 실패시키고(`status: failed`, rc=1), 가드의 순서 비교
(`<`/`<=`/`>`/`>=`)는 오늘의 다른 가드 값 오류(비수치 비교, 0 나눗셈)와 똑같이 실행
전체를 멈춘다(롤백, `lnpl run`은 `runtime error: ...`, rc=3). 통화는 필드
선언이 아니라 행 데이터라서 컴파일러는 미리 알 수 없다(RFC-0044 §5). 등가
(`==`/`!=`)는 실패하지 않는다 — 통화가 다른 두 금액은 그냥 같지 않다.

여전히 컴파일 거부인 것:

```
set a.x to a.price * a.cost        # Money × Money — 무슨 단위인가?
set a.x to a.price / 2             # 나눗셈 — 반올림 정책은 집계(avg)에만 있다
set a.x to a.price + 3             # Money ± 숫자 — 3 무슨 통화?
when a.price > 0                   # Money 대 숫자 — 같은 종류가 아니다
set a.stock to a.price             # Integer 필드에 Money를 넣는다
when a.price exists                # 존재 검사는 이 부분집합에 없다
set a.x to a.price * a.rate        # rate가 Decimal — Decimal은 여전히 평가기가 없다
```

리터럴 `3`은 `*` 옆에서만 허용된다 — 곱셈의 한쪽은 "몇 배"이고 통화가 필요 없지만,
덧셈의 `3`에는 통화가 없다. 가드에 `100USD` 같은 Money 리터럴을 쓰는 문법은
없다(RFC-0044 §3, 이 RFC는 문법 델타가 없다) — 다른 Money 참조나 `input.<필드>`와
비교한다.

모드 B(컴파일된 바이너리)는 Money 가드가 있는 워크플로의 빌드를 거부한다
(`lnpl diff`는 `backend error: ...`로 rc=4). Money `set`은 모드 B에 아무 변화도
요구하지 않는다 — 모드 B는 할당 표현식을 원래 계산하지 않는다(RFC-0028 §6).

## Reference-level Specification

### 1. 피연산자의 차원 규칙 — RFC-0016 §3 / RFC-0038 §3 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래 인용은 RFC-0016 §Reference-level Specification/3의
치환 후 최종 텍스트다(RFC-0038이 붙인 3.1 포함). 인용 안의 "RFC-0015"는 RFC-0015 §3을
가리킨다.

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
> 거부다(RFC-0015 §D6 유지, Decimal은 RFC-0044 §Open Questions 3).
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
> 이 좁힘은 **`list where`에만** 적용된다 — 가드 조건의 등가(`when status ==
> input.wantedStatus`)는 위 표(차원 규칙)로만 판정되고, Text 필드를 가드에서
> 비교하면 여전히 컴파일 거부다. `list where`는 `Condition` 문법을 재사용하지만,
> 그 판정 함수(`lower._check_list_predicate`)는 가드의 판정 함수
> (`lower._check_dimensions`)와 별개이므로 한쪽을 넓혀도 다른 쪽은 조용히 넓어지지
> 않는다.

거부 메시지는 모두 `RFC-0051`을 이름으로 댄다. `Money × Money`/나눗셈은 "multiplies
(divides) two Money values", 그 밖의 섞임은 "combines a Money value with a <차원>
value via '<op>'", 비교 불일치는 RFC-0016의 "compares like with like" 문장 끝에
"Money compares only to Money (RFC-0051)"를, `set` 불일치는 "assigns <값> (<차원>)
to <대상> (<차원>) — RFC-0051 requires the same dimension on both sides"를 낸다.
Decimal 등 차원 없는 타입의 거부는 기존 첫 구절("is neither Integer nor DateTime")을
글자 그대로 유지하고, 괄호 안에서 RFC-0051과 RFC-0044 §Open Questions 3을 댄다.

### 2. 정적 거부 — RFC-0015 §3 갱신 (치환 후 최종 텍스트)

> 문법이 받되 문서를 보면 거부되는 형태들이다. 전부 `lower`에서 판정한다 — 문서만으로
> 결정 가능한 것을 런타임까지 미루면 t2 F-4처럼 인터프리터 내부의 원시 예외가 조작자에게
> 샌다.
>
> | 거부 | 사유 |
> |------|------|
> | 양변이 모두 리터럴(`1 < 2`) | 아무것도 결정하지 않는 가드는 저작 오류다 |
> | 선언 타입이 어느 차원(RFC-0016 §3: Integer·DateTime·Money)도 아닌 피연산자 | 평가기가 없다. 실측: `payment.amount`(Money) 가드가 경고 없이 컴파일된 뒤 `TypeError: '<=' not supported between instances of 'dict' and 'int'`로 죽었다(t2 F-4). Money는 RFC-0051부터 차원이 있으므로 이 행이 아니라 차원 불일치 행으로 판정된다. Decimal은 여전히 이 행이다 |
> | 차원 규칙(RFC-0016 §3)이 거부하는 식·비교·할당 | 두 양이 같은 종류가 아니다 — 인스턴트와 숫자, Money와 숫자, Money와 Money의 곱·몫 |
> | 선언된 Money 필드에 `exists`/`missing` | RFC-0051이 여는 부분집합은 비교와 산술이다. 존재 검사는 열지 않는다(§Reference-level Specification/7) |
> | `input.<field>`의 `<field>`를 어떤 엔티티도 선언하지 않음 | payload는 선언된 전 엔티티 필드의 합집합이다. 그 밖의 이름은 오타다 |
> | 엔티티명 `Input` | 바인딩 이름이 `input` 네임스페이스와 충돌한다 |
> | 할당 대상이 `input.…` 또는 맨이름 | 입력은 이 워크플로가 소유한 상태가 아니다 |
> | 할당 대상 엔티티를 워크플로가 read하지 않음 | 바인딩이 존재할 수 없다(RFC-0012 §G12.5와 같은 사유) |
> | 앞선 스텝이 할당한 Reference를 뒤의 가드가 읽음 | 모드 B는 조건 필드를 진입 시 i64 파라미터로 고정 받는다. 그런 프로그램은 두 모드가 다른 값을 본다 |
> | `and` 안의 `exists`/`missing` | §1의 두 채널 사유 |

RFC-0050(Draft)의 숫자 형태 술어가 선언된 Money 필드에 걸리면 역시 거부다 — 그
술어의 판정 대상은 숫자 모양이지 금액이 아니다(§7).

### 3. 런타임 평가 — 모드 A (신설)

**형태 판별(shape dispatch).** `eval_value`는 참조의 원시 값이 `amount`와
`currency` 키를 가진 dict이면 그것을 `money.encode_money`로 `(minor, currency)` 쌍으로
바꾼다. 이 판별은 선언 타입이 아니라 **값의 모양**으로 한다 — 선언된 Money 필드와,
선언 타입이 없는 참조(`input.<field>`, 맨이름, 네트워크 결과)가 Money 모양 값을
실어 온 경우가 같은 경로를 탄다. RFC-0045의 집계(`_eval_sum_avg`)가 이미 세운 판별
방식 그대로다. 그 밖의 dict는 기존 "Cannot compare non-numeric" `RunError`로
떨어진다(RFC-0028 §2 불변).

**산술.** 쌍이 한쪽이라도 끼면:

| 식 | 평가 |
|----|------|
| 쌍 `+` 쌍 | `money.add` — 통화가 다르면 `money-currency-mismatch` |
| 쌍 `-` 쌍 | `money.sub` — 통화가 다르면 `money-currency-mismatch` |
| 쌍 `*` 정수, 정수 `*` 쌍 | `money.mul_int` |
| 그 밖(쌍 `*` 쌍, `/`의 어느 쪽이든 쌍, 쌍 ± 정수) | `RunError` — 두 모양을 이름으로 댄다 |

마지막 행은 선언 타입이 없는 참조만 도달한다 — 선언된 필드의 같은 식은 §1이 컴파일
시점에 거부한다. `money.sub`/`money.mul_int`는 자기 결과가 ±INT64를 벗어나면
`MoneyRangeError`(code `money-range`, 메시지 "value out of the 64-bit range: …")를
낸다. `money.py`는 여전히 다른 lnpl 모듈을 import하지 않는다.

**비교.** `==`/`!=`는 두 쌍의 구조적 비교다 — 통화가 다르면 같지 않다(`false`)이고
실패가 아니다(RFC-0044 §5). 순서 비교는 양쪽이 모두 쌍이어야 하며 `money.compare`로
판정한다 — 통화가 다르면 `money-currency-mismatch` `RunError`. 쌍 대 정수의 순서
비교는 `RunError`다(선언 타입이 없는 참조만 도달하는 차원 불일치). 가드 평가 기록
(`evaluations`, 스킵 레코드)의 `value`/`expected`에는 쌍이 아니라 와이어 모양
dict를 싣는다 — 저장 행과 같은 모양을 보여야 마스킹과 진단이 같은 값을 본다.

**할당.** 결과가 쌍이면 저장 전에 와이어 모양 `{"amount": <십진 문자열>, "currency":
<alpha-3>}`으로 되돌린다(RFC-0001 §Semantic Type 시스템). 복사(`set a.x to b.y`)는
원시 값을 그대로 옮기지 않고 같은 인코딩·디코딩을 거친다 — 정밀도가 통화 exponent와
어긋난 값은 `money-encode-precision`으로 실패한다.

**`expect result`의 Money 순서 비교.** spec의 `expect result <ref> <cmp>
<MoneyLiteral>`에서 순서 비교(`<`/`<=`/`>`/`>=`)를 연다 — 가드와 같은 `money.compare`
경로이고 같은 실패 규칙이다. 등가는 이전과 같다.

### 4. 실패 신호

새 결과 클래스를 만들지 않는다. 모든 새 실패는 RFC-0015 §4(RFC-0028 §2 갱신)의
기존 `RunError`다. 어디서 났느냐에 따라 **기존** 두 경로 중 하나를 탄다 — 이 RFC가
새 경로를 만들지 않는다:

| 실패가 난 자리 | 관측 |
|---------------|------|
| `set`(Assignment) 평가 | 그 스텝이 `failed`, `failed at: <스텝명>`, rc=1 |
| 가드(`when`/`until`/`or` 대안) 평가 | `RunError`가 실행 밖으로 나간다 — 트랜잭션 롤백(행 불변), `lnpl run`은 `runtime error: ...`, rc=3. 오늘의 비수치 가드 비교·가드 0 나눗셈과 같은 경로다 |

| 조건 | 메시지에 담기는 것 |
|------|-------------------|
| 서로 다른 통화의 덧셈·뺄셈·순서 비교 | `money-currency-mismatch` (RFC-0044 §5) |
| 결과가 ±INT64 밖 | `value out of the 64-bit range` (`money-range`) |
| 값의 소수 자릿수가 통화 exponent와 다름 | `money-encode-precision` (RFC-0044 §1) |
| 선언 타입 없는 참조의 허용되지 않는 Money 결합 | 두 피연산자의 모양 |

### 5. mode A/B 등가 — RFC-0016 §5 갱신 (치환 후 최종 텍스트)

> | 관측 클래스 | 판정 |
> |---|---|
> | 실행 순서 + i44 `skips` | **반드시 일치** — 시간 비교는 기존 i64 파라미터 채널을 탄다 |
> | 정책 결과(status/attempts) | **반드시 일치** |
> | 관측 신호(effects) | 불변 — 시간 문법은 새 effect를 만들지 않는다 |
> | 마스킹 | 불변(i43) |
> | 스케줄 트리거 | **비교 대상 아님** — 워크플로 스텝을 만들지 않아 두 모드 모두 관측할 것이 없다 |
> | Money 가드 | **비교 대상 아님** — 모드 B가 빌드를 거부한다(RFC-0051). 차동 하네스는 거짓 EQUIVALENT 대신 기록된 예외로 거부한다 |
> | Money `set` | 기존 행 그대로 — 할당이 만든 값은 허용된 차이다(RFC-0015 §5). EQUIVALENT는 "그 이름의 Assignment 효과가 있었다"만 뜻한다 |
> | 명령 선택(subi/cmpi 형태) | 허용된 차이 |
>
> 등가 주장의 범위: "시간 값이 두 모드에서 같은 i64로 인코딩되고, 같은 스텝 집합과 같은
> status를 낸다." **스케줄의 실제 발화는 어느 모드도 관측하지 않으므로 등가 주장에
> 포함하지 않는다.** Money 가드를 가진 워크플로는 등가 주장 밖이다 — 두 모드를
> 비교하지 않는다.

### 6. Mode B — RFC-0028 §6 갱신 (치환 후 최종 텍스트)

RFC-0050 §5가 제시한 RFC-0028 §6의 최종 텍스트(RFC-0028 원문 + "숫자 형태 술어"
문단)는 한 글자도 바뀌지 않고, 그 끝에 아래 문단 하나가 붙는다. 앞부분은 RFC-0050
§5를 그대로 참조하며 여기에 다시 싣지 않는다 — 같은 텍스트의 사본 둘이 발산하지
않도록.

> **Money (RFC-0051).** Money `set`은 모드 B에 아무 변화도 요구하지 않는다 — 위에
> 적은 대로 `Assignment.expression`은 `"lnpl.effect"` 마커 문자열 하나로만 방출되고
> 계산되지 않으므로, `set line.lineTotal to line.unitPrice * line.qty`의 모드 B
> EQUIVALENT는 여전히 그 Assignment 효과의 존재만 검증한다. 가드는 다르다:
> `condition_field_names`는 모든 가드 참조를 i64 파라미터로 승격하는데, Money는
> 통화를 행 데이터로 가지므로 i64 하나로 옮길 수 없다. 그래서 모드 B는 `when`/`until`
> 가드의 조건이나 어느 `or` 대안이든 **선언된 Money 필드**를 참조하면 그 워크플로의
> 빌드를 거부한다 — `BackendError`가 가드 텍스트를 이름으로 댄다: `guard '<text>'
> compares Money, which has no compiled evaluator (RFC-0051 §Mode B) — run it in mode
> A`. 선언된 Money 필드인지는 컴파일된 문서만으로 판정한다: 각 `Entity`의 기본 바인딩
> 이름과 `create ... as <name>` 별칭(`RepositoryCall.result`)으로 `<binding>.<field>`를
> 해석하고, `input.<field>`는 그 이름을 **문서 순서상 마지막으로 선언한** `Entity`의
> 필드로 해석한다(lowering의 `input.<field>` 표와 같은 규칙 — 두 판정이 어긋나지
> 않는다). refinement는 base로 푼다. `differential.verify`는 이 워크플로를 툴체인
> 확인보다 **먼저** 알아보고 `DifferentialError`(기록된 RFC-0051 예외)로 거부한다.
> 선언 타입이 없는 참조가 실행 시 Money 모양 값을 실어 오면, 차동 하네스는 그 값을
> i64 자리에 `0`으로 채워 넣지 않고 `DifferentialError`로 비교를 거부한다 — `0`으로
> 채우면 모드 A가 금액으로 평가한 가드를 모드 B가 0으로 평가해 거짓 판정을 낸다.
> Money를 쓰지 않는 워크플로의 MLIR은 바이트 단위로 그대로다.

### 7. Compatibility

- **기존 프로그램.** 바이트 동일 — 여섯 골든 쿼텟(`examples/{checkout,emitted,
  guarded,linkhub,login,shorten}.lir.json`)의 IR과 동작은 바뀌지 않는다. Money를
  `set`·가드에 쓰는 기존 예제가 없고, 새 거부(§1 마지막 행)에 걸리는 기존 `set`도
  없다.
- **문법 델타 없음.** 새 토큰·생산 규칙·어휘 키가 없다. `MoneyLiteral`은 여전히
  spec 전용이다(RFC-0044 §3).
- **Decimal.** 산술·비교 어디서도 여전히 거부다(RFC-0044 §Open Questions 3,
  RFC-0028 §Open Questions 2).
- **숫자 형태 술어(RFC-0050).** `is-numeric`/`is-not-numeric`은 Money에 적용되지
  않는다 — 선언된 Money 필드에 걸면 컴파일 거부다.
- **존재 검사.** 선언된 Money 필드의 `exists`/`missing`은 컴파일 거부로 남는다.
  Gate-1 부분집합은 비교와 산술만 연다(§Open Questions 3).
- **`list where` / `expose list ... by` / `order by`.** Money의 순서는 여전히 열리지
  않는다(§1의 3.1). Integer 필드 좌변에 Money 우변을 쓴 `list where`는 이전과 같이
  거부되지만, 메시지가 "no evaluator"에서 "compares like with like" 불일치로 바뀐다.
- **집계.** RFC-0045의 `sum`/`avg`/`min`/`max`는 그대로다.

### 8. 순서·산술의 통화 규칙 — RFC-0044 §5 갱신 (치환 후 최종 텍스트)

> Money 값 두 개를 **순서 비교**(`<`/`<=`/`>`/`>=`)하거나 **더하거나 빼는** 평가기는
> 양쪽의 통화 코드가 같을 때만 정의된다. RowSet의 각 행과 가드·`set`이 읽는 각
> 값은 저장소·입력 데이터이므로, 두 값의 `currency`가 같은지는 **런타임에만**
> 안다 — Money 필드는 통화를 타입 파라미터가 아니라 행 데이터로 갖는다(RFC-0001
> §Semantic Type 시스템, 이 RFC가 바꾸지 않는다). 컴파일 시점에 통화 일치를 검사하려면
> 필드 선언에 통화를 고정하는 새 refinement 표기가 필요한데, 그것은 RFC-0001 §Open
> Questions ⑤(복합류 base의 refinement — 내부 필드를 지목할 표기가 아직 없다)가 이미
> 미정으로 남긴 자리다. 이 RFC는 그 미정을 해소하지 않는다(§Alternatives 5) — 대신
> RFC-0028의 0 나눗셈과 같은 패턴을 따른다: **순서·산술 평가기가 실제로 서로 다른
> 통화의 두 값을 만나면** `RunError`(`money-currency-mismatch`)를 낸다(RFC-0015 §4의
> 기존 실패 클래스, 새 결과 클래스를 만들지 않는다). 집계와 `set`에서 나면 그 스텝이
> `status: failed`, `failed at: <스텝명>`, rc=1이고, 가드 비교에서 나면 다른 가드 값
> 오류와 같이 실행 밖으로 나가 롤백되고 `lnpl run`이 rc=3을 낸다(RFC-0051 §4). Integer 곱셈(`money × 정수`)에는 통화
> 질문이 없다.
>
> **등가(`==`/`!=`)는 이 규칙의 대상이 아니다** — §Guide-level Explanation이 이미
> 적은 대로, 등가는 구조적 비교이지 이 평가기를 거치지 않는다. 통화가 다른 두
> Money는 등가 비교에서 그냥 "같지 않다"(`false`)이지 실패가 아니다.
>
> **이 순서·산술 평가기를 부르는 자리는 셋이다**: RFC-0045의 `sum`/`avg`/`min`/`max`
> (Money 필드에 적용될 때), RFC-0051이 여는 가드 비교와 `set` 산술(RFC-0016 §3의
> `money` 차원), 그리고 spec의 `expect result` 순서 비교(RFC-0051 §3). 뺄셈과
> Integer 곱셈 평가기(`money.sub`/`money.mul_int`)는 RFC-0051이 더한 것이며, 자기
> 결과의 64비트 도메인을 스스로 검사한다.

## Examples

### 골든 시나리오 "Login" (RFC-0007 §6)

골든 시나리오는 Money를 쓰지 않는다. 이 RFC 뒤에도 `examples/login.lnpl`의 IR과
모드 B 출력은 바이트 단위로 같다.

### 골든 인접 예제 — s1 주문 라인과 s3 정산 (RFC-0007 §6, 골든이 다루지 않는 기능)

새 `examples/*.lnpl` 파일은 두지 않는다 — RFC-0028(단가 계산)·RFC-0044(Payment
시드) 선례처럼 산문과 테스트 픽스처로 보인다.

<!-- lnpl-check: skip — fragment: 조각: 엔티티·서비스 선언 없이 워크플로 본문만 보여줌 -->
```
workflow PriceLine
    read line
    set line.lineTotal to line.unitPrice * line.qty      # s1 F-1

workflow Settle
    read report
    when report.gross > report.threshold                 # Money 가드
    set report.net to report.gross - report.fees         # s3 F-1
    set report.carried to input.net                      # s3 F-1, 복사
```

| 입력 | 결과 |
|------|------|
| `unitPrice = 12.50 USD`, `qty = 3` | `lineTotal = {"amount": "37.50", "currency": "USD"}` |
| `unitPrice = 1000 JPY`, `qty = 3` | `lineTotal = {"amount": "3000", "currency": "JPY"}` (exponent 0) |
| `gross = 100.00 USD`, `fees = 30.25 USD` | `net = {"amount": "69.75", "currency": "USD"}` |
| `gross = 1.250 KWD`에 `0.750 KWD`를 더함 | `{"amount": "2.000", "currency": "KWD"}` (exponent 3) |
| `gross = 100.00 USD`, `threshold = 50.00 EUR` | 가드에서 `RunError`(`money-currency-mismatch`) — 롤백, `lnpl run` rc=3 |

정적 판정은 `impl/tests/test_value_semantics.py`의 `TestMoneyDimension`(허용 형태와
거부 형태 각각)과 `impl/tests/test_lower.py`의 `TestNumericPredicateRefusesMoney`·
`TestPresenceRefusesMoney`가, 코덱은 `impl/tests/test_money.py`의
`SameCurrencySubTest`·`MulIntTest`가 고정한다. 위 표의 런타임 값은
`impl/tests/test_value_semantics.py`의 `TestMoneyRuntime`(저장소에서 다시 읽어 단언)이,
`expect result`의 순서 비교는 `impl/tests/test_spec_money_literal.py`의
`TestExpectResultMoneyOrder`가, 모드 B 거부와 차동 예외는 `impl/tests/test_backend.py`의
`TestModeBRefusesAMoneyGuard`와 `impl/tests/test_differential_skips.py`의
`TestMoneyGuardExemption`이 고정한다.

### 컴파일 거부 — Money × Money

<!-- lnpl-check: skip — fragment: 조각: 워크플로 본문 한 줄 -->
```
    set line.lineTotal to line.unitPrice * line.discount
```

```
compile error: workflow PriceLine: 'set line.lineTotal to line.unitPrice * line.discount'
multiplies two Money values, which RFC-0051 does not evaluate (line.unitPrice * line.discount)
```

### 컴파일 거부 — Money 대 숫자

<!-- lnpl-check: skip — fragment: 조각: 워크플로 본문 한 줄 -->
```
    when report.net > 0
```

`report.net (money)`와 `a number literal (scalar)`의 차원 불일치 — "Money compares
only to Money (RFC-0051)".

## Alternatives

### 리터럴을 `+`/`-`에도 허용하는 안 (기각)

`price + 3`의 `3`은 통화가 없다 — 암묵적으로 왼쪽 통화를 빌려 오면 `3`이 달러인지
센트인지(minor 단위인지)가 모호해진다. `*`의 리터럴은 "몇 배"라 통화가 필요 없다.
그래서 리터럴은 `*` 옆에서만 받는다. Money 리터럴(`3.00USD`)을 가드·`set`에 여는
것은 문법 델타이고 이 RFC 범위 밖이다(§Open Questions 2).

### 모드 B 판정을 lowering 재실행으로 하는 안 (기각)

`backend.py`가 `lower`의 스코프 해석을 다시 부르면 선언 타입을 정확히 알 수 있지만,
백엔드는 컴파일된 IR만 본다 — 원시 AST에서 만드는 `_Scope`를 백엔드로 끌어오는 것은
계층 위반이다. IR이 이미 싣는 것(`Entity.fields`, `RepositoryCall.result`,
refinement base)으로 선언된 Money 필드 집합을 만들 수 있다.

### 모드 B에 Money 평가기를 넣는 안 (이번에는 기각)

minor 단위 i64와 통화를 두 파라미터로 넘기고 통화 일치를 바이너리가 검사하면 된다 —
하지만 통화는 타입 파라미터가 아니라 행 데이터라서(RFC-0044 §5, §Alternatives 5)
파라미터 채널 자체(RFC-0008 G8의 i64 하나)를 넓혀야 한다. §Open Questions 1.

### 차동 하네스가 Money 값을 0으로 채우고 계속 비교하는 안 (기각)

오늘의 자리표시자 `0`은 존재 검사·술어처럼 값을 읽지 않는 필드를 위한 것이다. Money는
모드 A가 실제로 평가하는 값이므로, `0`으로 채우면 두 모드가 다른 가드를 평가하고도
EQUIVALENT를 낼 수 있다. 거부가 거짓 판정보다 낫다(RFC-0050의 같은 판단).

### Decimal도 함께 여는 안 (기각)

Decimal은 고정 소수 자릿수가 없어 minor-unit i64 코덱에 들어가지 않는다 — 임의 정밀도
평가기를 두 런타임에 새로 들여야 한다(RFC-0044 §Alternatives 3). s2 F-1은 그대로
열린 질문이다.

## Open Questions

1. **모드 B의 Money 평가기.** i64 minor 단위 파라미터와 통화 검사를 컴파일된
   바이너리에 넣는 것. 통화가 행 데이터라서(RFC-0044 §5, §Alternatives 5) 파라미터
   채널 확장이 먼저다. 그 전까지 Money 가드는 모드 A 전용이다.
2. **가드의 Money 리터럴.** `when order.total > 100.00USD` — `MoneyLiteral`을
   `Operand`에 넣는 문법 델타(RFC-0044 §3 갱신)가 필요하다.
3. **Money 존재 검사.** `exists`/`missing`은 값을 평가하지 않으므로 모드 A에서는
   무해하지만 Gate-1 부분집합이 아니다. 요구가 생기면 모드 B 거부(§6)와 함께 연다.
4. **Decimal 산술.** RFC-0044 §Open Questions 3·RFC-0028 §Open Questions 2가 미룬
   그대로다. 이 RFC가 풀지 않는다.
5. **Accepted 승격.** 승격 시 RFC-0015/RFC-0016/RFC-0028/RFC-0038/RFC-0044에
   `Updated-by:`와 절 머리 포인터를 단다(§Status). RFC-0044 §Open Questions 1은 이
   RFC로 닫힌다.

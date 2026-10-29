# RFC-0069: Guard Conditions

## Status

- Status: **Accepted** (RFC-0069, 2026-10-28)
- Supersedes: RFC-0008

**통합 출처.** 갱신 RFC에서 온 텍스트와 그 출처는 다음과 같다(RFC-0007 §2.2 규칙 3·5, 연쇄를 끝까지 따른 최신 Accepted 텍스트).

| 절 | 효력 있는 텍스트의 출처 |
|----|------------------------|
| §Reference-level Specification/1. Full Grammar — 문법 블록 | `Guard`·`AltGuard`·`ArithOp`: RFC-0028 §1. `Condition`·`Term`·`Presence`·`NumericPred`: RFC-0050 §1. `Comparison`·`Comparator`·`Value`·`Operand`·`Reference`·`Namespace`·`Integer`: RFC-0015 §1. `Duration`: RFC-0016 §1. `AssignStep`·`Aggregate`: RFC-0025 §2. `AggFunc`: RFC-0047 §1(RFC-0045 §1을 거친 최종형) |
| §Reference-level Specification/1. Full Grammar — 기각된 형태 | 마지막 항목(3단 이상의 경로): RFC-0012 §RFC-0008 §Reference-level Specification / 1. Full Grammar |
| §Reference-level Specification/1. Full Grammar — 기각된 형태 뒤 문단 | 이 순서로: RFC-0015 §1(세 가지 제한, 리터럴, 정규화 — 둘째 제한 항목은 RFC-0050 §1), RFC-0016 §1(`h`·`d` 문단), RFC-0025 §2, RFC-0028 §1, RFC-0047 §1, RFC-0050 §1(구현 문단, `lnpl vocab` 문단) |
| §Reference-level Specification/2. Guard Runtime Semantics | 바탕은 RFC-0014 §2(상수 정의, 2.2·2.3 본문, 2.4의 `steps` 사유 문단과 status 어휘 문단, 2.5 첫 두 문단, 2.6 첫 문단과 마지막 두 문단). 2.1 본문: RFC-0060 §6. 2.4 머리 문장·표·결합 문단: RFC-0060 §7. 2.4 마지막 문단: RFC-0027 §6(후속 갱신이 말없이 뺀 요소, 유지). 2.5 마지막 문단: RFC-0022 §Reference-level Specification/표 1 — 관측 신호별 모드 대조. 2.6 둘째·셋째 문단: RFC-0028 §4. 2.4~2.6 제목: RFC-0014 §2 |
| §Examples/5.2 Guarded Workflow: guarded.lnpl | 코드 블록과 바로 뒤 문단: RFC-0046 §2. 절 끝의 기계 생성물 표·설계 제약 둘·`until` 제외 문단: RFC-0017 §Reference-level Specification |

표에 없는 절과, 표에 있는 절에서 출처를 적지 않은 텍스트는 RFC-0008 원문 그대로다.

## Motivation

이슈 #3 "[아직 열려있는 #3]"은 가드 조건식의 문법을 명확히 하고, 파서·평가기·컴파일러가 일관되게 조건을 다루도록 하기 위해 이 개정을 요구한다.

**수용 기준 (이슈 #3 원문):**
1. 파서가 평가기 없는 조건을 거부한다 — 런타임에 반드시 실패하는 `Guard`로 파싱되는 프로그램이 존재하지 않는다.
2. `when`과 `until`을 모두 쓰는 소스에 대해 `lnpl diff` → `EQUIVALENT`.
3. `until`이 모드 B에서 컴파일되고, 종료 한계가 현재의 2중 한계와 같은 정밀도로 서술된다.
4. `mutation_check.py`에 "조건 결과 반전"·"평가 불가 조건 수용" 추가 후 둘 다 RED.
5. 가드를 쓰는 골든 인접 예제로 differential이 가드 실행을 실제 커버한다.

**착수 전에 발견한 문제:**
- **발견 ①**: RFC-0003 §Guard의 "두 경계로 유계"(workflow 데드라인 + 라운드 상한)가 구현과 다르다. 명세는 "어느 쪽이든 먼저 닿으면 중단하고 WARN"이지만, 현재 구현은 `timeout` 미선언 시 1라운드 후 중단하고, `timeout` 선언 시 데드라인을 루프에서 보지 않는다.
- **발견 ②**: RFC-0002 §Condition의 `Word Word? Word? Word?` 대안이 평가기에서 구현되지 않았다. 이 생산 규칙을 따르는 프로그램은 런타임에 반드시 실패한다.

따라서 이 개정은 구현을 명세에 맞추고(§5 "구현과 명세가 어긋났을 때"), 동시에 조건식 문법을 닫힌 집합으로 제한하여 파서가 평가 불가 조건을 거부하게 한다.

## Guide-level Explanation

가드(guard)는 step이나 블록의 실행 여부·횟수를 제어한다. 조건식은 **존재 검사**와 **비교식** 두 형태만 사용할 수 있다.

**존재 검사:**
```
when tokenCache exists
  # 토큰 캐시가 있으면 실행
  
when tokenCache missing
  # 토큰 캐시가 없으면 실행
```

**비교식:**
```
when retryCount < 3
  # 재시도 횟수가 3 미만이면 실행
  
until retryBudget == 0
  # retryBudget이 0이 될 때까지 반복
```

`until` 반복은 **두 종료 조건**을 함께 감시한다:
1. workflow의 `timeout` 데드라인(선언된 경우)
2. 최대 16라운드

둘 중 먼저 닿는 경계에서 반복을 멈춘다.

## Reference-level Specification

### 1. Full Grammar (RFC-0002 §Full grammar/Condition 갱신)

RFC-0002의 `Condition` 정의를 다음과 같이 갱신한다:

**Old:**
```
Condition         ::= Comparison | Word Word? Word? Word?
```

**New:**
```
Guard        ::= 'when' Condition AltGuard* | 'until' Condition
AltGuard     ::= 'or' Condition
Condition    ::= Presence | Term ('and' Term)*
Term         ::= Comparison | NumericPred
Presence     ::= Reference ('exists' | 'missing')
NumericPred  ::= Reference ('is-numeric' | 'is-not-numeric')
Comparison   ::= Value Comparator Value
Comparator   ::= '<' | '<=' | '>' | '>=' | '==' | '!='

Value        ::= Operand (ArithOp Operand)?
Operand      ::= Reference | Integer | Duration
ArithOp      ::= '+' | '-' | '*' | '/'

Reference    ::= CamelName | Namespace '.' CamelName
Namespace    ::= 'input' | CamelName
Integer      ::= [0-9]+
Duration     ::= Integer ('ms' | 's' | 'm' | 'h' | 'd')

AssignStep    ::= 'set' Reference 'to' (Value | Aggregate)
Aggregate     ::= AggFunc Reference
AggFunc      ::= 'sum' | 'count' | 'avg' | 'min' | 'max'
```

**예약어 추가:** `exists`, `missing`을 예약어에 등록하여 필드명으로 사용 불가하게 한다.

**Comparator 집합** (RFC-0002 이미 정의):
- `<`, `<=`, `>`, `>=`, `==`, `!=`

**기각된 형태:**
- 1~4토큰 자유 구 (`Word Word? Word? Word?`)
- 논리 결합 (`and`, `or`, `not`) — 별도 계획 RFC-000X 대상
- 멤버십 연산
- **3단 이상의 경로**(`a.b.c`) — 바인딩은 행 하나이고 행의 필드는 스칼라다. 중첩 경로를
  받으려면 평가기가 중첩 구조를 순회해야 하는데, 참조 구현의 행은 평면 dict이므로 그 순회가
  평가할 대상이 없다. RFC-0008이 "평가기 없는 생산 규칙"을 제거한 것과 같은 판정이다.

세 가지 제한은 누락이 아니라 결정이다.

- **`or`·`not`·괄호 없음.** 이 RFC는 이슈 #47의 5개 요구를 덮는 최소 표면을 정의한다.
  생산규칙 하나를 더할 때마다 인터프리터와 방출된 MLIR **양쪽**에 같은 평가기를
  유지해야 한다. 표현력 확장은 다음 RFC의 몫이다(RFC-0008 §Alternatives가 세운 순서
  그대로: 검증 가능한 등가를 먼저 세우고 그 위에 쌓는다).
- **`and`는 비교식과 숫자 형태 술어만 잇는다.** 모드 B는 존재 여부를 실행당 boolean
  하나(`run_binary(skip=…)`)로 판정하고 비교는 i64 파라미터로 판정한다. 한 조건에 두
  채널이 섞이면 모드 B가 모드 A와 다른 스텝 집합을 낼 수 있다. 그래서 존재 검사는
  여전히 단독 가드로 쓴다. 숫자 형태 술어에는 이 우려가 없다 — 모드 B에 그 술어의
  채널이 아예 없고, 술어를 쓴 워크플로는 모드 B가 빌드를 거부한다(§4). 섞일 두
  번째 컴파일 채널이 없다.
- **산술은 중첩하지 않는다.** `a - b - c`는 우선순위 규칙을 요구하고, 우선순위 규칙은
  저자가 조용히 틀릴 수 있는 종류의 것이다. 곱셈·나눗셈은 없다(§Alternatives).

**리터럴은 부호가 없다.** 계산 **결과**는 음수일 수 있다. 모드 B가 상수를
`%c<value>_i64`라는 SSA 이름으로 선언하므로 `%c-3_i64`는 유효한 이름이 아니다.

**정규화.** 항은 소스 순서대로 ` and `로 잇고, 비교는 `<left> <op> <right>`, 산술은
`<a> <op> <b>`, 공백은 정확히 1칸이다. Duration은 최적 단위로 되돌린다(`60000` → `1m`).
이 문자열이 IR에 실리고, 두 모드가 그것을 비교하며, RFC-0071의 skip 레코드가 그것을
싣는다.

`h` = 3600000 ms, `d` = 86400000 ms. 주(`w`)·월·년은 넣지 않는다: 월과 년은 길이가
가변이라 정수 상수로 정의할 수 없다.

`Value`와 `Aggregate`는 **결합하지 않는 별개 생산 규칙**이다 — 기존 `Value`(산술)를
넓혀 집계를 흡수하면 `sum x + 1`이 파싱되게 되는데, 이는 Guide-level Explanation이
명시적으로 금지한 형태다. `AssignStep`이 두 우변 중 하나를 택일해 받는 것으로,
표현력의 결합 없이 집계라는 세 번째 값 출처를 더한다.

`Reference`는 RFC-0072 §1이 정의한 그대로다(`CamelName | Namespace '.' CamelName`).
`count link`의 `Reference`는 한 조각(RowSet 바인딩 이름), `sum link.clicks`의
`Reference`는 두 조각(RowSet 바인딩 이름 + 필드)이다. 파서 층위에서 `Aggregate`와
`Value`는 첫 토큰(`sum`/`count` 대 그 밖)으로 구별되며, 렉서·`given`/`expect`
phrase 라인의 토큰화(`Line.tokens = body.split()`)는 바뀌지 않는다.

**정규화.** `Assignment.expression`(RFC-0072 §2)에 싣는 문자열은 `<func> <ref>`,
공백 1칸 — `"sum link.clicks"`, `"count link"`. `Assignment` 노드의 다른 필드
(`kind`/`id`/`target`/`entity`)와 스키마(`schemas/lir.schema.json`의
`nodeAssignment`)는 바뀌지 않는다: `expression`은 이미 자유 문자열이고
(`"type": "string"`, 패턴 제약 없음), 정규화된 새 형태를 싣는 데 스키마 변경이
필요 없다.

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

`count link`·`sum link.clicks`처럼
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

구현: `impl/lnpl/lexer.py`의 `NUMERIC_PREDICATE_KINDS = ("is-numeric",
"is-not-numeric")`와(같은 파일로 옮긴 `PRESENCE_KINDS = ("exists", "missing")`),
`impl/lnpl/condition.py`의 `NumericPredicate(field, kind)` 노드. 두 낱말은
참조 이름이 될 수 없다(`and`/`to`/`exists`/`missing`과 같은 예약). 정규화 문자열은
`<field> <kind>`이고, `and` 항 안에서도 소스 순서 그대로 ` and `로 이어진다 — IR의
`Guard.condition`은 여전히 문자열 하나다(RFC-0015 §2 불변, 스키마 변경 없음).

`lnpl vocab`(및 MCP `lnpl_vocabulary`)의 `keywords`는 `presence_kinds`와
`numeric_predicate_kinds`를 싣는다.

### 2. Guard Runtime Semantics (RFC-0003 §Guard 갱신)

**상수 정의:**
```
_UNTIL_ROUND_CAP = 16
```

이 상수는 모드 A(런타임 평가) 및 모드 B(컴파일)가 모두 따라야 하는 계약값이다.

#### 2.1 `when` 모드

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

**`otherwise` 항목이 있으면**(RFC-0060), 판정은 위와 같고 그 결과로 두 항목 중 정확히
하나가 실행된다. 전부 거짓이면 피가드 항목의 스킵 레코드를 남긴 **뒤** `otherwise`
항목을 실행한다. 하나라도 참이면 피가드 항목을 실행한 **뒤** `otherwise` 항목에 대한
`mode: "otherwise"` 스킵 레코드 하나를 남긴다. 조건은 어느 쪽이든 한 번만 판정한다 —
`otherwise`는 조건을 다시 평가하지 않는다. 가드가 읽는 참조는 그 가드에 도달한 시점의
값이다 — 앞선 스텝이 `set`/`format`으로 바꾼 필드면 바뀐 값을 읽는다(RFC-0060 §1).

#### 2.2 `until` 모드 (명세 정정)

조건이 참이 될 때까지 피가드 항목을 반복한다. 반복은 **두 경계에 의해 유계**된다:

1. **시간 경계**: 매 라운드 시작 전 `clock.now >= deadline`이면 중단 (workflow의
   `timeout`이 선언된 경우)
2. **라운드 경계**: `rounds >= _UNTIL_ROUND_CAP`이면 중단

`timeout` 미선언 시에도 라운드 상한은 그대로 `_UNTIL_ROUND_CAP`이다. 중단 사유를
구분하여 WARN에 남긴다:
- `reason="deadline"` — 시간 경계 도달
- `reason="round_cap"` — 라운드 상한 도달

**첫 평가가 이미 참이어서 한 라운드도 실행하지 않은 경우**(`rounds == 0`),
`when`의 거짓 분기와 **동형으로** trace에 기록하고 §2.4의 스킵 레코드 하나를
남긴다. 라운드가 1회 이상 실행된 경우에는 아무 레코드도 남기지 않는다 — 그 경우
건너뛴 것이 없기 때문이다. 이 대칭은 규범이다: 두 경로 모두 "선언된 스텝이
실행되지 않았다"는 같은 사실이므로, 하나만 관측 가능한 상태는 관측 불가능한
분기를 만든다.

#### 2.3 실행 의미 표

| mode | 종료 보장 | 설명 |
|------|----------|------|
| `when` | 자명 | 조건 1회 평가 후 분기(반복 없음) |
| `repeat` | 자명 | 선언된 `count` 횟수 반복(유한 상수) |
| `until` | 두 경계로 유계 | 조건 성립 또는 `timeout`/`_UNTIL_ROUND_CAP` 도달 시 중단 |

#### 2.4 스킵 레코드 (신설)

실행 결과는 **스킵 매니페스트**를 가진다. 피가드 항목을 실행하지 않은 가드마다, 그리고
가드가 참이어서 실행하지 않은 `otherwise` 항목마다(RFC-0060) 레코드가 하나씩, 만난
순서대로 들어간다.

| 필드 | 의미 |
|------|------|
| `guard` | 가드 노드의 IR id. 모드 A 전용 — 모드 간 비교에서 제외한다 |
| `mode` | `"when"` 또는 `"until"`. **갱신 (RFC-0060)**: `otherwise` 항목의 레코드는 `"otherwise"` |
| `condition` | **갱신**: 대안이 없으면 정규화된 조건 문자열 그대로(RFC-0008 §4 불변). 대안이 있으면 조건과 모든 대안을 소스 순서대로 `" or "`로 이어붙인 문자열 — `"input.channel == 1 or input.amount <= 100"`. 이 결합은 **표시/비교 전용**이며 `parse_condition`으로 재파싱되지 않는다(§Reference-level Specification/3). `mode: "otherwise"` 레코드에서는 **참이었던** 그 가드의 같은 문자열이다(RFC-0060) |
| `steps` | 그 레코드가 가리키는 항목(피가드 항목, 또는 `otherwise` 항목)이 감싼 **모든 WorkflowStep의 이름**, 선언 순서. 중첩 블록(`Concurrency`·`Pipeline`)까지 하강해 수집한다. 피가드 항목의 레코드는 `otherwise` 항목의 스텝을 담지 않는다(RFC-0060) |
| `rounds` | `when`·`otherwise`면 없음(`null`), `until` 0라운드면 `0` |
| `evaluations` | (issue #83, RFC-0014 원문 불변 필드) **갱신**: 대안이 있으면 조건 자신의 항들에 이어 각 대안의 항들도 소스 순서대로 같은 리스트에 담는다 — 어느 항이 어느 대안 소속인지는 이 리스트의 위치가 아니라 `ref`가 가리키는 값으로 읽는다(추가 태깅 없음, RFC-0014가 이미 "다섯 키는 불변"이라 적은 원칙을 존중해 `evaluations`의 원소 shape을 넓히지 않는다). **갱신 (RFC-0050)**: 숫자 형태 술어 항도 한 원소를 남긴다 — 존재 검사와 같은 모양으로 `{"ref": <필드>, "value": <해소한 값, 없으면 null>, "op": "is-numeric" 또는 "is-not-numeric", "expected": null, "holds": <판정>}`. `and` 안의 술어 항은 다른 항과 함께 소스 순서대로 담긴다. **갱신 (RFC-0060)**: `mode: "otherwise"` 레코드에서는 빈 배열이다 — 가드는 참이었고, 참인 판정의 항은 이 채널이 아니라 트레이스(§2.1)가 싣는다 |

`condition`의 결합 표기는 `restore_skips`(모드 B 재구성)와 `_skip_record`(모드
A 실측)가 **같은 함수**로 만든다 — 이름은 §Reference-level Specification/5가
고정한다. 두 모드가 각자 결합하면 공백 하나의 실수가 `differential.verify`를
거짓 양성/거짓 음성으로 만든다.

`steps`가 이름이고 id가 아닌 이유는 규범적이다. 모드 B의 관측 표면에는 IR 노드
id가 없으므로(`step <index> <name>` 라인만 존재), 노드 id로 키잉된 매니페스트는
모드 B가 **원리적으로 생산할 수 없다**. 두 모드가 같은 신호를 관측해야 한다는
RFC-0004의 요구가 shape을 결정한다.

**status 어휘는 변경되지 않는다.** terminal status는 `completed`와 `failed`
둘뿐이며, 스킵은 status와 직교하는 신호다. 특히 스킵은 검증 실패·저장소 실패와
**다른 결과 클래스**다 — 후자는 `failed`이고 `failed_at`을 가진다.

네트워크 결과 바인딩 필드(`paymentResult.status`, `paymentResult.<bodyKey>`,
§3의 평탄화된 값)는 가드 평가 트레이스(`evaluations`)에서 **마스킹되지
않는다** — 바디 필드에 토큰이나 카드번호 같은 sensitive 값이 담겨도 그대로
trace에 남는다는 뜻이다.

#### 2.5 진단과 종료 코드 (신설)

스킵 레코드마다 진단 하나를 낸다: 코드 `guard-skipped-steps`, severity
`warning`. 진단은 기존 진단 채널을 그대로 쓴다 — 새 레코드 타입·누산기·포매터를
만들지 않는다.

기본 실행의 종료 코드는 바뀌지 않는다(스킵이 있어도 `completed`는 rc 0). 엄격도는
호출자가 고른다: `--strict`를 준 실행에서만 진단을 보고한 클린 종료가 rc 2로
승격된다. 이는 기존 `--strict` 게이트의 재사용이며 새 종료 코드 규약이 아니다.

`스킵 진단`의 그레인 차이는 **의도된 것이다.** mode A는 어떤 가드가 어떤 스텝들을
소유하는지 알고 있어 가드당 한 건을 낸다. mode B의 관측 표면에는 가드가 없고 계획된
스텝만 있으므로, 가드 단위로 묶으면 갖고 있지 않은 정보를 발명하게 된다. 같은
이유로 mode B 진단의 `where`는 가드 노드 id가 아니라 **워크플로 id**다 — 그것이 mode
B가 정직하게 지목할 수 있는 가장 세밀한 노드 id다.

#### 2.6 모드 A/B 동등성 (신설)

두 모드는 스킵을 **같게** 관측해야 한다. 비교는 `guard`를 제외하고 스텝 단위로
편 투영 위에서 이루어진다 — `{mode, condition, step, rounds}`. 모드 A는 레코드
하나를 그 `steps` 수만큼의 항목으로 펴고, 모드 B는 "계획에 있으나 출력에 없는
스텝"으로 같은 항목을 복원한다.

`condition`이 대안을 포함한 결합
문자열일 때도 이 넷은 그대로 비교 대상이다 — §2.4가 두 모드에게 같은 결합
규칙을 강제하므로 새 비교 클래스나 새 필드가 필요 없다.

모드 B에서 대안 가드는 `arith.ori`로 각 대안의 `arith.cmpi` 결과를 접어
하나의 i1로 만든다(§Reference-level Specification/6). `until`은 대안 가드를
가질 수 없으므로(§Reference-level Specification/1), 이 접기는 `negate`
경로와 만나지 않는다 — RFC-0014 원문의 드모르간 우려(`and`의 `until` 부정)는
대안 가드에는 적용되지 않는다.

모드 B에서 `until`은 라운드 상한까지 언롤되지만, 조건은 실행 중 상수이므로 라운드
수는 0 아니면 상한이다. 따라서 **라운드 1의 부재만** 0라운드 스킵으로 센다.
라운드 2 이상의 부재는 정상 종료이며 항목을 만들지 않는다.

이 비교는 RFC-0069 §5가 이미 규정한 대로 RFC-0004의 **실행 순서 분류(1/4) 안에서**
수행한다. 새 비교 클래스를 만들지 않는다.

### 3. Mode B Lowering (컴파일)

#### 3.1 Payload 전달

컴파일러는 조건이 참조하는 필드를 수집하여 `lnpl_run`의 추가 i64 파라미터로 변환한다. `main`이 `argv`에서 이 값들을 읽어 넘긴다.

**인코딩:**
- 존재 검사: 0(missing) 또는 1(exists)
- 비교식(정수): 정수값
- 비교식(Duration): 밀리초 단위 정수

**파라미터 순서:** 조건이 참조하는 필드의 **정렬된 이름 순**

예: 조건이 `retryCount < 3 && timeout > 5000`을 참조하면, `lnpl_run(..., i64 %retryCount, i64 %timeout)`

#### 3.2 `when` 컴파일

조건을 `arith.cmpi`로 컴파일하고, `scf.if` 분기로 피가드 항목을 감싼다.

**MLIR 의사 코드:**
```mlir
%cond = arith.cmpi <pred>, %field, %const : i64
scf.if %cond {
  // 피가드 항목
}
```

기존 `%skip` 파라미터는 **제거**한다(조건이 컴파일되므로 불필요).

#### 3.3 `until` 컴파일

`scf.while`로 컴파일하며, before 영역에 조건의 **부정** 및 라운드 카운터, after 영역에 피가드 항목과 카운터 증가를 담는다.

**MLIR 의사 코드:**
```mlir
%c0 = arith.constant 0 : i64
%c16 = arith.constant 16 : i64
%init = arith.constant 0 : i64
%final = scf.while (%rounds = %init) -> (i64) {
  // before: 조건 부정 & 라운드 카운터
  %cond = arith.cmpi <negated_pred>, %field, %const : i64
  %cap_ok = arith.cmpi ult, %rounds, %c16 : i64
  %continue = arith.andi %cond, %cap_ok : i1
  scf.condition(%continue) %rounds : i64
} do {
  ^bb(%rounds : i64):
  // after: 피가드 항목 + 카운터 증가
  ... // 피가드 항목
  %next = arith.addi %rounds, %c1 : i64
  scf.yield %next : i64
}
```

**데드라인 비대칭:** 모드 B에는 시계가 없으므로 시간 경계는 **유효하지 않다**. 오직 라운드 상한만 구현 가능하다. 이 비대칭은 모드 A와 B가 동일한 결과를 산출하기 위한 필요 조치다 — `until` 반복이 조건이 성립할 때까지 반복되며, 라운드 상한이 없으면 컴파일된 루프는 종료를 보장받지 못한다.

### 4. IR Representation

IR의 `Guard` 노드 필드 `condition`은 **정규화된 문자열**로 저장된다:
```
"<field> <comparator> <value>"  // 비교식
"<field> <exists|missing>"       // 존재 검사
```

**SSOT 함수:** `impl/lnpl/condition.py`의 `parse_condition(text: str) -> Condition` 한 함수만이 이 문자열을 해석하는 유일한 지점이다. 파서, 모드 A 평가기, 모드 B 컴파일러가 모두 이 함수를 호출하여 조건을 해석한다.

이를 통해 조건 해석이 여러 게이트에서 갈라지는 위험을 방지한다.

### 5. Differential Equivalence

RFC-0004의 differential 등가 판정에 다음 항목을 실행 순서 분류에 추가한다:

- **`until` 라운드 수:** 모드 A와 B의 반복 횟수가 같은가
- **skip 집합:** 모드 A와 B의 건너뜬 step 집합이 같은가

기존 4분류(실행 순서, 정책 결과, 관측 신호, 마스킹)는 유지하고, 새 항목을 실행 순서 내에 포함시킨다.

## Examples

### 5.1 Golden Scenario: Login

기존 `examples/login.lnpl` 시나리오는 **변경 없이 유지**된다. 이 RFC의 예제가 아니다.

### 5.2 Guarded Workflow: guarded.lnpl

조건식 두 형태를 실증하는 새 시나리오. `examples/guarded.lnpl`:

```lnpl
capability postgres
capability redis

entity Token
    field
        id UUID
        cachedAt DateTime
        retryBudget Integer

service TokenService
    policy
        retry 3
    performance
        cache 5m

workflow RetrieveWithCache
    validate token
    find token
    when token.cachedAt exists
    cache token
    when token.retryBudget > 0
    call token
    spec
        given
            valid token
        when
            retrieveWithCache
        expect
            completed
            effects complete
```

가드는 바로 다음 항목 하나만 소유한다(`references/grammar.md` §가드의
스코프) — `cache token`은 존재 검사(`when token.cachedAt exists`) 아래에,
`call token`은 비교식(`when token.retryBudget > 0`) 아래에 있고, 앞의
`validate token`·`find token`은 조건과 무관하게 늘 실행된다.

이 예제는:
- `when tokenCache missing` — 존재 검사 형태
- `until retryBudget == 0` — 비교식 형태

두 조건을 각각 실증하며, 수용 기준 ②(both `when` and `until`)을 만족한다.

**기계 생성물:** `examples/guarded.lir.json`은 위 소스를 파싱한 IR 표현이다(RFC-0066 노드 카탈로그, Guard 노드 참조).

**기계 생성물.** §5.2가 약속한 `examples/guarded.lir.json`에 더해, 다른 예제와
같은 4종 묶음을 커밋한다. 셋 다 컴파일러가 만든다.

| 파일 | 생성 명령 |
|------|-----------|
| `examples/guarded.lir.json` | `lnpl compile examples/guarded.lnpl -o examples/guarded.lir.json` |
| `examples/guarded.openapi.json` | `lnpl openapi examples/guarded.lnpl -o examples/guarded.openapi.json` |
| `examples/guarded.spec.json` | `lnpl spec examples/guarded.lnpl -o examples/guarded.spec.json` |

노드 id 안정성과 산출물 신선도는 이 문서가 아니라
`impl/tests/test_golden.py`(`TestGuardedGoldenPair`·`TestGuardedGeneratedArtifacts`)가
고정한다. 이 RFC가 계약하는 것은 **파일의 존재와 두 가드 형태의 실증**이다.

**설계 제약 둘.** 예제는 아래를 지킨다.

1. **가드 아래에 저장소 호출을 두지 않는다.** 모드 B는 실제로 참인 가드 아래의
   저장소 호출 실패를 재현하지 못한다(`impl/lnpl/backend.py`의 KNOWN LIMITATION).
   `impl/tests/test_backend.py`가 모든 예제를 전수 검사하므로, 이를 어기면 스위트가
   붉어진다.
2. **스텝 이름은 워크플로 안에서 유일하고, 같은 스텝이 반복되지 않는다.** 차등
   검사의 관측 맵은 스텝 **이름**으로 키를 잡는데, 두 모드가 그것을 다르게 접는다:
   모드 A는 dict comprehension이라 마지막 하나만 남기고
   (`impl/lnpl/differential.py`의 `observe_mode_a`), 모드 B는
   `setdefault(...).append(...)`로 전부 누적한다(`observe_mode_b`). 같은 이름이
   N번 나오면 두 모드가 **같은 일을 해도** 맵이 달라져 DIVERGENT가 난다.

**`until`을 싣지 않는 이유.** RFC-0069 §5.2의 수용 기준 ②는 `when`과 `until`
둘 다를 명시하지만, 이 예제는 `when` 두 형태만 싣는다. `until`은 피가드 스텝을
여러 라운드 반복하므로 **위 제약 2에 정면으로 걸린다** — 같은 스텝 이름이 N번
나오고, 그래서 두 모드가 동일하게 N라운드를 돌아도 `lnpl diff`가 DIVERGENT를 낸다.
발산의 원인은 `until`의 실행 의미가 아니라 차등 **관측기**의 비대칭이다.

기존 `impl/tests/test_until_mode_equivalence.py`는 유효하다. 그 픽스처는
`observe_*`의 effects 맵이 아니라 라운드 수를 직접 비교하므로 이 비대칭을 타지
않는다.

공식 예제가 DIVERGENT를 내는 것을 받아들이지 않으므로 `until`은 제외한다.
**이 관측기 비대칭의 수리는 이 RFC의 범위가 아니다** — 별도 추적 이슈로 올린다.
재현 증적은 `.orchestration/verify/i50-docs.md`에 있다. 수리된 뒤 `until` 예제를
더하는 것은 이 문서를 Updates하는 후속 RFC의 일이다.

## Alternatives

### 논리 결합(and/or/not)을 이번 개정에 넣지 않는 이유

모드 B가 조건을 실제로 평가·컴파일하려면, 표현력이 높아질수록 네이티브 평가 경로도 복잡해진다. 2형태(존재 검사, 비교식)로 `lnpl diff`의 EQUIVALENT를 먼저 세운 후, 그 기반 위에서 표현력 확장을 진행하는 것이 검증 가능한 순서다.

논리 결합은 별도 RFC(미정)로 미룬다.

## Open Questions

1. **절 이름의 안정성**: 이 RFC가 RFC-0002의 `§Full grammar`를 인용하는데, 섹션 이름이 바뀌면 포인터가 끊긴다. 절 이름이 안정 식별자가 되는 규칙이 필요하다(RFC-0007 §10 OQ 3번 참조).

2. **IR 구조화에 대한 긴장**: Guard.condition을 구조화된 객체가 아니라 정규화된 문자열로 유지하므로, SSOT 함수 1개에 의존한다. 이는 "IR이 허브"라는 CHARTER의 주장과 긴장이 있다. IR을 구조화하려면 RFC-0001(노드 카탈로그)까지 대체 대상이 되어 범위가 커진다. 이 설계의 정당성을 추후 재검토할 여지가 있다.

3. **논리 결합의 표현력**: Presence와 Comparison만으로는 복잡한 조건을 표현할 수 없다(e.g., "A와 B 중 하나가 참" 또는 "A가 참이 아님"). 이 제약이 실제 프로그래밍에서 불편을 초래하는지, 언제 확장해야 하는지는 실제 사용 경험에서 결정한다.

4. **Mode B에서 시간 경계 미지원**: 모드 B의 `until` 루프는 라운드 상한만 구현할 수 있다. 향후 컴파일러가 시계를 가질 수 있는 경로가 있는가?

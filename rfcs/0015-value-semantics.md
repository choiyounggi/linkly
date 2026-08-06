# RFC-0015: 값 의미론

## Status

- Status: **Accepted** (RFC-0015, 2026-08-06)
- Updates: RFC-0001 §Appendix A/A.4 Node catalogue(`Assignment` 1종 추가), RFC-0002 §Full grammar(`Condition`/`Value`/`AssignStep`), RFC-0008 §Reference-level Specification/1. Full Grammar

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목한다. 가드 조건의 문법은 RFC-0002
§Full grammar에 있었으나 RFC-0008 §1이 그 절을 이미 갱신했으므로 **효력 있는 계약은
RFC-0008 §1**이고, 이 문서는 그 절과 RFC-0002의 `Value`·`AssignStep` 생산규칙,
그리고 RFC-0001의 노드 카탈로그를 갱신한다. 세 문서 어느 본문과도 모순하지
않는다 — 이 개정은 표현력을 **추가**할 뿐 기존 형태의 의미를 바꾸지 않는다(규칙 2).
`when`/`until`의 실행 의미(RFC-0008 §2, RFC-0014가 갱신)와 skip의 관측 계약
(RFC-0014)은 지목하지 않는다. 새 비교식 가드는 그 계약을 **그대로** 탄다.

번호가 0015인 이유: 0013은 `main`의 RFC-0013(Step Attempt Ceiling), 0014는
RFC-0014(가드 스킵의 관측 가능성)가 점유했다. RFC-0007 §3은 번호 재사용을 금지한다.

## Motivation

2026-08-05 프로덕션 준비도 실측(`qa/REPORT.md`)은 네 케이스 전부에서 같은 공백을
보고했다. 언어에 **값이 없다**. 선언과 효과는 표현되는데, 그 효과가 다루는 수를
비교하거나 계산하거나 기록할 방법이 없다.

**증상 ① — 가드 우변이 리터럴뿐이다(t1 F-1, blocker).**
`when product.stock >= order.quantity`는 `invalid value 'order.quantity'`로 거부됐다.
저자는 `> 0`으로 후퇴할 수밖에 없었고, 그 결과 재고 1에 수량 2인 주문(S2)이
**completed로 완주하며 주문을 생성**했다. 초과 판매를 언어가 막지 못한다.

**증상 ② — 산술도 할당도 없다(t1 F-2, blocker).**
`update product`는 `operation=update`인 RepositoryCall 하나를 낳을 뿐이고, 차감량
`stock - quantity`를 적을 문법이 없다. "재고 5→3"은 어떤 채널로도 관측되지 않는다.
공식 예제 `checkout.lnpl`조차 `total` 필드를 "서술(계산 안 됨)"이라고 자인한다.

**증상 ③ — 가드는 읽은 행만 본다(t2 F-1).**
`workflow Approval / when payment.amount > 0`은 "이 워크플로가 payment를 읽지 않으므로
바인딩이 존재할 수 없다"는 (정확한) 진단으로 거부된다. 그런데 승인 워크플로가
검증하려던 것은 저장된 행이 아니라 **자기 입력**이었다. 우회는 워크플로를 입력 검증이
아닌 "기존 행의 갱신"으로 다시 쓰는 것뿐이었다.

**증상 ④ — 결합과 등가가 없다(t2 F-3, t4 F-7).**
`0 < 금액 ≤ 한도`는 상한 하나로 축소됐고, 전액 환불(`==`)과 부분 환불(`<`)을 구별할 수
없었다. 연쇄 `when`은 첫 가드가 조용히 탈락하던 결함(t2 F-2, 이슈 #45가 거부로 닫음)
이라 대안이 아니었다. 게다가 RFC-0008 §1이 약속한 `==`/`!=`가 **생성된
`grammar.md`에 없어서**, 저자는 RFC와 참조 중 어느 쪽이 구현인지 소스만으로 알 수
없었다(t4 F-7).

**증상 ⑤ — 집계가 없다(t3 F-1, blocker).**
`VERB_LEXICON` 16개가 전부 I/O 계열이고 `sum`/`count`는 어휘에도 문법에도 없다.
일 3건(100/250/50)에서 `count=3`·`sum=400`인 리포트를 만들 수 없다.

다섯 증상의 뿌리는 하나다. 이 RFC는 그중 ①~④를 문법으로 닫고, ⑤에 대해서는
**도입하지 않는다는 결정과 그 근거**를 기록한다(§Alternatives).

## Guide-level Explanation

저자가 새로 쓸 수 있게 되는 것은 다섯 가지다.

**1. 비교의 오른쪽에 필드를 쓴다.**

```
workflow PlaceOrder
    read product
    when product.stock >= input.quantity
    create order
```

**2. 입력 payload를 `input.`으로 지목한다.** 읽은 행이 없어도 된다.

```
workflow Approve
    when input.amount > 0 and input.amount <= 10000
    create payment
```

맨이름(`amount`)도 여전히 입력 payload를 가리킨다(RFC-0012 §G12.1). `input.`은 그
**명시 철자**이고, 선언되지 않은 필드명을 쓰면 컴파일이 거부한다 — 맨이름은 그
검사를 받지 않으므로 새 코드에서는 `input.`을 쓴다.

**3. 항을 `and`로 잇는다.** `or`·`not`·괄호는 없다. 존재 검사(`exists`/`missing`)는
단독 조건으로만 쓴다(§Reference-level Specification/1의 사유).

**4. 값을 계산해서 필드에 넣는다.**

```
    when product.stock >= input.quantity
    set product.stock to product.stock - input.quantity
```

`set`은 스텝이다. 바인딩된 행의 필드를 갱신하고 — 바인딩된 행은 저장된 행이므로
갱신은 `rows`/`result` 단언으로 관측된다 — 그 사실을 `Assignment` effect로 남긴다.
무음 갱신은 없다.

**5. 전액과 부분을 구별한다.**

```
    read payment
    when payment.amount == input.amount
    create refund
```

**쓸 수 없는 것**과 그 이유는 §Reference-level Specification/3의 표에 있다. 가장
자주 걸리는 둘: 앞선 스텝이 갱신한 필드를 뒤의 가드가 읽을 수 없고(모드 등가),
Money·DateTime 같은 비정수 필드는 비교할 수 없다(평가기 없음).

## Reference-level Specification

### 1. Full Grammar (RFC-0002 §Full grammar / RFC-0008 §1 갱신)

```
Guard        ::= ('when' | 'until') Condition
Condition    ::= Presence | Comparison ('and' Comparison)*
Presence     ::= Reference ('exists' | 'missing')
Comparison   ::= Value Comparator Value
Comparator   ::= '<' | '<=' | '>' | '>=' | '==' | '!='

Value        ::= Operand (ArithOp Operand)?
Operand      ::= Reference | Integer | Duration
ArithOp      ::= '+' | '-'

Reference    ::= CamelName | Namespace '.' CamelName
Namespace    ::= 'input' | CamelName
Integer      ::= [0-9]+
Duration     ::= Integer ('ms' | 's' | 'm')

AssignStep   ::= 'set' Reference 'to' Value
```

**Old (RFC-0008 §1):**
```
Condition ::= Presence | Comparison
Comparison ::= Reference Comparator (Integer | Duration)
```

세 가지 제한은 누락이 아니라 결정이다.

- **`or`·`not`·괄호 없음.** 이 RFC는 이슈 #47의 5개 요구를 덮는 최소 표면을 정의한다.
  생산규칙 하나를 더할 때마다 인터프리터와 방출된 MLIR **양쪽**에 같은 평가기를
  유지해야 한다. 표현력 확장은 다음 RFC의 몫이다(RFC-0008 §Alternatives가 세운 순서
  그대로: 검증 가능한 등가를 먼저 세우고 그 위에 쌓는다).
- **`and`는 비교식만 잇는다.** 모드 B는 존재 여부를 실행당 boolean 하나
  (`run_binary(skip=…)`)로 판정하고 비교는 i64 파라미터로 판정한다. 한 조건에 두 채널이
  섞이면 모드 B가 모드 A와 다른 스텝 집합을 낼 수 있다. 존재 검사는 단독 가드로 쓴다.
- **산술은 중첩하지 않는다.** `a - b - c`는 우선순위 규칙을 요구하고, 우선순위 규칙은
  저자가 조용히 틀릴 수 있는 종류의 것이다. 곱셈·나눗셈은 없다(§Alternatives).

**리터럴은 부호가 없다.** 계산 **결과**는 음수일 수 있다. 모드 B가 상수를
`%c<value>_i64`라는 SSA 이름으로 선언하므로 `%c-3_i64`는 유효한 이름이 아니다.

**정규화.** 항은 소스 순서대로 ` and `로 잇고, 비교는 `<left> <op> <right>`, 산술은
`<a> <op> <b>`, 공백은 정확히 1칸이다. Duration은 최적 단위로 되돌린다(`60000` → `1m`).
이 문자열이 IR에 실리고, 두 모드가 그것을 비교하며, RFC-0014의 skip 레코드가 그것을
싣는다.

### 2. IR Representation (RFC-0001 §Appendix A 갱신)

**`Guard.condition`은 정규화 문자열로 남는다.** 구조화하지 않는다 — 파서를 하나로
유지하는 것이 이 문법의 유일한 정본성 보장이고, 구조화는 RFC-0001 노드 카탈로그까지
대체 대상으로 만든다. RFC-0008 §Open Questions 2가 제기한 긴장은 해소되지 않은 채
§Open Questions로 이월한다.

**신규 노드 kind `Assignment`** (카탈로그 21종 → 22종). WorkflowStep의 자식 Effect다.

```json
{
  "kind": "Assignment",
  "id": "wf.place.order.step.3.assign",
  "target": "product.stock",
  "expression": "product.stock - input.quantity",
  "entity": "entity.product"
}
```

| 필드 | 규칙 |
|------|------|
| `kind` | `enum: ["Assignment"]` |
| `id` | `nodeId`. 슬러그는 `assign` |
| `target` | 정규화된 `<binding>.<field>` |
| `expression` | 정규화된 `Value` 문자열 |
| `entity` | `target`의 바인딩이 가리키는 선언된 Entity 노드 id |

`required`는 위 다섯이고 `additionalProperties: false`다. 스키마 게이트
(`scripts/validate_ir.py --self-test`)는 이 분기를 담은 최소 픽스처와, 분기가 도입한
키워드마다 하나씩의 부정 케이스(required 누락 / type 불일치 / enum 밖 kind /
미선언 속성 / 해소 불가 교차참조)를 함께 싣는다. 새 kind가 없는 골든을 변형해 만든
부정 케이스는 이 분기를 한 번도 지나지 않으므로, 그것만으로는 초록이 이 변경에
대해 아무것도 말하지 않는다.

`set`은 `VERB_LEXICON`의 17번째 항목이다(`set` → `Assignment`). 닫힌 동사 테이블은
하나로 유지된다 — 그것이 "어떤 동사가 존재하는가"에 답이 하나이게 하고, 생성된
`verbs.md`와 `docs/ENFORCEMENT-MATRIX.md` §A가 그 테이블에서 나온다.

### 3. 정적 거부 (컴파일 에러, rc=2)

문법이 받되 문서를 보면 거부되는 형태들이다. 전부 `lower`에서 판정한다 — 문서만으로
결정 가능한 것을 런타임까지 미루면 t2 F-4처럼 인터프리터 내부의 원시 예외가 조작자에게
샌다.

| 거부 | 사유 |
|------|------|
| 양변이 모두 리터럴(`1 < 2`) | 아무것도 결정하지 않는 가드는 저작 오류다 |
| 선언 타입이 Integer가 아닌 피연산자 | 평가기가 없다. 실측: `payment.amount`(Money) 가드가 경고 없이 컴파일된 뒤 `TypeError: '<=' not supported between instances of 'dict' and 'int'`로 죽었다(t2 F-4) |
| `input.<field>`의 `<field>`를 어떤 엔티티도 선언하지 않음 | payload는 선언된 전 엔티티 필드의 합집합이다. 그 밖의 이름은 오타다 |
| 엔티티명 `Input` | 바인딩 이름이 `input` 네임스페이스와 충돌한다 |
| 할당 대상이 `input.…` 또는 맨이름 | 입력은 이 워크플로가 소유한 상태가 아니다 |
| 할당 대상 엔티티를 워크플로가 read하지 않음 | 바인딩이 존재할 수 없다(RFC-0012 §G12.5와 같은 사유) |
| 앞선 스텝이 할당한 Reference를 뒤의 가드가 읽음 | 모드 B는 조건 필드를 진입 시 i64 파라미터로 고정 받는다. 그런 프로그램은 두 모드가 다른 값을 본다 |
| `and` 안의 `exists`/`missing` | §1의 두 채널 사유 |

### 4. 값 도메인과 실패 (RFC-0003 실행 의미에 종속)

값은 **부호 있는 64비트 정수**다. 모드 B가 i64로 컴파일하므로 모드 A도 같은 폭을
집행한다 — 그래야 컴파일 경로에서 감싸일 프로그램이 두 모드에서 **똑같이** 실패한다.

런타임 값 실패는 **새 결과 클래스를 만들지 않는다.** RFC-0014가 정한 거부(skip)와도,
성공과도 구별되는 기존 **실패** 클래스를 그대로 쓴다: `RunError` → `failed` +
`failed at: <스텝명>`, rc=1.

| 상황 | 판정 |
|------|------|
| 참조가 아무것도 가리키지 않음(바인딩 없음·필드 없음·payload 키 없음) | 그 비교는 **거짓**. 예외가 아니다(RFC-0008 이전과 동일) |
| 비수치 값의 비교 | `RunError` — `cannot compare non-numeric <ref>=<value>` |
| 산술 결과 또는 피연산자가 i64 범위 밖 | `RunError` — `value out of the 64-bit range` |
| 가드가 거짓이어서 할당이 실행되지 않음 | RFC-0014의 거부 클래스. `completed` 유지 + `skipped` 레코드 + 진단 `guard-skipped-steps` + `--strict` rc=2 |

### 5. Differential Equivalence (RFC-0004 §Execution modes)

관측 클래스는 **늘리지 않는다.** 새 문법의 관측은 기존 4분류와 RFC-0014의 `skips`에
싣는다.

| 관측 클래스 | 새 문법에서의 판정 |
|---|---|
| 실행 순서(스텝 시퀀스) + `skips` | **반드시 일치** |
| 정책 결과(status/attempts) | **반드시 일치** — 값 실패는 양쪽 `failed` |
| 관측 신호(effects) | **반드시 일치** — `Assignment` 효과 이름 포함 |
| 마스킹 | 불변 |
| 할당이 만든 **값** | **허용된 차이.** 모드 B는 저장소를 모형화하지 않는다 |
| 명령 선택(`cmpi`/`addi`/`andi` 형태) | 허용된 차이 |

마지막에서 두 번째 행은 이 RFC가 주장하는 등가의 **범위**다. 기본 입력에서의
EQUIVALENT는 "저장 값이 결과를 결정하지 않는 입력에서 두 모드가 합의했다"는 좁은
주장이며, 그 이상으로 인용해서는 안 된다. 값 차원은 모드 A가 단독으로 단언한다.

모드 B의 하강은 다음과 같다. 조건이 참조하는 **모든** 이름이 `lnpl_run`의 i64
파라미터가 되고(정렬된 이름 순), 산술은 `arith.addi`/`arith.subi`로 비교 앞에 놓이며,
비교는 `arith.cmpi`, `and`는 `arith.andi`로 접힌다. `until`은 조건이 거짓인 동안
반복하므로 항이 하나면 술어를 뒤집고, 여러 항이면 접은 결과를 `arith.xori`로 부정한다
— 드모르간을 방출기 안에서 손으로 펴면 루프의 의미가 틀릴 자리가 하나 더 생긴다.

## Examples

### 5.1 재고 (t1 재현)

```
capability postgres

entity Product
    field
        id UUID
        stock Integer

entity Order
    field
        id UUID
        quantity Integer

service OrderService
    policy
        timeout 5s

workflow PlaceOrder
    read product
    when product.stock >= input.quantity
    create order
    when product.stock >= input.quantity
    set product.stock to product.stock - input.quantity
```

가드가 할당보다 **앞에** 있는 것은 §3의 마지막 거부 때문이다. 의미상으로도 그 순서가
맞다: 확인하고, 만들고, 차감한다.

- `stock=5, quantity=2` → 4스텝 completed, 저장 행 `stock == 3`.
- `stock=1, quantity=2` → `read product`만 실행, `skipped` 2건, 저장 행 불변,
  `--strict` rc=2. **S2가 언어 안에서 거부된다.**

### 5.2 범위와 등가 (t2 재현)

```
workflow Approve
    when input.amount > 0 and input.amount <= 10000
    create payment
```

```
workflow Refund
    read payment
    when payment.amount == input.amount
    create refund
```

`amount=0`·`amount=10001`은 create를 스킵하고, `amount=1`·`amount=10000`은 실행한다.
경계 양쪽이 한 가드 안에서 표현된다.

### 5.3 IR 조각

`5.1`의 마지막 스텝이 낳는 노드:

```json
{"kind": "WorkflowStep", "id": "wf.place.order.step.3",
 "name": "set product.stock to product.stock - input.quantity",
 "children": ["wf.place.order.step.3.assign"]}
{"kind": "Assignment", "id": "wf.place.order.step.3.assign",
 "target": "product.stock", "expression": "product.stock - input.quantity",
 "entity": "entity.product"}
```

예제 파일(`examples/`)은 늘리지 않는다. 새 예제 하나는 `.lir.json`/`.openapi.json`/
`.spec.json` 세 생성물과 골든 테스트를 함께 끌고 오며, 이슈 #47이 요구한 것이 아니다.

## Alternatives

### 집계(`sum`/`count`)를 이번 개정에 넣지 않는 이유

이슈 #47의 완료 기준 [5]는 "집계 동사 도입 **또는** 명시적 로드맵 결정 기록"이다.
**도입하지 않는다.**

집계는 값 문법이 아니라 **행 집합**을 요구한다. 이 플랫폼의 실행 모형에는 그것이 없다:

- 저장소는 단일 키 조회다(`FakeRepository.execute(entity, operation, key)`).
- 실행 스코프는 엔티티당 행 **하나**를 바인딩한다(RFC-0012 §G12.2).
- 그 단일 키 불변식이 모드 B의 정적 판정을 떠받친다(`repo_policy`: 한 실행은 payload
  하나를 가지므로 엔티티 E의 테이블에는 행이 최대 하나다 — 그래서 "이 create가
  충돌하는가"를 문서만으로 답할 수 있다).

따라서 `sum`/`count`는 집합 타입·질의 동사·모드 B의 루프 하강을 함께 요구하며,
그것은 이 RFC가 정의한 최소 표면과 충돌한다.

`sum`/`count`를 **어휘에 넣지 않는다.** 넣으면 효과 없는 동사가 되어 이슈 #36(어휘 밖
동사가 조용한 no-op이 되던 문제)을 재생산한다. 현재 거동이 옳다: 어휘 밖 동사는
`unknown-verb` 진단을 받고 `--strict`에서 rc=2가 된다.

다만 t3 F-1이 요구한 것의 절반 — 파생값을 계산해 필드에 **기록**하는 것 — 은 이
RFC가 실제로 해결한다(`set report.total to report.total + input.amount`). 남은 절반인
"행 집합에 대한 집계"는 후속 이슈로 제안한다(§Open Questions 3).

### 곱셈·나눗셈을 넣지 않는 이유

이슈 #47의 다섯 요구 중 어느 것도 요구하지 않는다. 나눗셈은 0 나눗셈과 반올림 의미를
**두 런타임에서 동시에** 정의해야 하는데, 이 언어의 수치 타입은 Integer와 Decimal이고
Decimal의 산술은 아직 어떤 모드에도 없다. 곱셈만 넣는 것은 대칭을 깨는 특례다.

### IR의 조건을 구조화하지 않는 이유

§2에 적었다. 요지: 파서 SSOT 하나를 지키고 RFC-0001 대체를 피한다.

### `or`/`not`을 넣지 않는 이유

RFC-0008 §Alternatives가 세운 순서를 따른다 — 표현력이 높아질수록 네이티브 평가 경로가
복잡해지므로, 검증 가능한 등가를 먼저 세우고 그 위에 쌓는다. 이 RFC는 `and`까지의
등가를 실측으로 세웠다(양방향 가드 + 씨앗 발산 + 컨트롤 페어).

## Open Questions

1. **할당 후 가드의 해제 경로.** §3의 마지막 거부는 모드 B가 조건 필드를 진입 시점에
   고정 받기 때문이다. 방출기가 갱신된 값을 SSA로 이어 흘리면(scf.if의 결과값,
   unroll된 루프의 iter_args) 그 프로그램도 두 모드에서 같은 값을 볼 수 있다. 그것이
   `until` 루프의 언롤링과 어떻게 상호작용하는지는 이 RFC의 범위 밖이다.

2. **존재 판정을 파라미터로 승격하기.** 존재를 실행당 boolean 하나가 아니라 참조당
   i64 0/1 파라미터로 넘기면 `and` 안의 Presence 금지를 풀 수 있다. `run_binary`의
   `skip` 인자가 그 시점에 사라진다.

3. **집계와 행 집합.** 위 §Alternatives의 결정을 되돌리려면 무엇이 필요한지는 이미
   적혀 있다: 집합 타입, 질의 동사, 모드 B의 루프. 후속 이슈로 기표한다.

4. **Decimal/Money 산술.** 지금은 정적 거부다. 통화 산술은 반올림 정책과 통화 일치
   규칙을 함께 요구하므로 값 문법이 아니라 타입 시스템의 개정이다.

5. **IR 조건의 구조화** — RFC-0008 §Open Questions 2에서 이월. 정규화 문자열 하나에
   SSOT 함수 하나로 의존하는 설계가 "IR이 허브"라는 CHARTER의 주장과 갖는 긴장은
   그대로 남아 있다.

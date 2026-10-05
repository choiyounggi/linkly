# RFC-0062: 할당한 필드를 읽는 가드와 `otherwise` 항목

## Status

- Status: Draft
- Updates: RFC-0015 §Reference-level Specification/3. 정적 거부 (+RFC-0051 §2, RFC-0055 §7, RFC-0056 §7),
  RFC-0015 §Open Questions,
  RFC-0001 §노드 카탈로그/Guard (+RFC-0028, RFC-0056),
  RFC-0002 §Full grammar (+RFC-0012, RFC-0052),
  RFC-0002 §Block structure (+RFC-0019, RFC-0060),
  RFC-0014 §Reference-level Specification/2.1 `when` 모드 (+RFC-0028),
  RFC-0014 §Reference-level Specification/2.4 스킵 레코드 (+RFC-0028, RFC-0050)

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목하고, 규칙 5(연쇄 갱신)에 따라 이미
갱신된 절은 대상과 **직전 갱신 RFC를 모두** 지목한다. 괄호 안이 직전 갱신이다. 그중
RFC-0050·RFC-0051·RFC-0052·RFC-0055·RFC-0056·RFC-0060은 아직 Draft다 — 먼저 Accepted되는
쪽이 직전 갱신이 되고, 나중 쪽이 승격할 때 그 사실을 `Updates:`에 반영한다(RFC-0051·RFC-0052
선례). Draft이므로 대상 RFC에 `Updated-by:` 포인터를 달지 않는다.

- **정적 거부(RFC-0015 §3).** 아래 §1의 최종 텍스트는 RFC-0056 §7의 표에서 "앞선 스텝이
  할당한 Reference를 뒤의 가드가 읽음" 행 **하나를 뺀** 것이다.
- **Open Questions(RFC-0015).** 1번 "할당 후 가드의 해제 경로"를 해소한다(§2).
- **노드 카탈로그/Guard(RFC-0001).** `children`이 `otherwise` 항목을 하나 더 가질 수 있다(§3).
- **Full grammar(RFC-0002).** `GuardedItem` 생산규칙만 바꾼다(§4). RFC-0012는 그 생산규칙을
  "손대지 않는다"고 적었고, RFC-0052(RFC-0049 위)는 `StepLine`을 바꾼다 — 둘 다 이 RFC가
  바꾸는 생산규칙과 겹치지 않지만 같은 절이므로 지목한다.
- **Block structure(RFC-0002).** RFC-0060 개정판의 3항 a·c와 4항에 `otherwise`를 넣는다(§5).
- **가드 런타임(RFC-0014 §2.1·§2.4).** RFC-0028 §4가 §2 전체를, RFC-0050 §4가 그 위에 §2.4를
  갱신했다. 이 RFC는 §2.1에 `otherwise` 실행 규칙을, §2.4에 `mode: "otherwise"` 레코드를
  더한다(§6, §7).

지목하지 **않는** 것:

- RFC-0016 §5(mode A/B 등가 표). 두 모드 B 거부는 RFC-0055·0056·0057·0058처럼 이 RFC의
  §8에 둔다. RFC-0051·0052는 그 표에 행을 더했지만, 더 최근의 네 RFC가 표를 건드리지 않고
  거부를 자기 문서에 두는 쪽을 택했고 이 RFC도 그 선례를 따른다 — 누락이 아니라 선택이다.
- RFC-0014 §2.6(모드 A/B 동등성). 모드 B가 `otherwise`를 쓴 워크플로와 할당한 필드를 읽는
  가드를 모두 거부하므로(§8) 비교할 스킵 레코드가 생기지 않는다. 비교 투영
  `{mode, condition, step, rounds}`는 그대로다.
- RFC-0002 §Keywords. `otherwise`는 RFC-0028의 `or`처럼 가드에 이어지는 줄의 머리어다 —
  `KEYWORDS_CONTROL` 표에 넣지 않는다. 라인 분류는 `when` 가드의 항목 바로 다음 줄에서만
  `otherwise`를 구조로 읽고, 다른 모든 자리에서는 §4·§5의 거부가 결정한다.

이슈 #211 제안 3(RFC-0015 Open Question 1)과 4(`otherwise` 가지)를 닫는다. 제안 1·2는
RFC-0060이 닫았다.

## Motivation

2026-10-02 QA(main `c5e1679`, 이슈 #211)에서 "확인 → 실행 → 결과 보고 다음 단계"처럼
조건이 두 번 이상 이어지는 흐름을 쓰기 어려운 이유가 넷 나왔다. RFC-0060이 (3)을 닫았고,
이 RFC는 나머지 둘을 다룬다.

**(1) 워크플로가 바꾼 값은 가드에 쓸 수 없었다.**

```
    when product.stock >= input.quantity
    set product.stock to product.stock - input.quantity
    when product.stock >= 0
    update product
```

```
compile error: workflow PlaceOrder: guard condition 'product.stock >= 0' reads
'product.stock', which an earlier step assigns — a guard must not depend on a value
this workflow changed (RFC-0015: mode B fixes condition fields at entry). Move the
guard above the assignment.
```

RFC-0015 §3이 이것을 거부한 이유는 모드 B 하나다: 모드 B는 조건 필드를 실행 시작 시점의
i64 파라미터로 받으므로 할당 뒤의 값을 볼 수 없다. 모드 A는 처음부터 현재 값을 읽는다.
이 레포는 같은 모양의 긴장을 이미 세 번 풀었다 — 모드 A는 받고 모드 B가 그 워크플로를
기록된 예외로 거부한다(RFC-0050 숫자 형태 술어, RFC-0052 조회 키, RFC-0055·0056의
`optional`·Text 가드). AWS Step Functions의 Choice 상태가 "직전 상태의 출력"으로 분기하는
것이 기본 용례이듯, 다단 흐름의 핵심은 앞 단계가 바꾼 값으로 다음 단계를 가르는 것이다.

**(4) "아니면"이 없었다.** `else`는 VERB_LEXICON 밖의 낱말이라 아무것도 하지 않는 스텝이
되고, 제안은 `delete`였다.

```
warning: unknown-verb [line 21] else — `else` is outside VERB_LEXICON ... — did you mean 'delete'?
```

대안 가드(`or` 줄, RFC-0028)가 조건 쪽을 채웠지만 "조건이 거짓이면 이 항목" 쪽은 비어
있었다. Step Functions의 Choice가 평면 규칙 목록 + `Default`이듯, 평면 언어도 "아니면"
가지를 1급으로 둘 수 있다. 중첩 ≤2(RFC-0002 §Block structure)는 설계 원칙이므로 "아니면"은
중첩 블록이 아니라 가드의 **형제**여야 한다.

## Guide-level Explanation

### 바꾼 값으로 다시 가르기

```
workflow PlaceOrder
    find product
    when product.stock >= input.quantity
    create order
    when product.stock >= input.quantity
    set product.stock to product.stock - input.quantity
    when product.stock >= 0
    update product
```

이제 컴파일된다. 셋째 가드는 그 줄에 도달한 시점의 `product.stock`을 읽는다 — 재고 5,
수량 2면 차감 뒤의 3을 보고 `update product`를 실행한다. 차감이 재고를 0 아래로 보내면
(가드 없이 차감한 경우) 그 가드는 거짓이고, `update product`는 `skipped[]`에 남는다 — 그
레코드의 `evaluations`는 차감 뒤의 값을 싣는다.

모드 B(`lnpl build`, `lnpl diff`)는 이 워크플로를 거부한다. 조건 필드를 실행 시작 시점
값으로 고정하므로 차감 전 값을 비교하게 되기 때문이다. 고치는 법은 메시지에 있다: 모드 A로
실행한다.

### `otherwise`

```
workflow Settle
    find payment
    when payment.status == 200
    update payment
    otherwise
    fail declined
```

`otherwise`는 `when` 가드가 소유한 항목 **바로 다음 줄**에 쓴다. 그 다음 항목 하나(스텝 한
줄이거나 `pipeline`/`parallel` 블록 하나)를 소유하고, 가드와 그 모든 `or` 대안이 거짓일
때만 실행한다. 가드가 참이면(또는 대안 하나가 참이면) 피가드 항목이 실행되고, `otherwise`
항목은 `skipped[]`에 `mode: "otherwise"` 레코드로 남는다 — 어느 쪽이든 실행되지 않은 가지는
기록된다.

`otherwise`는 가드의 형제이지 가드 안의 블록이 아니다. 그래서 깊이 2를 넘지 않고, 여러
스텝을 실행하려면 가드 쪽과 똑같이 `pipeline` 블록 하나로 묶는다. `else if` 연쇄는 없다 —
`otherwise` 바로 다음 줄에 가드를 쓰면 거부된다.

`else`를 쓰면 이제 `did you mean 'otherwise'?`가 나온다.

## Reference-level Specification

### 1. 정적 거부 — RFC-0015 §3 갱신 (치환 후 최종 텍스트)

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
> | `and` 안의 `exists`/`missing` | §1의 두 채널 사유 |
> | `input.<field>`에 `exists`/`missing`, 그 `<field>`를 선언한 엔티티가 둘 이상인데 `optional` 표시가 엇갈림 | 존재 검사의 허용 여부(RFC-0016 §3 3.2)가 엔티티마다 다르다. 어느 엔티티의 선언을 따를지 정할 근거가 없으므로 선언한 엔티티를 모두 대고 거부한다(RFC-0055) |
> | `Password` base 필드를 가드의 `==`/`!=`에 씀 | RFC-0001의 마스킹 의무 — 가드 스킵 레코드가 비교한 값을 싣는다(RFC-0056) |
> | 가드 등가의 맨이름 리터럴이 상대쪽 `enum` refinement의 멤버가 아님 | enum은 닫힌 값 집합이다(RFC-0011) — 멤버가 아닌 리터럴은 항상 거짓이므로 저작 오류다(RFC-0056) |
> | 가드의 Text 등가 항 어느 쪽이든 산술식 | RFC-0016은 Text에 산술을 주지 않는다 — 평가기가 없다(RFC-0056) |
>
> 앞선 스텝이 할당한 Reference를 뒤의 가드가 읽는 것은 거부가 아니다(RFC-0062). 모드 A는
> 그 가드를 그 시점의 값으로 평가하고, 모드 B는 그런 워크플로를 기록된 예외로 거부한다
> (RFC-0062 §8).

RFC-0056 §7과 다른 곳은 둘이다: "앞선 스텝이 할당한 Reference를 뒤의 가드가 읽음" 행이
빠졌고, 표 아래에 그 사실을 적은 문단이 붙었다.

### 2. Open Questions — RFC-0015 §Open Questions 갱신 (치환 후 최종 텍스트)

> 1. **할당 후 가드의 해제 경로 — 해소(RFC-0062).** 모드 A는 할당한 필드를 읽는 가드를
>    그 시점의 값으로 평가하고, 모드 B는 그 워크플로를 거부한다. 방출기가 갱신된 값을
>    SSA로 이어 흘리는 길(scf.if의 결과값, unroll된 루프의 iter_args)은 택하지 않았다 —
>    RFC-0062 §Alternatives.
>
> 2. **존재 판정을 파라미터로 승격하기.** 존재를 실행당 boolean 하나가 아니라 참조당
>    i64 0/1 파라미터로 넘기면 `and` 안의 Presence 금지를 풀 수 있다. `run_binary`의
>    `skip` 인자가 그 시점에 사라진다.
>
> 3. **집계와 행 집합.** 위 §Alternatives의 결정을 되돌리려면 무엇이 필요한지는 이미
>    적혀 있다: 집합 타입, 질의 동사, 모드 B의 루프. 후속 이슈로 기표한다.
>
> 4. **Decimal/Money 산술.** 지금은 정적 거부다. 통화 산술은 반올림 정책과 통화 일치
>    규칙을 함께 요구하므로 값 문법이 아니라 타입 시스템의 개정이다.
>
> 5. **IR 조건의 구조화** — RFC-0008 §Open Questions 2에서 이월. 정규화 문자열 하나에
>    SSOT 함수 하나로 의존하는 설계가 "IR이 허브"라는 CHARTER의 주장과 갖는 긴장은
>    그대로 남아 있다.

1번만 바뀌었다. 2~5번은 RFC-0015 원문 그대로다.

### 3. 노드 카탈로그 `Guard` 행 — RFC-0001 §노드 카탈로그/Guard 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0001 "### 노드 카탈로그" 절 **Behavior** 표의
`Guard` 행에 대한 치환 후 최종 텍스트다(RFC-0028 §3, RFC-0056 §2의 텍스트 포함). 다른 kind의
행과 표 서두의 산문은 그대로다.

| kind | 필수 필드 | 선택 필드 | children 허용 |
|------|----------|----------|--------------|
| Guard | `mode`(`when`\|`until`\|`repeat` — 닫힌 enum) | `condition`(`when`·`until` 전용 — 조건 서술), `count`(`repeat` 전용 — 1 이상 정수), `alternatives`(`when` 전용, 배열, 1개 이상의 문자열 — `or`로 이어지는 대안 조건 서술. RFC-0028 신설), `textEqualityOperands`(배열의 배열 — `[condition, *alternatives]`와 같은 순서로 각 서술마다 하나, Text 등가 항(RFC-0016 §3 3.3)의 피연산자 이름을 중복 없이 정렬한 문자열 배열. 그런 항이 없는 서술은 빈 배열. 어느 서술에도 없으면 필드 자체가 없다. RFC-0056 신설) | 피가드 항목 1개(WorkflowStep, Concurrency, Pipeline 중 하나), 그리고 `mode`가 `when`이면 그 뒤에 `otherwise` 항목 0~1개(같은 세 kind 중 하나 — 가드와 모든 대안이 거짓일 때만 실행. RFC-0062). 실행 의미는 RFC-0014 §2. 2026-07-31 신설(RFC-0002 부록 A.4-① 해소), 2026-08-24 `alternatives` 추가(RFC-0028, 이슈 #93), 2026-10-04 `textEqualityOperands` 추가(RFC-0056, 이슈 #207), 2026-10-04 `otherwise` 항목 추가(RFC-0062, 이슈 #211) |

`children[0]`은 언제나 피가드 항목이고, `children[1]`이 있으면 `otherwise` 항목이다 —
새 필드나 새 kind를 두지 않고 위치로 가른다. `otherwise`를 쓰지 않은 가드의 IR은 이 RFC 전과
바이트 단위로 같다. `schemas/lir.schema.json`의 `nodeGuard.children`은 `minItems: 1`,
`maxItems: 2`이고, `mode`가 `until`/`repeat`인 Guard의 두 번째 자식은 스키마가 거부한다 —
파서도 만들지 않고(§5 4항), 에이전트 프로토콜의 구조 검사(`guard_cardinality`)도 받지 않는다.

### 4. Full grammar — RFC-0002 §Full grammar 갱신 (치환 후 최종 텍스트, `GuardedItem`만)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0002 §Full grammar의 `GuardedItem` 생산규칙에 대한
**치환 후 최종 텍스트**다. 이 절의 다른 생산규칙(`WorkflowItem`·`WhenGuard`·`RepeatGuard`·
`UntilGuard`·`ParallelBlock`·`PipelineBlock`, RFC-0052가 갱신한 `StepLine` 등)은 각 최신
텍스트가 그대로 유효하다. `WhenGuard` 뒤의 `or` 줄은 RFC-0028 §1의 `Guard`/`AltGuard`
생산규칙 그대로다.

```
GuardedItem       ::= WhenGuard GuardTarget OtherwiseItem?
                    | (RepeatGuard | UntilGuard) GuardTarget
GuardTarget       ::= StepLine | ParallelBlock | PipelineBlock
OtherwiseItem     ::= 'otherwise' EOL GuardTarget
```

**Old (RFC-0002 원문):**
```
GuardedItem       ::= (WhenGuard | RepeatGuard | UntilGuard)
                      (StepLine | ParallelBlock | PipelineBlock)
```

`OtherwiseItem`은 `Condition`을 갖지 않는다 — 조건 문법(RFC-0015 §1, RFC-0028 §1)은 그대로다.
`OtherwiseItem` 안에 다시 `GuardedItem`이 오는 생산규칙은 없다(`else if` 없음).

### 5. Block structure — RFC-0002 §Block structure 갱신 (치환 후 최종 텍스트 전문)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0060 개정판의 치환 후 최종 텍스트 전문이다. 3항
a·c와 4항에 `otherwise`를 넣었고, 4항 끝에 `otherwise`의 자리 규칙을 붙였다.

---

#### Block structure (RFC-0062 개정판)

1. **키워드 구획** — 블록 경계는 키워드가 정한다. 최상위 선언 키워드는 이전
   블록 전체를 자동 종결한다. 절 키워드는 소속 선언의 하위 구획을 열고, 다음
   절 키워드 또는 최상위 키워드에서 닫힌다. 명시적 종결 키워드를 가지는 블록은
   `parallel`(→ `merge`) 하나뿐이다.

2. **들여쓰기 비구조성** — 파서는 라인 선두 공백으로 블록을 만들지 않는다.
   관례 4칸·탭 금지는 style 권장일 뿐 문법이 아니다. **수용되는 모든
   프로그램에서, 같은 토큰열은 포맷팅과 무관하게 항상 같은 구조로 파싱된다.**

3. **모순 들여쓰기의 거부** — 다만 들여쓰기가 2항이 정한 구조와 **모순되는**
   프로그램은 수용 집합에서 제외한다(컴파일 에러). 들여쓰기는 구조를 만들지
   못하고 오직 프로그램을 반증할 수만 있으므로, 2항의 보장은 유지된다.
   모순은 다음 셋이며, 이 목록은 닫혀 있다.

   a. **가드 스코프 모순.** 가드(`when`/`until`/`repeat`) 또는 `otherwise`가 자기보다
      깊은 열의 항목을 소유할 때, 그 다음에 오는 첫 줄(최상위 항목이나 `otherwise`)이
      여전히 가드보다 깊은 열에 있으면 거부한다. 가드와 `otherwise`는 항목 하나만
      소유하므로(RFC-0008 §5.2) 그 줄은 밖에서 작동하는데, 열은 안에 있다고 말하기
      때문이다.

   b. **spec 꼬리 모순.** `spec` 절의 섹션(`given`/`when`/`expect`)이 `spec`보다
      깊은 열에 있을 때, 그 블록 안의 내용 줄이 `spec`과 같거나 더 얕은 열에
      있으면 거부한다. 워크플로의 항목은 `spec` 앞에 오므로(§Full grammar:
      `WorkflowItem* SpecClause?`) 그 줄은 항목이 될 수 없는데, 열은 항목인 것처럼
      말하기 때문이다.

   c. **파이프라인 암묵 종결 모순.** `pipeline`이 열려 있을 때, 그 `pipeline` 줄보다
      깊은 열에 제어 키워드(`when`/`until`/`repeat`/`pipeline`/`parallel`) 또는
      `otherwise`가 오면 거부한다. `pipeline`은 다음 키워드에서 저절로 닫히므로(1항) 그
      키워드는 파이프라인 밖에서 작동하는데, 열은 안에 있다고 말하기 때문이다. 에러
      문면은 닫히는 파이프라인(이름, 이름이 없으면 그 줄 번호)과 고치는 법을 싣는다:
      가드나 `otherwise`면 파이프라인 자신의 열로 내어 쓰거나 뒤 스텝을 새 `pipeline`으로
      묶을 것, 블록 개시면 파이프라인 자신의 열로 내어 쓸 것. 열린 `parallel`에는 적용되지
      않는다 — `parallel`은 `merge`로만 닫히고, 그 안의 가드·`otherwise`·블록 개시는 이미
      거부된다(4항). 선언 키워드나 파일 끝에서 닫히는 경우도 대상이 아니다.

   세 규칙 모두 **레이아웃이 정보를 담을 때만** 발동한다: 가드와 그 항목이 같은
   열이면 a가, 섹션과 `spec`이 같은 열이면 b가, 키워드가 `pipeline` 줄과 같거나 더
   얕은 열이면 c가 발동하지 않는다. 전부 같은 열에 쓴 프로그램은 이 항의 적용을
   받지 않는다.

4. **중첩 ≤2** — 선언 = 레벨 0, 절과 제어 블록 = 레벨 1, 그 내부 구획
   (`given`/`when`/`expect`, `parallel`의 브랜치 step) = 레벨 2. 그 이상의
   중첩은 문법적으로 불가능하다 — `ParallelBlock`과 `PipelineBlock`의 본문은
   `StepLine`만 허용하므로(§Full grammar의 EBNF) parallel 안의 parallel,
   spec 안의 spec은 생산규칙 차원에서 존재하지 않는다. `otherwise`는 가드의 형제라
   레벨을 더하지 않는다. 그래서 자리가 닫혀 있다 — 다음은 전부 컴파일 에러다:
   `when` 가드의 항목 바로 다음 줄이 아닌 곳의 `otherwise`(가드 없음, 사이에 다른
   항목이 낀 경우 포함), 한 가드의 두 번째 `otherwise`, `until`/`repeat` 가드 뒤의
   `otherwise`(거짓 가지가 없다), 열린 `parallel` 안의 `otherwise`, 아직 항목이 없는
   가드 뒤의 `otherwise`, `otherwise` 바로 다음의 가드(`else if` 없음), 아무것도
   소유하지 않고 선언이 끝나는 `otherwise`, 같은 줄에 낱말이 붙은 `otherwise`.

5. **한 줄 한 선언** — 모든 선언·절 개시·step·내용 항목은 정확히 한 라인이다.

---

참조 구현: `impl/lnpl/parser.py::_otherwise_line`(4항의 자리 규칙), `_attach`(항목을 가드의
`otherwise` 칸에 넣는다), `_check_pipeline_layout`(3항 c).

### 6. `when` 모드 — RFC-0014 §2.1 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0014 §Reference-level Specification/2.1(RFC-0028
§4가 갱신한 최종형)의 치환 후 최종 텍스트다. 마지막 문단이 새로 붙었고 그 앞은 RFC-0028 §4
원문 그대로다. 인용 안의 "§Reference-level Specification/N"은 RFC-0028을 가리킨다.

> #### 2.1 `when` 모드 (갱신)
>
> 조건을 **1회 평가**한다. 대안 가드가 없으면(§Reference-level Specification/1의
> `AltGuard*`가 0개) RFC-0014 원문 그대로 — 조건이 참이면 피가드 항목을 실행하고,
> 거짓이면 건너뛴다.
>
> **대안 가드가 있으면**, 조건과 모든 대안을 소스 순서대로 **전부 평가**한다
> (단락 평가 없음 — RFC-0014가 `and`의 각 항을 전부 평가하는 것과 같은 이유:
> 조건은 순수하므로 결과는 같고, 트레이스는 평가되지 않은 항이 있으면 그 항의
> 값을 영영 보여줄 수 없다). **하나라도 참이면** 피가드 항목을 실행한다. 실행되는
> 경우, 트레이스는 참으로 판정된 첫 항이 조건 자신인지 몇 번째 대안인지를
> `INFO` 레벨로 남긴다(§2.4에서 정의하는 스킵 레코드와는 다른 채널 — 스킵이
> 아니라 **실행됐다**는 사실의 관측이므로):
>
> ```
> guard alternative matched: alt=0 condition="input.channel == 1"
> ```
>
> 조건 자신이 참이면 `alt=<primary>`로 남긴다(대안 번호가 아니라 원 조건이
> 참이었다는 뜻) — 이 경우는 대안 가드가 없는 기존 프로그램과 관측이 달라지지
> 않는다는 것을 보장하기 위한 표기이지, 새 요구 사항이 아니다: **대안이 없는
> `when`은 이 로그를 전혀 내지 않는다**(하위 호환. `evaluations`가 issue #83에서
> 그랬듯, 새 신호는 그것을 켠 프로그램에서만 나타난다).
>
> **전부 거짓이면**(대안 가드가 없을 때의 "거짓"과 동형), 건너뛴 사실은 trace에
> 기록되며, §2.4의 스킵 레코드 하나를 남긴다.
>
> **`otherwise` 항목이 있으면**(RFC-0062), 판정은 위와 같고 그 결과로 두 항목 중 정확히
> 하나가 실행된다. 전부 거짓이면 피가드 항목의 스킵 레코드를 남긴 **뒤** `otherwise`
> 항목을 실행한다. 하나라도 참이면 피가드 항목을 실행한 **뒤** `otherwise` 항목에 대한
> `mode: "otherwise"` 스킵 레코드 하나를 남긴다. 조건은 어느 쪽이든 한 번만 판정한다 —
> `otherwise`는 조건을 다시 평가하지 않는다. 가드가 읽는 참조는 그 가드에 도달한 시점의
> 값이다 — 앞선 스텝이 `set`/`format`으로 바꾼 필드면 바뀐 값을 읽는다(RFC-0062 §1).

### 7. 스킵 레코드 — RFC-0014 §2.4 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0014 §Reference-level Specification/2.4(RFC-0050
§4가 갱신한 최종형)의 치환 후 최종 텍스트다. 첫 문장과 `mode`·`condition`·`steps`·
`evaluations` 행이 달라진다. 인용 안의 "§Reference-level Specification/N"은 RFC-0028의 절을
가리킨다.

> #### 2.4 스킵 레코드 (갱신)
>
> 실행 결과는 **스킵 매니페스트**를 가진다. 피가드 항목을 실행하지 않은 가드마다, 그리고
> 가드가 참이어서 실행하지 않은 `otherwise` 항목마다(RFC-0062) 레코드가 하나씩, 만난
> 순서대로 들어간다.
>
> | 필드 | 의미 |
> |------|------|
> | `guard` | 가드 노드의 IR id. 모드 A 전용 — 모드 간 비교에서 제외한다 |
> | `mode` | `"when"` 또는 `"until"`. **갱신 (RFC-0062)**: `otherwise` 항목의 레코드는 `"otherwise"` |
> | `condition` | **갱신**: 대안이 없으면 정규화된 조건 문자열 그대로(RFC-0008 §4 불변). 대안이 있으면 조건과 모든 대안을 소스 순서대로 `" or "`로 이어붙인 문자열 — `"input.channel == 1 or input.amount <= 100"`. 이 결합은 **표시/비교 전용**이며 `parse_condition`으로 재파싱되지 않는다(§Reference-level Specification/3). `mode: "otherwise"` 레코드에서는 **참이었던** 그 가드의 같은 문자열이다(RFC-0062) |
> | `steps` | 그 레코드가 가리키는 항목(피가드 항목, 또는 `otherwise` 항목)이 감싼 **모든 WorkflowStep의 이름**, 선언 순서. 중첩 블록(`Concurrency`·`Pipeline`)까지 하강해 수집한다. 피가드 항목의 레코드는 `otherwise` 항목의 스텝을 담지 않는다(RFC-0062) |
> | `rounds` | `when`·`otherwise`면 없음(`null`), `until` 0라운드면 `0` |
> | `evaluations` | (issue #83, RFC-0014 원문 불변 필드) **갱신**: 대안이 있으면 조건 자신의 항들에 이어 각 대안의 항들도 소스 순서대로 같은 리스트에 담는다 — 어느 항이 어느 대안 소속인지는 이 리스트의 위치가 아니라 `ref`가 가리키는 값으로 읽는다(추가 태깅 없음, RFC-0014가 이미 "다섯 키는 불변"이라 적은 원칙을 존중해 `evaluations`의 원소 shape을 넓히지 않는다). **갱신 (RFC-0050)**: 숫자 형태 술어 항도 한 원소를 남긴다 — 존재 검사와 같은 모양으로 `{"ref": <필드>, "value": <해소한 값, 없으면 null>, "op": "is-numeric" 또는 "is-not-numeric", "expected": null, "holds": <판정>}`. `and` 안의 술어 항은 다른 항과 함께 소스 순서대로 담긴다. **갱신 (RFC-0062)**: `mode: "otherwise"` 레코드에서는 빈 배열이다 — 가드는 참이었고, 참인 판정의 항은 이 채널이 아니라 트레이스(§2.1)가 싣는다 |
>
> `condition`의 결합 표기는 `restore_skips`(모드 B 재구성)와 `_skip_record`(모드
> A 실측)가 **같은 함수**로 만든다 — 이름은 §Reference-level Specification/5가
> 고정한다. 두 모드가 각자 결합하면 공백 하나의 실수가 `differential.verify`를
> 거짓 양성/거짓 음성으로 만든다.
>
> **status 어휘는 변경되지 않는다** (RFC-0014 원문 불변).

사람이 읽는 출력(`lnpl run`)과 진단 `guard-skipped-steps`는 `mode: "otherwise"` 레코드를
"가드가 참이어서 `otherwise`가 실행되지 않았다"로 쓴다 — `condition`을 `otherwise`의 조건으로
읽히게 두지 않는다:

```
  skipped by `otherwise` (`when payment.status == 200` held): fail declined
```

`lnpl run --dry-run`의 계획은 `otherwise` 항목을 가드 항목의 `otherwise` 키로 싣는다
(`children`은 피가드 항목 하나 그대로).

### 8. Mode B

모드 B(`lnpl build`, `lnpl diff`)는 두 가지를 기록된 예외로 거부한다. 둘 다 문서만으로
판정하므로 모드 B 도구가 없어도 같은 거부가 먼저 나온다.

1. **할당한 필드를 읽는 가드.** 가드(서술이든 `or` 대안이든)가, 소스 순서로 앞선 스텝의
   `Assignment`가 쓴 Reference를 읽는다. 모드 B는 조건 필드를 진입 시점의 i64 파라미터로
   고정하므로(RFC-0008 G8) 할당 전 값을 비교하게 된다. 판정은 RFC-0015 §3이 컴파일 시점에
   하던 것과 같은 걸음이다 — 가드는 자기가 소유한 항목보다 **먼저** 판정되므로, 몸체가 자기
   조건 필드를 바꾸는 `until` 루프는 대상이 아니다(RFC-0015가 언제나 받던 프로그램이다).
   ```
   step update product: guard 'product.stock >= 0' reads product.stock, which an earlier
   step assigns — mode B fixes condition fields at entry, so it would compare the value
   before the assignment (RFC-0062 §Mode B, recorded exemption) — run it in mode A
   ```

2. **`otherwise` 항목을 소유한 가드.** 모드 B는 거짓 가드에서 실행되는 가지를 컴파일하지
   않는다. 가드의 조건만 보면 모드 B가 컴파일할 수 있는 Integer 비교여도 거부한다.
   ```
   step update payment: guard 'payment.status == 200' owns an `otherwise` item, which mode
   B has no compiled branch for (RFC-0062 §Mode B, recorded exemption) — run it in mode A
   ```

거부 순서는 `build`와 `diff`가 같다(issue #185): Money 가드(RFC-0051) → 조회 키(RFC-0052)
→ `optional` 필드 가드(RFC-0055) → Text 등가 가드(RFC-0056) → fill-source create(RFC-0057)
→ `fail`(RFC-0058) → `respond` 집계·목록 항(RFC-0061) → 할당한 필드를 읽는 가드 →
`otherwise`(이 RFC). 앞선 것이 먼저 거부한다. `diff`는 그 앞에 숫자 형태 술어(RFC-0050)를
먼저 묻는다(RFC-0050 원문 그대로). 다른 거부 RFC가 `respond` 고리 뒤에 끼어들면 이 RFC의 두
고리는 그 뒤에 온다.

RFC-0061 §4의 "`respond list`는 워크플로의 유일한 `respond`" 규칙은 `otherwise`의 두 가지를
합쳐 센다 — 서로 배타적인 두 가지에 각각 `respond`를 두어도, 그중 하나가 목록 항이면
거부된다. 보수적인 거부이므로 이 RFC는 그대로 둔다.

참조 구현: `impl/lnpl/backend.py::_assigned_guard_offender`, `_otherwise_offender`,
`_refuse_unsupported_guards`; `impl/lnpl/differential.py::verify`.

## Examples

### 골든 시나리오 "Login" (RFC-0007 §6)

`examples/login.lnpl`은 가드에서 할당한 필드를 읽지 않고 `otherwise`도 쓰지 않는다. 컴파일
결과(IR, OpenAPI, spec 매니페스트)는 이 RFC 전과 바이트 단위로 같다.

### 골든 인접 예제 — 차감 뒤의 재고로 가르기 (RFC-0007 §6, 골든이 다루지 않는 기능)

```
workflow PlaceOrder
    find product
    set product.stock to product.stock - input.quantity
    when product.stock >= 0
    update product
```

재고 1, 수량 2로 실행하면 차감 뒤 재고는 -1이고 `update product`는 건너뛰어진다. 스킵
레코드의 `evaluations`는 `{"ref": "product.stock", "value": -1, "holds": false, ...}`다 —
진입 시점 값 1이었다면 가드는 참이었다. 재고 2, 수량 2면 0이므로 실행된다.
`impl/tests/test_assigned_field_guard.py`가 셋을 고정한다.

### 골든 인접 예제 — `otherwise` (RFC-0007 §6, 골든이 다루지 않는 기능)

```
workflow Settle
    when input.channel == 1
    or input.amount <= 100
    create payment
    otherwise
    fail declined
```

| 입력 | 실행 | `skipped[]` |
|------|------|-------------|
| `channel=1` | `create payment` | `{"mode": "otherwise", "steps": ["fail declined"], ...}` |
| `channel=2, amount=100` | `create payment` | `{"mode": "otherwise", "steps": ["fail declined"], ...}` |
| `channel=2, amount=101` | `fail declined` → `failed` | `{"mode": "when", "steps": ["create payment"], ...}` |

`impl/tests/test_otherwise_branch.py`가 이 표와 블록을 소유한 `otherwise`를 고정한다.

### 컴파일 거부

```
    otherwise
    create payment
```
```
line 9: `otherwise` has no preceding guard — it must immediately follow a `when`
guard's single step or block, and runs when the guard (and its `or` alternatives) are
all false (RFC-0062)
```

```
    repeat 2
    create payment
    otherwise
    create payment
```
```
line 11: `otherwise` follows the `repeat` guard on line 9, but only a `when` guard can
own an `otherwise` — `repeat` has no false branch for it to run on (RFC-0062)
```

```
    when payment.status == 200
    create payment
    otherwise
    update payment
    otherwise
    create payment
```
```
line 13: a second `otherwise` follows the one on line 11 — a guard owns at most one
`otherwise`, and `otherwise` owns exactly one step or block; wrap several steps in a
`pipeline` block instead (RFC-0062)
```

```
    when payment.status == 200
    parallel
        create payment
        otherwise
```
```
line 12: `otherwise` cannot appear inside a `parallel` block (close it with `merge` first)
```

`else`는 여전히 VERB_LEXICON 밖의 낱말(경고, no-op)이고 제안이 바뀐다:

```
`else` is outside VERB_LEXICON: this step derives no Effect and runs as a descriptive
no-op — did you mean 'otherwise'?
```

## Alternatives

### 모드 B가 갱신된 값을 SSA로 이어 흘리기 (기각)

RFC-0015 Open Question 1이 적은 길이다: `scf.if`의 결과값과 unroll된 루프의 `iter_args`로
할당 뒤의 값을 조건까지 이어 보낸다. 그러려면 모드 B가 `Assignment`의 **값**을 계산해야
하는데, 지금 모드 B는 할당을 효과 이름으로만 방출하고 값을 계산하지 않는다(RFC-0015 §5
"할당이 만든 값: 허용된 차이"). 값 계산을 들이면 저장소 모형, 산술의 i64 범위 실패, `until`
언롤링의 매 라운드 값까지 모드 B가 새로 책임져야 한다 — 이 이슈의 크기를 넘는 개정이다.
모드 A 허용 + 모드 B 기록된 예외는 이 레포가 세 번 쓴 방식이고, 나중에 모드 B가 값을 갖게
되면 이 예외 하나만 지우면 된다.

### 모드 B가 `otherwise`를 컴파일하기 (기각)

`when`은 이미 `scf.if`로 내려가므로 `else` 영역에 두 번째 항목을 두는 것 자체는 작다. 그러나
모드 B의 관측은 실행된 스텝 줄과 `restore_skips`가 재구성하는 스킵 목록인데, 재구성은
"`when`의 모든 자식은 조건이 참일 때 실행된다"는 가정 위에 서 있다(`_steps_in_order`). 두
가지를 넣으려면 그 재구성과 스킵 레코드의 모드 B 쪽 생성이 함께 바뀌어야 하고, 그 차이를
검증할 차등 테스트가 함께 와야 한다. 이 RFC는 모드 A 의미를 먼저 고정하고 모드 B는 기록된
예외로 둔다.

### `else`를 키워드로 쓰기 (기각)

`else`는 다른 언어에서 `if`의 짝이고, 이 언어는 `if`를 예약어로 금지했다(RFC-0002 §예약어).
짝 없는 `else`는 그 금지를 반쯤 되돌리는 낱말로 읽힌다. `otherwise`는 산문으로 읽히는 이
언어의 다른 키워드(`when`, `until`, `repeat`)와 같은 결이다. `else`를 쓰면 did-you-mean이
`otherwise`를 가리킨다.

### 여러 항목을 소유하는 `otherwise` 블록 (기각)

`otherwise` 아래 들여 쓴 여러 줄을 블록으로 읽으면 들여쓰기가 구조를 만들게 된다(RFC-0002
§Block structure 2항 위반). 가드와 똑같이 항목 하나를 소유하고, 여러 스텝은 `pipeline` 하나로
묶는다 — 한 규칙을 두 번 배우지 않는다.

### `until`/`repeat`에도 `otherwise`를 허용하기 (기각)

`repeat N`에는 거짓이 없고, `until`의 "거짓"은 루프를 한 번 더 도는 것이지 다른 가지가 아니다.
허용하면 "언제 실행되는가"를 모드마다 새로 정의해야 한다. 거부하고 메시지가 이유를 말한다.

## Open Questions

1. **모드 B의 값 계산.** 위 두 기각은 모두 "모드 B가 할당의 값을 모른다"에서 나온다. 모드
   B가 값을 갖게 되는 RFC가 생기면 §8의 두 고리를 함께 다시 본다.

2. **`otherwise` 레코드의 `evaluations`.** 지금은 빈 배열이다(§7). 가드가 참인 판정의 항까지
   스킵 레코드에 싣는 것이 관측자에게 쓸모 있는지는 사용 사례가 생기면 다시 판단한다.

# RFC-0012: 실행 스코프와 스텝 결과 바인딩

## Status

- Status: **Accepted** (RFC-0012, 2026-08-05)
- Updates: RFC-0002 §Full grammar, RFC-0008 §Reference-level Specification/1. Full Grammar, RFC-0003 §Guard

RFC-0007 §2.2 규칙 5(연쇄 갱신)에 따라 대상 RFC와 **직전 갱신 RFC를 모두** 지목한다.
`Condition` 생산 규칙은 RFC-0002 본문에 있고 RFC-0008이 이미 그 절을 갱신했으므로, 두 문서를
함께 지목하지 않으면 어느 텍스트가 이기는지 기계적으로 확인할 수 없다.

## Motivation

이슈 #37이 보고한 관측은 이것이다 — `examples/checkout.lnpl`은 `find product` 다음에
`when stock > 0`을 두지만, 그 가드가 참인지 거짓인지는 **조회된 행과 무관하게** 결정된다.

관측 가능한 형태로 적으면:

- RFC-0002 §Full grammar의 `Condition` 생산 규칙에는 필드를 가리키는 형태가 `CamelName` 하나뿐이다
  (RFC-0008이 갱신한 `Presence`/`Comparison` 양쪽 모두).
- 참조 구현 `impl/lnpl/interp.py`의 조건 평가 함수는 인자가 `(condition, payload)` 둘이며,
  값을 `payload.get(...)` 한 곳에서만 읽는다.
- 같은 파일의 `RepositoryCall` 실행부는 `read`/`query`가 돌려준 행을 지역 변수로 받아
  `found` 불리언만 남기고 **행 자체는 어디에도 보관하지 않는다.**

즉 `CamelName` 한 형태로 쓸 수 있는 이름은 입력 payload의 필드뿐이며, 조회된 행의 필드를
가리킬 표기가 문법에 없다. 이슈 #39가 요구하는 `spec … expect`의 반환값 단언도 같은 빈칸을
공유한다 — 단언할 대상에 접근할 표기가 없다.

이 RFC는 그 빈칸 하나를 메운다: **스텝 결과가 놓이는 이름 공간(실행 스코프)** 을 규정하고,
가드와 `expect`가 그 스코프를 **같은 규칙으로** 읽게 한다.

## Guide-level Explanation

조건과 단언에서 이름은 두 가지 형태로 쓴다.

```
when stock > 0                 # bare — 입력 payload의 stock
when product.stock > 0         # 한정 — 방금 읽은 Product 행의 stock
```

두 형태는 **서로 다른 곳을 본다.** bare 이름은 워크플로에 들어온 입력을,
한정 이름은 이 실행에서 저장소가 돌려준 행을 가리킨다.

`find product` 같은 읽기 스텝이 성공하면 그 행이 `product`라는 이름으로 스코프에 놓인다.
이후의 가드와 `spec`의 `expect`가 그것을 읽는다:

```
workflow Checkout
    find product
    when product.stock > 0
    create order
    spec
        given
            stored product stock 0
        when
            checkout
        expect
            result product.stock == 0
```

**한 벌의 스코프다.** 가드가 읽는 것과 `expect`가 읽는 것은 같은 이름 공간이며, 같은 해석
규칙을 따른다. 가드용 스코프와 단언용 스코프가 따로 있지 않다.

## Reference-level Specification

RFC-0007 §2.2 규칙 4에 따라, 아래는 "무엇을 바꾼다"가 아니라 **치환 후의 최종 텍스트**다.

### RFC-0002 §Full grammar / `Condition` (치환 후 최종 텍스트)

이 절의 다른 생산 규칙(`WorkflowItem`·`GuardedItem`·`WhenGuard`·`RepeatGuard`·`UntilGuard`·
`StepLine`·렉시컬 항목)은 RFC-0002 원문이 그대로 유효하며 이 RFC가 손대지 않는다.

```
Reference         ::= CamelName | CamelName '.' CamelName
Presence          ::= Reference ('exists' | 'missing')
Comparison        ::= Reference Comparator (Integer | Duration)
Condition         ::= Presence | Comparison
```

`CamelName ::= [a-z] [a-zA-Z0-9]*` 는 RFC-0002 §Lexical 원문 그대로다. 점(`.`)은 `CamelName`에
속하지 않으므로 `Reference`의 두 조각은 각각 `CamelName`이어야 하며, 조각은 **정확히 1개 또는
2개**다. `a.b.c`는 이 생산 규칙에 해당하지 않는다.

### RFC-0008 §Reference-level Specification / 1. Full Grammar (치환 후 최종 텍스트)

RFC-0008의 이 절에서 `Presence`·`Condition` 두 줄이 위 §RFC-0002 §Full grammar 블록으로
치환된다. 같은 절의 나머지는 RFC-0008 원문이 그대로 유효하다 — **예약어 추가**(`exists`,
`missing`), **Comparator 집합**(`<` `<=` `>` `>=` `==` `!=`), **기각된 형태**(1~4토큰 자유 구,
논리 결합, 멤버십 연산) 세 항목은 이 RFC가 손대지 않는다.

기각 목록에 한 항목을 더한다:

- **3단 이상의 경로**(`a.b.c`) — 바인딩은 행 하나이고 행의 필드는 스칼라다. 중첩 경로를
  받으려면 평가기가 중첩 구조를 순회해야 하는데, 참조 구현의 행은 평면 dict이므로 그 순회가
  평가할 대상이 없다. RFC-0008이 "평가기 없는 생산 규칙"을 제거한 것과 같은 판정이다.

### RFC-0003 §Guard (치환 후 최종 텍스트 — 조건 평가 스코프)

RFC-0008이 갱신한 `when`/`until`/`repeat`의 **반복·종료 의미는 그대로 유효하다**
(`_UNTIL_ROUND_CAP = 16`, 두 경계, `reason="deadline"`/`reason="round_cap"` 구분).
이 RFC는 그 절에 **조건이 무엇을 읽는가**를 더한다.

#### G12.1 이름 공간

조건 평가 시점의 이름 공간은 두 갈래이며, 갈래는 `Reference`의 **형태로** 결정된다.

| 형태 | 가리키는 것 |
|------|-------------|
| `CamelName` (bare) | 워크플로에 전달된 **입력 payload**의 필드 |
| `CamelName '.' CamelName` (한정) | `binding '.' field` — 바인딩된 **행**의 필드 |

#### G12.2 무엇이 바인딩되는가

이 실행에서 `operation`이 `read` 또는 `query`인 `RepositoryCall`이 **성공적으로 완료된**
Entity마다 바인딩이 하나 생긴다.

- **바인딩 이름**은 Entity의 선언 이름을 camelCase로 바꾼 것이다: `Product` → `product`,
  `OrderItem` → `orderItem`. IR의 노드 id에서 유도하지 않는다 — 노드 id는 다단어 이름을
  점으로 분할하므로(`entity.order.item`) 단일 `CamelName`이 되지 못한다.
- **바인딩 값**은 저장소가 돌려준 행이다.
- **마지막 쓰기가 이긴다.** 같은 Entity를 다시 읽으면 바인딩이 갱신된다. `until` 루프의
  각 라운드는 직전 라운드가 갱신한 값을 본다.
- `create`·`update`·`delete`는 **바인딩하지 않는다.** 이 연산들은 행이 아니라 영향 행 수를
  돌려주므로 바인딩할 행 내용이 없다. 실행 후의 엔티티 상태는 스코프가 아니라
  `spec`의 `expect entity <EntityName> rows <N>`이 관측한다.

#### G12.3 충돌 시 우선순위

**충돌이 존재하지 않는다.** bare 이름은 결코 바인딩으로 해석되지 않고, 한정 이름은 결코
payload로 해석되지 않는다. 분리는 우선순위 서열이 아니라 **문법 형태**로 이루어진다.

이 규정의 관측 가능한 결과: 이 RFC 이전에 작성된 프로그램은 조건이 전부 bare 형태이므로,
평가 결과가 하나도 달라지지 않는다.

두 Entity의 바인딩 이름이 같아질 수는 없다 — 선언 이름이 모듈 안에서 유일하기 때문이다.

#### G12.4 해석되지 않는 이름

값이 없을 때의 의미는 RFC-0008 이전부터의 동작과 같다. 네 경우 모두 **같은 한 규칙**을 따른다:
해석 결과가 없으면 `Presence`는 부재로, `Comparison`은 거짓으로 평가된다.

| 상황 | `exists` | `missing` | `Comparison` |
|------|----------|-----------|--------------|
| payload에 그 필드가 없다 | 거짓 | 참 | **거짓** |
| 바인딩이 아직 없다(읽기 전 / `query`가 행을 못 찾음) | 거짓 | 참 | **거짓** |
| 바인딩은 있으나 행에 그 필드가 없다 | 거짓 | 참 | **거짓** |
| 값이 정수로 해석되지 않는다 | 거짓 | 참 | **실행 오류** |

마지막 행만 예외다: 비교 대상이 존재하는데 숫자가 아닌 것은 부재가 아니라 오류이며,
참조 구현은 필드 이름과 조건 문자열을 담은 실행 오류를 낸다.

`read`가 행을 찾지 못하면 그 스텝이 실패하므로 후속 가드에 도달하지 못한다. 위 표의 두 번째
행이 실제로 관측되는 경로는 `query`가 행을 찾지 못한 경우다.

#### G12.5 컴파일 시점 거부

한정 참조는 **문서를 읽을 수 있는 시점**(lowering)에 검사되며, 아래 셋 중 하나라도 어긋나면
컴파일이 실패한다. 셋 다 런타임까지 살아 나가지 않는다.

| # | 검사 | 어긋났을 때 |
|---|------|-------------|
| ⓐ | `binding`이 선언된 Entity의 바인딩 이름과 일치한다 | 컴파일 실패 |
| ⓑ | 그 Entity가 `field`를 선언한다 | 컴파일 실패 |
| ⓒ | 이 워크플로가 그 Entity를 `read`/`query`로 부른다 | 컴파일 실패 |

ⓒ가 없으면 바인딩이 결코 생기지 않는 참조가 G12.4의 "바인딩이 아직 없다"로 흡수되어
**조용히 거짓**이 된다. 평가할 수 없는 조건을 파스 시점에 거부한다는 RFC-0008의 판정을
한정 참조까지 넓힌 것이다.

#### G12.6 모드 B

RFC-0004 §Execution modes의 네 관측 대상(실행 순서·정책 결과·관측 신호·마스킹)에서 두 모드가
일치해야 한다는 계약은 그대로다. 조건 필드 값은 모드 B에서도 **같은 스코프 규칙으로** 유도된다.

모드 B의 생성 모듈은 저장소 상태를 모델링하지 않는다(RFC-0004: 저장소 결과는 문서에서
유도 가능한 질문으로 답한다). 따라서 한정 참조의 값은 **호스트가 시드 규칙으로부터 정적으로
투영해** 주입한다. 시드 규칙으로 재현할 수 없는 행을 호출자가 모드 A에만 준 경우, 두 모드의
비교는 **수행되지 않고 거부된다** — 배선 차이를 모드 불일치로 보고하지 않기 위해서다.
이는 시드 조건이 어긋날 때 비교를 거부하는 기존 규정과 같은 처리다.

#### G12.7 `spec … expect` 어휘

`expect`는 가드와 **같은 스코프**를 읽는다. 어휘는 닫혀 있고, 평가할 수 없는 기대는
조용한 통과가 아니라 오류다. 기존 7종(`completed` `failed` `steps` `slo` `duration`
`cache` `attempts`)의 의미는 이 RFC가 바꾸지 않는다.

| 단언 대상 | 형태 | 읽는 것 |
|-----------|------|---------|
| 반환값 | `result <Reference> <op> <value>` / `result <Reference> exists\|missing` | G12.1의 이름 공간. 문법도 평가기도 가드의 것을 그대로 쓴다 |
| 엔티티 상태 | `rows <Entity> <N>` | 실행 후 저장소의 행 수 |
| 이벤트 | `emitted <Event>` / `emitted <Event> count <N>` / `emitted <Event> payload <field> exists\|missing` | 아웃박스 |
| 실패 | `error step <name…>` / `error reason <substring…>` | 실패한 스텝과 사유 |
| 효과 | `effects <N>` / `effects complete` | 실행된 각 스텝이 수행한 Effect |

키가 `entity`/`event`가 **아닌** 이유: 둘 다 최상위 선언 키워드(`lexer.KEYWORDS_TOP`)라
`expect` 줄 첫 토큰으로 쓰면 파서가 선언으로 읽는다. 그래서 `rows`/`emitted`다.

**`effects complete`** — 이 실행에서 **실행된 모든 스텝이 Effect를 최소 하나 수행했다**.
이슈 #39의 두 번째 수용 기준이다. `VERB_LEXICON` 밖의 동사는 Effect를 유도하지 않으므로
(이슈 #36) 그 스텝은 실행되고 아무것도 하지 않는데, `expect steps N`은 그것까지 세고
통과한다 — 구현이 비어 있는데 spec이 초록인 상태다. 이 형태가 그것을 빨갛게 만들고,
아무 일도 하지 않은 스텝의 이름을 보고한다.

**자동이 아니라 명시(opt-in)다.** 서술용 스텝은 LNPL을 쓰는 정당한 방법이며
(`diagnostics.py`가 그렇게 기록한다), 골든 `examples/login.lnpl`이 세 개를 쓴다
(`generate token`·`audit login`·`return token`). `unknown-verb` 진단이 있는 모든 모듈의
spec을 자동으로 실패시키면 **골든 시나리오 자체를 거부**하게 된다. 그래서 저자가 그 보증을
의도하는 곳에서 직접 적는다.

**범위는 이 실행이 수행한 것이다.** 닫힌 가드 아래의 no-op 스텝은 실행되지 않았으므로
여기서 세지 않는다. 그 경우를 보고하는 것은 컴파일 시점의 `unknown-verb` 진단이며,
`lnpl spec`이 이제 그것을 출력한다(이전에는 `compile`·`run`만 출력했다 — 검증이 본업인
명령이 유일하게 침묵했다).

## Examples

**허용** — 출하 예제 `examples/checkout.lnpl`의 가드:

```
workflow Checkout
    validate product
    find product
    cache product
    when product.stock > 0
    create order
```

`find product`가 `entity.product`를 `read`하므로 G12.5 ⓒ가 만족되고, `Product`가 `stock`을
선언하므로 ⓑ가 만족된다. 가드는 조회된 행의 `stock`으로 분기한다.

**거부** — 선언되지 않은 Entity를 가리키는 한정 참조:

```
    when widget.stock > 0
```

실측 결과(전문):

```
LowerError: workflow Checkout: guard condition 'widget.stock > 0' names 'widget', which is not a declared entity
```

**거부** — 그 Entity가 선언하지 않은 필드:

```
    when product.nosuch > 0
```

실측 결과(전문):

```
LowerError: workflow Checkout: guard condition 'product.nosuch > 0' names field 'nosuch', which entity Product does not declare
```

**거부** — 워크플로가 읽지 않는 Entity를 가리키는 한정 참조:

```
workflow Checkout
    find product
    when order.total > 0
    create order
```

실측 결과(전문):

```
LowerError: workflow Checkout: guard condition 'order.total > 0' reads entity.order, but this workflow never reads it — no binding can ever exist, so the guard would be false forever
```

**여전히 허용** — bare 형태. 의미가 바뀌지 않았다는 것의 관측 가능한 형태다:

```
    when stock > 0
```

## Alternatives

| # | 검토한 대안 | 기각 사유 |
|---|------------|----------|
| 1 | **암묵적 섀도잉** — bare 이름을 해석할 때 바인딩을 먼저 보고, 없으면 payload를 본다 | 기존 프로그램의 의미를 조용히 바꾼다. 저장소에 있는 `examples/` 와 `impl/tests/` 의 가드 조건을 전수 조사하면 bare `token`이 8회 쓰이며, 그 문장(`when token missing`)이 묻는 것은 "요청이 토큰을 가져왔는가"다. 섀도잉하면 그 질문이 "저장된 세션 행에 token 필드가 있는가"로 바뀐다 — 이것은 표현력 확장이 아니라 **뜻이 다른 프로그램으로의 재해석**이다. RFC-0008이 "파싱은 통과하고 런타임에 반드시 실패한다"를 제거한 것과 달리, 이 대안은 파싱도 실행도 통과하면서 **다른 답**을 낸다 |
| 2 | **모호성 오류** — bare 이름이 Entity의 필드명과도 겹치면 컴파일 실패시켜 한정 표기를 강제한다 | 같은 전수 조사에서 `token`(8) `total`(2) `stock`(2)이 이 판정에 걸린다. 그중 `when token missing`은 payload를 묻는 것이 **맞는** 문장이므로, 이 대안은 올바른 문장을 거부하고 저자에게 뜻이 다른 표기를 강요한다. 모호성 거부는 뜻이 갈리는 곳에 쓰는 장치인데, G12.3이 보이듯 두 형태는 문법으로 이미 갈려 있어 모호성 자체가 없다 |
| 3 | **모드 B가 저장소 행을 모델링하도록 확장** | RFC-0004는 모드 B의 저장소 결과를 "문서에서 유도 가능한 질문"으로 답하도록 규정하고, 참조 백엔드의 빌드는 그 이유를 "실행 시점에 저장소 결과를 정하면 생성 모듈이 저장소 상태를 분기하게 되고, 그것은 네이티브 런타임 안의 저장소다"라고 적는다. 한정 참조 하나를 위해 그 결정을 뒤집는 것은 범위에 비례하지 않는다. G12.6의 정적 투영 + 재현 불가 시 거부로 같은 보증을 얻는다 |
| 4 | 스코프 규칙을 RFC 없이 구현에만 둔다 | RFC-0007 §2.2 규칙 2 — 지목하지 않은 절과 모순되면 안 되고, 모순이 필요하면 그 절을 지목해야 한다. `Condition` 생산 규칙을 넓히면서 RFC-0002 §Full grammar를 지목하지 않으면 그것은 개정이 아니라 결함이다 |

## Open Questions

없음.

`Reference`의 3단 이상 경로는 §Reference-level Specification의 기각 목록에 들어갔으므로
미결이 아니다. 논리 결합(`and`/`or`)은 RFC-0008 §Open Questions 3이 계속 추적하며 이 RFC가
손대지 않는다. 멤버십 검사는 RFC-0009가 RFC-0002 §Open Questions ②에 남겨 둔 그대로다.

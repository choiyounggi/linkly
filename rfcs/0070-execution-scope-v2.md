# RFC-0070: 실행 스코프와 스텝 결과 바인딩

## Status

- Status: **Accepted** (RFC-0070, 2026-10-28)
- Supersedes: RFC-0012

**통합 출처.** 갱신 RFC에서 온 텍스트와 그 출처는 다음과 같다(RFC-0007 §2.2 규칙 3·5, 연쇄를 끝까지 따른 최신 Accepted 텍스트).

| 절 | 효력 있는 텍스트의 출처 |
|----|------------------------|
| §Reference-level Specification/RFC-0002 §Full grammar / `Condition` | 문법 블록의 `Reference`·`Comparison`: RFC-0015 §1. `Presence`·`Condition`: RFC-0050 §1 |
| §Reference-level Specification/G12.2 | 머리 문단: RFC-0030 §2. 머리 문단 뒤 문단(`Aggregate`의 `Reference`는 … 넓힌 것이다): RFC-0025 §5 — RFC-0027 §4가 말없이 뺀 두 문장, 유지. 단일 행 바인딩: RFC-0025 §5, 단 바인딩 값 문장은 RFC-0052 §2. RowSet 바인딩: RFC-0025 §5, 단 읽기 전용 소비 항목은 RFC-0059 §4. 네트워크 결과 바인딩: RFC-0027 §4. 생성 결과 바인딩과 `update`·`delete` 문단: RFC-0030 §2. 마지막 문장(`by`가 있어도 바인딩하지 않는다): RFC-0052 §2 |
| §Reference-level Specification/G12.4 | 표의 둘째 행과 마지막 문단: RFC-0025 §6.1 |
| §Reference-level Specification/G12.5 | 표의 ⓒ 행: RFC-0052 §2. 절 끝 문단들, 이 순서로: RFC-0025 §6.2(`query`를 뺀 이유), RFC-0030 §3, RFC-0052 §2(멤버십 문단, 조회 키 고유 규칙 표, 두 거부의 문구) |
| §Reference-level Specification/G12.6 | 마지막 문단: RFC-0052 §6 |

표에 없는 절과, 표에 있는 절에서 출처를 적지 않은 텍스트는 RFC-0012 원문 그대로다.

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
Reference    ::= CamelName | Namespace '.' CamelName
Presence     ::= Reference ('exists' | 'missing')
Comparison   ::= Value Comparator Value
Condition    ::= Presence | Term ('and' Term)*
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

이 실행에서 완료된 `RepositoryCall`은 그 `operation`에 따라, 완료된
`NetworkCall`은 `result` 필드의 유무에 따라 네 이름공간 중 하나에
바인딩을 남길 수 있다. 한 엔티티는 최대 단일 행 바인딩 1개 + RowSet
바인딩 1개를 동시에 가질 수 있다(RFC-0075 §5). 네트워크 결과 바인딩과
**생성 결과 바인딩**은 엔티티 자신의 바인딩 이름이 아닌, 저자가 이름
붙인 네 번째 이름공간이며, 단일 행 바인딩과 같은 문법 위치
(`<binding>.<field>`)를 쓴다 — 그래서 이름이 겹칠 수 없다는 것이
lowering 시점의 정적 거부다(RFC-0027 §2, §1로 확장).

`Aggregate`의 `Reference`(§2)는 언제나 RowSet
바인딩을 본다. 두 문법 위치가 겹치지 않으므로 충돌은 없다 — RFC-0012 §G12.3이
bare/한정 이름 사이에 이미 세운 것과 같은 "문법 형태가 가른다"는 원칙을 두
바인딩 종류 사이로 넓힌 것이다.

**단일 행 바인딩** (`operation == "read"`인 호출만 — `query`는 더는 여기 속하지
않는다.):

- **바인딩 이름**은 Entity의 선언 이름을 camelCase로 바꾼 것이다: `Product` →
  `product`. IR의 노드 id에서 유도하지 않는다.
- **마지막 쓰기가 이긴다.** 같은 Entity를 다시 `read`하면 바인딩이 갱신된다.

단일 행 바인딩의 **바인딩 값**은 "저장소가 그 read의 키 아래에서 돌려준 행"이다 —
`by <ref>`가 있는 read는 §3이 파생한 키 아래의 행을, 없는 read는 지금처럼 payload `id` 키
아래의 행을 바인딩한다.

**RowSet 바인딩** (`operation == "query"`인 호출만 — 이 RFC가 처음 도달시키는
경로, §Motivation 참조):

- **바인딩 이름**은 단일 행 바인딩과 같은 규칙(camelCase 선언 이름)이되, 별개
  이름 공간에 놓인다.
- **바인딩 값**은 드라이버의 `query(entity_id)`가 돌려준 행 리스트다(§7).
  드라이버가 행을 하나도 못 찾으면 빈 리스트다 — 부재가 아니라 **빈 RowSet**이며,
  §4의 규칙대로 그 위의 집계는 실패하지 않고 0을 낸다.
- **마지막 쓰기가 이긴다.** 같은 Entity를 다시 `list`하면 RowSet이 갱신된다.
- RowSet은 **읽기 전용 소비**다 — `<binding>.<field>` 형태의 단일 필드
  참조로도, 다른 쓰기 대상으로도 쓸 수 없다. 집계(§2)와, RFC-0059이 정한
  `respond`의 두 항 — 이름 붙인 집계 항과 목록 항 — 으로만 소비된다.

**네트워크 결과 바인딩** (`operation == "call"`이 아니라, 이 RFC가 처음
도달시키는 `NetworkCall.result` 필드가 있는 완료된 호출):

- **바인딩 이름**은 소스의 `as <name>`이 준 이름 그대로다 — Entity 선언에서
  유도하지 않는다(NetworkCall에는 대상 Entity가 없다).
- **바인딩 값**은 평탄화된 `{"status": <Integer>, **body}`다 — 응답 바디의
  최상위 키가 `status`와 같은 딕셔너리에 나란히 놓인다(`Reference`가 두
  조각까지만 받으므로, §Guide-level Explanation이 적은 대로 중첩된
  `body.<key>` 접근은 문법 밖이다). `<name>.status`, `<name>.<bodyKey>`로
  읽는다. `status`가 바디의 같은 이름 키보다 이긴다.
- **마지막 쓰기가 이긴다.** 같은 이름으로 다시 호출하면 갱신된다 — 단일 행
  바인딩과 같은 규칙, 다른 이름공간.
- **읽기 전용 소비**다 — 다른 쓰기 대상(`set`의 좌변)으로 쓸 수 없다.
  `NetworkCall`은 저장소에 쓰지 않으므로 `persist`할 행이 없다.
- `as` 없는 `call`/`request`는 어느 이름공간에도 바인딩하지 않는다 —
  RFC-0027 §3의 후방 호환 규칙 그대로다.

**생성 결과 바인딩** (`operation == "create"`이고, `result` 필드가 있는
완료된 `RepositoryCall` — `RepositoryCall.result`는 이 RFC가 처음
도달시킨다):

- **바인딩 이름**은 소스의 `as <name>`이 준 이름 그대로다 — Entity의
  선언 이름(camelCase)에서 유도하지 않는다(§1 ⓑ가 그 둘이 겹치는 것을
  이미 막는다).
- **바인딩 값**은 새로 만든 행이다 — 생성 시점에 payload의 동명 필드
  (`derived` 제외)를 초기값으로 복사한 것(§3). 단일 행 바인딩과 달리
  그 Entity의 **선언된 필드 형태를 그대로** 갖는다(네트워크 결과
  바인딩과 다른 점 — 응답 바디는 선언된 형태가 없다).
- **쓰기 가능**하다 — 네트워크 결과 바인딩과 달리 `set`/`format`의
  좌변이 될 수 있다(§4). 같은 이름으로 다시 `create ... as`를 쓰면
  갱신된다 — 마지막 쓰기가 이긴다는 같은 규칙, 다른 이름공간.
- `as` 없는 `create`/`insert`는 어느 이름공간에도 바인딩하지 않는다 —
  RFC-0027 §3의 후방 호환 규칙과 같은 모양.

`create`·`insert` 이외 — **`update`·`delete`는 여전히 바인딩하지
않는다** — RFC-0012 원문의 이유(영향 행 수만 돌려주므로 바인딩할 행
내용이 없다) 그대로다.

`update`/`delete`는 `by`가 있어도 바인딩하지 않는다.

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
| 바인딩이 아직 없다(읽기 전) | 거짓 | 참 | **거짓** |
| 바인딩은 있으나 행에 그 필드가 없다 | 거짓 | 참 | **거짓** |
| 값이 정수로 해석되지 않는다 | 거짓 | 참 | **실행 오류** |

마지막 행만 예외다: 비교 대상이 존재하는데 숫자가 아닌 것은 부재가 아니라 오류이며,
참조 구현은 필드 이름과 조건 문자열을 담은 실행 오류를 낸다.

`read`가 행을 찾지 못하면 그 스텝이 실패하므로 후속 가드에 도달하지 못한다. 이
RFC 이전에는 두 번째 행이 실제로 관측되는 경로가 `query`가 행을 찾지 못한 경우였다
— `query`도 그때는 단일 행 바인딩에 참여했기 때문이다(RFC-0012 원문 §G12.2). §5가
`query`를 그 이름 공간에서 빼고, §6.2(G12.5 ⓒ)가 `query`만 있고 `read`가 없는
엔티티로의 한정 참조 자체를 컴파일 거부로 막은 뒤로는, 그 경로가 더는 존재하지
않는다. 두 번째 행이 이제 실제로 관측되는 유일한 경로는 **읽기 전**이다 — 가드나
`expect`가 프로그램 순서상 그 엔티티의 `read`보다 앞서 있어서, 그 시점엔 아직
바인딩이 생기지 않은 경우(G12.5 ⓒ는 워크플로 **어딘가에** `read`가 있으면 만족되고,
그 `read`가 참조보다 뒤에 와도 된다).

#### G12.5 컴파일 시점 거부

한정 참조는 **문서를 읽을 수 있는 시점**(lowering)에 검사되며, 아래 셋 중 하나라도 어긋나면
컴파일이 실패한다. 셋 다 런타임까지 살아 나가지 않는다.

| # | 검사 | 어긋났을 때 |
|---|------|-------------|
| ⓐ | `binding`이 선언된 Entity의 바인딩 이름과 일치한다 | 컴파일 실패 |
| ⓑ | 그 Entity가 `field`를 선언한다 | 컴파일 실패 |
| ⓒ | 이 워크플로가 그 Entity를 `read`/`query`로 부르거나, `create ... as <binding>`으로 그 Entity의 행을 만든다. 조회 키 `by <binding>.<field>`도 같은 검사를 받는다 | 컴파일 실패 |

ⓒ가 없으면 바인딩이 결코 생기지 않는 참조가 G12.4의 "바인딩이 아직 없다"로 흡수되어
**조용히 거짓**이 된다. 평가할 수 없는 조건을 파스 시점에 거부한다는 RFC-0008의 판정을
한정 참조까지 넓힌 것이다.

`query`를 뺀 이유는 §5(G12.2)가 그 결과다 — `query`는 이제 단일 행이 아니라
RowSet을 바인딩하므로, `query`만 있고 `read`가 없는 워크플로에서 `<binding>.<field>`
한정 참조를 허용하면 결코 채워지지 않는 단일 행 바인딩을 조용히 참조하게 된다
(G12.4 "바인딩이 아직 없다"로 흡수돼 조용히 거짓이 되는데, 그 침묵이 §Motivation이
연 질문 — "죽은 경로가 틀린 채로 살아난다" — 을 반복한다). 이 갱신 전에는 `query`가
죽은 경로였으므로 ⓒ의 이 분기는 결코 참이 되지 않았다 — 관측 가능한 프로그램의
의미는 바뀌지 않는다. `read`(및 `authenticate`/`load`/`find`— 전부 `operation="read"`로
lower되는 동의어)만 있던 기존 프로그램의 컴파일 결과도 그대로다.

"쓰려면 먼저 읽어라"였던 유일한 해법에 "또는 만들면서 이름을
붙여라"가 더해진다 — G12.4의 "바인딩이 아직 없다"로 흡수되어 조용히
거짓이 되는 것을 막는다는 원래 취지(ⓒ가 없으면 벌어지는 일)는 그대로
지켜진다.

ⓒ는 **워크플로 전체의 멤버십**이다 — 그 읽기·생성이 참조보다 앞에 있는지는 보지 않는다.
참조보다 뒤에서 읽히는 바인딩(자기 참조 `find order by order.productId` 포함)은 컴파일을
통과하고, 그 스텝이 실행될 때 바인딩이 아직 없으면 §3의 명명된 `RunError`로 실패한다.

조회 키 고유 규칙(참조 형태별):

| 참조 | 판정 |
|------|------|
| bare 이름(`productId`) — payload 필드 | 허용, 실행 시점에 해석 |
| `input.<field>` | 필드가 어떤 Entity에 선언돼 있으면 허용(그 필드가 `derived`나 Password여도 — payload 값이다) |
| `caller.subject` / `caller.role` | 허용 |
| `call ... as <name>`의 `<name>.<field>` — 네트워크 결과 | 허용, 실행 시점에 해석(RFC-0027 §2) |
| `<binding>.<field>` — 선언된 비-`derived`, 비-Password 필드 | 허용(ⓒ 적용) |
| `<binding>.<field>` — `derived` 필드 | 거부 — 서버 계산 필드는 값이 믿을 만하게 있지 않다(RFC-0030 §3) |
| `<binding>.<field>` — base가 Password인 필드 | 거부 — 저장 키를 마스킹 필드로 만들 수 없다(issue #43의 마스킹 초크포인트) |

두 거부의 문구:

```
workflow <W>: lookup key '<ref>' names field '<f>', which is `derived` (server-computed, RFC-0030 §3) -- a row cannot be addressed by a field whose value is not reliably present
workflow <W>: lookup key '<ref>' has declared type <T>, whose base is Password -- a stored key must not be built from a masked field (issue #43's masking chokepoint, RFC-0052 §Static checks)
```

#### G12.6 모드 B

RFC-0004 §Execution modes의 네 관측 대상(실행 순서·정책 결과·관측 신호·마스킹)에서 두 모드가
일치해야 한다는 계약은 그대로다. 조건 필드 값은 모드 B에서도 **같은 스코프 규칙으로** 유도된다.

모드 B의 생성 모듈은 저장소 상태를 모델링하지 않는다(RFC-0004: 저장소 결과는 문서에서
유도 가능한 질문으로 답한다). 따라서 한정 참조의 값은 **호스트가 시드 규칙으로부터 정적으로
투영해** 주입한다. 시드 규칙으로 재현할 수 없는 행을 호출자가 모드 A에만 준 경우, 두 모드의
비교는 **수행되지 않고 거부된다** — 배선 차이를 모드 불일치로 보고하지 않기 위해서다.
이는 시드 조건이 어긋날 때 비교를 거부하는 기존 규정과 같은 처리다.

모드 B의 저장소 판정(read가 행을 찾는가, create가 충돌하는가)은 "한 실행은 payload
하나를 가지므로 엔티티 E의 모든 호출이 같은 키를 가리킨다"는 단일 키 투영에 기댄다.
조회 키(RFC-0052)는 그 투영을 깨므로, 워크플로 안의 어떤 `RepositoryCall`이든
`lookup`을 가지면 모드 B는 그 워크플로를 **빌드하지 않는다** — MLIR을 내기 전에
`BackendError`로 거부한다:

```
step <step>: <entity_id> uses a lookup key (by <ref>), which the single-key seed projection cannot model (RFC-0052 §Mode B) — run it in mode A
```

`lnpl build --backend`와 `lnpl diff`는 이를 `backend error: …`(rc=4)로 보고한다.
차동 하네스(`differential.verify`)는 툴체인 확인 **전에** 같은 워크플로를
`DifferentialError`(기록된 예외, RFC-0052 §Mode B)로 거부한다 — 비교를 수행하지 않으며
거짓 EQUIVALENT를 내지 않는다. `by`가 없는 워크플로의 모드 B 동작은 바뀌지 않는다.

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
미결이 아니다. 논리 결합(`and`/`or`)은 RFC-0069 §Open Questions 3이 계속 추적하며 이 RFC가
손대지 않는다. 멤버십 검사는 RFC-0009가 RFC-0002 §Open Questions ②에 남겨 둔 그대로다.

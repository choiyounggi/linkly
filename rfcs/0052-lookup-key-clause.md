# RFC-0052: 조회 키 절 `by <ref>` — read·update·delete가 payload `id` 아닌 키로 행을 지목한다

## Status

- Status: Draft
- Updates: RFC-0002 §Full grammar,
  RFC-0012 §Reference-level Specification/G12.2,
  RFC-0012 §Reference-level Specification/G12.5,
  RFC-0012 §Reference-level Specification/G12.6,
  RFC-0016 §Reference-level Specification/5. mode A/B 등가

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목하고, 규칙 5(연쇄 갱신)에 따라 이미
갱신된 절은 대상과 **직전 갱신 RFC를 모두** 지목한다.

- **문법(RFC-0002 §Full grammar).** Draft RFC-0049가 `StepLine`을
  `Verb Word* EOL`로 바꾸는 중이다. 이 RFC의 §1은 그 최종 텍스트 **위에** 저장소 동사의
  꼬리 절 규칙을 더한다 — RFC-0049를 직전 갱신으로 지목한다.
- **바인딩(RFC-0012 §G12.2).** RFC-0025 §5, RFC-0027 §4, RFC-0030 §2, RFC-0048 §4가
  차례로 갱신한 절이다. 효력 있는 텍스트는 RFC-0048 §4에 있다. 넷 모두 지목한다.
- **컴파일 시점 거부(RFC-0012 §G12.5).** RFC-0025와 RFC-0030 §3이 갱신한 절이다(ⓒ 행의
  효력 있는 텍스트는 RFC-0030 §3). 둘 다 지목한다.
- **모드 B(RFC-0012 §G12.6).** 이번이 첫 갱신이다 — 지목할 직전 갱신 RFC가 없다.
- **등가 표(RFC-0016 §5).** Draft RFC-0051 §5가 이 절의 첫 갱신이다(RFC-0051 Status
  문단: "RFC-0016 §5는 첫 갱신이다"). 이 RFC는 두 번째 갱신이므로 RFC-0051을 직전 갱신으로
  지목하고, 아래 §5의 최종 텍스트는 RFC-0051 §5의 표 **위에** 행 하나를 더한 것이다.
  두 Draft 중 먼저 Accepted되는 쪽이 직전 갱신이 되고, 나중 쪽이 승격할 때 그 사실을
  `Updates:`에 반영한다.

지목하지 **않는** 것:

- RFC-0015 §Alternatives의 "단일 키 불변식" 문장. 계약 절이 아니라 집계 기각의 근거를
  서술하는 문단이다. 이 RFC는 그 불변식을 **엔티티별로** 완화하지만(§7), 그 문단이 논증하는
  집계 기각은 그대로 선다(RFC-0007 §2.2 규칙 2 — 지목하지 않은 절은 반박되지 않는다).
- RFC-0004 §실행 모드와 semantic equivalence. 모드 B의 거부 행은 그 계약을 구체화하는
  RFC-0016 §5 표에 들어간다(§5) — RFC-0004 본문의 표는 바뀌지 않는다.

Draft이므로(RFC-0007 §2.2 규칙 6: 개정은 Accepted 시점에 효력이 발생한다) 대상 RFC들에
`Updated-by:` 줄이나 절 머리 포인터를 아직 달지 않는다.

## Motivation

probe-v0.8 s1 주문 플랫폼 사례(issue #175)의 두 발견이 같은 뿌리에서 나온다.

- **F-3 (blocker).** `find product`와 `create order as newOrder`를 한 워크플로에 두면,
  같은 상품을 가리키는 **서로 다른** 두 주문 중 두 번째의 `create order`가
  `repository create conflicts: entity.order already exists`로 실패한다 — 그리고 상품
  조회도 주문의 `id`로 한다. `repo_policy.row_key(entity_id, payload)`가 **모든**
  엔티티의 행을 한 payload의 `id` 아래 두기 때문이다. 저자는 `list product where id ==
  input.productId` + `max`로 우회하는 데 재시도 6회가 걸렸다.
- **F-6 (F-3의 연쇄).** 주문이 성공해도 `Stock.onHand`가 줄지 않는다. 재고 행을 주문의
  `id`와 **다른** 키(상품 id)로 `find` + `update`할 방법이 없기 때문이다(REPORT §5 U2가
  이 이슈로 합쳐졌다).

한 실행에서 엔티티마다 **다른 행**을 지목할 수단이 문법에 없다. `rfcs/`와 ROADMAP에 행
키·조회 키 항목은 없다 — 이 RFC가 첫 행 키 RFC다.

부수 결함: `find|read|load|authenticate|update|delete <Entity>` 뒤의 꼬리 단어는 지금까지
**조용히 버려졌다**(`update order as somethingElse`가 평범한 update로 컴파일된다). 조회 키
절을 여는 자리가 곧 그 자리이므로 같은 RFC에서 닫는다.

## Guide-level Explanation

저장소 동사 여섯 개가 선택적 꼬리 절 하나를 받는다:

```
find|read|load|authenticate|update|delete <Entity> [by <ref>]
```

- `by <ref>`가 없으면 지금과 같다 — 행 키는 `<entity_id>#<payload의 id>`다.
- `by <ref>`가 있으면 그 참조가 **실행 시점에** 가리키는 값이 키가 된다:
  `find product by input.productId`는 `entity.product#<input.productId의 값>` 아래 행을
  읽는다.
- `create`/`insert`는 여전히 `as <name>`만 받는다. 새로 만든 행의 키는 언제나 payload의
  `id`다 — `create order by …`는 컴파일 오류다.
- `list`는 자기 절(`where`/`order by`/`limit`, RFC-0025 §5·§8, RFC-0038)을 그대로 쓴다.
- 여섯 동사 뒤에 `by <ref>` 이외의 무엇이 오면 컴파일 오류다.

s1의 주문은 이렇게 쓴다 — 주문은 자기 `id`로 만들고, 상품·재고는 상품 id로 찾고 고친다:

```
workflow PlaceOrder
    find product by input.productId
    find stock by input.productId
    set stock.onHand to stock.onHand - input.qty
    update stock by input.productId
    create order as newOrder
```

두 번째 주문(다른 주문 id, 같은 상품 id)은 새 주문 행을 만들고(충돌 없음) 같은 재고 행을
한 번 더 줄인다.

`by`가 바꾸는 것은 **어느 행을 읽고 쓰느냐**뿐이다. 읽은 행이 어떤 이름으로 바인딩되는지는
그대로다 — `find stock by input.productId`는 여전히 `stock`에 바인딩한다.

## Reference-level Specification

### 1. 문법 — RFC-0002 §Full grammar 갱신 (치환 후 최종 텍스트)

RFC-0049가 정한 `StepLine ::= Verb Word* EOL`은 그대로다. 그 위에, 저장소 동사가 목적어 뒤에
받는 꼬리 절을 닫는다:

```
RepoStepLine   ::= ReadVerb Entity LookupClause? EOL
                 | ('update' | 'delete') Entity LookupClause? EOL
                 | ('create' | 'insert') Entity ('as' CamelName)? EOL
ReadVerb       ::= 'find' | 'read' | 'load' | 'authenticate'
LookupClause   ::= 'by' Reference
```

`Reference`는 RFC-0012 §G12.1의 생산 규칙(`CamelName ('.' CamelName)?`)이다. `by`는
렉서 키워드가 아니다 — `as`·`with`·`where`처럼 꼬리 토큰의 첫 자리에서 위치로 읽는다.
기존 `by` 토큰(`consume … by <group>`, `expose <verb> <Entity> by <field>`, `list … order
by <field>`)은 전부 다른 절 위치에 있어 충돌하지 않는다.

`ReadVerb`·`update`·`delete` 뒤의 꼬리 토큰이 비어 있지도, 정확히 `by <Reference>`도
아니면 컴파일 오류다:

```
line <N>: `<verb> <object>` accepts either no trailing words or `by <ref>`, got <tokens>
```

`create`/`insert`의 꼬리 규칙과 오류 문구(`create accepts either no trailing words or 'as
<name>', got …`)는 바뀌지 않는다 — `by`는 그 문구로 거부된다.

IR: `RepositoryCall` 노드가 선택적 문자열 필드 `lookup`을 갖는다 — 값은 참조 원문
(`"input.productId"`). `by`가 없으면 필드 자체가 없다 — `by` 없는 프로그램의 IR은 이 RFC
이전과 바이트 단위로 같다. `schemas/lir.schema.json`의 `nodeRepositoryCall.lookup`
(`type: string`, `required` 아님)이 이를 닫는다.

### 2. 정적 검사 — RFC-0012 §G12.2 / §G12.5 갱신 (치환 후 최종 텍스트)

**§G12.2 (RFC-0048 §4의 최종 텍스트 위에).** 다섯 이름공간의 규칙은 이 개정이 손대지
않는다. 단일 행 바인딩의 **바인딩 값**은 "저장소가 그 read의 키 아래에서 돌려준 행"이다 —
`by <ref>`가 있는 read는 §3이 파생한 키 아래의 행을, 없는 read는 지금처럼 payload `id` 키
아래의 행을 바인딩한다. 바인딩 이름(엔티티 선언 이름의 camelCase)과 "마지막 쓰기가 이긴다"는
그대로다. `update`/`delete`는 `by`가 있어도 바인딩하지 않는다.

**§G12.5 (RFC-0030 §3의 최종 텍스트 위에).** ⓐⓑ 행과 본문은 그대로다. ⓒ 행을 아래로
치환한다:

| # | 검사 | 어긋났을 때 |
|---|------|-------------|
| ⓒ | 이 워크플로가 그 Entity를 `read`/`query`로 부르거나, `create ... as <binding>`으로 그 Entity의 행을 만든다. 조회 키 `by <binding>.<field>`도 같은 검사를 받는다 | 컴파일 실패 |

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

### 3. 키 파생 — 모드 A 런타임

`RepositoryCall`의 실행 키:

1. `lookup`이 없으면 `row_key(entity_id, payload)` — 이 RFC 이전과 같다.
2. 있으면 `value = resolve_reference(lookup, payload, bindings, caller)`(가드가 쓰는 그
   해석기, RFC-0012 §G12.1–G12.4).
3. `value`가 없으면(`None`) 그 스텝은 실패한다 — 실패 이유는
   `repository <entity_id>: lookup key '<ref>' resolved to no value`. `"-"` 센티넬 키로
   떨어지지 않고, 어떤 행도 읽거나 쓰지 않는다.
4. 있으면 키는 `row_key(entity_id, {"id": value})` — 문자열이 아니면 `row_key`가 payload
   `id`를 문자열화하는 방식 그대로(`7` → `entity.stock#7`).

같은 키가 쓰기에도 쓰인다:

- `update`/`delete … by <ref>`는 그 키로 `execute`한다(영향 행 수를 돌려준다).
- `by`로 읽어 바인딩한 행에 대한 `set`/`format`의 `persist`는 **그 read가 쓴 키** 아래에
  쓴다 — payload `id`로 다시 계산하지 않는다. `create ... as`로 만든 행은 지금처럼 payload
  `id` 키에 쓴다.
- 낙관적 버전(RFC-0032, issue #174의 `observed_version` 전진)은 키와 무관하게 그대로다 —
  한 실행에서 조회 키로 읽은 행에 `set`+`update`를 두 번 해도 둘 다 성공한다.

드라이버 계약: `execute(entity_id, operation, key)`가 인터페이스 전부다. 키가 어디서
왔는지는 인터프리터의 일이다 — `RepositoryDriver` SPI와 `RepositoryDriverTCK`는 바뀌지
않는다.

### 4. 시드 규칙

기본 시드 정책(`repo_policy.default_rows`)의 **어느 엔티티를 시드하느냐**(issue #174: 문서
순서상 첫 read/create가 read인 엔티티)는 바뀌지 않는다. **어느 키 아래 두느냐**만 바뀐다:

- 그 엔티티의 첫 read가 `by input.<field>`이면 시드 행을
  `row_key(entity_id, {"id": payload[<field>]})` 아래 둔다. 행 내용은 여전히 payload의
  복사본이다. payload에 그 필드가 없으면(값이 없으면) 그 엔티티는 **시드하지 않는다** —
  `entity#None` 같은 키도, payload `id` 키로의 대체도 없다. 그 read는 §3의 3번
  `RunError`로 실패하고, 영속 저장소에도 떠돌이 행이 남지 않는다.
- 그 밖의 경우(`by` 없음, bare·`caller.*`·네트워크 결과·바인딩 참조)는 지금처럼 payload
  `id` 키다. 특히 **바인딩 참조 조회(`by order.productId`)는 기본 정책이 시드할 수 없다** —
  그 행은 실제 저장소, spec `given`, 또는 같은 워크플로의 앞선 `create`에서 와야 한다.

`fake` 백엔드로 돈 `lnpl run`/서빙된 워크플로, 그리고 `empty repository` 없는
spec/diff 케이스는 모두 `default_rows`로 시드하므로 이 규칙을 그대로 물려받는다
(이슈 #197 — 영속 백엔드(`sqlite:`, 또는 `lnpl.drivers`로 등록된 드라이버)에는
이 시드가 걸리지 않는다: 첫 읽기가 행을 못 찾으면 그 스텝이 실패하고, 영속
저장소에도 떠돌이 행이 남지 않는다). spec의 인덱스 다중 행 `given`
(`row_key=str(i)`, RFC-0025 §8)은 `list`의 시드이며 `by`로 지목할 수 없다.

### 5. mode A/B 등가 — RFC-0016 §5 갱신 (치환 후 최종 텍스트)

RFC-0051 §5의 최종 텍스트에 "조회 키" 행을 더한다:

> | 관측 클래스 | 판정 |
> |---|---|
> | 실행 순서 + i44 `skips` | **반드시 일치** — 시간 비교는 기존 i64 파라미터 채널을 탄다 |
> | 정책 결과(status/attempts) | **반드시 일치** |
> | 관측 신호(effects) | 불변 — 시간 문법은 새 effect를 만들지 않는다 |
> | 마스킹 | 불변(i43) |
> | 스케줄 트리거 | **비교 대상 아님** — 워크플로 스텝을 만들지 않아 두 모드 모두 관측할 것이 없다 |
> | Money 가드 | **비교 대상 아님** — 모드 B가 빌드를 거부한다(RFC-0051). 차동 하네스는 거짓 EQUIVALENT 대신 기록된 예외로 거부한다 |
> | Money `set` | 기존 행 그대로 — 할당이 만든 값은 허용된 차이다(RFC-0015 §5). EQUIVALENT는 "그 이름의 Assignment 효과가 있었다"만 뜻한다 |
> | 조회 키(`by <ref>`) | **비교 대상 아님** — 모드 B가 빌드를 거부한다(RFC-0052). 차동 하네스는 거짓 EQUIVALENT 대신 기록된 예외로 거부한다 |
> | 명령 선택(subi/cmpi 형태) | 허용된 차이 |
>
> 등가 주장의 범위: "시간 값이 두 모드에서 같은 i64로 인코딩되고, 같은 스텝 집합과 같은
> status를 낸다." **스케줄의 실제 발화는 어느 모드도 관측하지 않으므로 등가 주장에
> 포함하지 않는다.** Money 가드나 조회 키를 가진 워크플로는 등가 주장 밖이다 — 두 모드를
> 비교하지 않는다.

### 6. 모드 B — RFC-0012 §G12.6 갱신 (치환 후 최종 텍스트)

RFC-0012 §G12.6의 두 문단은 그대로다. 그 뒤에 한 문단을 더한다:

> 모드 B의 저장소 판정(read가 행을 찾는가, create가 충돌하는가)은 "한 실행은 payload
> 하나를 가지므로 엔티티 E의 모든 호출이 같은 키를 가리킨다"는 단일 키 투영에 기댄다.
> 조회 키(RFC-0052)는 그 투영을 깨므로, 워크플로 안의 어떤 `RepositoryCall`이든
> `lookup`을 가지면 모드 B는 그 워크플로를 **빌드하지 않는다** — MLIR을 내기 전에
> `BackendError`로 거부한다:
>
> ```
> step <step>: <entity_id> uses a lookup key (by <ref>), which the single-key seed projection cannot model (RFC-0052 §Mode B) — run it in mode A
> ```
>
> `lnpl build --backend`와 `lnpl diff`는 이를 `backend error: …`(rc=4)로 보고한다.
> 차동 하네스(`differential.verify`)는 툴체인 확인 **전에** 같은 워크플로를
> `DifferentialError`(기록된 예외, RFC-0052 §Mode B)로 거부한다 — 비교를 수행하지 않으며
> 거짓 EQUIVALENT를 내지 않는다. `by`가 없는 워크플로의 모드 B 동작은 바뀌지 않는다.

### 7. Compatibility

- **`by` 없는 프로그램.** IR은 바이트 단위로 같고(`_node`가 `lookup=None`을 떨어뜨린다),
  런타임 키·시드 키·모드 B 출력도 같다. 여섯 골든 쿼텟은 바뀌지 않는다.
- **꼬리 단어 거부.** 새 `LowerError`가 거부하는 기존 프로그램은 없다 — 코퍼스 조사
  (`examples/*.lnpl` 저장소 동사 10줄, `impl/tests/*.py` 픽스처)에서 read/update/delete 뒤에
  꼬리 단어를 가진 곳은 조용한 버림을 고정하던 테스트 픽스처 하나뿐이며, 그 테스트는 거부를
  단언하도록 다시 쓰였다.
- **단일 키 불변식의 완화.** RFC-0015 §Alternatives의 "한 실행은 payload 하나를 가지므로
  엔티티 E의 테이블에는 행이 최대 하나다"는 `by`를 쓰지 않는 엔티티에 대해 여전히 참이다.
  `by`를 쓰는 워크플로에서는 엔티티마다 키가 다를 수 있다 — 그래서 모드 B는 그 워크플로를
  거부한다(§6). 그 문단이 논증하는 집계 기각은 이 RFC와 무관하게 그대로다.
- **바뀌지 않는 표면.** `wsgi`의 `GET /<svc>/<entity>/{id}`는 이미 URL의 id 값을 키로
  쓰므로 그대로다. `lnpl migrate`는 저장된 키로 다시 읽으므로 그대로다(`create`의 키가
  바뀌지 않는다). OpenAPI는 경로·파라미터를 더하지 않는다 — 조회 값은 요청 payload에서
  온다. 드라이버 SPI·TCK는 그대로다(§3).
- **관찰(이 RFC가 고치지 않음).** Draft RFC-0049는 `Updates: RFC-0002 §Full grammar`를
  선언하지만 RFC-0002 머리에는 RFC-0049를 가리키는 `Updated-by:` 줄이 없다. RFC-0007
  §2.2 규칙 6(Draft는 Accepted 시점에 효력)에 따르면 결함이 아니라 예정된 상태다 — 이
  RFC도 같은 이유로 대상 RFC를 편집하지 않는다.

## Examples

### 골든 시나리오 "Login" (RFC-0007 §6)

골든 시나리오는 `authenticate`에 꼬리 절을 쓰지 않는다. 이 RFC 뒤에도
`examples/login.lnpl`의 IR과 모드 B 출력은 바이트 단위로 같다.

### 골든 인접 예제 — s1 주문과 재고 차감 (RFC-0007 §6, 골든이 다루지 않는 기능)

F-3/F-6을 재현하는 프로그램이다. 커밋되는 예제 파일이 아니라 이 RFC 본문의 설계
예시다.

```lnpl
capability postgres

entity Product
    field
        id Text
        name Text

entity Stock
    field
        id Text
        productId Text
        onHand Integer

entity Order
    field
        id Text
        productId Text
        qty Integer

service OrderPlatform
    policy
        retry 0

workflow PlaceOrder
    find product by input.productId
    find stock by input.productId
    set stock.onHand to stock.onHand - input.qty
    update stock by input.productId
    create order as newOrder
```

저장소에 `Product P1`과 `Stock{productId: P1, onHand: 5}`가 둘 다 `P1` 키 아래 있을 때
(`entity.product#P1`, `entity.stock#P1`):

| 실행 | payload | 결과(저장소에서 다시 읽은 값) |
|------|---------|--------------------------------|
| 1 | `{id: O1, productId: P1, qty: 2}` | `completed` — `entity.order#O1` 생성, `entity.stock#P1`의 `onHand == 3` |
| 2 | `{id: O2, productId: P1, qty: 3}` | `completed` — `entity.order#O2` 생성(충돌 없음), `onHand == 0` |

이 RFC 이전에는 상품·재고가 `entity.product#O1`/`entity.stock#O1`에서 조회되고, 실행 2의
주문 생성은 실행 1과 같은 키 공간을 두고 다투며, `onHand`는 줄지 않았다.

### 컴파일 거부 — `by` 이외의 꼬리 단어, `create … by`

<!-- lnpl-check: skip — 거부되는 형태를 보이는 예시다: `update … as x`와 `create … by`는 이 RFC §1이 컴파일 오류로 규정한다 -->
```lnpl
workflow Broken
    update stock as x
    create order by input.productId
```

첫 줄은 ``line <N>: `update stock` accepts either no trailing words or `by <ref>`, got
('as', 'x')``로, 둘째 줄은 기존 `create` 문구로 거부된다.

## Alternatives

### 필드 술어 조회 (`find product by sku == input.sku`) (보류)

키가 아닌 필드로 행을 찾는 형태다. F-3/F-6은 키 값 하나로 충분하고(이슈의 예시 자체가
`find product by input.productId`), 필드 술어는 0행·다행 결과의 의미, 드라이버 SPI의
`query` 다음 버전 있는 재조회(또는 새 SPI 메서드 — 외부 드라이버 전부의 계약 추가)를
요구한다. §Open Questions 1로 미룬다.

### 모드 B 예측을 `input.<field>`에 대해 확장하는 안 (이번에는 기각)

`input.<field>` 조회는 문서+payload에서 키가 유도되므로 모드 B의 read-found/create-conflict
예측을 넓힐 수 있다. 그러나 바인딩 참조 조회에는 여전히 거부가 필요하고, 두 경로를 둔 채
기본 시드와 `--no-row` 양쪽의 일치 테스트를 갖추는 비용이 크다. RFC-0050·RFC-0051이 세운
"거부 + 기록된 예외" 모양을 따른다.

### `create`에도 `by`를 여는 안 (기각)

만들어진 행의 키는 payload `id`로 남는다(이슈 #175 Gate-1 판정). 자연 키로 만드는 문제는
§Open Questions 2다.

## Open Questions

1. 필드 술어 조회(`by <field> <op> <ref>`)와 그 0행·다행 의미.
2. `create`의 자연 키 — 새 행을 payload `id`가 아닌 키로 만드는 표기.
3. 다행 일치 — 키 조회는 행 하나 또는 없음만 답한다. 여러 행을 지목하는 조회가 필요한가.
4. 시드 규칙의 확장 — bare 참조(`by productId`)도 `input.<field>`처럼 payload에서 유도되므로
   같은 시드 키 규칙(§4)을 받을 수 있다. 이번에는 `input.<field>`만 연다.

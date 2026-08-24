# RFC-0030: `create` 결과 바인딩과 payload 시드

## Status

- Status: **Accepted** (RFC-0030, 2026-08-24)
- Updates: RFC-0012 §G12.2 (RFC-0025 §5, RFC-0027 §4가 이미 갱신한 절 — 이
  개정은 그 절의 최종 텍스트 위에 `create`의 바인딩 규칙만 고친다), RFC-0012
  §G12.5 (ⓒ 조건에 "또는 `create ... as`로 만든다"를 더한다)

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목하고, 규칙 5(연쇄 갱신)에 따라
RFC-0012 §G12.2를 이미 갱신한 RFC-0025 §5·RFC-0027 §4도 함께 지목한다 —
G12.2의 효력 있는 텍스트는 RFC-0012 원문이 아니라 RFC-0027 §4에 있으므로,
`create`의 바인딩 규칙만 고치는 이 개정은 셋 다 지목해야 어느 텍스트가
이기는지 기계적으로 확인할 수 있다. §G12.5는 원문 그대로다 — RFC-0025·
RFC-0027 어느 쪽도 그 절을 갱신하지 않았다.

번호가 0030인 이유: 0029까지 점유됐다(RFC-0029, t100). RFC-0007 §3은 번호
재사용을 금지한다.

## Motivation

`create`가 만든 행은 실행 스코프에 들어오지 않는다 — RFC-0012 원문의 규칙
그대로다. 실측(이슈 #97):

```
$ lnpl compile p5_setcreate.lnpl
compile error: workflow Build: assignment 'set report.total to 1' assigns to entity.report,
but this workflow never reads it — no binding can ever exist (read it first with ...)
```

sqlite에 남는 행은 `{"id": "entity.order#3f25..."}` — 키만 있는 뼈대 행이다.
주문 행에 quantity도 total도 없다. `* /` 산술(RFC-0028)·`derived`
필드(issue #95)가 들어와도, 계산한 값을 생성 행에 넣을 곳이 없으면 의미가
없다.

이 규칙은 RFC-0012 시점에 create-후-쓰기 수요가 없었기 때문이지 원리적
제약이 아니다 — RFC-0012 §G12.2 원문이 이미 "행이 아니라 영향 행 수를
돌려주므로 바인딩할 행 내용이 없다"고 이유를 적어 두었다. `create`는
호출자가 준 행 내용(payload)을 그대로 들고 있으므로, 그 이유는 `create`에는
더 이상 성립하지 않는다.

타 생태계에는 선례가 없다: SQL `INSERT ... RETURNING`, JPA `persist()` 후
관리 엔티티, Rails `Model.create`가 인스턴스 반환 — "생성했는데 만질 수
없다"는 모델을 쓰는 곳이 없다.

## Guide-level Explanation

`call <target> as <name>`(RFC-0027)이 이미 확립한 결과 바인딩 표기를
저장소 동사로 확장한다:

```lnpl
create order as newOrder
set newOrder.total to product.price * input.quantity
set newOrder.placedAt to input.now
respond newOrder.id newOrder.total
```

1. `create <명사> as <이름>` — 생성 행이 `<이름>`으로 실행 스코프에
   바인딩되고, `set`(RFC-0015)·`format`(issue #94)·`respond`(issue #96)의
   대상이 된다. persist 경로는 기존 Assignment flush와 동일 — `drivers.py`는
   손대지 않는다.
2. `as` 없는 `create`는 **컴파일 표면에서 현행 유지**다 — RFC-0027이
   §Alternatives 2에서 자동 바인딩을 기각한 것과 같은 이유다: 이름 충돌
   검사에는 명시적 의도가 필요하고, 컴파일된 IR 문서는 바이트 동일해야
   한다(§1 — `result` 필드가 붙지 않고, 스코프에도 들어가지 않는다).
3. **payload 시드**: 생성 시점에 payload의 동명 필드(`derived` 제외)를
   초기값으로 복사한다 — "뼈대 행" 문제의 기본 해소이며, `as` 유무와
   무관하게 적용된다. `as` 바인딩은 그 위에 서버 계산 값을 얹는 수단이다.
   **이것은 `as` 없는 `create`의 런타임 관측(저장된 행 내용, 그 행을
   flush하는 persist 호출)이 이 RFC 이전과 달라진다는 뜻이다** — 2번이
   보장하는 바이트 동일성은 **컴파일 산출물(IR 문서·스코프 편입 여부)**에
   한정되고, 저장소에 쓰이는 행 내용까지 포함하지 않는다. 이 구분은 이슈
   #97 문면의 §2(컴파일 표면)와 §3(payload 시드)이 서로 다른 것을 말하고
   있다는 점을 명시적으로 확정한다 — §3이 "뼈대 행 문제의 기본 해소"라고
   적은 것 자체가 `as` 없는 `create`의 저장 결과가 바뀐다는 전제다. 이
   구분이 없으면 2번과 3번이 서로 모순되는 것처럼 읽힌다.
4. `insert`(RFC-0026의 `create` 근의어)도 같은 규칙을 받는다 —
   `VERB_LEXICON`에서 `create`와 같은 `operation`을 공유하기 때문이다.

이미 학습된 같은 표기(`as`)의 재사용이라 새 문법 표면이 0이고, "쓰려면
먼저 읽어라"는 §G12.5의 기존 규칙 문면에 "또는 만들면서 이름을 붙여라"가
자연스럽게 추가된다.

## Reference-level Specification

### 1. 문법 — RFC-0027 §2 표기 재사용, `create`/`insert`로 확장 (D1)

`create`/`insert` 스텝 줄의 객체 뒤 나머지 토큰(`rest`)이 정확히 `as
<name>` 형태면 그 결과를 바인딩한다. `update`/`delete`는 `rest`를 계속
무시한다 — 이 개정이 넓히는 것은 `create`뿐이며, RFC-0012 §G12.2의
"`update`·`delete`는 바인딩하지 않는다" 규칙은 그대로 남는다(영향 행
수만 돌려주므로 바인딩할 행 내용이 없다는 이유가 그 둘에는 여전히
성립한다).

RFC-0027 §2의 두 정적 거부를 그대로 재사용한다 — 새 검사를 발명하지
않는다:

| # | 검사 | 어긋났을 때 |
|---|------|-------------|
| ⓐ | `<name>`이 camelCase다(RFC-0012 §G12.1의 `Reference` 형태 요구) | 컴파일 실패 |
| ⓑ | `<name>`이 어느 선언된 Entity의 바인딩 이름과도 겹치지 않는다 | 컴파일 실패 |

`as` 뒤에 이름이 없거나, `as`가 아닌 다른 토큰이 오면 마찬가지로 컴파일
실패다(RFC-0027 §2의 "trailing 토큰" 거부와 같은 모양).

### 2. 실행 스코프 — RFC-0012 §G12.2 갱신 (치환 후 최종 텍스트) (D2)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0012 §G12.2(RFC-0027 §4가 이미
갱신한 최종 텍스트) 중 **바인딩 목록에 네 번째 갈래를 더하고 `create`
행만 고친** 치환 후 최종 텍스트다. **단일 행 바인딩**·**RowSet
바인딩**·**네트워크 결과 바인딩**의 규칙은 그대로다(이 개정이 손대지
않는다).

#### G12.2 무엇이 바인딩되는가

이 실행에서 완료된 `RepositoryCall`은 그 `operation`에 따라, 완료된
`NetworkCall`은 `result` 필드의 유무에 따라 네 이름공간 중 하나에
바인딩을 남길 수 있다. 한 엔티티는 최대 단일 행 바인딩 1개 + RowSet
바인딩 1개를 동시에 가질 수 있다(RFC-0025 §5). 네트워크 결과 바인딩과
**생성 결과 바인딩**은 엔티티 자신의 바인딩 이름이 아닌, 저자가 이름
붙인 네 번째 이름공간이며, 단일 행 바인딩과 같은 문법 위치
(`<binding>.<field>`)를 쓴다 — 그래서 이름이 겹칠 수 없다는 것이
lowering 시점의 정적 거부다(RFC-0027 §2, §1로 확장).

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

### 3. §G12.5 갱신 — ⓒ 조건에 생성 결과 바인딩을 더한다 (D2)

RFC-0007 §2.2 규칙 4에 따라, RFC-0012 §G12.5(원문 그대로, 이전 어느
개정도 손대지 않은 절)의 표 ⓒ 행을 아래로 치환한다. ⓐⓑ 행과 본문은
그대로다.

| # | 검사 | 어긋났을 때 |
|---|------|-------------|
| ⓒ | 이 워크플로가 그 Entity를 `read`/`query`로 부르거나, **이 스텝
  자신이 `create ... as <binding>`으로 그 Entity의 행을 만든다** | 컴파일
  실패 |

"쓰려면 먼저 읽어라"였던 유일한 해법에 "또는 만들면서 이름을
붙여라"가 더해진다 — G12.4의 "바인딩이 아직 없다"로 흡수되어 조용히
거짓이 되는 것을 막는다는 원래 취지(ⓒ가 없으면 벌어지는 일)는 그대로
지켜진다.

### 4. payload 시드 (D3)

생성 시점에, 그 Entity가 선언한 필드 중 `derived`가 아닌 것마다:
payload가 동명 키를 가지면 그 값을 새 행의 초기값으로 삼는다. payload에
없는 필드는 시드하지 않는다(생성 직후 값이 없는 채로 남는다 — 이전과
같다). `derived` 필드는 issue #95의 규칙대로 payload에서 절대 시드하지
않는다 — derived는 서버 계산 전용이고, `create` 시점에 그 계산이 아직
실행되지 않았을 수 있다.

시드는 **`as` 유무와 무관하게 적용**된다 — "뼈대 행" 문제 자체가 `as`
와 별개이기 때문이다. `as`는 그 위에 서버 계산 값을 얹는 **수단**이지,
시드가 켜지는 **조건**이 아니다.

`drivers.py`는 손대지 않으므로(§5) — `execute("create", ...)`는 여전히
키만 있는 뼈대 행을 만들고, 시드된 값은 그 직후 별도의 `persist` 호출
하나로 얹힌다. 그래서 `as` 없는 `create`도 — payload가 그 Entity의
비-`derived` 필드와 동명 키를 하나라도 가지면 — 이 RFC 이전에는 없던
`persist` 호출 하나를 관측 가능하게 만든다(§Guide-level Explanation
2번의 범위 확정 참고). 시드할 것이 전혀 없으면(동명 payload 키가 하나도
없으면) 이 `persist` 호출 자체를 생략한다 — 빈 델타를 위해 저장소를
한 번 더 때리지 않는다.

### 5. persist 경로 (D4)

`set`/`format`이 생성 결과 바인딩에 쓰는 경로는 §G12.2가 이미 규정한
단일 행 바인딩의 Assignment flush 경로와 동일하다(RFC-0015) —
`drivers.py`는 손대지 않는다. 생성 직후의 행은 읽기를 거치지 않고
태어나므로 관측된 `_version`이 없다(issue #92의 조건부 쓰기는 "읽은
뒤 쓴다"는 전제 위에 있다) — 이는 t92가 이미 다루는, 읽지 않고 쓰는
모든 쓰기와 같은 경로이며, `create`가 새로 여는 문제가 아니다.

### 6. IR 스키마 (D6)

`RepositoryCall`에 선택 필드 `result: string`을 더한다 —
`NetworkCall.result`(RFC-0027 §2)와 같은 모양, `required`에는 넣지
않는다. `operation`이 `"create"`가 아닌 `RepositoryCall`에 `result`가
있어도 스키마 수준에서는 거부하지 않는다 — 그 거부는 §1의 lowering
시점 검사(`update`/`delete`가 `rest`를 무시하므로 애초에 `result`
필드가 있는 노드를 만들지 않는다)가 이미 한다.

## Examples

### 골든 인접 예제 — 주문 생성과 즉시 응답

```lnpl
entity Order
    field
        id UUID
        quantity Integer
        total Money
        placedAt DateTime

workflow PlaceOrder
    create order as newOrder
    set newOrder.quantity to input.quantity
    respond newOrder.id newOrder.quantity
```

`payload = {"id": "o-1", "quantity": 3, "total": 12}`로 실행하면:
생성 직후 `newOrder`는 payload 시드로 `{"id": "o-1", "quantity": 3,
"total": 12}`를 담고, `set`이 `quantity`를 갱신하고, `respond`가
`newOrder.id`/`newOrder.quantity`를 응답으로 낸다 — `find order`로 먼저
읽을 필요가 없다.

### 컴파일 거부 — 이름 충돌

```lnpl
create order as order
```

→ `line N: `as order` collides with entity Order's single-row binding
name — a result binding cannot share a name with it (RFC-0027 §2)`

### 컴파일 거부 — `as` 없는 생성 행에 쓰기 (회귀 확인)

```lnpl
create order
set order.total to 1
```

→ 이전과 동일한 문면: `assignment 'set order.total to 1' assigns to
entity.order, but this workflow never reads it — no binding can ever
exist, so there is nothing to assign to (read it first with one of
`authenticate` / `load` / `find` / `read`, or create it with `as` if
this step creates it; `set` writes only to a row this workflow read or
created)` — 메시지 끝의 "또는 만들면서 이름을 붙여라" 절만 §3의 새
안내로 덧붙는다.

## Alternatives

| # | 대안 | 기각 이유 |
|---|------|-----------|
| 1 | `as` 없는 `create`도 자동으로 결과를 바인딩한다 | RFC-0027 §Alternatives 2가 `call`/`request`에 대해 이미 기각했다 — 이름 충돌 검사에는 명시적 의도가 필요하고, 자동 바인딩은 기존 문서를 바이트 동일하지 않게 만든다. 저장소 동사로 확장한다고 그 논리가 바뀌지 않는다 |
| 2 | payload 시드를 `as`가 있을 때만 적용한다 | 이슈 #97의 문제 자체("뼈대 행")가 `as`와 무관하다 — `as` 없는 `create`도 지금 당장 값 없는 행을 남긴다. `as`로만 시드를 게이팅하면 대부분의 `create` 호출(아직 `as`로 옮겨지지 않은)이 계속 뼈대 행을 만들어, 이 RFC가 풀려는 문제의 절반만 푼다. 실측: 이 대안을 택하면 `create`가 저장소를 때리는 횟수와 저장된 행 내용이 이 RFC 이전과 완전히 같아지지만, `impl/tests/test_driver_contract.py`의 `AssignmentFlushTargetTest` 두 케이스가 정확히 그 이유로 검사하는 대상(`create order`가 만든 행에 `quantity`가 실제로 시드됐는지)이 애초에 존재하지 않게 된다 — §Guide-level Explanation 2번이 확정한 "바이트 동일은 컴파일 산출물에 한정된다"는 구분을 받아들이는 쪽을 택했다 |
| 3 | `update`/`delete`에도 같은 `as` 표기를 연다 | 이슈 #97의 요구 범위 밖이다. `update`/`delete`는 행이 아니라 영향 행 수를 돌려주므로(§G12.2 원문의 이유) 바인딩할 새 행 내용이 없다 — `create`처럼 payload를 그대로 담아 만들 새 행이 없다는 점이 다르다. 필요해지면 별도 RFC가 그 경우의 바인딩 값이 무엇인지(변경 전 행? 변경 후 행?)부터 정해야 한다 |
| 4 | `RepositoryCall.execute()`의 드라이버 계약을 넓혀 `create`가 payload 행을 직접 받는다 | `drivers.py`는 t92·t102 소유이고, 이 이슈의 범위 밖이다. interp의 바인딩 계층(생성 직후 `persist`로 시드값을 flush)이 드라이버 계약을 바꾸지 않고 같은 결과를 낸다(§5) |

## Open Questions

- `update ... as <name>`으로 갱신 후 행을 바인딩하는 수요가 나오면,
  바인딩 값을 갱신 전/후 어느 행으로 할지부터 별도 RFC가 정해야 한다 —
  이 RFC는 그 질문을 열어만 두고 답하지 않는다(Alternatives 3).
- payload에 없는 필드가 많은 대형 Entity를 `create ... as`로 만든 뒤
  `respond`가 그 필드를 참조하면 어떤 값이 응답에 실리는지(부재 그대로
  전달? 오류?)는 `respond`(RFC-0012 §G12.4의 "바인딩은 있으나 행에 그
  필드가 없다" 행)의 기존 규칙이 이미 답한다 — 이 RFC가 새로 여는
  질문이 아니므로 별도로 다루지 않는다.

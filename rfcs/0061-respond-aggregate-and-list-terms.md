# RFC-0061: `respond`의 이름 붙인 집계 항과 목록 항

## Status

- Status: Draft
- Updates: RFC-0025 §Reference-level Specification/5 (RFC-0048 §Reference-level
  Specification/4가 이미 갱신한 절 — 그 개정은 RowSet 바인딩 규칙을 그대로 두고
  다섯 번째 이름공간만 더했다. 이 개정은 RowSet 바인딩 항목의 "집계(§2)로만
  소비된다" 한 문장만 고친다)

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목하고, 규칙 5(연쇄 갱신)에 따라 이미
갱신된 절은 대상과 **직전 갱신 RFC를 모두** 지목한다. RowSet 바인딩의 효력 있는
규칙은 RFC-0025 §5에 있다 — RFC-0027 §4, RFC-0030 §2, RFC-0048 §4는 G12.2를 다시
쓰면서 "RowSet 바인딩의 규칙은 RFC-0025 §5 그대로"라고 적었다. Draft이므로 대상
RFC에 `Updated-by:` 포인터를 달지 않는다(Accepted가 되는 시점의 일이다).

`respond` 자체를 규정한 RFC는 없다 — 이슈 #96에서 RFC 절차 없이 들어왔고, 구현의
주석은 "issue #96, D1/D3/D6"만 인용한다. 그래서 지목할 `respond` RFC 절이 없으며, 이
RFC가 `respond`의 첫 공식 명세다. 이슈 #96의 현행 규칙(평면 `<binding>.<field>` 목록,
Password 참조 거부, OpenAPI 200 스키마 유도)은 바꾸지 않고 그 위에 두 항을 더한다.

번호가 0061인 이유: 0060까지 이 브랜치에서 점유됐거나(0055–0060) 병행 실행에
배정됐다(0053, 0054). RFC-0007 §3은 번호 재사용을 금지한다.

언어 워킹네임은 **LNPL**(소스 확장자 `.lnpl`)이다.

## Motivation

2026-10-02 QA(main `c5e1679`, 이슈 #210)에서 조회 전용 엔드포인트가 답을 돌려줄
방법이 없었다. `respond`는 단일 행 바인딩의 필드만 받고, `list … where`가 채운
RowSet은 집계 표현식으로만 소비된다(RFC-0025 §5). 그래서 "이 고객의 주문 수"를
돌려주려면 답을 담을 행을 **만들어 저장**해야 했다.

```
workflow OrderStats
    create orderstats as s
    list order where customerId == input.customerId
    set s.orderCount to count order
    respond s.orderCount
```

- 읽기 요청이 저장소에 행을 쓴다. 같은 요청의 두 번째 호출은 409다(`create`
  충돌).
- 호출마다 새 id를 보내면 통과하지만, 조회할 때마다 통계 행이 하나씩 쌓인다.
- 조건이 붙은 목록("이 고객의 주문 목록")은 HTTP로 돌려줄 길이 아예 없다 —
  `expose list`(이슈 #99)의 GET은 조건을 받지 않는다.

Command Query Separation(조회는 관측 가능한 상태를 바꾸지 않는다)과 HTTP의
안전한 메서드 규칙에 따르면, 통계·목록 응답은 몇 번을 불러도 같은 답이어야 한다.
RFC-0025와 이슈 #96 사이에 "집계 결과를 응답에 싣는 경로"가 빠져 있었을 뿐,
어느 RFC도 그 경로를 기각한 적은 없다.

## Guide-level Explanation

`respond` 줄에 두 종류의 항을 더 쓸 수 있다.

**이름 붙인 집계 항** — `<이름> as <집계> <참조>`. 집계는 이미 있는 다섯 개
(`sum`·`count`·`avg`·`min`·`max`)뿐이다. 응답에 그 이름의 평면 키로 실린다.

<!-- lnpl-check: prelude examples/checkout.lnpl -->
```lnpl
workflow OrderStatsGuide
    list order where quantity > 0 limit 50
    respond orderCount as count order totalQuantity as sum order.quantity
```

조건에 맞는 주문이 셋이고 수량 합이 6이면 응답은 다음과 같다.

```json
{"orderCount": 3, "totalQuantity": 6}
```

기존 `<binding>.<field>` 참조와 한 줄에 섞어 써도 된다. 이름은 반드시 붙인다 —
`respond count order`처럼 이름이 없으면 지금과 똑같이 "bare name" 컴파일 에러다.

**목록 항** — `respond list <binding>`. 그 RowSet을 `expose list`와 같은 봉투로
싣는다. 이 항은 줄에 혼자 쓴다(다른 참조·항과 섞지 않는다).

<!-- lnpl-check: prelude examples/checkout.lnpl -->
```lnpl
workflow BigOrders
    list order where quantity > 5 order by quantity desc limit 20
    respond list order
```

```json
{"items": [{"id": "…", "quantity": 9, "…": "…"}], "next": null}
```

- RowSet을 채우는 `list`에는 `limit`이 있어야 한다 — 없으면 컴파일 에러다. 무제한
  목록 응답은 열지 않는다.
- `next`는 언제나 `null`이다. 워크플로는 커서 입력을 받지 않고, `limit`이 이미 행
  수를 묶는다. 다음 페이지가 필요하면 `expose list`를 쓴다.
- Password 계열 필드는 기존 마스킹(`***`)을 그대로 통과한다.

두 항 모두 저장소에 **아무것도 쓰지 않는다.** 같은 요청을 두 번 보내면 두 번 다
200이다. 모드 B(`lnpl build`·`lnpl diff`)는 두 항을 쓰는 워크플로를 거부한다 —
모드 A로 실행한다.

## Reference-level Specification

### 1. 문법

`respond` 뒤의 토큰열은 다음 둘 중 하나다.

```
RespondTail := ListTerm | Item { Item }
ListTerm    := "list" Binding
Item        := Reference | AggTerm
AggTerm     := Name "as" AggFunc AggRef
AggFunc     := "sum" | "count" | "avg" | "min" | "max"
```

- 항 하나는 정확히 4토큰이다. 이름 다음 토큰이 `as`이면 집계 항으로 읽는다. 그
  외의 토큰은 지금과 같은 `Reference`다(이름 없는 `respond count order`는 `count`가
  Reference로 읽혀 기존 "bare name" 에러를 낸다 — 새 경로가 아니다).
- `Name`은 camelCase(`^[a-z][a-zA-Z0-9]*$`)다. 한 줄에서 두 번 쓰면, 또는 어떤
  엔티티의 바인딩 이름(`repo_policy.binding_name`)과 같으면 컴파일 에러다 —
  `create … as <name>`(RFC-0030 §2)의 충돌 검사와 같은 규칙이다.
- `AggFunc`가 다섯 개 밖이면 컴파일 에러다. 새 집계 함수는 없다.
- `ListTerm`은 줄에 혼자 쓴다. `list` 뒤에 바인딩이 정확히 하나가 아니거나, 다른
  `Item`과 섞이면 컴파일 에러다.

`as`가 집계 항의 구분자인 이유: `create … as`, `call … as`가 이미 "이 이름으로
묶는다"는 뜻으로 쓴다. `emit … with` 같은 별도 절을 만들면 평면 목록이라는 #96의
설계(값 하나에 이름 하나)를 깨지 않고도 쓸 수 있는 것을 굳이 둘로 나누게 된다.

### 2. 정적 검사

- 집계 항은 `set <target> to <aggregate>`와 **같은** 검사(`_check_aggregate`,
  RFC-0025 §3 / RFC-0045 §2)를 받는다 — 엔티티 존재, `count`는 엔티티, 나머지는
  필드, 필드 타입 표. 집계 대상 필드의 기본 타입을 `agg_field_type`으로 기록한다
  (RFC-0047, `count`는 기록하지 않는다).
- 앞선 가드 밖 `list`가 그 RowSet을 채우지 않으면 `aggregation-orphaned-list`
  경고를 낸다(RFC-0025 §4와 같은 코드·문구).
- 목록 항의 바인딩은 엔티티의 RowSet 이름이어야 한다. `create … as`·`call … as`
  결과 이름은 단일 행이지 RowSet이 아니므로 컴파일 에러다. 그 RowSet을 채우는
  `list`가 하나도 없으면 같은 `aggregation-orphaned-list` 경고를 낸다.
- 그 RowSet을 채우는 `list`가 **하나라도** `limit`이 없으면 컴파일 에러다 — 가드
  안의 `list`도 센다. 어느 `list`가 실제로 실행될지 정적으로 알 수 없기 때문이다.
- `guard-scoped-binding-escape`(이슈 #198) 검사는 항의 참조도 읽는다.

### 3. IR

`Response` 노드에 선택 키 둘을 더한다. 쓰지 않으면 키 자체가 없다 — 기존 형태만
쓰는 워크플로의 IR은 바이트 단위로 같다.

- `aggTerms`: `[{name, func, ref, agg_field_type?}]` (`minItems: 1`).
  `agg_field_type`은 `Assignment`의 같은 키(RFC-0047)를 같은 철자로 재사용한다.
- `listTerm`: `{binding}`.
- `refs`는 이제 선택이다(있으면 `minItems: 1`). `anyOf`로 `refs`·`aggTerms`·
  `listTerm` 중 하나 이상을 요구한다.

### 4. 응답 조립 — RFC-0025 §5 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0025 §5의 RowSet 바인딩 항목 중 마지막
항의 **치환 후 최종 텍스트**다. §5의 나머지 항목(단일 행 바인딩, RowSet 바인딩의
이름·값·마지막 쓰기 규칙)과 RFC-0048 §4가 더한 다섯 번째 이름공간은 그대로다.

> - RowSet은 **읽기 전용 소비**다 — `<binding>.<field>` 형태의 단일 필드
>   참조로도, 다른 쓰기 대상으로도 쓸 수 없다. 집계(§2)와, RFC-0061이 정한
>   `respond`의 두 항 — 이름 붙인 집계 항과 목록 항 — 으로만 소비된다.

조립 규칙:

- 성공한(`completed`) 실행에서만 조립한다. 실제로 실행된 스텝의 `Response`만
  기여한다 — 가드가 건너뛴 스텝은 기여하지 않는다. `parallel` 블록 안의
  `respond`도 순차 실행과 같은 응답을 만든다.
- 집계 항: `response[<name>]` = 그 집계의 값. `set`이 쓰는 평가기(`eval_aggregate`)
  를 그대로 쓴다 — 빈 RowSet의 `count`는 0이다. 바인딩 묶음
  `{"<binding>": {"<field>": …}}`과 나란히 평면 키로 놓인다.
- 목록 항: `response` 전체가 `{"items": [...], "next": null}`이다. 각 행은
  `mask_payload`를 그 엔티티의 뷰로 통과한다 — RowSet은 `_masked_bindings`를
  거치지 않으므로 이 호출이 이 경로의 마스킹 chokepoint다. 빈 RowSet은
  `items: []`다. 봉투가 응답 **전체**이므로 다른 `respond` 스텝이 더하는 키와
  합칠 수 없다 — 목록 항을 쓰는 워크플로의 `respond` 스텝은 그 하나뿐이어야 하고,
  둘 이상이면 컴파일 에러다.
- `next`는 언제나 `null`이다. `list … limit N`이 드라이버까지 내려가 RowSet이 N행을
  넘지 않으므로 "더 있음"을 판정할 근거가 없고, 워크플로 실행은 커서 입력을 받지
  않는다. `wsgi.paginate`를 부르면 언제나 `(rows, None)`을 돌려주는 통과 경로만
  실행된다.
- 저장소 쓰기는 0이다. `list`·집계·`respond`는 어느 것도 `create`/`persist`를
  부르지 않는다. 쓰기 없는 워크플로에 트랜잭션을 열지 않는 최적화는 이 RFC에
  넣지 않는다 — 쓰기가 0이라는 관측 결과는 그 최적화 없이도 같다.

### 5. OpenAPI

- 집계 항은 200 스키마의 최상위 평면 속성 하나다 — 타입은 `agg_field_type`의
  `TYPE_SCHEMA`(`count`는 Integer). `required`에 들고, `additionalProperties:
  false`가 그대로 전체를 덮는다.
- 목록 항은 200 스키마 전체가 `expose list` GET의 봉투다 — `items`는 그 엔티티
  스키마의 배열, `next`는 `{"type": "null"}`(§4가 `null`만 보내므로 `["string",
  "null"]`로 넓히지 않는다).

### 6. spec

`expect result <name> <op> <value>`가 집계 항을 이름으로 단언한다. bare 이름은
응답의 같은 이름 항을 먼저 보고, 없으면 지금처럼 입력 필드를 본다. 이 조회는
`spec`의 `result` 단언에만 있다 — 가드는 응답을 보지 않는다. Money 타입 항은
Money 리터럴(`3.75USD`)로 단언한다(RFC-0044 §3과 같은 비교).

### 7. 모드 B

모드 B는 두 항을 쓰는 워크플로를 거부한다. RowSet과 그 위의 집계는 RFC-0004의
네 관측 클래스 어디에도 속하지 않는다(RFC-0045 §7과 같은 이유). `lnpl build`
(`_refuse_unsupported_guards`)와 `lnpl diff`(`differential.verify`)가 같은 순서로
묻는다 — Money 가드, lookup 키, optional 가드, Text 가드, fill-source, `fail`
다음, **마지막**에. 메시지는 이 RFC 번호를 인용하고 모드 A를 권한다. 기존 형태만
쓰는 `respond`는 이 거부에 걸리지 않는다.

## Examples

골든 시나리오 "Login"(정본: `plans/rfc-suite/plan.md` §골든 시나리오)은 `respond`
항을 쓰지 않는다. RFC-0007 §6에 따라 골든을 확장하지 않고 골든 인접 예제를 보인다.

<!-- lnpl-check: prelude examples/checkout.lnpl -->
```lnpl
workflow OrderSummary
    list order where quantity > 0 limit 100
    respond orderCount as count order largest as max order.quantity
```

같은 payload로 두 번 `POST`해도 두 번 다 200이고, 저장소 행 수는 변하지 않는다.

```json
{"status": "completed", "response": {"orderCount": 2, "largest": 4}, "…": "…"}
```

`lnpl openapi`의 200 스키마:

```json
{"type": "object",
 "properties": {"orderCount": {"type": "integer", "format": "int64"},
                "largest": {"type": "integer", "format": "int64"}},
 "required": ["orderCount", "largest"],
 "additionalProperties": false}
```

spec:

```
expect
    result orderCount == 2
```

정적 거부 — `limit` 없는 목록 항:

<!-- lnpl-check: skip — 이 RFC §2가 거부하는 형태(`limit` 없는 RowSet의 목록 항)를 보이는 예시라 컴파일 에러가 정답이다 -->
```lnpl
workflow AllOrders
    list order where quantity > 0
    respond list order
```

## Alternatives

- **읽기 전용 실행 모드 플래그**(쓰기 스텝이 없으면 트랜잭션을 열지 않는다) —
  쓰기 0은 이미 구조적으로 성립한다. 관측 결과가 같은 최적화이므로 범위 밖.
- **집계 값을 가짜 바인딩 아래 중첩**(`{"stats": {"orderCount": 3}}`) — 항 이름은
  바인딩이 아니다. 평면 키 하나가 #96의 "값 하나에 이름 하나"와 맞다.
- **목록 항을 키 아래 중첩**(`{"result": {"items": …}}`) — `expose list`의 GET이
  봉투를 그대로 본문으로 쓴다. 같은 모양이어야 클라이언트가 하나의 코드로 읽는다.
- **진짜 커서**(`limit+1` 과다 조회 후 `wsgi.paginate`/`encode_cursor`) — 워크플로에
  커서 입력 문법이 없어서 만든 커서를 돌려받을 방법이 없다.
- **`refs`에 `"name=func(ref)"` 문자열로 인코딩** — 한 키에 두 문법을 섞으면 모든
  소비자가 문자열을 다시 파싱해야 한다. 선택 키 둘이 기존 IR을 바이트 그대로 둔다.
- **`spec`에서 집계 값을 바인딩에 합성 키로 주입** — 단언 경로가 실행 스코프와
  다른 스코프를 갖게 된다. 공유 해석기에 선택 인자 하나를 더하는 편이 RFC-0012의
  "가드와 expect는 한 스코프" 원칙을 지킨다.
- **모드 B 지원**(RowSet을 시드에서 정적으로 투영) — RowSet 값은 RFC-0004의 관측
  클래스가 아니다. 거부가 RFC-0045 §7의 기존 판단과 일관된다.
- **`with` 절로 매핑**(`respond with orderCount count order`) — `emit … with`의
  매핑 문법은 참조를 옮길 뿐 집계를 받지 않는다. `as`가 이미 "이 이름으로
  묶는다"는 뜻이다.

## Open Questions

없다. 그룹별 원본 행 목록은 RFC-0048 §Open Questions에 그대로 남는다 — 이 RFC는
그것을 다시 열지 않는다.

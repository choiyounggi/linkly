# RFC-0056: `fail` 동사 — 저자가 선언하는 업무 거절

## Status

- Status: Draft
- Updates: RFC-0001 §Reference-level Specification/노드 카탈로그 (Effect 표 — `Rejection` 행 신설, Behavior 표의 `WorkflowStep` 행 — children 허용에 `Rejection` 추가),
  RFC-0003 §Reference-level Specification/Execution Model (Effect 표 — `Rejection` 행 신설; RFC-0032가 직전에 갱신한 표),
  RFC-0014 §Open Questions/1

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목하고, 규칙 5(연쇄 갱신)에 따라 이미
갱신된 절은 대상과 **직전 갱신 RFC를 모두** 지목한다. 이 RFC는 Draft이므로 대상
RFC에 `Updated-by:` 포인터를 달지 않는다(Accepted가 되는 시점의 일이다).

- **노드 카탈로그(RFC-0001).** "행의 추가·삭제는 이 RFC의 개정 사항이다"라는 그 절의
  규칙대로 새 kind `Rejection`을 Effect 표에 더하고, `WorkflowStep`의 children 허용
  목록에 넣는다. Guard 행(RFC-0028, Draft RFC-0054)은 건드리지 않는다. 아래 §1이 바뀐
  두 행의 치환 후 최종 텍스트다.
- **Execution Model의 Effect 표(RFC-0003).** RFC-0032가 이 표의 `Transaction`·`EventEmit`
  행을 갱신했다. 아래 §3이 그 표 전체의 치환 후 최종 텍스트다 — RFC-0032의 두 행은
  글자 그대로 두고 `Rejection` 행 하나를 더했다.
- **RFC-0014 Open Questions 1.** "가드를 정책 게이트로 선언하는 문법(그리고 그 게이트가
  거짓일 때의 종결 의미)"을 이 RFC가 답한다. 아래 §8이 그 항목의 치환 후 텍스트다.
  RFC-0048이 RFC-0001 §Open Questions/1을 답한 것과 같은 방식이다.

지목하지 **않는** 것(모순하지 않음):

- RFC-0014 §Reference-level Specification/2와 §Alternatives. 가드 스킵의 의미와 기록
  의무는 그대로다 — 거짓 가드 아래의 `fail`은 다른 스텝과 똑같이 스킵된다. 제3의
  terminal status `rejected`는 여전히 없다(§Alternatives 2).
- RFC-0003 §Policy Enforcement. 실패 유형별 재시도 판정 표의 "요청 자체의 오류(4xx류,
  Authorization 거부, Validation 실패) → 재시도 금지" 행이 `Rejection`을 이미 덮는다.
  인터프리터가 그 행을 `Rejection`에 대해 집행할 뿐 표는 바뀌지 않는다.
- RFC-0040(이벤트 소비 계약). 그 계약의 영구 실패(E7)는 "그 외 전부"이고, `fail`은
  그 정의 안에 든다. `docs/serving.md` E7 행에 사례 하나를 덧붙일 뿐이다.
- RFC-0032(실행 경계). 롤백 규칙은 그대로이며 `fail`은 그 규칙의 새 소비자다.

## Motivation

워크플로가 업무 규칙으로 **스스로 실패할 방법이 없다**(issue #206). 재고 부족·한도
초과·잘못된 상태 전이 같은 거절은 전부 `completed` + HTTP 200으로 나간다:

```
$ lnpl run reserve.lnpl --payload p.json     # stock 1, quantity 5
workflow Reserve -> completed  (1 step(s) skipped by guard)
```

`fail out-of-stock`이나 `reject ...` 같은 낱말은 `VERB_LEXICON` 밖이라 `unknown-verb`
경고와 함께 효과 없는 서술 스텝으로 실행된다. 그 결과:

1. HTTP 클라이언트는 200 본문의 `skipped[]`를 파싱해 "이 스킵이 거절이었는지"를
   **스스로 판정**해야 한다. 상태 코드나 problem `code`로 분기할 수 없다.
2. "재고가 부족하면 실패한다"를 `spec`으로 계약할 수 없다 — `expect failed`가 FAIL한다.
3. 이벤트 소비 경로(`consume by`)의 E7(422 영구 거절)에 저자가 도달할 수단이
   `validate` 실패와 `create` 충돌뿐이다.

RFC-0014는 스킵을 관측 가능하게 만들면서 남은 원인을 Open Questions 1에 적었다 —
어떤 가드가 정책 게이트인지 **선언할** 문법이 없다. 이 RFC가 그 문법이다. 런타임이
스킵을 거절로 추측하지 않는다. 저자가 쓴 자리에서만 실패한다.

## Guide-level Explanation

`fail <code>`는 그 스텝에 도달하면 실행을 실패로 끝낸다. 가드 아래에 쓴다:

<!-- lnpl-check: skip — fragment; the full program (entities included) is in §Examples -->
```lnpl
workflow Reserve
    find product
    when product.stock < input.quantity
    fail out-of-stock
    create order
```

- 가드가 **거짓**이면 `fail` 스텝은 다른 스텝처럼 스킵되고(`skipped[]`에 기록),
  실행은 이어진다 — 지금과 같다.
- 가드가 **참**이면 실행이 `failed`로 끝난다. `failure_kind`는 `"rejected"`,
  `failure_reason`은 코드 `out-of-stock`, `failed_step`은 `fail out-of-stock`이다.
  그 전에 한 쓰기는 롤백된다(RFC-0032). `policy retry`가 있어도 재시도하지 않는다.
- `lnpl run`은 rc 1로 끝난다.
- `lnpl serve`는 **422** problem+json을 돌려주고, 그 `code`가 저자의 코드다:
  `{"status": 422, "code": "out-of-stock", "title": "the workflow rejected the request", ...}`.
- `consume by` 경로에서는 E7 — 422 `event-rejected`(영구, 릴레이는 재시도하지 않는다).
- OpenAPI의 그 operation은 `422` 응답에 코드 목록을 싣는다.
- `spec`은 새 문법 없이 계약한다:

<!-- lnpl-check: skip — fragment; this `spec` block goes under the Reserve workflow shown in §Examples -->
```lnpl
    spec
        given
            stored product stock 1
            input.quantity 5
        when
            reserve
        expect
            failed
            error reason out-of-stock
```

코드는 컴파일 시점에 검사한다. kebab-case여야 하고(`out-of-stock`, `limit-2`), 서버가
이미 쓰는 problem `code`(`not-found`, `write-conflict`, `event-rejected` …)와 같으면
안 된다. 가드 없는 `fail`은 컴파일 에러다 — 모든 실행을 실패시키는 스텝은 결함이다.

## Reference-level Specification

### 1. IR — `Rejection` 노드 (RFC-0001 §노드 카탈로그 갱신)

`fail <code>`는 `WorkflowStep` 하나와 그 유일한 자식 `Rejection` 노드 하나로
lower된다. 노드 id는 `<step id>.reject`.

```json
{"kind": "Rejection", "id": "wf.reserve.step.2.reject", "code": "out-of-stock", "line": 13}
```

`schemas/lir.schema.json`의 `nodeRejection`: 필수 `kind`·`id`·`code`, 선택 `meta`·`line`,
`additionalProperties: false`, `code`는 패턴 `^[a-z0-9]+(-[a-z0-9]+)*$`.

치환 후 최종 텍스트 — RFC-0001 Behavior 표의 `WorkflowStep` 행:

| kind | 필수 필드 | 선택 필드 | children 허용 |
|------|----------|----------|--------------|
| WorkflowStep | `name`(동사구 — 예: `validate input`) | `constraints` | Validation, BusinessRule, NetworkCall, RepositoryCall, CacheAccess, Transaction, Authorization, EventEmit, Rejection, Concurrency, Pipeline |

치환 후 최종 텍스트 — RFC-0001 Effect 표에 더하는 행(기존 6행은 글자 그대로):

| kind | 필수 필드 | 선택 필드 | children 허용 |
|------|----------|----------|--------------|
| Rejection | `code`(kebab-case 문자열 — 저자가 선언한 업무 거절 코드. 서버의 예약 problem `code`와 겹칠 수 없다) | (없음) | (없음) — 2026-10-04 신설(RFC-0056) |

`fail`이 없는 워크플로의 IR은 이 RFC 이전과 바이트 동일하다.

### 2. 문법과 컴파일 시점 규칙

`VERB_LEXICON["fail"] = ("Rejection", {})`. 목적어는 엔티티명이 아니라 코드
리터럴이므로 `respond`/`note`처럼 전용 도출(`lower._derive_fail`)로 간다.

| 입력 | 결과 |
|------|------|
| `fail out-of-stock` (가드 아래) | `Rejection{code: "out-of-stock"}` |
| `fail` (코드 없음) | `LowerError` — "`fail` needs a kebab-case code" |
| `fail out-of-stock because empty` | `LowerError` — 코드는 하나뿐이다(`create`의 trailing 단어 규칙과 같다) |
| `fail OutOfStock`, `fail out_of_stock`, `fail -x`, `fail x-`, `fail a--b` | `LowerError` — kebab-case 규칙(`lexer.KEBAB_CODE_RE`) |
| `fail not-found` 등 예약 코드 | `LowerError` — "collides with the reserved problem code" |
| `when`/`until` 가드가 소유하지 않는 `fail` — 최상위, 가드 없는 `parallel`/`pipeline` 블록 안, `repeat N` 아래(N ≥ 1이라 본문이 언제나 실행된다) | `LowerError` — "is not guarded" |

예약 코드 집합은 `lexer.RESERVED_PROBLEM_CODES`이고 `wsgi._TITLES`의 키 집합과
**같아야 한다**(양방향 동치 — 적합성 테스트가 지킨다). `wsgi`가 `lower`를 import하므로
반대 방향 import는 순환이라 표를 복제하고 테스트로 묶는다. 서버에 새 problem `code`를
더하는 변경은 두 곳을 함께 고친다.

가드 없는 `fail`을 경고가 아니라 에러로 두는 이유: 그 워크플로의 모든 실행이
실패한다. 거짓이 될 수 있는 가드는 `when`과 `until`(0라운드 가능, RFC-0014 예 2)뿐이다. 스텝을 지우거나 가드를 다는 것 말고 고칠 방법이 없으므로 컴파일을 통과시킬
이유가 없다.

### 3. 실행 의미 (RFC-0003 §Execution Model 갱신)

치환 후 최종 텍스트 — RFC-0003 Execution Model의 Effect 표(머리 문장 포함):

**Effect 실행 의미.** Effect 대분류 7종 전부의 계약은 다음 표와 같다.

| Effect kind | 실행 의미(계약) |
|-------------|----------------|
| NetworkCall | 비동기 아웃바운드 호출 = await 지점. 모든 호출에 명시적 connect timeout + request timeout 필수 — 무한 기본값 금지(타임아웃 없는 호출 하나가 pool을 고갈시킨다). 잔여 데드라인과 상관ID를 자동 전파한다. 실패 유형별 재시도 판정은 §Policy Enforcement의 표를 따른다 |
| RepositoryCall | capability 커넥션 pool을 통해 실행되는 await 지점. 커넥션 획득은 operation당 1회이며, 다른 pool 자원을 획득하기 전에 반환해야 한다(같은 pool에 대한 중첩 획득은 pool 만석 시점에 데드락 — 금지). operation별 멱등성은 §Policy Enforcement의 판정 표를 따른다 |
| CacheAccess | `get` = miss가 오류가 아니라 정상 경로인 조회(miss 시 원천 조회로 폴백). `set` = TTL 필수 — TTL 값은 Performance 제약의 `cache` 예산이 소유한다(RFC-0001 CacheAccess 행). `invalidate` = 삭제. 캐시는 성능 계층일 뿐 정합성 메커니즘이 아니다 — 캐시 불가용 시 원천으로 폴백하되 동시성 상한 안에서만(무제한 폴백 herd는 캐시 장애를 원천 장애로 만든다) |
| Transaction | 원자적 스코프 노드: children 전부 성공 시 커밋, 하나라도 실패 시 abort — 부분 쓰기는 관측되지 않는다. `isolation` 서술은 힌트이며 집행 수준은 해당 capability가 결정한다. Policy `rollback`의 보상 경계가 이 노드다(§Policy Enforcement). **Phase 1은 이 노드를 선언할 문법이 없다**(`VERB_LEXICON`이 어떤 동사도 `Transaction`으로 도출하지 않는다) — 그 공백 동안 워크플로 실행 전체가 유일한 암묵적 경계다: 실행 시작 시 열리고, 완주 시 커밋되며, 실패 시 그 실행에서 이뤄진 모든 쓰기를 롤백한다(RFC-0032). 명시적 `Transaction` 노드가 도입되면 이 암묵적 경계는 "children으로 아무 `Transaction`도 갖지 않는 워크플로"의 경계로 좁혀진다 — 지금은 모든 워크플로가 그 경우다 |
| Authorization | 소유 step의 다른 Effect보다 먼저 평가되는 게이트. **거부(deny)는 비재시도 실패다** — 같은 요청은 다시 보내도 같은 결과이므로 재시도 대상이 아니다. 검사 서비스 불가용(전송 실패)과 거부는 구분되며, 전자만 재시도 판정 대상이다 |
| EventEmit | 비동기 발행 — step의 동기 구간은 발행 요청 등록까지다. Transaction의 children으로 소유된 EventEmit은 **커밋 성공 후에만** 발행된다(롤백된 트랜잭션의 이벤트 유출 금지). Phase 1은 명시적 `Transaction` 노드가 없으므로(위 Transaction 행), 모든 EventEmit은 워크플로 실행 전체의 암묵적 경계가 그 소유자다 — 등록(`record_emission`)은 그 경계의 커밋과 함께만 durable해지고, 실행이 실패해 롤백되면 등록 자체가 저장소에 남지 않는다(RFC-0032, issue #102). 전달 보장은 at-least-once이며, 소비자가 event id로 dedupe할 수 있도록 발행마다 유일한 event id를 부여한다(발행 메커니즘의 구현은 §Open Questions ③) |
| Rejection | 저자가 선언한 업무 거절(RFC-0056). 도달하면 그 step이 실패하고 실행이 `failed`로 끝난다: `failure_kind = "rejected"`, `failure_reason` = `code`, `failed_step` = 그 step 이름. 실행이 실패했으므로 위 Transaction 행의 암묵적 경계가 그 실행의 모든 쓰기와 발행 등록을 롤백한다 — 별도 경로가 없다. **비재시도 실패다**: 가드가 이미 이 실행의 바인딩에 대해 참이었으므로 다시 시도해도 같은 결과다(Authorization 거부와 같은 이유, §Policy Enforcement "요청 자체의 오류" 행). 가드가 거짓이면 이 step은 실행되지 않으며 스킵 기록(RFC-0014 §2.4)만 남는다 |

인터프리터는 `RunError(code)`에 `failure_kind = "rejected"`를 실어 던진다 — 순차·병렬
실행 경로 모두 기존 `failure_kind` 번역 지점이 그대로 결과에 옮긴다. 재시도 판정
(`Interpreter._retryable`)은 `Rejection`을 가진 step을 재시도하지 않는다.

### 4. HTTP 매핑 — `lnpl serve`

`wsgi.map_result`의 새 행(`docs/serving.md` M8e):

| # | 조건 | 상태 | problem `code` |
|---|------|------|----------------|
| M8e | 실행 실패 ∧ `failure_kind == "rejected"` | 422 | 저자의 코드(`failure_reason`) |

- 판정은 `failure_kind`(타입)로만 한다 — `failure_reason`의 문구를 매칭하지 않는다
  (issue #113 원칙). M8a/M8b/M8c와 서로 배타적인 값이라 그 행들 사이의 순서는 결과에
  영향이 없다.
- 상태는 **모든 코드에 422**다. 코드별 409 지정은 열지 않는다(§Alternatives 1).
- `problem()`의 `title`은 `_TITLES`에 없는 코드에 대해 `"the workflow rejected the
  request"`를 쓴다. 저자 코드는 정의상 `_TITLES`에 없다(§2). 기존 코드의 `title`은
  바이트 동일하다.
- 본문에는 다른 실패 행과 같이 `failed_step`·`correlation_id`·`skipped`가 실린다.
  `detail`은 `failure_reason`, 즉 코드 자체다. 사람이 읽을 원인 문장과 다국어 메시지는
  이 RFC의 범위가 아니다.

### 5. 이벤트 소비 — `consume by`

`wsgi.map_consume_result`는 `failure_kind == "rejected"`를 **영구 실패**(E7, 422
`event-rejected`)로 분류한다. 실패 step의 Effect 목록을 보는 일시 실패(E6) 분기보다
먼저 판정한다. 같은 페이로드를 다시 돌려도 같은 거절이므로 릴레이는 재시도하지 않고,
`Retry-After`를 싣지 않으며, 멱등 claim은 finish된다(422의 기존 규칙).

### 6. OpenAPI

워크플로 operation은 그 워크플로가 도달할 수 있는 `Rejection`이 하나 이상일 때만
`422` 응답을 갖는다:

```json
"422": {"description": "the workflow rejected the request (RFC-0056): codes out-of-stock, over-limit"}
```

코드는 중복 없이 사전순이다. `fail`이 없는 operation과 문서는 이 RFC 이전과 바이트
동일하다 — 커밋된 `examples/*.openapi.json`은 바뀌지 않는다.

### 7. Mode B

Mode B는 `fail`을 담은 워크플로를 **거부**한다(기록된 면제). 그 네 관측 클래스
(RFC-0004)는 저자가 선언한 실패 코드를 싣지 않으므로, 비교하면 서로 다른 두 결과를
"같다"고 부를 수밖에 없다 — 이 RFC 이전의 `lnpl diff`는 실제로 그런 워크플로를 PASS로
보고했다.

- `backend.workflow_uses_fail(document, workflow_id)` — 도달 가능한 `Rejection`이
  있는가. 모르는 워크플로면 `BackendError`.
- `build`/`emit_mlir`(`backend._refuse_unsupported_guards`)와 `diff`
  (`differential.verify`)는 같은 순서로 묻는다: Money(RFC-0051) → lookup(RFC-0052) →
  optional(RFC-0053) → Text(RFC-0054) → **fail(RFC-0056)**. 둘 다 툴체인 확인 전에
  거부하므로 결과가 툴체인 설치 여부에 좌우되지 않는다. CLI는 두 명령 모두 rc 4.
- 메시지: `step <name>: `fail <code>` has no compiled evaluator (RFC-0056 §Mode B,
  recorded exemption) — run it in mode A` / `workflow '<id>' uses `fail` — mode B has
  no compiled evaluator for it (RFC-0056 §Mode B, recorded exemption); differential
  comparison is not attempted`.

### 8. RFC-0014 Open Questions 1 (갱신)

치환 후 최종 텍스트:

1. **"거부" 판정의 소유자.** — **해소(RFC-0056).** 저자가 `fail <code>`로 선언한
   지점만 거절이다. 그 스텝을 소유한 가드가 참이면 실행이 `failed`(`failure_kind =
   "rejected"`)로 끝나고, 거짓이면 이 RFC의 §2.4대로 스킵이 기록될 뿐이다. 런타임은
   여전히 어떤 스킵도 거절로 추측하지 않는다.

## Examples

골든 시나리오 "Login"(`examples/login.lnpl`)에는 `fail`이 없다. 이 RFC 이후에도 그
IR(`examples/login.lir.json`), OpenAPI(`examples/login.openapi.json`), 실행 결과와
serve 응답은 바이트 동일하다 — 커밋된 골든이 바뀌지 않는 것이 그 증거다. Login에
업무 거절을 더한다면 모양은 이렇다(골든 자체는 바꾸지 않는다, RFC-0007 §6):

<!-- lnpl-check: skip — fragment of the golden Login workflow; `failedAttempts` is illustrative and the golden is not changed (RFC-0007 §6) -->
```lnpl
workflow Login
    validate input
    authenticate
    when user.failedAttempts > 4
    fail account-locked
    cache user
```

골든 인접 예제 — issue #206의 `Reserve`:

```lnpl
entity Product
    field
        id UUID
        stock Integer

entity Order
    field
        id UUID
        quantity Integer

service ShopService

workflow Reserve
    find product
    when product.stock < input.quantity
    fail out-of-stock
    create order
```

| 입력 | `lnpl run` | `lnpl serve` | `consume by` |
|------|-----------|--------------|--------------|
| stock 1, quantity 5 | rc 1, `failed`, `failure_kind` `rejected`, `failure_reason` `out-of-stock` | 422, `code` `out-of-stock` | 422 `event-rejected` |
| stock 5, quantity 5 | rc 0, `completed`, `skipped[0].steps == ["fail out-of-stock"]` | 200 | 200 |

## Alternatives

1. **코드별 상태 지정(`fail out-of-stock 409`).** 기각. 409(현재 상태와 충돌)와
   422(의미상 처리 불가)의 경계는 저자마다 다르게 그어지고, 그 선택이 클라이언트 분기를
   바꾼다. 분기의 정본은 상태가 아니라 `code`다(RFC 9457). 422 하나로 시작하고, 필요가
   실측되면 별도 RFC로 연다.
2. **제3의 terminal status `rejected`.** 기각 — RFC-0014 §Alternatives가 이미 기각한
   이유 그대로다. 상태는 `completed`/`failed` 둘이고, 거절은 `failure_kind`로 구분한다.
3. **가드 스킵을 거절로 재분류.** 기각 — 캐시 적중 스킵 같은 최적화 가드를 거절로
   오분류한다(RFC-0014). 이 RFC는 저자가 쓴 자리에서만 실패한다.
4. **`fail`을 mode B 구조 트레이스의 스텝 하나로 지원.** 기각(§7). 관측 클래스에 저자
   코드를 싣는 확장이 먼저 필요하고, 그 전에 비교하면 거짓 EQUIVALENT가 난다.
5. **예약 코드와의 충돌을 이름공간으로 해소(`app:out-of-stock` 등).** 기각. 클라이언트가
   분기할 문자열에 접두사 규칙을 더 얹을 뿐이고, 컴파일 거부가 더 단순하며 같은 보장을
   준다.
6. **가드 없는 `fail`을 경고로.** 기각(§2). 모든 실행을 실패시키는 스텝을 통과시킬
   이유가 없다.

## Open Questions

없다. 범위 밖으로 명시하는 것:

- 사람이 읽을 원인 문장(Step Functions의 `Cause`)과 다국어 메시지 — 코드 하나로 시작한다.
- `otherwise` 분기(가드가 거짓일 때의 대안 스텝) — 별도 태스크가 소유한다.

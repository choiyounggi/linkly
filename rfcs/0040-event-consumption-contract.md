# RFC-0040: 이벤트 소비 계약 — `consume by`, CloudEvents 인입, 멱등/오류 분류, 레퍼런스 릴레이

## Status

- Status: **Accepted** (RFC-0040, 2026-08-27)
- Updates: 없음 — `consume by`는 `event` 선언에 새 절 하나를 더하고 `Event` IR
  노드에 선택적 필드 하나(`consume`)를 더할 뿐이다. `subscribe`(RFC 없음,
  이슈 #103)·`on <Entity> <op>`/`on schedule`(RFC-0016) 소스 절의 기존 문법·
  의미는 손대지 않는다 — 세 절 모두 같은 `event` 선언에 나란히 앉되 서로
  배타적이지 않다(§Reference-level Specification/1). `docs/serving.md`의
  M1-M19 상태코드 매핑도 고치지 않는다 — `/-/events/<slug>`는 그 표에
  없던 새 라우트이고 자기 자신의 3갈래 매핑(E1-E7)을 새로 낸다.

번호가 0040인 이유: 0039까지 점유됐다(RFC-0039, `note` 동사 — 이 RFC와 같은
직렬 체인에서 앞서 병합됨). RFC-0007 §3은 번호 재사용을 금지한다.

## Motivation

발행 쪽(`emit`/`publish` → `EventEmit` → `lnpl_outbox`, 이슈 #102)은 완성됐고
RFC-0032가 그 트랜잭션 경계를 확정했다. `event ... subscribe`(이슈 #103)도
있다 — 하지만 이건 HTTP 클라이언트에게 SSE로 **내보내는** 것이지, 이벤트가
도착했을 때 **워크플로를 실행하는** 것이 아니다. 언어 안에는 이벤트가
워크플로를 깨우는 경로가 하나도 없다:

- `POST /<svc>/<workflow>`와 `POST /-/schedules/<slug>`(이슈 #81)는 둘 다
  요청/응답이지, 이벤트 인입이 아니다.
- `event <Name> on <Entity> create|update|delete`는 **발행 소스** 선언이지
  구독 선언이 아니다.
- 브로커 바인딩은 애초에 범위 밖이다(`docs/backends.md §5`, "코어는
  drain/ack 의미론만 소유한다" — #88 원칙).

결과: linkly로 이벤트 기반 아키텍처의 **발행 절반만** 만들 수 있다. 주문
서비스가 `emit orderPlaced`를 해도 배송 워크플로가 그걸 받을 방법이 언어
안에 없다 — 외부 릴레이가 `POST /<svc>/<workflow>`를 다시 찔러야 하고, 그
릴레이가 재시도·중복·DLQ를 전부 자기 방식으로 처리한다. **계약이 언어
밖으로 샌다.**

표준 사례가 수렴하는 지점은 하나다: **at-least-once 전제 + 멱등 소비자 +
명시적 오류 분류(재시도 vs dead-letter)**. CloudEvents v1.0은 이벉 봉투를
표준화하고([blogs.pavanrangani.com](https://blogs.pavanrangani.com/event-driven-architecture-kafka-cloudevents/)),
Kafka류 at-least-once 컨슈머는 멱등성 키로 중복을 걸러내며
([oneuptime.com](https://oneuptime.com/blog/post/2026-01-27-kafka-consumers-at-least-once/view)),
오프셋은 처리 성공 후에만 커밋한다. 오류를 일시적/영구적으로 나누지 않으면
릴레이는 영구 실패를 무한 재시도하거나 일시 실패를 성급히 dead-letter한다 —
넷 다 linkly가 **계약으로** 소유할 수 있는 것들이다, 브로커 자체는 아니고.

이슈 #88의 원칙(코어는 아웃박스 테이블 스키마와 drain/ack 의미론만 소유,
실제 브로커 퍼블리셔는 릴레이 구현체)을 소비 쪽에 **대칭 적용**한다:

> 코어는 **구독 선언 + 인입 엔드포인트 + 멱등/오류-분류 의미론**을 소유한다.
> 브로커에서 읽어 그 엔드포인트를 찌르는 것은 릴레이의 몫이다.

`lnpl_idempotency`(이슈 #113)가 이미 있다 — 두 번째 멱등 저장소를 만들
필요가 없다. 이 RFC가 하는 일은 그 위에 CloudEvents 인입 표면 하나를 얹는
것뿐이다.

## Guide-level Explanation

저자가 새로 쓸 수 있는 것은 이벤트 본문의 절 하나다:

```
event OrderPlaced
    consume by FulfillOrder
```

`consume by <Workflow>`는 "이 이벤트가 도착하면 `<Workflow>`를 실행한다"는
뜻이다. 같은 이벤트가 `subscribe`(HTTP로 내보내기)나 `on <Entity> <op>`/
`on schedule ...`(발행 소스)를 동시에 가질 수 있다 — 세 절은 서로 다른
질문에 답한다: "누가 내보내나(소스)", "누가 구독하나(subscribe)", "도착하면
뭘 돌리나(consume by)".

```
event OrderPlaced on Order create
    subscribe
    consume by FulfillOrder
```

대상 워크플로가 선언돼 있지 않으면 컴파일 에러다 — 후보 워크플로 목록과
함께 거부된다(추측하지 않는다, `emit`의 미선언-이벤트 거부와 같은 관례).

```lnpl
event OrderPlaced
    consume by Ghost
```
```
LowerError: line 2: event OrderPlaced declares `consume by Ghost`, which is
not a declared workflow (declared: wf.fulfill.order)
```

컴파일되면 `lnpl serve`가 `POST /-/events/<event-slug>` 라우트를 낸다 —
`/-/schedules/<slug>`(이슈 #81)와 같은 예약 공간이다. 이 라우트는 표준
CloudEvents v1.0 구조화 JSON 봉투를 받는다:

```bash
curl -X POST http://localhost:8080/-/events/order-placed \
  -H 'Content-Type: application/json' \
  -d '{
        "specversion": "1.0",
        "id": "evt-001",
        "source": "order-service",
        "type": "OrderPlaced",
        "data": {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c330b", "amount": 42}
      }'
```

`id`가 멱등성 키다. 같은 `id`를 다시 보내면 워크플로는 다시 실행되지 않고
첫 응답이 그대로 재생된다 — 이슈 #113이 이미 준 계약을 CloudEvents `id`에
연결했을 뿐이다.

응답은 릴레이가 기계로 판정할 수 있는 3갈래다: 성공은 200, 일시적 실패
(다운스트림 불가·데드라인)는 503 + `Retry-After`, 영구적 실패(검증 실패·
비즈니스 거부·충돌)는 422. 봉투 자체가 CloudEvents 형식이 아니면 400.

브로커 없이 이 계약을 실측하려면 레퍼런스 릴레이를 쓴다:

```bash
lnpl relay orders.lnpl --backend sqlite:./store.db \
  --target http://localhost:8081 --once
```

`lnpl outbox drain`(발행 쪽)이 쌓아 둔 emission을 CloudEvents 봉투로 감싸
`<target>/-/events/<slug>`에 POST하고, 응답에 따라 ack(200/422) 하거나
다음 드레인으로 미룬다(503/연결 실패). 브로커 의존은 0 — `urllib` 표준
라이브러리만 쓴다.

순환도 정적으로 경고한다: `A`가 소비하는 이벤트를 `A` 자신이 다시
`emit`하면, 무한 재디스패치 가능성을 컴파일 타임에 알려준다(경고, 에러는
아니다 — 가드가 실제로는 그 경로를 막을 수 있어서다).

```lnpl
event OrderPlaced
    consume by FulfillOrder

workflow FulfillOrder
    validate order
    emit orderPlaced
```
```
warning: event-consume-cycle [event.order.placed] cycle event.order.placed
-> wf.fulfill.order -> event.order.placed — if this path ever runs
unguarded, dispatching the event re-triggers the same workflow forever
```

## Reference-level Specification

### 1. 문법 — `consume by <Workflow>` (D1)

```
EventBody ::= SubscribeLine? ConsumeLine? | ConsumeLine? SubscribeLine?
ConsumeLine ::= 'consume' 'by' PascalName
```

이벤트당 최대 1회, 토큰 정확히 3개(`consume`/`by`/워크플로명). `subscribe`도
같은 절-없는 content-line 슬롯을 쓰므로(파서는 이벤트가 "절을 받지 않는다"고
보고, `lower`가 그 줄이 `subscribe` 단독인지 `consume by <W>`인지를
검사·구별한다), 파서 변경은 없다 — `lower.py`의 `_parse_event_body`(구
`_parse_event_subscribe`) 하나가 둘 다 받는다.

대상 워크플로는 **같은 모듈**에서 이름으로 참조된다(`derive_id` R2 규칙).
`by_kind["workflow"]`로부터 미리 계산한 선언된 워크플로 id 집합과 대조하여,
없으면 `LowerError` + 후보 나열(정렬된 전체 목록, `emit`의 undeclared-event
거부와 같은 관례). `on`/`schedule` 소스, `subscribe`와 배타적이지 않다 —
세 절 다 독립적인 opt-in.

### 2. IR — `Event.consume` (D2)

```json
{"kind": "Event", "id": "event.order.placed", "name": "OrderPlaced",
 "consume": "wf.fulfill.order"}
```

`consume`은 `nodeId`(워크플로 id) 타입, 선언 시에만 존재하는 선택적
필드(`_node()`가 `None`을 자동으로 걸러낸다 — `subscribe`와 같은 관례).
`schemas/lir.schema.json`의 `nodeEvent`에 `"consume": {"$ref":
"#/$defs/nodeId"}` 한 줄 추가. `scripts/validate_ir.py`에 골든 픽스처
(`CONSUME_EVENT_FIXTURE`)와 부정 케이스(타입 불일치, `nodeId` 패턴 밖) 추가.

### 3. 순환 탐지 — `event-consume-cycle` (D3)

이벤트 → 소비 워크플로 → 그 워크플로의 자기 `emit`/`publish` → ... → 같은
이벤트로 돌아오면 경고. 그래프는 두 종류 간선의 이분 그래프다: `event ->
workflow`(`consume`에서), `workflow -> event`(그 워크플로의 `EventEmit`
자식에서). 모든 워크플로가 lower된 **뒤**에 한 번(문서 스코프 후처리)
표준 white/gray/black 사이클 탐지 DFS로 순회한다 — **반복적으로**, Python
콜스택이 아니라 명시적 프레임 스택으로: 수백 개가 체인으로 연결된 모듈에서
재귀 한도를 칠 수 없다.

`event-consume-cycle`을 `diagnostics.py`의 `CODES`/`SEVERITY_OF`에
`warning`으로 등록한다 — RFC-0021의 질문("프로그램을 고치면 사라지는가")에
그렇다로 답한다(`consume by`를 떼거나 `emit`을 떼면 사라진다), 그러나
LowerError가 아니라 경고인 이유는 가드가 실제로는 그 경로를 런타임에 막을
수 있어서다(`consume by`의 미선언 대상 거부와 다른 성격 — 그건 저자가
의도할 수 없는 실수지만, 순환은 프로그램이 틀렸다는 증명이 아니다).

### 4. 인입 라우트 — `POST /-/events/<slug>` (D4)

`consume`이 있는 이벤트마다 라우트 하나. `/-/schedules/<slug>`(이슈 #81)와
같은 예약 공간·같은 병합 순서(`build_routes`의 OpenAPI 계약 검사 **뒤에**
`routes.update(...)`로 합류 — CloudEvents 인입은 오퍼레이션이 아니다) 새
route kind `"event-consume"` = `{workflow, event, auth, role}`. `auth`/`role`
은 **소비 워크플로 자신의 owning service**의 `security` 선언에서 읽는다 —
`build_schedule_routes`가 스케줄 이벤트의 owning service를 찾는 것과 반대
방향(이벤트가 아니라 워크플로에서 서비스로)이지만 같은 규칙이다: 그
워크플로의 일반 POST 라우트가 요구하는 인증을 인입 라우트도 그대로
요구한다 — 새 인증을 발명하지 않는다.

### 5. 봉투 검증 (D5)

구조화 모드 CloudEvents v1.0만. 필수: `specversion`(`"1.0"` 고정)·`id`·
`source`·`type`, 전부 비어있지 않은 문자열. `datacontenttype`이 오면
`application/json`만(`;` 뒤 파라미터 무시) 수용 — 그 외 값, 또는
`data_base64`(바이너리 모드)는 거부. `data`는 선택, 있으면 JSON object여야
하고 기본값은 `{}`. 하나라도 어긋나면 400 problem+json, 어느 필드가
왜인지 명시.

`type`을 이벤트 이름과 대조하지는 **않는다** — 슬러그가 이미 라우팅 키다.
릴레이가 자기 문서의 이벤트 이름을 `type`에 실어 보내지만, 서버는 그것을
검증하지 않는다(계획된 단순화, §Alternatives #3).

### 6. 멱등성 (D6)

CloudEvents `id`를 워크플로 입력(`data`, 기본 `{}`)의 실행 전에
`repository.idempotency_begin(workflow_id, key=id, now_ms, ttl_ms)`로
클레임한다 — 이슈 #113의 테이블·API·TTL·백엔드 분기(fake/sqlite)를
**그대로** 재사용, 두 번째 멱등 저장소를 만들지 않는다.

- `"in-progress"` → 409(`idempotency-in-progress`, #113과 같은 코드).
- `"done"` → 저장된 `(http_status, body)`를 재생, 워크플로 재실행 없음.
- `"started"` → 아래 실행한다.

실행 후 `idempotency_finish`는 **200과 422에서만** 호출한다(§7의 3갈래 중
결정적인 둘) — 그 봉투가 다시 와도 같은 결과가 나오므로 확정(재생)이 맞다.

503(및 예외 이스케이프)은 **확정하지 않는다 — 그리고 단순히 미확정 상태로
두지도 않는다. 대신 `repository.idempotency_release(workflow_id, key)`로
클레임 자체를 즉시 반납한다** (D6 r2 — 아래는 r1이 놓친 구멍과 그 수정).

**r1의 구멍**: 503을 `idempotency_finish`로 확정하면 #113이 그 키에 대해
503을 영원히 재생해, 릴레이가 `Retry-After`를 존중해 재시도해도 절대 새로
실행되지 않는다 — D7의 취지를 정면으로 깬다. 그래서 처음 낸 답은 "확정하지
않고 미확정(`in-progress`)으로 둔다"였다. 그런데 미확정 상태는 TTL(기본
24시간)이 지나야 클리어된다 — 503 수 초~수 분 뒤의 재전달(`Retry-After`가
정확히 요구하는 그 재시도)이 `in-progress`를 보고 409를 받는다는 뜻이다.
**일시적 실패 하나가 이 이벤트 id에 대해 최대 24시간짜리 장애가 된다** —
503이 존재하는 이유(재시도하면 성공할 수 있다) 자체를 무효화한다.

**r2의 수정**: `idempotency_release`(신규 API, #113의 스키마·기존 API는
변경하지 않는다 — `idempotency_begin`/`finish`와 같은 스타일의 즉시-커밋
DELETE 한 문장)를 503 판정 직후 호출해 클레임을 그 자리에서 반납한다.
다음 전달은 `idempotency_begin`이 그 키를 아예 본 적 없는 것처럼 새로
클레임하고(`"started"`), 워크플로가 실제로 다시 실행된다 — TTL을 기다릴
필요가 없다. 예외 이스케이프도 같은 이유로 같은 호출을 한다(진짜 결과가
불확실하다는 점은 그대로지만, "불확실하니 손대지 않는다"가 아니라
"불확실하니 다음 시도가 깨끗하게 다시 시작하게 한다"로 바뀐 것 — 후자가
503/이스케이프 둘 다에 실제로 필요한 것이다).

`in-progress` → 409(`idempotency-in-progress`)는 여전히 유효한 신호다 —
**진짜 동시(concurrent) 중복**(릴레이가 같은 키를 거의 동시에 두 번 POST한
경우 등)은 여전히 그 시점에 클레임을 쥔 요청이 있으므로 409를 본다. r2가
없애는 것은 "503 뒤에 자연스럽게 뒤따르는 순차적 재시도가 착오로 409를
보는" 경우뿐이다.

### 7. 오류 분류 — 3갈래 (D7)

`map_consume_result(result)`가 `run_workflow`의 결과를 분류한다 —
일반 워크플로 POST 라우트의 M6-M9 사다리(`map_result`)와 **다른** 함수다:
그 사다리는 "이 호출자가 뭘 잘못했나"를 답하고, 이 함수는 "이 봉투를 다시
밀어도 되는가"를 답한다.

| 결과 | HTTP | code |
|------|------|------|
| `status == "completed"` | 200 | — |
| `failure_kind == "deadline"` | 503 + `Retry-After: 1` | `event-retry-later` |
| `failure_kind == "conflict"` | 422 | `event-rejected` |
| 실패 스텝의 effect에 `RepositoryCall`/`NetworkCall` 포함(그 외) | 503 + `Retry-After: 1` | `event-retry-later` |
| 그 외 전부(`Validation` 거부, 명시적 비즈니스/가드 RunError) | 422 | `event-rejected` |

**순서가 중요하다**: `conflict`는 실패 스텝이 여전히 `RepositoryCall`
effect를 갖지만(생성 충돌도 결국 그 effect다), D7이 명시적으로 영구
실패라고 이름 붙였으므로 effect-only 분기보다 먼저 확인해야 한다 —
그렇지 않으면 재시도해도 절대 성공할 수 없는 충돌이 "재시도하라"는 503을
받아, 릴레이가 영원히 재시도하고 멱등 클레임도 절대 확정되지 않는다.

내부 예외 이스케이프(런타임 버그 등, `run_workflow` 자체가 raise)도
503으로 분류한다 — 진짜 원인이 불확실하므로 422(영구)라고 단정하지 않고,
같은 D6 r2 논리로 멱등 클레임을 `idempotency_release`로 반납한다(확정도,
방치도 아니다).

### 8. 레퍼런스 릴레이 — `lnpl relay` (D8)

```
lnpl relay <source...> --backend sqlite:<path> --target <base-url> [--once]
```

`source`는 emission의 이벤트 id를 이벤트 선언 이름으로 되돌리는 데만
컴파일한다(재실행 없음). 매 드레인 사이클마다:

1. `repository.drain_outbox()` — 미배달 emission 전부.
2. 각 emission을 CloudEvents 봉투로: `id="outbox-<seq>"`(안정값 — 같은
   행은 항상 같은 멱등성 키), `source`=모듈명, `type`=이벤트 선언 이름,
   `data`=emission의 payload.
3. `<target>/-/events/<slug>`에 POST(`urllib` 표준 라이브러리만).
4. 응답별 ack 결정: 200 → ack. 422 → ack + stderr에 dead-letter 경고 한
   줄(재시도해도 같은 결과이므로). 503 또는 응답 없음(연결 실패) → ack 안
   함, 다음 드레인이 재시도(at-least-once, 성공 후에만 커밋하는
   오프셋-커밋 규율). 그 외 예기치 못한 상태(예: 대상이 그 슬러그에
   `consume by`를 선언하지 않아 404)도 안전한 쪽(ack 안 함)으로 접는다 —
   이 레퍼런스 릴레이는 D7이 정의하지 않은 네 번째 갈래를 발명하지 않는다.

`--once`는 한 사이클만 돌고 rc 0으로 끝난다(테스트·cron이 미는 모양).
기본은 무한 반복(고정 폴링 간격) — `--interval` 같은 튜닝 플래그는 내지
않는다(이슈가 `--once` 하나만 요구했다, §Alternatives #5).

브로커 의존 없음. `lnpl-relay-kafka` 같은 실바인딩은 이 RFC의 범위 밖 —
드라이버 SPI(#75/#132)와 같은 판단.

### 9. 문서 — `subscribe` vs `consume by` (D9)

`docs/serving.md`에 대조표 + E1-E7 매핑표 신설(§Guide-level Explanation의
표 형태와 동일). `docs/backends.md §5`에 소비 측 대칭 경계 1문단 — 발행
쪽 #88 원칙이 소비 쪽에도 그대로 적용됨을 명시. 라우팅↔OpenAPI 대조는
`build_routes()`가 이미 강제한다: `event-consume` 라우트 테이블은 그
계약-검사 **뒤에** 합류하므로, 대조가 깨지면 `lnpl serve`가 기동 시점에
거부한다(스케줄 트리거와 같은 안전장치).

### 10. 회귀 (D11)

`consume by` 없는 기존 문서는 IR이 바이트 그대로 불변 — `Event.consume`
필드가 아예 나타나지 않는다(§2). 통합 테스트: 발행 문서(sqlite outbox) →
`lnpl relay --once` → 소비 인스턴스(`wsgiref` 실서버 스레드) 왕복 + 같은
CloudEvents `id` 재전달 시 워크플로 미재실행(§6의 계약이 두 프로세스
사이에서 실제로 성립함을 증명).

## Examples

골든 시나리오 "Login"(`plans/rfc-suite/plan.md`)은 `event UserCreated on
User create`를 선언하지만 `consume by`는 쓰지 않는다 — 이 RFC가 이미
존재하는 회귀 기준선을 건드리지 않는다는 증거 그 자체다(§Reference-level
Specification/10, `examples/login.lir.json` 바이트 동일).

`consume by`가 다루는 기능은 골든이 다루지 않으므로, RFC-0007 §6이 허용하는
**골든 인접 예제**를 별도로 제시한다:

```lnpl
capability postgres

entity Order
    field
        id UUID
        amount Integer

service OrderService

event OrderPlaced on Order create
    consume by FulfillOrder

workflow FulfillOrder
    validate order
    create order
```

CloudEvents 인입:

```json
POST /-/events/order-placed
{
  "specversion": "1.0", "id": "evt-42",
  "source": "order-service", "type": "OrderPlaced",
  "data": {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c330b", "amount": 42}
}
```

→ 200, `FulfillOrder` 실행 완료. 같은 `id="evt-42"`를 다시 보내면 →
200(재생, 재실행 없음). `data.id`가 UUID가 아니면 → 422
(`event-rejected`, `validate order` 거부). 저장소가 불가하면 → 503 +
`Retry-After: 1`(`event-retry-later`).

## Alternatives

| # | 검토한 대안 | 기각 사유 |
|---|------------|----------|
| 1 | **`consume by`를 `subscribe`의 값으로 오버로드**(`subscribe run <Workflow>`처럼) | `subscribe`(내보내기)와 `consume by`(실행)는 서로 다른 질문에 답한다 — 이슈 원문이 대조표를 요구할 만큼 헷갈리는 이름인데, 한 절에 욱여넣으면 더 헷갈린다. 독립 절 두 개가 각자 명확하다 |
| 2 | **인입 라우트를 `POST /<svc>/<workflow>`(기존 워크플로 라우트) 재사용** | CloudEvents 봉투와 일반 워크플로 입력은 다른 스키마다 — 같은 경로가 둘을 받으면 그 경로가 뭘 기대하는지 라우트 자체에서 알 수 없다. 예약 공간(`/-/events/`)이 스케줄 트리거와 같은 이유로 분리를 정당화한다 |
| 3 | **`type`을 이벤트 이름과 대조**(라우팅 슬러그와 별개로 검증) | 슬러그가 이미 라우팅 키이므로 대조는 정보를 추가하지 않는다 — 다른 소스가 다른 `type` 문자열 관례를 쓰는 실전 CloudEvents 발행자(레거시 시스템 등)를 이유 없이 거부하게 된다. 필요해지면 릴레이 레벨의 관례로 남긴다 |
| 4 | **일시적/영구적 오류를 `failure_kind`에 새 값으로 명시적으로 태그**(effect 기반 추론 대신) | `run_workflow`에 새 필드를 더하면 그 결과 dict의 계약을 넓히는 것이고, 일반 워크플로 라우트의 `map_result`도 갈아엎을 위험이 있다. 이미 있는 `effects`/`failure_kind` 필드만으로 결정적으로 분류 가능하다(§7) — 새 필드 없이 기존 관측만으로 답이 나오면 새 필드를 만들지 않는다 |
| 5 | **`lnpl relay`에 `--interval`/`--concurrency` 등 운영 튜닝 플래그** | 이슈가 요구한 것은 `--once` 하나뿐이다. 레퍼런스 구현이 프로덕션 운영 도구로 확장되기 시작하면 범위가 무한정 넓어진다 — 실제 운영 규모의 릴레이는 애초에 별도 패키지(§8, `lnpl-relay-kafka`류)의 몫이다 |
| 6 | **503을 즉시 확정하고 별도 "재시도 가능" 플래그를 body에 얹는다** | #113의 **테이블 스키마**를 바꾸지 않고 재사용하는 것이 이슈의 제약이다 — API 표면에 메서드 하나(`idempotency_release`)를 더하는 것까지 막지는 않는다. 이 대안은 확정 자체를 하므로 재생-영구화 문제를 되풀이한다 |
| 7 | **503을 미확정(`in-progress`) 상태로 그냥 둔다**(D6 r1의 첫 설계) | TTL(기본 24시간)이 지나야 클레임이 풀린다 — `Retry-After`가 요구하는 몇 초~몇 분 뒤의 재시도가 그 사이 전부 409를 받아, 일시적 실패 하나가 이 이벤트 id에 대해 최대 24시간짜리 장애가 된다. 재검토 결과 기각(§Reference-level Specification/6, D6 r2) |
| 8 | **TTL을 짧게 줄여 503의 자연 치유를 앞당긴다**(운영자가 `--idempotency-ttl`로 조정) | TTL은 이 인스턴스가 받는 **모든** 키에 적용되는 전역 값이다 — 503의 회복 시간을 위해 낮추면, 정당한 200/422 결과의 재생 보장 기간도 함께 짧아진다(같은 하나의 놉으로 서로 다른 두 요구를 만족시킬 수 없다). 503 전용의 즉시 반납(`idempotency_release`)이 TTL을 건드리지 않고 정확히 그 경우만 고친다 |

## Open Questions

1. **AsyncAPI 발행.** OpenAPI가 REST 계약을 발행하듯 이벤트 계약을 발행할
   자리 — `x-lnpl-schedules`처럼 확장으로 시작하지 않고, 수요가 실측되면
   별도 이슈로 넘긴다(이슈 원문이 이미 명시).
2. **집계 어휘와의 상호작용.** `consume by` 워크플로가 `list where`/
   `sum`/`count`(RFC-0025/RFC-0038)를 쓸 때의 멱등성 경계는 이 RFC의
   범위 밖 — #113의 기존 멱등 계약을 그대로 물려받을 뿐, 새로 결정할 것이
   없다고 보이지만 실측되지 않았다.
3. **순환 탐지의 교차 문서 범위.** `_check_event_consume_cycles`는 한
   컴파일 단위(모듈) 안의 순환만 본다 — 여러 `.lnpl` 파일이 별도 서비스로
   배포되고 그 사이에서 이벤트가 순환하는 경우(A 서비스가 소비→발행,
   B 서비스가 그걸 소비→A가 발행한 이벤트를 다시 발행)는 정적으로 볼 수
   없다(별도 프로세스, 별도 컴파일). 런타임 관측(예: correlation_id 체인
   깊이 경고)으로 보완할지는 후속 이슈.

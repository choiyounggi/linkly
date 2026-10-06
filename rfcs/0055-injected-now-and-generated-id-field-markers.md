# RFC-0055: 실행이 채우는 필드 — `derived generated`와 `derived clock`

## Status

- Status: Draft
- Updates: RFC-0030 §Reference-level Specification/4. payload 시드

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목한다. RFC-0030 §4는 이번이 첫
갱신이다 — RFC-0030 머리에 `Updated-by:`가 없고, 다른 RFC의 Updates 목록에도 그 절이
없다. 그래서 대상 RFC 하나만 지목한다. 이 RFC는 Draft이므로 RFC-0030에
`Updated-by:` 포인터를 달지 않는다(Accepted가 되는 시점의 일이다).

이 RFC는 RFC-0016 Open Question 6("주입식 `now`의 승격")에 답한다. 그 절의 텍스트를
바꾸지 않으므로 RFC-0016에 대한 Updates가 아니다 — RFC-0029·RFC-0030이 앞선 열린
질문에 답할 때 쓴 것과 같은 모양이다. RFC-0029(시계 계약)도 바꾸지 않는다: 이 RFC는
`Clock`을 읽기만 한다.

배치 결정(코디네이터 판정, 2026-10-04): 값은 실행 문맥에서 **한 번** 정해지고,
`create` 시점에 그 스텝이 만드는 엔티티의 표식 필드에만 들어간다. 공유 입력
payload에는 절대 쓰지 않는다(§4). 구현은 한 단계로 들어간다 — §1–§10 전부.

## Motivation

issue #209가 실측한 증상: 서버는 행 id도 현재 시각도 만들 수 없다.

```lnpl
entity AuditEntry
    field
        id UUID
        action Text

service AuditService

workflow Record
    create auditentry as a
    respond a.action
```

`{"action":"login"}`으로 sqlite에서 두 번 실행하면 두 번째가 `repository create
conflicts`로 실패한다. 행 키가 `row_key(entity, payload)`이고, payload에 `id`가 없으면
`-`로 떨어져 모든 행이 `entity.audit.entry#-` 하나에 몰린다. 저장된 `id` 값도
`"entity.audit.entry#-"`다 — `UUID`로 선언한 필드에 행 키 문자열이 들어간다. `id`를
`derived`로 선언하면 `derived-never-assigned`가 "채우라"고 하지만 채울 수단이 없다
(`set a.id to uuid()`는 `invalid operand`). `set a.at to now`(괄호 없음)는 경고 없이
컴파일되고 런타임에 "a reference in 'now' resolves to nothing"으로 실패한다.

스케줄 배치(`lnpl trigger`)와 이벤트 소비(`consume by`)에는 id를 지어 줄 호출자가
없고, 주문 시각을 클라이언트 시계로 받는 것은 신뢰 경계가 뒤집힌 것이다.

RFC-0016은 벽시계 `now` 원시값을 기각하고 주입식을 택하면서 Open Question 6을 남겼다:
"이 필드가 실행 시각"이라는 표식이 생기면 **서빙 계층이 자동으로 채울 수 있고**,
재현성은 여전히 호출자가 값을 고정할 수 있다는 사실에서 나온다. 이 RFC가 그 표식이고,
같은 방식을 id에 적용한다.

| 출처 | 규칙 | 이 RFC가 취한 것 |
|---|---|---|
| Google AIP-133 (Create) | `{resource}_id`를 OPTIONAL로 두고 주지 않으면 system-generated ID를 만든다 | `derived generated` — 서버가 만든다 |
| Google AIP-148 (Standard fields) | output only `uid`는 UUID4, `create_time`도 output only | UUIDv4, 생성 시각은 서버 할당 |
| AWS Step Functions Context object | 실행 시각은 로직이 계산하지 않고 런타임이 넣어 주는 컨텍스트에서 읽는다 | 함수 호출이 아니라 주입된 실행 문맥 |

## Guide-level Explanation

`derived` 필드 줄 끝에 **채움 원천 표식**을 붙인다. 닫힌 두 낱말이다.

```lnpl
entity AuditEntry
    field
        id UUID derived generated      # 실행마다 UUIDv4 하나
        at DateTime derived clock      # 실행 시작 시각
        action Text

service AuditService

workflow Record
    create auditentry as a
    respond a.action
```

이제 같은 payload `{"action":"login"}`으로 두 번 실행하면 서로 다른 UUID 키의 행
두 개가 생기고, 각 행의 `id`는 진짜 UUID, `at`은 그 실행의 시각이다.

- **함수가 아니라 선언이다.** 워크플로 안에 `now()`/`uuid()`는 여전히 없다(RFC-0016
  §Alternatives 3의 기각 사유가 그대로 유효하다).
- **값은 실행 시작에 한 번 정해진다.** `lnpl run`/`trigger`/`serve`는 실행마다 새로
  정한다. `spec`은 `given run.generated <uuid>`/`given run.clock <instant>`로 고정한다.
- **payload로는 고를 수 없다.** 표식 필드는 `derived`이므로 클라이언트가 보낸 값은
  쓰이지 않는다(`validate`는 지금처럼 그 키를 거부한다).
- **표식 없는 엔티티를 `id` 없이 만들면 실패한다.** `failure_kind == "id-required"`,
  `serve`에서는 400이다. 조용히 `<entity>#-`에 쓰던 동작이 사라진다.
- **선언하지 않은 맨이름을 `set` 값에 쓰면 컴파일 오류다.** `set a.at to now`는
  "`derived clock`으로 선언한 필드를 뜻했느냐"고 묻는다.
- **모드 B는 표식 엔티티를 만드는 워크플로를 거부한다.** RFC-0052처럼 이유와 RFC
  번호를 말한다.

서버가 id를 만들면 재시도가 중복 행을 만든다(재시도마다 새 UUID). 재시도 안전성이
필요한 생성 경로는 `Idempotency-Key`(issue #113)와 함께 쓴다.

## Reference-level Specification

### 1. 문법 — 채움 원천 표식

필드 줄의 넷째 토큰으로, `derived` **바로 뒤에만** 온다.

```
<name> <Type> derived generated
<name> <Type> derived clock
```

| 표식 | 필드 타입의 기본형(base) | 값 |
|---|---|---|
| `generated` | `UUID` | 실행당 UUIDv4 하나(§3) |
| `clock` | `DateTime` | 실행 시작 시각(§3) |

기본형은 RFC-0015와 같이 refinement를 벗긴 18개 기본 타입 중 하나로 판정한다
(`refine AuditId of UUID`로 선언한 필드도 `generated`를 받는다). 컴파일 오류:

- `derived` 뒤의 표식이 위 둘이 아님 — 유효한 표식 둘을 나열한다.
- 표식이 `derived` 바로 뒤가 아님(`at DateTime optional clock`, `at DateTime clock`) —
  `derived` 뒤에만 온다고 말하고 고쳐 쓴 줄을 보여 준다.
- 기본형 불일치(`at Text derived generated`) — 표식, 필요한 기본형, 선언된 타입을 댄다.
- `id`에 `clock`(`id DateTime derived clock`) — `id`는 행 키이고 한 실행의 시각은 유일하지
  않다(가상 시계에서는 실행마다 같다). `id`가 받는 표식은 `generated`뿐이다.
- `optional`과의 결합은 RFC-0053의 `derived`+`optional` 거부가 그대로 막는다(필드 줄은
  토큰 4개가 상한이라 셋을 함께 쓸 자리도 없다).

### 2. IR — 노드 카탈로그/Entity의 `fields[]`

표식이 있는 필드에만 `fill_source: "generated" | "clock"`이 붙는다. 표식이 없으면 키
자체가 없다(RFC-0053의 `optional`과 같은 "부재 = 아님" 규칙). 표식 필드는 언제나
`derived: true`도 가진다.

```json
{"name": "id", "type": "UUID", "derived": true, "fill_source": "generated"}
```

`schemas/lir.schema.json`의 `fieldList` 항목은 `derived: boolean`과
`fill_source: enum["generated","clock"]`을 받는다. `derived`는 issue #95부터 IR에
있었지만 스키마가 받지 않던 공백이었다(t208이 기록) — 같은 변경으로 닫는다. 어느
표식이 어느 기본형을 요구하는지는 스키마가 아니라 컴파일러가 판정한다(`type`이
refinement 이름일 수 있다).

### 3. 실행 문맥 — 언제, 무엇으로 정해지는가

인터프리터의 `run_workflow(workflow_id, payload=None, run_context=None)`는 워크플로를
찾은 직후, `null` 정규화·`validate`·시드·어떤 스텝보다도 **먼저** 실행 문맥을 한 번
정한다.

- `run_context`가 준 키는 그대로 쓴다(고정). 키는 `generated`/`clock`뿐이고, 다른
  키나 빈 문자열·비문자열 값은 `RunError`다.
- `generated`가 없으면 UUIDv4 하나(`uuid.uuid4()`의 표준 문자열 표기)를 만든다.
- `clock`이 없으면 그 실행의 `Clock`을 읽는다(RFC-0029 바인딩): virtual이면 `now`(실행
  시작 시점의 가상 밀리초 — 기본값은 0, 즉 `1970-01-01T00:00:00.000Z`로 결정적), real이면
  벽시계 epoch 밀리초. `RealClock.now`는 단조 시계라 절대 시각이 아니므로 읽지 않는다.
- 시각의 텍스트는 RFC 3339 UTC 밀리초 `YYYY-MM-DDTHH:MM:SS.mmmZ`다. RFC-0016의
  `encode_instant`로 다시 읽으면 같은 순간이 된다(`condition.decode_instant`).

`lnpl run`/`trigger`/`serve`는 `run_context`를 넘기지 않으므로 실행(요청)마다 새 값이
정해진다. 한 실행 안에서 `derived generated` 엔티티를 둘 이상 만들면 **같은 UUID를
공유할 수 있다** — 엔티티 접두사가 달라 행 키는 겹치지 않는다. 같은 엔티티를 한 실행에서
두 번 만들면 같은 키라서 두 번째가 충돌한다(표식 없는 엔티티가 같은 payload id로 두 번
만들 때와 같다).

### 4. payload 시드 — RFC-0030 §4 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라 RFC-0030 §4 전체를 아래로 치환한다.

> **4. payload 시드 (D3; RFC-0055 갱신)**
>
> 생성 시점에, 그 Entity가 선언한 필드마다:
>
> - **채움 원천 표식이 있는 필드**(RFC-0055 §1)는 이 실행의 실행 문맥 값(§3)을 새 행의
>   초기값으로 삼는다. payload의 동명 키는 보지 않는다.
> - **그 밖의 `derived` 필드**는 issue #95의 규칙대로 시드하지 않는다 — derived는 서버
>   계산 전용이고, `create` 시점에 그 계산이 아직 실행되지 않았을 수 있다.
> - **나머지 필드**는 payload가 동명 키를 가지면 그 값을 초기값으로 삼는다. payload에
>   없는 필드는 시드하지 않는다(생성 직후 값이 없는 채로 남는다). `optional` 필드의
>   `null`은 저장하지 않는다(RFC-0053 §4).
>
> 행 키: 그 Entity의 `id`가 `derived generated`이면 `row_key(entity, {"id": <실행 문맥의
> generated>})`, 아니면 이전처럼 `row_key(entity, payload)`다.
>
> 저장되는 `id`: 두 드라이버의 뼈대 행은 `{"id": <행 키 문자열>}`이다. Entity가 `id`를
> 선언했으면 시드는 언제나 `id`에 **행 키를 만든 그 값**(실행 문맥의 UUID 또는 payload
> `id`)을 넣는다 — 선언된 `id`에 행 키 문자열이 남지 않는다. `id`를 선언하지 않은
> Entity는 뼈대 값을 그대로 둔다(이전과 같다).
>
> 시드는 **`as` 유무와 무관하게 적용**된다. 시드된 값은 `execute("create", ...)` 직후
> 별도의 `persist` 호출 하나로 얹힌다(`drivers.py`는 손대지 않는다, §5). `persist`는
> Entity가 `id`를 선언했으면 언제나, 아니면 `id` 밖에 시드할 것이 있을 때만 호출한다.
> 그래서 `id`만 담긴 payload로 `id`를 선언한 Entity를 만들면 이 갱신 이전에는 없던
> `persist` 호출 하나가 생긴다 — 저장된 `id`를 진짜 값으로 고치는 호출이다.

실행 문맥 값은 공유 입력 payload에 **쓰지 않는다.** `input.<f>` 참조, `validate`,
다른 엔티티의 시드와 행 키는 표식의 영향을 받지 않는다. 그래서 한 모듈에 표식 엔티티와
표식 없는 엔티티가 함께 있어도 판정할 엇갈림이 없다 — `AuditEntry`(`id` generated)와
`Order`(클라이언트 `id`)를 한 워크플로가 함께 만들 수 있다.

### 5. `derived-never-assigned`

표식이 있는 필드는 이 경고의 대상이 아니다 — 실행이 채운다. 표식 없는 `derived`
필드에는 지금처럼 경고한다.

### 6. `id-required` — 표식 없는 `create`에 `id`가 없을 때

`create`(`insert`/`persist`/`save` 포함)의 대상 Entity의 `id`가 `derived generated`가
아니고 payload에 `null` 아닌 `id`가 없으면, 그 스텝은 **쓰기 전에** 실패한다.
`RunError.failure_kind == "id-required"`, 메시지는 엔티티 id와 `id`를 댄다. Entity가
`id` 필드를 선언했는지와 무관하다 — 선언하지 않아도 payload에 `id`가 없으면 행은
`<entity>#-`에 몰리기 때문이다.

- `serve`: 매핑표 M8d = 400 `id-required`(M8a/M8b와 함께 M8보다 먼저). 이벤트 소비
  경로는 영구 실패 E7 = 422 `event-rejected` — 같은 payload를 다시 보내도 같은 결과다.
- 경고가 아니라 오류인 근거(호환성 결과): 이 규칙을 구현한 뒤 전체 스위트와 모든
  `examples/*.lnpl`(워크플로 10개 기본 payload 실행, `spec --run` 6개)을 돌린 실측
  결과, `<entity>#-` 키에 기대는 테스트·예제·문서 스니펫은 **0건**이었다. 걸린 것은
  새 오류 코드가 `docs/serving.md`에 없다는 문서 검사 하나였고, 매핑표 행으로 닫았다.
  예제 10개 워크플로는 모두 `completed`, spec은 모두 통과였다.

### 7. 선언하지 않은 맨이름 피연산자

`set <binding>.<field> to <값>`의 값(또는 산술의 양쪽 피연산자)에 점 없는 맨이름이
오고, 그 이름을 필드로 선언한 엔티티가 하나도 없으면 컴파일 오류다. 맨이름은 입력
필드다(RFC-0012 §G12.1) — 선언된 이름은 지금처럼 허용된다. 이름이 `now`/`time`/
`timestamp`이면 `derived clock`을, `uuid`/`guid`/`generated`이면 `derived generated`를
제안한다. `format`의 인자, 가드 조건(RFC-0016 §3의 기존 허용), 집계(`count`/`sum`)의
참조는 바뀌지 않는다. 이 검사는 대상 필드의 타입 검사 **뒤에** 돈다 — `set`이 쓸 수
없는 대상(Text 필드는 RFC-0054의 "`format`을 쓰라" 거부, UUID 필드는 차원 거부)은 그
거부가 먼저 나온다.

이 규칙 때문에 바뀐 기존 테스트(의도된 변경): `test_value_semantics`의 미선언 맨이름
`amount`를 쓰던 경계 테스트는 선언된 `stock`으로, Money 런타임 거부를 맨이름으로 재던
테스트들은 그 이름(`extra`/`left`/`right`)을 보조 엔티티에 선언하도록 고쳤다 —
선언된 맨이름도 정적 타입이 없으므로 런타임 경로는 그대로 검증된다.

### 8. 모드 B

모드 B의 파라미터 채널은 i64이고 UUID 문자열을 실을 수 없다. 그래서 RFC-0052처럼
**거부한다**: 도달 가능한 `create`가 표식 필드를 가진 Entity를 대상으로 하면(가드 안이어도)
`emit_mlir`/`build`는 `BackendError`로, `diff`(`differential.verify`)는
`DifferentialError`로 RFC-0055을 인용해 거절한다. 각자의 거부 사슬에서 **마지막**에 묻는다
— `build`는 Money → lookup → optional → fill-source, `diff`는 numeric → Money → lookup
→ optional → fill-source. 둘이 공유하는 넷의 순서가 같다. 표식 엔티티를 읽기만 하거나
표식 없는 엔티티를 만드는 워크플로는 영향이 없다.

§6과의 등가: 모드 B의 실패 투영은 `create`의 payload에 `id`가 없으면 그 효과에서 실패를
예측한다 — 모드 A의 `id-required`와 같은 지점이다.

### 9. `spec` — 값의 고정

`given` 형태 둘을 더한다(값은 매니페스트 단계에서 검사한다).

| 형태 | 뜻 |
|---|---|
| `run.generated <uuid>` | 실행 문맥의 `generated`를 고정. 값은 `UUID` 타입 검사를 통과해야 한다 |
| `run.clock <instant>` | 실행 문맥의 `clock`을 고정. 존 표기가 있는 RFC 3339 순간이어야 한다 |

이 값은 payload가 아니라 실행 문맥으로 간다. 케이스의 워크플로가 `derived generated`
필드를 가진 Entity를 만드는데 `run.generated`가 없으면 그 케이스는 실행하지 않고
FAIL이다 — 고정하지 않은 UUID는 실행마다 달라 spec이 반복 가능하지 않다. `clock`은
고정이 없어도 가상 시계의 실행 시작 시각이라 결정적이다. `diff`의 결정성은 §8의 거부가
보장한다(거부는 매번 같다).

### 10. 관측

새 `failure_kind` 하나(`id-required`), 새 문제 코드 하나(같은 이름). 새 진단 코드는
없다 — §1과 §7은 컴파일 오류이고, §5는 기존 경고의 범위를 좁힌다.

## Examples

### 골든 시나리오 "Login" (RFC-0007 §6)

골든 시나리오는 표식을 쓰지 않고, 그 `create`는 payload `id`를 가진다. 이 RFC 뒤에도
`examples/login.lnpl`의 IR, OpenAPI, 모드 B 출력은 바이트 단위로 같다. 다른 예제 다섯도
같다.

### 골든 인접 예제 — issue #209 감사 기록 (RFC-0007 §6, 골든이 다루지 않는 기능)

```lnpl
entity AuditEntry
    field
        id UUID derived generated
        at DateTime derived clock
        action Text

service AuditService

workflow Record
    create auditentry as a
    respond a.action
    spec
        given
            action login
            run.generated 00000000-0000-4000-8000-000000000057
            run.clock 2030-01-02T03:04:05.006Z
        when
            record
        expect
            completed
            rows AuditEntry 1
            result a.id exists
```

`lnpl run`으로 `{"action":"login"}`을 sqlite에 두 번 실행하면 행 키가
`entity.audit.entry#<uuid>`인 행 두 개가 생기고, 두 `id`는 서로 다른 UUIDv4다.
`--clock virtual`(기본)에서 `at`은 `1970-01-01T00:00:00.000Z`, `--clock real`에서는 그
실행의 벽시계다. spec 케이스는 위 두 값을 고정해 두 번 돌려도 같은 결과를 낸다.

### 컴파일 거부

```
line 3: fill-source marker 'generated' needs a UUID field, but 'at' is declared Text (RFC-0055)
line 3: fill-source marker 'clock' is valid only directly after `derived` — write `at DateTime derived clock` (RFC-0055)
line 3: unknown fill-source marker 'now' after `derived` — valid markers are generated, clock (RFC-0055)
line 11: assignment 'set a.at to now' reads 'now', which no declared entity has as a field — a bare name is an input field (RFC-0012 §G12.1) — did you mean a field declared `derived clock`? The run fills it at `create` (RFC-0055)
```

## Alternatives

1. **워크플로 함수 `now()`/`uuid()` — 기각.** RFC-0016 §Alternatives 3의 사유(재현성,
   모드 등가)가 그대로다. 표식은 필드 선언이라 값이 실행 문맥 하나에서 오고, `spec`이
   그것을 고정할 수 있다.
2. **값을 입력 payload에 써 넣기 — 기각.** payload는 모든 엔티티가 공유하는 이름
   공간이다(RFC-0015 §G15.2). `AuditEntry`의 생성 id가 `payload.id`에 들어가면 같은
   워크플로의 표식 없는 `Order` 생성이 그 id를 집어 `id-required`를 우회하고, `read`는
   엉뚱한 키를 읽는다. 엇갈림을 컴파일 오류로 막으면(RFC-0053 §11 방식) `id`를 선언한
   다른 엔티티가 있는 모듈에서는 표식을 쓸 수 없다.
3. **payload 값이 있으면 그것을 쓰기(호출자 고정) — 기각.** `derived` 필드를
   클라이언트가 고르게 된다 — issue가 지적한 "클라이언트 시계를 믿는 주문 시각"이 그대로
   남는다. 고정은 `spec`의 실행 문맥 채널로만 한다.
4. **`id-required`를 경고로 — 기각.** §6의 실측에서 기대는 곳이 0건이었고, 경고로 두면
   두 번째 생성부터 영원히 409인 데이터를 계속 만든다.
5. **모드 B 파라미터 채널로 전달 — 기각(이번에는).** 채널이 i64라 UUID 문자열을 실을 수
   없다. 시각만 실을 수는 있지만 반쪽 지원은 거부 규칙을 표식마다 둘로 나눈다.
6. **UUIDv7·ULID·시퀀스 — 범위 밖.** AIP-148의 UUID4를 따른다.
7. **모든 맨이름 거부 — 기각.** 선언된 맨이름은 입력 필드다(RFC-0012 §G12.1). 거부할
   것은 아무것도 가리키지 않는 이름뿐이다.

## Open Questions

1. **다른 id 형식.** 정렬 가능한 UUIDv7이 필요해지면 표식을 하나 더 여는가, `generated`의
   인자로 두는가.
2. **표식 필드의 refinement 패싯.** `refine AuditId of UUID` + `pattern`처럼 생성 값이
   통과하지 못할 패싯을 지금은 생성 시점에 검사하지 않는다(읽기의 `check_row` 형 검사가
   드러낸다). 컴파일 시점에 표식 필드의 패싯을 금지할지.
3. **모드 B 지원.** 문자열 파라미터 채널이 생기면 §8의 거부를 걷어낼 수 있다.
4. **서빙 계층의 고정 채널.** 재현 실험을 위해 `serve`/`run`에서 실행 문맥을 고정하는
   플래그가 필요한지 — 지금은 `spec`만 고정한다.

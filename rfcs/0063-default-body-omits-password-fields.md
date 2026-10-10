# RFC-0063: send 없는 call/request의 기본 본문은 Password 계열 입력 필드를 뺀다

## Status

- Status: Draft
- Updates: RFC-0057 §Guide-level Explanation (`send`가 없는 호출의 본문을 말하는 문단), RFC-0057 §Reference-level Specification/4. 런타임 본문 구성, RFC-0057 §Reference-level Specification/5. 호환성, RFC-0057 §Reference-level Specification/8. 이 RFC에 없는 것

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목한다. 아래 §Reference-level
Specification의 5~8이 지목한 네 절의 치환 후 최종 텍스트다(규칙 4, 자기완결). 이
RFC와 RFC-0057은 둘 다 Draft이므로 RFC-0057에 `Updated-by:` 포인터를 달지 않는다
(Accepted가 되는 시점의 일이다).

## Motivation

`send` 절이 없는 `call`/`request`는 실행 입력 전체를 외부 호출 본문으로 보냈다
(RFC-0057 §4: "마스킹 없이"). 그래서 Password 계열 입력 필드의 원문이 외부 서비스에
나갔다(issue #214). #43의 마스킹 계약 — Password 계열 값은 어떤 출력 채널에도 원문으로
나가지 않는다 — 은 로그·응답·이벤트를 `mask_payload`로 막지만 이 경로는 막지 않았다.
RFC-0057 §8(D13)은 이 누출을 실측만 하고(`PasswordInDefaultBodyMeasurementTest`) 별도
이슈로 넘겼다.

- GDPR 제5조 1항 (c): 개인정보는 "adequate, relevant and limited to what is necessary
  in relation to the purposes for which they are processed"여야 한다. 상대가 요구하지
  않은 비밀값은 필요한 범위 밖이다.
- OWASP Logging Cheat Sheet는 "Authentication passwords", "Access tokens" 등을
  "removed, masked, sanitized, hashed, or encrypted" 하라고 한다. 외부 호출 본문도
  출력 채널이다. 이 RFC는 "removed"를 고른다.

## Guide-level Explanation

```
entity Customer
    field
        id UUID
        secret Password

workflow Ping
    find customer
    call PaymentGateway as paymentResult
```

입력이 `{"id": "c-1", "secret": "..."}`이면 결제 게이트웨이는 `{"id": "c-1"}`만
받는다. `secret` 키는 본문에 아예 없다 — `***`로 바뀌어 남는 것이 아니다.

어떤 필드가 빠지는가: 문서의 **어느 엔티티든** 그 이름을 `Password`나
`refine ... of Password`로 선언했으면 그 이름의 입력 키가 빠진다. 입력에 그런 키가
없으면 본문은 이 RFC 이전과 바이트까지 같다.

Password 값을 상대에게 보내는 길은 없다. `send customer.secret`은 여전히 컴파일
에러다(RFC-0057 §3, RFC-0049).

## Reference-level Specification

### 1. Password 계열 이름 집합

`Interpreter._input_masked_names()`는 문서의 모든 `Entity` 노드에 대해
`masked_field_names(self._entity_view(node))`를 구해 합집합(frozenset)을 낸다.
`masked_field_names`는 필드의 선언 타입을 18-타입 `base`로 해석한 값이
`MASKED_TYPES`에 드는 필드 이름이다 — `mask_payload`도 같은 함수를 부른다(마스킹
이름 도출은 하나다).

모든 엔티티를 보는 이유: 실행 입력은 한 엔티티에 묶이지 않는다. 인터프리터는 이미
`input.<field>`의 optional 여부를 그 이름을 선언한 모든 엔티티로 판정한다(RFC-0053).
한 엔티티에서 `Text`, 다른 엔티티에서 `Password`인 같은 이름도 뺀다(보수적인 쪽).

컴파일 시점의 `send input.<field>` 거부와의 관계: 그 거부도 같은 합집합으로 판정한다 —
그 이름을 선언한 엔티티 중 하나라도 Password 계열이면 컴파일 거부다(issue #219,
RFC-0049 §3 규칙 3, RFC-0057 §3 규칙 4). 이전에는 평평한 `declared_fields` dict(같은
이름이면 마지막에 선언한 엔티티가 이긴다)로 판정해 선언 순서에 따라 결과가 달랐다. 이제
런타임 본문 필터와 컴파일 거부가 어느 선언 순서에서도 같은 이름 집합을 본다.

### 2. 본문 필터

`omit_masked_fields(payload, masked_names)`:

- `payload`가 dict가 아니거나 `masked_names`와 겹치는 키가 없으면 **같은 객체**를
  돌려준다. 그래서 Password 계열 필드가 없는 입력의 본문은 바이트 동일하다.
- 아니면 입력 순서를 지킨 새 dict에서 그 키들을 뺀다. 호출자의 dict는 바꾸지 않는다.
- `MASK`(`***`)로 바꾸지 않는다 — 키가 있다는 사실도 알리지 않는다.

### 3. 적용 지점

기본 본문을 만드는 곳은 한 곳이다: `interp.py`의 `NetworkCall` 분기에서 `bodyMap`이
없을 때 `request_body = omit_masked_fields(payload, self._input_masked_names())`.
(스윕: `grep -n -E 'network\.call\(' impl/lnpl/*.py` → 1건.) `call`과 `request`
둘 다, 두 `NetworkDriver` 구현(fake, http) 모두, `lnpl run`·`lnpl serve`·`spec` 모두
이 지점을 지난다 — 셋 다 `Interpreter`로 실행한다.

### 4. mode B·IR·진단

mode B는 바뀌지 않는다. mode B는 호출 본문을 만들지 않는다(스윕:
`grep -c bodyMap impl/lnpl/backend.py` → 0, RFC-0057 §6). IR(`bodyMap` 키 없음)과
골든은 같고, 새 진단도 없다.

### 5. RFC-0057 §Guide-level Explanation — `send`가 없는 호출의 문단 (치환 후 최종 텍스트)

`send`가 없는 호출의 본문은 실행 입력에서 Password 계열 필드(RFC-0063 §1)를 뺀
것이다. 입력에 그런 필드가 없으면 이 RFC 이전과 바이트까지 같다.

### 6. RFC-0057 §Reference-level Specification/4. 런타임 본문 구성 (치환 후 최종 텍스트)

`interp.py`의 `Interpreter._assemble_mapped_payload(payload_map, payload, bindings)`가
RFC-0049 §4의 조립을 그대로 한다: 각 참조를 `resolve_reference`로 해석하고, 참조 종류에
맞는 엔티티 뷰로 필드 단위 `mask_payload`를 통과시키고, 값이 없는 optional 필드는
생략한다(RFC-0053). `EventEmit`과 `NetworkCall`이 같은 메서드를 부른다.

`NetworkCall`에 `bodyMap`이 있으면 그 결과가 `NetworkDriver.call`의 `payload` 인자다.
없으면 실행 입력 `payload`에서 Password 계열 필드의 키를 뺀 것을 넘긴다 —
`omit_masked_fields(payload, self._input_masked_names())`(RFC-0063 §1, §2). 뺄 키가
없으면 `payload` 객체를 그대로 넘긴다. `NetworkDriver` 계약(RFC-0027 §1,
RFC-0037)은 바뀌지 않는다.

### 7. RFC-0057 §Reference-level Specification/5. 호환성 (치환 후 최종 텍스트)

`send`가 없는 모든 기존 소스는 같은 IR(`bodyMap` 키 없음)과 같은 골든을 낸다. 본문
바이트는 입력에 Password 계열 필드(RFC-0063 §1)가 없으면 같고, 있으면 그 키가 빠진다
— 호환성 변경이며 CHANGELOG에 적는다(issue #214). 이전에 `call X send ...`는 trailing
단어 거부로 컴파일 에러였으므로 새로 받아들이는 형태가 기존 프로그램의 뜻을 바꾸지
않는다.

`send`가 없을 때 "본문이 입력 전체다"를 알리는 info 진단은 **더하지 않는다**.
RFC-0049가 plain `emit`(마스킹된 입력 전체)에 같은 선택을 했고, 모든 기존 `call` 줄에
새 진단을 띄우는 것은 이 이슈의 완료 기준에 없는 넓은 파급이다.

### 8. RFC-0057 §Reference-level Specification/8. 이 RFC에 없는 것 (치환 후 최종 텍스트)

- **spec의 보낸 본문 단언** (`expect called <Target> body ...`, D11) — 더하지 않는다.
  RFC-0049도 발행된 payload 단언을 더하지 않았다. 실제 HTTP 기록 서버 테스트가 보낸
  바이트를 그대로 검증한다. 새 문법·IR·어휘 다이제스트 변경이 필요한 일이므로 별도
  RFC의 몫이다.
- **기본 본문의 Password 누출** (D13) — RFC-0063이 닫았다. `send` 없는 호출의 본문은
  Password 계열 입력 필드를 뺀다.
- **경로 인자의 Password 값** — `call PaymentGateway with input.secret`처럼 `with`가
  Password 계열 참조를 가리키면 컴파일 거부한다(issue #218, RFC-0057 §3 규칙 4). 값이
  요청 경로에 치환되는 일은 없다.
- 중첩 본문, 필드별 이름 바꾸기, 조건부 필드, 헤더·쿼리 문자열 매핑.

## Examples

골든 시나리오 "Login"은 아웃바운드 호출을 선언하지 않으므로(RFC-0007 §6) 이 RFC의
예제는 Login 참조를 그대로 둔다. 새 `examples/*.lnpl` 파일은 더하지 않는다.
`impl/tests/test_network_body_mapping.py`가 아래 경우를 fake 드라이버와 실제 로컬
HTTP 서버로 실행한다.

| 엔티티 선언 | 입력 | 보낸 본문 |
|---|---|---|
| `Customer`: `id UUID`, `secret Password` | `{"id": "c-1", "secret": "..."}` | `{"id": "c-1"}` |
| `Order`(`secret` 없음) 먼저, `Customer`: `secret Password` 나중 | `{"id": "c-1", "secret": "..."}` | `{"id": "c-1"}` |
| `Order`: `secret Text`, `Customer`: `secret Password` | `{"id": "c-1", "secret": "..."}` | `{"id": "c-1"}` |
| `refine ApiKey of Password`, `Customer`: `token ApiKey` | `{"id": "c-1", "token": "..."}` | `{"id": "c-1"}` |
| `Customer`: `id UUID`, `tier Text` | `{"id": "c-1", "tier": "gold"}` | 같은 객체, 바이트 동일 |
| 엔티티 없음 | `{"id": "c-1", "note": "plain-note"}` | 같은 객체 |

## Alternatives

| 대안 | 기각 사유 |
|------|----------|
| 값을 `***`로 마스킹 | 사용자 결정(issue #214 제안 1)은 제외다. 상대는 의미 없는 문자열을 받고, 키가 남아 비밀값이 입력에 있었다는 사실이 드러난다 |
| 경고만 내고 동작 유지(issue #214 제안 2) | 기본 동작이 계속 누출한다 |
| 문서의 첫 엔티티만 보기(`_entity_node()`) | 누출한다: `Order`가 먼저, `secret Password`를 가진 `Customer`가 나중이면 `secret`이 원문으로 나간다 |
| 워크플로 바인딩이 가리키는 엔티티만 보기 | 실행 입력은 바인딩이 아니고, 호출만 있는 워크플로는 엔티티를 하나도 가리키지 않아 입력이 걸러지지 않는다 |
| 두 `NetworkDriver` 구현 안에서 거르기 | 같은 규칙을 두 곳에 두는 호출 지점별 마스킹이다 — RFC-0003 §Observability가 계약 위반이라 부르는 형태다 |
| `send`로 Password 값을 보내는 옵트인 | #43과 RFC-0049의 규칙(Password 계열 참조는 컴파일 거부)에 어긋난다 |

## Open Questions

1. **다른 출력 채널은 아직 첫 엔티티만 본다.** 워크플로 시작 로그, plain `emit`,
   `emit ... with`의 `input.<field>`, `lnpl serve` 응답은 `mask_payload(...,
   _entity_node())`로 마스킹한다(스윕: `grep -n "_entity_node()" impl/lnpl/interp.py
   impl/lnpl/wsgi.py` → 4건). 두 번째 이후 엔티티에만 선언된 Password 필드는 그
   채널들에 원문으로 남는다. 그 채널들을 `_input_masked_names()`로 옮기는 일은 별도
   이슈다.
2. **`send`/`emit ... with`의 같은 이름 공백.** 해결됨(issue #219): 그 거부는 이제
   그 이름을 선언한 모든 엔티티를 본다(§1).
3. **경로 인자.** 해결됨(issue #218): `with`의 Password 계열 참조는 컴파일 거부다(§8).

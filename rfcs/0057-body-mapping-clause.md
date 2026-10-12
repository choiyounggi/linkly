# RFC-0057: `call ... send` — 아웃바운드 본문 매핑 절

## Status

- Status: Draft
- Updates: RFC-0027 §Reference-level Specification/2 (`as` 결과 바인딩 문법)

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목한다. RFC-0027 머리의 `Updated-by:`는
§1(RFC-0037)만 가리킨다 — §2는 이번이 첫 갱신이다. 그 절의 "trailing 토큰 판정표"는
issue #109가 `with <ref>...`(경로 치환)를 RFC 없이 더한 뒤로 실제 동작과 어긋나 있었다
(표에는 `()`와 `("as", name)` 두 행뿐이다). 아래 §1이 `send`·`with`·`as` 셋을 함께 담은
그 표의 치환 후 최종 텍스트다(RFC-0007 §2.2 규칙 4, 자기완결). 이 RFC는 Draft이므로
RFC-0027에 `Updated-by:` 포인터를 달지 않는다(Accepted가 되는 시점의 일이다).

## Motivation

`call`/`request`가 외부로 보내는 본문은 **워크플로가 받은 원본 입력 payload 전체**다
(issue #200). `interp.py`는 실행 입력을 그대로 드라이버에 넘긴다:

```python
status, body, _headers = self.network.call(
    effect["target"], payload, remaining_ms, trace_headers,
    path_args=path_args)
```

```
workflow PlaceOrder
    create order as o
    set o.total to product.price * input.quantity     # 서버가 계산한 결제 금액
    call PaymentGateway as pay                         # 금액을 보낼 방법이 없다
```

- 계산된 `total`이 본문에 없다 — 결제 게이트웨이가 금액을 받지 못한다.
- 상대가 요구하지 않은 내부 필드(`customerId`, `status`)가 그대로 나간다.
- `call PaymentGateway with o.id o.total as pay`는 거부된다 — `with`는 issue #109부터
  URL 경로 치환 전용이다(`` `with` needs a `path` declared on capability http
  PaymentGateway to substitute into ``).

#101(method·auth), #109(retry·breaker·path), #76(응답 바인딩, RFC-0027)이 호출의
나머지 축을 다 열었고 **요청 본문만** 남았다. `emit`은 같은 문제를 RFC-0049(`emit ...
with`, `payloadMap`)로 이미 풀었다 — 이 RFC는 그 규칙을 아웃바운드 호출로 옮긴다.

## Guide-level Explanation

```
call <Target> [send <ref>...] [with <ref>...] [as <name>]
```

`send` 뒤의 각 참조가 보내는 본문의 한 필드가 된다. 필드 이름은 참조의 마지막 dot
세그먼트다(`o.total` -> `total`) — RFC-0049와 같은 규칙이다.

```
workflow PlaceOrder
    create order as o
    set o.total to input.quantity
    call PaymentGateway send o.id o.total as pay
```

결제 게이트웨이는 `{"id": <o.id>, "total": <계산된 값>}`만 받는다. 입력의 다른 필드는
나가지 않는다.

세 절은 **이 순서로만** 쓴다: `send`, `with`(경로), `as`(결과 바인딩). 각 절은
선택이다. `with`와 `as`의 뜻과 둘 사이의 순서는 이 RFC 이전과 같다 — `send`가 그
앞에 들어갈 뿐이다:

```
call PaymentGateway send o.id o.total with o.id as pay   # 허용
call PaymentGateway with o.id send o.id                  # 컴파일 에러 — 순서
```

`send`가 없는 호출은 이 RFC 이전과 바이트까지 같다: 본문은 여전히 실행 입력 전체다.

참조 규칙은 RFC-0049 `emit ... with`와 같다. 허용: 바인딩된 행의 선언된 필드(`set`으로
채운 값 포함), `input.<field>`, 앞선 `call ... as <name>`의 결과 필드. 컴파일 거부:
맨 이름, 선언되지 않은 바인딩, Password 계열 필드, 같은 필드 이름 두 번, 앞선
`set`/`format`이 없는 `derived` 필드. RFC-0055의 실행이 채우는 필드(`derived
generated`/`derived clock`)는 `create`가 언제나 채우므로 그대로 쓸 수 있다.

`with <ref>...`의 경로 인자도 Password 계열 참조를 같은 판정으로 컴파일 거부한다(issue
#218) — 맨 이름(`with secret`)은 실행 시점에 같은 이름의 입력 필드로 풀리므로
`input.secret`과 같이 판정한다. `input.<field>`의 Password 계열 판정은 그 이름을 선언한
모든 엔티티를 본다(issue #219, §3 규칙 4).

## Reference-level Specification

### 1. 문법과 고정 순서 — RFC-0027 §2 갱신 (치환 후 최종 텍스트) (D1, D2, D3)

`send`는 `lexer.RESERVED`에 넣지 않는다. `as`·`with`와 마찬가지로
`lower._derive_effect`의 `NetworkCall` 분기가 `call`/`request` 스텝 줄의 trailing
위치에서만 닫힌 낱말로 읽는다. 그 밖의 문맥에서 "send"는 여느 단어와 같다.

`with`를 다시 쓰지 않는 이유: `call X with a`는 이미 경로 치환이다(issue #109). 같은
낱말에 본문 뜻을 더하면 `call X with a`가 경로인지 본문인지 문맥 없이 읽을 수 없다.

`NetworkCall` 분기는 `tokens[2:]`를 표지 낱말(`send`·`with`·`as`)로 구간을 나눈다.
표지의 순위는 `send`=0, `with`=1, `as`=2이고, 각 표지는 앞 표지보다 순위가 높아야
한다. 판정표:

| `tokens[2:]` | 판정 |
|---|---|
| `()` (없음) | 바인딩·경로·본문 매핑 없음 — RFC-0027 §3의 "바인딩 없는 호출" 그대로(후방 호환, 노드 모양 불변) |
| `send <ref>...` | `bodyMap`을 노드에 싣는다(§2) |
| `with <ref>...` | `path_args`를 노드에 싣는다(issue #109 — 대상 capability의 `path` `{}` 개수와 참조 개수가 같아야 한다). 참조가 Password 계열이면 컴파일 거부한다(issue #218, §3 규칙 4의 판정) |
| `as <name>` | `name`이 아래 두 검사를 통과하면 `result=name`을 싣는다 |
| 위 셋의 부분집합을 `send`, `with`, `as` 순서로 | 각 절의 판정을 모두 적용한다 |
| 표지가 아닌 낱말로 시작 | `LowerError` — `line %d: call/request accepts trailing clauses 'send <ref>...', 'with <ref>...', 'as <name>' in that order, got %r` |
| 표지의 순서가 어긋남 또는 같은 표지 두 번 | `LowerError` — `line %d: call/request's clauses must appear in the fixed order send, with (path), as -- %r cannot follow a clause of equal or later rank` |
| `send` 뒤 참조 0개 | `LowerError` — `` line %d: `send` needs at least one reference `` |
| `with` 뒤 참조 0개 | `LowerError` — `` line %d: `with` needs at least one reference `` |
| `as` 뒤 이름이 정확히 하나가 아님 | `LowerError` — `` line %d: `as` needs exactly one name ('as <name>'), got %r `` |

**`name`의 두 가지 컴파일 시점 검사** (둘 다 `LowerError`, rc=2) — RFC-0027 §2
원문 그대로다:

1. **형태.** `name`은 camelCase(`[a-z][a-zA-Z0-9]*`)여야 한다 — `<name>.status`가
   유효한 `Reference`(RFC-0012 §G12.1)가 되려면 필요한 형태다.
2. **이름 충돌.** `name`은 이 모듈에 선언된 어떤 Entity의 camelCase 바인딩 이름과도
   같을 수 없다 — `<name>.field`가 어느 바인딩을 읽는지 결정할 방법이 없어진다.

**스키마.** `nodeNetworkCall`의 선택 필드는 `result`(RFC-0027), `path_args`(issue
#109), `bodyMap`(§2)이다. `required`는 바뀌지 않는다.

### 2. `bodyMap` IR 모양 (D4)

`schemas/lir.schema.json`의 `nodeNetworkCall.bodyMap`은
`nodeEventEmit.payloadMap`(RFC-0049 §2)과 같은 모양이다:

```json
"bodyMap": {
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "field": {"type": "string"},
      "ref": {"type": "string"}
    },
    "required": ["field", "ref"],
    "additionalProperties": false
  }
}
```

저자가 쓴 `send` 순서 그대로인 `{"field", "ref"}` 객체의 순서 있는 배열이다. `field`는
언제나 `ref`의 마지막 dot 세그먼트다. `send`가 없는 호출은 이 키 자체를 생략한다. 단일
객체 map이 아니라 배열인 이유는 RFC-0049 §2와 같다(JSON 객체 키 순서는 데이터 모델이
아니고, 중복 필드명이 조용히 덮어써지지 않고 탐지 가능한 입력으로 남는다).

### 3. 정적 검사 (D5, D6, D7)

새 검사 함수를 만들지 않는다. RFC-0049의 두 검사를 두 절이 함께 쓴다:

- **문법 시점** — `lower._build_payload_map(arg_tokens, lineno, clause_label)`:
  참조 0개 거부, 각 토큰이 camelCase 또는 `binding.field` 형태인지, 같은 매핑 필드명이
  두 번 나오는지(`` `send` maps field %r from both %r and %r -- each mapped field
  name must be unique ``). `emit ... with`와 `call ... send`가 같은 함수를 부른다.
- **스코프 시점** — `lower._check_payload_map(payload_map, scope, workflow_name,
  base_of, derived_assigned, guard_key, line, verb_label)`(RFC-0049의
  `_check_emit_payload`를 이름만 바꾸고 메시지용 `verb_label`을 더한 것).
  `_check_scoped_conditions`가 `EventEmit`에는 `"emit with"`, `NetworkCall`에는
  `"call/request send"`로 부른다. 항목마다:
  1. `"." not in ref` -> `LowerError`(맨 이름).
  2. `scope.resolve_field(ref, ...)` — 선언되지 않은 바인딩이면 그 함수가 직접
     `LowerError`를 낸다(`... is not a declared entity ...`). `None`이면 네트워크 결과
     바인딩(`call ... as <name>`)이다 — 선언된 형태가 없으므로 무검사로 허용한다.
  3. `derived` 필드: RFC-0055의 실행이 채우는 필드(`field["fill_source"]`가 있음)면
     허용한다 — `create`가 언제나 채우고 `set`/`format`으로는 채울 수 없으므로 가드
     스코프 조건이 없다. 아니면 같은 `<binding>.<field>`를 채우는 `set`/`format`이
     같은 가드 스코프에서 앞서 있을 때만 허용한다(issue #204). 없으면 `LowerError`.
  4. 참조가 Password 계열이면 `LowerError`(issue #43, `respond`·`emit ... with`와 같은
     규칙). `<binding>.<field>`는 그 행 엔티티가 선언한 필드 타입의 base로,
     `input.<field>`는 그 이름을 선언한 모든 엔티티 중 하나라도 base가 `Password`인지로
     판정한다(issue #219 — 마지막에 선언한 엔티티 하나만 보지 않는다).

3번의 실행이 채우는 필드 허용은 두 절에 함께 적용된다 — `emit ... with o.id`(`id`가
`derived generated`)도 이제 허용된다. 같은 함수를 쓰는 이상 한쪽만 허용할 근거가 없다.

`with <ref>...` 경로 인자(issue #218): 의미 시점의 `NetworkCall` 검사가 `path_args`의 각
참조에 규칙 4의 Password 계열 판정만 적용한다(라벨 `call/request with`, 메시지 끝은
"in an outbound request path"). 맨 이름(`with secret`)은 실행 시점에 같은 이름의 입력
필드로 풀리므로 `input.secret`과 같은 판정을 받는다. 그 밖의 `with` 검사(모양, `{}` 개수)는
그대로다. 선언되지 않은 입력 필드, 알 수 없는 바인딩, 네트워크 결과, `caller` 참조는 이
판정에서 Password 계열이 아니다 — 새 거부 종류를 더하지 않는다.

### 4. 런타임 본문 구성 (D8, D9)

`interp.py`의 `Interpreter._assemble_mapped_payload(payload_map, payload, bindings)`가
RFC-0049 §4의 조립을 그대로 한다: 각 참조를 `resolve_reference`로 해석하고, 참조 종류에
맞는 엔티티 뷰로 필드 단위 `mask_payload`를 통과시키고, 값이 없는 optional 필드는
생략한다(RFC-0053). `EventEmit`과 `NetworkCall`이 같은 메서드를 부른다.

`NetworkCall`에 `bodyMap`이 있으면 그 결과가 `NetworkDriver.call`의 `payload` 인자다.
없으면 지금과 똑같이 실행 입력 `payload`를 **그대로**(마스킹 없이) 넘긴다 — 새 분기를
타지 않는다. `NetworkDriver` 계약(RFC-0027 §1, RFC-0037)은 바뀌지 않는다.

### 5. 호환성 (D9, D10)

호환성 파괴 없음. `send`가 없는 모든 기존 소스는 같은 IR(`bodyMap` 키 없음), 같은
골든, 같은 본문 바이트를 낸다. 이전에 `call X send ...`는 trailing 단어 거부로 컴파일
에러였으므로 새로 받아들이는 형태가 기존 프로그램의 뜻을 바꾸지 않는다.

`send`가 없을 때 "본문이 입력 전체다"를 알리는 info 진단은 **더하지 않는다**.
RFC-0049가 plain `emit`(마스킹된 입력 전체)에 같은 선택을 했고, 모든 기존 `call` 줄에
새 진단을 띄우는 것은 이 이슈의 완료 기준에 없는 넓은 파급이다.

### 6. mode B (D12)

**결정: mode B 코드는 바뀌지 않는다 — `send`는 mode B에서 지원된다.** RFC-0027 §8이
`result` 필드에 대해 실측한 것과 같은 자리다: `backend._render_std`는 `NetworkCall`의
kind와 target만 구조적으로 내고 노드의 다른 필드를 읽지 않으며, mode B는 실제 HTTP
호출도 fake 스텁 조회도 하지 않는다. `differential`의 관측 비교도 네트워크 본문을 보지
않는다. 그래서 `bodyMap`은 mode B가 거부할 이유도 갈라질 표면도 없다 —
`_refuse_unsupported_guards`(money, lookup, optional, text, fill-source, fail)와
`differential.verify`의 거부 사슬에 새 항목이 없고, `lnpl build`와 `lnpl diff`가 같은
순서를 지킨다(issue #185). `send`를 쓰는 워크플로에 대해 `backend.build`가 성공하고
`differential.verify`가 `ok=True`를 내는 테스트가 이를 고정한다.

### 7. 가드 스코프 읽기 (D18)

`send`의 참조도 바인딩을 읽는 자리다. `lower._check_guard_scoped_binding_reads`
(`guard-scoped-binding-escape` 경고, issue #198)는 `EventEmit`의 `payloadMap`처럼
`NetworkCall`의 `bodyMap`도 읽는다 — 가드 안에서만 묶인 바인딩을 그 가드 밖의 `call
... send`가 읽으면 경고한다. 메시지는 스텝의 앞 두 낱말로 `` `call PaymentGateway ...
send` ``처럼 그린다.

### 8. 이 RFC에 없는 것

- **spec의 보낸 본문 단언** (`expect called <Target> body ...`, D11) — 더하지 않는다.
  RFC-0049도 발행된 payload 단언을 더하지 않았다. 실제 HTTP 기록 서버 테스트가 보낸
  바이트를 그대로 검증한다. 새 문법·IR·어휘 다이제스트 변경이 필요한 일이므로 별도
  RFC의 몫이다.
- **기본 본문의 Password 누출** (D13) — `send` 없는 호출은 실행 입력 전체를 마스킹 없이
  보내므로, Password 계열 입력 필드의 원문이 본문에 실린다(실측:
  `impl/tests/test_network_body_mapping.py`의
  `PasswordInDefaultBodyMeasurementTest`). 기본 본문을 바꾸는 것은 이 RFC의 범위가
  아니다(§5) — 별도 이슈로 다룬다.
- 중첩 본문, 필드별 이름 바꾸기, 조건부 필드, 헤더·쿼리 문자열 매핑.

## Examples

골든 시나리오 "Login"은 아웃바운드 호출을 선언하지 않으므로(RFC-0007 §6) 이 RFC의
예제는 Login 참조를 그대로 둔다. 이 RFC는 새 `examples/*.lnpl` 파일을 더하지 않는다 —
§Guide-level Explanation의 `PlaceOrder`가 예제이고,
`impl/tests/test_network_body_mapping.py`가 그것을 실제 로컬 HTTP 서버로 실행한다.

컴파일 거부 예:

```
call PaymentGateway with o.id send o.total     # 순서 — send는 with 앞
call PaymentGateway send customer.secret       # Password 계열
call PaymentGateway send o.total p.total       # 같은 필드 이름 total 두 번
call PaymentGateway send total                 # 맨 이름
```

## Alternatives

| # | 검토한 대안 | 기각 사유 |
|---|------------|----------|
| 1 | 본문에도 `with`를 쓴다 | `call X with a`는 issue #109부터 경로 치환이다. 같은 낱말에 두 뜻을 주면 `call X with a`를 문맥 없이 읽을 수 없다 |
| 2 | `send`를 `as` 뒤(맨 끝)에 둔다 | 이슈가 제안한 문법은 `send`가 앞이다. 기존 `with`/`as`의 상대 순서와 "`as <name>`이 마지막" 관례를 그대로 두려면 앞에 넣는 편이 바꾸는 것이 적다 |
| 3 | `bodyMap`을 단일 객체 map(`{"id": "o.id"}`)으로 정한다 | RFC-0049 §Alternatives 2와 같은 이유 — 저자의 순서를 실을 수 없고 중복 필드명이 조용히 덮어써진다 |
| 4 | `call ... send` 전용 검사 함수를 따로 쓴다 | `emit ... with`와 같은 규칙의 두 번째 사본이 생겨 두 절이 시간이 지나며 갈라진다. 한 함수를 두 절이 부른다 |
| 5 | spec에 보낸 본문 단언을 더한다 | §8 — RFC-0049와 같은 선택. 기록 서버 테스트가 이미 전체 바이트를 검증한다 |
| 6 | `send` 없는 호출의 본문도 마스킹한다 | 모든 기존 프로그램의 아웃바운드 바이트를 바꾸는 호환성 파괴다(§5). 누출은 실측해 별도 이슈로 넘긴다(§8) |

## Open Questions

없음 — 이 RFC가 다루는 질문은 위에서 모두 결정했다.

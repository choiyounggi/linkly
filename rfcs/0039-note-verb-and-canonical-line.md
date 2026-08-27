# RFC-0039: `note` 동사와 canonical log line 확장

## Status

- Status: **Accepted** (RFC-0039, 2026-08-27)
- Updates: 없음 — `note`는 새 동사 하나를 `VERB_LEXICON`에 더할 뿐, 기존 RFC가
  확정한 문법·의미를 고치지 않는다(RFC-0007 §2.2 규칙 4의 "치환"이 필요 없는
  순수 추가). canonical log line의 신규 3필드(`notes`/`effects`/
  `input_digest`)도 issue #78/#107/#123이 이미 정한 필드 목록에 뒤이어
  덧붙을 뿐, 기존 필드의 순서·값을 바꾸지 않는다(§Reference-level
  Specification/6).

번호가 0039인 이유: 0038까지 점유됐다(RFC-0038, `list where`). RFC-0007 §3은
번호 재사용을 금지한다.

## Motivation

`VERB_LEXICON` 20개 동사에 로그를 남기는 동사가 없다 — `lnpl-authoring`의
`verbs.md`가 명시하는 대로, `return`/`log`/`send`/`notify`/`verify`처럼
자연스러워 보이는 낱말은 전부 아무 효과가 없다. `Trace.log()` 호출자는
전부 인터프리터 내부이고 저자 코드에서 도달할 수 있는 경로가 0이다.

이 설계 자체는 옳다 — 저자가 로그를 오염시킬 수 없으니 "불필요한 로그 없이
딱 필요한 로그만"이 구조적으로 보장된다. 문제는 그 반대편이다. `--log-format
json` 한 줄에 남는 정보가 스텝 이름과 마스킹된 skipped/diagnostics뿐이라,
사후에 버그를 추적하는 LLM에게 두 가지가 없다:

1. **도메인 맥락** — "왜 이 분기로 갔나". `skipped[].evaluations`(issue #83)가
   가드 비교값을 싣지만, 가드가 아닌 판단(어떤 엔티티를 왜 골랐는지 등)은
   흔적이 없다.
2. **재현 입력** — 실패한 실행의 입력 payload가 trace에 없다. `failure_reason`
   문자열 하나로 재현해야 한다.

[Stripe의 canonical log lines](https://stripe.com/blog/canonical-log-lines)는
요청/작업당 **정확히 한 줄**의 넓은 구조화 레코드를 낸다 — 목표는 사람
가독성이 아니라 **질의 가능성**이고, Ruby `ensure` 블록으로 감싸 예외가 나도
반드시 한 줄이 나가게 한다. [Wide events / Honeycomb 계열의
관찰](https://baselime.io/blog/canonical-log-lines)도 같은 형태를 권한다 —
여러 줄을 질의 시점에 짜맞추지 않으므로 인시던트 중 스트레스 상태에서도 쓸 수
있는 질의가 된다. [OpenTelemetry span
attributes/events](https://opentelemetry.io/docs/concepts/context-propagation/)는
자유 로그가 아니라 span에 붙는 구조화 어노테이션이다 — 키-값이지 문장이 아니다.

linkly는 이미 canonical log line 형태(`_emit_request_log`, issue #78)를 갖고
있다. 필요한 건 그 줄을 넓히는 것과, 저자가 거기에 구조화된 값을 더할 **좁은
통로** 하나다 — 자유 로그가 아니라 span 어노테이션.

`trace_id`/`span_id`(issue #107/#123)는 이미 이 줄에 실려 있다 — 이 RFC의
대상이 아니다.

## Guide-level Explanation

저자가 새로 쓸 수 있게 되는 것은 워크플로 스텝 하나다:

```
note "picked-tier-{}-for-{}-orders" with customer.tier order.count
```

`note "<template>" [with <ref>...]` — `format`의 저장 표현식 문법과 글자
그대로 같다(`{}` 개수와 `with` 인자 개수가 일치해야 한다). 다른 점은 대상이
없다는 것뿐이다: `format`은 값을 필드에 쓰지만, `note`는 아무것도 쓰지 않고
현재 span에 어노테이션 하나를 남긴다.

```
capability postgres

entity Order
    field
        id UUID
        tier Text
        count Integer

entity Customer
    field
        id UUID
        tier Text
        secret Password

service Orders
    policy
        retry 0

workflow LabelOrder
    find order
    find customer
    note "picked-tier-{}-for-{}-orders" with customer.tier order.count
```

`--log-format json`으로 이 워크플로를 실행하면 canonical line에 다음이
실린다:

```json
{
  "correlation_id": "req-...", "method": "POST", "path": "/orders/label-order",
  "workflow": "wf.label.order", "status": 200, "duration_ms": 1.2,
  "skipped": [], "diagnostics": [],
  "trace_id": "...", "span_id": "...",
  "notes": [{"template": "picked-tier-{}-for-{}-orders", "values": ["gold", 3]}],
  "effects": {"RepositoryCall": 2},
  "input_digest": "4a3f..."
}
```

`note`는 자유 로그가 아니다: 레벨을 지정할 수 없고(항상 현재 span에 붙는다),
임의 출력 스트림도 없다. 참조가 가리키는 값이 Password 계열이면 기존
`mask_payload` chokepoint(issue #43)를 그대로 통과해 마스킹된 채로만 실린다
— 두 번째 마스킹 규칙을 만들지 않는다. 워크플로당 `note`가 16개를 초과하면
컴파일이 실패하는 게 아니라 `note-cap-exceeded` 경고가 난다 — "필요한 로그만"
을 어휘 차원에서 지키되, 그 상한을 넘었다고 프로그램이 컴파일되지 않을
이유는 없다.

실패한 실행의 재현을 돕기 위해 `lnpl serve --capture-on-failure`를 켜면,
**실패/500으로 끝난 실행에 한해** canonical line에 마스킹된 입력 payload
전문이 실린다. 기본은 off — 성공 경로까지 payload를 실으면 로그 비용이
그 한 줄이 지배하게 되고, 마스킹을 통과했어도 PII 노출면이 넓어진다.

## Reference-level Specification

### 1. 표면 문법 — `VERB_LEXICON`/`EFFECT_SLUG`에 추가 (D1/D2)

```
StepLine ::= 'note' StringLiteral ('with' Reference+)?
```

템플릿과 `with` 절은 `condition._parse_format_rhs`(issue #94가 `format`의
저장 표현식 재-파싱을 위해 낸 함수)를 **그대로 재사용**한다 — 새 파서를
만들지 않는다. `_parse_format_rhs` 자신은 `{}` 개수 검사를 하지 않으므로(이미
검증된 표현식을 재-읽는 용도라서), `note`를 lower하는 `_derive_note`가
`_check_placeholder_count`를 직접 호출해 그 검사를 재현한다 — `parse_format`이
저자 대면 `format` 문법에 대해 하는 것과 같은 호출이다.

```python
VERB_LEXICON["note"] = ("Annotation", {})
EFFECT_SLUG["Annotation"] = "note"
```

`Annotation`은 아홉 개 Effect kind에 들지 않는다 — `respond`가 `Response`를
따로 받은 것(issue #96)과 같은 판단이다: 상태를 바꾸지 않는다.

### 2. `Annotation` IR 노드 (D2)

```json
{"kind": "Annotation", "id": "wf.label.order.step.3.note",
 "template": "picked-tier-{}-for-{}-orders",
 "refs": ["customer.tier", "order.count"], "line": 14}
```

`refs`는 `with` 절의 Reference를 소스 순서대로 담은 문자열 목록이다 —
`respond`의 `refs` 필드와 같은 모양. `template`은 따옴표를 벗긴 문자열.
`{}` 0개 + `with` 절 없음(0 인자)은 컴파일 에러가 아니다 — 순수 체크포인트
노트(`note "reached-the-tier-check"`)로 허용된다. 이는 `format`과 다르다:
`format`은 대상 필드에 값을 쓰는 것이 목적이므로 `{}` 없는 템플릿도 의미가
있지만(정적 문자열을 필드에 쓴다), `note`는 애초에 아무것도 쓰지 않으므로
"의미 없음" 판정 자체가 없다 — 런타임에 실제로 trace에 실리는 한 인자가
있든 없든 유효하다.

### 3. 상한 진단 — `note-cap-exceeded` (D3)

```python
NOTE_CAP = 16

def _check_note_cap(emitted, workflow_name, diagnostics):
    count = sum(1 for node in emitted if node["kind"] == "Annotation")
    if count > NOTE_CAP:
        diagnostics.add(code="note-cap-exceeded", where=workflow_name,
                        subject=workflow_name, message=...)
```

`_check_derived_never_assigned`류의 기존 워크플로-스코프 검사와 같은 자리
(`lower()`의 워크플로 루프, 매 워크플로 처리 뒤)에서 실행된다. `CODES`/
`SEVERITY_OF`에 `"note-cap-exceeded": "warning"`으로 등록 — RFC-0021의
"프로그램을 고치면 사라지는가" 질문에 그렇다로 답하므로(`note`를 16개 이하로
줄이면 사라진다) `warning`, `unknown-verb`와 같은 등급이다. 컴파일은
계속되고 워크플로는 정상 실행된다 — 상한 초과는 경고이지 거부가 아니다.

### 4. 런타임 실행 — 해석·마스킹·null (D4)

`interp.py`의 `_run_effect`는 `Annotation` kind에서 아무것도 하지 않는다
(`Response`와 같은 no-op 분기) — 실제 해석은 `run_workflow`의 스텝 루프가,
그 스텝의 `_run_step`이 반환한 **직후**(그 스텝이 아직 나중 스텝에 덮어써지지
않은 시점의 `bindings`를 보고) 수행한다:

```python
notes.append({"template": child["template"],
             "values": _note_values(self, child["refs"], payload, bindings)})
```

`_note_values`는 각 참조를 `resolve_reference`(RFC-0012 §G12.1이 정한 유일한
리졸버)로 해석한 뒤, 참조가 선언된 엔티티의 Password 계열 필드를 가리키면
`mask_payload`로 마스킹한다 — `_masked_evaluation`(issue #83)이 가드 평가값에
이미 적용하는 것과 같은 chokepoint, 세 번째 호출부일 뿐 두 번째 규칙이
아니다. 해석 실패(미바인딩 참조, 즉 그 `find`/`create` 스텝을 가드가
건너뛴 경우 등)는 실행 실패가 아니라 값 `null`이다 — 관측 채널이 실행을
죽이면 안 된다는 것이 이 필드의 존재 이유 자체와 모순되기 때문이다.

`result["notes"]`는 `result["emissions"]`(issue #102)과 같은 규약이다:
추가적(additive)이고, `note`가 없는 워크플로는 이 키 자체가 없다(회귀 없음).
`status == "completed"`에 게이트되지 않는다 — 실패로 끝난 실행이야말로
`note`가 가장 필요한 순간(§Motivation)이므로, 실패한 스텝 이전에 성공한
스텝의 note는 남아야 한다.

### 5. `effects` 목록에서 제외 (D5)

`result["steps"][].effects`(자식 kind 나열)에서 `Annotation`만 필터한다 —
`Response` 등 기존 나열은 바이트 그대로 둔다(회귀 면적 최소화, `Response`가
런타임 effects 나열에서 이미 카운트되는 기존 동작은 이 RFC의 대상이 아니다).
`spec.py`의 `effects <N>` 어서션은 이 필터된 목록의 길이를 합산하므로,
`note`는 그 총합을 움직이지 않는다. `effects complete`(모든 스텝이 Effect를
수행했는가)는 별개 어서션이며, `note`만 있는 스텝은 필터 후 effects 목록이
정말로 비므로 이 어서션은 여전히 그 스텝을 "Effect 없음"으로 정확히
잡아낸다 — 이는 결함이 아니라 `note`가 진짜로 Effect가 아니라는 사실 그대로다.

### 6. canonical line 3필드 (D6)

`_emit_request_log`가 기존 8개 필드(`correlation_id`/`method`/`path`/
`workflow`/`status`/`duration_ms`/`skipped`/`diagnostics`) + `trace_id`/
`span_id`(issue #107/#123, 조건부 포함) **뒤에** 3필드를 조건부로 덧붙인다
— 존재할 때만 싣는다, null 자리표시자가 아니다:

- `notes` — `result["notes"]`(§4).
- `effects` — 스텝별 필터된 effects 목록을 kind별로 합산한 dict
  (`{"RepositoryCall": 2, "EventEmit": 1}`).
- `input_digest` — 마스킹된 입력 payload의 안정 해시:
  `sha256(json.dumps(마스킹된_payload, sort_keys=True,
  separators=(",", ":"), ensure_ascii=False)).hexdigest()` — RFC 8785식
  canonical JSON의 최소 근사(정렬 키 + 공백 없음 + UTF-8). 값 자체가 아니라
  "같은 입력인가"를 판정하는 용도다. 마스킹은 워크플로 시작 trace 로그가
  이미 쓰는 chokepoint(`Interpreter._entity_node()` 기반 뷰)를 재사용한다 —
  세 번째 호출부.

payload가 없는 라우트(GET 등)는 세 필드 모두 생략된다 — `_respond`(POST/
워크플로 핸들러)만 `log_sink`에 이 값들을 채우고, GET은 애초에 `_respond`를
거치지 않는다.

### 7. `--capture-on-failure` (D7)

```python
serve(..., capture_on_failure=False)
```

기본 off. on이고 **실행이 실패/500으로 끝났을 때만** canonical line에
`input` 필드(마스킹된 payload 전문)가 실린다 — 성공한 실행은 on이어도 이
필드가 없다. CLI 플래그(`lnpl serve --capture-on-failure`)와 `serve()`
kwarg만 노출한다 — `lnpl.toml`(issue #114) 키 추가는 이 RFC의 범위 밖이다.

### 8. 예외 안전 (D8)

`_call_with_json_log`(json 로그 모드에서 POST/GET/기타를 디스패치하고
`_emit_request_log`를 호출하는 메서드)를 try/finally로 감싼다. 이전에는
SSE 경로(`_log_sse_then`)만 자신의 try/finally로 방출을 보장했고, POST/GET
경로는 본문이 확정된 뒤 한 번만 `_emit_request_log`를 호출했다 — `_respond`
자신이 처리하지 못하는 예외(즉 `_do_post`/`_do_get` 자신, 또는 `_respond`에
도달하기도 전인 라우팅/인증 단계에서 나는 예외)는 그 호출을 건너뛰고 그대로
전파돼, canonical line이 **한 줄도** 나가지 않았다. `logged` 플래그가 두
정상 분기(SSE로 넘기거나, 직접 방출하거나) 각각이 방출을 이미 보장했음을
표시하고, `finally`는 `logged`가 여전히 False일 때만(즉 둘 중 어느 정상
분기도 실행되지 못했을 때만) 방출한다 — SSE 경로를 이중 로깅하지 않는다.

## Examples

### 순수 체크포인트 노트 — `{}` 0개

```
workflow ReachedCheckpoint
    find order
    note "reached-the-tier-check"
```

`with` 절 없이 컴파일된다. 런타임에 `result["notes"]`에
`{"template": "reached-the-tier-check", "values": []}`가 실린다.

### 상한 초과 — 경고이지 거부가 아님

```
workflow TooManyNotes
    find order
    note "checkpoint-1"
    note "checkpoint-2"
    # ... 15개 더 ...
```

17개째 `note`부터 `note-cap-exceeded` 경고가 나지만 컴파일은 성공하고
워크플로는 정상 실행된다.

### Password 마스킹

```
entity Customer
    field
        id UUID
        secret Password

workflow CheckSecret
    find customer
    note "checked-secret-{}" with customer.secret
```

`result["notes"][0]["values"]`는 `["s3cret"]`이 아니라 `["***"]` — 마스킹된
채로만 trace에 실린다.

### `{}` 개수 불일치 — 컴파일 거부

```
workflow BadNote
    find order
    note "picked-tier-{}-for-{}-orders" with order.count
```

→ 컴파일 거부: `note` 템플릿의 `{}` 2개에 대해 `with` 인자가 1개뿐이다
(`_check_placeholder_count`, `format`과 완전히 같은 에러 메시지 형식).

## Alternatives

| # | 검토한 대안 | 기각 사유 |
|---|------------|----------|
| 1 | **자유 로그 동사를 낸다**(`log <level> "<msg>"`처럼 레벨·임의 텍스트를 받는다) | §Motivation의 핵심 통찰과 정면으로 배치된다 — linkly가 "일관되게 쓸모없는 로그가 아니라 일관되게 유용한 로그"를 낼 수 있는 유일한 이유는 로그 형태를 언어가 소유하기 때문이다. 레벨·임의 스트림을 열면 저자 규율에 다시 의존하게 되고, LLM이 생성한 코드가 로그를 너무 적게/많이 남기는 자바·파이썬의 실패 모드를 그대로 들여온다 |
| 2 | **`note`의 템플릿에 새 파서를 만든다** | `format`이 이미 정확히 필요한 문법(`{}` 위치 인자 + `with` 절)을 갖고 있는데 두 번째 파서를 만들면 두 문법이 조용히 갈라지는 결함 계열(RFC-0008 §Motivation)을 새로 연다. `_parse_format_rhs` 재사용이 이슈 #111 제안 자체가 명시한 설계다 |
| 3 | **참조를 컴파일 타임에 엔티티/필드로 검증한다**(`respond`처럼) | `respond`는 응답 바디를 조립하므로 미선언 참조가 곧 깨진 API 계약이지만, `note`는 관측 채널일 뿐이다. 컴파일 타임에 거부하면 저자가 나중에 `find`를 추가할 계획인 엔티티를 미리 언급하는 흔한 패턴(가드로 나중에 조건부 실행)을 막는다 — 런타임 `null`이 정확히 그 유연성을 유지하면서도 관측이 실행을 절대 죽이지 않는다는 §Motivation의 요구를 만족한다 |
| 4 | **`note`를 하나의 Effect kind로 취급한다**(아홉 Effect 중 하나로) | `note`는 상태를 바꾸지 않는다 — `respond`가 이미 세운 "효과 없는 kind는 Effect가 아니다" 원칙(issue #96)을 뒤집을 이유가 없다. Effect로 취급하면 `effects <N>` 카운트가 매 `note` 추가마다 흔들려, DoD 5가 막으려는 바로 그 회귀를 스스로 만든다 |
| 5 | **`--capture-on-failure`를 기본 on으로 한다** | 성공 경로까지 payload를 실으면 canonical line이 로그 비용을 지배하고, 마스킹을 통과했어도 PII 노출면이 실행마다 넓어진다 — 이슈 #111 제안 3이 명시적으로 기본 off를 요구한다 |
| 6 | **`input_digest`를 RFC 8785 전체 구현으로 낸다** | payload는 이미 파싱된 JSON(부동소수점 정규화·유니코드 정규화 규칙이 요청 본문 자체가 갖지 않은 애매함을 새로 만들지 않는다)이므로, 정렬 키+공백 없음+UTF-8이라는 최소 근사로 "같은 입력인가"라는 이 필드의 유일한 목적을 충분히 만족한다. 전체 RFC 8785 구현은 이 필드가 풀어야 할 문제보다 큰 새 의존성이다 |

## Open Questions

1. **집계/히스토그램 노트.** 여러 실행에 걸친 `note` 값의 집계(예: "이
   워크플로가 tier=gold를 고른 비율")는 이 RFC의 범위 밖이다 — canonical
   line은 실행 하나당 한 줄이고, 집계는 그 줄들을 질의하는 쪽(로그 파이프라인)
   의 책임으로 남긴다.
2. **`note`가 가드 스킵 스텝 안에 있을 때.** 가드가 닫혀 `note` 스텝 자체가
   실행되지 않으면 그 note는 `result["notes"]`에 전혀 나타나지 않는다 —
   `respond`의 `response_refs`가 이미 쓰는 것과 같은 규약(스킵된 스텝은
   아무것도 기여하지 않는다)이라 이 RFC가 별도로 결정할 것이 없지만, 향후
   `skipped[]`가 "이 가드 밑에 note가 몇 개 있었다"를 함께 보고해야 하는지는
   후속 이슈로 이월한다.
3. **`--capture-on-failure`와 `lnpl.toml`.** issue #114의 설정 파일 키로
   승격할지는 이 RFC가 결정하지 않는다 — CLI 플래그로 먼저 내고, 운영
   경험이 쌓이면 후속 이슈가 설정 파일 노출 여부를 판단한다.

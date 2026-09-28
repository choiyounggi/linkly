# RFC-0049: `emit ... with`와 `payloadMap`

## Status

- Status: Draft
- Updates: RFC-0002 §Full grammar (`StepLine` 프로덕션 — `docs/CONSISTENCY-CHECK.md`
  발견 F5, 2026-09-28 기록)

번호가 0049인 이유: 0048까지 점유됐다(RFC-0048). RFC-0007 §3은 번호 재사용을
금지한다.

## Motivation

`schemas/lir.schema.json`의 `nodeEventEmit`은 RFC-0001이 이 노드를 처음 실은
때부터 선택적 `payloadMap` 필드를 갖고 있었지만, 지금까지 그 필드는 (1) 저자가
문법으로 채울 방법이 없었고 (2) `interp.py`가 읽지도 않았다 — 스키마에만 존재하는
죽은 필드였다(issue #178, `grep -rn "payloadMap" scripts/validate_ir.py
impl/tests/*.py schemas/*.json` -> 1건, 그 스키마 선언 자신뿐).

그 결과 `lower.py`의 `_derive_effect` `EventEmit` 분기는 `emit <Event>` 뒤에 오는
모든 trailing 단어(`rest`)를 조용히 버렸다: `emit orderPlaced foo bar`가 컴파일
성공하면서 `foo bar`는 아무 흔적도 없이 사라진다. 동시에 `interp.py`는 발행되는
payload로 **워크플로 입력 전체**를 (마스킹한 채로) 실었다 — 저자가 무엇을
발행할지 고를 수 없었다.

이 RFC는 `payloadMap`을 실제로 채우는 표면 문법 `emit <Event> with <ref>...`를
연다. `note ... with <ref>...`(RFC-0039)가 같은 절 모양을 이미 쓰고 있고, `call
... with <ref>...`(RFC-0037, 네트워크 호출 인자)도 마찬가지다 — `emit`이 세
번째 자리다.

## Guide-level Explanation

```
create order as newOrder
call OrdersApi as orderResult
emit orderPlaced with newOrder.id input.customerId orderResult.status
```

`emit <Event> with <ref> <ref>...` — `with` 뒤의 각 참조가 발행되는 이벤트
payload의 한 필드가 된다. 필드 이름은 참조 자신의 마지막 dot 세그먼트다
(`newOrder.id` -> `id`, `input.customerId` -> `customerId`) — RFC-0030 §4가
이미 세운 "동명 필드" 관례를 그대로 쓴다, 별도 개명 문법을 만들지 않는다.

참조는 셋 중 하나여야 한다:

1. `create ... as`/read 바인딩된 행의, `derived`가 아닌 선언된 필드
   (`newOrder.id`)
2. `input.<field>` — 이 실행의 입력값
3. `call ... as <name>`으로 바인딩된 네트워크 호출 결과 (`orderResult.status`)
   — 선언된 형태가 없으므로 무검사로 허용된다(`note`의 `_note_values`가 같은
   종류의 바인딩을 이미 이렇게 다룬다)

다음은 컴파일 거부다:

- **맨 이름** (`with unknownRef`) — 위 세 형태 중 어느 것과도 구분되지 않는다
- **`derived` 필드** (`with newOrder.total`, `total`이 `derived`) — 서버 계산
  전용이라 `create` payload로 시드되지 않는다(RFC-0030 §3); `set`/`format`이
  명시적으로 채우지 않는 한 값이 신뢰성 있게 존재한다는 보장이 없다
- **Password 계열 필드** (`with customer.secret`) — 마스킹 chokepoint(issue
  #43)를 `emit`으로 우회하는 경로를 막는다. `respond`가 이미 같은 규칙을 쓴다
- **같은 매핑 필드명을 두 번 쓰는 것** (`with newOrder.id otherRow.id` — 둘 다
  `id`) — 어느 쪽 값이 실리는지 저자도 읽는 사람도 알 수 없는 모호함을 컴파일
  타임에 없앤다
- **`with <ref>...`가 아닌 나머지 trailing 단어** (`emit orderPlaced foo bar`)
  — §Compatibility 참조. 이전에는 조용히 버려졌다

`with` 없는 `emit <Event>`는 이 RFC 이전과 완전히 동일하다: `payloadMap` 키
자체가 없고, 발행되는 payload는 여전히 마스킹된 입력 전체다.

## Reference-level Specification

### 1. 표면 문법

```
StepLine ::= 'emit' | 'publish' Reference ('with' Reference+)? EOL
```

(비형식 표기다 — 아래 "Updates: RFC-0002 §Full grammar"가 형식적 EBNF 수정을
싣는다.) `with`는 렉서 키워드가 아니다 — `note`/`call`과 같은 방식으로
`_derive_effect`의 `EventEmit` 분기 안에서 지역적으로 파싱되는 낱말이다.

### 2. `payloadMap` IR 모양

`schemas/lir.schema.json`의 `nodeEventEmit.payloadMap`:

```json
"payloadMap": {
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

저자가 쓴 `with` 절 순서 그대로인 `{"field", "ref"}` 객체의 **순서 있는
배열**이다. `field`는 언제나 `ref`의 마지막 dot 세그먼트이며 저자가 고르는
별도 이름이 아니다. `with` 절이 없는 `emit`은 이 키 자체를 노드에서 생략한다
(단일 객체 map이 아니라 배열을 고른 이유: JSON 객체 키 순서는 데이터 모델의
일부가 아니므로 저자의 `with` 순서를 안정적으로 실을 수 없고, 중복 필드명이
조용히 마지막 값으로 덮어써지는 대신 배열에서는 탐지 가능한 입력으로 남는다).

### 3. 정적 검사 규칙

새 함수 `_check_emit_payload(payload_map, scope, workflow_name, base_of)`가
`_check_scoped_conditions`의 기존 `Response`/`_check_respond` 호출 자리 옆에
`EventEmit` 형제 분기로 추가된다. 각 `{"field", "ref"}` 항목마다:

1. `"." not in ref` -> `LowerError` — 맨 이름은 세 허용 형태 중 어느 것과도
   구분되지 않으므로 거부한다(네트워크 결과 바인딩과 진짜 미바인딩 이름 둘
   다 `scope.resolve_field`가 `None`을 돌려주므로, 이 dot 검사가 먼저 실행돼야
   둘을 가른다).
2. 아니면 `scope.resolve_field(ref, ...)`를 호출한다. `None`이 돌아오면
   네트워크 결과 바인딩(`call ... as <name>`)이라는 뜻이고, 무검사로
   허용한다 — 선언된 형태가 없다.
3. 필드 딕셔너리가 돌아오면: `field.get("derived")`이면 `LowerError`(issue
   #95의 `derived` 플래그). 아니면 선언된 타입의 base가 `Password`이면
   `LowerError`(`_check_respond`와 같은 규칙, issue #43).
4. 중복 매핑 필드명은 문법 시점(`_derive_effect`, 스코프가 필요 없는 순수
   텍스트 검사)에 먼저 거부된다 — 같은 `with` 절 안에서 트레일링 세그먼트가
   겹치는 두 참조.

`emit orderPlaced with` (참조 0개)는 `LowerError`: "`with` needs at least one
reference".

### 4. 런타임 payload 구성

`interp.py`의 `Interpreter._run_effect` `EventEmit` 분기: `payloadMap`이
있으면, 각 `{field, ref}`를 `resolve_reference`(null-안전 유일 리졸버)로
해석하고 참조의 종류에 맞는 뷰로 필드 단위 `mask_payload`를 통과시킨 뒤
`{field: masked_value}`를 조립한다. `payloadMap`이 없으면 기존 동작
(`mask_payload(payload, self._entity_node())`, 마스킹된 입력 전체) 그대로다.
가드에 막혀 스킵된 바인딩을 가리키는 참조는 `resolve_reference`의 기존 계약대로
`null`로 해석된다 — 실행 실패가 아니다(정적 검사는 참조가 문서 안에서
무언가를 가리킨다는 것만 보장하지, 이 특정 실행에서 그 스텝이 실제로
실행됐다는 것을 보장하지 않는다). 네트워크 결과 참조는 마스킹할 선언된
엔티티 뷰가 없어 마스킹 없이 그대로 실린다 — 이 RFC가 여는 새 구멍이 아니라
`_note_values`가 이미 갖고 있던, 같은 종류의 바인딩에 대한 기존 한계다.

`emission["payload"]`는 두 경로 모두에서 평범한 `dict[str, Any]`로 남는다 —
`impl/lnpl/cli.py`의 outbox-relay CloudEvents 봉투를 포함해, 이 값을 불투명한
dict로 다루는 모든 기존 소비자는 변경이 필요 없다.

### 5. §Compatibility — trailing 단어 거부

**호환성 파괴 사항:** `emit <Event>` 뒤에 `with <ref>...`가 아닌 단어가 남으면
이제 `LowerError`다. 이전에는 `_derive_effect`가 `rest`를 전혀 검사하지 않아
조용히 버려졌다 — issue #178의 근본 결함 그 자체다.

경고 단계 없이 곧바로 거부를 적용한다. 이 저장소 자신의 전체 코퍼스를 훑은
결과(`analysis.md` "Corpus sweep" 참조): `.lnpl` 파일 62개 + `impl/tests/*.py`의
삼중따옴표 인라인 프로그램 198개 중 `emit`/`publish` 사용 15건, 그중 이 규칙에
걸리는 것은 **0건**이다 — 전부 `emit <Event>` 단독 형태다. 이 저장소 밖의
`.lnpl` 저자가 예전의 조용한 무시에 의존했을 가능성이 이 파괴의 실제 대상이며,
그 대상을 위해 이 절과 `CHANGELOG.md`가 기록을 남긴다.

### 6. §Mode B — MLIR/LLVM 백엔드

**결정: mode B 코드는 변경하지 않는다.** `backend.py`의 유일한 `EventEmit`
참조(`_lnpl_ops`, 재시도 자격 표지자)는 이미 `{"node_id", "kind"}`만 기록하고
노드 자신의 필드는 절대 읽지 않는다 — `payloadMap`뿐 아니라 `emit`이 예전부터
갖고 있던 어떤 payload도 mode B로 lowering된 적이 없다. `differential.py`의
`observe_mode_a`/`observe_mode_b`/`verify`도 발행된 이벤트의 payload를 오늘
읽지 않는다(`emission`/`outbox`/`EventEmit` 0건). 따라서 mode B의 비교 가능
표면은 `with` 유무와 무관하게 payload 내용을 포함하지 않는다 — 이는 이 RFC가
새로 만드는 격차가 아니라 기존에 이미 있던 격차를 이 기능이 그대로 물려받는
것이며, 조용한 공백이 아니라 결정된 상태로 이 절에 기록한다.

### `Updates: RFC-0002 §Full grammar` — 치환 후 최종 텍스트

RFC-0002의 `StepLine` 프로덕션은 다음과 같이 캡을 두었다:

```
StepLine ::= Verb Word? Word? Word? EOL
```

동사 뒤 최대 3단어라는 뜻이지만, 실제 렉서는 `Line.tokens = body.split()`로
무제한이며 이미 Accepted된 RFC-0037(`call OrdersApi with order.id order.sku as
r`, 6단어)과 RFC-0039(`note "..." with customer.tier order.count`, 4단어)의
`## Examples`가 이 캡을 넘는다(`docs/CONSISTENCY-CHECK.md` 발견 F5). 이 RFC의
`with <ref>...` 절도 참조 개수에 상한이 없으므로 같은 초과가 세 번째로 생긴다.
이 절이 정하는 최신 유효 텍스트는:

```
StepLine ::= Verb Word* EOL
```

렉서의 실제 동작(무제한 공백 분리 토큰)과 일치시키는 자기완결적 교체다
(RFC-0007 §2.2 규칙 4) — RFC-0002 본문은 지금 직접 수정하지 않는다.

## Examples

골든 시나리오 "Login"은 이벤트를 선언하지 않으므로(RFC-0007 §6) 이 RFC의
`## Examples`는 Login 참조를 그대로 유지하고, 골든 인접 예제
`examples/emitted.lnpl`을 추가로 제시한다(RFC-0008 §5.2가 `examples/
guarded.lnpl`을 참조하는 것과 같은 방식) — 전체 프로그램을 여기 인라인하지
않고 그 파일을 가리키기만 한다. `examples/emitted.lnpl`은 세 허용 참조 원천
(create-as 바인딩, `input.*`, 네트워크 호출 결과)을 한 워크플로 안에서 모두
실증한다.

## Alternatives

| # | 검토한 대안 | 기각 사유 |
|---|------------|----------|
| 1 | `NetworkCall`의 `with <ref>...` 파서(3062-3075) 대신 `condition._parse_with_clause`를 재사용한다 | 그 함수는 `"format"`이라는 리터럴을 자신의 에러 메시지에 하드코딩하고 있어, `emit`에서 쓰면 "format takes only..."라는 오해를 부르는 메시지가 난다 — `NetworkCall`이 이미 하는 것처럼 `_derive_effect` 안의 지역 블록을 새로 쓴다 |
| 2 | `payloadMap`을 단일 객체 map(`{"id": "newOrder.id", ...}`)으로 정한다 | JSON 객체 키 순서는 데이터 모델의 일부가 아니므로 저자가 쓴 `with` 순서를 안정적으로 실을 수 없고, 두 참조가 같은 필드명으로 매핑되면 조용히 마지막 값이 이기는 대신, 순서 있는 배열에서는 그 충돌이 탐지 가능한 입력으로 남는다(중복 필드명 검사가 어차피 필요하지만, 배열은 그 검사를 하기 전부터 이미 정직하다) |
| 3 | Password 필드를 런타임 마스킹만으로 막고 컴파일 타임 거부를 두지 않는다 | `mask_payload`는 블랙리스트 방식(`{k: (MASK if k in masked_names else v) ...}`)이라 필드 존재 여부 자체를 걸러내지 않는다 — `respond`가 이미 갖고 있는 이중 보장(컴파일 타임 거부 + 런타임 마스킹)보다 약해지는 것을 추가 비용 없이 받아들일 이유가 없다 |
| 4 | trailing 단어 거부를 경고로 먼저 내고 이후 릴리스에서 거부로 승격한다(2단계 전환) | 코퍼스 스윕 결과 이 저장소 안에서 거부되는 사례가 0건이다 — 이는 "실제로 배포된 무언가를 거부하게 된다"는 경고-우선 전환이 필요한 경우가 아니라, "인식되지 않는 키를 무시해 파싱이 그냥 통과하게 두지 말고 이름을 대며 거부하라"는 원칙이 그대로 적용되는 경우다 |

## Open Questions

1. `differential.py`의 비교 가능 표면을 넓혀 발행된 payload 내용까지
   mode A/B 사이에 비교할지는 이 RFC가 결정하지 않는다(§Mode B) — 오늘은
   `emit`의 payload가 plain이든 `with`-매핑이든 mode B 비교 대상이 아니며,
   그 상태를 바꾸는 것은 별도 이슈의 몫이다.

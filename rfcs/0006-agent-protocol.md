# RFC-0006: Agent Protocol

## Status

- Status: Draft

## Motivation

Charter(`CHARTER.md` §AI Pipeline)는 9종 에이전트의 파이프라인을 고정한다 —
"Planner → Architect → Coder → Reviewer → Tester → Performance Analyzer →
Security Auditor → Refactoring Agent → Release Agent"(181~182행) — 그리고 그
바로 아래에 이 파이프라인이 성립하는 전제를 한 줄로 못 박는다: "모든 Agent는
Semantic IR를 공유한다"(184행).

문제는 "공유한다"가 그 자체로는 실행 가능한 계약이 아니라는 점이다. 같은 IR을
여러 에이전트가 동시에 읽고 고치는 상황에서 다음 세 가지가 정의되지 않으면
파이프라인의 산출물은 발산한다:

- **누가 무엇을 읽고 바꿀 수 있는가** — 9역할의 IR 접근권이 정해지지 않으면 두
  에이전트가 같은 노드를 서로 다른 의도로 덮어쓴다.
- **무엇을 어떤 형태로 주고받는가** — IR 조각과 KB 문서를 싣는 메시지 형식이
  정해지지 않으면 에이전트마다 다른 표현을 만들어 상호 해석이 깨진다.
- **실패·중복·지연을 어떻게 처리하는가** — 타임아웃·재시도·중복 수신 규정이
  없으면 재시도 한 번이 작업을 두 번 실행하고, 응답 없는 에이전트가 파이프라인
  전체를 무기한 붙잡는다.

이 RFC가 정의하는 것은 위 셋과 그 운용 규정 다섯 가지다: 역할별 IR 접근권,
메시지 계층과 메서드 셋, 구조화 오류, 신뢰성(멱등·데드라인·재시도), 태스크
수명주기.

정의하지 않는 것은 셋이다. **에이전트 구현과 오케스트레이터 선정**은 ROADMAP이
소유한다. **KB 문서의 내용 규격**(문서 스키마·카테고리·라우팅)은 RFC-0005가
소유하며 이 RFC는 인용만 한다. **IR 노드의 의미**는 RFC-0001이 소유한다.

반대로 이 RFC가 이행해야 하는 위임이 하나 있다. RFC-0005는 자신이 정의하지 않는
것을 명시하면서 "소비 인터페이스의 **전송 표현**(JSON-RPC 메서드화 — RFC-0006
소유)"을 이 RFC로 넘겼다(`rfcs/0005-knowledge-base.md` 24~25행). 아래
`### KB 전송 표현`이 그 이행이며, RFC-0005의 논리 시그니처를 이름·인자 글자 단위로
보존한다.

## Guide-level Explanation

이 프로토콜은 **JSON-RPC 2.0** 위에 있다. 이는 취향의 문제가 아니라 정렬의
문제다 — 에이전트 간 통신의 두 표준이 모두 같은 베이스를 쓴다. 에이전트↔에이전트
계층은 **A2A(Agent2Agent)** 와 정렬한다(A2A는 JSON-RPC 2.0 + HTTP + SSE 조합,
Agent Card로 능력 공표, 태스크 상태기계를 규정한다). 에이전트↔도구 계층 — 즉
에이전트가 컴파일러나 KB 저장소 같은 도구를 호출하는 경로 — 는 **MCP**와 정렬한다.
LNPL(워킹네임 — `rfcs/0000-rfc-process.md` §4)의 프로토콜은 이 두 계층을 구분하되
같은 JSON-RPC 봉투를 쓰고, **두 표준과 어긋나는 확장을 만들지 않는다**: 장기적으로
A2A/MCP 생태계와 상호운용하려면 지금 사설 확장을 심지 않는 것이 비용이 가장 싸다.
근거 원문과 링크는 `docs/RESEARCH-NOTES.md` §4(<https://atlan.com/know/google-a2a-protocol/>,
서베이 <https://arxiv.org/html/2505.02279v1>,
계층 구분 관례 <https://atlan.com/know/mcp/mcp-vs-a2a-protocol/>)에 있다.

에이전트의 입장에서 이 프로토콜을 쓰는 경험은 다섯 걸음이다.

1. **능력을 공표한다** — `agent.card`로 자기 역할, 읽을 수 있는 IR 대분류, 제안할
   수 있는 IR 대분류, 지원 메서드를 구조화 JSON으로 알린다. 오케스트레이터는 이
   카드를 보고 누구에게 무엇을 맡길지 정한다.
2. **작업을 받는다** — `agent.dispatch`로 위임받는다. 위임은 즉시 결과를 주지
   않고 **태스크**를 만든다. 태스크는 `submitted`에서 시작해 상태기계를 따라
   움직이고, 진행 상황은 SSE 통지로 흐른다.
3. **IR을 읽는다** — `ir.get`으로 필요한 노드만 가져온다. 전체 문서를 끌어오지
   않는다.
4. **IR을 바꿀 때는 제안한다** — `ir.propose`뿐이며 직접 쓰기 메서드는 없다.
   제안은 IR을 즉시 변경하지 않고 리뷰 태스크를 만들며, Reviewer가 승인해야 병합된다.
   에이전트가 여럿인 환경에서 이 2단계가 충돌 조정의 유일한 지점이다.
5. **지식을 찾고, 끝나면 보고한다** — `kb.route`로 관련 문서를 찾고 `kb.load`로
   읽고 `kb.verify`로 핀을 검증한다. 작업이 끝나면 `agent.report`로 결과를 보고한다.

모든 호출에는 **데드라인**이 필수다. 부작용이 있는 두 메서드(`agent.dispatch`,
`ir.propose`)에는 **멱등키**가 필수다. 실패는 하나의 구조화 오류 객체로 돌아오고,
그 객체의 `retryable` 불리언이 재시도 여부를 결정한다 — 에이전트는 오류 메시지를
읽고 판단하지 않는다.

## Reference-level Specification

### Agent Roles & IR Access

역할은 Charter §AI Pipeline의 9종으로 **고정**한다. 행 순서는 파이프라인 순서와
같다. Charter 산문의 공백 표기(`Performance Analyzer` 등)는 프로토콜 식별자로
쓸 때 PascalCase 단일 토큰(`PerformanceAnalyzer`)으로 정규화한다 — RFC-0001이
D15의 "Workflow Step"을 `WorkflowStep`으로 정규화한 것과 같은 규칙이다
(`rfcs/0001-semantic-ir.md` 88~90행).

IR 대분류는 RFC-0001의 4종(Declaration / Behavior / Effect / Constraint —
`rfcs/0001-semantic-ir.md` 44~47행)을 그대로 쓰며 새 분류를 만들지 않는다.

| Agent | 입력 아티팩트 | 출력 아티팩트 | IR 읽기 | IR 제안(`ir.propose`) | 승인 권한 |
|-------|--------------|--------------|---------|----------------------|-----------|
| Planner | 자연어 요구(intent) | 태스크 분해 목록(`agent.dispatch` 대상) | 전체 | 없음 | 없음 |
| Architect | Planner 태스크 | IR 노드 제안(`ir_fragment`) | 전체 | Declaration, Behavior | 없음 |
| Coder | 승인된 IR 조각 + KB 문서 | `.lnpl` 소스 + Effect 노드 제안 | 전체 | Behavior, Effect | 없음 |
| Reviewer | IR 제안 + 산출물 | 승인/반려 판정 | 전체 | 없음 | **보유** |
| Tester | 승인된 IR + 코드 | spec/테스트 산출물 | 전체 | Behavior | 없음 |
| PerformanceAnalyzer | 실행 측정치 + IR | 성능 리포트 + 성능 예산 제안 | 전체 | Constraint | 없음 |
| SecurityAuditor | IR + 코드 | 보안 감사 리포트 + 인가 지점 제안 | 전체 | Constraint, Effect | 없음 |
| RefactoringAgent | 승인된 IR + 코드 | 리팩터 제안 | 전체 | Behavior, Effect | 없음 |
| ReleaseAgent | 승인된 IR + 테스트 결과 | 릴리즈 아티팩트 | 전체 | 없음 | 없음 |

**읽기가 9역할 전부 `전체`인 것은 누락이 아니라 결정이다.** Charter가 "모든
Agent는 Semantic IR를 공유한다"(`CHARTER.md` 184행)고 요구하므로 읽기를 역할별로
좁히지 않는다 — 읽기를 좁히면 에이전트가 자기 시야 밖의 제약(Policy·Security·
Performance)을 모른 채 산출물을 만들게 되고, 이는 Charter가 IR 공유로 막으려던
바로 그 발산이다.

**차별화는 제안 범위와 승인 권한에서만 일어난다.** 각 역할의 제안 범위는 그 역할이
Charter에서 만들어내는 산출물의 성격에서 유도했다: Architect는 무엇이 존재하고
어떻게 흐르는지를 설계하므로 Declaration·Behavior, Coder는 흐름을 구현하며 부수효과를
도입하므로 Behavior·Effect, Tester는 검증 규칙을 추가하므로 Behavior, PerformanceAnalyzer와
SecurityAuditor는 제약을 추가하므로 Constraint(SecurityAuditor는 인가 지점을 심으므로
Effect도 포함), RefactoringAgent는 의미를 보존하며 구조를 바꾸므로 Behavior·Effect다.
Planner는 IR을 만들지 않고 작업을 나누며, ReleaseAgent는 승인된 IR을 소비할 뿐이므로
둘 다 제안 권한이 없다. Reviewer는 제안하지 않고 판정한다 — 제안자와 승인자를
겸하면 `### Proposal & Approval`의 2단계가 무의미해진다.

`agent.card`의 응답은 이 표의 한 행과 1:1로 대응해야 한다(`### Methods`).

### Message Envelope

JSON-RPC 2.0 요청의 최상위 멤버는 `jsonrpc`, `method`, `params`, `id`뿐이다.
프로토콜 메타데이터를 최상위에 새 멤버로 추가하지 않는다 — 대신 **`params._meta`**
객체에 담는다. MCP가 구현 메타데이터에 `_meta`를 쓰는 관례를 준용해, 표준과 어긋나는
확장을 만들지 않기 위함이다(Guide-level의 정렬 원칙).

| `_meta` 필드 | 타입 | 필수 | 의미 |
|-------------|------|------|------|
| `deadline` | string (RFC 3339 UTC) | **전 메서드 필수** | 이 호출의 절대 만료 시각 |
| `correlation_id` | string | **전 메서드 필수** | 요청·응답·오류·통지를 잇는 상관 ID |
| `idempotency_key` | string (UUID) | `agent.dispatch`·`ir.propose`에서만 필수 | 논리 연산 1개당 1키 |

응답의 반향 규칙은 다음과 같다. 응답은 요청의 `id`로 이미 상관되므로 `_meta` 반향은
**선택**이며, 반향할 때도 최상위에 멤버를 추가하지 않고 `result` 객체 안에
`_meta`로 담는다. **`result`의 형태가 이 RFC 밖에서 정해진 경우에는 반향하지
않는다** — `kb.route`(배열)·`kb.verify`(불리언)·`kb.load`(`document` 객체)의 result
형태는 RFC-0005가 소유하므로, 거기에 `_meta`를 끼워 넣으면 그 계약이 깨진다.
오류 응답은 `error.details.correlation_id`로 상관을 유지한다.

통지(`task.status`)는 요청이 아니어서 데드라인·멱등키를 갖지 않으므로 `_meta`를
쓰지 않고 `params.correlation_id`로 직접 상관을 싣는다(`### Task Lifecycle`).

세 필드의 상세 규정(형식·전파·경합·보존)은 `### Reliability`가 소유하며 여기서
중복 정의하지 않는다.

### Methods

메서드는 3개 네임스페이스(`agent.*`, `ir.*`, `kb.*`)의 **8개로 고정**한다. 새 메서드를
추가하지 않는다 — 승인 같은 신규 동작도 기존 8개의 조합으로 표현한다
(`### Proposal & Approval`).

| Method | 방향 | 부작용 | `idempotency_key` | 발생 가능 `type` |
|--------|------|--------|-------------------|-----------------|
| `agent.card` | 에이전트↔에이전트 | 없음 | 불필요 | `internal` |
| `agent.dispatch` | 에이전트↔에이전트 | **있음** | **필수** | `agent_timeout`, `internal` |
| `agent.report` | 에이전트↔에이전트 | 있음(멱등) | 불필요 | `kb_version_conflict`, `internal` |
| `ir.get` | 에이전트↔도구 | 없음 | 불필요 | `ir_invalid`, `internal` |
| `ir.propose` | 에이전트↔도구 | **있음** | **필수** | `ir_invalid`, `kb_version_conflict`, `proposal_rejected`, `internal` |
| `kb.route` | 에이전트↔도구 | 없음 | 불필요 | `internal` |
| `kb.load` | 에이전트↔도구 | 없음 | 불필요 | `internal` |
| `kb.verify` | 에이전트↔도구 | 없음 | 불필요 | `internal` |

#### `agent.card`

능력 공표 조회. A2A의 Agent Card 방식 — 역할·다루는 IR 대분류·지원 메서드를
구조화 JSON으로 반환한다.

- params: `{ _meta }` (자기 카드) 또는 `{ role, _meta }` (특정 역할의 카드) —
  `_meta`는 전 메서드 필수이므로 params가 그 밖에 아무 필드도 갖지 않는 경우에도
  생략할 수 없다(`### Message Envelope`)
- result: `{ role, ir_access: { read: [대분류], propose: [대분류] }, methods: [메서드명], protocol: { jsonrpc, streaming }, version }`
- `ir_access`의 두 배열은 `### Agent Roles & IR Access` 표의 해당 행과 값이 일치해야
  한다. 불일치는 카드의 결함이며 표가 정본이다.

#### `agent.dispatch`

작업 위임. 즉시 결과를 반환하지 않고 태스크를 만든다.

- params: `{ role, task, ir_refs?, _meta }` — `role`은 위임 대상 역할, `task`는 자연어
  작업 서술, `ir_refs`는 관련 노드 id 배열(선택)
- result: `{ task_id, state: "submitted" }`
- 부작용이 있으므로 `_meta.idempotency_key` 필수. 이후 진행은 `### Task Lifecycle`.

#### `agent.report`

결과 보고. 태스크 상태를 **절대값으로 설정**한다.

- params: `{ task_id, state, result?, error?, kb_pins, _meta }` — `state` ∈ `working` |
  `input-required` | `completed` | `failed` | `canceled`
- result: `{ task_id, state }` (수용된 상태의 반향)
- `error`는 `state`가 `failed`일 때 필수이며 `### Errors`의 오류 객체 형태를 쓴다.
- `kb_pins`는 이 작업의 근거로 사용한 KB 문서의 핀 목록(`[{ doc_id, version }]`)이며
  **필수**다. KB 문서를 쓰지 않았다면 빈 배열 `[]`을 명시한다 — 필드를 생략해
  핀 검증을 우회할 수 없다. 검증 규정은 `### Errors` ④.
- `state`가 `canceled`인 보고는 담당 에이전트가 취소를 확정했음을 뜻한다
  (진입 경로는 `### Task Lifecycle`).
- 멱등키가 **불필요한 이유**: 이 메서드는 상태를 누적하지 않고 전체 교체하므로
  핸들러 자체가 멱등이다(같은 보고를 두 번 받아도 결과 상태가 같다). 멱등한 전체
  교체 연산에 키를 요구하지 않는 것은 HTTP의 PUT/DELETE 취급과 같은 판단이다.

#### `ir.get`

IR 조각 조회. 읽기 전용.

- params: `{ module, node_ids, _meta }` — `node_ids`는 dot-path 노드 id 배열
- result: 요청 노드만 담은 LIR 문서 객체(`### IR Fragment Embedding`과 같은 형태)
- 존재하지 않는 노드 id가 포함되면 `ir_invalid`.

#### `ir.propose`

IR 변경 제안. **IR을 즉시 변경하지 않는다.**

- params: `{ module, ir_fragment, rationale, kb_pins, _meta }` — `kb_pins`는 이 제안의
  근거로 사용한 KB 문서 핀 목록(`[{ doc_id, version }]`)이며 **필수**다(사용하지
  않았다면 `[]`). 검증 규정은 `### Errors` ④
- result: `{ proposal_id, state: "pending", review_task_id }`
- 부작용이 있으므로 `_meta.idempotency_key` 필수. 상세는
  `### IR Fragment Embedding`과 `### Proposal & Approval`.

#### KB 전송 표현

RFC-0005는 KB 소비 연산 3종의 **논리 계약**을 다음과 같이 확정했다
(`rfcs/0005-knowledge-base.md` 141~145행 — 원문 그대로 인용):

```
kb.route(task_description) -> [doc_id]
kb.load(doc_id) -> document
kb.verify(doc_id, version) -> bool
```

이 RFC는 위 시그니처의 **이름과 인자를 글자 단위로 보존한 채** 전송 표현만 규정한다:

| 논리 시그니처 | JSON-RPC method | params | result |
|--------------|-----------------|--------|--------|
| `kb.route(task_description) -> [doc_id]` | `kb.route` | `{ task_description, _meta }` | `[doc_id]` (문서 id 문자열 배열) |
| `kb.load(doc_id) -> document` | `kb.load` | `{ doc_id, _meta }` | `document` (파싱된 frontmatter + 본문 Markdown) |
| `kb.verify(doc_id, version) -> bool` | `kb.verify` | `{ doc_id, version, _meta }` | `bool` |

**의미론은 RFC-0005가 소유하며 이 RFC는 재정의하지 않는다.** 즉 `kb.route`의 빈
목록은 오류가 아니고, 존재하지 않는 `doc_id`는 오류이며, `kb.verify`의 `false`는
핀 이후 문서가 개정·삭제되었음을 뜻해 `kb.route`부터 재수행해야 한다는 규정은 모두
RFC-0005 147~158행에 있다. 이 RFC가 더하는 것은 그 오류를 어떤 코드·`type`으로
싣는지뿐이다(`### Errors`).

### IR Fragment Embedding

`params.ir_fragment`는 **완전한 LIR 문서 객체**다 — 즉 `{ lir_version, module, nodes }`
세 필드를 갖고, 대상 노드만 담은 부분집합이다. 이 조각은 `schemas/lir.schema.json`을
수정 없이 통과해야 한다.

- **bare `nodes` 배열을 보내지 않는다.** 스키마의 root는 `lir_version`·`module`·
  `nodes`를 `required`로 요구하고 `additionalProperties: false`이므로
  (`schemas/lir.schema.json` 5~36행), 배열만 보내면 스키마 위반이다.
- **별도의 fragment 스키마를 신설하지 않는다.** 조각과 전체 문서가 같은 스키마를
  쓰는 것이 검증 경로를 하나로 유지하는 유일한 방법이다(plan.md D4의 constrained-
  decoding 부분집합 제약도 그대로 상속된다).
- **`module` 불일치는 오류다.** `ir_fragment.module`이 대상 문서의 `module`과 다르면
  병합 대상이 모호해지므로 `ir_invalid`(-32602)로 거절한다.
- **노드의 출처를 표기한다.** 조각의 각 노드는 `meta.origin`을 `agent:<role>`
  형식으로 채운다(예: `agent:architect`). 이는 스키마에 이미 있는 필드이며
  (`schemas/lir.schema.json` 50행, pattern `^(human|agent:.+)$`) 신규 필드를 만들지
  않는다.

**dangling 참조의 판정 시점.** RFC-0001 §구조 규칙 6은 "모든 참조(소유·비소유)는
같은 IR 문서 내의 `id`로 해소되어야 한다"고 규정한다. 조각은 정의상 문서의
부분집합이므로 이 규칙을 조각 단독에 적용하면 거의 모든 제안이 거절된다 — 예를 들어
`wf.login`만 담은 조각의 `children`은 조각 밖의 step 노드를 가리킨다. 따라서 이
프로토콜은 다음과 같이 시점을 분리한다:

| 검사 | 대상 | 실패 시 |
|------|------|---------|
| `lir.schema.json` 스키마 유효성 | **조각 단독** | `ir_invalid` (제안 거절) |
| RFC-0001 §구조 규칙 6 dangling 금지 | **병합 결과 문서** | `ir_invalid` (제안 거절) |
| RFC-0001 §구조 규칙 2·4 (소유 유일·순환 금지) | **병합 결과 문서** | `ir_invalid` (제안 거절) |

즉 조각 단독 요건은 스키마 유효성뿐이고, 참조 정합성은 수신 측이 병합을 시뮬레이션한
뒤 평가한다.

### Proposal & Approval

IR 변경은 **항상 제안 + 승인 2단계**다. 직접 쓰기 메서드는 존재하지 않는다.

1. **제안** — 제안자가 `ir.propose`를 호출한다. 서버는 IR을 변경하지 않고 제안을
   저장한 뒤 `{ proposal_id, state: "pending", review_task_id }`를 반환하고, 승인
   권한을 가진 역할(Reviewer)에게 리뷰 태스크를 만든다.
2. **판정** — Reviewer는 그 태스크를 처리하고 `agent.report`로 판정을 싣는다:
   `result` = `{ proposal_id, decision: "approved" | "rejected", reason }`.
   **승인 전용 메서드를 만들지 않는 이유**는 메서드 셋을 8개로 고정했기 때문이며,
   승인은 본질적으로 "리뷰 태스크의 결과 보고"이므로 `agent.report`가 자연스러운
   자리다.
3. **반영** — `approved`면 서버가 조각을 병합하고(병합 시점에
   `### IR Fragment Embedding`의 병합 후 검사를 수행한다) 리뷰 태스크는 `completed`가
   된다. `rejected`면 병합하지 않고 리뷰 태스크는 `failed`가 되며, 그 태스크 결과에
   `proposal_rejected` 오류 객체가 실린다(`reason`이 `message`로 전달된다).

제안자는 결과를 폴링하지 않는다 — 태스크 상태 전이 통지(SSE `task.status`)로 받는다
(`### Task Lifecycle`). 별도의 조회 메서드를 만들지 않는다.

### Errors

모든 메서드는 **하나의 오류 객체 형태**만 반환한다. 메서드별로 다른 오류 형태를
만들지 않는다 — 그러면 클라이언트가 메서드마다 다른 파서를 써야 한다.

| 필드 | 타입 | 필수 | 의미 |
|------|------|------|------|
| `code` | integer | 필수 | JSON-RPC 오류 코드. 아래 매핑 표의 값 |
| `type` | string(enum) | 응용 계층 오류에서 필수 | 머신리더블 오류 종별 |
| `message` | string | 필수 | 사람이 읽는 설명. **클라이언트는 여기에 분기하지 않는다** |
| `retryable` | boolean | 필수 | 재시도 가능 여부. 재시도 판단의 유일한 근거 |
| `details` | object | 선택 | 종별별 부가 정보. 항상 `correlation_id`를 포함한다 |

`type` enum은 다음 5종으로 고정한다:

| `type` | 의미 | `retryable` | 주 발생 메서드 |
|--------|------|-------------|---------------|
| `ir_invalid` | IR 조각이 스키마 또는 병합 후 구조 규칙을 위반 | `false` | `ir.propose`, `ir.get` |
| `kb_version_conflict` | 제출물이 근거로 삼은 KB 문서 핀이 이미 개정됨 | `false` | `ir.propose`, `agent.report` |
| `agent_timeout` | 하류 에이전트·도구가 데드라인 내 응답하지 않음 | `true` | `agent.dispatch` |
| `proposal_rejected` | Reviewer가 제안을 반려 | `false` | `ir.propose`(리뷰 태스크 결과) |
| `internal` | 서버 내부 결함 | `false` | 전 메서드 |

#### 코드 매핑

응용 계층 5종과 봉투 계층 코드를 하나의 표로 규정한다. `-32001`~`-32003`과
`-3201x`는 JSON-RPC 2.0이 구현 정의 서버 오류용으로 남긴 **`-32099`~`-32000`
범위** 안에서 할당했다.

| `code` | `type` | 계층 | 의미 | `retryable` |
|--------|--------|------|------|-------------|
| `-32700` | (없음) | 봉투 | Parse error — JSON 파싱 실패 | `false` |
| `-32600` | (없음) | 봉투 | Invalid Request — JSON-RPC 봉투 위반 | `false` |
| `-32601` | (없음) | 봉투 | Method not found — 8종 밖의 메서드 | `false` |
| `-32602` | `ir_invalid` | 봉투/응용 | Invalid params — 필수 `_meta` 누락, `ir_fragment` 스키마 위반, `module` 불일치 | `false` |
| `-32603` | `internal` | 봉투 | Internal error — 서버 내부 결함 | `false` |
| `-32001` | `kb_version_conflict` | 응용 | KB 문서 버전 핀 불일치 | `false` |
| `-32002` | `agent_timeout` | 응용 | 하류 무응답(데드라인 초과) | `true` |
| `-32003` | `proposal_rejected` | 응용 | 제안 반려 | `false` |
| `-32010` | (없음) | 봉투 | 동일 `idempotency_key`의 최초 시도가 진행 중 | `true` |
| `-32011` | (없음) | 봉투 | 동일 `idempotency_key`에 다른 params — 클라이언트 키 생성 결함 | `false` |
| `-32012` | (없음) | 봉투 | 수용 한도 초과 — 큐잉하지 않고 즉시 실패. `details.retry_after_ms` 포함 | `true` |

**`type` 생략 규칙**: 봉투 계층 오류에는 대응하는 도메인 종별이 없으므로 `type`을
생략한다. 예외는 `-32603`(=`internal`)과 `-32602`이며, `-32602`는 IR 조각의 유효성
위반일 때만 `type: "ir_invalid"`를 싣고, 그 밖의 파라미터 위반(예: `_meta.deadline`
누락)에서는 `type`을 생략한다. 이 규칙은 구현자가 임의로 판단할 여지를 남기지 않기
위해 명문화한다.

#### 오류 운용 3규정

**① `code`는 계약이다.** 코드 값의 변경·삭제는 breaking change이며, 응답 필드를
제거하는 것과 동일한 검토 절차를 거친다. 클라이언트는 `code`와 `type`에 분기하고
`message`에 분기하지 않는다.

**② `internal`은 내부를 드러내지 않는다.** `message`는 일반 문구
("internal error")로 고정하고, `details`에는 `correlation_id`만 담는다. 다음은
어떤 경우에도 응답에 넣지 않는다 — **스택트레이스, 파일 경로, 클래스·함수명, SQL,
의존 서비스의 호스트명**. 이들은 `correlation_id`를 키로 서버 측 로그에 기록하며,
조사자는 로그에서 조회한다. 응답이 아니라 로그가 내부 정보의 자리다.

**③ `ir_invalid`는 모든 위반을 한 응답에 담는다.** `details.errors[]`에
`{ path, code, message }` 항목을 위반마다 하나씩 넣는다(`path`는 조각 내 JSON 경로
또는 노드 id). 위반을 하나씩 돌려주면 제안자가 수정–재제안 루프를 여러 번 돌아야
하고, 그 루프마다 리뷰 태스크가 생성된다.

**④ `kb_version_conflict`는 `kb.*` 읽기에서 발생하지 않는다.** `kb.verify`가 `false`를
반환하는 것은 **정상 결과**이며 오류가 아니다 — RFC-0005는 `false`를 "핀 이후 문서가
개정(또는 삭제)되었음"으로 정의하고 에이전트가 `kb.route`부터 다시 수행하라고
규정한다(`rfcs/0005-knowledge-base.md` 154~158행). `kb.load(doc_id)` 역시 `version`
인자를 갖지 않으므로 버전 충돌을 판정할 위치가 아니다.

이 오류가 발생하는 지점은 **제출 시점**이다. `ir.propose`와 `agent.report`는
`kb_pins`(`[{ doc_id, version }]`)로 자기 산출물의 근거 문서를 신고하며, 서버는
제출을 수용하기 전에 그 핀들을 검증한다. **`kb_pins`는 필수 필드**이며 KB 문서를
쓰지 않은 경우에도 빈 배열을 명시해야 한다 — 필드를 생략해 검증을 건너뛰는 경로를
남기지 않기 위함이다(누락은 `-32602`). 핀 중 하나라도 현재 버전과 다르면
`kb_version_conflict`(-32001, `retryable: false`)로 거절한다 — 개정된 지침 위에서
만들어진 산출물이 병합되는 것을 막는 자리다. `retryable: false`인 이유는 같은
제출을 재시도해도 같은 결과가 나오기 때문이며, 에이전트는 `kb.route`부터 다시
수행해야 한다. `details.errors[]`에 어긋난 핀을 `{ path, code, message }`로 열거한다.

**`agent_timeout`을 `internal`과 분리하는 이유**: 하류 에이전트의 무응답은 이 서버의
결함이 아니라 인프라 결함이다. 두 경우를 같은 종별로 묶으면 모니터링이 "우리 코드의
버그"와 "의존 대상의 지연"을 구분할 수 없고, 재시도 판정도 갈라지지 않는다
(`agent_timeout`만 `retryable: true`).

### Reliability

#### Deadlines

- **모든 요청에 `_meta.deadline`이 필수다.** 누락은 `-32602`로 거절한다. 무기한
  대기하는 호출을 프로토콜 차원에서 없애기 위함이다 — 응답 없는 하류 하나가
  상류의 처리 슬롯을 모두 소진하면 파이프라인 전체가 멈춘다.
- **형식은 RFC 3339 UTC 절대 시각**이다(예: `2026-07-29T04:15:03.000Z`). 홉을
  넘길 때 값을 그대로 전파한다. 상대 잔여시간(예: `timeout_ms`)을 쓰지 않는 이유는
  홉마다 재계산이 필요하고 그 재계산이 누락·중복되면 예산이 왜곡되기 때문이다.
  절대 시각이 전제하는 시계 동기 가정은 `## Open Questions` ⑤로 남긴다.
- **데드라인 예산은 부등식을 만족해야 한다**: 상위 호출의 데드라인 >
  (시도 타임아웃 × 시도 수) + 총 백오프. 이 부등식이 깨지면 하류가 재시도를 마치기
  전에 상위가 포기하고, 하류는 아무도 읽지 않을 작업에 용량을 쓴다.
- **이 RFC는 타임아웃 상수를 규정하지 않는다.** 값은 각 호출 대상의 **관측된 p99
  지연 + 헤드룸**에서 유도하며 추측으로 정하지 않는다. 상수를 명세에 박으면 실제
  지연 분포와 무관한 숫자가 고정된다. 타임아웃이 실제로 발화할 때 관측 가능해야
  한다(발화율을 지표로 노출한다).
- **데드라인이 지나면 취소를 전파한다.** 호출자가 연결을 끊거나 데드라인이 경과하면
  진행 중인 하류 호출을 취소하고 작업을 멈춘다. 태스크는 `canceled`로 간다.

#### Idempotency

- **`agent.dispatch`와 `ir.propose`는 `_meta.idempotency_key`가 필수다.** 키는
  클라이언트가 생성하는 UUID이며 **논리 연산 1개당 1키**다(재시도는 같은 키를 쓴다).
- **동일 키 재수신 시 저장된 최초 응답을 그대로 반환한다.** 연산을 다시 실행하지
  않는다. 타임아웃된 요청은 이미 실행되었을 수 있으므로, 키 없는 재시도는 위임을
  두 번 만들고 제안을 두 개 만든다.
- **키는 unique 제약으로 저장하고 중복 키 오류를 처리한다.** "조회해서 없으면 삽입"
  방식을 쓰지 않는다 — 동시에 도착한 두 재시도가 둘 다 조회를 통과한다.
- **키 레코드와 응답은 부작용과 같은 커밋 단위로 기록한다.** 부작용은 반영되었는데
  키가 기록되지 않으면 재시도가 부작용을 중복시킨다.
- **경합 2케이스**: 최초 시도가 아직 진행 중인 상태에서 같은 키가 오면 `-32010`
  (`retryable: true`)으로 거절하고 연산을 병렬로 두 번 돌리지 않는다. 같은 키에
  **다른 params**가 오면 `-32011`(`retryable: false`) — 클라이언트의 키 생성 결함이며
  조용히 첫 응답을 돌려주면 두 번째 연산이 소리 없이 사라진다.
- **보존 기간은 클라이언트의 최대 재시도 지평 이상, 최소 24시간**이다. 만료 후 같은
  키는 새 요청으로 실행된다. 만료된 레코드는 정리해 키 저장소가 무한히 자라지 않게
  한다.
- **나머지 5개 메서드가 키를 요구하지 않는 근거**: `ir.get`·`kb.route`·`kb.load`·
  `kb.verify`는 읽기 전용이므로 재시도가 안전하다. `agent.report`는 태스크 상태를
  절대값으로 설정하는 전체 교체 연산이라 핸들러 자체가 멱등이다. 이는 누락이 아니라
  분류의 결과다.

#### Retries

- **재시도는 `retryable: true` 오류에만 한다.** `false`인 오류를 재시도하면 같은
  바이트가 같은 실패를 반복하며 예산만 태운다. `ir_invalid`·`proposal_rejected`·
  `kb_version_conflict`가 `false`인 것은 요청 자체를 고쳐야 하기 때문이다 — 특히
  `kb_version_conflict`는 `kb.route`부터 다시 수행하는 것이 정답이다
  (`rfcs/0005-knowledge-base.md` 154~158행).
- **총 시도는 3회 이내다**(최초 1회 + 재시도 2회). 소진되면 실패를 상위로 노출한다.
- **백오프는 full jitter다**: `sleep = random(0, min(cap, base × 2^attempt))`.
  즉시 재시도나 지터 없는 고정 백오프는 동기화된 재시도 스파이크를 만들어, 하류가
  가장 약한 순간에 부하를 몰아준다.
- **재시도는 한 계층에서만 한다.** 여러 계층(클라이언트·프로토콜 라이브러리·게이트웨이)이
  각자 재시도하면 시도 수가 곱해진다(3 × 3 × 3 = 27). 재시도를 수행하는 계층을 하나
  정하고 나머지는 1회로 고정한다.
- **전역 재시도 예산을 둔다** — 재시도가 전체 요청의 10%를 넘지 않게 한다. 하류가
  내려간 상황에서 재시도가 트래픽을 증폭시키지 않게 하는 상한이다.
- **과부하에서는 큐잉하지 않고 빠르게 실패한다.** 에이전트별 동시 처리 상한을 두고,
  초과하면 `-32012`(`retryable: true`, `details.retry_after_ms`)로 즉시 거절한다.
  무한 큐는 느린 의존을 자기 장애로 바꾼다.

### Task Lifecycle

`agent.dispatch`가 만드는 태스크는 6상태 기계를 따른다(A2A 준용 — 상태명도 A2A
표기를 그대로 쓴다).

| 상태 | 의미 |
|------|------|
| `submitted` | 위임이 수용되어 태스크가 생성됨. 아직 처리 시작 전 |
| `working` | 담당 에이전트가 처리 중 |
| `input-required` | 사람 또는 다른 에이전트의 입력을 기다리는 중(HITL) |
| `completed` | 성공 종결 |
| `failed` | 실패 종결 |
| `canceled` | 취소 종결 |

`completed`·`failed`·`canceled`는 종결 상태이며 이후 전이가 없다.

| From | To | 전이 조건 | 통지 이벤트 |
|------|----|-----------|-------------|
| `submitted` | `working` | 담당 에이전트가 처리를 시작 (`agent.report` state=`working`) | `task.status` |
| `submitted` | `canceled` | 처리 시작 전 취소 — 호출자 데드라인 경과·연결 단절, 또는 상위 태스크 취소의 전파 | `task.status` |
| `working` | `input-required` | 에이전트가 외부 입력 필요를 보고 (`agent.report` state=`input-required`) | `task.status` |
| `input-required` | `working` | 필요한 입력이 제공됨 (`agent.report` state=`working`) | `task.status` |
| `input-required` | `canceled` | 대기 중 데드라인 경과, 또는 담당 에이전트가 취소를 확정 (`agent.report` state=`canceled`) | `task.status` |
| `working` | `completed` | 에이전트가 성공 결과를 보고 (`agent.report` state=`completed`). IR 제안의 리뷰 태스크는 `decision="approved"`로 병합 완료 시 | `task.status` |
| `working` | `failed` | `retryable: false` 오류 발생, 또는 재시도 3회 소진. 리뷰 태스크는 `decision="rejected"`(→ `proposal_rejected`) | `task.status` |
| `working` | `canceled` | 호출자 데드라인 경과·연결 단절(취소 전파), 상위 태스크 취소의 전파, 또는 담당 에이전트가 취소를 확정 (`agent.report` state=`canceled`) | `task.status` |

**`canceled` 진입 경로는 위 표의 셋으로 한정된다** — ① 호출자 데드라인 경과·연결
단절에 의한 취소 전파(`### Reliability`), ② 상위 태스크 취소의 하위 전파,
③ 담당 에이전트의 `agent.report` state=`canceled`. 메서드 셋이 8종으로 고정되어
있으므로 **외부(사용자·오케스트레이터)가 취소를 개시하는 전용 메서드는 이 RFC에
없다**. 그 표면이 필요한지는 `## Open Questions` ④로 남긴다 — 정의되지 않은
메커니즘을 전이 조건에 적어 두지 않기 위해 명시한다.

- `failed`로 갈 때 태스크 결과에는 `### Errors`의 오류 객체를 **그대로** 싣는다 —
  원인(`code`/`type`/`retryable`)이 보존되어야 상류가 다음 행동을 결정할 수 있다.
- `input-required`에서 사람의 승인을 받는 UX(승인 화면·알림 경로)는 이 RFC의 범위
  밖이다(`## Open Questions` ②).

#### 통지와 스트리밍

- 상태 전이마다 `task.status` **통지**를 발행한다. 통지는 `id`가 없는 JSON-RPC
  notification이며, payload는 `{ task_id, state, correlation_id, error? }`다.
- 전달 채널은 **SSE 준용**이다(A2A와 같은 조합). 장기 실행 태스크의 진행 통지와
  부분 결과 스트리밍은 같은 채널을 쓰며, 별도의 폴링 메서드를 만들지 않는다.

## Examples

골든 시나리오 "Login"을 사용한다(정본: `plans/rfc-suite/plan.md` §골든 시나리오
"Login" — RFC-0000 §5 규칙에 따라 참조만 하고 재정의하지 않는다). 노드 id는
`examples/login.lir.json`의 실제 값을 인용한다.

파이프라인 1사이클: **Planner가 Login intent를 받아 Architect에 위임 → Architect가
Workflow 노드를 제안 → Coder가 KB를 라우팅해 `generate token`을 구현 → Reviewer가
승인.** 아래 6개 교환이 그 흐름이다.

### ① Architect의 능력 공표 — `agent.card`

```json
{
  "jsonrpc": "2.0",
  "id": "c-1",
  "method": "agent.card",
  "params": {
    "role": "Architect",
    "_meta": {
      "deadline": "2026-07-29T04:15:01.000Z",
      "correlation_id": "login-cycle-7f3a"
    }
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "c-1",
  "result": {
    "role": "Architect",
    "ir_access": {
      "read": ["Declaration", "Behavior", "Effect", "Constraint"],
      "propose": ["Declaration", "Behavior"]
    },
    "methods": ["agent.card", "agent.report", "ir.get", "ir.propose", "kb.route", "kb.load", "kb.verify"],
    "protocol": { "jsonrpc": "2.0", "streaming": "sse" },
    "version": "0.1.0",
    "_meta": { "correlation_id": "login-cycle-7f3a" }
  }
}
```

`ir_access`의 두 배열은 `### Agent Roles & IR Access` 표의 Architect 행(읽기 전체 /
제안 Declaration·Behavior)과 값이 일치한다.

### ② Planner → Architect 위임 — `agent.dispatch`

```json
{
  "jsonrpc": "2.0",
  "id": "d-1",
  "method": "agent.dispatch",
  "params": {
    "role": "Architect",
    "task": "Login 서비스의 Workflow 단계를 설계한다 — validate input, authenticate, cache user, generate token, audit login, return token",
    "ir_refs": ["svc.login", "wf.login", "entity.user", "cap.jwt"],
    "_meta": {
      "deadline": "2026-07-29T04:20:00.000Z",
      "correlation_id": "login-cycle-7f3a",
      "idempotency_key": "b1d9c7e2-4a55-4f0e-9c31-8ac2f6e5d011"
    }
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "d-1",
  "result": {
    "task_id": "task-arch-0912",
    "state": "submitted",
    "_meta": { "correlation_id": "login-cycle-7f3a" }
  }
}
```

부작용이 있는 메서드이므로 `idempotency_key`가 실려 있다. 이 요청이 타임아웃되어
Planner가 재시도하면 같은 키가 전달되고, 서버는 저장된 `task-arch-0912` 응답을 그대로
반환한다 — 위임이 두 개 생기지 않는다.

### ③ Architect의 IR 제안 — `ir.propose`

```json
{
  "jsonrpc": "2.0",
  "id": "p-1",
  "method": "ir.propose",
  "params": {
    "module": "login",
    "rationale": "Login Workflow의 단계 순서를 고정하고 generate token 단계를 명시한다",
    "ir_fragment": {
      "lir_version": "0.1",
      "module": "login",
      "nodes": [
        {
          "kind": "Workflow",
          "id": "wf.login",
          "meta": { "origin": "agent:architect" },
          "name": "Login",
          "children": [
            "wf.login.step.1",
            "wf.login.step.2",
            "wf.login.step.3",
            "wf.login.step.4",
            "wf.login.step.5",
            "wf.login.step.6"
          ],
          "constraints": ["policy.login", "security.login", "perf.login"]
        },
        {
          "kind": "WorkflowStep",
          "id": "wf.login.step.4",
          "meta": { "origin": "agent:architect" },
          "name": "generate token"
        }
      ]
    },
    "kb_pins": [],
    "_meta": {
      "deadline": "2026-07-29T04:22:00.000Z",
      "correlation_id": "login-cycle-7f3a",
      "idempotency_key": "e4c81a60-2f7b-4d19-b8aa-51d0c93e7742"
    }
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "p-1",
  "result": {
    "proposal_id": "prop-31f0",
    "state": "pending",
    "review_task_id": "task-rev-0913",
    "_meta": { "correlation_id": "login-cycle-7f3a" }
  }
}
```

`kb_pins`가 빈 배열인 것은 Architect가 이 제안을 만들 때 KB 문서를 근거로 쓰지
않았다는 **명시적 신고**다 — 필수 필드이므로 생략이 아니라 `[]`로 적는다
(`### Methods`, `### Errors` ④). 아래 ④에서 Coder는 실제로 KB를 읽으므로 그 결과를
⑤의 `kb_pins`에 싣는다.

`ir_fragment`는 완전한 LIR 문서 객체(`lir_version`/`module`/`nodes`)이므로
`schemas/lir.schema.json`을 그대로 통과한다. 조각의 `wf.login.children`은 조각 밖의
step 노드를 가리키지만 이는 오류가 아니다 — dangling 판정은 병합 결과 문서에서
수행된다(`### IR Fragment Embedding`). 각 노드는 `meta.origin: "agent:architect"`로
출처를 표기한다. 응답은 `state: "pending"`이며 이 시점에 IR은 아직 변경되지 않았다.

### ④ Coder의 KB 라우팅 — `kb.route` → `kb.load`

```json
{
  "jsonrpc": "2.0",
  "id": "k-1",
  "method": "kb.route",
  "params": {
    "task_description": "Login 워크플로의 generate token step 구현 — jwt capability 사용",
    "_meta": {
      "deadline": "2026-07-29T04:23:00.000Z",
      "correlation_id": "login-cycle-7f3a"
    }
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "k-1",
  "result": ["security-jwt-issuance"]
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "k-2",
  "method": "kb.load",
  "params": {
    "doc_id": "security-jwt-issuance",
    "_meta": {
      "deadline": "2026-07-29T04:23:05.000Z",
      "correlation_id": "login-cycle-7f3a"
    }
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "k-2",
  "result": {
    "frontmatter": {
      "id": "security-jwt-issuance",
      "category": "Security",
      "version": "1.0.0",
      "status": "verified"
    },
    "body": "# JWT 발급\n\n## When this applies\n\nJWT 기반 인증 토큰을 발급·서명하는 코드를 생성하거나 리뷰할 때.\n"
  }
}
```

두 호출 모두 읽기 전용이므로 `_meta`에 `idempotency_key`가 없다 — 재시도가 그 자체로
안전하다. 두 응답은 `_meta`를 반향하지 않는다: `kb.route`의 result는 `[doc_id]` 배열,
`kb.load`의 result는 `document` 객체이며 두 형태는 RFC-0005가 소유하므로 이 RFC가
필드를 덧붙이지 않는다(`### Message Envelope`). Coder는 사용한 문서를 `security-jwt-issuance@1.0.0`으로 핀하고, 이후
`kb.verify("security-jwt-issuance", "1.0.0")`로 검증한다(의미론은 RFC-0005 소유).

### ⑤ Reviewer의 승인 — `agent.report` + 상태 통지

```json
{
  "jsonrpc": "2.0",
  "id": "r-1",
  "method": "agent.report",
  "params": {
    "task_id": "task-rev-0913",
    "state": "completed",
    "result": {
      "proposal_id": "prop-31f0",
      "decision": "approved",
      "reason": "단계 순서가 골든 시나리오와 일치하고 generate token 단계의 제약 참조가 유효하다"
    },
    "kb_pins": [{ "doc_id": "security-jwt-issuance", "version": "1.0.0" }],
    "_meta": {
      "deadline": "2026-07-29T04:25:00.000Z",
      "correlation_id": "login-cycle-7f3a"
    }
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "r-1",
  "result": {
    "task_id": "task-rev-0913",
    "state": "completed",
    "_meta": { "correlation_id": "login-cycle-7f3a" }
  }
}
```

승인이 수용되면 서버는 조각을 병합하고, 제안자에게 SSE로 통지를 흘린다. 통지는
`id`가 없는 notification이다:

```json
{
  "jsonrpc": "2.0",
  "method": "task.status",
  "params": {
    "task_id": "task-rev-0913",
    "state": "completed",
    "correlation_id": "login-cycle-7f3a"
  }
}
```

`agent.report`에 `idempotency_key`가 없는 것은 이 메서드가 태스크 상태를 절대값으로
설정하기 때문이다 — 같은 보고를 두 번 받아도 결과는 `completed` 하나다.

`kb_pins`는 이 판정이 근거로 삼은 KB 문서의 핀이다. 서버는 병합 직전에 이 핀을
검증하며, ④에서 Coder가 읽은 `security-jwt-issuance`가 그사이 `1.1.0`으로 개정되어
있었다면 이 보고는 `kb_version_conflict`(-32001)로 거절된다 — 개정된 지침 위에서
만들어진 산출물이 병합되지 않는다(`### Errors` ④).

### ⑥ 실패 2종 — `ir_invalid`와 `internal`

`ir.propose`에 `module`이 대상과 다른 조각을 보낸 경우
(`### IR Fragment Embedding`의 `module` 일치 규정 위반):

```json
{
  "jsonrpc": "2.0",
  "id": "p-2",
  "error": {
    "code": -32602,
    "type": "ir_invalid",
    "message": "ir_fragment is not valid for the target module",
    "retryable": false,
    "details": {
      "correlation_id": "login-cycle-7f3a",
      "errors": [
        {
          "path": "/module",
          "code": "module_mismatch",
          "message": "fragment module 'signup' does not match target module 'login'"
        },
        {
          "path": "/nodes/1/id",
          "code": "node_id_pattern",
          "message": "node id 'wf.Login.Step.4' violates the dot-path pattern"
        }
      ]
    }
  }
}
```

위반이 둘이지만 한 응답에 모두 실려 있다 — 제안자가 한 번의 수정으로 재제안할 수
있다. `retryable: false`이므로 같은 조각을 재시도하지 않는다.

내부 결함이 발생한 경우:

```json
{
  "jsonrpc": "2.0",
  "id": "p-3",
  "error": {
    "code": -32603,
    "type": "internal",
    "message": "internal error",
    "retryable": false,
    "details": { "correlation_id": "login-cycle-7f3a" }
  }
}
```

`details`에 `correlation_id`만 있다 — 스택트레이스·파일 경로·클래스명·SQL·의존
호스트명은 응답에 담기지 않으며, 조사자는 `login-cycle-7f3a`로 서버 로그를 조회한다.

## Alternatives

**① REST/HTTP 자원 모델 — 기각.** 에이전트 간 통신을 자원(`/tasks`, `/proposals`)의
CRUD로 표현하는 방식은 HTTP 의미론(상태 코드·멱등 메서드)을 그대로 쓸 수 있어
매력적이다. 그러나 에이전트 상호운용의 두 표준이 모두 JSON-RPC 2.0을 베이스로
한다 — A2A는 JSON-RPC 2.0 + SSE, MCP도 JSON-RPC 2.0이다(`docs/RESEARCH-NOTES.md`
§4). 정렬을 벗어나면 향후 A2A/MCP 생태계와의 상호운용에 어댑터 계층이 필요해지고,
그 비용이 HTTP 의미론에서 얻는 이득보다 크다. plan.md D8의 결정을 유지한다.

**② IR 직접 쓰기(`ir.put`) — 기각.** 제안+승인 2단계 대신 승인된 에이전트가 IR을
직접 쓰게 하면 왕복이 한 번 줄어든다. 그러나 9개 에이전트가 같은 IR을 공유하는
구조에서 직접 쓰기는 **충돌 조정 지점을 없앤다** — Architect와 RefactoringAgent가
같은 Workflow 노드를 다른 의도로 덮어쓰는 것을 막을 자리가 사라지고, 변경의 근거
(`rationale`)와 판정 기록도 남지 않는다. 2단계의 왕복 비용은 이 조정 지점의 대가로
지불한다.

**③ 계층마다 재시도 허용 — 기각.** 클라이언트·프로토콜 라이브러리·게이트웨이가 각각
재시도하게 두면 개별 계층의 구현이 단순해진다. 그러나 시도 수가 곱해져
3 × 3 × 3 = 27회가 되고, 이는 이미 약해진 하류에 대한 자기 유발 DDoS다. 재시도
계층을 하나로 못 박고 나머지를 1회로 고정하는 `### Reliability`의 규정을 택했다.

**④ 오류를 JSON-RPC 코드만으로 표현 — 기각.** `type` 없이 `code`만 쓰면 필드가
하나 줄어든다. 그러나 -32xxx 코드는 봉투 계층 어휘라 도메인 실패(제안 반려 vs KB
버전 충돌)를 구분하기에 부족하고, 클라이언트가 코드 숫자에 도메인 의미를 임의로
부여하게 된다. 머신리더블 `type` enum과 `retryable` 불리언을 분리해 두면 클라이언트의
분기가 명세에 고정된다.

## Open Questions

1. **에이전트 인증·권한** — 누가 어떤 역할로 `agent.dispatch`를 호출할 수 있는지,
   `agent.card`가 공표한 접근권을 서버가 어떻게 강제하는지. 현재 이 RFC는 역할별
   접근권을 **정의**하지만 인증 주체와 집행 메커니즘은 정의하지 않는다.
2. **HITL 승인 UX** — `input-required` 상태에서 사람이 개입하는 표면(승인 화면,
   알림 경로, 대기 만료 처리). 상태기계에는 자리가 있으나 그 자리를 무엇이 채우는지는
   미결이다.
3. **A2A/MCP 공식 호환성 인증 범위** — "정렬"을 어디까지 밀어 실제 A2A 클라이언트가
   LNPP 에이전트를 그대로 호출할 수 있게 할 것인가(Agent Card 스키마 완전 준수,
   A2A 메서드명 채택 여부). 완전 호환은 이 프로토콜의 메서드명을 A2A 것으로 바꾸는
   문제가 된다.
4. **외부 발신 취소 표면** — 사용자나 오케스트레이터가 진행 중 태스크의 취소를
   **개시**하는 경로. 현재 `canceled`는 데드라인 경과·상위 전파·담당 에이전트의
   확정 보고 셋으로만 진입하며, 취소 개시 전용 메서드는 메서드 셋 8종 고정 때문에
   두지 않았다(`### Task Lifecycle`). 9번째 메서드를 추가할지, `agent.dispatch`의
   재호출 의미론으로 흡수할지 미결이다.
5. **절대 데드라인의 시계 동기 가정** — RFC 3339 절대 시각 전파는 홉 간 시계가
   동기화되어 있음을 전제한다. 드리프트가 큰 환경에서의 보정(단조 시계 병용, 상대
   잔여시간 폴백)이 필요한지.

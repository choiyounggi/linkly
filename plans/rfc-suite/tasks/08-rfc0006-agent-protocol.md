# Task 08: RFC-0006 Agent Protocol — 역할·메시지·오류·신뢰성

## Objective
`rfcs/0006-agent-protocol.md`가 존재하고, AI Pipeline의 에이전트 역할과 에이전트 간
통신(메시지 스키마·IR 전달·오류·재시도·멱등성)이 정의되어 있다.

## Wiki pages (read these first, only these)
- wiki/backend/common/api-design/error-responses.md — use for: 프로토콜 오류 객체
  설계(코드 체계, 무엇을 드러내고 무엇을 숨길지)
- wiki/backend/common/api-design/idempotency.md — use for: 부작용 있는 메서드의
  멱등키 규정
- wiki/backend/common/reliability/timeouts-and-retries.md — use for: 타임아웃
  필수화·재시도 가능 오류 분류·백오프 규정

## Inputs
- `schemas/lir.schema.json` — 메시지에 실리는 IR 조각의 유효성 기준 (Task 02 산출물)
- `rfcs/0005-knowledge-base.md`의 소비 인터페이스 3종(`kb.route`/`kb.load`/`kb.verify`) (Task 07 산출물)
- plan.md: D8(JSON-RPC 2.0, A2A/MCP 계층 정렬), D13(신뢰성), D19(A2A 태스크
  수명주기·Agent Card·SSE), 골든 시나리오

## Steps
1. `rfcs/0006-agent-protocol.md`를 7섹션 템플릿으로 생성, Status=Draft
2. 에이전트 역할을 Charter 9종 그대로 고정: Planner, Architect, Coder, Reviewer,
   Tester, PerformanceAnalyzer, SecurityAuditor, RefactoringAgent, ReleaseAgent —
   각각: 입력 아티팩트, 출력 아티팩트, 읽기/쓰기 가능한 IR 대분류(D15 기준) 표
3. 메시지 계층(D8): JSON-RPC 2.0 — Guide-level에 업계 정렬 1문단(에이전트↔에이전트
   계층은 A2A와, 에이전트↔도구(컴파일러·KB 저장소 접근) 계층은 MCP와 같은 베이스
   위에 있으며 장기적으로 상호운용 가능하도록 어긋나는 확장을 만들지 않는다).
   메서드 네임스페이스 `agent.*`, `kb.*`, `ir.*` — 최소 메서드 셋:
   `agent.card`(능력 공표 조회 — A2A Agent Card 방식: 역할, 다루는 IR 대분류,
   지원 메서드를 구조화 JSON으로 반환), `agent.dispatch`(작업 위임),
   `agent.report`(결과 보고), `ir.get`/`ir.propose`(IR 조각 조회/변경 제안 —
   변경은 항상 제안+승인 2단계), `kb.route`/`kb.load`/`kb.verify`(RFC-0005
   인터페이스의 전송 표현). IR 조각은 `params.ir_fragment`에 lir.schema.json 유효
   JSON으로 임베드
3b. 태스크 수명주기 절(D19): `agent.dispatch`가 만드는 태스크는 상태기계
   `submitted → working → input-required → completed / failed / canceled`를
   따른다(A2A 준용). 장기 실행 태스크의 진행 통지·부분 결과 스트리밍은 SSE 준용.
   상태 전이 표(전이 조건·통지 이벤트) 포함
4. 오류 절(error-responses 적용): 구조화 오류 객체
   `{code, type, message, retryable, details}` — `type`은 머신리더블 enum
   (`ir_invalid`, `kb_version_conflict`, `agent_timeout`, `proposal_rejected`,
   `internal`), 내부 오류(`internal`)는 스택·내부 경로를 드러내지 않음.
   JSON-RPC 예약 코드(-32xxx)와의 매핑 표 포함
5. 신뢰성 절(idempotency + timeouts-and-retries 적용, D13):
   부작용 있는 메서드(`agent.dispatch`, `ir.propose`)는 `idempotency_key` 필수 —
   동일 키 재수신 시 저장된 최초 응답을 반환. 모든 호출에 데드라인 필수,
   재시도는 `retryable=true`에만 지수 백오프+지터, 최대 3회
6. Examples: 골든 시나리오로 파이프라인 1사이클 서술 — Planner가 Login intent를
   받아 `agent.dispatch`로 Architect에 위임 → Architect가 `ir.propose`로 Workflow
   노드 제안 → Coder가 `kb.route("generate token")`→`kb.load("security-jwt-issuance")`
   후 구현 → Reviewer 승인. 각 단계 실제 JSON-RPC 요청/응답 예시 3개 이상 수록
7. Open Questions: 에이전트 인증/권한, 사람 개입(HITL — `input-required` 상태에서의
   승인 UX), A2A/MCP와의 공식 호환성 인증 범위

## Deliverables
- `rfcs/0006-agent-protocol.md`

## Verify
- 체크리스트: (a) 9개 역할 전부 입력/출력/IR 접근권 표에 존재 (b) 오류 `type`
  enum과 JSON-RPC 코드 매핑 표 존재 (c) `agent.dispatch`·`ir.propose`에
  idempotency_key가 Examples의 JSON에 실제로 등장 (d) Examples의 ir_fragment가
  골든 시나리오 노드 id를 인용 (e) 태스크 상태기계 6상태 전이 표 존재 +
  `agent.card` 응답 예시 존재 (f) 7섹션 모두 비어있지 않음

## Out of scope
- 에이전트 구현·오케스트레이터 선정(ROADMAP), KB 문서 내용 규격(Task 07 소유)

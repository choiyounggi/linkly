# lnpp-rfc-suite — LNPP Charter를 6개 RFC로 구체화

Goal: LNPP Project Charter(0단계 비전 문서)를 구현 착수 가능한 수준의 설계 문서로
구체화한다. 산출물 = RFC 프로세스 문서 1개 + 설계 RFC 6개(문법 / Semantic IR /
컴파일러 / 런타임 / Knowledge Base / 에이전트 프로토콜) + 교차 정합성 검증 +
MVP 로드맵.

수용 기준(acceptance):
1. 6개 RFC가 모두 D7 템플릿의 7개 섹션을 갖추고 작성 완료.
2. 골든 시나리오 "Login"(아래)이 문법(.lnpl) → IR(.lir.json) → 컴파일 패스 →
   런타임 계약 → KB 참조 → 에이전트 메시지까지 전 RFC를 관통하며 동일하게 표현됨.
3. IR 골든 예제가 JSON Schema 검증 스크립트를 통과하고, 고의로 깨뜨린 예제는
   실패함(검증이 실패할 수 있음을 증명).
4. Task 09의 교차 정합성 체크리스트 전 항목 PASS.

Stack: 산출물은 전부 설계 문서(Markdown) + JSON Schema(draft 2020-12) +
검증 스크립트(Python 3.11+, `jsonschema` 패키지). 구현 코드는 이 계획의 범위 밖.

프로젝트 루트: `/Users/choeyeonggi/Desktop/workspace/ai/` (임시 로컬 레포 — 원격 레포 생성 시 remote 연결 예정). 이하 모든 상대경로는 이 루트 기준. 워크트리에서 실행될 땐 해당 워크트리 루트를 기준으로 한다.

## 골든 시나리오 "Login" (전 태스크 공통 — 여기서만 정의, 각 태스크는 참조만)

Charter 예제를 그대로 고정한다. 모든 RFC의 예제 섹션은 이 시나리오를 사용한다.

- Entity `User`: `id UUID`, `email Email`, `password Password`, `createdAt DateTime`
- Service `LoginService`
- Workflow `Login` 단계(순서 고정): `validate input` → `authenticate` →
  `cache user` → `generate token` → `audit login` → `return token`
- Policy: `retry 3`, `rollback`, `timeout 3s`
- Security: `jwt`
- Performance: `response < 50ms`, `cache 5m`
- Event: `UserCreated` (User 생성 시 발행)
- Capability: `postgres`, `redis`, `jwt`

## Decisions

`[ext]` 표기 결정의 외부 근거 원문·링크는 `docs/RESEARCH-NOTES.md` (2026-07-28 조사).

| # | Decision | Choice | Wiki basis |
|---|----------|--------|------------|
| D1 | 설계 허브 | Semantic IR(RFC-0001)이 허브. 문법은 IR로 lowering되는 표면 표기, 컴파일러·런타임·에이전트는 IR의 소비자로 정의 | [no-wiki] — Charter "Syntax보다 Semantic" 원칙의 구조화 |
| D2 | RFC 번호·순서 | 0000 프로세스 → 0001 Semantic IR → 0002 Syntax → 0003 Runtime → 0004 Compiler → 0005 Knowledge Base → 0006 Agent Protocol | [no-wiki] — 의존 순서(§Task order 근거 참조) |
| D3 | 언어 워킹네임 | **LNPL**, 소스 확장자 `.lnpl` (추후 개명 가능 — RFC 본문에서 "언어명은 워킹네임" 명시) | [no-wiki] |
| D4 | IR 직렬화 | JSON + JSON Schema draft 2020-12, 확장자 `.lir.json`. **저장 형식은 2-space pretty JSON**(LLM 가독), **동등성 비교·해시·서명용 canonical form은 RFC 8785(JCS)**. 스키마는 **constrained-decoding 호환 부분집합**으로 제한: 노드 판별은 `anyOf`(`oneOf` 금지), `default` 금지, root는 object, 중첩 ≤5레벨. 바이너리 포맷은 Open Questions | [ext] RFC 8785 (rfc-editor.org/info/rfc8785); OpenAI Structured Outputs 지원 스키마 제약(oneOf 미지원·no defaults·nesting ≤5) |
| D5 | 문법 형식화 | W3C-style EBNF, **라인 지향 + 키워드 구획 블록**: 블록은 여는 키워드~닫는 경계(다음 최상위 선언 키워드 또는 명시적 종결 키워드 — `parallel`은 `merge`로 종결, Charter 예제 그대로)로 정해지고 **들여쓰기는 비유의미**(관례 4칸, 탭 금지·표기 권장일 뿐). 중첩 깊이 ≤2로 제한. 키워드 전부 소문자, 한 줄 한 선언 | [ext] 포맷팅 토큰이 코드 토큰의 ~24.5%이며 오프사이드 언어는 제거 불가(arXiv:2508.13666); MoonBit AI-native 설계 "중첩 축소=KV-cache 친화"(LLM4Code 2024); Ronacher "A Language For Agents"(significant whitespace는 LLM에 불리). 초안의 오프사이드 룰을 근거로 기각 |
| D6 | RFC 검증 방식 | 각 RFC는 "실패 가능한 검증"을 가져야 함: IR은 스키마 검증 스크립트(부정 케이스 포함), 나머지는 골든 시나리오 관통 체크리스트 | testing/quality/tests-that-cannot-fail.md — 실패할 수 없는 검증은 검증이 아니다 |
| D7 | RFC 템플릿 | 고정 7섹션: Status / Motivation / Guide-level Explanation / Reference-level Specification / Examples(=골든 시나리오) / Alternatives / Open Questions | [no-wiki] — Rust RFC 관례 차용 |
| D8 | 프로토콜 베이스 | JSON-RPC 2.0 — **A2A(Agent2Agent)·MCP와 동일 베이스로 확증**. 계층 구분: 에이전트↔에이전트 = A2A 정렬, 에이전트↔도구(컴파일러·KB 저장소) = MCP 정렬. 오류는 코드+머신리더블 `type`+`retryable` 불리언 구조화 객체, 부작용 있는 메서드는 멱등키 필수 | backend/common/api-design/error-responses.md, idempotency.md; [ext] A2A 프로토콜(JSON-RPC 2.0+SSE+Agent Card), MCP |
| D9 | KB 문서 포맷 | Markdown + YAML frontmatter(id, category, triggers, version, status) + **3단 progressive disclosure**: ① 라우팅 인덱스(메타데이터만: id+1줄 트리거) → ② 문서 본문(트리거 매칭 시만 로드, **본문 ≤500줄**) → ③ 부속 리소스(본문이 지시할 때만). 루트 인덱스는 llms.txt 관례 준용 | [no-wiki] — dev-loop 위키 구조 차용; [ext] Anthropic Agent Skills의 progressive disclosure 패턴(메타→SKILL.md→리소스 3단 로딩)으로 확증 |
| D10 | 참조 구현 언어(후속 전제) | Rust(LLVM 바인딩·단일 바이너리 배포). 단 RFC 본문은 구현 언어 비종속으로 기술하고 이 결정은 ROADMAP에만 명시 | [no-wiki] |
| D11 | 문서 언어 | 한국어 본문 + 영어 식별자·키워드·스키마 필드명 | [no-wiki] — 사용자 작업 언어 |
| D12 | 런타임 관측성 계약 | metrics/trace/log 자동 생성은 RFC-0003에서 계약으로 명시: 상관ID 전파 필수, 메트릭 라벨에 무한 카디널리티 값(사용자ID·UUID) 금지 | infrastructure/observability/logs-metrics-signals.md |
| D13 | 프로토콜 신뢰성 | 에이전트 간 호출은 타임아웃 필수, 재시도는 `retryable=true` 오류에만, 지수 백오프+지터. RFC-0006에 규정 | backend/common/reliability/timeouts-and-retries.md |
| D14 | MVP 슬라이스 | 네이티브 컴파일 전에 **IR 인터프리터 먼저**: MVP = `login.lnpl` 파싱 → `.lir.json` 생성 → 인터프리터 실행. LLVM 백엔드는 Phase 2 | [no-wiki] — 검증 루프 최단화 |
| D15 | IR 노드 대분류 | Charter 목록 고정: Declaration(Entity/Service/Workflow/Event/Capability) · Behavior(BusinessRule/Validation/Workflow Step/Pipeline/Concurrency) · Effect(NetworkCall/RepositoryCall/CacheAccess/Transaction/Authorization/EventEmit) · Constraint(Policy/Security/Performance) | [no-wiki] — Charter "새 IR" 목록의 분류화 |
| D16 | Semantic Type 초기셋 | Charter 목록 고정 13종: UUID, Money, Email, Phone, Password, Address, Image, File, Currency, GeoLocation, Json, Html, Markdown + 원시 보조(Text, Integer, Decimal, Boolean, DateTime). 각 타입은 validation rule 필드를 가짐 | [no-wiki] |
| D17 | IR 구조 | **평탄(flat) 노드 테이블 + id 참조**: 자식은 인라인 중첩 객체가 아니라 노드 id 배열로 참조. 효과 — ① D4의 중첩 ≤5레벨 구조적 보장 ② 노드 단위 diff/fragment 교환 저비용 ③ 안정된 직렬화 순서로 KV-cache 프리픽스 재사용 | [ext] MoonBit "중첩 축소=KV-cache 친화"; OpenAI Structured Outputs nesting ≤5 제약. [no-wiki] 세부 배열 순서 규칙 |
| D18 | 컴파일러 lowering 경로 | 직접 IR→LLVM IR이 아니라 **MLIR 커스텀 dialect(`lnpl`) 경유 progressive lowering**: Semantic IR → lnpl dialect(고수준 최적화 3종이 dialect 패스) → 표준 dialect 하강 → LLVM dialect → Native. 고수준 시맨틱(Effect·Policy)이 살아있는 레벨에서 최적화 | [ext] MLIR 설계 목표 — 고수준 dialect에서 정보 보존 최적화 후 단계적 하강, 기존 하부 생태계 재사용(mlir.llvm.org, Lattner MLIR keynote) |
| D19 | 프로토콜 태스크 수명주기 | A2A 준용: 태스크 상태기계 `submitted → working → input-required → completed / failed / canceled`, 에이전트 능력 공표는 Agent Card 방식(`agent.card` 조회), 스트리밍은 SSE 준용(Open Question에서 승격) | [ext] A2A 프로토콜 태스크 lifecycle·Agent Card·SSE |
| D20 | RFC 채택 요건(피처 게이트) | Wasm 표준화 관례 준용 — 기능 채택에 4종 아티팩트: ① 명세(Reference-level) ② 산문 설명(Guide-level) ③ 참조 인터프리터 구현 ④ 테스트 스위트. RFC 단계(현재)는 ①②만, ③④는 ROADMAP Phase 1부터 게이트로 적용 | [ext] WebAssembly/spec — 참조 인터프리터는 "명확성·단순성 우선, 실행 가능한 명세" 관례 |

## Task order

| Task | Depends on | Parallel-ok |
|------|-----------|-------------|
| 00-scaffold-and-rfc-process | — | — |
| 01-rfc0001-semantic-ir-core | 00 | — |
| 02-rfc0001-ir-serialization | 01 | — |
| 03-rfc0002-syntax-core | 01 | 05, 07과 parallel-ok |
| 04-rfc0002-lowering-map | 02, 03 | — |
| 05-rfc0003-runtime | 01 | 03, 07과 parallel-ok |
| 06-rfc0004-compiler | 02, 05 | 08과 parallel-ok |
| 07-rfc0005-knowledge-base | 00 | 03, 05와 parallel-ok |
| 08-rfc0006-agent-protocol | 02, 07 | 06과 parallel-ok |
| 09-cross-consistency-and-roadmap | 04, 06, 08 | — |

순서 근거: IR(01·02)이 계약의 원천 → 문법(03·04)은 IR로의 lowering을 정의해야 하므로 IR 뒤 →
런타임(05)은 IR의 실행 의미를 정의 → 컴파일러(06)는 IR 스키마와 런타임 계약을 모두 소비 →
KB(07)는 프로세스 문서에만 의존해 조기 병렬 가능 → 프로토콜(08)은 IR 조각을 메시지에 싣고
KB 참조 방식을 인용 → 09가 전체를 봉합.

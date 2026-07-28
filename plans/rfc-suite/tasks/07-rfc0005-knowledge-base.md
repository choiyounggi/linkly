# Task 07: RFC-0005 Knowledge Base — 문서 스키마·라우팅·버저닝

## Objective
`rfcs/0005-knowledge-base.md`가 존재하고, 모든 AI 에이전트가 공유하는 KB의 문서
포맷·카테고리·라우팅·버저닝·소비 인터페이스가 정의되어 있다.

## Wiki pages (read these first, only these)
- (없음 — 포맷은 plan.md D9로 확정. dev-loop 위키 구조를 차용하되 본 태스크는
  RFC 본문만 작성)

## Inputs
- `rfcs/0000-rfc-process.md`의 7섹션 템플릿 (Task 00 산출물)
- plan.md: D9(Markdown+frontmatter+2단 라우팅), 골든 시나리오

## Steps
1. `rfcs/0005-knowledge-base.md`를 7섹션 템플릿으로 생성, Status=Draft
2. 카테고리를 Charter 12종 그대로 고정: Architecture, Naming, Performance,
   Security, Testing, Concurrency, Database, Cloud, Patterns, AntiPatterns,
   Style, Framework — 각각 1줄 정의와 대표 문서 예 1개
3. 문서 스키마 절(D9): YAML frontmatter 필수 필드 —
   `id`(kebab-case, 카테고리 접두), `category`(위 12종 enum), `triggers`
   (이 문서를 로드해야 하는 상황 서술 목록), `version`(semver),
   `status`(draft/verified/deprecated), `sources`(근거 링크 목록, 최소 1개).
   본문 규칙: 지시는 긍정형("X 상황엔 Y"), 금지형은 안전 임계에만, **본문 ≤500줄**
   (초과 시 분할 — progressive disclosure의 로드 단위 유지)
4. 라우팅 절(D9 개정판): **3단 progressive disclosure** — ① 라우팅 인덱스
   (루트 `INDEX.md` 카테고리→"route here when" + 카테고리 `index.md` 문서
   메타데이터(id+1줄 트리거)만, 항상 로드 가능한 목차 계층) → ② 문서 본문
   (트리거 매칭 시에만 로드) → ③ 부속 리소스(스키마·체크리스트·예제 파일 —
   본문이 명시적으로 지시할 때만 로드). 루트 인덱스는 llms.txt 관례를 준용한
   평문 마크다운. Guide-level에 이 구조의 근거(Anthropic Agent Skills의
   메타데이터→SKILL.md→리소스 3단 로딩 패턴 — 컨텍스트 토큰 절약) 1문단 서술
5. 소비 인터페이스 절: 에이전트가 KB를 읽는 논리 연산 3종을 함수 시그니처로 정의 —
   `kb.route(task_description) -> [doc_id]`, `kb.load(doc_id) -> document`,
   `kb.verify(doc_id, version) -> bool`(버전 핀 검증). 전송 표현은 RFC-0006이
   정의한다고 위임 명시
6. 갱신 수명주기 절: 신규 지식은 draft로 들어와 근거 검증 후 verified 승격,
   충돌 시 기존 문서 병합 우선(신규 문서 남발 금지)
7. Examples: 골든 시나리오와 연결 — Security 카테고리의 `security-jwt-issuance`
   문서 1편을 frontmatter 포함 완전한 예시로 수록(Login의 `generate token` step에서
   Coder 에이전트가 이 문서를 라우팅으로 로드하는 흐름 서술)

## Deliverables
- `rfcs/0005-knowledge-base.md`

## Verify
- 체크리스트: (a) 12개 카테고리 전부 정의됨 (b) frontmatter 필수 필드 6종이
  예시 문서에 모두 등장 (c) 소비 인터페이스 3종 시그니처 존재 (d) 7섹션 모두
  비어있지 않음

## Out of scope
- KB 전송 프로토콜 표현(Task 08 소유), 실제 KB 시드 문서 집필(ROADMAP)

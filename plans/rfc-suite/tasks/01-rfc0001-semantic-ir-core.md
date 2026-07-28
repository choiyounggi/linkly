# Task 01: RFC-0001 Semantic IR — 개념 모델·노드 카탈로그·타입 시스템

## Objective
`rfcs/0001-semantic-ir.md`가 존재하고, IR의 노드 대분류·노드별 필드·Semantic Type
시스템이 표로 완전히 정의되어 있다(직렬화 포맷은 다음 태스크).

## Wiki pages (read these first, only these)
- (없음 — 노드/타입 목록은 plan.md D15, D16으로 확정됨)

## Inputs
- `rfcs/0000-rfc-process.md`의 7섹션 템플릿 (Task 00 산출물)
- plan.md: D1(IR이 허브), D15(노드 대분류), D16(Semantic Type 초기셋), D17(평탄 노드
  테이블 + id 참조), 골든 시나리오

## Steps
1. `rfcs/0001-semantic-ir.md`를 7섹션 템플릿으로 생성, Status=Draft
2. Reference-level Specification에 D15의 4개 대분류(Declaration/Behavior/Effect/
   Constraint)별로 노드 카탈로그 표 작성. 각 노드마다: `kind`(영문 PascalCase 고정),
   필수 필드, 선택 필드, 자식 노드 허용 목록. AST를 쓰지 않는 이유(Charter "AST를
   버린다")를 Motivation에 서술
3. 모든 노드 공통 필드를 확정: `kind`, `id`(노드 고유, `svc.login.step.3` 형태의
   dot-path 문자열), `meta`(선택: 소스 위치·생성 주체). **구조는 D17 준수**:
   자식 노드는 인라인 중첩 객체가 아니라 `children: [<id>...]` 등 id 배열 참조로만
   표현 — 문서 전체는 평탄한 노드 테이블이다(중첩 트리 금지). 이 결정의 근거
   (constrained-decoding 중첩 한계, 노드 단위 diff, KV-cache 프리픽스 안정성)를
   Motivation에 1문단으로 서술
4. Semantic Type 시스템 절 작성: D16의 13+5 타입 각각에 대해 표(타입명, 의미,
   내장 validation rule, 예: Email→RFC 5322 형식 검증). 사용자 정의 타입은
   기존 타입 제약(refinement)으로만 허용한다고 규정
5. Examples 섹션: 골든 시나리오 Login의 Entity `User`와 Workflow `Login` 6단계를
   **평탄 노드 테이블(id | kind | 주요 필드 | children 참조)**로 표현하고, 참조
   관계는 별도의 화살표 목록(`wf.login → step 6개`)으로 병기
6. Open Questions에 최소 수록: 제네릭/컬렉션 타입, 바이너리 직렬화(D4), IR 버전 마이그레이션

## Deliverables
- `rfcs/0001-semantic-ir.md`

## Verify
- 체크리스트: (a) D15의 4대분류 아래 Charter가 명명한 노드 전부(BusinessRule,
  Validation, NetworkCall, RepositoryCall, CacheAccess, Transaction, Authorization,
  Concurrency, Workflow, Pipeline + Entity, Service, Event, Capability, Policy,
  Security, Performance, EventEmit)가 표에 존재 (b) D16의 18개 타입 전부 표에 존재
  (c) Examples가 골든 시나리오의 6단계 순서와 일치 (d) 7섹션 모두 비어있지 않음

## Out of scope
- JSON 직렬화 문법·스키마(Task 02), 문법 표기(Task 03), 실행 의미(Task 05)

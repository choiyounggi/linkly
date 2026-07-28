# Task 06: RFC-0004 Native Compiler — 파이프라인·패스·불변조건

## Objective
`rfcs/0004-compiler.md`가 존재하고, 소스→IR→네이티브 바이너리 파이프라인의 각
단계가 입력/출력/불변조건(invariant)과 함께 정의되어 있다.

## Wiki pages (read these first, only these)
- (없음 — 파이프라인 단계는 Charter + plan.md D18이 규정, 세부는 본 태스크에서 확정)

## Inputs
- `schemas/lir.schema.json` — 고수준 패스의 입출력이 이 스키마의 유효 문서여야 함 (Task 02 산출물)
- `rfcs/0003-runtime.md`의 메모리 프리미티브·actor 계약 (Task 05 산출물)
- plan.md: D14(MVP는 인터프리터 먼저 — 본 RFC에도 실행 모드 2종을 명시),
  D18(MLIR 커스텀 dialect 경유 progressive lowering)

## Steps
1. `rfcs/0004-compiler.md`를 7섹션 템플릿으로 생성, Status=Draft
2. 파이프라인 정의 표 작성 — Charter의 논리 단계를 유지하되 하강 경로는 D18의
   MLIR progressive lowering으로 구체화:
   `Semantic Parser → IR Validator → [고수준 패스: Architecture Optimizer →
   Concurrency Optimizer → Memory Optimizer (Semantic IR 레벨, 입출력 모두
   lir.schema.json 유효)] → lnpl MLIR dialect 변환 → 표준 dialect 하강(scf/async/
   memref 등) → LLVM dialect → Native Binary`.
   각 단계: 입력, 출력, 보존 불변조건(예: 고수준 패스는 lir.schema.json 유효성과
   노드 `id` 안정성을 보존 — id는 삭제만 가능, 재명명 불가; dialect 변환 후에는
   IR 노드 id를 MLIR location/attribute로 보존해 역추적 가능).
   Motivation에 직접 LLVM IR 대신 MLIR을 경유하는 이유 1문단(고수준 시맨틱이
   살아있는 레벨에서 최적화 + 하부 생태계 재사용 — MLIR 설계 목표) 서술
3. 실행 모드 절: 모드 A = IR 인터프리터(MVP, D14), 모드 B = LLVM 네이티브.
   두 모드가 동일한 관측 가능 동작을 내야 한다는 semantic equivalence 요구를 명시
4. Optimizer 3종의 책임 경계 표:
   - Architecture: capability 구현체 선택(postgres/redis 바인딩), Effect 노드 배치,
     자동 생성물(REST/OpenAPI/마이그레이션) 산출 지점
   - Concurrency: `parallel` 블록 스케줄링, 독립 step의 자동 병렬화 판정 기준
     (Effect 간 데이터 의존 없음 + 같은 capability 인스턴스 미공유)
   - Memory: Stack/Heap/Arena/Pool 선택 규칙(runtime RFC의 프리미티브에 매핑),
     escape analysis 적용 지점
5. 자동 최적화 목록(Charter의 Inline~Branch Prediction 9종)은 dialect 하강~LLVM
   단계 하위 절로 수록하되 각각 1줄 정의 + 발생 레벨(lnpl dialect / 표준 dialect /
   LLVM)만 표기(상세 알고리즘은 Open Questions로)
6. Examples: 골든 시나리오 `login.lir.json`이 각 Optimizer를 지날 때 무엇이
   변하는지 before/after 노드 스케치(예: Concurrency Optimizer가 `cache user`와
   `audit login`을 병렬화할 수 **없는** 이유 — 순서 의존 — 를 판정 기준으로 설명)
7. Open Questions: MLIR/LLVM 버전 고정 정책, lnpl dialect의 커스텀 op 목록 확정,
   증분 컴파일, 디버그 정보 포맷

## Deliverables
- `rfcs/0004-compiler.md`

## Verify
- 체크리스트: (a) 7단계 각각에 입력/출력/불변조건 3요소가 있음 (b) Optimizer
  3종의 책임이 서로 겹치지 않게 표로 구분됨 (c) Examples가 골든 시나리오 노드
  id를 실제로 인용 (d) 실행 모드 2종과 동등성 요구가 명시 (e) 7섹션 모두 비어있지 않음

## Out of scope
- 파서·인터프리터 구현(ROADMAP), 런타임 프리미티브 정의(Task 05 소유),
  에이전트가 컴파일을 트리거하는 프로토콜(Task 08)

# Task 09: 교차 정합성 검증 + MVP 로드맵

## Objective
6개 RFC 사이의 용어·계약 불일치가 해소되어 있고, 구현 착수 순서를 담은
`docs/ROADMAP.md`가 존재한다.

## Wiki pages (read these first, only these)
- wiki/testing/quality/tests-that-cannot-fail.md — use for: 정합성 체크리스트가
  "항상 PASS 되는 항목"이 되지 않도록 각 항목을 반증 가능한 형태로 작성

## Inputs
- `rfcs/0001-semantic-ir.md` ~ `rfcs/0006-agent-protocol.md` 전부 (Task 01~08 산출물)
- `examples/login.lnpl`, `examples/login.lir.json`, `scripts/validate_ir.py`
- `docs/GLOSSARY.md` (Task 00 산출물)
- plan.md: D10(참조 구현 Rust), D14(MVP = 인터프리터 슬라이스)

## Steps
1. `docs/CONSISTENCY-CHECK.md` 작성 — 아래 고정 체크리스트를 수행하고 각 항목에
   PASS/FAIL + 근거(파일·절 인용) 기록:
   - C1: RFC-0002 EBNF의 모든 최상위 선언 ↔ RFC-0001 Declaration 노드 1:1
   - C2: RFC-0003이 실행 의미를 정의한 노드 kind ⊇ RFC-0001 Effect 대분류 전체
   - C3: RFC-0004의 고수준 패스(Semantic IR 레벨 3종) 불변조건이 lir.schema.json
     유효성 보존을 포함하고, dialect 변환 이후 단계는 IR 노드 id 역추적 보존을 명시
   - C4: RFC-0006의 `kb.*` 메서드 시그니처 = RFC-0005 소비 인터페이스 3종 (이름·인자 일치)
   - C5: 골든 시나리오 요소(Entity User, 6 step, Policy 3종, Performance 2종,
     Event, Capability 3종)가 6개 RFC Examples 모두에서 동일 명칭으로 등장
   - C6: GLOSSARY의 10개 용어가 각 RFC에서 다른 의미로 재정의되지 않음
   - C7: `python3 scripts/validate_ir.py --self-test` exit 0
2. FAIL 항목은 해당 RFC를 수정해 해소(수정 원칙: IR이 정본 — plan.md D1 — 이므로
   충돌 시 RFC-0001 쪽 정의에 다른 RFC를 맞춘다). 해소 후 체크리스트 재수행,
   전 항목 PASS까지 반복
3. `docs/ROADMAP.md` 작성 — 3 Phase:
   - Phase 1 (MVP, D14): Rust로 `.lnpl` 파서 → `.lir.json` 산출 → IR 인터프리터로
     골든 시나리오 실행(capability는 인메모리 fake). 이 인터프리터는 성능이 아니라
     **실행 가능한 명세**가 목적(WebAssembly 참조 인터프리터 관례 — 명확성·단순성
     우선)이며, D20의 4종 아티팩트 게이트(명세+산문+참조구현+테스트 스위트)를
     이 Phase부터 적용. 완료 기준: `login.lnpl` 실행이 RFC-0003 Examples의
     타임라인과 일치 + 공식 테스트 스위트 디렉토리(`tests/`) 신설
   - Phase 2: LLVM 백엔드(모드 B) + Architecture Optimizer의 자동 생성물 1종
     (OpenAPI). 완료 기준: 모드 A/B 동일 동작(RFC-0004의 동등성 요구)
   - Phase 3: KB 시드 12카테고리 각 1문서 + 에이전트 2종(Planner, Coder)의
     프로토콜 왕복 데모. 완료 기준: RFC-0006 Examples 사이클 재현
   각 Phase에 선행 RFC와 예상 리스크(Open Questions 인용) 표기

## Deliverables
- `docs/CONSISTENCY-CHECK.md`
- `docs/ROADMAP.md`
- (FAIL 해소 과정에서 수정된 RFC 파일들 — 수정 목록을 CONSISTENCY-CHECK.md 말미에 기록)

## Verify
- `docs/CONSISTENCY-CHECK.md`의 C1~C7 전 항목 PASS + 각 항목에 파일·절 인용 근거 존재
- `python3 scripts/validate_ir.py --self-test` → exit 0

## Out of scope
- Phase 1 구현 착수(별도 계획), RFC Status의 Accepted 승격(사용자 리뷰 후 결정)

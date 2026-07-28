# Task 00: 프로젝트 골격 + RFC-0000 프로세스 문서

## Objective
레포 루트(작업 중인 워크트리 루트)에 골격이 만들어지고, 이후 모든 RFC가 따를 템플릿·
용어집·수명주기를 정의한 RFC-0000이 존재한다.

## Wiki pages (read these first, only these)
- (없음 — 전 결정이 plan.md D2, D3, D7, D11로 확정됨)

## Inputs
- `plans/rfc-suite/plan.md`의 Decisions 표(D2, D3, D7, D11)와 골든 시나리오 정의
- `CHARTER.md` (프로젝트 루트에 이미 존재 — 계획 단계에서 박제됨. 수정 금지, 읽기만)

## Steps
1. 디렉토리 생성: `rfcs/`, `schemas/`, `examples/`, `scripts/`, `docs/`
2. `CHARTER.md`가 존재하고 비어있지 않은지 확인만 한다(내용 수정 금지)
3. `rfcs/0000-rfc-process.md` 작성:
   - RFC 수명주기: `Draft → Review → Accepted → Superseded` 4단계
   - D7의 고정 7섹션 템플릿을 복붙 가능한 마크다운 블록으로 수록
   - 번호 체계: D2의 0000~0006 고정, 이후 신규는 0007부터 증가
   - 문서 언어 규칙: D11(한국어 본문 + 영어 식별자)
   - 골든 시나리오 규칙: 모든 RFC의 Examples 섹션은 plan.md의 "Login" 시나리오를 사용
4. `docs/GLOSSARY.md` 작성 — Charter에 등장하는 용어 정의(최소): Intent, Semantic IR,
   Semantic Type, Capability, Workflow, Policy, Knowledge Base(KB), Agent Pipeline,
   Lowering, LNPL(D3 워킹네임)

## Deliverables
- `rfcs/0000-rfc-process.md`
- `docs/GLOSSARY.md`

## Verify
- 체크리스트: (a) 0000 문서에 7섹션 템플릿 블록이 있고 섹션명이 D7과 글자 단위로 일치
  (b) GLOSSARY에 위 10개 용어가 모두 있음 (c) CHARTER.md가 원문 그대로임
- `ls rfcs schemas examples scripts docs` 가 에러 없이 5개 디렉토리를 보여줌

## Out of scope
- RFC 0001~0006의 내용 작성(다음 태스크들), git init·CI 설정(ROADMAP에서 다룸)

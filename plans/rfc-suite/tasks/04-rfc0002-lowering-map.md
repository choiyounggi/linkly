# Task 04: RFC-0002 부록 — Lowering 매핑(문법→IR) + 골든 예제 봉합

## Objective
LNPL 문법 구성요소 각각이 어떤 IR 노드로 lowering되는지의 완전한 매핑 표가 존재하고,
`examples/login.lnpl`과 `examples/login.lir.json`이 그 표를 통해 1:1 대응함이
검증되어 있다.

## Wiki pages (read these first, only these)
- (없음 — 매핑 대상 양끝이 Task 01·03 산출물로 확정됨)

## Inputs
- `rfcs/0002-syntax.md`의 EBNF와 Examples 절 Login 소스 (Task 03 산출물)
- `rfcs/0001-semantic-ir.md`의 노드 카탈로그 (Task 01 산출물)
- `examples/login.lir.json`, `scripts/validate_ir.py` (Task 02 산출물)

## Steps
1. `examples/login.lnpl` 생성 — `rfcs/0002-syntax.md` Examples 절의 Login 소스를
   그대로 파일로 추출(내용 불일치 금지, 복사만)
2. `rfcs/0002-syntax.md`에 "부록 A: Lowering 매핑" 추가 — 3열 표:
   `문법 생산규칙(EBNF 이름) | IR 노드 kind | 매핑 규칙 비고`.
   EBNF의 모든 생산규칙이 행으로 존재해야 하며, IR 노드를 만들지 않는 규칙
   (순수 구문 규칙)은 kind 열에 `—`와 사유를 기입
3. 부록 A 끝에 "골든 예제 대응표" 추가 — `login.lnpl`의 줄 번호 ↔
   `login.lir.json`의 노드 `id`를 짝지은 표. workflow 6단계는 각 step 줄 ↔
   step 노드 id가 순서대로 대응해야 함
4. 대응표 작성 중 두 파일 사이 불일치를 발견하면 **IR 쪽이 정본**(plan.md D1):
   `login.lnpl`과 `rfcs/0002-syntax.md` Examples를 고쳐 맞추고, 스키마 위반이
   의심되면 `python3 scripts/validate_ir.py examples/login.lir.json`으로 재확인

## Deliverables
- `examples/login.lnpl`
- `rfcs/0002-syntax.md` 부록 A 추가 (수정)

## Verify
- `python3 scripts/validate_ir.py examples/login.lir.json` → exit 0 (봉합 후에도 유효)
- 체크리스트: (a) 부록 A 표의 행 수 ≥ EBNF 생산규칙 수 (b) 골든 예제 대응표에서
  workflow 6단계가 소스 줄과 IR 노드 id로 모두 순서 일치 (c) `login.lnpl`과
  RFC Examples 코드 블록이 diff 없이 동일

## Out of scope
- 실제 파서 구현(ROADMAP/MVP), 컴파일 패스에서의 IR 변형(Task 06)

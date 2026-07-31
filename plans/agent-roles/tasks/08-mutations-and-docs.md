# Task 08: 뮤테이션 확장 + 문서 갱신

## Objective
새 역할들의 규율이 실제로 강제되는지 뮤테이션으로 증명하고, README·ROADMAP·이슈에
현재 상태를 반영한다.

## Wiki pages (read these first, only these)
- wiki/testing/quality/tests-that-cannot-fail.md — use for: 각 뮤테이션이 반드시
  RED를 내야 한다는 기준

## Inputs
- `impl/tests/mutation_check.py` — 현재 30종
- 03~07 산출물(새 역할들)
- 결정: 수용 기준 6

## Steps
1. 뮤테이션 6종 추가 — 각각 "규율을 없애면 잡히는가":
   - Reviewer: `_assess`를 항상 `(True, "")`로 (판단력 제거)
   - Reviewer: `provenance` 검사 제거
   - Architect: spec 불완전해도 제안
   - SecurityAuditor: 이미 Security가 있어도 덮어쓰기
   - PerformanceAnalyzer: 측정치 없어도 제안
   - Tester: `EXPECTATIONS` 밖 기대를 생성
2. README 양 언어의 에이전트 서술을 갱신: 3종 → 8종, RefactoringAgent만 남음.
3. `docs/ROADMAP.md` Phase 3 배너에 현재 상태 한 줄 추가.
4. 이슈 #2에 진행 코멘트를 남길 준비(본문은 오케스트레이터가 게시).

## Deliverables
- `impl/tests/mutation_check.py`
- `README.md`, `README.ko.md`, `docs/ROADMAP.md`

## Verify
- `.venv/bin/python impl/tests/mutation_check.py` → no-op 대조군 SURVIVED + 전 항목
  CAUGHT, exit 0. (실행 결과: 53/53 — 역할별 항목과, 적대적 재감사가 드러낸 Reviewer
  규칙별 항목을 추가한 뒤의 수. 대조군이 CAUGHT면 하네스 고장이므로 즉시 중단한다.)
- `PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl` → OK
- README 섹션 수 en == ko

## Out of scope
- RefactoringAgent(RFC-0006 개정 필요), 이슈 종료

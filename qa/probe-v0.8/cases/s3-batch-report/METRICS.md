# METRICS — s3-batch-report

| 지표 | 값 | 측정 방법 |
|------|-----|-----------|
| 소스 줄 수 (.lnpl 또는 .py, 공백·주석 제외) | domain.lnpl ~45, settlement.lnpl ~90, seed.py 126, glue.py 54, oracle.py ~140, bench.py ~55, run_settlement.py ~65, run_rollup.py ~45 (합계 ~620) | `grep -cve '^\s*$' <file>` |
| 파일 수 | 8 (`src/domain.lnpl`, `src/settlement.lnpl`, `src/seed.py`, `src/glue.py`, `src/oracle.py`, `src/bench.py`, `src/run_settlement.py`, `src/run_rollup.py`) | — |
| authoring 라운드 (편집→재실행 사이클 총계) | round 1: 5 (4 `.lnpl` + 1 seed포맷); round 2: 9 (8 `.lnpl` + 1 harness버그) — 합계 14 | evidence/01-authoring.md 합산 |
| 실행한 CLI 명령 수 | round 1 ~24 + round 2 ~120(`lnpl run`×100(50가맹점×2pass), `lnpl trigger`×50, `lnpl migrate`×6, `lnpl serve`/`openapi`/`spec`×5, `python3 oracle.py/glue.py/bench.py`×~15, `sqlite3 .backup`×2) ≈ 144 | evidence 전수 + 세션 로그 재구성 |
| 첫 컴파일 성공까지 라운드 | 1 (domain.lnpl 단독, probe 제외) | evidence/02-compile.md |
| 첫 spec 전건 통과까지 라운드 | 2 (`empty repository`+`stored` 모순 → 드롭 후 통과) | evidence/04-spec.md |
| spec 시나리오 수 / 단언 수 | 4 / 33 (C1 9, C2 4, C3-analog 6, rerun 9 — rerun 블록은 spec 자체의 delete 버그(F-10)로 7 FAIL, 나머지 24 PASS) | evidence/04-spec.md |
| 요구사항 충족 / 부분 / 불가 / 우회 (개수) | 충족 5(R1,R2,R5,R6,R7) / 부분 1(R10) / 불가 1(R8) / 우회 3(R3,R4,R9) | FINDINGS.md 커버리지 표 집계 |
| 결함 탐지: spec이 잡은 것 / 사람이 실행 출력을 보고 잡은 것 / 못 잡고 지나간 것 | 1(F-10, spec 자신의 delete 버그를 spec 실행 결과가 직접 드러냄) / 9(money-encode-precision, input 필드 전역 규칙, avg-of-empty-rowset, create-conflict, expose Money/desc 거부, openapi create-as 크래시, write-conflict 자기충돌, migrate 무동작, camelCase 바인딩 규칙) / N/A | evidence 01·02·03·04·06·08·10 |
| 읽은 문서 (파일 목록과 대략 줄 수) | round 1 목록(evidence/00-env.md) + round 2 추가: docs/serving.md(경로 매핑·스케줄, ~60줄), docs/backends.md §14(백업, ~30줄), docs/migration.md(expand/migrate, ~60줄), rfcs/0030(create-as 바인딩, ~40줄), rfcs/0002(ServiceClause, ~20줄), lnpl-authoring/references/naming.md(전체, 71줄) | 워커가 실제로 Read한 것 |
| 변경 요청(R-change) 반영: 바뀐 줄 수 / 라운드 / 기존 spec 중 깨진 것 | N/A(이 케이스에 변경 요청 시나리오 없음) | — |
| 벽시계 시간 (시작~FINDINGS 완성) | round 1: 2026-09-05 16:30Z~16:50Z(≈21분, 예산 오독으로 조기 종료); round 2: 16:55Z~17:23Z(≈28분); round 3: 코디네이터 리뷰 대기 후 2026-09-06 12:47Z 재개(대기 시간 제외, 활성 작업 ~15분) — 능동 작업 합계 ≈64분 | `date -u` (라운드별 시작/종료 실측) + status t3.json 타임스탬프 대조 |
| 토큰 | (코디네이터 기입) | token-report.sh |

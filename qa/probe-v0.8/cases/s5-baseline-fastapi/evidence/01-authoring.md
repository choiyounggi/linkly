# 01 — Authoring rounds

라운드 정의(D11): 편집 → (pytest 또는 lint-imports 또는 uvicorn) 1회 실행 = 1라운드.
카운팅 명령: `wc -l < evidence/01-authoring.md`에서 `round ` 로 시작하는 줄 수 (표 아래 참고).

round 1 — `PYTHONPATH=src .venv-s5/bin/python -c "import orderhub.db, orderhub.app"` — rc=0 — 패키지 스켈레톤(db.py/app.py/inventory.py) 작성 직후 import 성립 확인
round 2 — `cd src && ../.venv-s5/bin/lint-imports` — rc=1 "Could not read any configuration" — cwd에서 `.importlinter`를 못 찾음(설정 파싱 실패, 계약 위반 아님) → 케이스 루트에서 `--config .importlinter`로 재실행 필요 발견
round 3 — `PYTHONPATH=src .venv-s5/bin/lint-imports --config .importlinter` (위반 import 삽입 상태) — rc=1 "orders.inventory is internal to the orders team BROKEN" — R1 경계가 실제로 거부됨을 증명
round 4 — `PYTHONPATH=src .venv-s5/bin/lint-imports --config .importlinter` (위반 import 제거 후) — rc=0 "KEPT" — 경계 통과 확인
round 5 — `.venv-s5/bin/pytest -q tests -k "a1 or a2 or a3"` — rc=0 — 3 passed — place_order/router/conftest 작성 후 A1~A3 첫 실행
round 6 — `PYTHONPATH=src .venv-s5/bin/lint-imports --config .importlinter` — rc=1 — 예상 못 한 실패: `orderhub.app -> orders.router -> orderhub.db -> orders.inventory` 간접 경로가 forbidden contract에 걸림(db.py가 STOCK_DDL을 inventory에서 import했었음) — 아키텍처 수정 필요 발견
round 7 — `db.py`에서 STOCK_DDL import 제거, stock/stock_reservation DDL을 db.py 자체 스크립트로 복귀 → 재실행 `lint-imports` — rc=1 — 여전히 실패: 이번엔 `app -> orders.router -> orders.service -> orders.inventory`(같은 팀 내부의 정당한 조립 경로)가 걸림 — forbidden contract 기본값이 간접 import까지 검사한다는 것을 확인(소스 읽음: `.venv-s5/lib/python3.13/site-packages/importlinter/contracts/forbidden.py`)
round 8 — `.importlinter`에 `allow_indirect_imports = True` 추가 → 재실행 — rc=0 "KEPT"; 위반 재주입 재실행 — rc=1 "BROKEN"(직접 import는 여전히 잡힘); 위반 제거 재실행 — rc=0 — 최종 확정
round 9 — `.venv-s5/bin/pytest -q tests` — rc=0 — 3 passed — 스키마 변경 후 회귀 확인
round 10 — `.venv-s5/bin/pytest -q tests` (state.py, payments/service.py+router.py, A4/A5/simulate_failure/illegal-matrix 추가 후) — rc=0 — 13 passed, 9 skipped(cancelled 타깃은 task 04에서 cancel 엔드포인트 추가 후 커버) — 첫 실행에 통과
round 11 — `PYTHONPATH=src .venv-s5/bin/lint-imports --config .importlinter` — rc=0 — KEPT — payments/state 추가 후 경계 재확인
round 12 — `.venv-s5/bin/pytest -q tests` (cancel_order/refund/require_admin/A6~A8/injected/limit 추가 후) — rc=1 — `test_a7_...` FAIL: `sqlite3.OperationalError: ambiguous column name: amount`(refund·payment 두 테이블 모두에 `amount` 컬럼, JOIN에서 미명시) — 테스트 쿼리 버그, 프로덕션 코드 결함 아님
round 13 — 테스트 쿼리에 `r.amount AS amount` alias 추가 → 재실행 `.venv-s5/bin/pytest -q tests` — rc=0 — 20 passed, 7 skipped(대상이 pending/paid이고 그 상태로 되돌리는 엔드포인트 자체가 API에 없어 스킵 — 정상)
round 14 — `PYTHONPATH=src .venv-s5/bin/lint-imports --config .importlinter` — rc=0 — KEPT — cancel/refund 추가 후 경계 재확인
round 15 — `ORDERHUB_TEST_HOOKS=1 .venv-s5/bin/pytest -q tests -p no:cacheprovider` — rc=0 — 20 passed, 7 skipped — D14 evidence용 첫 green 캡처
round 16 — A1 기대값 4318→4319로 변경 후 재실행(D14) — rc=1 — 1 failed(의도된 red) — evidence/03에 기록
round 17 — 기대값 4318로 복원 후 재실행(D14) — rc=0 — 20 passed, 7 skipped — evidence/03에 기록
round 18 — `python -m orderhub.seed` (실서버 시드) — rc=0 — live.db 시드 성공
round 19 — `uvicorn orderhub.app:app --port 8765` 기동 + `curl openapi.json` — rc=0 — openapi 3.1.0, 경로 7개 확인
round 20 — curl A1~A8 순서대로 실행(evidence/05-serve.md) — 전부 기대값과 일치, 재시도 없음
round 21 — R10(gift_wrap) 3파일(db.py/orders/router.py/orders/service.py) 수정 + 테스트 3개 추가 후 `ORDERHUB_TEST_HOOKS=1 .venv-s5/bin/pytest -q tests` — rc=0 — 23 passed, 7 skipped(기존 20개 그대로 + 신규 3개, 깨진 것 0건) — 재시도 없이 첫 실행에 통과
round 22 — `PYTHONPATH=src .venv-s5/bin/lint-imports --config .importlinter` — rc=0 — KEPT — R10 반영 후 경계 최종 재확인
round 23 — test-quality-auditor(별도 세션) 결과 반영: (1) `ILLEGAL_PAIRS`를 구현체의 `TRANSITIONS`가 아닌 스펙 R4 표에서 직접 하드코딩, (2) `to_status=="paid"` 케이스를 스킵 대신 실제 `/pay` 호출로 커버, (3) `test_simulate_failure`에 예약 유지(R5 "예약은 유지") DB 단언 추가, (4) `test_a3`/`test_a5`/`test_simulate_failure`의 느슨한 상태코드 범위(400~500)를 정확한 422로 교체 → `ORDERHUB_TEST_HOOKS=1 .venv-s5/bin/pytest -q tests` — rc=0 — 26 passed, 4 skipped(진짜로 API에 없는 pending 복귀만 남음)
round 24 — 뮤테이션 재현: `payments/service.py`의 pending 가드 제거 → 재실행 — rc=0(11 passed, 여전히 통과: `state.transition()` 호출이 별도로 방어하고 있음을 확인, 원복) — `orders/state.py`의 `delivered: set()` → `delivered: {"shipped"}`로 완화 → 재실행 — rc=1 `test_illegal_transitions[delivered-shipped]` FAILED(의도대로 잡힘, 원복) — `PYTHONPATH=src .venv-s5/bin/lint-imports --config .importlinter` 재확인 rc=0

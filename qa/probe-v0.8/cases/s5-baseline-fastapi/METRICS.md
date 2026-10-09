# METRICS — s5-baseline-fastapi

| 지표 | 값 | 측정 방법 |
|------|-----|-----------|
| 소스 줄 수 (.py, 공백·주석 제외) | 548 (src) + 385 (tests: 359+26) = 933 | `grep -cve '^\s*$' src/orderhub/*.py src/orderhub/*/*.py` 및 `tests/*.py` |
| 파일 수 | 16 (src) + 2 (tests: test_a1_a8.py, conftest.py) = 18 | `find src/orderhub -name '*.py'` |
| authoring 라운드 (편집→재실행 사이클 총계) | 24 | evidence/01-authoring.md의 `round ` 줄 수 |
| 실행한 CLI 명령 수 | ~50 | evidence 전수(설치·venv·pytest·lint-imports·curl·uvicorn·python 검증·뮤테이션 재현 명령 합산; 정확한 나열은 evidence/00~09 참고) |
| 첫 컴파일(=import) 성공까지 라운드 | 1 | evidence/01 round 1 |
| 첫 spec(=pytest) 전건 통과까지 라운드 | 각 태스크의 신규 테스트는 첫 실행에 통과(round 5, 10, 15, 21); 세션 전체에서 red는 2건: round 12(테스트 코드의 ambiguous-column 버그, round 13에서 즉시 수정)와 독립 test-quality-auditor 검토 후 round 23(테스트 커버리지 갭 자체 수정, round 23에서 즉시 green) | evidence/01 |
| spec 시나리오 수 / 단언 수 | 26개 pytest 노드(파라미터화 포함, 16개 정의 중 `test_illegal_transitions` 1개가 11개로 확장 — pending 타깃 4개는 API에 없어 skip) / 83개 assert | `grep -c '^def test_'`, `grep -c 'assert '` on tests/test_a1_a8.py |
| 요구사항 충족 / 부분 / 불가 / 우회 (개수) | 충족 10 / 부분 0 / 불가 0 / 우회 0 | 커버리지 표(FINDINGS.md) 집계 |
| 결함 탐지: spec이 잡은 것 / 사람이 실행 출력을 보고 잡은 것 / 못 잡고 지나간 것 | 2 / 1 / 0 | spec=round 12 ambiguous-column 테스트 버그(pytest가 즉시 실패로 잡음); 사람=import-linter 결과를 읽고 근본 원인(db.py의 불필요한 orders.inventory 의존)을 찾아 아키텍처를 고침(round 6~8); **독립 리뷰(test-quality-auditor)**가 자체 개발 중에는 못 잡았던 테스트 커버리지 갭 3건(paid-타깃 illegal-transition 미검증, ILLEGAL_PAIRS가 구현체 자기참조, R5 예약유지 미단언)을 발견 → round 23에서 즉시 수정(자기 평가 vs 독립 평가 분리의 실효성을 보여주는 데이터); 못 잡고 지나간 것=0(세션 종료 시점까지 미해결로 남은 결함 없음) |
| 읽은 문서 (파일 목록과 대략 줄 수) | requirements/README.md(85줄) · FINDINGS-SCHEMA.md(87줄) · s1.md(49줄) · s5.md(31줄) = 4개 파일 ~252줄; 그 외 설치한 패키지 문서는 열람하지 않음(에러 메시지·타입 힌트·`--help`만 사용) | 워커가 실제로 Read한 파일 |
| 변경 요청(R-change) 반영: 바뀐 줄 수 / 라운드 / 기존 spec 중 깨진 것 | +18/-4줄(파일 3개) / 1라운드(round 21, 재시도 0) / 0건 | evidence/06-change-request.md |
| 벽시계 시간 (시작~FINDINGS 완성) | 2026-09-05T16:37Z ~ 2026-09-05T17:1Xz경(독립 리뷰 대기 포함 ~40분) | evidence/00-env.md 시작 타임스탬프 + 세션 타임스탬프 |
| 토큰 | (코디네이터 기입) | token-report.sh |

## 추가 지표 (s5.md, 대조군 전용)

| 지표 | 값 |
|------|-----|
| 비즈니스 규칙 1개당 평균 줄 수 (R2~R7 6개 규칙 / 관련 코드 줄) | ~29 (R2 재고예약 ~45[inventory.py 28+place_order 재고부분], R3 금액계산 ~15[money.py 7+인라인], R4 상태전이 19[state.py], R5 결제 37[pay()], R6 취소원자성 25[cancel_order()], R7 환불 32[refund()] → 합 173/6 ≈ 28.8; place_order가 R2·R3를 한 함수에서 같이 처리해 경계가 흐릿함 자체가 결과) |
| 규칙이 코드 어디에 있는지 찾는 데 걸린 파일 수 (R10 변경 시) | 3 (db.py 스키마, orders/router.py 입력 모델, orders/service.py 비즈니스 로직) — 사전에 아키텍처를 알고 있었으므로 탐색 라운드 없이 바로 3곳을 짚음(evidence/06 참고) |
| 상태 전이 표(R4)가 코드에서 한 곳에 모여 있는가 | 예 — `orders/state.py`의 `TRANSITIONS` dict 1개, `transition()` 1개 함수로 모든 상태 변경이 통과 |
| 카드 원문 미노출(R5)을 **보장**하는 장치 (테스트? 타입? 없음?) | 테스트만(타입 시스템은 미보장). `card_number: str`가 여전히 함수 인자로 전달 가능하고, `card_last4 = card_number[-4:]`를 개발자가 빼먹어도 파이썬 타입 체커는 잡지 못함 — A4/`test_a4_pan_not_in_logs`가 DB dump·응답·로그 3채널에서 원문 부재 + last4 존재(음성 대조)를 실행 시점에 검증하는 것이 유일한 보장 |

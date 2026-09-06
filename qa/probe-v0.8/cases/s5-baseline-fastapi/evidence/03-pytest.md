# 03 — pytest full run + D14 flip-red-restore

명령: `ORDERHUB_TEST_HOOKS=1 .venv-s5/bin/pytest -q tests -p no:cacheprovider`

## Green (첫 실행)

```
.........s.ss.ss..ss.......                                              [100%]
20 passed, 7 skipped, 2 warnings in 0.26s
rc=0
```

7 skipped는 `test_illegal_transitions`에서 목표 상태가 `pending`/`paid`이고 그 상태로
"되돌리는" 엔드포인트 자체가 API에 없어서(요구사항에도 없음) 스킵된 것 — 결함이 아니다.

## D14 — 의도적 flip-red

`tests/test_a1_a8.py`의 `test_a1_standard_order` 기대값을 `4318` → `4319`로 1회 변경 후
재실행:

```
>       assert body["total"] == 4319  # D14: deliberately wrong, temporary — flip-red proof
E       assert 4318 == 4319

tests/test_a1_a8.py:23: AssertionError
FAILED tests/test_a1_a8.py::test_a1_standard_order - assert 4318 == 4319
1 failed, 19 passed, 7 skipped, 2 warnings in 0.27s
rc=1
```

기대값을 `4318`로 복원 후 재실행 (green):

```
20 passed, 7 skipped, 2 warnings in 0.49s
rc=0
```

## 저장소 단언 커버리지

`grep -c "SELECT" tests/test_a1_a8.py` → **22** (SELECT 문 수) vs
`grep -c "^def test_" tests/test_a1_a8.py` → **13** (테스트 함수 수, 파라미터화된
`test_illegal_transitions`는 1개 정의로 여러 케이스를 생성) — 테스트당 평균 1개 이상의
SELECT 단언을 포함(파라미터화 테스트는 상태 값 자체가 assert 대상).

이 위 수치(20 passed/22 SELECT/13 def)는 D14 flip-red-restore 시점(evidence/01
round 15~17)의 스냅샷이다. 이후 독립 리뷰(test-quality-auditor)가 지적한 테스트
커버리지 갭 3건을 수정(round 23~24, FINDINGS.md F-5)하면서 테스트가 늘어났다 —
FINDINGS/METRICS가 최종적으로 인용하는 숫자는 아래 Final run 기준이다.

## Final run (독립 리뷰 반영 후, integration-r1 I4 대응)

명령: `date -u && ORDERHUB_TEST_HOOKS=1 .venv-s5/bin/pytest -q tests -p no:cacheprovider`

```
2026-09-06T14:03:49Z
.........s.s..s...s...........                                           [100%]
26 passed, 4 skipped, 2 warnings in 0.43s
rc=0
```

4 skipped는 전부 `test_illegal_transitions`에서 목표 상태가 `pending`인 케이스다
(그 상태로 "되돌리는" 엔드포인트 자체가 API·요구사항에 없음 — 정상). "→paid" 3개
케이스는 더 이상 스킵되지 않고 실제 `/pay` 호출로 커버된다(round 23 수정).

`PYTHONPATH=src .venv-s5/bin/lint-imports --config .importlinter` → `Contracts: 1 kept, 0 broken`(rc=0, 회귀 없음 재확인).

저장소 단언 커버리지(최종): `grep -c "SELECT" tests/test_a1_a8.py` → **28**,
`grep -c "^def test_" tests/test_a1_a8.py` → **16**(파라미터화 포함 26 노드 = 26 passed
+ 4 skipped와 일치). FINDINGS.md 케이스 판정과 METRICS.md 11행은 이 Final run
수치(26 passed, 4 skipped / 26 노드 / 83 assert)를 그대로 인용한다.

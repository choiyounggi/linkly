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

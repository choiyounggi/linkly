# Task 04: 테스트의 LNPL_LLVM_BIN 오염을 복원 방식으로 수리한다

## Objective
`TestLlvmBinOverride`가 어떤 순서로 실행돼도 `LNPL_LLVM_BIN`의 호출자 값이 보존된다. 같은 미복원 패턴이 impl/tests에 더 없음이 스윕으로 증명된다. 재-dispatch에서 toolchain-unavailable류 실패 0건.

## Wiki pages (read these first, only these)
- wiki/testing/data/test-data-and-isolation.md — use for: "env 변수를 만진 테스트는 setup에서 설정, 실패 시에도 도는 teardown에서 복원" 행
- wiki/debugging/methodology/verify-the-fix.md — use for: 수정 후 같은 경로(재-dispatch)로 검증

## Inputs
- plans/i169-mutation-baseline/runner-evidence.md — 원인 판정
- impl/tests/test_backend.py:568-612 (TestLlvmBinOverride)
- Decisions that bind you: D9, D5 (검증은 운영 경로), D6

## Steps
1. Red 테스트: test_backend.py에 `TestLlvmBinOverrideRestoresCallerEnv` 추가 — setUp 없이, 케이스 3개:
   - 정상: os.environ["LNPL_LLVM_BIN"]="SENTINEL-DIR" 설정(addCleanup으로 자기 복원) 후 `unittest.TestLoader().loadTestsFromTestCase(TestLlvmBinOverride)`를 `unittest.TextTestRunner(stream=io.StringIO())`로 실행 → 실행 후 os.environ.get("LNPL_LLVM_BIN") == "SENTINEL-DIR" 단정
   - 경계값: 변수 미설정 상태에서 같은 실행 → 실행 후에도 미설정(None) 단정
   - 에러 경로: 위 실행의 result.wasSuccessful() 단정 (오염 수리로 기존 3케이스가 깨지지 않음)
2. 수정: TestLlvmBinOverride.setUp에 `self._original_llvm_bin = os.environ.get("LNPL_LLVM_BIN")` 저장; tearDown의 `os.environ.pop("LNPL_LLVM_BIN", None)`를 조건부 복원으로 교체 (원래 None이면 pop, 아니면 되돌림).
3. 스윕(defect clustering): `grep -n "os.environ\[" impl/tests/*.py`와 `grep -n "os.environ.pop\|del os.environ" impl/tests/*.py`로 **직접 변이** 전수 열거(절단 금지). 각 히트를 setUp/tearDown/addCleanup 복원 여부로 판정해 표로 기록 — 미복원이면 같은 방식으로 수리. (subprocess에 넘길 dict 복사본 변이는 오염 아님 — 제외 근거를 명시.)
4. 전체 스위트 로컬 green 확인 후 같은 브랜치에 커밋·push, `gh workflow run "Mutation testing" --ref fix/i169-mutation-baseline-red` 재실행 → baseline 판정 관측. GREEN이면 R3 충족; 새 실패가 드러나면 그 증거로 runner-evidence.md 갱신 후 다음 repair 라운드 (bounded).

## Deliverables
- impl/tests/test_backend.py (수정 — 복원 + 회귀 테스트)
- 스윕에서 미복원으로 판정된 추가 파일 (있으면; 3파일 상한 초과 시 분할 제안)
- plans/i169-mutation-baseline/runner-evidence.md (재-dispatch 결과 추기)

## Verify
- PYTHONPATH=impl .venv/bin/python -m unittest tests.test_backend -q → rc 0
- 전체 스위트: 기준선(3783/failures=1 기지)과 실패 집합 동일
- 재-dispatch run에서 "baseline (unmutated copy): GREEN" 또는 새 실패 집합 기록
- covers: R3

## Out of scope
- 오염 이외의 새로 드러나는 러너 실패 수정 (다음 repair 라운드)
- CI 배선 변경

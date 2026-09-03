# Task 06: stale anchor 4건을 현재 코드로 재고정한다

## Objective
MUTATIONS의 stale 4건(interp 가드 참조·spec result 스코프·openapi 미매핑 타입·lower 모호성)이 현재 코드 텍스트에 매치되고, 각각 주입 시 스위트가 RED(caught)가 된다. 최종 dispatch full-matrix green.

## Wiki pages (read these first, only these)
- wiki/testing/quality/harness-reverse-controls.md — use for: "verify one mutation reaches the artifact by hand" — 재고정 후 4건 각각 직접 실행 검증

## Inputs
- runner-evidence.md + run 33705681024 (stale 4건 목록)
- 현재 코드: impl/lnpl/interp.py:674-677, spec.py:171-173, openapi.py:370-371, lower.py:3450-3452
- Decisions that bind you: D11, D6

## Steps
1. impl/tests/mutation_check.py의 4개 튜플 original/mutated를 현재 코드 기준으로 교체 (의미 보존; interp 앵커는 674행 4줄 블록 — 1723행은 들여쓰기가 달라 첫-매치 안전).
2. 로컬 검증: PYTHONPATH=impl로 apply_and_run을 4건에 대해 직접 호출 → 전부 RED(caught) 단정. 전체 stale 스캔(0건) 재확인.
3. 기존 mutation 테스트 5모듈 green 확인, 커밋·push, 재-dispatch, 완주 green 관측 → runner-evidence.md 추기.

## Deliverables
- impl/tests/mutation_check.py (4개 튜플만)
- plans/i169-mutation-baseline/runner-evidence.md (최종 결과)

## Verify
- 로컬: 4건 apply_and_run 전부 RED, stale 스캔 0건, mutation 테스트 5모듈 rc 0
- 최종 dispatch: "MUTATION CHECK: PASS" + 잡 green
- covers: R3

## Out of scope
- 새 뮤테이션 추가, 앵커 드리프트 방지 자동화(후속 이슈 후보)

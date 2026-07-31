# Task 05: PerformanceAnalyzer — 측정치가 있을 때만 예산을 제안한다

## Objective
mode A 실행 측정치를 입력으로 받아 `Performance` 제약을 제안한다. **측정치가 없으면
제안하지 않는다** — 측정 없는 예산은 추측이다.

## Wiki pages (read these first, only these)
- (없음 — 결정은 A6·A9·A10에 고정)

## Inputs
- `impl/lnpl/agents.py` — `_AgentBase`
- `impl/lnpl/interp.py` — `Interpreter.run_workflow` 결과 형태(`duration_ms`, `steps`)
- 결정: A6, A9, A10

## Steps
1. `class PerformanceAnalyzer(_AgentBase)`, `role = "PerformanceAnalyzer"`.
2. `analyze(self, task, measurements, deadline_ms=30000)`:
   - `measurements`는 `run_workflow` 결과 dict의 리스트. 비어 있으면 `_refuse` —
     사유 `"no measurements"`, 인용 `"RFC-0006 §Roles (PerformanceAnalyzer: 입력 아티팩트)"`.
   - 대상 Service에 이미 `response` 예산이 있으면 제안 0으로 정상 완료(덮어쓰지 않음).
   - 예산 값: 관측된 `duration_ms`의 **최댓값을 10ms 단위로 올림**한 값에 `<`를 붙인다
     (예: 33ms → `"<40ms"`). 결정적이어야 하므로 평균·백분위가 아니라 최댓값을 쓴다
     — 표본이 적을 때 백분위는 최댓값과 같거나 덜 안전하다.
   - `Performance` 노드 + Service 교체본(constraints에 추가)을 함께 제안.
   - `_meta("ir:<workflow id>")` — 근거가 KB가 아니라 실행 측정이다.

## Deliverables
- `impl/lnpl/agents.py`
- `impl/tests/test_agents.py`

## Verify
- `PYTHONPATH=impl .venv/bin/python -m unittest tests.test_agents` → OK
- 테스트: ① 측정치 없음 → 제안 0 + 인용 있는 거부 ② 측정치 있고 예산 없음 →
  `<40ms` 형태 제안 ③ 이미 예산 있음(골든) → 제안 0 ④ 올림 규칙 경계(30ms → `<30ms`,
  31ms → `<40ms`)

## Out of scope
- SLO 집행(RFC-0003: 측정만), 다른 metric(cache/prefetch) 제안

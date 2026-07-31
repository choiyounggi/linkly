# Task 07: ReleaseAgent — 읽기 전용 릴리즈 요약

## Objective
승인된 IR과 검증 결과를 읽어 릴리즈 아티팩트 요약을 만든다. 제안은 0건 — RFC-0006
역할표가 읽기 전용으로 규정한다.

## Wiki pages (read these first, only these)
- (없음 — 결정은 A8·A9에 고정)

## Inputs
- `impl/lnpl/agents.py` — `_AgentBase`
- 결정: A8, A9

## Steps
1. `class ReleaseAgent(_AgentBase)`, `role = "ReleaseAgent"`.
2. `summarize(self, task, verification=None, deadline_ms=30000)`:
   - `ir.get`(인자 없이)으로 문서 요약을 얻는다 — 이 역할이 `ir.get`의 1차 소비자다.
   - 요약: `module`, `lir_version`, 노드 수, kind별 개수, capability 목록,
     그리고 `verification`(있으면 그대로, 없으면 `None`).
   - `verification`이 없거나 그 안에 실패가 있으면 `ready=False`, 사유를 남긴다.
     **실패를 통과로 바꾸지 않는다.**
   - `agent.report`로 `completed` + payload에 요약.
3. `ir.propose`를 호출하지 않는다(권한도 없다).

## Deliverables
- `impl/lnpl/agents.py`
- `impl/tests/test_agents.py`

## Verify
- `PYTHONPATH=impl .venv/bin/python -m unittest tests.test_agents` → OK
- 테스트: ① 요약에 kind별 개수와 capability가 있음 ② `verification` 없으면
  `ready=False` ③ 실패가 섞인 verification → `ready=False`이고 사유가 남음
  ④ `ir.propose` 호출 0건(server.log로 확인)

## Out of scope
- 실제 배포·아티팩트 생성

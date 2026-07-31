# Task 02: 역할 공통 골격 `_AgentBase`

## Objective
모든 역할이 공유하는 3요소를 한 곳에 둔다: 역할 이름, 서버 핸들, 그리고 결정 불가 시
**RFC 조항을 인용하며 거부하는 경로**.

## Wiki pages (read these first, only these)
- (없음 — 순수 리팩터, 결정은 A9에 고정)

## Inputs
- `impl/lnpl/agents.py` — 현재 Planner/Coder/Reviewer가 각자 `__init__(self, server)`
- 결정: A9(공통 골격), A10(출처 필수)

## Steps
1. `class _AgentBase:`를 추가한다.
   - `role = None` (하위 클래스가 지정)
   - `__init__(self, server)` — `self.server = server`
   - `_card()` → `self.server.call("agent.card", role=self.role)`
   - `_refuse(self, task, reason, clause)` → `agent.report`로 태스크를 `completed`로
     닫고 payload에 `{"proposed": None, "reason": reason, "clause": clause}`를 남긴다.
     `clause`는 RFC 조항 문자열(예: `"RFC-0002 Open Questions 2"`).
   - `_meta(self, source)` → `{"origin": "agent:%s" % self.role, "source": source}`
2. Planner/Coder/Reviewer가 `_AgentBase`를 상속하도록 바꾼다. **동작 변경 없음** —
   기존 테스트가 전부 그대로 통과해야 한다.
3. Coder의 `meta` 생성이 `_meta()`를 쓰도록 통일한다.

## Deliverables
- `impl/lnpl/agents.py`

## Verify
- `PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl` → OK
  (기존 테스트 전부 — 리팩터가 동작을 바꾸지 않았음을 증명)
- `PYTHONPATH=impl .venv/bin/python -m lnpl agents examples/login.lnpl` 출력 무변경

## Out of scope
- 새 역할의 결정 규칙(03~07)

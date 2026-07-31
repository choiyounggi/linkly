# Task 01: Reviewer에게 자기 기준의 반려 판단력을 준다

## Objective
`Reviewer.decide(...)`가 호출자의 지시 없이도 제안을 판정한다. A1의 5가지 사유 중
하나라도 걸리면 반려하고, 사유 코드를 `reason`에 남긴다.

## Wiki pages (read these first, only these)
- wiki/backend/common/api-design/error-responses.md — use for: 반려 사유를 분류할 때
  "구문 위반(형식)"과 "의미 규칙 위반"을 나누는 원칙(§Failure 표)

## Inputs
- `impl/lnpl/agents.py` — 현재 `Reviewer.decide`(호출자가 approve를 넘기면 그대로)
- `impl/lnpl/protocol.py` — `Server.proposals`, `ROLES`, `_apply`의 dangling 검사
- 결정: A1(5사유), A2(approve=None 기본), A10(meta.source 필수)

## Steps
1. `Reviewer._assess(proposal) -> (ok, reason)`를 추가한다. 검사 순서와 사유 코드:
   - `rights`: 제안자 역할이 제안할 수 없는 kind가 섞였는가 (`ROLES[proposal["role"]]["propose"]`)
   - `provenance`: 제안 노드 중 `meta.source`가 없는 **신규** 노드가 있는가
     (기존 노드의 교체본은 제외 — 부모 step 갱신처럼 출처가 원래 없던 노드가 있다)
   - `dangling`: 제안 적용 후 해소되지 않는 `children` 참조가 있는가
   - `orphan`: 신규 Effect/Behavior 노드가 어떤 노드의 `children`에도 안 들어가는가
   - `schema`: `server.validate`가 있으면 병합본을 통과시키는가
2. `decide(review_task_id, proposal_id, approve=None, reason="")`:
   - `approve is None` → `_assess` 결과로 판정. 반려 시 `reason`은 `"<code>: <설명>"`.
   - `approve` 명시 → 그대로 따르되 `reason` 앞에 `"override: "`를 붙인다.
3. `_assess`가 병합본을 만들 때 서버 상태를 변형하지 않는다(사본으로 계산).

## Deliverables
- `impl/lnpl/agents.py` (Reviewer 수정)
- `impl/tests/test_agents.py` (Reviewer 판단력 테스트 추가)

## Verify
- `PYTHONPATH=impl .venv/bin/python -m unittest tests.test_agents` → OK
- 반려 5사유 각각에 테스트 1건 + 정상 승인 1건 + override 1건
- `PYTHONPATH=impl .venv/bin/python -m lnpl agents examples/login.lnpl` → 여전히
  `IR nodes: 19 -> 20 | proposals applied: ['prop-0001']` (Coder 제안이 새 기준을 통과)

## Out of scope
- 새 역할 추가(02 이후), 프로토콜 메서드 변경(A11: 없음)

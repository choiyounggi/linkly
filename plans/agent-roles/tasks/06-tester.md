# Task 06: Tester — 승인된 IR에서 spec 케이스를 도출한다

## Objective
Constraint 노드에서 테스트 케이스를 기계적으로 도출한다. Tester는 **IR 노드를
제안하지 않는다** — `spec`은 IR이 아니라 테스트 아티팩트이기 때문(RFC-0002 A.4-②).

## Wiki pages (read these first, only these)
- wiki/testing/quality/minimum-case-set.md — use for: 정상·실패·경계 최소셋 구성

## Inputs
- `impl/lnpl/agents.py` — `_AgentBase`
- `impl/lnpl/spec.py` — `EXPECTATIONS`(기대 어휘 닫힌 집합), 매니페스트 형태
- 결정: A4, A5, A9

## Steps
1. `class Tester(_AgentBase)`, `role = "Tester"`.
2. `derive(self, task, workflow_id, deadline_ms=30000)`:
   - `ir.get`으로 workflow와 그 Service의 Constraint를 읽는다.
   - A5 규칙으로 케이스를 만든다. 기대 문자열은 **`spec.EXPECTATIONS`에 있는 키만**
     쓴다 — 없는 기대를 만들면 러너가 실패시킨다(그게 옳지만, 만들지 않는 게 낫다).
     - 항상: `completed`, `steps <n>`
     - `retry N` 있으면 실패 케이스: `given: empty repository` + `failed` + `attempts N+1`
     - `response` 있으면 `slo met`
     - `cache` 있으면 `cache written`
   - 반환은 `spec.py`의 매니페스트와 같은 모양(`{"spec_version","module","cases"}`).
   - Constraint가 하나도 없으면 정상 케이스만 담은 1케이스를 낸다(빈 매니페스트 금지).
3. `agent.report`로 매니페스트를 payload에 담아 `completed`.

## Deliverables
- `impl/lnpl/agents.py`
- `impl/tests/test_agents.py`

## Verify
- `PYTHONPATH=impl .venv/bin/python -m unittest tests.test_agents` → OK
- 테스트: ① 골든에서 도출한 매니페스트가 `spec.run_manifest`로 **실제 실행되어 전부
  통과** ② `retry` 있으면 실패 케이스가 포함됨 ③ 기대 어휘가 전부
  `spec.EXPECTATIONS`에 존재 ④ Tester가 `ir.propose`를 호출하지 않음

## Out of scope
- spec 블록을 `.lnpl` 소스에 써넣기(문법 생성은 별개)

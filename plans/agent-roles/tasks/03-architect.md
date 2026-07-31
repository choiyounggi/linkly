# Task 03: Architect — intent에서 Declaration 노드를 제안한다

## Objective
Architect가 선언 명세를 받아 Entity/Service/Workflow 노드를 제안한다. 명세에 없는
필드·타입은 지어내지 않고, 명명 규약은 KB에서 확인한다.

## Wiki pages (read these first, only these)
- (없음 — 결정은 A3·A9·A10에 고정)

## Inputs
- `impl/lnpl/agents.py` — `_AgentBase`(02 산출물)
- `impl/lnpl/lower.py` — `derive_id`(R2 id 규칙; 노드 id는 이 함수로만 만든다)
- KB 문서 `naming-entity-field-conventions`(이미 시드됨)
- 결정: A3, A9, A10

## Steps
1. `class Architect(_AgentBase)`, `role = "Architect"`.
2. `design(self, task, spec, deadline_ms=30000)`:
   - `spec`은 `{"entity": {"name": str, "fields": [{"name","type"}]},
      "service": {"name": str}, "workflow": {"name": str, "steps": [str]}}`.
     세 키 중 하나라도 없으면 `_refuse(...)` — 사유 `"spec incomplete"`,
     인용 `"RFC-0006 §Roles (Architect: 입력 아티팩트)"`.
   - `kb.route("entity name field name")`로 명명 문서를 찾고, 있으면 `kb.load`+
     `kb.verify`로 버전을 핀한다. 없으면 제안을 멈추고 `_refuse` — 사유
     `"no naming guidance"`, 인용 `"RFC-0005 §Consumption Interface"`.
   - 노드 id는 전부 `derive_id(name, kind)`로 만든다. 직접 문자열 조립 금지.
   - Workflow의 `children`은 step 노드 id들(`<wf id>.step.<n>`)이고, 그 step 노드도
     함께 제안한다(고아 방지 — Reviewer의 `orphan` 검사가 잡는다).
   - `ir.propose(role="Architect", ...)` 후 `agent.report`로 `input-required` 보고.
3. 모든 제안 노드에 `_meta("kb:<id>@<version>")`.

## Deliverables
- `impl/lnpl/agents.py`
- `impl/tests/test_agents.py`

## Verify
- `PYTHONPATH=impl .venv/bin/python -m unittest tests.test_agents` → OK
- 테스트: ① 완전한 spec → Entity·Service·Workflow·step 노드 제안, Reviewer 자기
  판정으로 승인됨 ② spec 누락 → 제안 0 + 인용 있는 거부 ③ 제안 id가 `derive_id`
  결과와 일치 ④ 권한 밖 kind(Effect) 제안 0건

## Out of scope
- Effect 도출(Coder 소관), Guard/Concurrency 결정

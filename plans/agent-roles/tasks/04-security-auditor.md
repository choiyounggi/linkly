# Task 04: SecurityAuditor — Password를 읽는 workflow에 보안 제약을 제안한다

## Objective
IR만 보고 판정 가능한 규칙 하나를 정확히 구현한다: `Password` 타입 필드를 가진
Entity를 읽는 workflow의 Service에 `Security` 제약이 없으면 `jwt`를 제안한다.

## Wiki pages (read these first, only these)
- (없음 — 결정은 A7·A9·A10에 고정)

## Inputs
- `impl/lnpl/agents.py` — `_AgentBase`
- KB 문서 `security-jwt-issuance`
- 결정: A7, A9, A10

## Steps
1. `class SecurityAuditor(_AgentBase)`, `role = "SecurityAuditor"`.
2. `audit(self, task, deadline_ms=30000)`:
   - `ir.get`으로 문서를 읽어 판정한다: (a) `Password` 필드를 가진 Entity가 있는가
     (b) 그 Entity를 `entity`로 참조하는 `RepositoryCall`이 있는가 (c) 그 Effect를
     소유한 step이 속한 Workflow의 Service에 `Security` 제약이 있는가.
   - (a)(b)가 참이고 (c)가 거짓일 때만 제안한다. 그 외에는 `_refuse`가 아니라
     **정상 완료 + 제안 0**으로 보고한다(위반이 없는 것은 거부 사유가 아니다).
   - 제안 노드: `Security` id는 `security.<service segments>`(기존 규칙과 동일),
     `mechanisms=["jwt"]`. 그리고 소유를 위해 **Service 노드의 교체본**을 함께 제안해
     `constraints`에 새 id를 추가한다.
   - KB `security-jwt-issuance`를 route→load→verify로 핀하고 `_meta`에 기록.
3. 이미 `Security`가 있으면 덮어쓰지 않는다.

## Deliverables
- `impl/lnpl/agents.py`
- `impl/tests/test_agents.py`

## Verify
- `PYTHONPATH=impl .venv/bin/python -m unittest tests.test_agents` → OK
- 테스트: ① Password+read+Security 없음 → 제안 1건, 승인 후 Service.constraints에
  추가됨 ② 이미 Security 있음(골든) → 제안 0 ③ Password 필드 없음 → 제안 0
  ④ 제안 노드에 `meta.source`가 `kb:security-jwt-issuance@...`

## Out of scope
- Authorization Effect 제안(Coder가 이미 함), 다른 보안 규칙

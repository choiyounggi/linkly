# agent-roles — issue #2의 즉시 가능한 부분

Goal: RFC-0006이 규정한 9역할 중 미구현 5종을 구현하고, Reviewer에게 **자기 기준의
반려 판단력**을 준다. RefactoringAgent는 `ir.propose`가 노드 제거를 표현할 수 없어
RFC-0006 개정이 선행돼야 하므로 범위 밖(이슈 #2에 남는다).

수용 기준:
1. `protocol.ROLES`의 9역할 중 8종이 `agents.py`에 구현되고(RefactoringAgent 제외),
   각 역할의 제안이 프로토콜 권한 검사를 전부 통과한다(권한 밖 kind 제안 0건).
2. Reviewer가 **호출자 지시와 무관하게** 자기 기준으로 반려한다.
3. 각 역할에 "처방/근거 없으면 아무것도 제안하지 않는다"를 증명하는 테스트가 있다.
4. 골든 예제 `examples/login.lir.json` 무변경(기계 생성물).
5. RFC 본문 무변경(Accepted 상태 — 구현만).
6. 뮤테이션 검사에 역할별 "무조건 제안" 변형이 추가되고 전부 RED.

Stack: Python 3.9+ (venv `.venv`), unittest, `PYTHONPATH=impl`. 외부 의존 없음.
Baseline: HEAD `8d3a8b9`, working tree clean(실측).

## Decisions

| # | Decision | Choice | 근거 |
|---|----------|--------|------|
| A1 | Reviewer 반려 기준 | **5가지 거부 사유를 코드로 고정**: ① 스키마 위반(validator 있을 때) ② dangling 참조 ③ 제안자 권한 밖 kind ④ `meta.source` 출처 누락 ⑤ 기존 노드를 **소유자 없이** 추가(고아). 각 사유는 반려 `reason`에 사유 코드로 남는다 | 이슈 #2 본문("대부분 apply 시점에 이미 raise — 그걸 리뷰 시점으로 옮기는 게 요점"); wiki `backend-common-api-design-error-responses` §Failure 표 — 무엇이 400(구문)이고 무엇이 422(의미 규칙 위반)인지 구분하는 원칙을 반려 사유 분류에 적용 |
| A2 | Reviewer API | `decide(review_task_id, proposal_id, approve=None, reason="")`. **`approve=None`(기본)이면 자기 기준으로 판정**하고, `True`/`False`는 명시적 override로 남기되 override 사실을 reason에 기록 | 기존 호출자(`run_cycle`)를 깨지 않으면서 기본 동작을 판단으로 바꾼다. 기본값을 True로 두면 도장 문제가 그대로 남는다 |
| A3 | Architect 입력·출력 | 입력 = intent 문자열 + 선언 명세(dict). 출력 = Declaration 노드 제안(Entity/Service/Workflow). **KB 라우팅으로 명명 규약을 확인**하고, 명세에 없는 필드/타입을 지어내지 않는다 | RFC-0006 역할표(Architect: 입력=Planner 태스크, 출력=IR 노드 제안); KB `naming-entity-field-conventions`가 이미 시드돼 있다 |
| A4 | Tester 입력·출력 | 입력 = 승인된 IR. 출력 = **제안이 아니라 spec 매니페스트 케이스**. Tester의 propose 권한(Behavior)은 쓰지 않는다 — `spec`은 IR 노드가 아니기 때문(RFC-0002 A.4-②) | A.4-②가 이미 확정한 사실. 여기서 Behavior 노드를 제안하면 그 결정을 뒤집는 셈 |
| A5 | Tester 케이스 도출 규칙 | Constraint 노드에서 **기계적으로** 도출: `retry N` → `attempts N+1` 기대, `timeout` → 데드라인 케이스, `response` → `slo met`, `cache` → `cache written`. 정상 케이스 1건은 항상 포함 | wiki `testing-quality-minimum-case-set` — 정상 1 + 실패 1 + 경계 1. 선언이 실패 경로를 이미 말해주므로 도출이 결정적이다 |
| A6 | PerformanceAnalyzer | 입력 = 실행 측정치(mode A 결과) + IR. 출력 = Performance 제약 제안. **측정치가 없으면 제안하지 않는다**. 이미 `response` 예산이 있으면 제안하지 않는다(기존 선언을 덮어쓰지 않음) | RFC-0006 역할표; 측정 없는 예산 제안은 추측이다 |
| A7 | SecurityAuditor | 입력 = IR. 출력 = Security/Authorization 제안. 규칙: **`Password` 타입 필드를 가진 Entity를 읽는 workflow에 `Security` 제약이 없으면** `jwt` 제약을 제안한다. 그 외에는 제안하지 않는다 | KB `security-jwt-issuance`가 시드돼 있고 규칙이 IR에서 판정 가능하다 |
| A8 | ReleaseAgent | 입력 = 승인된 IR + 검증 결과. 출력 = **릴리즈 아티팩트 요약**(제안 0 — 읽기 전용 역할). `ir.get`을 1차 소비자로 사용 | RFC-0006 역할표(ReleaseAgent: 제안 없음, 읽기 전용) |
| A9 | 공통 골격 | 모든 역할은 `_AgentBase`를 상속: `role` 클래스 속성, `server`, 그리고 `_refuse(reason, clause)` — 결정 불가 시 RFC 조항을 인용해 태스크를 `completed`로 닫고 `proposed=None`을 보고한다 | 이슈 #2가 요구한 3요소(입력 계약·"없으면 제안 안 함"·인용 있는 거부 경로)를 한 곳에 둔다 |
| A10 | 제안 시 출처 필수 | 모든 역할의 제안 노드는 `meta.origin = "agent:<Role>"`, 근거가 KB면 `meta.source = "kb:<id>@<version>"`, IR 파생이면 `meta.source = "ir:<node id>"` | Coder가 이미 하는 것을 규칙으로 승격. A1-④가 이것을 반려 사유로 검사하므로 둘이 맞물린다 |
| A11 | 프로토콜 변경 | **없음.** 8종 전부 기존 8메서드로 표현된다. RefactoringAgent만 새 표현이 필요하고 그건 범위 밖 | 수용 기준 5(RFC 무변경)와 정합 |
| A12 | 골든 무변경 보장 | 새 역할은 `run_cycle`에 자동 편입하지 않는다 — `run_cycle`은 Planner→Coder→Reviewer 그대로 두고, 새 역할은 개별 호출·테스트로 검증 | 골든 IR과 `lnpl agents` 출력이 회귀 없이 유지돼야 한다(수용 기준 4) |

## Task order

| Task | Depends on | Parallel-ok |
|------|-----------|-------------|
| 01-reviewer-judgment | — | — |
| 02-agent-base | 01 | — |
| 03-architect | 02 | 04·05와 parallel-ok |
| 04-security-auditor | 02 | 03·05와 parallel-ok |
| 05-performance-analyzer | 02 | 03·04와 parallel-ok |
| 06-tester | 02 | — |
| 07-release-agent | 02 | — |
| 08-mutations-and-docs | 03,04,05,06,07 | — |

01이 먼저인 이유: Reviewer 판단력이 생기면 이후 모든 역할의 제안이 그 기준을 통과해야
하므로, 나중에 붙이면 앞선 역할들을 다시 고치게 된다.

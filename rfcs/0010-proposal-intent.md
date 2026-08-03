# RFC-0010: Proposal Intent

## Status

- Status: **Accepted** (RFC-0010, 2026-08-03)
- Updates: RFC-0006 §Agent Roles & IR Access, RFC-0006 §Methods/ir.propose

## Motivation

RFC-0006의 권한표는 역할별로 제안할 수 있는 노드 **kind**를 정한다. 그런데 노드는
**다른 범주의 노드가 자신을 참조해야** 효력이 생기고, 그 참조 편집은 저작 역할이 갖지
못한 범주에 있다. 세 역할이 같은 구멍에 걸린다:

| 역할 | 저작 가능 | 부착에 필요한 kind | 현행 |
|------|----------|------------------|------|
| RefactoringAgent | `WorkflowStep` | `Workflow` (Declaration) | 거절 |
| SecurityAuditor | `Security` | `Service` (Declaration) | 거절 |
| PerformanceAnalyzer | `Performance` | `Service` (Declaration) | 거절 |

실측하면 `role RefactoringAgent may not propose Workflow nodes`로 막힌다. 즉 세 역할
모두 **자기가 저작할 수 있는 노드를 문서에 효력 있게 넣을 수 없다.**

두 번째로, 참조가 **이동**하면 현행 참조 구현은 그것을 제거로 읽고 거절한다 —
`removal: replacing wf.w.step.1 would drop reference(s) wf.w.step.1.b`. 그런데
**RFC-0006은 제거를 금지한 적이 없다.** 그 거절은 참조 구현의 보수적 판단이며, 오류
메시지가 `(RFC-0006 §Methods)`를 인용하지만 그 절에 해당 규정이 없다. 이 RFC가 그
의미론을 처음으로 규정한다.

두 결함이 겹친 결과 RefactoringAgent의 **유일한** 근거 있는 작업(KB 문서
`patterns-repository-call`의 "한 step에 한 저장소 접근")이 실행 불가였고, 그래서 9종
에이전트 중 하나가 미구현으로 남아 있었다.

## Guide-level Explanation

지금까지 제안은 **노드의 목록**이었다. 리뷰어는 그 목록을 문서와 비교해, 참조가
사라졌으면 제거로 보고 거절했다. 표면 비교라 "옮겼다"와 "지웠다"를 구별할 수 없었다.

이 RFC는 제안에 **의도**를 싣는다. 제안이 "이 노드를 저 부모에 붙인다"(`attach`)와
"이 참조를 여기서 저기로 옮긴다"(`move`)를 **선언**하고, 리뷰어는 표면 diff 대신
**병합 결과의 불변식**을 검사한다 — 고아가 없는가, 소유자가 하나인가, 순환이 없는가.

예를 들어 저장소 접근이 둘인 step을 쪼갤 때 제안은 이렇게 말한다:

```json
{
  "nodes": [ "…부모(참조만 추가)…", "…원본 step(접근 하나만 남김)…", "…신설 step…" ],
  "intent": {
    "attach": [{ "parent": "wf.w", "child": "wf.w.split.1" }],
    "move":   [{ "node": "wf.w.step.1.b", "from": "wf.w.step.1", "to": "wf.w.split.1" }]
  }
}
```

**권한표의 뜻은 바뀌지 않는다.** 표는 여전히 "이 역할이 무엇을 **저작**할 수 있는가"를
답한다. 부착은 저작이 아니므로 별도 축으로 다루고, 그래서 제안 범위 밖 노드에 대해
**참조 추가만** 허용한다 — 그 외 어떤 변경도 허용하지 않는다.

## Reference-level Specification

### RFC-0006 §Agent Roles & IR Access (치환 후 최종 텍스트)

역할은 Charter §AI Pipeline의 9종으로 **고정**한다. 행 순서는 파이프라인 순서와
같다. Charter 산문의 공백 표기(`Performance Analyzer` 등)는 프로토콜 식별자로
쓸 때 PascalCase 단일 토큰(`PerformanceAnalyzer`)으로 정규화한다 — RFC-0001이
D15의 "Workflow Step"을 `WorkflowStep`으로 정규화한 것과 같은 규칙이다
(`rfcs/0001-semantic-ir.md` 88~90행).

IR 대분류는 RFC-0001의 4종(Declaration / Behavior / Effect / Constraint —
`rfcs/0001-semantic-ir.md` 44~47행)을 그대로 쓰며 새 분류를 만들지 않는다.

| Agent | 입력 아티팩트 | 출력 아티팩트 | IR 읽기 | IR 제안(`ir.propose`) | 승인 권한 |
|-------|--------------|--------------|---------|----------------------|-----------|
| Planner | 자연어 요구(intent) | 태스크 분해 목록(`agent.dispatch` 대상) | 전체 | 없음 | 없음 |
| Architect | Planner 태스크 | IR 노드 제안(`ir_fragment`) | 전체 | Declaration, Behavior | 없음 |
| Coder | 승인된 IR 조각 + KB 문서 | `.lnpl` 소스 + Effect 노드 제안 | 전체 | Behavior, Effect | 없음 |
| Reviewer | IR 제안 + 산출물 | 승인/반려 판정 | 전체 | 없음 | **보유** |
| Tester | 승인된 IR + 코드 | spec/테스트 산출물 | 전체 | Behavior | 없음 |
| PerformanceAnalyzer | 실행 측정치 + IR | 성능 리포트 + 성능 예산 제안 | 전체 | Constraint | 없음 |
| SecurityAuditor | IR + 코드 | 보안 감사 리포트 + 인가 지점 제안 | 전체 | Constraint, Effect | 없음 |
| RefactoringAgent | 승인된 IR + 코드 | 리팩터 제안 | 전체 | Behavior, Effect | 없음 |
| ReleaseAgent | 승인된 IR + 테스트 결과 | 릴리즈 아티팩트 | 전체 | 없음 | 없음 |

**읽기가 9역할 전부 `전체`인 것은 누락이 아니라 결정이다.** Charter가 "모든
Agent는 Semantic IR를 공유한다"(`CHARTER.md` 184행)고 요구하므로 읽기를 역할별로
좁히지 않는다 — 읽기를 좁히면 에이전트가 자기 시야 밖의 제약(Policy·Security·
Performance)을 모른 채 산출물을 만들게 되고, 이는 Charter가 IR 공유로 막으려던
바로 그 발산이다.

**차별화는 제안 범위와 승인 권한에서만 일어난다.** 각 역할의 제안 범위는 그 역할이
Charter에서 만들어내는 산출물의 성격에서 유도했다: Architect는 무엇이 존재하고
어떻게 흐르는지를 설계하므로 Declaration·Behavior, Coder는 흐름을 구현하며 부수효과를
도입하므로 Behavior·Effect, Tester는 검증 규칙을 추가하므로 Behavior, PerformanceAnalyzer와
SecurityAuditor는 제약을 추가하므로 Constraint(SecurityAuditor는 인가 지점을 심으므로
Effect도 포함), RefactoringAgent는 의미를 보존하며 구조를 바꾸므로 Behavior·Effect다.
Planner는 IR을 만들지 않고 작업을 나누며, ReleaseAgent는 승인된 IR을 소비할 뿐이므로
둘 다 제안 권한이 없다. Reviewer는 제안하지 않고 판정한다 — 제안자와 승인자를
겸하면 `### Proposal & Approval`의 2단계가 무의미해진다.

`agent.card`의 응답은 이 표의 한 행과 1:1로 대응해야 한다(`### Methods`).

**부착(attachment)은 저작과 다른 축이다.** 제안 범위는 역할이 **저작**할 수 있는 kind를
정한다. 자기가 저작한 노드를 그것을 소유할 노드에 **부착**하는 것은 저작이 아니므로,
제안이 의도를 명시하고 아래 §Methods/ir.propose의 조건을 모두 만족하는 한 제안 범위
**밖** 노드의 **참조 추가만** 허용한다. 이 예외는 권한표를 넓히지 않는다 — 표는 여전히
"무엇을 저작하는가"를 답하며, 부착으로 들어갈 수 있는 노드도 결국 그 역할이 저작할 수
있는 kind로 한정된다.

### RFC-0006 §Methods/ir.propose (치환 후 최종 텍스트)

#### `ir.propose`

IR 변경 제안. **IR을 즉시 변경하지 않는다.**

- params: `{ module, ir_fragment, intent, rationale, kb_pins, _meta }` — `kb_pins`는 이 제안의
  근거로 사용한 KB 문서 핀 목록(`[{ doc_id, version }]`)이며 **필수**다(사용하지
  않았다면 `[]`). 검증 규정은 `### Errors` ④
- result: `{ proposal_id, state: "pending", review_task_id }`
- 부작용이 있으므로 `_meta.idempotency_key` 필수. 상세는
  `### IR Fragment Embedding`과 `### Proposal & Approval`.

#### `intent`

`intent`는 제안이 수행하는 **구조적 의도**를 선언한다. 형식:

```
{ "attach": [{ "parent": <노드 id>, "child": <노드 id> }],
  "move":   [{ "node": <노드 id>, "from": <노드 id>, "to": <노드 id> }] }
```

두 키 모두 선택이다. **`intent` 부재는 이 RFC 이전과 동일한 의미다** — 기존 제안은 한
글자도 바뀌지 않으며, 그것이 이 개정의 하위 호환 조건이다.

**`attach` 유효 조건.** 다음을 모두 만족해야 하며, 하나라도 어기면 `ir_invalid`다.

1. `child`는 **이 제안에서 저작된 노드**다 — 조각에 있고 문서에 없다. 이것이 역할이
   자기가 쓰지 않은 노드를 재부모화하는 것을 막는다.
2. `parent`의 kind가 `child`의 kind를 `children`으로 가질 수 있다 — RFC-0001
   §노드 카탈로그의 *children 허용* 열이며 RFC-0004 §S2의 불변식 **V5**다.
3. `parent`는 제안 범위 밖일 수 있으나, 그 편집이 다음을 **모두** 만족할 때만이다:
   - ⓐ 문서에 이미 존재하는 노드의 교체이고,
   - ⓑ `kind`가 기존 노드와 같고,
   - ⓒ **참조 필드가 아닌** 모든 필드가 기존 노드와 같고,
   - ⓓ **참조 필드 각각에 대해**, 기존 노드의 그 필드 값과 **완전히 동일**하다 — 값과
     **순서** 모두. 단 `children`에서만 선언된 추가분을 제거한 뒤 비교한다. 즉
     **부착은 `children`에만 쓸 수 있다** — 같은 id를 `constraints`나 `requires`에도
     넣을 수 있게 하면 "자기가 저작한 것을 부착한다"가 "소유하지 않은 kind의 노드의
     아무 참조 필드에나 id를 쓴다"로 넓어진다,
   - ⓔ `meta.origin`이 `agent:<role>` 형식이다.

**ⓓ가 집합 비교가 아니라 필드별·순서보존인 이유.** 집합으로 비교하면 두 가지가 통과한다.
① `children` 순서 뒤집기 — 그런데 `children` 순서가 **실행 순서**다(RFC-0001 구조 규칙
3). ② 참조를 `constraints`에서 `children`으로 옮기기 — 집합은 그대로지만 런타임은
`constraints`에서 retry·timeout·rollback을 읽으므로 **선언한 정책이 조용히 사라진다.**
두 경우 모두 이 설계의 초안에 대해 실증됐다. ⓔ가 필요한 이유는, 병합 후 문서에 "어떤
역할이 자기 범위 밖으로 손을 뻗었다"는 기록이 남지 않으면 이 조건들의 회귀를 사후에
발견할 수 없기 때문이다.

**`move` 유효 조건.** 떨어진 참조는 다음을 만족하는 `move` 항목이 있을 때만 정당하다.

1. `node`가 그 참조이고 `from`이 그것을 떨어뜨린 노드다.
2. 병합 후 `to`가 그것을 **떠난 것과 같은 필드에서** 참조한다. "어딘가에서 참조하면
   된다"로는 부족하다 — 그 느슨한 판정은 Constraint 제거를 `children` 삽입으로 세탁할
   수 있고, 그것이 실증됐다.
3. `to`가 그것을 **새로** 얻는다. 이미 그 필드에서 참조하고 있던 노드를 `to`로 적으면
   2를 만족하면서 아무것도 이전되지 않는다 — 즉 순수 제거가 move로 세탁된다. 실증:
   두 Service가 같은 Policy를 제약으로 걸고 있을 때 한쪽에서 떼고 다른 쪽을 `to`로
   선언하니 승인됐고 retry가 2에서 1로 떨어졌다.
4. **소실 판정은 필드별이다.** `children`과 명명 참조 필드를 합집합으로 비교하면 참조가
   필드 *사이를* 옮겨갈 때 아무 변화가 없어 보인다 — 그리고 런타임은 `constraints`에서
   retry·timeout·rollback을 읽으므로 Policy를 `children`으로 옮기면 정책이 조용히
   사라진다. 이 판정은 `intent` 유무와 무관하게 적용된다.
5. Constraint 노드(`Policy`·`Security`·`Performance`)는 `constraints`에만 놓일 수 있다
   — RFC-0001 구조 규칙 5가 Constraint를 `children`으로 소유하는 것을 금지한다. **이
   조항은 2·4의 결과로 자동 충족된다**: 판정 기준이 되는 필드는 참조가 *떠난* 곳이고,
   유효한 문서는 Constraint를 `constraints`에만 두므로 2가 곧 3을 함의한다. 참조
   구현은 이를 별도 분기로 두지 않는다 — 어떤 뮤테이션도 그 분기를 죽일 수 없었고,
   그것이 도달 불가 조건의 표식이다.

선언되지 않은 참조 소실은 여전히 거절한다. `intent`가 선언한 것과 조각이 실제로 하는
일이 어긋나면 `ir_invalid`다.

**불변식은 병합 결과에서 판정한다** — dangling 금지(RFC-0001 규칙 6), 소유 유일(규칙 2),
고아 금지(규칙 2·5), 비순환(규칙 4). 이는 §IR Fragment Embedding이 이미 규정한 판정
시점이며 이 RFC가 바꾸지 않는다. **단 V5(kind별 children 허용)는 참조 구현에 없다** —
이 RFC는 `attach`에 대해서만 그것을 요구하고, 문서 전역 V5 집행은 미구현으로 남는다
(`docs/CONSISTENCY-CHECK.md`에 기록).

**집행 시점.** 위 조건은 `ir.propose`(제안 시점)와 리뷰 판정에서 검사된다. 승인
override(`decide(approve=True)`)와 손으로 만든 `agent.report`는 병합 단계에 직접
도달하며 그쪽은 dangling만 본다 — override는 구성상 신뢰되고 이 기제가 막아주지 않는다.

## Examples

골든 시나리오 "Login"(정본: `plans/rfc-suite/plan.md` §골든 시나리오 — RFC-0007 §6에
따라 참조만 하고 재정의하지 않는다)에는 **이 기제가 할 일이 없다.** `wf.login`의 여섯
step 중 저장소 접근을 둘 이상 소유한 step이 없기 때문이다(`wf.login.step.2`가
`RepositoryCall` 하나, `wf.login.step.3`이 `CacheAccess` 하나). 따라서 아래는 RFC-0007
§6이 허용하는 **골든 인접 예제**다.

**주의: 이 예제는 `.lnpl`이 아니라 IR로 제시한다.** `.lnpl` 프런트엔드는 step당
`RepositoryCall`을 하나만 만들며(실측), 두 접근 step을 표현할 문법이 없다. IR은 허브이고
에이전트는 `ir.propose`로 IR을 주고받으므로 이 입력은 도달 가능하다 — §6의 표현이
`.lnpl` 파일을 전제하지만 이 경우엔 IR이 정확한 표면이다.

한 step이 저장소 접근을 둘 소유한 상태:

```json
{"kind": "WorkflowStep", "id": "wf.w.step.1", "name": "load and audit",
  "children": ["wf.w.step.1.a", "wf.w.step.1.b"]}
```

`patterns-repository-call`은 "한 step에 한 저장소 접근. 두 접근이 필요하면 두 step이다"를
처방한다. 제안은 세 노드와 의도로 구성된다:

| 노드 | 무엇 | 어느 조건이 지킨다 |
|------|------|------------------|
| `wf.w` (부모) | `children`에 `wf.w.split.1`을 **원본 직후** 삽입. 그 외 무변경 | ⓐ~ⓔ. 특히 ⓓ가 순서 뒤집기를, ⓒ가 다른 필드 변경을 막는다 |
| `wf.w.step.1` (교체) | `children`에서 `…b`를 뺀다 | `move` 1·2가 그 소실을 정당화한다 |
| `wf.w.split.1` (신설) | `…b`를 소유. `meta.source` = `kb:patterns-repository-call@0.1.0` | `attach` 1(이 제안에서 저작), 2(Workflow가 WorkflowStep을 소유할 수 있다) |

```json
{"attach": [{"parent": "wf.w", "child": "wf.w.split.1"}],
  "move":   [{"node": "wf.w.step.1.b", "from": "wf.w.step.1", "to": "wf.w.split.1"}]}
```

**이 변환이 보존하는 것과 보존하지 않는 것.** RFC-0006 권한표의 도출 산문은
RefactoringAgent를 "의미를 보존하며 구조를 바꾸므로"로 설명한다. 정확히는 **effect의
순서는 보존되고, 재시도 그룹은 보존되지 않는다.** `patterns-repository-call`이 한 접근
per step을 요구하는 *이유* 자체가 "step은 재시도·span의 단위이므로 접근을 묶으면 재시도가
둘을 함께 반복한다"이므로, 쪼개면 재시도 단위가 달라지는 것이 **처방의 목적**이다.
실측: `retry 2`와 실패하는 저장소에서 옮겨진 effect의 실행 횟수가 3회에서 1회로 바뀐다.
이것을 "동작 보존"이라 부르면 틀린다.

**부수적으로 낡는 산출물.** `Tester.derive`가 step 수에서 `"steps N"` 케이스를 만들므로,
분리 이전에 파생된 spec 매니페스트는 분리 후 낡는다. 재파생이 필요하다.

## Alternatives

| # | 검토한 대안 | 기각 사유 |
|---|------------|----------|
| 1 | **필드 단위 권한** — RefactoringAgent에 `Workflow.children`, SecurityAuditor·PerformanceAnalyzer에 `Service.constraints`를 직접 부여 | RFC-0006은 권한을 역할의 **산출물**에서 도출한다("각 역할의 제안 범위는 그 역할이 Charter에서 만들어내는 산출물의 성격에서 유도했다"). 필드 증여는 산출물이 아니므로 그 도출 근거를 흐린다. 새 부착 지점이 생길 때마다 RFC 개정이 필요해지고, 제거 문제는 여전히 별도로 남는다 |
| 2 | **별도 `ir.attach`/`ir.detach` 메서드** | 메서드 셋이 **8종으로 고정**돼 있고(RFC-0006이 본문 4곳에서 인용하며 `-32601`을 "8종 밖의 메서드"로 정의한다), 9번째 메서드 추가는 그 자체로 RFC-0006 §Open Questions 4의 미결 사항이다. 또 그래프를 바꾸는 메서드가 둘로 나뉘면 리뷰 게이트를 양쪽에 동일하게 걸어야 하고(누락이 곧 구멍), 한 문장의 수정이 여러 호출로 쪼개져 원자성 경계가 흐려진다 |
| 3 | 제거를 금지한 채 두고 RefactoringAgent를 포기 | 9종 파이프라인은 CHARTER §AI Pipeline이 고정한 것이고, 이 역할의 유일한 근거 있는 작업이 KB에 실재한다. 포기는 계약을 줄이는 것이지 지키는 것이 아니다 |

## Open Questions

1. **다른 두 역할의 배선.** 이 기제는 SecurityAuditor·PerformanceAnalyzer의 부착 구멍도
   동일하게 해소하지만, 두 역할이 실제로 `intent`를 쓰도록 바꾸는 것은 별도 작업이다.
   현재 두 역할은 `attachment_required`를 보고한다.
2. **`attach` 봉쇄 규칙의 완화 여부.** 조건 1(자기가 저작한 노드만 부착)은 재부모화를
   막지만, 정당한 재부모화가 필요한 리팩터가 나오면 재검토 대상이다. 지금은 그런 사례가
   없다.
3. **문서 전역 V5 집행.** 이 RFC는 `attach` 시점에만 kind 호환성을 요구한다. RFC-0004
   §S2가 문서 불변식으로 규정한 V5(그리고 V1)를 검증 패스에 넣는 것은 더 큰 변경이며
   별도 이슈다.

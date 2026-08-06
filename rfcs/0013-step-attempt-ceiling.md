# RFC-0013: Step Attempt Ceiling

## Status

- Status: **Accepted** (RFC-0013, 2026-08-06)
- Updates: RFC-0003 §Policy Enforcement

## Motivation

RFC-0003 §Policy Enforcement은 재시도의 상한을 `Policy.retry N`과
`Policy.timeout T`의 잔여 데드라인, 둘로 규정했다. 그런데 이 둘은 **동시에
사라질 수 있다** — `timeout`은 선택 항목이므로 선언하지 않은 service에는 데드라인이
아예 없고, 그러면 남는 상한은 `retry` 하나뿐이다. 상한이 하나뿐인 재시도 루프는
그 하나가 어떤 이유로든 적용되지 않게 되는 순간 **실패가 아니라 무한 루프**가 된다.
이것은 `kb/antipatterns/antipatterns-unbounded-retry.md`가 이름으로 기록해 둔
안티패턴이며, 무한 루프는 실패보다 나쁘다 — 실패는 관측되고 보고되지만 무한 루프는
호출자의 예산을 조용히 태운다.

이 결함은 추론이 아니라 **뮤테이션 하네스가 실측으로 드러냈다.**
`impl/tests/mutation_check.py`의 `RFC-0003: drop the retry attempt cap`은 참조
인터프리터에서 `attempts > con["retry"]` 한 줄을 지운다. 상한이 둘이라면 남은
하나가 잡아내 스위트가 RED가 되어야 한다. 실제 결과는 RED가 아니라 **HANG**이었다
— 77개 뮤테이션 중 유일하게 깨끗하게 잡히지 않는 건이었고, 스위트가 반환하지
않으므로 **테스트를 더 써서 닫을 수 없는** 종류의 구멍이었다. 관찰하려는 테스트
자신이 돌아오지 않기 때문이다. 닫으려면 런타임에 경계가 하나 더 있어야 한다.

`Policy.retry`의 의미는 바뀌지 않는다. 이 RFC는 선언된 예산 **아래에** 그것이
지워져도 남는 바닥을 하나 깐다.

## Guide-level Explanation

`.lnpl`을 쓰는 쪽에서 이 RFC 때문에 달라지는 것은 없다. `retry 3`은 여전히 초기
시도 1회 + 재시도 최대 3회, 총 4회를 뜻한다. 상한은 정책이 아니라 백스톱이므로
유효한 설정에서는 관측되지 않는다.

달라지는 경우는 하나뿐이다: `retry`를 **100 이상**으로 선언하면 선언한 만큼
재시도되지 않고 총 100회에서 멈춘다. 런타임은 이를 진단하지 않는다. 이는 지원되는
모드가 아니라 설정 오류이며, 그 영역에서의 동작을 명시해 두는 것이 이 절의 목적이다
(진단을 붙일 것인가는 §Open Questions ①).

100이라는 값은 실사용 예산과 겹치지 않게 골랐다. 이 레포 전체에서 가장 큰 `retry`
선언은 5이고, 실제 재시도 예산은 2~3회를 쓴다. 상한이 낮으면 정상 설정을 잘라내고,
없으면 무한 루프를 허용한다. 100은 양쪽 모두에서 멀되 **유한하다** — 유한하다는
것이 전부다.

## Reference-level Specification

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0003 §Policy Enforcement의 **치환 후 최종
텍스트 전문**이다. 이 절이 RFC-0003의 같은 이름 절을 대체한다.

---

### Policy Enforcement

Constraint 노드(RFC-0001: Policy·Security·Performance)의 런타임 의미.
Security의 `mechanisms`는 컴파일러가 구현을 선택하는 입력이며(CHARTER §핵심
철학 2), 런타임 계약으로는 Authorization 게이트(위 표)와 §Observability의
마스킹 의무가 해당한다. Policy·Performance의 집행 계약은 다음 표와 같다.

| 항목 | 런타임 의미(계약) |
|------|------------------|
| `Policy.retry N` | 실패한 **step**의 재실행. 최대 N회 재시도(초기 시도는 별도 — `retry 3` = 실패 후 최대 3회 더 시도). 대기는 capped exponential backoff + full jitter. 재시도는 2중 게이트를 모두 통과할 때만: ① step이 소유한 Effect 전부가 아래 멱등 판정 표에서 멱등 ② 실패 유형이 아래 실패 유형 표에서 재시도 가능. 모든 재시도는 `Policy.timeout`의 잔여 데드라인 안에서만 수행한다 |
| `Policy.rollback` | 실패 시 보상의 경계는 **Transaction 노드**다. 진행 중이던 Transaction은 원자적으로 abort되고(부분 쓰기 없음), 이미 커밋된 선행 step의 Transaction들은 역순으로 보상을 실행한다. Transaction 밖의 Effect(예: 외부 NetworkCall)는 자동 보상이 불가하다 — rollback이 보장하는 범위는 Transaction 경계까지이며, 그 밖의 보상은 계약하지 않는다(한계는 §Open Questions ③과 연결) |
| `Policy.timeout T` | workflow 실행 전체의 데드라인. 실행 시작 시각에 기산하고, 모든 하위 Effect 호출에 **잔여 데드라인을 전파**한다(호출받은 쪽은 잔여 시간을 자신의 타임아웃 상한으로 삼는다). 초과 시: in-flight Effect에 취소를 전파하고(아무도 읽지 않을 일을 계속하지 않는다), actor 메일박스의 해당 실행 작업을 폐기하며, workflow는 `TimedOut` 실패로 종결한다 |
| `Performance.cache T` | 해당 workflow의 CacheAccess `set`에 적용되는 TTL 예산. TTL의 소유권은 Performance 제약에 있다(RFC-0001 CacheAccess 행 — 중복 지정 금지). 런타임 계약: TTL 없는 `set`은 금지된다 — 모든 key는 TTL을 가진다(무효화가 유실돼도 TTL이 백스톱) |
| `Performance.response X` | **SLO 선언이다 — 집행 대상이 아니다.** 런타임은 초과 요청을 차단하지 않는다(유효한 요청을 자기 손으로 실패시키는 것은 SLO 개선이 아니다). 대신 계측·경보한다: step/workflow duration histogram의 **p50/p95/p99**를 SLO와 비교하고 위반 시 경보를 발화한다. 평균 단독 비교는 금지 — 평균은 사용자가 실제로 겪는 꼬리 지연을 가린다 |

**retry 시도 상한.** `retry N`이 선언한 예산과 **무관한 절대 상한**이 하나 더
있다: 한 step의 총 시도 횟수(초기 시도 포함)는 **100회**를 넘지 않는다. 이 상한은
`retry` 값을 읽지 않고 판정하며, `retry`보다 **먼저** 평가된다. 따라서 관측 가능한
시도 횟수는 `min(retry + 1, 100)`이다.

상한이 하나뿐인 재시도 루프는 그 하나를 잃는 순간 실패가 아니라 **무한 루프**가
된다(`kb/antipatterns/antipatterns-unbounded-retry.md`). 위 `Policy.timeout`의
데드라인은 이 자리를 대신하지 못한다 — `timeout`을 선언하지 않은 service에는
데드라인이 없고, 그러면 남는 상한이 `retry` 하나뿐이기 때문이다.

`retry`를 100 이상으로 선언하는 것은 지원되는 모드가 아니라 **설정 오류다.**
선언한 만큼 재시도되지 않으며, 런타임은 이를 진단하지 않고 100에서 멈춘다.
유효한 설정은 이 상한에 닿지 않는다 — 이 레포 전체에서 가장 큰 `retry` 선언은
5이고, 실제 재시도 예산은 2~3회를 쓴다. 상한은 정책이 아니라 백스톱이다.

상한은 **두 실행 모드 모두**에 있다(RFC-0004 §실행 모드와 semantic equivalence의
관측 대상 2 "정책 집행 결과 — retry 판정"). 어느 한쪽에만 두면 `retry >= 100`에서
두 모드의 시도 횟수가 갈리고 `lnpl diff`가 `DIVERGENT`를 보고한다.

**retry 멱등 판정 기준.** 어떤 Effect가 멱등인가의 정의: *동일 Effect를 2회
실행한 최종 상태와 외부에서 관측 가능한 부수효과가 1회 실행과 같으면 멱등이다.*
타임아웃된 요청은 실제로는 실행되었을 수 있으므로, 이 기준을 통과하지 못하는
Effect의 재전송은 부수효과를 복제한다. kind×operation 판정 표:

| Effect kind | operation | 멱등 판정 |
|-------------|-----------|----------|
| RepositoryCall | `read`, `query` | 멱등 — 상태를 바꾸지 않는다 |
| RepositoryCall | `delete` | 멱등 — 이미 삭제된 대상의 재삭제는 부수효과가 없다 |
| RepositoryCall | `update` | 절대값 쓰기(full replace)만 멱등. 상대 연산(증분·누적)은 비멱등 |
| RepositoryCall | `create` | 비멱등 — 멱등키가 선언된 경우에만 재시도 가능(키 저장·응답 재생 계약은 RFC-0006의 멱등키 규정과 정렬) |
| CacheAccess | `get`, `set`, `invalidate` | 멱등 — get은 무부수효과, set은 절대 상태 쓰기(last-write-wins), invalidate는 삭제 |
| NetworkCall | (operation별) | operation이 멱등으로 선언되었거나 멱등키를 전파하는 경우에만 멱등 취급. 선언 없는 NetworkCall은 비멱등으로 간주한다 |
| Authorization | — | 검사 자체는 멱등(무부수효과). 단 거부는 재시도 대상이 아니다(위 표) |
| EventEmit | — | event id 기반 dedupe가 가능한 조건에서만 멱등 취급(at-least-once 전제) |
| Transaction | — | children 전부가 멱등일 때만 스코프 단위 재시도 가능 |

**실패 유형별 재시도 판정.** 멱등 게이트를 통과했더라도 실패 유형이 재시도를
허용해야 한다:

| 실패 유형 | 판정 |
|-----------|------|
| 도달 전 실패(connection refused, connect timeout) | 재시도 — 요청이 핸들러에 도달하지 않았다 |
| 전송 후 무응답(request timeout) | 멱등 게이트 통과 시에만 재시도 — 요청은 실행되었을 수 있다 |
| 일시 오류 응답(5xx류, 과부하 신호) | 재시도 예산 내에서 재시도, 반복 실패 시 실패 확정 |
| 요청 자체의 오류(4xx류, Authorization 거부, Validation 실패) | 재시도 금지 — 같은 요청은 다시 보내도 같은 결과다 |

---

**참조 구현.** 상한은 `impl/lnpl/interp.py`의 `MAX_STEP_ATTEMPTS`(모드 A)와
`impl/lnpl/backend.py`의 `_MAX_STEP_ATTEMPTS`(모드 B)에 있다. 모드 B는 모드 A를
import하지 않고 미러링한다 — 독립 도출이어야 차분 검사가 의미를 갖기 때문이며,
그 미러의 표류를 막는 것은 `test_backend.TestModeBDerivesRetryAttempts`다.

## Examples

골든 시나리오 "Login"(정본: `plans/rfc-suite/plan.md` §골든 시나리오 "Login").
RFC-0003 §Examples의 타임라인 C — `policy.login`이 `retry 3`과 `timeout 3s`를
선언하고 step 2의 postgres가 계속 불가용한 경우 — 는 이 개정으로 **바뀌지 않는다**:

```
└── step.2  authenticate
    ├── 시도 1~4 (초기 1 + retry 3/3)   ← min(3 + 1, 100) = 4, 개정 전과 동일
    └── retry 소진 → step 실패
```

상한이 관측되는 것은 골든이 다루지 않는 영역이다. `policy.login`에서 `timeout`을
지우고 `retry`를 1000으로 바꾼 변형은 — 두 가지 모두 설정 오류다 — 총 100회에서
멈춘다:

```
└── step.2  authenticate
    ├── 시도 1~100 (데드라인 없음, 선언 예산 1000)
    └── 시도 상한 도달 → step 실패        ← min(1000 + 1, 100) = 100
```

두 실행 모드가 같은 100을 내야 한다. 이 등가성이 `lnpl diff`의 관측 대상 2이며,
`test_backend.TestModeBDerivesRetryAttempts`가 상한 근방 셀에서 이를 고정한다.

## Alternatives

**① `Policy.timeout`을 필수로 만든다.** 데드라인이 항상 있으면 두 번째 상한이
따로 필요 없다. 기각한다: 모든 workflow에 벽시계 예산을 강제하는 것은 재시도
경계보다 훨씬 큰 언어 변경이고, 배치·백필처럼 데드라인이 자연스럽지 않은 작업까지
숫자를 지어내게 만든다. 무엇보다 이 방식은 여전히 **상한이 하나**다 — 이번에는
`timeout` 쪽이 지워지면 무한 루프가 된다. 문제를 옮길 뿐 없애지 않는다.

**② 상한을 `retry`에서 도출한다**(예: `max(retry + 1, 10)`). 기각한다: 도출은
독립이 아니다. 이 RFC의 요건은 "`retry`가 적용되지 않아도 남는 경계"이므로,
`retry`를 읽는 상한은 요건을 정의상 만족하지 못한다. 뮤테이션이 공격하는 지점이
바로 그것이다.

**③ 상한 도달을 별도 실패 유형으로 종결한다**(`AttemptCeilingExceeded` 등).
기각한다: 상한은 유효한 설정에서 도달할 수 없으므로 새 실패 유형은 실사용에서
관측되지 않는 어휘를 하나 늘릴 뿐이다. 상한은 재시도를 멈출 뿐이고 종결 상태는
평소의 step 실패다 — 원인(마지막 시도의 실패)이 그대로 보존된다.

## Open Questions

① **`retry >= 100` 선언에 컴파일 타임 진단을 붙일 것인가.** 지금은 조용히 100에서
멈춘다. `diagnostics.ENFORCEMENT` 행렬에 넣는 것이 자연스러워 보이나, 이 개정의
범위(런타임 경계)를 넘고 진단 어휘의 소유는 RFC-0004에 있다. 별건으로 둔다.

② **상한 값 100의 소유를 어디에 둘 것인가.** 지금은 두 실행 모드가 각자 상수를
들고 있고, 표류 방지는 차분 테스트가 맡는다. `_STEP_COST_MS`·`_IDEMPOTENT_OPS`가
같은 방식이므로 선례와는 정합하나, `backend.py`의 주석이 적어 둔 대로 세 번째
소비자가 생기면 중립 모듈로 추출해야 한다.

# 선언 ↔ 집행 매트릭스

LNPL 프로그램이 **선언하는 것**과 플랫폼이 **실제로 하는 것** 사이의 간극을 한자리에
적는다. 이슈 #36(사전 밖 동사가 조용히 no-op이 됨)과 #38(보안·정책 선언이 집행되지
않음)이 같은 실패 모드 — "플랫폼이 못 하는 것을 사용자에게 말하지 않는다" — 를
공유하므로, 그 사실을 여기 한 벌로 적고 진단도 한 채널로 낸다.

**정본은 코드다.** 아래 두 표는 `impl/lnpl/diagnostics.py`의 `ENFORCEMENT`와
`impl/lnpl/lower.py`의 `VERB_LEXICON`을 사람이 읽는 형태로 옮긴 것이며, 정본은
코드다. 둘이 갈라지면 `impl/tests/test_enforcement_matrix.py`가 실패한다.

## A. 스텝 동사 → 도출 Effect

`VERB_LEXICON`은 **닫힌 사전**이다. 스텝 줄의 첫 토큰이 Verb이고, Effect 도출은
추론이 아니라 이 사전의 조회다(RFC-0002 A.4-3, `lower.py`의 R1).

| verb | effect kind | 비고 |
|------|-------------|------|
| validate | Validation | 대상이 필드면 그 필드의 규칙, `input`이면 엔티티 전체를 시맨틱 타입 규칙으로 검사 |
| authenticate | RepositoryCall | operation `read` |
| load | RepositoryCall | operation `read` |
| find | RepositoryCall | operation `read` |
| read | RepositoryCall | operation `read` |
| create | RepositoryCall | operation `create` |
| insert | RepositoryCall | operation `create` |
| update | RepositoryCall | operation `update` |
| delete | RepositoryCall | operation `delete` |
| cache | CacheAccess | operation `set`, TTL은 `performance cache`가 소유 |
| invalidate | CacheAccess | operation `invalidate` |
| call | NetworkCall | 대상이 없으면 `unspecified` |
| request | NetworkCall | 대상이 없으면 `unspecified` |
| emit | EventEmit | 발행할 이벤트를 목적어로 요구한다. 없으면 컴파일 에러 |
| publish | EventEmit | 발행할 이벤트를 목적어로 요구한다. 없으면 컴파일 에러 |
| authorize | Authorization | requirement를 **기록만** 한다 — §B의 `security` 항목과 같은 간극 |

### 사전 밖 동사

사전 밖 동사는 **컴파일 에러가 아니다.** Effect를 도출하지 않고 서술 스텝
(descriptive step)으로 남으며, `WorkflowStep` 노드는 자식 없이 emit된다.

사전 밖 동사에는 **반드시 `unknown-verb` 진단이 발생한다.** 스텝 1개당 1건이며,
같은 동사가 여러 줄에 나오면 줄마다 1건씩 나온다.

이 둘을 함께 두는 이유: 어휘를 넓혀 `generate token`이 어떤 Effect인지 정하는 것은
**추측**이고, 추측은 프로그램의 의미에 발명을 집어넣는다(R1이 거부하는 바로 그것).
그렇다고 컴파일 에러로 만들면 Charter의 골든 시나리오 자신이 컴파일되지 않는다.
그래서 IR은 그대로 두고, 침묵만 걷어낸다.

골든 예제 `examples/login.lnpl`이 쓰는 사전 밖 동사는 셋이다:

| verb | login.lnpl의 스텝 | 왜 사전에 없나 |
|------|-------------------|----------------|
| generate | `generate token` | 토큰 발급의 Effect 의미(무엇을 읽고 무엇을 쓰는가)가 Phase 1에 정의돼 있지 않다 |
| audit | `audit login` | 감사 로그가 EventEmit인지 RepositoryCall인지 미결이다 |
| return | `return token` | 워크플로 반환값 개념이 IR에 아직 없다 — 스텝 결과 바인딩(#37)의 소관이다 |

## B. 서비스 선언 → 집행 상태

`status`의 뜻:

- `enforced` — 선언이 실행을 실제로 바꾼다.
- `measured` — 실행이 관측·보고하지만 차단하지는 않는다.
- `unenforced` — 실행이 전혀 읽지 않는다.

| clause | name | status | 진단 코드 | 근거 |
|--------|------|--------|-----------|------|
| policy | retry | enforced | — | `run_workflow`가 실패 스텝을 멱등인 동안 재실행한다 |
| policy | timeout | enforced | — | 워크플로 데드라인을 계산하고 초과 시 실행을 실패시킨다 |
| policy | rollback | unenforced | declared-not-enforced | Phase 1에 Transaction 경계가 없어 보상할 대상이 없다 |
| policy | parallel | unenforced | declared-not-enforced | 파싱되지만 실행 계획이 읽지 않는다 |
| security | jwt | unenforced | declared-not-enforced | 토큰을 발급하지도 검증하지도 않는다. OpenAPI 문서까지만 도달한다 |
| security | role | unenforced | declared-not-enforced | 역할을 무엇과도 대조하지 않는다 |
| security | encrypt | unenforced | declared-not-enforced | 필드를 암호화하지 않는다. Password 마스킹은 타입이 하는 별개 동작이다 |
| performance | response | measured | declared-measured-only | 실행마다 측정·보고하지만 예산 초과 실행을 차단하지 않는다 |
| performance | cache | enforced | — | 모든 CacheAccess set이 쓰는 TTL 예산을 소유한다 |
| performance | parallel | unenforced | declared-not-enforced | 파싱되지만 실행 계획이 읽지 않는다 |
| performance | prefetch | unenforced | declared-not-enforced | 파싱되지만 실행 계획이 읽지 않는다 |
| performance | batch | unenforced | declared-not-enforced | 파싱되지만 실행 계획이 읽지 않는다 |

`enforced` 행의 진단 코드 셀이 `—`인 것은 값이 빠진 것이 아니라 **진단을 내지
않는다는 뜻**이다. 집행되는 선언까지 경고하면 보고 전체가 정보를 잃는다.

## C. 진단 코드

| code | severity | 언제 나오나 | 어디서 나오나 |
|------|----------|-------------|---------------|
| unknown-verb | warning | 스텝의 동사가 `VERB_LEXICON` 밖일 때 | 컴파일 타임 — lowering |
| declared-not-enforced | warning | §B에서 status가 `unenforced`인 선언이 있을 때 | 컴파일 타임 — lowering |
| declared-measured-only | warning | §B에서 status가 `measured`인 선언이 있을 때 | 컴파일 타임 — lowering |
| authorization-not-verified | warning | Authorization Effect가 실제로 실행됐을 때 | 런타임 — 인터프리터 |

전부 `warning`이고, **어느 것도 종료 코드를 바꾸지 않는다.** `lnpl compile`과
`lnpl run`이 stderr로 출력하며, 형식은 `impl/lnpl/diagnostics.py`의
`format_lines()` 한 곳에서만 만들어진다.

## D. 이 문서가 약속하지 않는 것

이 문서는 **가시화**의 계약이지 집행의 계약이 아니다. `unenforced` 행을
`enforced`로 바꾸는 일 — jwt 발급·검증, 역할 검사, Transaction 경계와 보상 —
은 이슈 #25와 `docs/ROADMAP.md`의 소관이다.

표의 status를 고치는 것만으로 집행이 생기지는 않는다. 정본은 코드이므로
`ENFORCEMENT`를 먼저 바꿔야 하고, 그러면 그 주장을 뒷받침하는 실제 구현과
테스트가 같은 변경 안에 있어야 한다.

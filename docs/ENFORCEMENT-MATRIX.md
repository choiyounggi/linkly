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
| set | Assignment | 목적어가 엔티티명이 아니라 값 표현식이다(`set product.stock to product.stock - input.quantity`). 바인딩된 행의 필드를 갱신하고 그 사실을 effect로 남긴다 — RFC-0015 |
| format | Assignment | 형식 문자열의 위치 `{}` 개수만큼 Reference 인자를 받아 조립한 문자열을 대상 필드(Text 계열)에 쓴다(`format order.label from "ORD-{}-{}" with product.name input.quantity`). `{}` 개수와 인자 개수 불일치, Password 계열 인자, Text가 아닌 대상은 모두 컴파일 에러 — 마스킹 chokepoint(#43)를 문자열 조립으로 우회하는 경로를 막는다. RFC-0028이 정한 "표현식으로 안 되는 계산은 동사로 흡수" 규칙의 첫 적용 — issue #94 |
| validate | Validation | 대상이 필드면 그 필드의 규칙, `input`이면 엔티티 전체를 시맨틱 타입 규칙으로 검사 |
| authenticate | RepositoryCall | operation `read` |
| load | RepositoryCall | operation `read` |
| find | RepositoryCall | operation `read` |
| read | RepositoryCall | operation `read` |
| list | RepositoryCall | operation `query` — 단일 행이 아니라 그 엔티티의 전 행을 실행 스코프의 RowSet 이름공간에 바인딩한다(RFC-0012 §G12.2·§G12.5, 이 워크플로의 단일 행 바인딩에는 참여하지 않는다). RFC-0025 |
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
| respond | Response | 목적어가 엔티티명이 아니라 `<binding>.<field>` Reference 목록이다(`respond order.id order.status`). 다른 Effect와 달리 상태를 바꾸지 않는다 — 워크플로가 성공적으로 끝난 시점에 바인딩값을 읽어 `response` 절로 조립할 뿐이다. Password 계열 참조는 컴파일 에러 — 마스킹 chokepoint(#43)를 respond로 우회하는 경로를 막는다. OpenAPI 200 스키마가 이 목록에서 유도된다 — issue #96 |

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
| policy | rollback | unenforced | declared-not-enforced | Phase 1에 Transaction 경계가 없어 보상할 대상이 없다. #25의 드라이버는 연산 단위로 커밋한다 |
| policy | parallel | unenforced | declared-not-enforced | 파싱되지만 실행 계획이 읽지 않는다 |
| security | jwt | unenforced | declared-not-enforced | 기본 경로는 발급도 검증도 하지 않는다. `lnpl serve --jwt-secret-env NAME`은 요청마다 베어러 토큰을 검증한다(docs/serving.md M3a, docs/backends.md) |
| security | role | unenforced | declared-not-enforced | 역할을 무엇과도 대조하지 않는다 |
| security | encrypt | unenforced | declared-not-enforced | 필드를 암호화하지 않는다. Password 마스킹은 타입이 하는 별개 동작이다 |
| performance | response | measured | declared-measured-only | 실행마다 측정·보고하지만 예산 초과 실행을 차단하지 않는다 |
| performance | cache | enforced | — | 모든 CacheAccess set이 쓰는 TTL 예산을 소유한다 |
| performance | parallel | unenforced | declared-not-enforced | 파싱되지만 실행 계획이 읽지 않는다 |
| performance | prefetch | unenforced | declared-not-enforced | 파싱되지만 실행 계획이 읽지 않는다 |
| performance | batch | unenforced | declared-not-enforced | 파싱되지만 실행 계획이 읽지 않는다 |
| event | schedule | unenforced | declared-not-enforced | 스케줄러가 없다. 선언은 IR과 OpenAPI 스케줄 메타데이터까지만 도달한다 — 실행기는 이슈 #26(서빙 계층)이 소유한다 (RFC-0016) |

`enforced` 행의 진단 코드 셀이 `—`인 것은 값이 빠진 것이 아니라 **진단을 내지
않는다는 뜻**이다. 집행되는 선언까지 경고하면 보고 전체가 정보를 잃는다.

### status는 왜 경로별이 아니라 하나인가

`security jwt`는 이제 **경로에 따라 다르게** 동작한다 — `lnpl run`과 기본 `serve`는
아무것도 검증하지 않고, `lnpl serve --jwt-secret-env NAME`은 서명·`exp`/`nbf`·
`iss`/`aud`/`typ`를 전부 본다. 그런데 이 진단은 **컴파일 타임**에 나오고, 컴파일러는
그 프로그램이 어느 백엔드로 실행될지 모른다.

그래서 status는 **가장 약한 경로**(기본값)를 말하고, 집행되는 경로는 `근거` 칸이
이름으로 지목한다. 한 칸에 하나의 status만 적고 경로를 감추면 두 경로 중 하나에
대해서는 반드시 거짓이 된다.

## C. 진단 코드

| code | severity | 언제 나오나 | 어디서 나오나 |
|------|----------|-------------|---------------|
| unknown-verb | warning | 스텝의 동사가 `VERB_LEXICON` 밖일 때 | 컴파일 타임 — lowering |
| unknown-entity | warning | 스텝 객체가 선언된 entity 중 어느 것과도(소문자 연결형·필드명) 매칭되지 않는데, 모듈이 entity를 정확히 1개 선언해 그 하나로 조용히 해석될 때 (issue #91) | 컴파일 타임 — lowering |
| declared-not-enforced | info | §B에서 status가 `unenforced`인 선언이 있을 때 | 컴파일 타임 — lowering |
| declared-measured-only | info | §B에서 status가 `measured`인 선언이 있을 때 | 컴파일 타임 — lowering |
| authorization-not-verified | info | Authorization Effect가 실제로 실행됐을 때 | 런타임 — 인터프리터 |
| guard-skipped-steps | warning | 가드가 false여서 선언된 스텝이 실행되지 않았을 때 | 런타임 — 인터프리터 |
| guard-orphaned-steps | warning | 가드 조건이 참조한 엔티티를, 그 가드 뒤의 비가드 스텝이 읽거나 쓸 때 (RFC-0023) | 컴파일 타임 — lowering |
| validation-sample-derived | info | mode B 빌드가 Validation 결과를 파생 sample payload로 확정했을 때 | 컴파일 타임 — mode B 빌드 |
| aggregation-orphaned-list | warning | `sum`/`count`가 참조하는 RowSet을, 이 워크플로의 어떤 `list`도(가드 밖에서) 앞서 채우지 않을 때 (RFC-0025) | 컴파일 타임 — lowering |
| event-source-mismatch | warning | `event <E> on <Entity> <op>` 소스가 선언돼 있고 워크플로에 `emit <E>`가 있는데, 같은 워크플로의 `<op> <entity>` 스텝이 emit과 같은 가드 스코프에 있지 않을 때 (issue #98) | 컴파일 타임 — lowering |
| event-source-orphaned | info | `on`-소스 이벤트를 `emit`하는 워크플로에 그 소스가 지목하는 `<op> <entity>` 스텝이 아예 없을 때 (issue #98) | 컴파일 타임 — lowering |
| derived-never-assigned | warning | `derived` 필드를 가진 entity에 `create` 스텝이 있는데, 그 필드를 채우는 `set`/`format`이 같은 워크플로 안에 하나도 없을 때 (issue #95) | 컴파일 타임 — lowering |

등급을 정하는 것은 이 표가 아니라 `impl/lnpl/diagnostics.py`의 `SEVERITY_OF`다 —
이 표는 §B가 `ENFORCEMENT`의 복사본인 것과 같은 뜻에서 그것의 복사본이고,
`impl/tests/test_enforcement_matrix.py`가 둘이 어긋나면 실패한다. 등급을 가르는
질문은 하나다(RFC-0021): **프로그램을 고치면 이 진단이 사라지는가.** 사라지면
`warning`(`unknown-verb` · `unknown-entity` · `guard-skipped-steps` ·
`guard-orphaned-steps` · `aggregation-orphaned-list` · `event-source-mismatch` ·
`derived-never-assigned`),
사라지지 않으면 `info`(나머지 다섯 행 — 플랫폼이 자기가 하는 일을 진술한 것이다).

**기본 경로에서는 어느 것도 종료 코드를 바꾸지 않는다** — `--strict`를 준 실행에서만
rc 0이 rc 2로 승격되고, `--strict=<level>`이 어느 등급부터 승격할지 고른다(이슈
#45의 게이트를 RFC-0021이 넓힌 것). `lnpl compile`·`lnpl run`·`lnpl build`가
stderr로 출력하며, 형식은 `diagnostics.py`의 `format_lines()` 한 곳에서만 만들어진다.
`build`에는 `--strict`가 없으므로 mode B에서는 승격 경로가 없다(rfcs/0022 잔여 표).

## D. 이 문서가 약속하지 않는 것

이 문서는 **가시화**의 계약이지 집행의 계약이 아니다.

이슈 #25가 닫은 것: **jwt 발급·검증 경로**(`lnpl token` + `serve
--jwt-secret-env`, HS256, RFC 8725 체크리스트)와 **실제 영속 저장소**
(`--backend sqlite:<path>`). 계약과 한계는 `docs/backends.md`.

#25 이후에도 남는 것, 그리고 그 이유:

| 남은 것 | 왜 |
|---------|-----|
| `redis` 실제 바인딩 | RFC-0003의 cache TTL이 주입된 **가상 시계** 단위라 프로세스를 넘으면 뜻이 없다. 영속 캐시는 새 프로세스의 시계 0에 대해 언제나 신선해 보인다 — 만료 계약이 거짓인 저장소가 된다 |
| `policy rollback` | 워크플로 단위 트랜잭션 경계를 만들지 않았다. 보상 로직 없이 경계만 만들면 이 행이 `enforced`로 읽히면서 실패한 실행이 앞선 쓰기를 남긴다 |
| `security role` / `security encrypt` | 역할 검사와 필드 암호화는 손대지 않았다 |
| refresh 토큰·회전·폐기 목록 | 서버 측 세션 저장소를 요구한다. 저장소 없는 refresh는 수명만 긴 액세스 토큰에 다른 이름을 붙인 것이다 |

표의 status를 고치는 것만으로 집행이 생기지는 않는다. 정본은 코드이므로
`ENFORCEMENT`를 먼저 바꿔야 하고, 그러면 그 주장을 뒷받침하는 실제 구현과
테스트가 같은 변경 안에 있어야 한다.

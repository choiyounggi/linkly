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
| authenticate | RepositoryCall | operation `read` — 행 키는 기본적으로 `<entity_id>#<payload의 id>`다. 목적어 뒤에 `by <ref>`를 더하면(RFC-0052) 그 참조의 실행 시점 값이 키가 된다(`find product by input.productId`); 읽은 행은 여전히 엔티티의 기본 바인딩 이름에 바인딩된다(RFC-0012 §G12.2). 참조는 맨 이름(payload 필드), `input.<field>`(그 필드가 `derived`·Password로 선언돼 있어도 payload 값이라 허용), `caller.subject`/`caller.role`, `call ... as <name>` 네트워크 결과 바인딩(무검사 허용), 이 워크플로가 어딘가에서 읽거나 `create ... as`로 만드는 바인딩의 non-`derived`·non-Password 필드 중 하나여야 한다 — 그 외에는 컴파일 에러다: `derived` 필드(RFC-0030 §3 — 값이 믿을 만하게 있지 않다), Password 계열 필드(마스킹 chokepoint #43 — 저장 키를 마스킹 필드로 만들 수 없다), 이 워크플로가 읽지도 만들지도 않는 바인딩(RFC-0012 §G12.5 ⓒ, 워크플로 전체 멤버십 — 순서는 보지 않는다), 두 개 이상의 참조, 참조가 아닌 토큰, `by <ref>`가 아닌 나머지 trailing 단어(이전에는 조용히 버려졌다 — 지금은 컴파일 에러). 키 값이 실행 시점에 없으면 그 스텝이 실패한다(`"-"` 키로 떨어지지 않는다). `by` 없는 스텝은 이 RFC 이전과 바이트 동일 — issue #175 |
| load | RepositoryCall | operation `read` — 행 키는 기본적으로 `<entity_id>#<payload의 id>`다. 목적어 뒤에 `by <ref>`를 더하면(RFC-0052) 그 참조의 실행 시점 값이 키가 된다(`find product by input.productId`); 읽은 행은 여전히 엔티티의 기본 바인딩 이름에 바인딩된다(RFC-0012 §G12.2). 참조는 맨 이름(payload 필드), `input.<field>`(그 필드가 `derived`·Password로 선언돼 있어도 payload 값이라 허용), `caller.subject`/`caller.role`, `call ... as <name>` 네트워크 결과 바인딩(무검사 허용), 이 워크플로가 어딘가에서 읽거나 `create ... as`로 만드는 바인딩의 non-`derived`·non-Password 필드 중 하나여야 한다 — 그 외에는 컴파일 에러다: `derived` 필드(RFC-0030 §3 — 값이 믿을 만하게 있지 않다), Password 계열 필드(마스킹 chokepoint #43 — 저장 키를 마스킹 필드로 만들 수 없다), 이 워크플로가 읽지도 만들지도 않는 바인딩(RFC-0012 §G12.5 ⓒ, 워크플로 전체 멤버십 — 순서는 보지 않는다), 두 개 이상의 참조, 참조가 아닌 토큰, `by <ref>`가 아닌 나머지 trailing 단어(이전에는 조용히 버려졌다 — 지금은 컴파일 에러). 키 값이 실행 시점에 없으면 그 스텝이 실패한다(`"-"` 키로 떨어지지 않는다). `by` 없는 스텝은 이 RFC 이전과 바이트 동일 — issue #175 |
| find | RepositoryCall | operation `read` — 행 키는 기본적으로 `<entity_id>#<payload의 id>`다. 목적어 뒤에 `by <ref>`를 더하면(RFC-0052) 그 참조의 실행 시점 값이 키가 된다(`find product by input.productId`); 읽은 행은 여전히 엔티티의 기본 바인딩 이름에 바인딩된다(RFC-0012 §G12.2). 참조는 맨 이름(payload 필드), `input.<field>`(그 필드가 `derived`·Password로 선언돼 있어도 payload 값이라 허용), `caller.subject`/`caller.role`, `call ... as <name>` 네트워크 결과 바인딩(무검사 허용), 이 워크플로가 어딘가에서 읽거나 `create ... as`로 만드는 바인딩의 non-`derived`·non-Password 필드 중 하나여야 한다 — 그 외에는 컴파일 에러다: `derived` 필드(RFC-0030 §3 — 값이 믿을 만하게 있지 않다), Password 계열 필드(마스킹 chokepoint #43 — 저장 키를 마스킹 필드로 만들 수 없다), 이 워크플로가 읽지도 만들지도 않는 바인딩(RFC-0012 §G12.5 ⓒ, 워크플로 전체 멤버십 — 순서는 보지 않는다), 두 개 이상의 참조, 참조가 아닌 토큰, `by <ref>`가 아닌 나머지 trailing 단어(이전에는 조용히 버려졌다 — 지금은 컴파일 에러). 키 값이 실행 시점에 없으면 그 스텝이 실패한다(`"-"` 키로 떨어지지 않는다). `by` 없는 스텝은 이 RFC 이전과 바이트 동일 — issue #175 |
| read | RepositoryCall | operation `read` — 행 키는 기본적으로 `<entity_id>#<payload의 id>`다. 목적어 뒤에 `by <ref>`를 더하면(RFC-0052) 그 참조의 실행 시점 값이 키가 된다(`find product by input.productId`); 읽은 행은 여전히 엔티티의 기본 바인딩 이름에 바인딩된다(RFC-0012 §G12.2). 참조는 맨 이름(payload 필드), `input.<field>`(그 필드가 `derived`·Password로 선언돼 있어도 payload 값이라 허용), `caller.subject`/`caller.role`, `call ... as <name>` 네트워크 결과 바인딩(무검사 허용), 이 워크플로가 어딘가에서 읽거나 `create ... as`로 만드는 바인딩의 non-`derived`·non-Password 필드 중 하나여야 한다 — 그 외에는 컴파일 에러다: `derived` 필드(RFC-0030 §3 — 값이 믿을 만하게 있지 않다), Password 계열 필드(마스킹 chokepoint #43 — 저장 키를 마스킹 필드로 만들 수 없다), 이 워크플로가 읽지도 만들지도 않는 바인딩(RFC-0012 §G12.5 ⓒ, 워크플로 전체 멤버십 — 순서는 보지 않는다), 두 개 이상의 참조, 참조가 아닌 토큰, `by <ref>`가 아닌 나머지 trailing 단어(이전에는 조용히 버려졌다 — 지금은 컴파일 에러). 키 값이 실행 시점에 없으면 그 스텝이 실패한다(`"-"` 키로 떨어지지 않는다). `by` 없는 스텝은 이 RFC 이전과 바이트 동일 — issue #175 |
| list | RepositoryCall | operation `query` — 단일 행이 아니라 그 엔티티의 전 행을 실행 스코프의 RowSet 이름공간에 바인딩한다(RFC-0012 §G12.2·§G12.5, 이 워크플로의 단일 행 바인딩에는 참여하지 않는다). RFC-0025 |
| create | RepositoryCall | operation `create` — trailing 절은 `as <name>`(생성 결과 바인딩, issue #97 / RFC-0030) 하나뿐이다. 새 행의 키는 언제나 `<entity_id>#<payload의 id>`다 — `by <ref>`는 `create`에서 거부된다(`create accepts either no trailing words or 'as <name>'` 컴파일 에러, issue #175 Gate-1 판정, RFC-0052) |
| insert | RepositoryCall | operation `create` — trailing 절은 `as <name>`(생성 결과 바인딩, issue #97 / RFC-0030) 하나뿐이다. 새 행의 키는 언제나 `<entity_id>#<payload의 id>`다 — `by <ref>`는 `insert`에서 거부된다(`create accepts either no trailing words or 'as <name>'` 컴파일 에러, issue #175 Gate-1 판정, RFC-0052) |
| update | RepositoryCall | operation `update` — 행 키는 기본적으로 `<entity_id>#<payload의 id>`다. 목적어 뒤에 `by <ref>`를 더하면(RFC-0052) 그 참조의 실행 시점 값이 키가 된다(`update stock by input.productId`). 행이 아니라 영향 행 수를 돌려주므로 `by`가 있어도 바인딩하지 않는다. 참조는 맨 이름(payload 필드), `input.<field>`(그 필드가 `derived`·Password로 선언돼 있어도 payload 값이라 허용), `caller.subject`/`caller.role`, `call ... as <name>` 네트워크 결과 바인딩(무검사 허용), 이 워크플로가 어딘가에서 읽거나 `create ... as`로 만드는 바인딩의 non-`derived`·non-Password 필드 중 하나여야 한다 — 그 외에는 컴파일 에러다: `derived` 필드(RFC-0030 §3 — 값이 믿을 만하게 있지 않다), Password 계열 필드(마스킹 chokepoint #43 — 저장 키를 마스킹 필드로 만들 수 없다), 이 워크플로가 읽지도 만들지도 않는 바인딩(RFC-0012 §G12.5 ⓒ, 워크플로 전체 멤버십 — 순서는 보지 않는다), 두 개 이상의 참조, 참조가 아닌 토큰, `by <ref>`가 아닌 나머지 trailing 단어(이전에는 조용히 버려졌다 — 지금은 컴파일 에러). 키 값이 실행 시점에 없으면 그 스텝이 실패한다(`"-"` 키로 떨어지지 않는다). `by` 없는 스텝은 이 RFC 이전과 바이트 동일 — issue #175 |
| delete | RepositoryCall | operation `delete` — 행 키는 기본적으로 `<entity_id>#<payload의 id>`다. 목적어 뒤에 `by <ref>`를 더하면(RFC-0052) 그 참조의 실행 시점 값이 키가 된다(`delete stock by input.productId`). 행이 아니라 영향 행 수를 돌려주므로 `by`가 있어도 바인딩하지 않는다. 참조는 맨 이름(payload 필드), `input.<field>`(그 필드가 `derived`·Password로 선언돼 있어도 payload 값이라 허용), `caller.subject`/`caller.role`, `call ... as <name>` 네트워크 결과 바인딩(무검사 허용), 이 워크플로가 어딘가에서 읽거나 `create ... as`로 만드는 바인딩의 non-`derived`·non-Password 필드 중 하나여야 한다 — 그 외에는 컴파일 에러다: `derived` 필드(RFC-0030 §3 — 값이 믿을 만하게 있지 않다), Password 계열 필드(마스킹 chokepoint #43 — 저장 키를 마스킹 필드로 만들 수 없다), 이 워크플로가 읽지도 만들지도 않는 바인딩(RFC-0012 §G12.5 ⓒ, 워크플로 전체 멤버십 — 순서는 보지 않는다), 두 개 이상의 참조, 참조가 아닌 토큰, `by <ref>`가 아닌 나머지 trailing 단어(이전에는 조용히 버려졌다 — 지금은 컴파일 에러). 키 값이 실행 시점에 없으면 그 스텝이 실패한다(`"-"` 키로 떨어지지 않는다). `by` 없는 스텝은 이 RFC 이전과 바이트 동일 — issue #175 |
| cache | CacheAccess | operation `set`, TTL은 `performance cache`가 소유 |
| invalidate | CacheAccess | operation `invalidate` |
| call | NetworkCall | 대상이 없으면 `unspecified` |
| request | NetworkCall | 대상이 없으면 `unspecified` |
| emit | EventEmit | 발행할 이벤트를 목적어로 요구한다. 없으면 컴파일 에러 — 목적어 뒤에 `with <ref> <ref>...`를 더하면(issue #178, RFC-0049) 그 참조들로 발행 payload를 구성한다(`payloadMap`, 저자 순서 그대로): 참조는 `create ... as`/read 바인딩의 선언된 필드(`derived` 필드는 앞선 `set`/`format`이 채웠을 때만), `input.<field>`, `call ... as <name>` 네트워크 결과 바인딩(선언된 형태가 없어 무검사로 허용) 셋 중 하나여야 한다 — 그 외에는 컴파일 에러다: 맨 이름, `derived` 필드인데 같은 바인딩·필드를 채우는 `set`/`format`이 같은 가드 스코프에서 이 `emit`보다 앞에 없는 경우(RFC-0030 §3 — 서버 계산 전용, `create` payload로 시드되지 않는다; 앞서 채웠으면 허용된다, issue #204), Password 계열 필드(마스킹 chokepoint #43 우회 차단, respond와 같은 규칙), 같은 매핑 필드명을 두 번 쓰는 것, `with <ref>...`가 아닌 나머지 trailing 단어(이전에는 조용히 버려졌다 — 지금은 컴파일 에러). `with` 없는 `emit`은 이 RFC 이전과 바이트 동일 |
| publish | EventEmit | 발행할 이벤트를 목적어로 요구한다. 없으면 컴파일 에러 — 목적어 뒤에 `with <ref> <ref>...`를 더하면(issue #178, RFC-0049) 그 참조들로 발행 payload를 구성한다(`payloadMap`, 저자 순서 그대로): 참조는 `create ... as`/read 바인딩의 선언된 필드(`derived` 필드는 앞선 `set`/`format`이 채웠을 때만), `input.<field>`, `call ... as <name>` 네트워크 결과 바인딩(선언된 형태가 없어 무검사로 허용) 셋 중 하나여야 한다 — 그 외에는 컴파일 에러다: 맨 이름, `derived` 필드인데 같은 바인딩·필드를 채우는 `set`/`format`이 같은 가드 스코프에서 이 `emit`보다 앞에 없는 경우(RFC-0030 §3 — 서버 계산 전용, `create` payload로 시드되지 않는다; 앞서 채웠으면 허용된다, issue #204), Password 계열 필드(마스킹 chokepoint #43 우회 차단, respond와 같은 규칙), 같은 매핑 필드명을 두 번 쓰는 것, `with <ref>...`가 아닌 나머지 trailing 단어(이전에는 조용히 버려졌다 — 지금은 컴파일 에러). `with` 없는 `publish`는 이 RFC 이전과 바이트 동일 |
| authorize | Authorization | requirement를 **기록만** 한다 — §B의 `security` 항목과 같은 간극 |
| respond | Response | 목적어가 엔티티명이 아니라 `<binding>.<field>` Reference 목록이다(`respond order.id order.status`). 다른 Effect와 달리 상태를 바꾸지 않는다 — 워크플로가 성공적으로 끝난 시점에 바인딩값을 읽어 `response` 절로 조립할 뿐이다. Password 계열 참조는 컴파일 에러 — 마스킹 chokepoint(#43)를 respond로 우회하는 경로를 막는다. OpenAPI 200 스키마가 이 목록에서 유도된다 — issue #96. RFC-0059: 이름 붙인 집계 항 `<name> as <func> <ref>`(`sum`/`count`/`avg`/`min`/`max` 5종만, `respond orderCount as count order`)를 같은 줄에 섞어 쓸 수 있다 — `set`과 같은 집계 타입 규칙과 `aggregation-orphaned-list` 경고를 받고, 응답의 평면 키로 실린다. 목록 항 `respond list <binding>`은 그 줄에 혼자 쓰며 RowSet을 `{items, next}` 봉투로 싣는다(`next`는 항상 null) — 그 RowSet을 채우는 `list ... where`에 `limit`이 없으면 컴파일 에러다. 두 항 모두 행을 쓰지 않는다. 모드 B는 두 항을 거부한다(`build`·`diff` 같은 순서, `fail` 다음) |
| note | Annotation | 목적어가 엔티티명이 아니라 `"<template>" [with <ref>...]`다(`note "picked-tier-{}" with customer.tier`) — `format`의 저장 표현식 파서(`condition._parse_format_rhs`)를 그대로 재사용한다. respond와 같은 이유로 Effect가 아니다: 상태를 바꾸지 않고 현재 span에 구조화 어노테이션 하나를 남길 뿐이다. 참조는 컴파일 타임에 검증하지 않는다 — 미바인딩 참조는 실행 실패가 아니라 값 `null`(관측이 실행을 죽이면 안 된다), Password 계열 값은 `mask_payload` chokepoint(#43)로 마스킹된 채로만 실린다. 워크플로당 16개 초과 시 `note-cap-exceeded` 경고 — issue #111 |
| fail | Rejection | 목적어가 엔티티명이 아니라 kebab-case 코드 하나다(`fail out-of-stock`). 도달하면 실행이 `failed`로 끝나고 `failure_kind = "rejected"`, `failure_reason` = 그 코드, 앞선 쓰기는 RFC-0032 경계가 롤백한다. `when`/`until` 가드가 소유하지 않는 `fail`(`repeat N` 아래 포함 — 본문이 언제나 실행된다), kebab-case가 아닌 코드, 코드 누락, 코드 뒤 낱말, 서버가 이미 쓰는 problem `code`(`not-found` 등)와 같은 코드는 전부 컴파일 에러다. 재시도하지 않는다. serve는 422 + `code` = 그 코드, `consume by`는 E7(422 `event-rejected`), mode B는 거부 — RFC-0056, issue #206 |

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
| policy | rollback | enforced | — | `run_workflow`가 첫 step 전에 트랜잭션을 열고, 실행이 실패하면 그 실행에서 이뤄진 모든 쓰기(outbox 등록 포함)를 **선언 여부와 무관하게 모든 서비스에서 무조건** 롤백한다 — `policy rollback` 선언이 실제로 좌우하는 것은 (a) 그 INFO trace 로그 한 줄과 (b) 컴파일 타임 `rollback-escapes-network` 진단(issue #112)의 활성화뿐이다(issue #79, RFC-0032, RFC-0036) |
| policy | parallel | enforced | — | `run_workflow`가 `parallel` 블록의 스텝을 블록 스코프 `ThreadPoolExecutor`에서 동시 실행한다 — fail-fast(한 스텝 실패 시 나머지 취소), 동시성 상한은 선언값(없으면 블록 스텝 수)이 정한다(issue #108, RFC-0041) |
| security | jwt | unenforced | declared-not-enforced | 기본 경로는 발급도 검증도 하지 않는다. `lnpl serve --jwt-secret-env NAME`은 요청마다 베어러 토큰을 검증한다(docs/serving.md M3a, docs/backends.md) |
| security | role | enforced | — | 이 서비스가 소유한 모든 라우트는 검증된 토큰의 역할이 `<r>`과 정확히 일치할 때만 실행된다. 불일치·부재는 403 `forbidden`(docs/serving.md M3b). `jwt`와 달리 "약한 경로"가 없다 — `security role`을 선언하고도 `serve`가 뜬다면 token_provider 없이는 기동 자체가 rc 2로 거부되기 때문이다(D6) |
| performance | response | measured | declared-measured-only | 실행마다 측정·보고하지만 예산 초과 실행을 차단하지 않는다 |
| performance | cache | enforced | — | 모든 CacheAccess set이 쓰는 TTL 예산을 소유한다 |
| performance | parallel | unenforced | declared-not-enforced | 파싱되지만 실행 계획이 읽지 않는다 |
| performance | prefetch | unenforced | declared-not-enforced | 파싱되지만 실행 계획이 읽지 않는다 |
| performance | batch | unenforced | declared-not-enforced | 파싱되지만 실행 계획이 읽지 않는다 |
| event | schedule | unenforced | declared-not-enforced | 기본 경로(선언만)는 아무것도 부르지 않는다. `lnpl trigger --schedule NAME`과 `POST /-/schedules/<slug>`(`lnpl serve`)가 요청 시 연결된 워크플로를 실행한다 — 단 cron/systemd 같은 외부 스케줄러가 그중 하나를 부르도록 구성돼 있어야 한다(issue #81, `lnpl schedules`가 그 스니펫을 생성한다) |

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

`event schedule`도 같은 이유로 `unenforced`다(issue #81) — 컴파일러는 운영자가
`lnpl trigger`나 `/-/schedules/<slug>`를 실제로 cron/systemd에 연결했는지 알
방법이 없고, 연결하지 않으면 선언은 여전히 아무것도 실행하지 않는다.

### `performance parallel`/`prefetch`/`batch`는 왜 여전히 unenforced인가

issue #108이 집행하는 것은 `policy parallel`(§B 위 행) 하나뿐이다 — **워크플로
안 스텝의 실행 순서**를 바꾼다. `performance parallel`/`prefetch`/`batch` 셋은
이름은 비슷해도 뜻이 다르다: 저장소 호출 하나를 **어떻게** 내보내는지(묶어서
prefetch할지, batch로 낼지)를 말하는 저장소 접근 패턴 선언이다. 그 의미는
질의 술어(issue #116의 이웃)가 있어야 채워지고, 이번 이슈의 범위 밖이다 — 셋
다 `unenforced`로 남는다.

### 실측 열의 유일한 소스는 드라이버 신고다 (RFC-0043)

위 표의 `status`/`근거`는 **코어가 코드로 아는 사실**(`impl/lnpl/diagnostics.py`의
`ENFORCEMENT`)만 담는다 — 어떤 실제 postgres 드라이버가 `READ COMMITTED`로
격리되는지, 어떤 kafka 아웃박스 릴레이가 `at-least-once`만 보장하는지는 이 표가
알 수 있는 사실이 아니다. 그 자리는 RFC-0043(이슈 #138/#140)이 연 별도의
경로가 채운다: 드라이버 팩토리가 `lnpl_enforcement`(class/static 속성, closed
axis table — `delivery`/`isolation`/`cache_scope`/`token_claims`)로 자기
행동을 **자기 신고**하면, `capability` 선언이 활성화하는 슬롯에 설치된 모든
드라이버를 코어가 대조해 `<entry-point 이름>/<axis-code>` 진단(전원 `info`)을
합성한다 — `impl/lnpl/capabilities.py`의 `enforcement_diagnostic_records`,
`docs/backends.md`의 신고 SPI 절.

**신고가 실측의 유일한 소스다 — 미신고와 unenforced는 다른 사실이다.**
드라이버가 `lnpl_enforcement`를 채우지 않으면(내장 `fake`/`sqlite`를 포함해
오늘 설치된 드라이버 대부분이 그렇다) 그 축에 대해 아무 진단도 나오지 않는다.
그 침묵은 "이 드라이버는 그 축을 강제하지 않는다"는 뜻이 **아니다** — 위 §B
표의 `unenforced`(코어가 실행 경로를 읽어서 아는 사실)와 혼동해서는 안 된다.
신고 없음은 그저 "이 드라이버가 아직 말하지 않았다"는 뜻이고, `lnpl
capabilities --json`의 `slots.<slot>.registered[].enforcement` 키 자체가
없는 것으로 나타난다(신고가 있을 때만 존재하는 additive 키 — 빈 `dict`가
아니다). `lnpl compile`이 조용하다고 해서 그 드라이버가 순진하다고 읽어서는
안 된다.

## C. 진단 코드

| code | severity | 언제 나오나 | 어디서 나오나 |
|------|----------|-------------|---------------|
| unknown-verb | warning | 스텝의 동사가 `VERB_LEXICON` 밖일 때 | 컴파일 타임 — lowering |
| unknown-entity | warning | 스텝 객체가 선언된 entity 중 어느 것과도(소문자 연결형·필드명) 매칭되지 않는데, 모듈이 entity를 정확히 1개 선언해 그 하나로 조용히 해석될 때 (issue #91) | 컴파일 타임 — lowering |
| declared-not-enforced | info | §B에서 status가 `unenforced`인 선언이 있을 때 | 컴파일 타임 — lowering |
| declared-measured-only | info | §B에서 status가 `measured`인 선언이 있을 때 | 컴파일 타임 — lowering |
| authorization-not-verified | warning | Authorization Effect가 실제로 실행됐을 때 | 런타임 — 인터프리터 |
| guard-skipped-steps | warning | 가드가 false여서 선언된 스텝이 실행되지 않았을 때 | 런타임 — 인터프리터 |
| guard-orphaned-steps | warning | 가드 조건이 참조한 엔티티를, 그 가드 뒤의 비가드 스텝이 읽거나 쓸 때 (RFC-0023) | 컴파일 타임 — lowering |
| validation-sample-derived | info | mode B 빌드가 Validation 결과를 파생 sample payload로 확정했을 때 | 컴파일 타임 — mode B 빌드 |
| aggregation-orphaned-list | warning | `sum`/`count`가 참조하는 RowSet을, 이 워크플로의 어떤 `list`도(가드 밖에서) 앞서 채우지 않을 때 (RFC-0025) | 컴파일 타임 — lowering |
| event-source-mismatch | warning | `event <E> on <Entity> <op>` 소스가 선언돼 있고 워크플로에 `emit <E>`가 있는데, 같은 워크플로의 `<op> <entity>` 스텝이 emit과 같은 가드 스코프에 있지 않을 때 (issue #98) | 컴파일 타임 — lowering |
| event-source-orphaned | info | `on`-소스 이벤트를 `emit`하는 워크플로에 그 소스가 지목하는 `<op> <entity>` 스텝이 아예 없을 때 (issue #98) | 컴파일 타임 — lowering |
| derived-never-assigned | warning | `derived` 필드를 가진 entity에 `create` 스텝이 있는데, 그 필드를 채우는 `set`/`format`이 같은 워크플로 안에 하나도 없을 때 (issue #95) | 컴파일 타임 — lowering |
| declared-not-bound | info | `call`/`request`의 target이 URL 리터럴이 아닌 논리명인데, 그 이름을 선언한 `capability http`가 모듈에 없을 때 (issue #101) — method POST·인증 없음으로 그대로 실행된다 | 컴파일 타임 — lowering |
| stored-row-shape-mismatch | warning | `read`/`find`가 돌려준 행에 entity가 선언한 필드가 없거나(missing), 있어도 선언된 타입과 맞지 않을 때(type) — 값은 절대 싣지 않는다 (issue #85) | 런타임 — 인터프리터 |
| rollback-escapes-network | warning | `policy rollback`을 선언한 서비스가 소유한 워크플로에 `call`/`request`(NetworkCall) 스텝이 있을 때 — 저장소 트랜잭션 밖이라 rollback이 되돌리지 못한다. 스텝마다 한 건씩 (issue #112) | 컴파일 타임 — lowering |
| retry-on-non-idempotent | warning | `capability http`가 `method post`/`patch`와 `retry`를 함께 선언했을 때 — 비멱등 메서드에 재시도를 걸면 효과가 중복될 수 있다 (issue #109) | 컴파일 타임 — lowering |
| note-cap-exceeded | warning | 워크플로 하나에 `note`가 16개를 초과할 때 — "필요한 로그만"을 어휘 차원에서 지킨다 (issue #111) | 컴파일 타임 — lowering |
| event-consume-cycle | warning | `event <E> consume by <W>`가 선언돼 있고, `W`(그 자식 워크플로 포함)가 결국 `E`를 다시 `emit`/`publish`할 때 — 런타임 무한 재디스패치의 정적 신호. 가드가 실제로는 그 경로를 막을 수 있어 에러가 아니라 경고다 (issue #118) | 컴파일 타임 — lowering, 모든 워크플로를 다 내린 뒤 |
| predicate-not-pushed-down | info | `list where`/`order by`/`limit`이 있는 `list <Entity>`가 `supports_predicate`를 선언하지 않은 드라이버로 실행돼, 코어가 전체 행을 fetch한 뒤 로컬에서 필터/정렬/자르기를 했을 때 (issue #164) | 런타임 — 인터프리터 |
| respond-field-missing | warning | `respond`가 가리키는 바인딩은 있는데, 그 바인딩이 가리키는 필드가 저장된 행에 없을 때 — 그 참조는 응답에서 빠지고 진단이 하나 남는다 (issue #198) | 런타임 — 인터프리터 |
| guard-scoped-binding-escape | warning | 가드(또는 가드된 `parallel`/`pipeline` 블록) 안의 `create ... as`/`call ... as`/`request ... as`가 만든 바인딩을, 그 가드 스코프 밖의 `respond`/`set`/`format`/`emit ... with`가 읽을 때 (issue #198) | 컴파일 타임 — lowering |
| optional-field-unguarded-arithmetic | warning | `set`/가드 산술이 `optional` 필드를 읽는데, 그 필드의 존재(`exists`)를 확인하는 가드가 이 스텝을 소유하지 않을 때 (RFC-0053) | 컴파일 타임 — lowering |

등급을 정하는 것은 이 표가 아니라 `impl/lnpl/diagnostics.py`의 `SEVERITY_OF`다 —
이 표는 §B가 `ENFORCEMENT`의 복사본인 것과 같은 뜻에서 그것의 복사본이고,
`impl/tests/test_enforcement_matrix.py`가 둘이 어긋나면 실패한다. 등급을 가르는
질문은 하나다(RFC-0021): **프로그램을 고치면 이 진단이 사라지는가.** 사라지면
`warning`(`unknown-verb` · `unknown-entity` · `guard-skipped-steps` ·
`guard-orphaned-steps` · `aggregation-orphaned-list` · `event-source-mismatch` ·
`derived-never-assigned` · `stored-row-shape-mismatch`(프로그램이 아니라
데이터를 고치면 사라진다는 점만 다르다 — 이슈 #85, RFC-0021 질문의 데이터판) ·
`rollback-escapes-network`(호출을 경계 밖으로 옮기거나 `rollback`을 떼면
사라진다 — 이슈 #112) · `retry-on-non-idempotent`(`retry`를 떼거나 멱등
메서드로 바꾸면 사라진다 — 이슈 #109) · `note-cap-exceeded`(`note`를 16개
이하로 줄이면 사라진다 — 이슈 #111) · `event-consume-cycle`(`consume by`를
떼거나 그 워크플로의 `emit`을 떼면 사라진다 — 이슈 #118) ·
`respond-field-missing`(저장된 행에 누락된 필드를 채우면 사라진다 — 이슈 #198,
RFC-0021 질문의 데이터판) · `guard-scoped-binding-escape`(리더를 가드 스코프
안으로 옮기거나 가드 줄을 반복하면 사라진다 — 이슈 #198) ·
`optional-field-unguarded-arithmetic`(가드 안으로 옮기면 사라진다 — RFC-0053)),
사라지지 않으면 `info`(나머지 여섯 행 — 플랫폼이 자기가 하는 일을 진술한 것이다).

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
| `security encrypt` | 더 이상 없다 — issue #127이 RFC-0035 §D3을 집행해 닫힌 어휘에서 제거했다(드라이버 0건이 항상 빈 집합이었다는 이유로). `security role`은 issue #119가 이후 집행으로 옮겼다 |
| refresh 토큰·회전·폐기 목록 | 서버 측 세션 저장소를 요구한다. 저장소 없는 refresh는 수명만 긴 액세스 토큰에 다른 이름을 붙인 것이다 |

표의 status를 고치는 것만으로 집행이 생기지는 않는다. 정본은 코드이므로
`ENFORCEMENT`를 먼저 바꿔야 하고, 그러면 그 주장을 뒷받침하는 실제 구현과
테스트가 같은 변경 안에 있어야 한다.

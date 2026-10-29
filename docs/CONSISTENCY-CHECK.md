# CONSISTENCY-CHECK — RFC 스위트 교차 정합성 (Task 09)

7개 RFC(0000~0006) + `schemas/lir.schema.json` + `examples/` + `scripts/validate_ir.py`를
교차 대조한 판정 기록. 이 문서는 새 설계를 하지 않는다 — 이미 확정된 문서 사이의 불일치를
찾아 판정하고, 해소한 것과 이월한 것을 구분해 기록한다.

- 판정 대상 항목: **C1~C9** (C1~C7은 태스크 스펙, C5는 2층 보정, C8·C9는 오케스트레이터 신설)
- 판정 원칙: **IR이 정본** — `plans/rfc-suite/plan.md` **D1**. 충돌 시 RFC-0001 쪽 정의에 다른
  RFC를 맞춘다.
- RFC Status는 이 판정과 무관하게 전부 `Draft`를 유지한다. RFC-0000 §2가 Accepted 전이 기준을
  "Task 09 교차 정합성 체크리스트 전 항목 PASS **+ 소유자 승인**"으로 규정하므로, 체크리스트
  통과는 승격의 필요조건일 뿐이다(승격은 사용자 리뷰 대상).

## 0. 판정 프로토콜

이 태스크에는 실행 코드가 없으므로 **판정 명령 자체가 테스트**다. 따라서 검사가 "항상 PASS
되는 항목"이 되지 않도록, dev-loop 위키 `testing/quality/tests-that-cannot-fail.md`의 규칙 1
("테스트는 **실패할 수 있어야만** 무언가를 증명한다")과 그 Edge case 행("코드 변형이 비현실적이면
**기대값을 반대로 넣어 red를 요구**한다")을 문서 검사에 적용한다.

각 항목은 아래 5요소를 **전부** 갖춘다. 하나라도 빠지면 그 항목은 미판정이다.

| # | 요소 | 규칙 |
|---|------|------|
| E1 | `### 기준` | 무엇이 PASS인가를 **판정 전에** 이진 문장으로 고정. 판정 후 완화 금지 |
| E2 | `### 명령·출력` | 실행한 명령과 **출력 원문**을 코드블록으로 붙인다. "확인함" 산문 금지 |
| E3 | `### 근거 인용` | `파일:행` 또는 `파일 §절` + 원문 인용. 파일명만 쓰는 것은 근거가 아니다 |
| E4 | `### 음성 대조` | 같은 검사에 **반대 기대**를 넣어 0건/FAIL이 나옴을 보인다 |
| E5 | `### 판정` | `PASS` \| `FAIL` \| `FINDING` 한 낱말 |

### 음성 대조의 3형

검사가 장식이 아님을 보이는 대조. 항목당 최소 1형을 쓴다.

| 형 | 이름 | 방법 |
|----|------|------|
| **N1** | 부재 대조 | 카탈로그·골든에 **없는 값**을 같은 명령에 넣어 0건을 보인다(가짜 kind `FileWrite`, 가짜 메서드 `kb.search`, 골든에 없는 `capability kafka`) |
| **N2** | 분별 대조 | 같은 명령이 대상 집합 안에서 **갈린다**는 것을 보인다. 전 대상에 무조건 히트하면 그 검사는 아무것도 판별하지 않는다 |
| **N3** | 반전 대조 | 기대값을 반대로 뒤집어 red를 요구한다(위키 Edge case 행) |

### 검사 범위 규약

골든 시나리오 규칙은 RFC-0000 §5가 각 RFC의 `## Examples` 섹션에 부과하므로, C5의 검사 범위는
`## Examples` 섹션 한정이다. 구획 추출 함수를 정본으로 고정한다:

```sh
EX() { awk '/^## Examples/{on=1} /^## Alternatives/{on=0} on' "$1"; }
```

베이스라인: HEAD `ed57711`, 워킹트리 clean(판정 시작 시점 실측).

## 0.1 판정 요약

| 항목 | 판정 | 근거 위치 | 음성 대조 형태 |
|------|------|-----------|----------------|
| C1 문법 최상위 선언 ↔ IR Declaration 1:1 | **PASS** | `0002:255-256,258-265` ↔ `0001:96-104` | N1 — 6번째 짝(`PolicyDecl` 등) 0건 |
| C2 RFC-0003의 Effect 6종 전체 실행 의미 | **PASS** | `0003:87,91-96` ↔ `0001:46,116-125` | N1 — 가짜 kind `FileWrite` 0건 |
| C3 고수준 패스 불변조건 + dialect 이후 역추적 | **PASS** | `0004:100`(S3 스키마) · `0004:101-104,171-173`(S4~S7 역추적) | N2 — S1~S3=0 / S4~S7=1로 갈림 |
| C4 `kb.*` = RFC-0005 소비 인터페이스 3종 | **PASS** | `0005:142-144` ↔ `0006:225-227,234-236` (diff 빈 출력) | N1 — 가짜 4번째 메서드 0건 |
| C5 골든 시나리오 관통(C5a 엄격 / C5b 관점별) | **C5a: PASS / C5b: PASS** | `0000:59-62`(§5 규범) + 소속 표 + 요소×RFC 히트 표 | N1 — `capability kafka`·`timeout 9s`·`entity Order` 전 6 RFC 0건 |
| C6 GLOSSARY 10 용어의 재정의 부재 | **PASS** | 판별 속성 10행 + 용어별 원문 대조 10행 + 기계 검사 A·B | N1(가짜 용어 0건) + N3(재정의 선언 0건) |
| C7 `validate_ir.py --self-test` exit 0 | **PASS** | 출력 5행 + `EXIT=0` | 스크립트 내장 negative 3건 전부 REJECTED |
| C8 Heap 프리미티브 런타임 계약 공백 | **FINDING** — 경로 (b) 적용 | `0003:143-145,149,150`(계약 2종) ↔ `0004:242,251`(Heap 선택) | N2(arena·pool은 계약 찾아냄) + N1(Stack 오탐 배제) + N3(전수 검색으로 반대 가설 기각) |
| C9 하네스 미탐지 3부류 | **①③ PASS(무모순·무강등) / ② 모순 확정 → 해소** | ① `0003:92,111,149,150`↔`0004:198,199,241,243` / ② `0004:282-283` vs `:410-415,260-265` / ③ `0004:55-57,99,101,198,213` | ① N3 반전 / ② N1 목록 겹침 0건 / ③ N2 어휘 2건 적발 |

**DoD 요건 충족**: C1~C7 **전항 PASS**. C8·C9는 판정·기록 항목이며 각 발견에 해소 소유자와
인용 Phase가 명시됐다.

## C1 — 문법 최상위 선언 ↔ IR Declaration 1:1

### 기준

RFC-0002 §Full grammar의 `Declaration` 우변이 만드는 최상위 선언 생산규칙 5종
`{EntityDecl, ServiceDecl, WorkflowDecl, EventDecl, CapabilityDecl}`과 RFC-0001 노드 카탈로그
Declaration 표의 kind 5종 `{Entity, Service, Workflow, Event, Capability}`가 **집합으로 1:1**이고,
**양쪽 개수가 정확히 5**여야 한다. 한쪽에만 있는 항목이 1개라도 있으면 FAIL.

### 명령·출력

```sh
$ grep -nE "^Declaration +::=" -A1 rfcs/0002-syntax.md
255:Declaration       ::= EntityDecl | ServiceDecl | WorkflowDecl | EventDecl
256-                    | CapabilityDecl

$ grep -nE "^(EntityDecl|ServiceDecl|WorkflowDecl|EventDecl|CapabilityDecl) +::=" rfcs/0002-syntax.md | wc -l
5

$ grep -nE '^\| (Entity|Service|Workflow|Event|Capability) \|' rfcs/0001-semantic-ir.md | wc -l
5
```

대응 표:

| RFC-0002 생산규칙 (`:258-265`) | RFC-0001 Declaration kind (`:100-104`) |
|-------------------------------|----------------------------------------|
| `EntityDecl ::= 'entity' PascalName EOL FieldClause+` | `Entity` |
| `ServiceDecl ::= 'service' PascalName EOL ServiceClause*` | `Service` |
| `WorkflowDecl ::= 'workflow' PascalName EOL WorkflowItem* SpecClause?` | `Workflow` |
| `EventDecl ::= 'event' PascalName EventSource? EOL` | `Event` |
| `CapabilityDecl ::= 'capability' CapabilityName Version? EOL` | `Capability` |

### 근거 인용

- `rfcs/0002-syntax.md:255-256` — `Declaration ::= EntityDecl | ServiceDecl | WorkflowDecl |
  EventDecl | CapabilityDecl` (우변 5택, 6번째 분기 없음)
- `rfcs/0002-syntax.md:157-158` — "최상위 선언 키워드 5종은 RFC-0001 Declaration kind 5종
  (Entity/Service/Workflow/Event/Capability)과 1:1이다. 키워드는 전부 소문자다."
- `rfcs/0001-semantic-ir.md:96` — "**Declaration** — 무엇이 존재하는가. 진입 노드가 될 수 있는
  유일한 대분류." + `:100-104`(5행 표)
- `rfcs/0002-syntax.md:152` — 키워드 카탈로그 "최상위 선언 | `entity` `service` `workflow`
  `event` `capability` | 5"
- 방향성 확인: 문법 쪽 5종 전부가 IR kind를 갖고(누락 0), IR Declaration 5종 전부가 문법 생산규칙을
  갖는다(잉여 0) — 양방향이므로 1:1이다.

### 음성 대조

**N1 부재 대조.** 존재하지 않는 6번째 짝을 기대하면 검사가 0을 낸다:

```sh
$ grep -cE "^(PolicyDecl|PipelineDecl|ValidationDecl) +::=" rfcs/0002-syntax.md
0
```

`Policy`·`Pipeline`·`Validation`은 RFC-0001에서 각각 **Constraint**(`:134-138`)·**Behavior**
(`:113`)·**Behavior**(`:111`) 대분류이며 Declaration이 아니다. 즉 이 검사는 "아무 kind나 최상위
선언으로 통과시키는" 검사가 아니다 — 대분류를 실제로 분별한다. 만약 `PolicyDecl`이 EBNF에
있었다면 C1은 FAIL이었다.

### 판정

PASS

## C2 — RFC-0003의 Effect 6종 전체 실행 의미

### 기준

RFC-0003 §Execution Model의 "Effect 실행 의미" 표가 RFC-0001 Effect 대분류 6종
`{NetworkCall, RepositoryCall, CacheAccess, Transaction, Authorization, EventEmit}` **전부에 대해
각 1행**을 갖는다(⊇ 성립, 누락 0). 6종 중 하나라도 0행이면 FAIL.

### 명령·출력

```sh
$ for k in NetworkCall RepositoryCall CacheAccess Transaction Authorization EventEmit FileWrite; do
    printf "%-16s %s\n" "$k" "$(awk '/^### Execution Model/{on=1} /^### Policy Enforcement/{on=0} on' \
      rfcs/0003-runtime.md | grep -cE "^\| $k \|")"; done
NetworkCall      1
RepositoryCall   1
CacheAccess      1
Transaction      1
Authorization    1
EventEmit        1
FileWrite        0
```

### 근거 인용

- `rfcs/0003-runtime.md:87` — "**Effect 실행 의미.** Effect 대분류 6종 전부의 계약은 다음 표와 같다."
- `rfcs/0003-runtime.md:91-96` — 6행 각각이 실행 의미를 규정한다. 발췌:
  - `:91` NetworkCall — "비동기 아웃바운드 호출 = await 지점. 모든 호출에 명시적 connect timeout
    + request timeout 필수 — 무한 기본값 금지"
  - `:92` RepositoryCall — "capability 커넥션 pool을 통해 실행되는 await 지점. 커넥션 획득은
    operation당 1회이며, 다른 pool 자원을 획득하기 전에 반환해야 한다"
  - `:93` CacheAccess — "`get` = miss가 오류가 아니라 정상 경로인 조회 … `set` = TTL 필수"
  - `:94` Transaction — "원자적 스코프 노드: children 전부 성공 시 커밋, 하나라도 실패 시 abort"
  - `:95` Authorization — "소유 step의 다른 Effect보다 먼저 평가되는 게이트. **거부(deny)는
    비재시도 실패다**"
  - `:96` EventEmit — "비동기 발행 … Transaction의 children으로 소유된 EventEmit은 **커밋 성공
    후에만** 발행된다"
- 상류 계약: `rfcs/0001-semantic-ir.md:46` — "**Effect** — 어떤 부수효과를 일으키는가:
  NetworkCall, RepositoryCall, CacheAccess, Transaction, Authorization, EventEmit" +
  `:118-125`(6행 카탈로그)
- 위임의 이행: `rfcs/0001-semantic-ir.md:92-93` — "실행 의미(순서·실패·재시도의 동작)는
  RFC-0003이 정의한다"

### 음성 대조

**N1 부재 대조.** 카탈로그 21종에 없는 가짜 kind `FileWrite`를 같은 명령에 넣으면 `0`이다
(위 출력 마지막 행). 이 검사는 임의 문자열을 통과시키지 않는다 — 표에 실제로 존재하는 행만
센다. 6종 중 하나라도 표에서 빠지면 그 행이 `0`으로 나타나 FAIL이 된다.

### 판정

PASS

## C3 — 고수준 패스 불변조건 + dialect 이후 역추적

### 기준

2부 모두 충족해야 PASS.

1. RFC-0004 파이프라인 표의 **S3 행**(`High-level Passes (Semantic IR level)` — 고수준 최적화
   3종이 도는 Semantic IR 레벨 단계)의 보존 불변조건에 `schemas/lir.schema.json` **유효성 보존이
   명시**돼 있다.
2. dialect 변환 이후 단계 **S4·S5·S6·S7 전부**의 불변조건에 IR 노드 id **역추적 보존이 명시**돼
   있다. 4단계 중 하나라도 누락이면 FAIL.

### 명령·출력

```sh
$ grep -cE '^\| S3 `High-level Passes.*lir\.schema\.json' rfcs/0004-compiler.md
1

$ for s in S1 S2 S3 S4 S5 S6 S7; do printf "%s 역추적=%s\n" $s \
    "$(grep -E "^\| $s \`" rfcs/0004-compiler.md | grep -c '역추적')"; done
S1 역추적=0
S2 역추적=0
S3 역추적=0
S4 역추적=1
S5 역추적=1
S6 역추적=1
S7 역추적=1
```

### 근거 인용

**기준 1 (S3의 스키마 유효성).**

- `rfcs/0004-compiler.md:100` — S3 행의 보존 불변조건 원문: "① 출력이 `schemas/lir.schema.json`
  유효 ② 문서 수준 불변식 5종 유지 ③ 노드 id 안정성 ④ Constraint 노드(Policy·Security·
  Performance)의 값 불변. 3개 서브패스 **경계마다 S2를 재실행할 수 있어야 한다** — 이 재실행
  가능성이 ①②의 반증 수단이다"
- 고수준 최적화 3종이 모두 이 불변조건을 상속한다: `:187`(S3-1 Architecture Optimizer),
  `:188`(S3-2 Concurrency Optimizer), `:189`(S3-3 Memory Optimizer) — 세 행 모두 보존
  불변조건 칸이 "S3 불변조건 4개"다.
- 설계 의도: `:60-62` — "세 패스 모두 **Semantic IR 레벨에서** 돌기 때문에, 각 패스 사이에서
  S2를 다시 돌려 IR이 여전히 성립하는지 확인할 수 있다. 이것이 이 단계 설계의 핵심이다 —
  최적화 결과가 여전히 검증 가능한 IR이라는 성질."

**기준 2 (S4~S7의 역추적 보존).**

- `:101` S4 — "IR 노드 id의 **역추적 보존**(아래 §dialect 변환 이후의 역추적). 이 단계부터
  산출물은 JSON이 아니므로 IR 스키마 유효성은 적용 대상이 아니고, **역추적 보존이 그 자리를
  대신하는 불변조건이다**"
- `:102` S5 — "① 역추적 보존 ② RFC-0003 §Execution Model의 관측 가능한 동작 보존"
- `:103` S6 — "① 역추적 보존 ② 관측 가능한 동작 보존"
- `:104` S7 — "① 역추적 보존(디버그 정보 경유 — 포맷은 §Open Questions ④)"
- 판정 문장: `:171-173` — "역추적 요구는 다음 한 문장으로 판정한다: **최종 산출물의 임의
  지점에서 원 IR 노드 id를 최소 1개 이상 얻을 수 있다.**"
- 이중 경로: `:158-162` — "① MLIR 위치 정보(Location) … ② discardable attribute
  `lnpl.node_id`"

### 음성 대조

**N2 분별 대조.** 위 루프 출력이 S1·S2·S3에서 `0`, S4~S7에서 `1`로 **갈린다**. 이 갈림이 검사의
분별력 증거다 — 만약 `역추적`이 7단계 전부에 무조건 적혀 있었다면 "dialect 변환 **이후** 단계에
명시돼 있다"는 판정은 아무것도 판별하지 않는 장식이었을 것이다. 갈림의 근거도 문서에 있다:
S1~S3은 산출물이 JSON IR이라 스키마 유효성이 불변조건이고(`:98-100`), S4부터 형식이 MLIR로
바뀌므로 역추적이 "그 자리를 대신하는 불변조건"이다(`:101`). 즉 두 불변조건은 **상보적으로 배치**돼
있고 검사는 그 경계를 정확히 짚는다.

보강(N1): S3 행의 스키마 유효성 검사도 부재 대조가 성립한다 — S4~S7 행에서 `lir.schema.json`을
찾으면 0건이며(`:101`이 "IR 스키마 유효성은 적용 대상이 아니다"라고 명시), 따라서 기준 1의 검사도
전 단계를 무조건 통과시키지 않는다.

### 판정

PASS

## C4 — `kb.*` = RFC-0005 소비 인터페이스 3종

### 기준

RFC-0006이 싣는 `kb.*` 3종 시그니처가 RFC-0005 §Consumption Interface의 논리 시그니처와
**이름·인자·반환 표기까지 바이트 동일**하고(diff 빈 출력), RFC-0006의 `kb.*` 메서드가 **정확히
3개**여야 한다. 이름이 같아도 인자가 다르거나, 4번째 `kb.*` 메서드가 있으면 FAIL.

### 명령·출력

```sh
$ P='^kb\.(route\(task_description\) -> \[doc_id\]|load\(doc_id\) -> document|verify\(doc_id, version\) -> bool)$'
$ diff <(grep -E "$P" rfcs/0005-knowledge-base.md) <(grep -E "$P" rfcs/0006-agent-protocol.md) && echo IDENTICAL
IDENTICAL

$ grep -cE '^\| `kb\.(route|load|verify)` \|' rfcs/0006-agent-protocol.md
3
```

대조 대상 3행 (양쪽 동일):

```
kb.route(task_description) -> [doc_id]
kb.load(doc_id) -> document
kb.verify(doc_id, version) -> bool
```

위치: `rfcs/0005-knowledge-base.md:142-144` ↔ `rfcs/0006-agent-protocol.md:225-227`.

### 근거 인용

- `rfcs/0005-knowledge-base.md:138-139` — "에이전트가 KB를 읽는 논리 연산은 다음 3종이다. 아래
  시그니처는 **논리 계약**이며, **이 이름과 인자 그대로 상위 RFC들이 참조한다**"
- `rfcs/0005-knowledge-base.md:160-162` — "이 3종의 **전송 표현**(JSON-RPC 메서드명·파라미터
  스키마·오류 코드)은 **RFC-0006 Agent Protocol이 정의한다**. 이 RFC는 논리 시그니처와 의미론만
  소유한다."
- `rfcs/0006-agent-protocol.md:234-236` — 전송 표현 대응 표: `kb.route(task_description) ->
  [doc_id]` → 메서드 `kb.route`, params `{ task_description, _meta }`, result `[doc_id]` /
  `kb.load(doc_id) -> document` → `kb.load`, `{ doc_id, _meta }`, `document` /
  `kb.verify(doc_id, version) -> bool` → `kb.verify`, `{ doc_id, version, _meta }`, `bool`
  — 인자 이름이 논리 시그니처와 일치하고 `_meta`만 봉투 계층으로 추가된다.
- `rfcs/0006-agent-protocol.md:238-240` — "**의미론은 RFC-0005가 소유하며 이 RFC는 재정의하지
  않는다.** 즉 `kb.route`의 빈 목록은 오류가 아니고, 존재하지 않는 `doc_id`는 오류이며,
  `kb.verify`의 `false`는 …"
- `rfcs/0006-agent-protocol.md:147-149` — "메서드는 3개 네임스페이스(`agent.*`, `ir.*`, `kb.*`)의
  **8개로 고정**한다. 새 메서드를 추가하지 않는다" + `:158-160`(kb.* 3행)
- 경계 보존 확인: `rfcs/0006-agent-protocol.md:134-136` — "**`result`의 형태가 이 RFC 밖에서
  정해진 경우에는 반향하지 않는다** — `kb.route`(배열)·`kb.verify`(불리언)·`kb.load`(`document`
  객체)의 result 형태는 RFC-0005가 소유하므로, 거기에 `_meta`를 끼워 넣으면 그 계약이 깨진다."
  즉 RFC-0006은 자기 봉투 규약을 RFC-0005 계약 앞에서 스스로 제한한다.

### 음성 대조

**N1 부재 대조.** 존재하지 않는 4번째 `kb.*` 메서드를 기대하면 양쪽 0건이다:

```sh
$ grep -cE '^kb\.(search|list|write)\(' rfcs/0005-knowledge-base.md rfcs/0006-agent-protocol.md
rfcs/0005-knowledge-base.md:0
rfcs/0006-agent-protocol.md:0
```

**초안 명령의 결함과 교정(기록).** 최초 초안은 `^kb\.(route|load|verify)`로 앵커했는데, 이 패턴은
RFC-0005 §Examples의 호출 예시 2행(`:190` `kb.route("Login 워크플로의 generate token step
구현 …")`, `:215` `kb.verify("security-jwt-issuance", "1.0.0") -> true`)까지 포착해 diff가 비지
않았다. 시그니처 3행 전체를 앵커하는 패턴으로 교체해 `IDENTICAL`을 얻었다. 이 기록을 남기는
이유는, 느슨한 앵커가 "불일치"를 거짓으로 만들어낼 수 있음을 보이기 때문이다 — 명령의 정밀도가
판정의 일부다.

### 판정

PASS

## C5 — 골든 시나리오 관통 (C5a 엄격 / C5b 관점별)

### 기준

**보정 사실 고지 (필수).** 태스크 스펙 원문의 C5는 다음과 같다:

> C5: 골든 시나리오 요소(Entity User, 6 step, Policy 3종, Performance 2종, Event, Capability 3종)가
> **6개 RFC Examples 모두에서 동일 명칭으로 등장**
> — `plans/rfc-suite/tasks/09-cross-consistency-and-roadmap.md:25-26`

이 문자적 판정은 **거짓 FAIL을 만든다**. 근거 둘:

**① 규범 근거 — RFC-0000 §5가 관점별 표현을 규정한다.**

> "모든 RFC의 `## Examples` 섹션은 골든 시나리오 **"Login"**을 사용한다. 정본 정의는
> `plans/rfc-suite/plan.md` §골든 시나리오 "Login" — **참조만 하고 재정의하지 않는다**(사본 발산
> 방지). RFC는 **자기 관점의 표현(문법, IR, 런타임 계약, KB 참조, 에이전트 메시지)으로 같은
> 시나리오를 나타내야 한다**."
> — `rfcs/0000-rfc-process.md:59-62`

즉 6 RFC가 전 요소를 동일 명칭으로 열거하는 것이 규범이 아니다. 규범은 "같은 시나리오를 자기
관점으로" 나타내는 것이다.

**② 실측 근거 — 요소 부재는 결함이 아니라 관점의 결과다.** (`EX()` 범위, 아래 §명령·출력의 전량
표 참조)

| RFC | 관점 | 부재 요소 실측 | 부재의 성격 |
|-----|------|---------------|------------|
| 0003 Runtime | 6 step 실행 타임라인 A/B/C | `User`·`id UUID`·`email Email`·`password Password`·`createdAt DateTime`·`UserCreated` = **각 0회** | 타임라인은 step·정책·관측을 다루므로 Entity를 명명할 필요가 없다 |
| 0005 KB | `generate token` 한 step의 KB 라우팅 | `User`·6 step 중 5개·`retry 3`·`rollback`·`timeout 3s` = **각 0회**, `generate token` **4회**·`jwt` **9회** | KB 소비 흐름만 다루므로 workflow 전체·정책이 등장할 자리가 없다 |

**③ 실측 근거 — 리터럴 판정은 IR 정본 문서를 FAIL시킨다.** RFC-0001 Examples는 IR 필드 표기를
쓰므로 골든 표면 리터럴이 0회다:

> `| policy.login | Policy | rules=[{retry, 3}, {rollback}, {timeout, 3s}] | [] |`
> — `rfcs/0001-semantic-ir.md:257`
> `| perf.login | Performance | budgets=[{response, <50ms}, {cache, 5m}] | [] |`
> — `rfcs/0001-semantic-ir.md:259`

문자열 `retry 3`은 이 문서에 **0회**다(공백 대신 `, `). 리터럴로 판정하면 **IR 정본**(plan.md D1)이
FAIL한다 — 판정 도구의 결함이 정본 문서를 유죄로 만드는 형태다. 따라서 매칭은 표면 표기와 IR
필드 표기를 **모두 수용하는 정규식**으로 한다(아래 매칭 규약).

**따라서 C5를 두 층으로 판정한다.** 소속 표를 **판정 전에** 고정하며, 판정 후 완화하지 않는다.
(●=필수 / —=비대상 / ○=보조 관측·비게이팅)

| 요소 | 0001 | 0002 | 0003 | 0004 | 0005 | 0006 |
|------|:----:|:----:|:----:|:----:|:----:|:----:|
| Entity `User` | ● | ● | — | — | — | — |
| 4필드 `id UUID`/`email Email`/`password Password`/`createdAt DateTime` | ● | ● | — | — | — | — |
| Workflow 6단계 이름 전량 | ● | ● | ● | — | — | ● |
| Policy 3종 `retry 3`/`rollback`/`timeout 3s` | ● | ● | ● | — | — | — |
| Performance 2종 `response < 50ms`/`cache 5m` | ● | ● | ● | — | — | — |
| Event `UserCreated` | ● | ● | — | — | — | — |
| Capability 3종 `postgres`/`redis`/`jwt` | ● | ● | — | — | — | — |
| 노드 id `wf.login.step.1`~`.6` 인용 | — | — | — | ● | — | ● |
| `generate token` step 연결 | — | — | — | — | ● | — |
| (보조·비게이팅) Security `jwt` | ○ | ○ | — | — | — | — |

- **C5a(엄격)** = 0001·0002 열의 ● 전량. 골든 시나리오를 정면으로 다루는 두 RFC이므로 전 요소를
  동일 명칭으로 포함해야 한다.
- **C5b(관점별)** = 0003·0004·0005·0006 열의 ● 전량. 각 RFC의 관점: 0003 = Policy·Performance
  5항목 + 6 step / 0004 = 노드 id 인용 / 0005 = `generate token` 연결 / 0006 = `ir_fragment`의
  노드 id.
- **보조 관측(D8)**: 골든 정본에는 `Security: jwt`도 있으나 브리프 C5a 요소 열거에 포함되지
  않으므로 **게이트를 넓히지 않는다**. 비게이팅 관측 행으로만 기록한다.

**매칭 규약(고정).** `retry,? 3` / `rollback` / `timeout,? 3s` / `response,? *< *50ms` /
`cache,? 5m` / `id,? UUID` / `email,? Email` / `password,? Password` / `createdAt,? DateTime` /
`name ?= ?User|entity User` / `UserCreated` / `postgres` / `redis` / `jwt` / 6 step 이름은 리터럴 /
노드 id는 `wf\.login\.step\.<n>\b`(1~6 **개별** 확인 — 범위 표기 `~`가 개별 인용을 대신하지
못하므로 집계가 아니라 id마다 센다).

### 명령·출력

```sh
$ EX() { awk '/^## Examples/{on=1} /^## Alternatives/{on=0} on' "$1"; }
$ for f in rfcs/000[1-6]*.md; do echo "## $(basename $f)"; for p in <위 매칭 규약의 정규식 전량>; do
    printf "  %-26s %s\n" "$p" "$(EX "$f" | grep -cE -- "$p")"; done; done
```

요소 × RFC 히트 수 (전량 출력):

| 요소 정규식 | 0001 | 0002 | 0003 | 0004 | 0005 | 0006 |
|-------------|-----:|-----:|-----:|-----:|-----:|-----:|
| `name ?= ?User\|entity User` | 2 | 2 | 0 | 0 | 0 | 0 |
| `id,? UUID` | 1 | 2 | 0 | 0 | 0 | 0 |
| `email,? Email` | 1 | 2 | 0 | 0 | 0 | 0 |
| `password,? Password` | 1 | 2 | 0 | 0 | 0 | 0 |
| `createdAt,? DateTime` | 1 | 2 | 0 | 0 | 0 | 0 |
| `validate input` | 1 | 1 | 3 | 0 | 0 | 1 |
| `authenticate` | 1 | 2 | 4 | 0 | 0 | 1 |
| `cache user` | 1 | 1 | 2 | 3 | 0 | 1 |
| `generate token` | 2 | 1 | 1 | 0 | **4** | 6 |
| `audit login` | 2 | 1 | 1 | 4 | 0 | 1 |
| `return token` | 2 | 1 | 1 | 0 | 0 | 1 |
| `retry,? 3` | 1 | 2 | 3 | 2 | 0 | 0 |
| `rollback` | 1 | 2 | 5 | 1 | 0 | 0 |
| `timeout,? 3s` | 1 | 2 | 4 | 3 | 0 | 0 |
| `response,? *< *50ms` | 1 | 2 | 3 | 0 | 0 | 0 |
| `cache,? 5m` | 1 | 2 | 2 | 1 | 1 | 0 |
| `UserCreated` | 1 | 2 | 0 | 0 | 0 | 0 |
| `postgres` | 3 | 2 | 2 | 3 | 0 | 0 |
| `redis` | 3 | 2 | 0 | 5 | 0 | 0 |
| `jwt` (보조) | 5 | 4 | 0 | 2 | 9 | 9 |

노드 id 개별 실측 (C5b의 0004·0006):

```sh
$ for f in rfcs/0004-compiler.md rfcs/0006-agent-protocol.md; do echo "## $(basename $f)";
    for i in 1 2 3 4 5 6; do printf "  wf.login.step.%s  %s\n" $i "$(EX "$f" | grep -cE "wf\.login\.step\.$i\b")"; done; done
## 0004-compiler.md
  wf.login.step.1  4
  wf.login.step.2  7
  wf.login.step.3  8
  wf.login.step.4  3
  wf.login.step.5  7
  wf.login.step.6  3
## 0006-agent-protocol.md
  wf.login.step.1  1
  wf.login.step.2  1
  wf.login.step.3  1
  wf.login.step.4  2
  wf.login.step.5  1
  wf.login.step.6  1
```

**판정 대조.** 소속 표의 ● 칸 전량이 히트 ≥1인가:

| 층 | 대상 | ● 칸 수 | 히트 ≥1 | 결과 |
|----|------|--------:|--------:|------|
| C5a | 0001 (7요소군: Entity·4필드·6step·Policy 3·Perf 2·Event·Cap 3) | 7군 / 개별 20 | 20 | 충족 |
| C5a | 0002 (동일) | 7군 / 개별 20 | 20 | 충족 |
| C5b | 0003 (6step + Policy 3 + Perf 2) | 11 | 11 | 충족 |
| C5b | 0004 (노드 id 6개) | 6 | 6 | 충족 |
| C5b | 0005 (`generate token`) | 1 | 1 (4회) | 충족 |
| C5b | 0006 (6step + 노드 id 6개) | 12 | 12 | 충족 |

### 근거 인용

- `rfcs/0000-rfc-process.md:59-62` — 골든 시나리오 규칙(위 인용). C5 2층 보정의 규범 근거.
- `plans/rfc-suite/plan.md:21-33` — 골든 시나리오 "Login" 정본(요소 목록의 원천).
- `rfcs/0001-semantic-ir.md:242-262` — 19노드 평탄 테이블. `:245`(entity.user 4필드),
  `:247`(wf.login children 6), `:257`(policy.login `{retry, 3}` 등), `:259`(perf.login),
  `:246`(event.user.created), `:260-262`(cap.postgres/redis/jwt).
- `rfcs/0002-syntax.md:512-546` — `.lnpl` 골든 소스 33줄(전 요소 표면 표기) + `:550-559`
  "골든 시나리오 요소 → 소스 대조" 8행 표.
- `rfcs/0003-runtime.md:197-200` — "노드 id는 RFC-0001 Examples의 IR 표를 그대로 인용한다:
  `wf.login.step.1`~`.6`, `policy.login`(retry 3, rollback, timeout 3s), `perf.login`(response
  < 50ms, cache 5m)" + `:290-293` "세 타임라인으로 `policy.login`·`perf.login`의 **5개 항목
  전부** … 의 런타임 의미가 나타난다" — 0003의 관점이 Policy·Performance 5항목 + 6 step임을
  문서 자신이 선언한다.
- `rfcs/0004-compiler.md:319-325` — "인용하는 노드 id는 `examples/login.lir.json`의 실제 값이다:
  `svc.login`, `entity.user`, `wf.login`, `wf.login.step.1`~`wf.login.step.6` …" — 0004의 관점이
  노드 id 인용임을 선언한다.
- `rfcs/0005-knowledge-base.md:186-187` — "**흐름 — Coder 에이전트가 `generate token` step을
  구현한다.**" — 0005의 관점이 한 step의 KB 라우팅임을 선언한다.
- `rfcs/0006-agent-protocol.md:497-503` — "노드 id는 `examples/login.lir.json`의 실제 값을
  인용한다. 파이프라인 1사이클: Planner가 Login intent를 받아 … Reviewer가 승인" — 0006의 관점이
  에이전트 메시지에 실린 `ir_fragment` 노드 id임을 선언한다.

즉 C5b의 4개 RFC는 각자 자기 관점을 Examples 서두에 **명시**하고 있고, 소속 표는 그 선언을
그대로 기준으로 채택한 것이다 — 판정 후에 만든 사후 변명이 아니다.

### 음성 대조

**N1 부재 대조(필수).** 골든 정본에 **없는** 요소 3종을 같은 명령에 넣으면 전 6 RFC Examples에서
0건이다:

```sh
$ for p in 'capability kafka' 'timeout,? 9s' 'entity Order'; do echo "-- $p";
    for f in rfcs/000[1-6]*.md; do printf "   %-28s %s\n" "$(basename $f)" "$(EX "$f" | grep -cE -- "$p")"; done; done
-- capability kafka
   0001-semantic-ir.md          0
   0002-syntax.md               0
   0003-runtime.md              0
   0004-compiler.md             0
   0005-knowledge-base.md       0
   0006-agent-protocol.md       0
-- timeout,? 9s
   0001-semantic-ir.md          0
   0002-syntax.md               0
   0003-runtime.md              0
   0004-compiler.md             0
   0005-knowledge-base.md       0
   0006-agent-protocol.md       0
-- entity Order
   0001-semantic-ir.md          0
   0002-syntax.md               0
   0003-runtime.md              0
   0004-compiler.md             0
   0005-knowledge-base.md       0
   0006-agent-protocol.md       0
```

18칸(3 문자열 × 6 RFC) 전부 0. 요약하지 않고 전량을 싣는 이유는, 요약이 "일부만 확인하고
나머지를 추정한 것"과 구분되지 않기 때문이다.

세 문자열은 각각 골든에 없는 **capability**(kafka) · 골든과 다른 **값**(9s vs 3s) · 골든에 없는
**Entity**(Order)를 겨냥한다. 만약 이 중 하나라도 히트했다면, 위 요소 검사는 "아무 문자열이나
통과시키는" 검사라는 뜻이므로 C5 판정 전체가 무효였다. 특히 `timeout,? 9s`가 0인 것은 매칭
규약의 `,?` 완화가 **값 자체를 느슨하게 만들지 않았음**을 보인다 — 완화는 구분자(`,`/공백)에만
적용되고 값(`3s`)은 여전히 정확히 대조된다.

**검증 기준의 자기 교정(기록).** 이 절의 음성 대조를 파일 전역 grep으로 검사하려던 최초 기준은
결함이 있었다 — §0.의 N1 정의 행이 예시로 `capability kafka`를 언급하므로 전역 grep이 항상 ≥1을
낸다(실측 1건, `docs/CONSISTENCY-CHECK.md:37`). 기준을 **C5 절 스코프로 좁혀 강화**했다
(`awk '/^## C5 — /{on=1} /^## C[6-9] — |^## 수정한/{on=0} on'`). 느슨한 검사가 자기 문서의
설명 문장을 증거로 오인하는 형태였고, 이를 완화가 아니라 스코프 축소로 고쳤다.

### 판정

C5a: PASS
C5b: PASS

## C6 — GLOSSARY 10 용어의 재정의 부재

### 기준

`docs/GLOSSARY.md`의 10 용어가 어느 RFC에서도 **다른 의미로 재정의되지 않아야** 한다.
용어 언급 횟수는 판정 근거가 아니다 — 각 용어에서 "이것이 어긋나면 재정의"인 **판별 속성**
1개를 뽑아 그것만 본다. 판별 속성 표를 판정 전에 고정한다:

| # | 용어 | 판별 속성 (GLOSSARY 정본) | 어긋남의 형태 |
|---|------|--------------------------|---------------|
| 1 | Intent | 개발자가 작성하는 **유일한 입력**이며 How가 아니라 What | RFC가 Intent를 구현 방법 기술로 서술 |
| 2 | Semantic IR | AST를 **대체**하는 의미 중심 IR이자 **설계 허브** | IR을 구문 트리/AST로 서술, 또는 허브를 다른 문서로 이전 |
| 3 | Semantic Type | 원시 최소화 + validation rule 내장, 확장은 **refinement만** | 새 원시 타입 창설 허용 서술 |
| 4 | Capability | 능력 단위 선언, **구현체는 Compiler가 자동 선택** | 개발자가 구현체를 지정한다는 서술 |
| 5 | Workflow | **순서가 고정된** 단계열 | 순서 무의미·집합으로 서술 |
| 6 | Policy | 제약으로 **선언**하고 적용 방법은 컴파일러·런타임이 결정 | Policy 값을 최적화가 변경, 또는 Policy를 실행 코드로 서술 |
| 7 | Knowledge Base (KB) | **모든** Agent가 **동일한** KB를 공유 | 에이전트별 개별 KB 허용 서술 |
| 8 | Agent Pipeline | Planner→…→Release Agent **9종 체인**, 동일 KB·IR 공유 | 다른 역할 구성·개수로 재정의 |
| 9 | Lowering | **의미를 보존하며** 낮은 표현으로, 2층위(문법→IR / IR→dialect→LLVM→Native) | 의미 변경을 허용하는 **재정의** |
| 10 | LNPL | 표면 언어 **워킹네임**, 확장자 `.lnpl` | 다른 언어명·확장자 사용 |

기계 검사 2종을 함께 통과해야 한다: **A** 각 RFC가 GLOSSARY 재정의 금지를 명시(7파일 전부 ≥1),
**B** LNPL을 언급하는 RFC의 **첫 언급**에 `워킹네임` 표기(RFC-0000 §4 의무).

### 명령·출력

**기계 검사 A — 인용 준수.**

```sh
$ grep -c '재정의하지 않는다' rfcs/000[0-6]*.md
rfcs/0000-rfc-process.md:1
rfcs/0001-semantic-ir.md:2
rfcs/0002-syntax.md:1
rfcs/0003-runtime.md:1
rfcs/0004-compiler.md:3
rfcs/0005-knowledge-base.md:2
rfcs/0006-agent-protocol.md:2
```

7파일 전부 ≥1. 최소값 1(0000·0002·0003), 최대 3(0004).

**기계 검사 B — LNPL 첫 언급의 워킹네임 표기.**

```sh
$ for f in rfcs/000[1-6]*.md; do n=$(grep -c 'LNPL' "$f"); first=$(grep -n 'LNPL' "$f" | head -1)
    printf "%-30s 총%s회  첫언급: %s\n" "$(basename $f)" "$n" "${first:-（0회 — 의무 미발동）}"; done
0001-semantic-ir.md            총1회  첫언급: 15:… 표면 언어 LNPL(워킹네임,
0002-syntax.md                 총4회  첫언급: 10:… LNPL(워킹네임 — RFC-0000 §4,
0003-runtime.md                총1회  첫언급: 31:LNPL(워킹네임, RFC-0000 §4)로 개발자가 선언하는 것은 …
0004-compiler.md               총1회  첫언급: 47:언어명 **LNPL**(워킹네임 — RFC-0000 §4)로 작성된 소스 …
0005-knowledge-base.md         총0회  첫언급: （0회 — 의무 미발동）
0006-agent-protocol.md         총1회  첫언급: 48:LNPL(워킹네임 — `rfcs/0000-rfc-process.md` §4)의 …
```

**공허한 PASS를 통과로 세지 않는다.** RFC-0005는 LNPL 언급이 **0회**이므로 RFC-0000 §4의 의무가
애초에 발동하지 않는다. 이 항목은 **미발동(vacuous)**이며 **준수의 증거가 아니다** — 5개 RFC
(0001·0002·0003·0004·0006)만 실제 준수를 증명한다. 위키 `tests-that-cannot-fail.md`의 Edge case
행("의도적으로 outcome assertion이 없는 항목은 그렇다고 이름을 붙여 리뷰어가 커버리지로 세지
않게 한다")의 적용이다.

**용어별 원문 대조** (판별 속성 ↔ RFC 용법):

| # | 용어 | 대조한 RFC 원문 | 판정 |
|---|------|----------------|------|
| 1 | Intent | `0001:32-40` "개발자는 코드를 쓰지 않고 의도를 선언한다 … 구현 방법 — 어떤 라이브러리로 JWT를 만들지 … 는 IR에 없다. 그것은 선언된 Capability와 제약을 보고 컴파일러가 결정한다" | 일치 |
| 2 | Semantic IR | `0001:9-18` "LNPP는 AST를 버린다 … Semantic IR은 플랫폼의 설계 허브다(plan.md D1)"; `0002:11-13` "모든 문법 구성은 Semantic IR 노드로 lowering되는 표기일 뿐"; `0004:16-19` 두 상류 위임 인용 | 일치 (허브 이전 없음) |
| 3 | Semantic Type | `0001` "**사용자 정의 타입은 refinement만 허용한다** … 새 원시 타입의 창설은 금지한다"(문장 유지); `0002` §Lexical 타입명 항은 `TypeName`을 `BaseTypeName`(18종 닫힌 열거) + `RefinedTypeName`(PascalName)의 합으로 적는다 — 2026-08-04 개정 | 일치 (base 표는 18행 그대로이고 19번째 원시 타입 행이 없다. refinement는 `Refinement` 노드라는 별도 kind이지 19번째 Semantic Type이 아니다. 18종 제한은 이제 문법이 아니라 IR 쪽 `base` enum과 이름 해소 패스가 강제한다 — RFC-0001 부록 A.6.1·A.7 ⓐ) |
| 4 | Capability | `0004:187`(S3-1) "capability 구현체 선택 … 자동 생성물 산출 지점"; `0002:223` `database` 절은 `CapabilityName` 참조일 뿐 구현체 지정이 아니다; `0002:226-228` "정책·보안·성능 어휘가 닫힌 열거인 것은 RFC-0001 Constraint 카탈로그(consume-only)의 귀결이다" | 일치 (구현체 선택 주체 = 컴파일러) |
| 5 | Workflow | `0003:74-77` "Workflow의 `children` 배열 순서(RFC-0001 구조 규칙 3)가 **실행 순서**다"; `0001:78-80` 구조 규칙 3 "순서 유의미"; `0002:469-471` "workflow 6단계는 소스 28~33행과 … **순서까지 1:1**로 대응한다" | 일치 |
| 6 | Policy | `0004:131-132`(M4) "단 Constraint 노드(Policy·Security·Performance)의 값은 제외한다. **제약은 최적화의 입력이며 대상이 아니다**"; `0003:100-103` Constraint의 런타임 의미; `0004:199`(B2) "어느 패스도 그 값을 변경하지 않는다" | 일치 (값 불변이 명문화) |
| 7 | Knowledge Base | `0005:9-12` "모든 AI Agent는 동일한 KB를 사용한다"; `0006:101-105` "**읽기가 9역할 전부 `전체`인 것은 누락이 아니라 결정이다** … 읽기를 좁히면 … Charter가 IR 공유로 막으려던 바로 그 발산이다" | 일치 |
| 8 | Agent Pipeline | `0006:80-84` "역할은 Charter §AI Pipeline의 **9종**으로 고정한다. 행 순서는 파이프라인 순서와 같다" + `:89-99`(9행 표, 실측 9행). 표기 정규화(`Performance Analyzer` → `PerformanceAnalyzer`)는 `:81-84`에서 **명시적으로 선언**되며 RFC-0001의 `WorkflowStep` 정규화와 같은 규칙임을 밝힌다 | 일치 (개수·순서 동일, 표기 정규화는 선언된 것) |
| 9 | Lowering | `0002:11-13`·`0002:333-338`(부록 A "충돌 시 IR이 정본"); `0004:30-35`(D18 progressive lowering). **어느 RFC도 Lowering을 "의미 변경 허용"으로 재정의하지 않는다** — 대신 RFC-0002가 자기 매핑이 **부분사상**임을 등재한다(아래 인접 발견 ②) | 일치 (재정의 없음) |
| 10 | LNPL | 위 기계 검사 B의 5개 RFC 첫 언급. 확장자 `.lnpl` 외 표기 없음 | 일치 |

### 근거 인용

- `rfcs/0000-rfc-process.md:11-12` — "정본 관계: `CHARTER.md`는 0단계 비전 문서 … 정본 설계는
  `rfcs/`의 RFC들이다. **용어 정의의 정본은 `docs/GLOSSARY.md`**."
- `rfcs/0000-rfc-process.md:52-55`(§4) — "언어 워킹네임은 **LNPL**(소스 확장자 `.lnpl`)이다.
  추후 개명 가능성이 있으므로 **각 RFC 본문에서 언어명을 처음 언급할 때 워킹네임임을 명시한다**."
- `docs/GLOSSARY.md:3-5` — "Charter와 모든 RFC가 공유하는 용어의 정의 정본."
- 재정의 금지의 명시 예: `rfcs/0001-semantic-ir.md:55-56` "용어의 정의 정본은 `docs/GLOSSARY.md`
  이며 이 문서는 재정의하지 않는다" / `rfcs/0005-knowledge-base.md:11-12` "용어 정의의 정본은
  `docs/GLOSSARY.md`의 "Knowledge Base (KB)" 항목이며 이 RFC는 그 정의를 참조만 하고 재정의하지
  않는다" / `rfcs/0006-agent-protocol.md:238` "의미론은 RFC-0005가 소유하며 이 RFC는 재정의하지
  않는다".
- 축 분리를 명시한 예(재정의로 오인되기 쉬운 지점): `rfcs/0005-knowledge-base.md:65` — KB 문서의
  `status`가 "**KB 문서의 상태 축이며 RFC 수명주기(Draft/Review/Accepted/Superseded)와는 별개
  축이다**". 같은 낱말(`status`)이지만 GLOSSARY 10 용어가 아니고, 문서가 스스로 축을 갈라 놓았다.

### 음성 대조

**N1 부재 대조.** GLOSSARY에 없는 가짜 용어를 정본처럼 찾으면 전 파일 0건이다:

```sh
$ grep -c 'Semantic Graph\|Intent IR' rfcs/000[0-6]*.md docs/GLOSSARY.md
rfcs/0000-rfc-process.md:0   rfcs/0001-semantic-ir.md:0   rfcs/0002-syntax.md:0
rfcs/0003-runtime.md:0       rfcs/0004-compiler.md:0      rfcs/0005-knowledge-base.md:0
rfcs/0006-agent-protocol.md:0   docs/GLOSSARY.md:0
```

**N3 반전 대조.** 재정의를 **긍정으로 선언한** 문장을 찾으면 0건이다:

```sh
$ grep -nE '(용어|정의)를? 재정의한다|여기서 다시 정의한다' rfcs/000[0-6]*.md
(출력 없음 — exit 1, 0건)
```

두 대조가 함께 성립해야 판정이 의미를 갖는다: N1은 "정본에 없는 용어를 정본으로 취급하지
않는다"를, N3은 "재정의 선언이 실제로 없다"를 각각 보인다. 다만 **N3만으로는 부족하다** —
문장이 "재정의한다"고 말하지 않으면서 실질적으로 다른 의미를 쓰는 경우를 잡지 못하기 때문이다.
그 부류를 잡는 것이 위 §명령·출력의 **용어별 원문 대조 10행**이며, 그 대조에서 실제로 인접
발견 2건이 나왔다(아래) — 즉 이 판정은 항상 PASS를 내는 장식이 아니다.

### 인접 발견 (등재만 — 이 태스크는 수정하지 않는다)

용어 대조 과정에서 C6 자체를 FAIL시키지는 않지만 교차 모호성으로 남는 2건을 등재한다.
defect clustering 원칙(발견된 결함은 그 부류의 첫 사례로 취급하고 이웃을 훑는다)의 적용이다.

**① 무수식 `Pipeline`의 3의미.**

```sh
$ for f in rfcs/000[1-6]*.md; do printf "%-30s Pipeline=%s 파이프라인=%s\n" "$(basename $f)" \
    "$(grep -c 'Pipeline' $f)" "$(grep -c '파이프라인' $f)"; done
0001-semantic-ir.md   Pipeline=5  파이프라인=1
0002-syntax.md        Pipeline=11 파이프라인=0
0003-runtime.md       Pipeline=0  파이프라인=1
0004-compiler.md      Pipeline=1  파이프라인=6
0005-knowledge-base.md Pipeline=0 파이프라인=1
0006-agent-protocol.md Pipeline=2 파이프라인=7
```

세 의미가 공존한다: ⓐ IR 노드 kind `Pipeline`(Behavior, 데이터 흐름 순서 —
`rfcs/0001-semantic-ir.md:113`) ⓑ 컴파일 파이프라인 S1~S7(`rfcs/0004-compiler.md:89-104`)
ⓒ GLOSSARY의 `Agent Pipeline`(9 에이전트 체인 — `docs/GLOSSARY.md:68`).

**판정: C6 FAIL 아님.** GLOSSARY가 정의한 용어는 수식어를 포함한 `Agent Pipeline`이고, ⓐⓑ는
그 용어의 재정의가 아니라 **다른 용어**다. 다만 무수식 `Pipeline`이 문맥에 따라 3의미인 것은
독자에게 모호하다.
**해소 소유자**: `docs/GLOSSARY.md` 개정(무수식 `Pipeline` 사용 금지 또는 3의미 명시).
**인용 위치**: ROADMAP에 Phase 리스크로 올릴 만한 구현 영향은 없으므로 등재만 한다.

**② Lowering의 "의미 보존"과 A.4-① 가드 소실의 긴장.**

GLOSSARY `Lowering`은 "상위 표현을 **의미를 보존하며** 더 낮은 수준의 표현으로 변환하는 것"
(`docs/GLOSSARY.md:78`)이다. 그런데 RFC-0002 부록 A.4-①은 이렇게 등재한다:

(아래 인용은 **당시의** A.4-① 원문이다 — 인용이므로 원문을 보존한다. 그 뒤
`Guard` 신설로 ①이 해소됐고, 2026-08-04 `Refinement` 신설로 카탈로그는 **21종**이
됐다. 즉 인용 안의 "19종"은 인용 시점의 값이며 현재 값이 아니다.)

> "`when`·`repeat`·`until` 가드와 `Condition`에 대응하는 IR kind가 없다(카탈로그 19종).
> RFC-0003도 가드의 실행 의미를 규정하지 않는다. **결과: 가드는 lowering에서 소실되고 피가드
> 항목만 노드가 된다**"
> — `rfcs/0002-syntax.md:488`

즉 가드 구문에 대해서는 문법→IR lowering이 의미를 보존하지 못한다. RFC-0002는 이 사실을
`:473`에서 "문법 → IR이 **부분사상**임을 보이는 지점"으로 명시한다.

**판정: C6 FAIL 아님.** RFC-0002는 Lowering을 "의미 변경 허용"으로 **재정의하지 않았다** —
반대로 자기 매핑의 불완전성을 해소 소유자와 함께 공백으로 등재했다(감추지 않았다). C6가 보는
것은 용어의 재정의이고, 이것은 매핑의 미해소다.
**해소 소유자**: A.4-①이 지정한 `RFC-0001 개정(조건·가드 kind 신설) + RFC-0003(평가 의미)`.
**인용 위치**: ROADMAP Phase 1 리스크(A.4-① — 문법 전량 파서 구현 시 부딪힌다).

### 판정

PASS

## C7 — `validate_ir.py --self-test` exit 0

### 기준

`python3 scripts/validate_ir.py --self-test`가 exit 0으로 종결하고, 출력에 positive 1건 통과와
**negative 3건 REJECTED**가 모두 나타나야 한다. exit 0이지만 negative가 REJECTED되지 않으면
(=고의로 깨뜨린 문서를 통과시키면) 이 검증은 실패할 수 없는 검증이므로 FAIL로 판정한다.

### 명령·출력

```sh
$ python3 scripts/validate_ir.py --self-test; echo "EXIT=$?"
PASS (positive): examples/login.lir.json validates
REJECTED (negative): required field removed: wf.login.name
REJECTED (negative): undefined kind injected: Foo
REJECTED (negative): undefined extra field injected: svc.login.extra
self-test: OK (1 positive passed, 3 negatives rejected)
EXIT=0
```

출력 5행 + exit code. 마지막 요약행(`self-test: OK …`)이 positive 1 / negative 3의 집계를
스크립트 자신이 확인한 것이다.

### 근거 인용

- `rfcs/0001-semantic-ir.md:185-187`(부록 A.1) — "정본 스키마는 `schemas/lir.schema.json`
  (JSON Schema draft 2020-12)이다. 골든 예제는 `examples/login.lir.json`, 실행 가능한 검증기는
  `scripts/validate_ir.py`(단일 문서 검증 + `--self-test`)다."
- `rfcs/0001-semantic-ir.md:229-234`(부록 A.7) — "JSON Schema는 노드 단위 구조·타입 … 만
  검증한다. 문서 수준 불변식 — id 유일성, dangling 참조 금지 … 은 스키마 표현 범위 밖이며,
  컴파일 파이프라인의 검증 패스(RFC-0004 계열)가 소유한다. `scripts/validate_ir.py`는 스키마
  검증까지만 수행한다." — 즉 exit 0의 의미 범위는 스키마 검증까지이며, 문서 수준 불변식 5종은
  RFC-0004 S2 소유다(C3에서 확인).
- `plans/rfc-suite/plan.md` D6 — "각 RFC는 '실패 가능한 검증'을 가져야 함: IR은 스키마 검증
  스크립트(**부정 케이스 포함**)"
- `plans/rfc-suite/plan.md` 수용 기준 3 — "IR 골든 예제가 JSON Schema 검증 스크립트를 통과하고,
  **고의로 깨뜨린 예제는 실패함**(검증이 실패할 수 있음을 증명)"

### 음성 대조

이 항목의 음성 대조는 **스크립트가 자체 내장**한다(N3 반전 대조의 자동화 형태). 위 출력의
`REJECTED (negative)` 3행이 각각 다른 파괴 방식으로 red를 확인한다:

| negative | 파괴 방식 | 무엇을 증명하는가 |
|----------|----------|------------------|
| `required field removed: wf.login.name` | 필수 필드 제거 | 스키마의 `required` 강제가 실효함 |
| `undefined kind injected: Foo` | 카탈로그 21종 밖 kind 주입 | `anyOf` 21분기 판별이 실효함 |
| `undefined extra field injected: svc.login.extra` | 미정의 추가 필드 주입 | `additionalProperties: false`가 실효함 |

3건이 전부 REJECTED이고 positive 1건이 통과했으므로, 이 검증기는 통과와 실패를 실제로 분별한다.
만약 3건 중 하나라도 통과했다면 exit 0이어도 C7은 FAIL이다.

### 판정

PASS

## C8 — Heap 프리미티브 런타임 계약 공백 (스위트 수준)

> 오케스트레이터 신설 항목. 이것은 문서 하나의 결함이 아니라 **스위트 수준 공백**이므로 개별
> RFC가 아니라 이 태스크가 소유한다.

### 기준

RFC-0004는 값 배치 대상으로 **Heap**을 선택하는데, 그 선택이 전제하는 **heap 프리미티브의
런타임 계약**(할당·해제 책임, 수명 종료 시점)이 어느 RFC에도 존재하지 않는지 확인한다.
공백이 존재하면 해소 경로를 **(a) 등재만** 또는 **(b) RFC-0004 최소 수정** 중 하나로 결정해
기록한다. "발견되지 않은 것처럼" 넘기면 FAIL.

**판정 문장의 정밀도 요건(중요).** "RFC-0003에 heap 언급이 0건"이라고 쓰지 않는다 — 실측하면
heap은 §Memory Model 산문에 **2회 등장**하므로 그 서술은 즉시 반박된다. 정확한 사실은
"**런타임 프리미티브 계약 표가 arena·pool 2행뿐이고 heap 행이 없다**"이며, 산문의 2회는 모두
*컴파일러가 선택한다*는 **위임 문장**이다.

### 명령·출력

**① RFC-0003 §Memory Model의 런타임 프리미티브 계약 표 = 2행 (heap 행 없음)**

```sh
$ awk '/^### Memory Model/{on=1} /^### Observability/{on=0} on' rfcs/0003-runtime.md \
    | grep -nE '^\| \*\*[a-z]+\*\* \|'
10:| **arena** | workflow 실행 1회당 하나 생성된다. 수명 = **workflow 실행 수명**: …
11:| **pool** | capability 커넥션(postgres·redis 등) 전용 자원 풀. ① 크기는 …

$ (같은 범위) | grep -cE '^\| \*\*[a-z]+\*\* \|'
2

$ for p in arena pool heap stack; do printf "  계약표 %s 행: %s\n" "$p" \
    "$(awk '/^### Memory Model/{on=1} /^### Observability/{on=0} on' rfcs/0003-runtime.md \
      | grep -cE "^\| \*\*$p\*\* \|")"; done
  계약표 arena 행: 1
  계약표 pool 행: 1
  계약표 heap 행: 0
  계약표 stack 행: 0
```

**② 같은 절의 heap 산문 언급 2회 — 둘 다 위임 문장이다**

```sh
$ awk '/^### Memory Model/{on=1} /^### Observability/{on=0} on' rfcs/0003-runtime.md | grep -niE 'heap'
3:개발자는 메모리를 다루지 않는다(CHARTER §Memory Model — Stack/Heap/Arena/
14:pool"이라는 전제 위에서 Stack/Heap 승격·탈출 분석을 수행할 수 있다. 그 결정
```

원문(`rfcs/0003-runtime.md:142-145`, `:152-154`):

> "개발자는 메모리를 다루지 않는다(CHARTER §Memory Model — Stack/Heap/Arena/Pool은 컴파일러가
> 자동 선택). 이 절은 그 선택이 전제할 수 있도록 **런타임이 제공해야 하는 프리미티브 2종의
> 계약만** 정의한다. **어떤 값을 어느 배치로 보낼지의 선택 알고리즘은 RFC-0004 소유다** — 이
> 문서는 관여하지 않는다."
>
> "이 두 계약이 있으면 컴파일러는 "step 간 전달 값은 arena, capability I/O는 pool"이라는 전제
> 위에서 Stack/Heap 승격·탈출 분석을 수행할 수 있다. 그 결정 자체(escape analysis, 배치 선택)는
> RFC-0004의 최적화 패스가 소유한다."

두 문장 모두 **배치 선택 권한을 RFC-0004로 넘기는 위임**이고, heap 프리미티브가 무엇을 보장하는지
(누가 해제하는가, 언제 수명이 끝나는가)는 규정하지 않는다.

**③ RFC-0004는 Heap을 배치 대상으로 선택한다**

```sh
$ grep -nE '^\| \*\*(Stack|Arena|Heap|Pool)\*\* \|' rfcs/0004-compiler.md
240:| **Stack** | …탈출이 **없음이 확증된** 값만 해당한다 |
241:| **Arena** | step 경계를 넘어 흐르는 중간 값 — **기본 배치**다 …(RFC-0003 arena 계약) |
242:| **Heap** | workflow 실행 수명(= arena 수명)을 넘겨 생존해야 하는 값 … |
243:| **Pool** | capability 커넥션 … operation당 1회 획득, 다른 자원 획득 전 반환(RFC-0003 — 중첩 획득 금지) |
```

**공백의 정확한 형태.** Arena 행은 RFC-0003 arena 계약을, Pool 행은 RFC-0003 pool 계약을 각각
인용한다. **Heap 행만 인용할 상류 계약이 없다** — 그런데 Heap이 담당하는 값은 정의상 arena의
일괄 해제를 넘겨 생존하므로, arena 계약이 그 값의 수명을 덮지 못한다. 따라서 heap 값의
할당·해제 책임과 수명 종료 시점을 규정한 계약이 **어느 RFC에도 없다**.

### 근거 인용

- `rfcs/0003-runtime.md:143-145` — "**런타임이 제공해야 하는 프리미티브 2종의 계약만** 정의한다"
  (2종 = arena·pool, 명시적 한정)
- `rfcs/0003-runtime.md:149`(arena 계약) — "수명 = **workflow 실행 수명**: 실행 시작 시 생성되고,
  실행 종결 시 — 성공·실패·취소를 불문하고 — 일괄 해제된다"
- `rfcs/0003-runtime.md:150`(pool 계약) — "① 크기는 다운스트림 용량 기준 … ② bounded — 고갈 시
  … fail-fast로 거부한다 ③ 획득은 operation당 1회, 다른 자원 획득 전 반환"
- `rfcs/0004-compiler.md:242`(수정 전 원문) — "workflow 실행 수명(= arena 수명)을 **넘겨
  생존해야 하는** 값. 소유권이 외부 계층으로 이전되는 값, 비동기 발행 이후에도 읽히는 페이로드가
  해당한다" — arena 수명을 넘긴다고 스스로 규정하므로 arena 계약으로 덮이지 않는다
- `rfcs/0004-compiler.md:251` — "workflow 종결 이후에도 읽히면 **Heap**"
- `rfcs/0004-compiler.md:232-236` — "런타임이 제공하는 프리미티브 **2종(arena·pool)**의 계약은
  RFC-0003 §Memory Model이 소유하며 이 문서는 인용만 한다" — RFC-0004 자신도 상류가 2종뿐임을
  알고 있으면서 4번째 배치로 Heap을 쓴다. 이 비대칭이 공백의 위치를 정확히 가리킨다
- `CHARTER.md:208` — "Compiler가 Stack, Heap, Arena, Pool을 **자동 선택**한다" — Charter는 4종을
  말하지만 RFC-0003이 계약화한 것은 2종이다. 즉 Charter→RFC 구체화 과정에서 2종이 계약 없이 남았다
- **Stack과의 구분**: Stack도 계약 표에 없으나(위 ① 출력 `stack 행: 0`) Stack은 대상 ABI가
  제공하는 배치이므로 별도 런타임 프리미티브를 요구하지 않는다. **heap만 할당자와 해제 정책을
  요구한다** — 이 구분이 없으면 "계약 표에 없는 2개"를 같은 문제로 뭉개게 된다

### 음성 대조

**N2 분별 대조.** 같은 검사가 arena·pool에서는 계약을 **찾아낸다**(각 1행, 위 ① 출력). 즉
"프리미티브에 런타임 계약이 있는가"라는 이 검사는 실제로 판별한다 — 2/3이 있고 heap만 없다.
검사가 무조건 0을 내는 형태였다면 공백 주장 자체가 무의미했을 것이다.

**N1 부재 대조 + 오탐 배제.** 위 근거의 Stack 구분이 이 항목의 오탐 배제다: "계약 표에 없다"는
사실만으로 공백을 주장하면 Stack도 공백이 되지만, Stack은 런타임 프리미티브를 요구하지 않으므로
공백이 아니다. 판정은 "표에 없음"이 아니라 "**표에 없으면서 런타임 보장을 요구함**"으로 좁혀졌다.

**N3 반전 대조.** 반대 가설 — "heap 계약이 실은 다른 RFC에 있다" — 를 전수 검색으로 기각한다:

검사 범위는 `rfcs/` + `CHARTER.md`다 — `docs/`는 제외한다. **이 문서 자신과 `docs/ROADMAP.md`가
heap을 논하므로 포함하면 자기 참조로 히트한다**(실측: `docs/CONSISTENCY-CHECK.md` 45회,
`docs/ROADMAP.md` 3회). 자기 참조는 "다른 RFC에 heap 계약이 있는가"라는 질문의 답이 될 수 없다.

```sh
$ grep -n 'Heap\|heap' rfcs/000[1-6]*.md CHARTER.md
rfcs/0003-runtime.md:142   (위임 문장)
rfcs/0003-runtime.md:153   (위임 문장)
rfcs/0004-compiler.md:189  (S3-3 결정 대상 열거)
rfcs/0004-compiler.md:234  (2종 인용 선언)
rfcs/0004-compiler.md:242  (배치 표 Heap 행)
rfcs/0004-compiler.md:251  (판정 근거)
rfcs/0004-compiler.md:261  (층위 구분)
rfcs/0004-compiler.md:282  (동등성 비대상 목록)
rfcs/0004-compiler.md:398  (Examples — 해당 없음)
CHARTER.md:208             (4종 자동 선택 — 비전 문서)
```

전 스위트에서 heap 언급 10곳 중 **런타임 계약을 규정한 곳은 0곳**이다. RFC-0001·0002·0005·0006에는
언급조차 없다(런타임 관심사가 아니므로 정상).

### 해소 경로 결정

**선택: (b) — RFC-0004 Heap 행에 한정 표기를 최소 추가 + 등재 + ROADMAP 리스크 인용(3중).**

(a)(등재만, RFC 무수정)를 택하지 않은 사유 3개:

1. **스위트 선례가 (b)다.** RFC-0002 부록 A.4는 미해소 lowering 공백 8항을 **문서 자체에**
   등재하며 그 가치를 이렇게 밝힌다 — "아래 8항은 이 부록이 해소하지 못한 항목이며 각각 해소
   소유자를 명시한다. **공백을 감추지 않는 것이 이 표의 검증 가치다**(plan.md D6)"
   (`rfcs/0002-syntax.md:483-484`). 같은 성질의 공백을 다른 방식으로 다루면 스위트 안에서 규약이
   갈린다.
2. **plan.md D6** — "각 RFC는 '실패 가능한 검증'을 가져야 함". 공백이 그 RFC를 읽는 사람에게
   보이지 않으면, 그 RFC의 검증은 공백을 통과시킨다.
3. **(a)만 택하면 검사가 통과로 위장된다.** Phase 1 구현자는 `rfcs/0004-compiler.md`를 읽고
   구현한다. 수정하지 않으면 Heap 행이 **완결된 계약처럼** 읽히고, 공백은 별도 감사 문서
   (이 파일) 안에서만 존재한다. 위키 `tests-that-cannot-fail.md`가 경고하는 형태 — 문제가
   없어 보이는 것과 문제가 없는 것의 혼동 — 그대로다.

**(b)는 (a)를 배제하지 않는다.** 세 곳에 함께 남긴다: ① RFC-0004 본문(수정) ② 이 문서(등재)
③ `docs/ROADMAP.md` Phase 1 리스크(R6).

**적용한 수정** — `rfcs/0004-compiler.md:242` 배치 표 Heap 행 1행 교체. 기존 배치 규칙은 그대로
보존하고 한정 표기만 덧붙였다(배치 분류 자체는 변경하지 않았다):

> | **Heap** | workflow 실행 수명(= arena 수명)을 넘겨 생존해야 하는 값. 소유권이 외부 계층으로
> 이전되는 값, 비동기 발행 이후에도 읽히는 페이로드가 해당한다. **단 heap 프리미티브 자체의
> 런타임 계약(할당·해제 책임, 수명 종료 시점)은 v0.1에서 미정이다** — RFC-0003 §Memory Model은
> 런타임이 제공하는 프리미티브를 arena·pool 2종만 계약으로 정의한다. 이 행은 **배치 분류만**
> 규정하며, heap 프리미티브의 런타임 계약은 RFC-0003 소유의 미해소 항목이다
> (`docs/CONSISTENCY-CHECK.md` C8) |

수정 후 검증:

```sh
$ git diff --numstat rfcs/0004-compiler.md
1	1	rfcs/0004-compiler.md

$ grep -c 'CONSISTENCY-CHECK' rfcs/0004-compiler.md
1

$ grep -c '^- Status: Draft' rfcs/0004-compiler.md
1

$ python3 scripts/validate_ir.py --self-test; echo "EXIT=$?"
PASS (positive): examples/login.lir.json validates
REJECTED (negative): required field removed: wf.login.name
REJECTED (negative): undefined kind injected: Foo
REJECTED (negative): undefined extra field injected: svc.login.extra
self-test: OK (1 positive passed, 3 negatives rejected)
EXIT=0
```

1행 삽입 / 1행 삭제 — 최소 수정이 지켜졌고, Status는 `Draft` 유지, 스키마·골든 예제에 회귀 없음.

**해소 소유자**: RFC-0003 개정(heap 프리미티브 계약 신설 — 할당·해제 책임, 수명 종료 시점,
arena와의 경계). 이 태스크는 새 런타임 계약을 설계하지 않는다(범위 밖).
**인용 위치**: `docs/ROADMAP.md` Phase 1 리스크 **R6**.

### 판정

FINDING

(공백은 확인됐고 해소는 소유자로 이월됐다. PASS/FAIL이 아니라 FINDING인 이유: C8은 "정합성이
성립하는가"를 묻는 항목이 아니라 "공백을 발견하고 경로를 결정했는가"를 묻는 항목이다.)

## C9 — 하네스 미탐지 3부류 교차 대조

> 오케스트레이터 신설 항목. RFC-0004의 검증 하네스는 **어휘·앵커 기반**(문자열·행 앵커 대조)이라
> 아래 3부류를 구조적으로 잡지 못한다: ① 인용된 상류 계약의 **의미**가 원문과 어긋나는 경우
> ② 같은 문서 안 두 목록이 **서로** 어긋나는 경우 ③ 의무의 **심각도**가 낮아진 경우.
> 문자열이 존재하는지는 기계가 보지만, 그 문자열이 상류 원문과 같은 뜻인지는 보지 못한다.
> 따라서 이 3부류는 **사람의 원문 직접 대조**가 담당한다(감사 보고 §5 권고).

### 기준

각 부류별 판정 기준을 판정 전에 고정한다.

| 부류 | PASS 기준 | FINDING 기준 |
|------|----------|-------------|
| ① 상류 계약의 의미적 모순 | RFC-0004가 RFC-0003을 인용하는 3개 지점(arena 수명 / pool 중첩 획득 / Performance.response)에서 인용 내용이 RFC-0003 원문과 **같은 뜻**이다 | 재정의·연장·단축·조건부 허용 중 하나라도 있으면 FINDING |
| ② 문서 내 목록 자기모순 | 동등성 **대상** 4종 목록과 **비대상** 목록이 서로 겹치지 않고, 두 목록이 같은 문서의 다른 절(§층위 구분·§두 모드에서의 동일 관측)의 서술과 문자적으로 충돌하지 않는다 | 비대상 목록의 한 항목이 다른 절의 사실 진술과 **같은 낱말에서** 어긋나면 FINDING |
| ③ 심각도 강등 | S2의 문서 수준 불변식 5종(V1~V5), S3 불변조건 4개, S4의 실체화 의무, RFC-0003의 fail-fast·중첩 획득 금지 중 **어느 것도** 경고·권고로 낮춰지지 않았다 | 하나라도 강등되면 FINDING |

### 명령·출력

**부류 ① — 상류 계약의 의미적 대조 3건.**

| 대조 | RFC-0004 주장 | RFC-0003 원문 | 판정 |
|------|--------------|--------------|------|
| ①-1 arena 수명 | `:241` "개별 해제가 없고 workflow 실행 종결 시 일괄 해제된다(RFC-0003 arena 계약)" / `:400-402` "데드라인 초과로 실행이 종결되어도 arena는 **성공·실패·취소를 불문하고** 일괄 해제된다" | `:149` "수명 = **workflow 실행 수명**: 실행 시작 시 생성되고, 실행 종결 시 — **성공·실패·취소를 불문하고** — 일괄 해제된다. … 개별 해제·GC 추적이 없다" | **모순 없음** — 수명 기산점·종결 조건·해제 방식이 자구까지 일치. 연장·단축·재정의 없음 |
| ①-2 pool 중첩 획득 | `:243` "operation당 1회 획득, 다른 자원 획득 전 반환(RFC-0003 — 중첩 획득 금지)" / `:198`(B1) "두 브랜치는 형제이므로 **각자 1개를 획득하며** RFC-0003의 중첩 획득 금지에 걸리지 않는다. bounded pool 고갈 시 fail-fast는 런타임 계약(RFC-0003)이며 **컴파일러가 완화하지 않는다**" | `:92` "커넥션 획득은 operation당 1회이며, **다른 pool 자원을 획득하기 전에 반환해야 한다**(같은 pool에 대한 중첩 획득은 pool 만석 시점에 데드락 — 금지)" / `:150`③ "획득은 operation당 1회, 다른 자원 획득 전 반환 — 중첩 획득 금지" | **모순 없음** — 아래 N3 반전 대조 참조 |
| ①-3 Performance.response | `:199`(B2) "`Performance` 제약은 두 패스 모두에게 **입력**이며 **어느 패스도 그 값을 변경하지 않는다**(S3 불변조건 ④)" | `:111` "**SLO 선언이다 — 집행 대상이 아니다.** 런타임은 초과 요청을 차단하지 않는다 … 대신 계측·경보한다" | **모순 없음** — RFC-0004는 response를 집행 대상으로 다루지 않고 입력으로만 취급한다. 값 변경 금지는 RFC-0003의 비집행 계약과 같은 방향이다 |

**부류 ② — 동등성 대상/비대상 3자 대조.** 세 절의 원문:

```
[A] 동등성 대상 4종 (rfcs/0004-compiler.md:277-280)
1. **실행 순서** — step 순서, structured concurrency의 join·취소 전파
2. **정책 집행 결과** — retry 판정, rollback 경계, timeout 시 종결 상태
3. **관측성 신호** — trace 구조(step = span), 상관ID 전파, 메트릭 라벨 집합, 로그 레벨
4. **마스킹** — Password·secret이 로그·trace·에러·직렬화에 평문으로 나타나지 않음

[B] 동등성 비대상 목록 (rfcs/0004-compiler.md:282-283)
"**동등성 대상이 아닌 것**을 함께 못박는다: 스케줄러 구조, 메모리 배치(Stack/Heap/
Arena 선택), 명령 선택, op 개수, 실행 시간."

[C] §두 모드에서의 동일 관측 (rfcs/0004-compiler.md:410-415)
"**배치 결정 자체는 두 모드에서 갈리지 않는다** — S3은 두 모드가 공유하는 단계이므로
`wf.login.step.2.repo`의 read 결과는 양쪽 모두 **Arena**다 … 갈리는 것은 그 결정의
**실현 방식**이다: 모드 A는 인터프리터 자료구조로 arena 슬롯을 잡고, 모드 B는 S5~S7
하강에서 같은 슬롯을 레지스터나 스택 슬롯으로 승격할 수 있다. 이 차이는 **동등성
대상이 아닌** 쪽에 속한다"

[D] §층위 구분 (rfcs/0004-compiler.md:260-265)
"이 절이 정하는 것은 **S3-3의 배치 선택 층위**다 … S5~S7 하강에서 LLVM이 수행하는
레지스터 할당·스택 슬롯 재사용은 **다른 층위**이며 … 그 차이는 §실행 모드와 semantic
equivalence의 동등성 비대상에 속한다"
```

**대조 결과.** [C]와 [D]는 일치한다 — 둘 다 비대상인 것을 **하강 층위의 실현 방식**으로 지목한다.
그런데 [B]는 비대상 항목을 "메모리 배치(Stack/Heap/Arena **선택**)"이라고 적는다. `선택`은
[D]가 "이 절이 정하는 것"이라 부른 **S3-3의 배치 선택**을 가리키는 낱말이고, [C]는 그 선택이
**두 모드에서 갈리지 않는다**고 사실로 진술한다.

즉 같은 낱말(`배치 선택`)에 대해 [B]는 "동등성을 요구하지 않는다", [C]는 "동등하다"라고 말한다.

**부류 ③ — 심각도 어휘 전수 검색.**

```sh
$ grep -cE '경고|warning|완화|권고|강등' rfcs/000[1-6]*.md
rfcs/0001-semantic-ir.md:0     rfcs/0002-syntax.md:0     rfcs/0003-runtime.md:0
rfcs/0004-compiler.md:2        rfcs/0005-knowledge-base.md:0   rfcs/0006-agent-protocol.md:0
```

히트 2건 모두 **강등을 금지하는** 문장이다:

```sh
$ grep -nE '경고|완화' rfcs/0004-compiler.md
99:  … 위반은 컴파일 실패이며 경고로 강등하지 않는다 |
198: … fail-fast는 런타임 계약(RFC-0003)이며 컴파일러가 완화하지 않는다 |
```

의무별 심각도 확인 (전부 실패·금지 등급 유지):

| 의무 | 심각도 원문 | 위치 |
|------|------------|------|
| S2 문서 수준 불변식 V1~V5 | "위반은 컴파일 실패이며 **경고로 강등하지 않는다**" | `:99` |
| S2 IR 무변형 | "이 단계는 IR을 **고치지 않는다** — 통과 아니면 **컴파일 실패다**" | `:55-57` |
| S4 컴파일 컨텍스트 실체화 | "실체화되지 않은 결정은 유실이며 **변환 실패로 취급한다**" | `:101` |
| 자동 병렬화 보수 규칙 | "IR로 확증할 수 없으면 **병렬화하지 않는다**" | `:213` |
| RFC-0003 pool fail-fast | "**컴파일러가 완화하지 않는다**" | `:198` |

**용어 구분(오탐 배제).** RFC-0003의 `경보`(3회 — SLO 위반 alert)는 심각도 강등의 `경고`(warning)와
다른 개념이다. `경보`는 `Performance.response`가 **집행 대신 계측·경보** 대상이라는 계약의 일부
(`rfcs/0003-runtime.md:111`)이고, 이는 강등이 아니라 애초부터 그렇게 설계된 것이다. RFC-0004에는
`경보`가 0회다. 두 낱말을 섞으면 거짓 FINDING이 난다.

### 근거 인용

- 하네스의 성질(왜 이 3부류를 못 잡는가): `rfcs/0004-compiler.md:287-295` — 차동 검증은
  "같은 `.lir.json`을 두 모드로 실행하고 위 4종을 대조한다"이며, 대조 대상이 **실행 산출물**이다.
  문서 간 의미 일치는 그 대조의 범위 밖이다.
- ①-1: `rfcs/0003-runtime.md:149` ↔ `rfcs/0004-compiler.md:241, 400-402`
- ①-2: `rfcs/0003-runtime.md:92, 150` ↔ `rfcs/0004-compiler.md:198, 243`
- ①-3: `rfcs/0003-runtime.md:111` ↔ `rfcs/0004-compiler.md:199`
- ②: `rfcs/0004-compiler.md:274-285`(대상·비대상), `:260-265`(층위 구분), `:410-415`(두 모드)
- ②의 상류: `rfcs/0003-runtime.md:60-63` — "계약의 단위는 **관측 가능한 동작**이다: 실행 순서,
  정책 집행 결과, 관측성 신호, 마스킹. **내부 구현(스케줄러 구조, 메모리 배치 선택)은 계약
  대상이 아니며, 배치 선택 알고리즘은 RFC-0004 소유다**" — RFC-0003도 "메모리 배치 선택"을
  비계약으로 적는다. 즉 [B]의 표현은 상류를 그대로 따랐고, 어긋난 쪽은 [C]가 나중에 추가한
  사실 진술이다. 이 계보 확인이 해소 방향을 정한다(아래).
- ③: `rfcs/0004-compiler.md:55-57, 99, 101, 198, 213`

### 음성 대조

**부류 ① — N3 반전 대조.** ①-2에 반대 독법을 세운다: *"형제 브랜치 둘이 같은 pool에서 동시에
1개씩 획득하는 것은 중첩 획득이다"*. 이 독법이 성립하면 RFC-0004 B1은 RFC-0003을 위반한다.
기각 근거는 RFC-0003 자신의 정의다 — `:92`는 중첩을 **한 획득 주체의 순서**로 정의한다("커넥션
획득은 operation당 1회이며, **다른 pool 자원을 획득하기 전에 반환해야 한다**"). 형제 브랜치는
각자 1개를 쥐고 각자 반환하므로 어느 주체도 "쥔 채로 다른 것을 획득"하지 않는다. 따라서 반대
독법은 원문에서 배제되고 ①-2는 모순 없음이다. **만약 RFC-0003이 중첩을 "동시 보유 총량"으로
정의했다면 이 판정은 뒤집혔을 것이다** — 즉 이 대조는 원문에 의존해 갈린다.

**부류 ② — N1 부재 대조.** 동등성 **대상** 4종이 비대상 목록에 등장하는지 검사하면 전부 0이다:

```sh
$ for t in '실행 순서' '정책 집행' '관측성 신호' '마스킹'; do
    printf "  %-12s %s\n" "$t" "$(awk 'NR>=282 && NR<=285' rfcs/0004-compiler.md | grep -c "$t")"; done
  실행 순서        0
  정책 집행        0
  관측성 신호       0
  마스킹          0
```

두 목록은 **서로 겹치지 않는다** — 이것이 더 큰 모순(같은 항목이 대상이면서 비대상)이 없음을
보인다. ②의 FINDING은 목록 간 겹침이 아니라 **비대상 목록과 본문 사실 진술의 어긋남**이며, 이
대조가 0을 낸 덕에 두 문제를 구분해 진단할 수 있었다.

**부류 ③ — N2 분별 대조.** 심각도 어휘 검색이 실제로 어휘를 잡아낸다는 증거로, `:99`의
"경고로 강등하지 않는다"와 `:198`의 "컴파일러가 완화하지 않는다"가 히트한다(위 출력). 검색이
아무것도 잡지 못하는 패턴이었다면 "강등 0건"은 무의미했다 — 어휘가 있는 곳을 정확히 2건 집어냈고
그 2건이 모두 강등 **금지** 문장이므로 강등은 없다.

### 부류별 판정

| 부류 | 판정 | 근거 행 | 해소 소유자 | 인용 위치 |
|------|------|---------|-------------|-----------|
| ① 상류 계약의 의미적 모순 | **모순 없음** | `0003:92,111,149,150` ↔ `0004:198,199,241,243,400-402` | 해당 없음 | — |
| ② 문서 내 목록 자기모순 | **모순 확정 → 해소** | `0004:282-285`(수정) vs `0004:410-415`·`:260-265`(미수정) | RFC-0004 — **이 태스크가 최소 수정으로 해소** | 해소 완료. ROADMAP Phase 2 R11에 해소 사실로 기록 |
| ③ 심각도 강등 | **강등 없음** | `0004:55-57,99,101,198,213` | 해당 없음 | — |

**②의 정확한 진단.**

- **왜 하네스가 못 잡는가**: 두 문장에 같은 낱말(`메모리 배치`)이 등장하므로 어휘 대조는 오히려
  "일관됨"으로 읽는다. 차동 검증도 못 잡는다 — 배치는 외부에서 관측되지 않으므로 두 모드
  대조에 나타나지 않는다. 어휘 기반도 실행 기반도 놓치는 사각지대다.
- **모순의 확정 근거(오케스트레이터 리뷰).** 최초 판정은 이를 "모순 소지 있음"으로 등급을 낮춰
  등재만 했으나, 리뷰에서 **모순 확정**으로 상향됐다. 근거: **S3은 두 모드가 공유하는 단계다**
  (모드 A = S1→S2→S3, `rfcs/0004-compiler.md:271`). 따라서 S3-3에서 내려진 배치 **결정**은
  두 모드에서 **문자 그대로 같은 산출물**이며 다를 수가 없다 — [C](`:410-411`)와 [D](`:260-265`)가
  둘 다 그렇게 말한다. 그러므로 부정확한 쪽은 그 결정을 동등성 **비대상**으로 열거한
  [B](`:282-283`)다. "비대상이면서 사실상 동일할 수 있다"는 최초의 논리적 방어는, 그 동일성이
  **구조적으로 강제된다**는 사실 앞에서 성립하지 않는다: 계약이 비대상이라 말하는 것을 구조가
  동일하게 만들고 있으면, 계약 문장이 구조를 잘못 기술한 것이다.
- **Phase 2에 미치던 영향**: 모드 A/B 동등성 판정(ROADMAP Phase 2 완료 기준 1)에서 "배치가
  달라졌다"를 결함으로 볼지 허용 범위로 볼지가 문서에서 갈렸다.

### ②의 해소 — 최소 수정 적용

C8과 동일한 처방(최소 수정 + 등재 + ROADMAP 반영)을 적용했다. **[C]·[D]는 건드리지 않고 [B]만**
고쳤다 — 부정확한 쪽이 [B]이므로.

**before** (`rfcs/0004-compiler.md:282-285`):

> **동등성 대상이 아닌 것**을 함께 못박는다: 스케줄러 구조, 메모리 배치(Stack/Heap/
> Arena 선택), 명령 선택, op 개수, 실행 시간. 이것들은 내부 구현이며, 여기에 동등성을
> 요구하면 모드 B의 최적화 자체가 계약 위반이 된다. 계약은 **외부에서 관측되는 것**에
> 대해서만 성립한다.

**after** (같은 위치, 4행 유지):

> **동등성 대상이 아닌 것**을 함께 못박는다: 스케줄러 구조, **메모리 배치의 실현 방식**
> (S5~S7 하강에서의 레지스터·스택 슬롯 승격 등), 명령 선택, op 개수, 실행 시간. 배치의
> *선택* 자체는 S3에서 확정되어 두 모드가 공유하므로 비대상이 아니다(§층위 구분). 비대상에
> 동등성을 요구하면 모드 B의 최적화가 계약 위반이 된다 — 계약은 **외부에서 관측되는 것**에만 성립한다.

변경의 요점 3가지: ① 비대상을 배치의 **선택**에서 **실현 방식**으로 좁혔다 ② 그 실현 방식이
무엇인지(S5~S7 하강의 레지스터·스택 슬롯 승격)를 명시해 [D] §층위 구분과 낱말을 맞췄다
③ **"배치의 선택 자체는 비대상이 아니다"를 명문화**해 [C]의 사실 진술을 계약이 보호하게 했다.

**해소 후 재대조** (수정 후 실측):

```sh
$ awk 'NR>=282 && NR<=285' rfcs/0004-compiler.md | grep -cE '메모리 배치\(Stack/Heap/|Arena 선택\)'
0                          # [B]에 '배치 선택'을 비대상으로 두는 표기가 사라짐
$ awk 'NR>=282 && NR<=285' rfcs/0004-compiler.md | grep -c '메모리 배치의 실현 방식'
1                          # 비대상은 실현 방식으로 좁혀짐
$ awk 'NR>=282 && NR<=285' rfcs/0004-compiler.md | grep -c '비대상이 아니다'
1                          # 선택은 비대상이 아님이 명문화됨
$ grep -c '배치 결정 자체는 두 모드에서 갈리지 않는다' rfcs/0004-compiler.md
1                          # [C] 미수정
$ grep -c '이 절이 정하는 것은 \*\*S3-3의 배치 선택 층위\*\*다' rfcs/0004-compiler.md
1                          # [D] 미수정
$ wc -l rfcs/0004-compiler.md
444                        # 줄 수 보존
```

**회귀 검사** — Task 06의 컴파일러 검사 하네스를 워크트리에서 실행했다.

> **주의 — 이 하네스는 이 레포에 포함돼 있지 않다.** `.orchestration/`은 이 스위트를 만든
> 오케스트레이션의 작업 스캐폴딩(브리프·계획·검증 기록·태스크별 하네스)이며 `.gitignore`
> 대상이다. 아래 출력은 작성 당시 실행한 기록이고, 레포를 클론한 사람은 이 경로를 갖지
> 않는다. 레포에 포함된 재현 가능한 검사는 `scripts/validate_ir.py`(C7)다.

```sh
$ bash .orchestration/verify/06-compiler-check.sh   # (오케스트레이션 로컬 — 레포 미포함)
PASS  A4l [음성] RFC-0003 프리미티브 재정의 문장
PASS  A5c [앵커] 동등성 비대상 명시(>=3항목)
PASS  A10i [구조] 두 모드 관측 문단이 배치 불변을 주장(모드별 배치 상이 주장 부재)
PASS  A9f [재현성] 기록의 줄 수 주장이 실제 문서와 일치
FAIL  S2 [음성] out_of_scope 무변경
RESULT: FAIL (passed=61 failed=1)
```

- **A5c 유지**: 비대상 열거가 3항목 이상이어야 하는데, `메모리 배치의 실현 방식`이 부분문자열
  `메모리 배치`를 포함하므로 열거 수가 줄지 않았다.
- **A10i 유지**: 이 검사는 [C]의 "배치 결정 자체는 두 모드에서 갈리지 않는다"를 앵커하는데,
  [C]를 건드리지 않았으므로 그대로 통과한다.
- **A9f 유지**: 파일 줄 수 444를 보존했다(4행 → 4행).
- **A4l은 이번에 FAIL→PASS로 회복**했다. 이것은 **C8 수정이 유발한 내 회귀**였다 — 아래 참조.
- 남은 `FAIL S2`는 이 하네스가 **Task 06 스코프**를 기준으로 "범위 밖 변경 없음"을 검사하기
  때문이며, 검출한 변경은 Task 09의 정당한 산출물(`docs/CONSISTENCY-CHECK.md`·`docs/ROADMAP.md`)이다.
  Task 09가 유발한 결함이 아니라 하네스의 스코프 기준 차이다.

**C8 수정이 유발했던 회귀 1건(A4l) — 발견과 해소.** 최초 C8 (b) 수정문은
"RFC-0003 §Memory Model은 런타임이 제공하는 프리미티브를 arena·pool 2종만 계약으로 **정의한다**"
였는데, Task 06 하네스의 부정 검사 A4l이 이를 잡았다:

```
FAIL  A4l [음성] RFC-0003 프리미티브 재정의 문장
      -> 재정의 패턴 1 hits (0이어야 함): ['arena·pool 2종만 계약으로 정의한다']
```

A4l의 정규식은 `(arena|pool|아레나)[^\n]{0,60}(재정의|정의한다|규정한다|…)`이며, RFC-0004가
RFC-0003의 프리미티브를 재정의하지 못하게 막는 게이트다. 내 문장은 RFC-0003이 무엇을 정의하는지
**서술**한 것이지 재정의가 아니지만, **어휘 게이트는 서술과 재정의를 구분하지 못한다** — 이 태스크
C9가 다루는 바로 그 사각지대에 내가 걸린 것이다. 서술을 유지하면서 게이트를 통과하도록 문구를
바꿨다: "RFC-0003 §Memory Model**의 프리미티브 계약 표에는 arena·pool 2행만 있고 heap 행이 없다**".
사실 내용은 동일하고(계약 2종·heap 부재), 정의 동사가 사라져 A4l이 PASS로 회복됐다.

### 판정

①③ PASS (무모순·무강등) / ② **모순 확정 → 해소 완료**

(최초 판정은 ②를 "모순 소지 있음(FINDING)"으로 등재만 했다. 오케스트레이터 리뷰가 S3 공유
논거로 모순을 확정하고 최소 수정을 지시했으므로, 이 항목은 이제 **이월이 아니라 해소**다.
수정 사실은 §수정한 파일 목록에 기록했다.)

## 수정한 파일 목록

C1~C9 판정 과정에서 실제로 수정한 파일을 전량 기록한다. 신규 생성 산출물과 구분하고,
**등재만 하고 수정하지 않은 발견**은 다음 절에 따로 적는다(섞지 않는다).

### 수정 (기존 파일 변경) — 1파일 3처

수정한 파일은 `rfcs/0004-compiler.md` **1개**이며, 그 안의 3처를 고쳤다. 전부 최소 수정이고
파일 줄 수 444를 보존했다.

| # | 위치 | 수정 내용 | 이유 | 근거 C항목 |
|---|------|----------|------|-----------|
| 1 | §Memory 배치 규칙 **Heap 행**(`:242`) | 기존 배치 조건은 보존하고 "heap 프리미티브 자체의 런타임 계약(할당·해제 책임, 수명 종료 시점)은 v0.1에서 미정 — RFC-0003 §Memory Model의 프리미티브 계약 표에는 arena·pool 2행만 있고 heap 행이 없다. 이 행이 다루는 것은 배치 분류뿐" 한정 표기를 덧붙임 | heap 프리미티브의 런타임 계약이 스위트 어디에도 없는데 RFC-0004가 Heap을 배치 대상으로 선택한다. 공백을 문서 표면에 드러내지 않으면 Phase 1 구현자가 Heap 행을 완결된 계약으로 오독한다 | **C8** — 해소 경로 (b) |
| 2 | §실행 모드와 semantic equivalence **동등성 비대상 목록**(`:282-285`) | 비대상을 "메모리 배치(Stack/Heap/Arena **선택**)"에서 "**메모리 배치의 실현 방식**(S5~S7 하강에서의 레지스터·스택 슬롯 승격 등)"으로 좁히고, "배치의 *선택* 자체는 S3에서 확정되어 두 모드가 공유하므로 비대상이 아니다"를 명문화 | **S3은 두 모드가 공유하는 단계**이므로 S3-3의 배치 결정은 두 모드에서 같은 산출물이며 다를 수가 없다. 그런데 비대상 목록은 그 결정을 비대상으로 열거해, 같은 문서의 §두 모드에서의 동일 관측·§층위 구분과 어긋났다. 부정확한 쪽이 비대상 목록이므로 그것만 고쳤다([C]·[D] 미수정) | **C9 부류②** — 모순 확정 후 해소 |
| 3 | 위 1의 문구 재조정 | "arena·pool 2종만 계약으로 **정의한다**" → "…계약 표에는 arena·pool **2행만 있고 heap 행이 없다**" | 1의 최초 문구가 Task 06 하네스의 부정 게이트 **A4l**(RFC-0004가 RFC-0003 프리미티브를 재정의하지 못하게 막는 검사)에 걸렸다. 서술을 재정의로 오인한 어휘 게이트의 오탐이지만, 사실 내용을 유지하면서 정의 동사를 없애 게이트를 통과시켰다 | **C8 수정의 회귀 해소** |

**FAIL 해소 수정은 0건이다** — C1~C7이 전항 PASS였으므로 FAIL 해소를 위한 RFC 수정은 발생하지
않았다. 위 3처는 모두 신설 항목(C8·C9)의 처방과 그 회귀 정리이며, 브리프의 수정 권한
(C1~C7 FAIL 해소 + C8(b))과 오케스트레이터 리뷰의 C9② 오버라이드 지시 안에 있다.

`git diff --numstat` = `5 5 rfcs/0004-compiler.md` (5행 삽입 / 5행 삭제 — Heap 행 1행 + 비대상
문단 4행).

### 신규 생성 (산출물 — 수정이 아니다) — 2건

| 파일 | 내용 |
|------|------|
| `docs/CONSISTENCY-CHECK.md` | 이 문서. C1~C9 판정 기록 |
| `docs/ROADMAP.md` | 3 Phase 구현 착수 로드맵 |

### 수정하지 않은 것 (스코프 준수 확인)

| 대상 | 상태 | 근거 |
|------|------|------|
| `rfcs/0000`·`0001`·`0002`·`0003`·`0005`·`0006` | 무수정 | `git diff --name-only rfcs/` = `rfcs/0004-compiler.md` 1건뿐 |
| 전 RFC `Status` | 전부 `Draft` 유지 | RFC-0000 §2 — Accepted 전이는 체크리스트 PASS **+ 소유자 승인**이 필요하며 승인은 사용자 리뷰 대상 |
| `CHARTER.md` | 무수정 | `git status --short CHARTER.md` 빈 출력 |
| `plans/**` | 무수정 | `git status --short plans/` 빈 출력 |
| `schemas/`·`examples/`·`scripts/` | 무수정 | 판정은 읽기 전용. `validate_ir.py --self-test` exit 0으로 회귀 없음 확인 |

## 재수행 결과

`rfcs/0004-compiler.md` 수정 **이후** 상태에서 C1~C9 판정 명령을 전량 재수행했다. 수정이 다른
항목의 판정을 바꾸지 않았음을 확인하는 것이 이 절의 목적이다(특히 C3·C9①이 같은 파일을 본다).

### 재수행 출력

```
--- C1   0002 최상위선언=5  0001 Declaration=5  음성(6번째)=0
--- C2   NetworkCall=1 RepositoryCall=1 CacheAccess=1 Transaction=1 Authorization=1 EventEmit=1 FileWrite=0
--- C3   S3 스키마=1  S1=0 S2=0 S3=0 S4=1 S5=1 S6=1 S7=1
--- C4   IDENTICAL / kb.* 표 행=3
--- C5   0001 retry,?3=1  0002 UserCreated=2  0003 rollback=5  0004 step.6=3
         0005 gen-token=4  0006 step.1=1     음성(kafka/9s/Order) 전 6RFC 합계=0
--- C6   재정의하지않는다 7파일 최소=1  가짜용어 최대=0
--- C7   self-test: OK (1 positive passed, 3 negatives rejected)   EXIT=0
--- C8   0003 계약표 행=2  heap행=0  0004 Heap 한정표기=1
--- C9   심각도어휘=2(둘 다 강등 금지 문장)  동등성 대상∩비대상 합계=0
--- diff 1	1	rfcs/0004-compiler.md
```

**수정 전후 판정 변화 없음.** C3은 S1~S3=0 / S4~S7=1 갈림을 그대로 유지했고(수정한 Heap 행은
파이프라인 표가 아니라 §Memory 배치 규칙에 있어 S열 검사에 영향이 없다), C9①의 arena 수명 대조도
그대로 모순 없음이다(수정은 heap 행에만 적용되어 arena 행 `:241`을 건드리지 않았다).

### 등재만 — 수정 없음 (4건)

발견했으나 이 태스크의 수정 권한 밖이므로 **소유자에게 이월**한 항목이다. 위 §수정한 파일
목록과 섞지 않는다.

| # | 발견 | 판정 항목 | 해소 소유자 | 인용 위치 |
|---|------|-----------|-------------|-----------|
| 1 | heap 프리미티브의 런타임 계약 부재(계약 자체의 신설) | C8 | RFC-0003 개정 | `docs/ROADMAP.md` Phase 1 리스크 **R6** |
| ~~2~~ | ~~동등성 비대상 목록의 "메모리 배치(…선택)" 어긋남~~ → **해소됨**(오케스트레이터 리뷰 오버라이드로 최소 수정 적용). 이 표에서 이월 대상이 아니다 — §수정한 파일 목록 2행 참조 | C9 부류② | — | — |
| 3 | 무수식 `Pipeline`의 3의미(IR kind / 컴파일 파이프라인 / Agent Pipeline) | C6 인접 발견 ① | `docs/GLOSSARY.md` 개정 | 구현 영향 없음 — 등재만 |
| 4 | `Lowering`의 "의미 보존"과 A.4-① 가드 소실의 긴장 | C6 인접 발견 ② | A.4-①의 소유자(RFC-0001 개정 + RFC-0003) | `docs/ROADMAP.md` Phase 1 리스크 **R4** |

1번은 (b) 경로로 **표기**를 RFC-0004에 남겼으나 **계약 신설**은 하지 않았으므로 이월 항목이다.

### 게이트 결과

**알려진 이슈와 함께 통과.**

판단 근거: C1~C7이 전항 PASS이고, C8·C9에서 나온 발견 2건과 C6 인접 발견 2건이 **각각 해소
소유자와 인용 위치를 갖고 목록에 있다**. 소유자 없는 발견은 0건이므로 `차단`이 아니고, 발견이
존재하므로 `통과`도 아니다. 네 번째 결과는 없다.

이 판정은 RFC Status 승격과 무관하다 — RFC-0000 §2가 요구하는 "소유자 승인"은 사용자 리뷰
대상이며 이 문서가 대신할 수 없다.

---

## 승격 기록 — 전 RFC Draft → Accepted (2026-07-31)

RFC-0000 §2는 `Accepted` 승격에 두 조건을 요구한다: **교차 정합성 전항 통과**와
**소유자 승인**. 두 조건이 모두 충족됐으므로 RFC 0000~0006 전편을 승격했다.

### 조건 1 — 교차 정합성

C1~C9 전항 판정은 위에 기록돼 있다. 그 판정 이후 이 스위트는 두 차례 개정됐고,
개정 후 재검증 결과는 다음과 같다(2026-07-31):

| 검사 | 결과 | 근거 |
|------|------|------|
| C1 문법 최상위 ↔ IR Declaration | PASS | 생산규칙 5종·Declaration kind 5종 유지 |
| C2 Effect 실행 의미 | PASS | Effect 6종 + **신설 `Guard`** 전부 RFC-0003에 실행 의미 존재(§Guard 추가) |
| C3 패스 불변조건·역추적 | PASS | 개정이 RFC-0004 파이프라인을 건드리지 않음 |
| C4 `kb.*` 시그니처 | PASS | 0005·0006 양쪽 각 2회, 문자열 동일 |
| C5 골든 관통 | PASS | 골든이 **기계 생성**으로 전환돼 소스↔IR 불일치가 회귀 테스트로 차단됨 |
| C6 GLOSSARY 재정의 부재 | PASS | 용어 정의 무변경 |
| C7 `validate_ir.py --self-test` | PASS (exit 0) | positive 1 + negative 3 거부 |
| C8 heap 계약 공백 | **해소** | RFC-0003에 `transfer` 프리미티브 신설, RFC-0004 Heap 행이 이를 참조 |
| C9 하네스 미탐지 3부류 | **해소** | ② 동등성 목록 자기모순을 최소 수정으로 정정(이전 기록 참조) |

### 조건 2 — 소유자 승인

레포 소유자가 2026-07-31 승격을 승인했다.

### 승격 시점에 미해소로 남은 것

**RFC-0002 부록 A.4의 8항은 전부 해소됐다**(①②③④⑤⑥⑦⑧). 승격을 막는 공백은 없다.
남은 미결은 각 RFC의 `## Open Questions`에 있으며, 그것들은 *결정을 유보한 항목*이지
*계약의 공백*이 아니다 — 대표적으로 조건식의 일반 문법(RFC-0002 OQ②), refinement 타입
표면 표기(OQ③), MLIR Location API 표기(RFC-0004 OQ②), 에이전트 인증(RFC-0006 OQ).

### 구현이 규칙보다 좁게 강제하는 지점 (2026-07-31 기록)

RFC-0001 구조 규칙 5는 비소유 참조 필드로 `requires`, `constraints`, `entity`, `event`,
`target`, `source.ref`를 열거하고, 규칙 6은 **모든 참조가 같은 문서의 id로 해소돼야
한다**고 못박는다. 구현(`protocol.NAMED_REF_FIELDS`)은 이 중 **`target`을 제외**한다 —
컴파일러가 그 필드에 노드 id뿐 아니라 필드 경로(`entity.user.email`)와 리터럴
`"unspecified"`도 쓰기 때문이다(`lower.py`의 Validation 하강). `target`을 규칙 6에
곧이곧대로 넣으면 컴파일러 자신의 정상 출력이 반려된다.

- 판정: **RFC 개정 후보**(`target`의 값 문법을 규칙 5에서 분리해 명시)이지 계약 공백은
  아니다. `Accepted` 상태이므로 본문 수정 대신 여기에 기록하고 Supersede 대상으로 남긴다.
- 대신 지킨 것: `children`·`requires`·`constraints`·`entity`·`event`·`source.ref`는
  리뷰 시점(`Reviewer._assess`)과 적용 시점(`Server._apply`) **양쪽에서 같은 함수로**
  검사한다. 두 게이트가 서로 다른 질문을 하던 동안, `constraints`에서 빠진 참조가 둘 다
  통과했다(적대적 재감사가 실증).

### 이후 변경 절차

`Accepted` RFC의 실질 변경은 본문 편집이 아니다. 오탈자·서식·인용 경로 수정은 그대로
편집한다.

**효력 있는 절차는 RFC-0007 §2.2**(RFC-0000을 대체). 범위에 비례하는 두 관계가 있다:

| 관계 | 쓰는 때 | 대상 상태 |
|---|---|---|
| **Supersedes** | RFC의 주제·계약이 전체적으로 바뀔 때 | `Superseded` (종결) |
| **Updates** | 명시한 **절**만 바뀔 때 | `Accepted` 유지 + 그 절에 포인터 1줄 |

RFC-0000에는 전면 대체만 있었고, 그래서 생산 규칙 한 줄을 고치려도 대상 RFC를 통째로
재서술해야 했다 — 재서술 표류 위험이 크고, 그 비용이 곧 "이번만 편집하자"는 압력이 되어
규율 자체를 무너뜨린다. 아래 목록의 개정 요구들이 동시에 그 문제에 걸렸고, 그래서
RFC-0007로 프로세스를 먼저 대체했다.

**2026-07-31 확정 — 예외를 두지 않는다.** 첫 개정 요구가 들어왔을 때 "해당 RFC를 Draft로
되돌려 편집한다"를 대안으로 검토했고 기각했다: 이 레포의 주장 자체가 "Accepted는 편집하지
않는다"이므로, 첫 개정에서 예외를 만들면 그 규율이 곧 무의미해진다.

**2026-08-02 정정 — 앞의 두 건은 전면 대체가 아니라 `Updates`로 나갔다.** 위 문단은
"각각 새 RFC 번호로 나가며 원본은 `Superseded by`로 표시한다"고 적었는데, 그것은
RFC-0000 기준이었다. RFC-0007이 §2.2에서 **`Updates` 관계**를 신설했고 — 그 신설
사유가 정확히 "생산 규칙 한 줄이나 한 절을 고치려 해도 전면 대체가 필요했다"는 문제다 —
한 절만 바뀌는 개정은 대상을 `Accepted`로 둔 채 절 단위로 갱신한다. "Accepted는 편집하지
않는다"는 규율은 그대로다. 바뀐 것은 그 규율을 지키는 **수단**이 하나 늘었다는 것뿐이다.

| 대상 | 사유 | 어떻게 처리됐나 | 추적 |
|---|---|---|---|
| RFC-0002 (Syntax) | 평가기 없는 `Word Word? Word? Word?` 생산 규칙 제거 | **완료** — RFC-0008이 `Updates: RFC-0002 §Full grammar`로 갱신. 대체 아님, RFC-0002는 `Accepted` 유지 | 이슈 #3 |
| RFC-0002 (Syntax) | Open Questions ② 가 옛 문법을 서술한 채 남아 RFC-0008과 모순(RFC-0007 §2.2 규칙 2의 "지목 없는 모순") | **완료** — RFC-0009가 `Updates: RFC-0002 §Open Questions`로 보충 | 이슈 #3 |
| RFC-0003 (Runtime) | §Guard의 "평가할 수 없는 조건은 거부한다"를 새로 평가 가능한 범위로 갱신, `until` 종료 한계 재서술 | **완료** — RFC-0008이 `Updates: RFC-0003 §Guard`로 갱신. 대체 아님 | 이슈 #3 |
| RFC-0006 (Agent Protocol) | ① 역할표 권한 구멍 — 자기가 저작한 노드를 **부착**할 권한이 없다. Constraint 전용이 아니라 세 역할 공통이다(RefactoringAgent→`Workflow`, SecurityAuditor·PerformanceAnalyzer→`Service`) ② 참조 **이동**이 제거로 읽힌다 | **완료 (2026-08-03) — RFC-0010이 `Updates`로 갱신.** 대체 아님, RFC-0006은 `Accepted` 유지. 지목 절은 `§Agent Roles & IR Access`와 `§Methods/ir.propose` 둘이며, RFC-0007 §2.2 규칙 7의 기준(한 절을 읽으려 몇 문서를 여는가)으로 선행 갱신이 없어 절당 2문서 — 규칙 안이다. **부수 발견: RFC-0006은 제거를 금지한 적이 없다** — 참조 구현이 거절하며 `(RFC-0006 §Methods)`를 인용했으나 그 절에 규정이 없었다. RFC-0010이 처음으로 규정하고 인용을 정정했다 | 이슈 #2 |


### V5(kind별 children 허용 종별) 미구현 — 2026-08-03 기록

RFC-0004 §S2는 문서 불변식 5종을 규정하는데 참조 구현은 V2(소유 유일)·V3·V4(비순환)만
검사한다. **V1(id 유일)과 V5는 어디에서도 검사되지 않고**, `schemas/lir.schema.json`은
`children`을 제약 없는 id 배열로 둔다. 그래서 RFC-0010 이전에는 `WorkflowStep`을 `Entity`의
`children`에 넣어도 통과했다.

RFC-0010은 `attach` 시점에 한해 V5를 요구한다(`protocol.CHILDREN_ALLOWED` — RFC-0001
§노드 카탈로그의 *children 허용* 열을 전사). 그 예외의 내용 자체가 "자기가 소유하지 않은
kind의 노드에 참조를 쓴다"이므로 그 지점만은 막아야 했다. **문서 전역 집행은 여전히 없다.**
우회하기 전에 적는다(RFC-0007 §5).

---

## 이슈 #17 — RFC-0001 노드 종수 오류정정 (2026-08-03 기록)

**사실:** RFC-0001 §노드 카탈로그 행 90의 산문은 "19개 kind"라고 했지만, 바로 아래 4개 표(Declaration/Behavior/Effect/Constraint)는 20개 kind를 나열한다. 2026-07-31에 Guard가 추가되면서 19→20으로 올라갔는데, 산문 숫자를 업데이트하지 않았다.

| 표 | kind 수 | 명단 |
|----|-----:|-----|
| Declaration | 5 | Entity, Service, Workflow, Event, Capability |
| Behavior | 6 | BusinessRule, Validation, WorkflowStep, Guard, Pipeline, Concurrency |
| Effect | 6 | NetworkCall, RepositoryCall, CacheAccess, Transaction, Authorization, EventEmit |
| Constraint | 3 | Policy, Security, Performance |
| **합계** | **20** | **정본은 표, 산문은 재술** |

**판정 원칙 확정:** RFC-0007 §2.1에 따라 "Accepted RFC의 실질 변경은 본문 편집이 아니다. 오탈자·서식·인용 경로 수정은 그대로 편집한다"(단, "실질 변경"은 의미 있는 내용 수정을 뜻함).

산문 숫자와 표의 불일치는 **오탈자에 해당하는지 실질 변경에 해당하는지** 판정해야 한다.
- 정본(source of truth)은 RFC-0001 §노드 카탈로그 본문의 "행의 추가·삭제는 이 RFC의 개정 사항이다"에서 명시한 **표**다.
- 표가 정본이면, 산문 숫자는 표의 **재술(restatement)**이지 독립 규정이 아니다.
- 표가 변했을 때 산문을 따라 갱신하지 않은 것은 **오탈자**다.

**적용:** 산문 "19개 kind" → "20개 kind" 정정. 이와 같은 범주(표는 정본, 산문 숫자는 재술)의 불일치는 모두 오탈자로 취급한다.

**재검증:**
- `rfcs/0001-semantic-ir.md:90` "19개" → "20개"
- `rfcs/0004-compiler.md:130` "19 kind" → "20 kind"
- `docs/ROADMAP.md:79` "19 kind" → "20 kind"
- `schemas/lir.schema.json` anyOf 21개 ref 검증 ✓

**판정:** PASS — 오탈자 수정, 실질 변경 없음.

---

## 이슈 #11 — RFC-0007 상태 승격 및 교차정합성 게이트 재확인 (2026-08-03)

**배경:** RFC-0007 §Process v2는 상태가 Draft였지만 RFC-0000이 2026-07-31에 Superseded되면서 그 날짜부터 효력이 있어 왔다. RFC-0008과 RFC-0009(둘 다 Accepted)는 RFC-0007의 `Updates` 관계와 7섹션 템플릿을 사용한다. RFC-0007 §2.1에 따라 상태는 "구현이 따라야 할 계약"이 되는 시점에 Accepted로 표기되어야 한다.

### 승격 조건 확인 (RFC-0007 §2.1)

RFC-0007 자체가 정의하는 Draft→Accepted 전이 기준: "교차 정합성 체크리스트 **전 항목 PASS** + 소유자 승인"

#### 조건 1: 교차 정합성 게이트 전항 재확인

**날짜 구분 (F2 — 역추적 기록의 정직성):**
- **2026-07-31**: RFC-0000이 Superseded되면서 RFC-0007의 프로세스가 **실제 효력**을 갖기 시작한 날짜. 이 날 RFC-0007은 공식적으로 Draft였으나 구현 계약이 됨.
- **2026-08-03**: 이 문서가 **교차정합성 게이트를 형식적으로 걷고 기록한** 날짜. RFC-0007의 Accepted 승격이 이 날짜에 **형식적으로** 결정됨.
- 표의 "2026-07-31 판정" 열은 실제로는 "RFC-0007 프로세스 효력 발생일"을 의미하고, "2026-08-03 재확인"은 "게이트 형식적 평가"를 의미한다. 표 헤더는 레트로스펙티브한 기록의 정직성을 위해 유지하되, 여기 주석으로 구분한다.

RFC-0007 승격 시점(2026-07-31) 이후 세 개정(RFC-0008·0009·0010)이 있었으므로, 승격 기준 확인 시점의 상태를 기록한다(2026-08-03):

| C항목 | 기준 | 프로세스 효력일(07-31) | 게이트 평가일(08-03) | 근거 |
|-------|------|-----------------|------------------|------|
| **C1** | 문법 Declaration 5종 ↔ IR Declaration kind 5종 | PASS | PASS | `rfcs/0002-syntax.md:255-256` vs `rfcs/0001-semantic-ir.md:100-104`, 개정 영향 0 |
| **C2** | RFC-0003 Effect 6종 실행 의미 | PASS (Guard 신설) | PASS | `rfcs/0003-runtime.md:87-96` Guard 실행 의미 2026-07-31 규정됨(RFC-0008), 이후 추가 변경 0 |
| **C3** | S3 스키마 불변+S4~S7 역추적 | PASS | PASS | `rfcs/0004-compiler.md:100-104`, 개정이 컴파일 파이프라인을 건드린 적 없음 |
| **C4** | `kb.*` 3종 시그니처 동일성 | PASS | PASS | `rfcs/0005-knowledge-base.md:142-144` ↔ `rfcs/0006-agent-protocol.md:225-227`, RFC-0010의 `ir.propose` 추가는 개정 범위 밖(절 §Methods 부분만 지목, 시그니처 아님) |
| **C5** | 골든 관통(C5a/C5b) | PASS | PASS | 소스·IR·런타임·컴파일러·KB·에이전트 6 요소 검증 완료(§C5 명령·출력 판정 대조 표 :461-468), 골든 기계 생성으로 회귀 보호 |
| **C6** | GLOSSARY 10 용어 재정의 부재 | PASS | PASS | `docs/GLOSSARY.md` 정의 무변경, 용어 판별 속성 10개 검증 완료(`:607-620`) |
| **C7** | `validate_ir.py --self-test` | PASS (exit 0) | PASS | positive 1 + negative 3 — 스크립트 무변경 |
| **C8** | Heap 프리미티브 계약 | 해소 (프로세스 효력일) | 해소 유지 | `:1328` `transfer` 프리미티브 신설됨, 이후 변경 0 |
| **C9** | 하네스 미탐지 3부류 | 해소 (프로세스 효력일) | 해소 유지 | `:1329` 동등성 목록 정정됨, 이후 변경 0 |

**판정:** C1~C7 전항 PASS. C8·C9 발견 각각 2026-07-31 해소 상태 유지. **조건 1 충족.**

#### 조건 2: 소유자 승인

RFC-0007 이 문서 작성 시점 최종 검토 대상. 승격은 사용자 리뷰에 따른다.

### 부수 발견: RFC-0008의 7섹션 규칙 위반 기록

**사실:** RFC-0008 §제목은 "RFC-0008: Guard Conditions"이고, 섹션 구조는:
1. Status
2. Motivation
3. Guide-level Explanation
4. Reference-level Specification
5. Examples
6. Alternatives
7. Open Questions
8. **Implementation Status** ← RFC-0007 §7에서 금지한 8번째 섹션

**규칙 위반 확인:**

RFC-0007 §7 템플릿 §6 각 RFC 템플릿:
```
신규 RFC는 아래 블록을 그대로 복사해 시작한다. **7개 섹션의 이름과 순서는 고정이며
글자 단위로 일치해야 한다(섹션 추가·삭제·개명 금지).**
```

RFC-0008 섹션 목록(`grep "^## " rfcs/0008-guard-conditions.md`): 8개.

**판정:** 규칙 위반 확정. RFC-0007 §5는 규칙 위반을 발견했을 때의 처리를 규정한다:

> 설계 결함이 발견되면 이 문서(RFC-0007)에 기록하고, 해소는 명시적 개정 RFC(`Updates`)를 통해 하며, 대상을 Draft로 되돌리지 않는다.

**처리 방식:** RFC-0007 §2.1 규칙에 따라 Accepted RFC의 실질 변경은 본문 편집이 아니다. RFC-0008 자체를 수정하지 않고, 이 문서에 기록한다. 향후 RFC-NNNN이 `Updates: RFC-0008 §Implementation Status` 로 지목해 섹션을 제거하거나, 템플릿을 8개로 확장하는 개정이 필요하다.

**영향도:** 낮음 — RFC-0008 본문의 내용은 정확하고, 위반은 구조(섹션 개수)일 뿐이다. 이 검사 기준 성립 자체(7개 고정)가 "허용 범위 확대 금지"를 의도했으므로 콘크리트한 위반 기록으로 남긴다.

### 발견 F1: 노드 카탈로그 수정의 시간 순서 — RFC-0007의 모순 방지 (2026-08-03 기록)

**상황:** RFC-0001의 Guard 행은 2026-07-31 11:23:10 (commit 9712ea2)에 추가되었고, RFC-0007은 같은 날 17:28:12 (commit 11469c0)에 생성되었다. 따라서 Guard 행을 추가한 행위는 RFC-0007의 프로세스가 존재하기 이전에 일어났다.

**원칙 확인:** RFC-0007 §2.1은 "Accepted RFC의 실질 변경은 본문 편집이 아니다. 오탈자·서식·인용 경로 수정은 그대로 편집한다"고 말한다.

**논점:** RFC-0001의 19→20 **산문 숫자 수정**(2026-08-03)은 RFC-0007 §2.1이 적용되는 오탈자 수정이다. 하지만 **Guard 행 자체의 추가**(2026-07-31 11:23)는 RFC-0007이 존재하기 전에 일어났으므로, RFC-0007 §2.1이 사후 통제(retroactive governance)하지 않는다.

**결론:** 발견은 **시간 차이로 인한 혼동 가능성**을 명확히 하는 것일 뿐이다. 이슈 #17의 19→20 산문 정정 자체는 RFC-0007 §2.1의 오탈자 규칙으로 정당화된다. Guard 행의 존재는 2026-07-31 이후 구현의 사실이며, RFC-0007은 그 사실을 승인하는 것이다.

---

### 발견 F3: Guard 행 개정의 교차참조 공백 (2026-08-03 기록)

**사실:** RFC-0001의 Guard 행은 다음과 같이 표기되었다:
```
2026-07-31 신설(RFC-0002 부록 A.4-① 해소)
```

RFC-0002는 "부록 A.4"에서 Guard 문법을 규정했으나, 실제로 RFC-0001의 **노드 카탈로그** 행을 추가한 것은 누가인가?

**검증:**
- RFC-0008: `Updates: RFC-0002 §Full grammar, RFC-0003 §Guard` — RFC-0001을 지목하지 않음
- RFC-0002: Guard 생성을 위임했을 가능성 (부록 A.4-① 해소라는 표기)
- RFC-0001: `Updated-by:` 역링크 없음

**판정:** 교차참조 공백 확정. RFC-0007 §2.2 규칙 1은 "절을 이름으로 지목한다"고 명시하고, 규칙 3은 "효력 있는 계약 = 대상 RFC 본문 + 지목된 절을 최신 갱신 RFC로 치환"이라 정의한다.

현 상황: RFC-0001의 Guard 행이 **어느 Updates RFC에 포함되는가** 불명확하다.

**향후 처리:** 향후 RFC-NNNN이 명확히 정의해야 한다:
- 만약 RFC-0008이 책임이면: RFC-0008에 `Updates: RFC-0001 §노드 카탈로그/Guard` 추가 (이미 Accepted이므로 추가는 Updates로)
- 만약 RFC-0002 책임이면: RFC-0002에 `Updates: RFC-0001 §노드 카탈로그/Guard` 추가
- RFC-0001에는 해당 절에 `Updated-by: RFC-[NNNN] (§노드 카탈로그/Guard)` 백링크 추가

이 공백 자체는 즉시 처리 대상이 아니라 다음 정합성 검사 사이클에서 기록할 항목이다. 지금은 **결함 기록**만 한다.

**영향도:** 중간 — RFC-0001 Guard 행은 유효하고 구현을 지배하나, 개정 추적성(RFC-0007 §2.2 규칙 1)이 어긋난다.

---

### 발견 F4: RFC-0001 노드 카탈로그 개수 — 정본 여부 명시 부재 (2026-08-03 기록)

**배경:** 이슈 #17에서 RFC-0001 라인 90의 산문 "19개 kind"를 "20개 kind"로 정정했다. 정정 근거는 "표가 정본이고 산문은 재술"이다.

**문제:** RFC-0001 §노드 카탈로그 라인 90은 다음과 같이 표기되었다:
```
**19개 kind — 아래 4표가 전부이며 행의 추가·삭제는 이 RFC의 개정 사항이다.**
```

이 문장은:
- ✓ "행의 추가·삭제는 이 RFC의 개정 사항" — **표(행)이 정본**임을 명시
- ✗ "19개 kind"의 정규화 지위를 **명시하지 않음** — 재술인지 독립 규정인지 모호

**검증 가능 사실:**
- RFC-0001 본문 어디에서도 "개수는 재술이다", "숫자는 정규화되지 않는다" 같은 명시가 없다
- CONSISTENCY-CHECK.md 이슈 #17 섹션에서만 "표는 정본, 산문은 재술"이라는 가정을 기록했다

**판정:** 이슈 #17의 19→20 정정은 **RFC-0007 §2.1 오탈자 원칙에 따라 정당**하지만, 그 근거 자체("산문 숫자는 비정규")가 RFC-0001에 **명시되지 않았다**.

**기록 목적:** 향후 RFC가 비슷한 정정을 할 때, 여기 기록이 선례가 되지 않도록 주의할 것. RFC-0001이 개수의 비정규 지위를 명시하지 않았다는 사실을 이 문서에만 기록한다.

**우선도:** 낮음 — 현재 19→20 정정은 구현 사실(20개 노드)과 일치하므로 정확하다. 하지만 원칙 기반의 명시성을 위해 **향후 RFC-0001을 개정할 때** (Supersedes로든 Updates로든) "숫자는 표의 재술이며 개정 사항이 아니다"를 명시할 것을 권장한다.

**비규범성:** RFC-0001의 본문을 지금 수정하지 않는다 (Accepted RFC 신규 정규화 추가 금지). 이 기록 자체가 충분하다.

---

### 발견 F5: RFC-0002 StepLine 3단어 상한과 실제 with-절 문법의 어긋남 (2026-09-28 기록)

**사실:** RFC-0002 `### Full grammar`의 `StepLine` 프로덕션은 `StepLine ::= Verb Word? Word? Word? EOL`로, 동사 뒤 trailing 단어를 최대 3개까지만 허용한다. 그러나 RFC-0037의 예시 `call OrdersApi with order.id order.sku as r`(issue #109 D6)은 동사 뒤 6개 단어를 쓰고, RFC-0039의 예시 `note "picked-tier-{}-for-{}-orders" with customer.tier order.count`는 4개 단어를 쓴다. 둘 다 이미 Accepted RFC의 `## Examples`에 실려 있다.

**검증:** `grep -n "^- Updates:" rfcs/0037-http-resilience.md rfcs/0039-note-verb-and-canonical-line.md` — RFC-0037은 `Updates: RFC-0027 §Reference-level Specification/1`만 갖고, RFC-0039는 `Updates:` 헤더가 아예 없다. 둘 중 어느 쪽도 RFC-0002 `§Full grammar`를 지목하지 않는다. 실제 렉서는 `Line.tokens = body.split()`로 무제한이며, RFC-0002 `§Full grammar` 자신의 산문도 이미 그렇게 말한다 — EBNF가 파서보다 과소 집계된 것이지, 파서가 EBNF를 어긴 것이 아니다.

**판정:** 어긋남 확정. RFC-0007 §5("어긋남을 발견했으면 고치기 전에 기록한다")에 따라 고치기 전에 이 문서에 먼저 남긴다.

**향후 처리:** 이 RFC(RFC-0049)가 `Updates: RFC-0002 §Full grammar`로 해소한다 — `StepLine ::= Verb Word? Word? Word? EOL`을 `StepLine ::= Verb Word* EOL`로 대체하는 자기완결적 최신 텍스트를 RFC-0049 자신이 싣는다(RFC-0007 §2.2 규칙 4).

**영향도:** 낮음 — 실행에는 영향 없음(파서가 이미 무제한이었다), 문서 신뢰도 문제일 뿐이다.

---

### 발견 F6: RFC-0007 §2.2 규칙 7 통합 후보 15절 — Supersedes 통합을 후속으로 이월 (2026-10-26 기록)

**사실:** RFC-0007 §2.2 규칙 7은 한 절을 읽으려고 열어야 하는 문서가 2개를 넘으면 Updates를 더 쌓지 말고 통합본으로 Supersedes하라고 한다. 이슈 #263 §3이 RFC 10개·15절을 후보로 꼽았다. 아래 "열 문서 수"는 대상 RFC 1개와 그 절을 갱신한 Accepted RFC의 수를 더한 값이다 — 이슈 #263 처리 뒤 대상 머리의 `Updated-by:` 줄과 절 머리 `> 갱신됨:` 줄 기준이며, Draft RFC-0048은 규칙 6에 따라 세지 않는다.

| 대상 절 | 갱신한 Accepted RFC | 열 문서 수 | 결정 |
|---------|--------------------|-----------|------|
| RFC-0001 §노드 카탈로그/Guard | RFC-0028, RFC-0054, RFC-0060 | 4 | consolidated by RFC-0066 (Supersedes RFC-0001) |
| RFC-0002 §Full grammar | RFC-0008, RFC-0012, RFC-0015, RFC-0016, RFC-0049, RFC-0052, RFC-0060, RFC-0062 | 9 | consolidated by RFC-0067 (Supersedes RFC-0002) |
| RFC-0002 §Block structure | RFC-0019, RFC-0058, RFC-0060 | 4 | consolidated by RFC-0067 (Supersedes RFC-0002) |
| RFC-0003 §Execution Model | RFC-0027, RFC-0029, RFC-0032, RFC-0041, RFC-0056, RFC-0062 | 7 | consolidated by RFC-0068 (Supersedes RFC-0003) |
| RFC-0012 §G12.2 | RFC-0025, RFC-0027, RFC-0030, RFC-0052 | 5 | consolidated by RFC-0070 (Supersedes RFC-0012) |
| RFC-0012 §G12.5 | RFC-0025, RFC-0030, RFC-0052 | 4 | consolidated by RFC-0070 (Supersedes RFC-0012) |
| RFC-0014 §2.1 `when` 모드 | RFC-0028, RFC-0060 | 3 | consolidated by RFC-0071 (Supersedes RFC-0014) |
| RFC-0014 §2.4 스킵 레코드 | RFC-0027, RFC-0028, RFC-0050, RFC-0060 | 5 | consolidated by RFC-0071 (Supersedes RFC-0014) |
| RFC-0015 §1 Full Grammar | RFC-0025, RFC-0028, RFC-0050 | 4 | consolidated by RFC-0072 (Supersedes RFC-0015) |
| RFC-0015 §3 정적 거부 | RFC-0051, RFC-0053, RFC-0054, RFC-0060 | 5 | consolidated by RFC-0072 (Supersedes RFC-0015) |
| RFC-0016 §3 피연산자의 차원 규칙 | RFC-0038, RFC-0051, RFC-0053, RFC-0054 | 5 | consolidated by RFC-0073 (Supersedes RFC-0016) |
| RFC-0016 §5 mode A/B 등가 | RFC-0051, RFC-0052 | 3 | consolidated by RFC-0073 (Supersedes RFC-0016) |
| RFC-0025 §5 실행 스코프 | RFC-0059 | 2 | consolidated by RFC-0075 (Supersedes RFC-0025) — 문서 2개로 문턱 아래였지만 RFC-0025 §2(3개)로 문서 전체가 통합 대상이었다 |
| RFC-0028 §6 Mode B | RFC-0050, RFC-0051 | 3 | consolidated by RFC-0076 (Supersedes RFC-0028) |
| RFC-0038 §3 등가 비교의 타입 규칙 | RFC-0051, RFC-0053, RFC-0054 | 4 | consolidated by RFC-0077 (Supersedes RFC-0038) |

**결정:** 사용자 결정(2026-10-26, 이슈 #263): 이번 변경은 통합 RFC를 쓰지 않는다. 15절 모두 위 표대로 이월하고 후속 이슈가 Supersedes 통합을 다룬다.

**처리 (2026-10-28, 이슈 #268):** 사용자 결정(2026-10-28)으로 대상 RFC 12개(위 표의 10개와 재집계가 찾은 RFC-0008·RFC-0021)를 통합 RFC-0066~RFC-0077이 Supersedes했다. 통합본은 대상의 효력 있는 텍스트(규칙 3: 대상 본문의 각 절을 최신 Accepted 갱신 텍스트로 치환)를 같은 절 이름·순서로 싣고, 대체된 RFC는 `Superseded`로 rfcs/에 남는다. `scripts/rfc_lint.py`가 규칙 7을 검사하고(`rule7_check`), 이 변경 뒤 실제 rfcs/에서 0건이다. 재집계 — `rule7_violations`를 a310017의 rfcs/에 돌리면 22행이다: 위 표에서 문서가 2개를 넘는 14행과 아래 8행. 아래 앞 5행은 코디네이터 재집계가, 뒤 3행은 기계 집계만이 찾았다.

| 대상 절 | 갱신한 Accepted RFC | 열 문서 수 | 결정 |
|---------|--------------------|-----------|------|
| RFC-0003 §Guard | RFC-0008, RFC-0012 | 3 | consolidated by RFC-0068 (Supersedes RFC-0003) |
| RFC-0003 §Policy Enforcement | RFC-0013, RFC-0032, RFC-0041 | 4 | consolidated by RFC-0068 (Supersedes RFC-0003) |
| RFC-0008 §1 | RFC-0012, RFC-0015, RFC-0016 | 4 | consolidated by RFC-0069 (Supersedes RFC-0008) |
| RFC-0021 §코드 → 등급 (정본) | RFC-0022, RFC-0023, RFC-0042 | 4 | consolidated by RFC-0074 (Supersedes RFC-0021) |
| RFC-0025 §2 | RFC-0028, RFC-0045 | 3 | consolidated by RFC-0075 (Supersedes RFC-0025) |
| RFC-0001 §노드 카탈로그 | RFC-0015, RFC-0016, RFC-0056 | 4 | consolidated by RFC-0066 (Supersedes RFC-0001) |
| RFC-0014 §2.5 | RFC-0022, RFC-0028 | 3 | consolidated by RFC-0071 (Supersedes RFC-0014) |
| RFC-0014 §2.6 | RFC-0022, RFC-0028 | 3 | consolidated by RFC-0071 (Supersedes RFC-0014) |

**RFC-0007 §10 미결 1 (2026-10-29):** RFC-0007 §10 미결 1(갱신 누적의 기계적 검증 — 규칙 7은 사람이 판단하고 검사는 아직 없다)은 이제 답이 있다. `scripts/rfc_lint.py`의 `main()`이 `rule7_check`를 불러, Accepted RFC의 한 절을 읽으려고 여는 문서가 2개를 넘거나 `Updated-by:`에 절 이름 묶음이 없으면 실패하고, CI(`.github/workflows/ci.yml`)가 그 린터를 blocking 단계로 돌린다. RFC-0007은 Accepted 본문이라 고치지 않고 여기에만 기록한다 — 미결을 닫는 문면 개정은 후속 Updates RFC의 몫이다.

**영향도:** 낮음 — 효력 있는 계약은 §2.2 규칙 3(최신 갱신이 이긴다)으로 여전히 정해진다. 남는 것은 읽는 비용이다.

---

### 발견 F7: §2.2 역링크 표류 — 이슈 #263 §4 처리 기록 (2026-10-26 기록)

**사실:** 이슈 #263이 `scripts/rfc_lint.py`에 더한 §2.2 검사(Accepted RFC의 `- Updates:`가 괄호 밖에서 지목한 대상마다 `Updated-by: RFC-<갱신>`)를 이 변경 전 트리에 돌리면 17쌍이 걸린다. 이슈 본문 §4는 그중 RFC-0015 → RFC-0002 하나만 적었다. 17쌍(갱신 → 대상): RFC-0015 → 0001, 0002, 0008; RFC-0016 → 0001, 0002, 0008; RFC-0017 → 0008; RFC-0018 → 0017; RFC-0022 → 0014, 0021; RFC-0023 → 0021; RFC-0024 → 0023; RFC-0028 → 0025, 0027; RFC-0031 → 0004; RFC-0045 → 0025; RFC-0047 → 0045.

**처리:**

1. 역링크 17쌍 — 대상 RFC 11개(0001, 0002, 0004, 0008, 0014, 0017, 0021, 0023, 0025, 0027, 0045)의 머리에 `Updated-by:` 줄을, 해당 절 머리에 `> 갱신됨:` 줄을 달았다. RFC-0007 §2.2 표가 "대상에 남는 표기"로 정한 것이고 §2.1이 허용하는 비실질 편집이다. RFC-0015와 RFC-0016의 `Updates:`는 RFC-0001의 대상 절을 `§Appendix A/A.4 Node catalogue`로 적었지만 RFC-0001의 부록 A.4는 "constrained-decoding 호환 부분집합"이고 노드 카탈로그는 `### 노드 카탈로그` 절이다. 그래서 RFC-0001에 단 두 `Updated-by:` 줄은 실제 절 이름 `§노드 카탈로그`를 적었다 — RFC-0015·0016의 `Updates:` 문면은 Accepted 본문이라 고치지 않는다.
2. 앞선 갱신을 빠뜨린 포인터 블록 — RFC-0001 §노드 카탈로그, RFC-0002 §Full grammar, RFC-0003 §Execution Model, RFC-0012 §G12.2·§G12.5, RFC-0014 §2.1·§2.4, RFC-0015 §1, RFC-0016 §3의 블록을 대상 머리의 `Updated-by:`와 맞췄다. 이슈 본문과 달리 RFC-0003 §Execution Model과 RFC-0012 §G12.2에는 블록이 있었고 앞선 갱신만 빠져 있었다.
3. Draft RFC-0048의 표기 9곳을 지웠다 — 포인터 8줄(RFC-0001 §Open Questions, RFC-0025 §1·§3·§5, RFC-0038 §2·§Open Questions, RFC-0045 §2·§Open Questions)과 RFC-0012 머리의 `Updated-by: RFC-0048 (§G12.2)`. 근거: RFC-0007 §2.2 규칙 6(갱신 RFC는 Accepted된 순간 효력이 생긴다), 그리고 RFC-0050~0063이 Draft 시점에 남긴 기록("Draft이므로 대상 RFC에 `Updated-by:` 포인터를 달지 않는다"). RFC-0048이 Accepted되면 이 9곳을 다시 단다 — 그때부터 린터가 RFC-0001·0012·0025·0038·0045 머리의 `Updated-by: RFC-0048`을 요구한다.
4. 직전 갱신 이름(규칙 5: 대상과 직전 갱신 RFC를 함께 지목, 이슈 #263 §4와 RFC-0062 l.6처럼 앞선 갱신을 여럿 적는 레포 선례를 따른 코디네이터 결정) — RFC-0049는 RFC-0002 §Full grammar에 RFC-0012를, RFC-0056과 RFC-0062는 RFC-0003 §Execution Model에 RFC-0041을 `Updates:` 괄호에 더했다(§2.1 깨진 인용 경로 수정 — 어느 텍스트가 이기는지는 규칙 3·5의 "최신 갱신이 이긴다"로 이미 정해져 있어 바뀌지 않는다).
5. 고치지 않고 기록만 한 것 — RFC-0052(§Status의 바인딩 항목, §Reference-level Specification/2의 "RFC-0048 §4의 최종 텍스트 위에")와 RFC-0059(§Status의 `Updates:` 괄호와 본문)는 Draft RFC-0048 §4의 텍스트를 기반으로 쓰였다. 규칙 6에 따라 RFC-0048은 아직 효력이 없으므로 이 서술은 결함이지만, 그 문장을 바꾸는 것은 갱신의 기반을 바꾸는 실질 변경이라 RFC-0007 §2.1이 직접 편집을 금지한다. 해소는 RFC-0048의 승격 또는 Updates 개정이다 — 후속 이슈에 함께 적었다.

   (2026-10-28, 이슈 #268; 2026-10-29 해소) 해소됐다 — 사용자 결정(2026-10-29). 두 서술의 대상인 RFC-0012 §G12.2와 RFC-0025 §5는 이제 `Superseded`라, RFC-0052(l.18-19, l.134)와 RFC-0059(l.6, l.13, l.157)의 RFC-0048 기반 서술은 대체된 대상만 가리키는 이력이다. RFC-0059 l.277("그룹별 원본 행 목록은 RFC-0048 §Open Questions에 그대로 남는다")은 대체된 대상이 아니라 Draft RFC-0048 자신의 Open Questions를 가리키고, RFC-0048이 Draft인 동안 참으로 남는다. 효력 있는 텍스트는 통합본 RFC-0070 §G12.2와 RFC-0075 §5에 있고(같은 G12.2 텍스트의 사본이 RFC-0068 §Guard에도 있다 — 발견 F9), 통합본은 RFC-0048의 텍스트를 싣지 않는다 — 규칙 6, 발견 F8의 RFC-0070·RFC-0075 묶음에 있는 RFC-0048 항목, 그리고 rfcs/0066~0077 열두 파일 모두 `grep -c 'RFC-0048'`이 0이다. RFC-0048은 Draft로 남고, `Updates:`는 같은 절 이름으로 통합본 번호로 옮겼으며 G12.2는 세 사본(RFC-0070 §G12.2, RFC-0068 §Guard/G12.2, RFC-0075 §5)을 모두 지목한다. 항목 3의 재부착 대상도 함께 옮겨 갔다 — RFC-0048이 Accepted되면 표기를 다시 달고 린터가 `Updated-by: RFC-0048`을 요구하는 곳은 RFC-0066·RFC-0068·RFC-0070·RFC-0075·RFC-0077과 RFC-0045다(RFC-0045는 그대로).

---

### 발견 F8: 이슈 #268 통합 작업의 발견 — 통합 RFC별 전사 (2026-10-29 기록)

**사실:** 이슈 #268의 작업(t1–t9)이 작업 중 남긴 발견 기록을 그대로 옮긴다. 원천은 작업 블랙보드의 `- [tN] finding:` 줄 216개다(`grep -c 'finding:'` = 217, 2026-10-29 — 나머지 1줄은 그 수를 적은 t9의 사실 줄이라 발견이 아니다). 바이트까지 같은 줄 0개를 하나로 합쳐 216개 항목이다. 항목 문면은 원문(영어) 그대로이고 앞의 `[tN]`은 기록한 작업이다. 뒤의 작업이 항목의 처리를 바꾼 곳은 그 항목 아래 들여쓴 줄에 적었다. 각 항목 끝의 경로:줄은 그 작업의 기준 트리 기준이며 여기서 다시 맞추지 않았다 — t1·t2·t4·t5·t6·t7은 a310017, t3은 `@` 뒤에 적은 커밋(적지 않은 줄은 f7a808d), t8은 975299f, t9는 67af189(RFC-0048 `:15-18` 항목만 2b0b01a 기준 — 67af189에서는 l.18-21). 경로:줄이 없는 항목은 원문이 적은 명령·문면이 증거다.

**처리:** 항목 머리(첫 ` — ` 앞)를 왼쪽부터 읽어, 대체된 12개(통합 번호로 옮긴다) 또는 RFC-0066~0077에 드는 첫 번호로 묶는다. 그 밖의 번호는 건너뛴다. 드는 번호가 없으면 마지막 "그 밖" 묶음이다. 묶음 안 순서는 블랙보드 순서다.

**RFC-0066 (Supersedes RFC-0001) — 25건**

- [t2] RFC-0001 §노드 카탈로그 — RFC-0015 and RFC-0016 name `§Appendix A/A.4 Node catalogue`, which is no single section (부록 A.4 is the constrained-decoding subset; the catalogue is §노드 카탈로그, where RFC-0001's own Updated-by and pointer lines place both), and give a delta, not a final text (rule 4); applied in their own words per C1 (Assignment block, Event.source schedule block) — rfcs/0015-value-semantics.md:6, :172; rfcs/0016-time-and-schedule-semantics.md:6, :165; rfcs/0001-semantic-ir.md:7-8, :97-98, :220
- [t2] RFC-0001 §공통 필드, §노드 카탈로그, §부록 A: 직렬화 — the kind count `21` is stale (22 table rows after RFC-0056 plus Assignment from RFC-0015 = 23 kinds) and is carried verbatim in three places: the `kind` cell (`21개 PascalCase 식별자`), the catalogue lead (`21개 kind`) and A.4 (`anyOf 21분기`) — rfcs/0001-semantic-ir.md:73, :105, :225; rfcs/0015-value-semantics.md:172
- [t2] RFC-0001 §부록 A: 직렬화 (A.4) — `anyOf 21분기 — oneOf는 사용하지 않는다` conflicts with RFC-0016 §4 `Event.source가 두 분기의 oneOf가 된다` (now carried in the same RFC-0066) and with the kind count — rfcs/0001-semantic-ir.md:225; rfcs/0016-time-and-schedule-semantics.md:165
- [t2] RFC-0001 §노드 카탈로그/Guard — RFC-0054's Updates names RFC-0001 without `(+RFC-0028)` although its Status prose says it names both (rule 5 form) — rfcs/0054-text-equality-guards.md:9, :24-26
- [t2] RFC-0001 §노드 카탈로그 — the RFC-0028, RFC-0054 and RFC-0060 Guard-row texts each say the other rows and the table prose are RFC-0001 verbatim, yet RFC-0015 and RFC-0056 changed the kind set; no updater restates the catalogue intro — rfcs/0028-arithmetic-and-alternative-guards.md:226-228; rfcs/0060-assigned-field-guard-and-otherwise.md:193-195
- [t2] RFC-0001 §노드 카탈로그/Event — RFC-0040 (`Updates: 없음`, rule 1) adds optional field `consume` to the Event IR node and documents bare code `event-consume-cycle` (`warning`); the Event row does not list the field, RFC-0021's table does not list the code, and nothing is carried (C15) — rfcs/0040-event-consumption-contract.md:5-6, :170, :183; impl/lnpl/diagnostics.py:148
- [t2] RFC-0001 §부록 A: 직렬화 and §노드 카탈로그 — Accepted body edited in place after 2026-07-31 by commits 95eafee (2026-08-04: A.6, Refinement row, kind count 20 -> 21) and 55ae27c (2026-08-05: preset `Url` -> `URL`); no updater replaced those units, so kept per C5 — rfcs/0001-semantic-ir.md:120, :281, :317, :327
- [t2] RFC-0001 §노드 카탈로그/WorkflowStep — RFC-0015 §2 says Assignment is a WorkflowStep child Effect, but the WorkflowStep row (RFC-0056 final text) does not list Assignment among allowed children — rfcs/0015-value-semantics.md:172; rfcs/0056-fail-business-rejection.md:122
- [t2] RFC-0001 §노드 카탈로그/NetworkCall — RFC-0027 (Accepted, no Updates entry naming RFC-0001) adds optional `result` to nodeNetworkCall; the NetworkCall row does not list it and nothing is carried (C15) — rfcs/0027-network-driver-and-result-binding.md:273-277; schemas/lir.schema.json:1082
- [t2] RFC-0001 §노드 카탈로그/RepositoryCall and RFC-0021 §코드 → 등급 (정본) — RFC-0038 (Accepted, no Updates entry naming RFC-0001 or RFC-0021) adds `predicate`, `order` and `limit` to nodeRepositoryCall and documents bare code `predicate-not-pushed-down` (`info`); neither the row nor the table lists them and nothing is carried (C15) — rfcs/0038-list-where-predicate.md:137-148, :160-162, :223; schemas/lir.schema.json:1159, :1190, :1206; impl/lnpl/diagnostics.py:152
- [t2] RFC-0001 §노드 카탈로그 (RFC-0015 §2 Assignment block) — RFC-0047 (Accepted, Updates names only RFC-0045) adds optional `agg_field_type` to nodeAssignment, while the carried Assignment block says `required` is the five fields with `additionalProperties: false`; nothing is carried (C15); the same block is in RFC-0072 §2 — rfcs/0047-aggregate-field-type-carriage.md:122-138; rfcs/0015-value-semantics.md:192; schemas/lir.schema.json:805
- [t2] RFC-0001 §노드 카탈로그/EventEmit — RFC-0049 (Accepted, Updates names only RFC-0002) fixes `payloadMap` as an array of `{field, ref}`, while the EventEmit row calls it `필드 매핑 서술`; nothing is carried (C15) — rfcs/0049-emit-payload-mapping.md:86-101; rfcs/0001-semantic-ir.md:142; schemas/lir.schema.json:1336
- [t2] RFC-0001 §노드 카탈로그/RepositoryCall — RFC-0052 (Accepted, no Updates entry naming RFC-0001) adds optional `lookup` to nodeRepositoryCall; the row does not list it and nothing is carried (C15) — rfcs/0052-lookup-key-clause.md:127-130; schemas/lir.schema.json:1153
- [t2] RFC-0001 §노드 카탈로그/NetworkCall — RFC-0057 (Accepted, Updates names only RFC-0027) adds optional `bodyMap` to nodeNetworkCall and lists `result`, `path_args`, `bodyMap` as its optional fields; the row lists `protocol`, `operation` only and nothing is carried (C15) — rfcs/0057-body-mapping-clause.md:125-131; schemas/lir.schema.json:1085, :1091
- [t2] RFC-0001 §노드 카탈로그/RepositoryCall — RFC-0062 (Accepted, no Updates entry naming RFC-0001) adds optional `cached` to nodeRepositoryCall; the row does not list it and nothing is carried (C15) — rfcs/0062-cached-read-through-clause.md:118-121; schemas/lir.schema.json:1156
- [t2] RFC-0001 §노드 카탈로그 — RFC-0059 (Accepted, Updates names only RFC-0025) adds keys `aggTerms` and `listTerm` to the `Response` node and makes `refs` optional; `Response` is a kind the catalogue does not list, and nothing is carried (C15) — rfcs/0059-respond-aggregate-and-list-terms.md:142-151; schemas/lir.schema.json:822
- [t2] RFC-0001 §노드 카탈로그 — the IR schema defines kinds `Response` and `Expose` that no RFC introduced (commits 30244c9, issue #96 and 26c6bcc, issue #99); the catalogue says its four tables are every kind and that adding a row is a revision of this RFC — rfcs/0001-semantic-ir.md:105; schemas/lir.schema.json:822, :1491
- [t2] RFC-0001 §공통 필드 — RFC-0024 (Accepted, Updates names only RFC-0023 §5) adds optional `line` to every IR node kind, while the carried §공통 필드 says `이 4개 외의 공통 필드는 없다`; nothing is carried (C15) — rfcs/0024-enforcement-diagnostic-line.md:6-8, :95-97; rfcs/0001-semantic-ir.md:69
- [t2] RFC-0001 §노드 카탈로그/NetworkCall and RFC-0021 §코드 → 등급 (정본) — RFC-0037 (Accepted, Updates names only RFC-0027 §1) adds optional `path_args` to the NetworkCall IR node and documents bare code `retry-on-non-idempotent` (`warning`); neither the row nor the table lists them and nothing is carried (C15) — rfcs/0037-http-resilience.md:72, :200; schemas/lir.schema.json:1085; impl/lnpl/diagnostics.py:139
- [t2] RFC-0001 §노드 카탈로그 and RFC-0021 §코드 → 등급 (정본) — RFC-0039 (`Updates: 없음`) adds IR node kind `Annotation` (live in the interpreter, absent from the IR schema) and bare code `note-cap-exceeded` (`warning`); neither the catalogue nor the table lists them and nothing is carried (C15) — rfcs/0039-note-verb-and-canonical-line.md:6, :140-147, :157; impl/lnpl/interp.py:2107, :2807; impl/lnpl/diagnostics.py:142
- [t2] RFC-0001 §노드 카탈로그/Entity and RFC-0021 §코드 → 등급 (정본) — RFC-0055 (Accepted, Updates names only RFC-0030) adds `fill_source` to the Entity `fields` items (`fieldList`) and specifies bare code `derived-never-assigned` (`warning`) in its §5; the carried Entity row (RFC-0053 §2) and the table list neither and nothing is carried (C15) — rfcs/0055-injected-now-and-generated-id-field-markers.md:138-139, :200; schemas/lir.schema.json:163; impl/lnpl/diagnostics.py:115
- [t2] RFC-0001 §노드 카탈로그/Guard — RFC-0060 §3 says its final text includes RFC-0028 §3 and RFC-0054 §2 text but carries only its own paragraph after the row, silently omitting the RFC-0028 `alternatives` paragraph and the RFC-0054 `textEqualityOperands` paragraph; both kept per U2/C12/C18 after the Behavior table, with RFC-0060's paragraph — rfcs/0060-assigned-field-guard-and-otherwise.md:193-195, :201-205; rfcs/0028-arithmetic-and-alternative-guards.md:234-240; rfcs/0054-text-equality-guards.md:153-156
- [t2] RFC-0001 §노드 카탈로그/Guard (C18 paragraphs) — the carried paragraphs cite their own RFC's sections without an RFC number (`§Reference-level Specification/6` of RFC-0028, `§5 4항` of RFC-0060), which inside RFC-0066 resolve to sections that do not hold that content; kept as written (R3 allows no rewrite) — rfcs/0028-arithmetic-and-alternative-guards.md:236; rfcs/0060-assigned-field-guard-and-otherwise.md:205
- [t2] RFC-0001 §노드 카탈로그 — re-pointing `RFC-0002가` (R3(a) token rewrite) yields `RFC-0067가`, whose particle no longer agrees with the number as read (0067 ends in a consonant → 이); kept, since R3 allows only the number change — rfcs/0001-semantic-ir.md:107; rfcs/0066-semantic-ir-v2.md:111
  - **t9 처리 (2026-10-29):** 고쳤다 — C26 정정으로 rfcs/0066-semantic-ir-v2.md:111은 이제 `RFC-0067이`다. 위의 "kept"는 t2가 기록한 시점의 처리다.
- [t9] RFC-0048 Updates block spans l.6-16 at 67af189 (plan text said l.6-15); replaced by text anchor ("- Updates: RFC-0001 §Open Questions/1, " through "  RFC-0045 §Open Questions/1"), same result — rfcs/0048-collections-non-goal-and-rowset-group-by.md:6

**RFC-0067 (Supersedes RFC-0002) — 21건**

- [t1] F1 RFC-0002 §Status — Updated-by: RFC-0009 names only §Open Questions; RFC-0009 also updates §Workflow body & control/가드 라인 — rfcs/0002-syntax.md:7, rfcs/0009-guard-condition-open-question.md:6
- [t1] F2 RFC-0002 §Open Questions item 3 — commit 95eafee (2026-08-04) added the 해소 note in place, after RFC-0009 (Accepted 2026-08-02) had replaced the section; RFC-0009's text still has item 3 unresolved. Kept the in-place note per C5 — rfcs/0009-guard-condition-open-question.md:81-83 vs rfcs/0002-syntax.md:705-714; commit 55ae27c (2026-08-05) further edited item 3 in place (Url→URL), also kept (C5) — rfcs/0002-syntax.md:712
- [t1] F3 RFC-0002 §Open Questions item 4 — still says only ms, s, m with h and d undecided; RFC-0016 §1 added h and d — rfcs/0009-guard-condition-open-question.md:84-86, rfcs/0016-time-and-schedule-semantics.md:96
- [t1] F4 RFC-0002 §Workflow body & control — the StepLine bullet caps a step at 4 tokens; RFC-0049 made StepLine Verb Word* without naming this section (rule 2) — rfcs/0002-syntax.md:302-307, rfcs/0049-emit-payload-mapping.md:205
- [t1] F5 RFC-0002 §Workflow body & control/가드 라인 — the RFC-0009 text says Condition is Presence or Comparison and knows no or-line or otherwise; stale against RFC-0050/0028/0060 — rfcs/0009-guard-condition-open-question.md:96-100
- [t1] F6 RFC-0002 §Lexical — Comparison/Comparator (4 operators) and the ms/s/m unit catalogue are stale against the effective §Full grammar; no updater names §Lexical — rfcs/0002-syntax.md:196-200
- [t1] F7 RFC-0002 §예약어 — RFC-0008 §1 reserves exists/missing and RFC-0050 §1 reserves is-numeric/is-not-numeric without naming §예약어 — rfcs/0008-guard-conditions.md:79, rfcs/0050-numeric-guard-predicate.md:139
- [t1] F12 RFC-0002 §부록 A — A.2 counts and maps 58 productions; the consolidated §Full grammar has more, with no mapping rows (no updater named 부록 A) — rfcs/0002-syntax.md:463, 531
- [t1] F13 RFC-0002 §Full grammar — DurationUnit is orphaned by the RFC-0015/0016 Duration form — rfcs/0002-syntax.md:402-403
- [t1] F19 RFC-0002 §Full grammar (consolidated) — Guard and AltGuard (RFC-0028 §1), AssignStep (RFC-0025 §2) and RepoStepLine (RFC-0052/0062 §1) are not reachable from SourceFile; WhenGuard and Guard both define the when line and are linked only by the RFC-0060 §4 sentence — rfcs/0002-syntax.md:372-377, rfcs/0028-arithmetic-and-alternative-guards.md:152, rfcs/0060-assigned-field-guard-and-otherwise.md:212-213
- [t1] F25a RFC-0002 §Lexical — 타입명 bullet (TypeName = BaseTypeName + RefinedTypeName, name resolution) added in place by 95eafee; kept (C5) — rfcs/0002-syntax.md:184-195
- [t1] F25b RFC-0002 §Keywords — keyword rows for refine and of, the 6-kind sentence and the facet-name paragraph edited in place by 95eafee; kept (C5) — rfcs/0002-syntax.md:207,210,212-217
- [t1] F25c RFC-0002 §Declarations — refine declaration row and bullet added in place by 95eafee; kept (C5) — rfcs/0002-syntax.md:267,273-274,276
- [t1] F25d RFC-0002 §Full grammar — Declaration's RefineDecl alternative, RefineDecl, FacetLine, the TypeName/BaseTypeName/RefinedTypeName split, Regex, Number, EnumValue and the note sentences added in place by 95eafee; kept (C5) — rfcs/0002-syntax.md:334,344-347,392-393,397-400,412-419
- [t1] F25e RFC-0002 §부록 A — the A.2 production count, the Declaration, RefineDecl, FacetLine, TypeName, BaseTypeName, RefinedTypeName, Regex, Number and EnumValue mapping rows and the 집계 counts edited in place by 95eafee; kept (C5) — rfcs/0002-syntax.md:463,469,477-478,515-520,528-531
- [t1] F26 commit 55ae27c (2026-08-05) renamed the preset Url to URL in place in RFC-0002 §Declarations; kept (C5) — rfcs/0002-syntax.md:275 (its second hunk, line 712, is in Open Questions item 3, recorded with F2)
- [t1] F27 commit b96f50e (2026-08-02) rewrapped RFC-0002 §Workflow body & control / 가드 라인 in place to add the inline marker "(`Condition` 부분은 갱신됨: RFC-0009)"; not carried, because RFC-0009's bullet replaces the whole item (D2) — rfcs/0002-syntax.md:308-309
- [t1] F29 commit 8d3a8b9 (2026-07-31 13:06, after the 9712ea2 Accepted promotion at 11:23 the same day) edited RFC-0002 §부록 A in place: the EventEmit verb-dictionary row and the "2026-07-31 구현" goal note; content is RFC-0002's own (no updater carries it), so kept (C5). Measured with git blame -s a310017 -- rfcs/0002-syntax.md and git log --format='%h %ci' -1 on both commits — rfcs/0002-syntax.md:505,610-615
- [t1] F32 RFC-0009 §Open Questions item 2 and §Workflow body & control/가드 라인 (carried in RFC-0067) — "`Condition`은 `Presence | Comparison`이다(RFC-0008 §Full grammar)" keeps its old reference (C25a, review r1 F1/F2): re-pointed it would claim RFC-0069 §Full grammar defines Condition as Presence | Comparison, but RFC-0069 carries RFC-0050 §1's `Condition ::= Presence | Term ('and' Term)*`; the sentence's staleness is F5/F23 — rfcs/0009-guard-condition-open-question.md:74,99; rfcs/0067-syntax-v2.md:349,423,939
- [t1] F33 RFC-0060 §5 (carried as RFC-0067 §Block structure) — "가드와 `otherwise`는 항목 하나만 소유하므로(RFC-0008 §5.2)" cites RFC-0008 §5.2, which is the example "5.2 Guarded Workflow: guarded.lnpl" under §Examples, not a rule section; re-pointed to RFC-0069 §5.2 (the cited content is unchanged) — rfcs/0060-assigned-field-guard-and-otherwise.md:257; rfcs/0008-guard-conditions.md:209; rfcs/0067-syntax-v2.md:258
- [t9] C26 sweep (particles.py 66 77, 55 hits) fixed 1 re-point mismatch rfcs/0066-semantic-ir-v2.md:111 RFC-0067가->RFC-0067이; 3 RFC-0059이 left (not re-points, C6 shared span) — rfcs/0068-runtime-v2.md:343, rfcs/0070-execution-scope-v2.md:158, rfcs/0075-row-sets-and-aggregation-v2.md:287

**RFC-0068 (Supersedes RFC-0003) — 12건**

- [t3] RFC-0003 §Guard — the section pointer names only RFC-0008, while the Updated-by header and RFC-0012's Updates also name RFC-0012 — rfcs/0003-runtime.md:153@a310017, rfcs/0003-runtime.md:7@a310017
- [t3] RFC-0003 body — implementation commits edited the Accepted body in place (the Concurrency paragraph, the Transaction/EventEmit/rollback rows and the timeline C node copy updater text; the parallel row carries an "(RFC-0041)" suffix the updater row lacks; RFC-0013's retry-ceiling paragraphs never reached the body); RFC-0068 takes each updater's own text (C5); the notes added by a8f204c (with RFC-0041) and 362a5a8 (with RFC-0029) are pointer-class and not carried (C21) — rfcs/0003-runtime.md:107-113@a310017, rfcs/0003-runtime.md:144-149@a310017, rfcs/0003-runtime.md:195@a310017, rfcs/0013-step-attempt-ceiling.md:68-85
- [t3] RFC-0068 §Guard — guard runtime semantics now sit byte-identical in RFC-0068 §Guard, RFC-0069 §2 and RFC-0071 §2, and G12 in RFC-0068 §Guard and RFC-0070 (C6); a later Updates of one copy must name every copy — rfcs/0008-guard-conditions.md:91@a310017, rfcs/0012-execution-scope.md:102@a310017
- [t3] RFC-0068 §Guard (kept paragraph, C12) — "`condition`의 문법은 RFC-0002 Open Questions ②가 소유한다" is stale: Open Questions ② is resolved and points to RFC-0008 §Full grammar; kept with its old reference (C25a) — rfcs/0003-runtime.md:174@a310017, rfcs/0067-syntax-v2.md:938@e961b73
- [t3] RFC-0068 §Guard (kept paragraph, C12) — "(RFC-0002 부록 A.2 P10)": no P10 label exists in RFC-0002 or RFC-0067 (grep -c P10 rfcs/0002-syntax.md -> 0); re-pointed to RFC-0067 부록 A.2, whose RepeatGuard row states the rule — rfcs/0003-runtime.md:172@a310017, rfcs/0067-syntax-v2.md:737@e961b73
- [t3] RFC-0068 §Guard — the three kept RFC-0003 paragraphs follow the last carried heading (#### G12.7) and so read as part of G12.7; brief R3 allows no new heading, so the structure is recorded, not fixed — rfcs/0003-runtime.md:155-157@a310017, rfcs/0003-runtime.md:170-177@a310017
- [t3] RFC-0068 §Motivation, §Observability — the quotations of RFC-0001 ("실행 의미(순서·실패·재시도의 동작)는 RFC-0003이 정의한다", "마스킹 의무 — 런타임 계약은 RFC-0003") and their attributions are kept as written (C4 provenance), while RFC-0066 now reads RFC-0068 at the quoted places — rfcs/0003-runtime.md:20-22@a310017, rfcs/0003-runtime.md:34-35@a310017, rfcs/0003-runtime.md:282-283@a310017, rfcs/0066-semantic-ir-v2.md:111@e961b73, rfcs/0066-semantic-ir-v2.md:231@e961b73
- [t3] RFC-0003 §Guard — the target's mode table is not carried (RFC-0008 §2.3 restates it, C14); the intro paragraph is kept in RFC-0068 §Guard (C30(b)): its second sentence ("…항목 자체의 의미는 건드리지 않는다") is stated nowhere else and contradicted by nothing — RFC-0008 §Guide-level Explanation states only 실행 여부·횟수, and RFC-0060 §3's otherwise item (children[1]) leaves one guarded item — rfcs/0003-runtime.md:155-163@a310017, rfcs/0008-guard-conditions.md:32@a310017, rfcs/0060-assigned-field-guard-and-otherwise.md:201
- [t3] RFC-0003 §Guard — the until-bounds paragraph is not carried into RFC-0068: its "둘 중 하나라도 없으면 종료가 보장되지 않는다" is contradicted by RFC-0014 §2.2 (the round cap applies when no timeout is declared) and RFC-0008 §3.3 (mode B terminates on the round cap alone) (C12, C14, C30(a)) — rfcs/0003-runtime.md:165-168@a310017, rfcs/0014-guard-skip-observability.md:109@a310017, rfcs/0008-guard-conditions.md:176@a310017
- [t3] RFC-0068 (carried updater text) — bare self-references now read as RFC-0068's: "이 RFC가 새로 정하는 상수" (RFC-0027 §5), "이 RFC의 관할이 아니다" (RFC-0029), "(§실행 경계)" (RFC-0032); kept as written (C26(b)) — rfcs/0027-network-driver-and-result-binding.md:376, rfcs/0029-clock-contract-and-real-binding.md:91-92, rfcs/0032-transaction-boundary-and-rollback-enforcement.md:207
- [t3] RFC-0068 §Guard parts (a) and (b) (copied spans) — bare self-references now read as RFC-0068's: "§Reference-level Specification/1", "/3", "/5", "/6" and "§3의 평탄화된 값" (from RFC-0028, RFC-0060 and RFC-0027 text via RFC-0071 §2), and "이 RFC가 처음 …" (three times), "이 RFC 이전에" and "이 RFC가 바꾸지 않는다" (RFC-0012's own text via RFC-0070 G12); kept as written so C6 holds (C26(b), C30(d)) — rfcs/0071-guard-skip-observability-v2.md:87-210, rfcs/0070-execution-scope-v2.md:148, rfcs/0070-execution-scope-v2.md:161, rfcs/0070-execution-scope-v2.md:179, rfcs/0070-execution-scope-v2.md:206, rfcs/0070-execution-scope-v2.md:318
- [t3] RFC-0003 (C15 drift, best-effort sweep) — RFC-0015 §4 states runtime value-failure semantics "RFC-0003 실행 의미에 종속" without an Updates entry naming RFC-0003; no text is folded in — rfcs/0015-value-semantics.md:225-232@a310017

**RFC-0069 (Supersedes RFC-0008) — 12건**

- [t1] F8 RFC-0008 §1 — says RFC-0002 already defines the six-operator Comparator set; RFC-0002 defines four — rfcs/0008-guard-conditions.md:81, rfcs/0002-syntax.md:404
- [t1] F15 RFC-0008 §1 기각된 형태 — still lists 논리 결합 (and, or, not) as rejected, while RFC-0015 §1 added and and RFC-0028 §1 added or; no later source replaces this list, so it is kept (U2) — rfcs/0008-guard-conditions.md:86
- [t4] RFC-0008 §Examples — RFC-0046 names the whole §Examples but replaces only the §5.2 code block, and does not name RFC-0017, the earlier updater of §5.2 (rule 5) — rfcs/0046-rfc-example-realignment.md:6, rfcs/0046-rfc-example-realignment.md:140-142, rfcs/0017-guarded-example-correction.md:6
- [t4] RFC-0008 §1 — RFC-0015 and RFC-0016 update it without naming RFC-0012, its earlier updater (rule 5) — rfcs/0015-value-semantics.md:6, rfcs/0016-time-and-schedule-semantics.md:6, rfcs/0012-execution-scope.md:6
- [t4] RFC-0008 §1 — RFC-0025 §2, RFC-0028 §1, RFC-0045 §1, RFC-0047 §1 and RFC-0050 §1 change its effective grammar through RFC-0015 §1 without naming RFC-0008 §1 (rule 5); RFC-0069 §1 follows the chain (C2, C13) — rfcs/0025-row-sets-and-aggregation.md:6, rfcs/0028-arithmetic-and-alternative-guards.md:6, rfcs/0045-rowset-aggregation-extension.md:6, rfcs/0047-aggregate-field-type-carriage.md:6, rfcs/0050-numeric-guard-predicate.md:6
- [t4] RFC-0008 §2 — RFC-0022, RFC-0027, RFC-0028, RFC-0050 and RFC-0060 change its effective text through RFC-0014 §2 without naming RFC-0008 §2 (rule 5) — rfcs/0022-mode-b-observation-surface.md:6, rfcs/0027-network-driver-and-result-binding.md:8-9, rfcs/0028-arithmetic-and-alternative-guards.md:8, rfcs/0050-numeric-guard-predicate.md:7-8, rfcs/0060-assigned-field-guard-and-otherwise.md:11
- [t4] RFC-0008 §1 — the kept 기각된 형태 list still rejects 논리 결합 (and, or, not), and RFC-0015 §1's kept limitation bullets say "or·not·괄호 없음" and "곱셈·나눗셈은 없다", while the effective grammar has and (RFC-0050), or-guards (RFC-0028) and * / (RFC-0028); kept (U1, U2) — rfcs/0008-guard-conditions.md:86, rfcs/0015-value-semantics.md:147, rfcs/0015-value-semantics.md:155, rfcs/0028-arithmetic-and-alternative-guards.md:152-155
- [t4] RFC-0008 §5.2 — the kept target bullets describe "when tokenCache missing" and "until retryBudget == 0", which the effective code block (RFC-0046 §2) no longer contains — rfcs/0008-guard-conditions.md:237-241, rfcs/0046-rfc-example-realignment.md:144-175
- [t4] RFC-0008 §Examples — commit a2b504d, which added RFC-0046, also inserted a pointer note into the target body ("RFC-0046 §Reference-level Specification/2가 §5.2를 갱신한다 … 아래 §5.2의 인라인 사본은 … 여전히 컴파일되지 않는다"); it is pointer-class text and is not carried (C21); the lnpl-check skip marker added in place by aa1e9c4 governed the replaced block and is not carried either — rfcs/0008-guard-conditions.md:201-203, rfcs/0008-guard-conditions.md:216
- [t4] RFC-0069 and RFC-0070, carried updater text — relative references that pointed into their source RFC (bare §N, §Motivation, §Guide-level Explanation, "이 RFC") now read as pointing into RFC-0069 or RFC-0070; kept as written (brief R3 allows no rewrite; C26(b)). The relation-only sentence of rfcs/0025:224 is not among them: it is dropped (C23). Examples: RFC-0050 §1 "(§4)", RFC-0025 §5 "(§7)", RFC-0027 §4 "§Guide-level Explanation", RFC-0060 §6/§7 "§Reference-level Specification/N" (whose note "인용 안의 … RFC-0028을 가리킨다" is relation text and is not carried) — rfcs/0050-numeric-guard-predicate.md:133, rfcs/0025-row-sets-and-aggregation.md:236, rfcs/0027-network-driver-and-result-binding.md:357, rfcs/0060-assigned-field-guard-and-otherwise.md:304, rfcs/0060-assigned-field-guard-and-otherwise.md:344-345
- [t4] RFC-0008 §Open Questions 3 and RFC-0012 §Open Questions — both still treat 논리 결합 (and/or) as open ("Presence와 Comparison만으로는 복잡한 조건을 표현할 수 없다"; "RFC-0008 §Open Questions 3이 계속 추적하며"), while the effective grammar has and (RFC-0015, RFC-0050) and or-guards (RFC-0028); kept (U1), best-effort — rfcs/0008-guard-conditions.md:259, rfcs/0012-execution-scope.md:305-306, rfcs/0028-arithmetic-and-alternative-guards.md:152-153
- [t3] RFC-0008 §2 — replaced RFC-0003 §Guard whole and silently dropped its intro paragraph (the guard changes only whether and how often its item runs), its repeat-vs-Policy.retry rule and its unevaluable-condition rule; the three are kept as RFC-0068 §Guard's last three paragraphs (C12(2), C30(b)); RFC-0014's Status prose still calls the RFC-0003 §Guard body consistent with the live contract — rfcs/0003-runtime.md:155-157@a310017, rfcs/0003-runtime.md:170-177@a310017, rfcs/0014-guard-skip-observability.md:13-17@a310017

**RFC-0070 (Supersedes RFC-0012) — 18건**

- [t1] F16 RFC-0012 RFC-0008 §1 subsection — states a delta ("기각 목록에 한 항목을 더한다") instead of final text (rule 4); applied as stated per C1 — rfcs/0012-execution-scope.md:96
- [t4] RFC-0012 §G12.4 — the Status block lists RFC-0025 as an updater of §G12.4, but the section carries no "> 갱신됨: RFC-0025" pointer line — rfcs/0012-execution-scope.md:7, rfcs/0012-execution-scope.md:147-151
- [t4] RFC-0012 §G12.5 ⓒ — RFC-0025 §6.2 removed query from ⓒ; RFC-0030 §3 and RFC-0052 §2 put it back while RFC-0030 states no earlier revision touched §G12.5. RFC-0070 carries RFC-0052's row (latest) and keeps RFC-0025's "query를 뺀 이유" paragraph, which now contradicts it — rfcs/0025-row-sets-and-aggregation.md:287, rfcs/0025-row-sets-and-aggregation.md:291, rfcs/0030-create-result-binding-and-payload-seed.md:15-16, rfcs/0030-create-result-binding-and-payload-seed.md:156, rfcs/0052-lookup-key-clause.md:145
- [t4] RFC-0012 §G12.2 — RFC-0059 replaces a bullet RFC-0025 §5 carried into §G12.2 without naming RFC-0012 §G12.2 (rule 5); RFC-0070 carries its text (C8) — rfcs/0059-respond-aggregate-and-list-terms.md:6-9, rfcs/0059-respond-aggregate-and-list-terms.md:159-161
- [t4] RFC-0012 §RFC-0008 §Reference-level Specification / 1. Full Grammar — states a delta ("기각 목록에 한 항목을 더한다") instead of final text (rule 4); applied as stated (C1) — rfcs/0012-execution-scope.md:91-96
- [t4] RFC-0012 §G12.2 — RFC-0027 §4, RFC-0030 §2 and RFC-0052 §2 state deltas over earlier text ("규칙은 RFC-0025 §5 그대로다", "네 번째 갈래를 더하고 create 행만 고친", "다섯 이름공간의 규칙은 … 손대지 않는다") instead of whole final text (rule 4); applied per C1 — rfcs/0027-network-driver-and-result-binding.md:347-348, rfcs/0030-create-result-binding-and-payload-seed.md:110-114, rfcs/0052-lookup-key-clause.md:134-138
- [t4] RFC-0012 §G12.2 — RFC-0052 §2 replaces only the single-row 바인딩 값 sentence; RFC-0070 drops RFC-0025 §5's bullet "바인딩 값은 저장소가 돌려준 행이다", carries RFC-0052's sentence as its own paragraph after the single-row list, and carries "update/delete는 by가 있어도 바인딩하지 않는다" as the last paragraph of §G12.2 — rfcs/0052-lookup-key-clause.md:135-138, rfcs/0025-row-sets-and-aggregation.md:228
- [t4] RFC-0012 §G12.4, §G12.5, §G12.6 — RFC-0025 §6.1/§6.2, RFC-0030 §3 and RFC-0052 §2/§6 replace single rows or append paragraphs instead of giving final text (rule 4); applied per C1 — rfcs/0025-row-sets-and-aggregation.md:250-253, rfcs/0025-row-sets-and-aggregation.md:281, rfcs/0030-create-result-binding-and-payload-seed.md:150-152, rfcs/0052-lookup-key-clause.md:140-141, rfcs/0052-lookup-key-clause.md:240
- [t4] RFC-0012 §G12.2 (brief R7) — RFC-0048-only wording not carried: RFC-0052's "**§G12.2 (RFC-0048 §4의 최종 텍스트 위에).** 다섯 이름공간의 규칙은 이 개정이 손대지 않는다." and RFC-0059's "RFC-0048 §4가 더한 다섯 번째 이름공간은 그대로다"; the remaining §G12.2 stays coherent on RFC-0030 §2's four namespaces — rfcs/0052-lookup-key-clause.md:134-135, rfcs/0059-respond-aggregate-and-list-terms.md:155-157
- [t4] RFC-0012 §G12.2 — RFC-0025 §5's final text restates the target bullets without three sentences (the OrderItem example with the node-id rationale; "until 루프의 각 라운드는 직전 라운드가 갱신한 값을 본다"; "실행 후의 엔티티 상태는 … rows <N>이 관측한다"); these are revisions inside restated units and are not spliced back (C14) — rfcs/0012-execution-scope.md:127-135, rfcs/0025-row-sets-and-aggregation.md:226-229, rfcs/0025-row-sets-and-aggregation.md:243-244
- [t4] RFC-0012 §RFC-0002 §Full grammar / Condition — with its four productions at their latest text (C10), the block references Term, NumericPred, Value and Namespace, which it does not define, and its kept target sentence still says the other productions are RFC-0002's original text — rfcs/0012-execution-scope.md:75-82, rfcs/0050-numeric-guard-predicate.md:117-120, rfcs/0015-value-semantics.md:124, rfcs/0015-value-semantics.md:131
- [t4] RFC-0012 §G12.1 — its table still gives the qualified form as CamelName '.' CamelName, while RFC-0015 §1 changed Reference to Namespace '.' CamelName without naming §G12.1 (no Updates relation, C15) — rfcs/0012-execution-scope.md:115, rfcs/0015-value-semantics.md:131-132
- [t4] RFC-0012 §G12.1 (C15 drift, best-effort sweep) — RFC-0054 adds a place where a bare name resolves (a bare name paired with a Text-like field in an equality term) without an Updates entry naming RFC-0012 §G12.1; no text is folded in — rfcs/0054-text-equality-guards.md:40-42, rfcs/0054-text-equality-guards.md:164, rfcs/0012-execution-scope.md:110-115
- [t4] RFC-0012 §G12.2 — RFC-0027 §4 restates RFC-0025 §5's lead paragraph and silently omits two stand-alone sentences ("`Aggregate`의 `Reference`(§2)는 언제나 RowSet 바인딩을 본다." and "두 문법 위치가 겹치지 않으므로 충돌은 없다 — … 넓힌 것이다."), and RFC-0030 §2 keeps the shorter form; RFC-0070 keeps both sentences after the lead paragraph (U2, C14, C22) — rfcs/0025-row-sets-and-aggregation.md:218-221, rfcs/0027-network-driver-and-result-binding.md:339-345, rfcs/0030-create-result-binding-and-payload-seed.md:118-125
- [t4] RFC-0012 §G12.2 (C14 revision) — RFC-0027 §4's restatement of RFC-0025 §5's lead (kept by RFC-0030 §2) drops the clause "둘은 같은 바인딩 이름(엔티티의 camelCase 선언 이름)을 공유하지만, **어느 쪽이 해석되는지는 참조가 나타나는 문법 위치가 결정한다**: `Condition`/`expect result`의 `<binding>.<field>`(RFC-0012 §G12.1)는 언제나 단일 행 바인딩을 본다" (source bold kept); it is a revision inside a restated sentence and is not spliced back. RFC-0070 §G12.2's lead still names the `<binding>.<field>` position but no longer says that `Condition`/`expect result` references in it always read the single-row binding, so the kept sentence "두 문법 위치가 겹치지 않으므로 충돌은 없다" (C22) contrasts the Aggregate position with a position the text no longer ties to those references — rfcs/0025-row-sets-and-aggregation.md:214-218, rfcs/0027-network-driver-and-result-binding.md:341-342, rfcs/0025-row-sets-and-aggregation.md:219
- [t4] RFC-0012 §G12.4 — the kept last paragraph from RFC-0025 §6.1 says G12.5 ⓒ now blocks a qualified reference to an entity the workflow only queries ("§6.2(G12.5 ⓒ)가 `query`만 있고 `read`가 없는 엔티티로의 한정 참조 자체를 컴파일 거부로 막은 뒤로는"), but the effective ⓒ row (RFC-0052 §2, via RFC-0030 §3) admits query again; kept (U1), best-effort, same root as F02 — rfcs/0025-row-sets-and-aggregation.md:269-277, rfcs/0052-lookup-key-clause.md:145
- [t8] update_targets now reads an Updates value starting with 없음, 해당 없음, none or n/a (any case, optional * _ backtick or parentheses) as empty; a prose value such as "None of these … RFC-0012" would therefore have no targets — no RFC in the corpus has one (sweep of 69 rfcs: 0 changed targets)
- [t3] RFC-0012 §RFC-0003 §Guard — the final text is not self-contained (rule 4: its lead defers to RFC-0008's iteration semantics) and the Updates entry does not name RFC-0008 §2, the earlier updater (rule 5); the lead is relation text and is not carried into RFC-0068 (C3) — rfcs/0012-execution-scope.md:6@a310017, rfcs/0012-execution-scope.md:104-106@a310017

**RFC-0071 (Supersedes RFC-0014) — 6건**

- [t3] RFC-0014 §Examples — no section pointer names RFC-0046; a note added by a2b504d (the commit that added RFC-0046) stands in and is not carried (C21) — rfcs/0014-guard-skip-observability.md:188-190@a310017
- [t3] RFC-0071 (carried updater text) — bare self-references now read as RFC-0071's: "§Reference-level Specification/1", "/5", "/6" (RFC-0028's sections, inside RFC-0060 §6·§7 and RFC-0028 §4 text), "§3의 평탄화된 값" (RFC-0027 §3), "이 RFC의 §2.4" (RFC-0056 §8; RFC-0056 has no §2.4); kept as written (C26(b)) — rfcs/0060-assigned-field-guard-and-otherwise.md:308, rfcs/0060-assigned-field-guard-and-otherwise.md:363, rfcs/0028-arithmetic-and-alternative-guards.md:313-314, rfcs/0027-network-driver-and-result-binding.md:402, rfcs/0056-fail-business-rejection.md:237
- [t3] RFC-0071 §Motivation — "RFC-0008 §2.1은 … §2.2의 `until`에는 같은 의무가 없다" describes the state before RFC-0014; kept as written (C25: re-pointed to RFC-0069 it would be false, RFC-0069 §2.2 carries the obligation) — rfcs/0014-guard-skip-observability.md:37-40@a310017
- [t3] RFC-0071 §Reference-level Specification — the target's lead "아래는 RFC-0008 §Reference-level Specification/2 … 치환한 최종 텍스트다" is RFC-0014's relation prose; kept as written (C4); re-pointed it would claim RFC-0071 replaces RFC-0069 §2, which no Updates entry says (C25) — rfcs/0014-guard-skip-observability.md:80-82@a310017
- [t3] RFC-0014 §2.4 (C15 drift, best-effort sweep) — RFC-0051 fixes the shape of Money values in `evaluations` without an Updates entry naming RFC-0014; no text is folded in — rfcs/0051-money-arithmetic-in-set-and-guards.md:256
- [t3] RFC-0014 §2.4 (C15 drift, best-effort sweep) — RFC-0054 adds text-equality terms to `evaluations` without an Updates entry naming RFC-0014; no text is folded in — rfcs/0054-text-equality-guards.md:169

**RFC-0072 (Supersedes RFC-0015) — 9건**

- [t1] F22 RFC-0015 §1 — the bullets "`or`·`not`·괄호 없음" and "곱셈·나눗셈은 없다" are stale against RFC-0028 §1 (or-guards, `*`, `/`), which did not name these paragraphs; kept (U2) — rfcs/0015-value-semantics.md:147,155
- [t5] RFC-0015 §1 — the restriction bullet "`or`·`not`·괄호 없음" is kept as target text but is stale against RFC-0028 §1's `AltGuard` (or-guards); RFC-0028 replaced only the Guard and ArithOp productions — rfcs/0015-value-semantics.md:147-150, rfcs/0028-arithmetic-and-alternative-guards.md:152-153
- [t5] RFC-0015 §1 — the restriction bullet sentence "곱셈·나눗셈은 없다(§Alternatives)" is kept as target text but is stale against RFC-0028 §1's four-operator ArithOp — rfcs/0015-value-semantics.md:154-155, rfcs/0028-arithmetic-and-alternative-guards.md:155
- [t5] RFC-0015 §1 — RFC-0016 §1 widened Duration to h and d without naming RFC-0015 §1 (rule 5); RFC-0072 §1 carries RFC-0016's form (C13) — rfcs/0016-time-and-schedule-semantics.md:6,96, rfcs/0015-value-semantics.md:134
- [t5] RFC-0015 §Guide-level Explanation — item 3 "`or`·`not`·괄호는 없다" and the closing paragraph (assigned fields unreadable by later guards; Money and DateTime not comparable) are stale against RFC-0028, RFC-0060, RFC-0016 and RFC-0051; no updater names this section — rfcs/0015-value-semantics.md:86,108-110
- [t5] RFC-0015 §3 — RFC-0051 §2's sentence outside its final-text quote (is-numeric on a declared Money field is rejected) was dropped by RFC-0053 §7, RFC-0054 §7 and RFC-0060 §1 without saying so; RFC-0072 keeps it (U2); its "(§7)" pointed at RFC-0051 §7 and has no target in RFC-0072, and its "RFC-0050(Draft)" label is stale (RFC-0050 is Accepted) — rfcs/0051-money-arithmetic-in-set-and-guards.md:225-226
- [t5] RFC-0015 §Open Questions item 4 — "Decimal/Money 산술. 지금은 정적 거부다." is stale against RFC-0051, which opened Money arithmetic; RFC-0060 restated it unchanged — rfcs/0060-assigned-field-guard-and-otherwise.md:182-183
- [t5] RFC-0072 §1, §3, RFC-0073 §3 — carried updater prose keeps section references relative to its own RFC that resolve to another or no section in the new RFC: "Guide-level Explanation" (0025:145), "§5" and "§Reference-level Specification/2" and "이 RFC" (0047:135,137,141-142), "§Motivation" (0028:169), "(§4)" (0050:133), "(§7)" (0051:226), "이 RFC 이전" (0054:257); not rewritten (brief R3) — rfcs/0025-row-sets-and-aggregation.md:145, rfcs/0047-aggregate-field-type-carriage.md:135-142, rfcs/0028-arithmetic-and-alternative-guards.md:169, rfcs/0050-numeric-guard-predicate.md:133
- [t5] RFC-0015 §Alternatives — "실행 스코프는 엔티티당 행 **하나**를 바인딩한다(RFC-0012 §G12.2)" is kept as written in RFC-0072 (C25): it records the reason aggregation was once left out, and RFC-0070 §G12.2 now also binds a RowSet (RFC-0025 §5), so re-pointing would state something false — rfcs/0015-value-semantics.md:345, rfcs/0025-row-sets-and-aggregation.md:211-221

**RFC-0073 (Supersedes RFC-0016) — 13건**

- [t1] F9 RFC-0016 §1 — TimeOfDay uses Digit, which no production defines — rfcs/0016-time-and-schedule-semantics.md:103
- [t1] F10 RFC-0016 — changes Duration but does not name RFC-0015 §1, which also restates Duration (rule 5 gap) — rfcs/0016-time-and-schedule-semantics.md:6, rfcs/0015-value-semantics.md:134
- [t1] F17 RFC-0016 §1 — the TimeOfDay line carries an ISO-EBNF comment `(* … *)` inside RFC-0002's W3C-EBNF block, which uses `/* … */` — rfcs/0016-time-and-schedule-semantics.md:103
- [t1] F24 RFC-0016 §1 — states a delta ("RFC-0002 §Full grammar와 RFC-0008 §1에서 바뀌는 생산규칙만 적는다") instead of final text (rule 4); applied as stated per C1 — rfcs/0016-time-and-schedule-semantics.md:92
- [t1] F28 RFC-0016 — its Updates entry names only `EventSource`·`Duration` for RFC-0002 §Full grammar, but its §1 block also restates EventDecl (rule 1 naming gap); RFC-0067 takes EventDecl from RFC-0016 §1 (D3) — rfcs/0016-time-and-schedule-semantics.md:6,99
- [t5] RFC-0016 §3 — RFC-0051 §1's 거부 메시지 paragraph outside its quote was dropped by RFC-0053 §6 and RFC-0054 §6 without saying so; RFC-0073 keeps it (U2) — rfcs/0051-money-arithmetic-in-set-and-guards.md:198-204
- [t5] RFC-0016 §3 — RFC-0038 §3 states a delta ("그 끝에 새 절 하나를 더한 것이다") instead of final text (rule 4); later final texts absorbed it — rfcs/0038-list-where-predicate.md:170-174
- [t5] RFC-0016 §3 — RFC-0051 §1 reworded the closing paragraphs of RFC-0038's 3.1, dropping the no-new-rejection clause and the RFC-0025 §Alternatives rationale clause without saying so; not re-inserted (C14) — rfcs/0038-list-where-predicate.md:190-202, rfcs/0054-text-equality-guards.md:266-271
- [t5] RFC-0016 §2, §3 — cite "RFC-0015 §Value domain" and "RFC-0015 §D6", section names RFC-0015 does not have (its §4 is "값 도메인과 실패"; there is no D6); RFC-0073 §2 and §3 carry them (P15 re-points the first to RFC-0072 §Value domain); RFC-0016's Status prose has the same §Value domain citation, which RFC-0073's new Status block does not carry — rfcs/0016-time-and-schedule-semantics.md:116, rfcs/0054-text-equality-guards.md:245, rfcs/0016-time-and-schedule-semantics.md:20
- [t5] RFC-0016 §Examples — commit aa1e9c4 (2026-08-31) added the two `<!-- lnpl-check: ... -->` skip markers in place after acceptance; they are doc-snippet gate markers, not contract text, and RFC-0073 keeps each directly above its fence (C5) — rfcs/0016-time-and-schedule-semantics.md:231,249
- [t5] RFC-0016 §3 — the 거부 메시지 paragraph kept from RFC-0051 §1 (U2) sits at its source anchor, after the end of the §3 final text, which in RFC-0054 §6's text is inside `#### 3.3` (Text 등가); in RFC-0073 it therefore reads under the 3.3 heading although it is about Money and dimension messages — rfcs/0051-money-arithmetic-in-set-and-guards.md:198-204, rfcs/0054-text-equality-guards.md:282-301
- [t4] RFC-0016 §1 — gives only the changed productions ("바뀌는 생산규칙만 적는다") instead of final text for RFC-0008 §1 (rule 4); Duration applied as stated (C1, C13) — rfcs/0016-time-and-schedule-semantics.md:92
- [t4] RFC-0016 §Status — its Updates entry claims an operand-type rule for RFC-0008 §1, but RFC-0016 §1 holds no such text (the rule is RFC-0016 §3), so RFC-0016 contributes only Duration and the h/d paragraph to RFC-0069 §1 — rfcs/0016-time-and-schedule-semantics.md:6, rfcs/0016-time-and-schedule-semantics.md:133

**RFC-0074 (Supersedes RFC-0021) — 10건**

- [t2] RFC-0021 §코드 → 등급 (정본) — RFC-0042 says the section was never updated, but RFC-0022 and RFC-0023 had updated it; its final text silently drops `validation-sample-derived` and `guard-orphaned-steps`; both kept per U2 (live in impl/lnpl/diagnostics.py:95, :100) — rfcs/0042-extension-diagnostics.md:8-10, :128-134; rfcs/0022-mode-b-observation-surface.md:9; rfcs/0023-guard-scope-diagnostic.md:6
- [t2] RFC-0021 §코드 → 등급 (정본) — RFC-0022 and RFC-0023 updates are delta form (`코드 하나를 추가한다`), not final text (rule 4) — rfcs/0022-mode-b-observation-surface.md:9-10; rfcs/0023-guard-scope-diagnostic.md:6-7
- [t2] RFC-0021 §코드 → 등급 (정본), §`--strict[=LEVEL]` — RFC-0042's final text cites RFC-0042's own sections (`Guide-level Explanation, §Motivation`; `"하지 않는 것", Open Questions 1`), which inside RFC-0074 resolve to RFC-0021-derived sections that do not hold that content — rfcs/0042-extension-diagnostics.md:150, :179
- [t2] RFC-0021 §`--strict[=LEVEL]` — no `> 갱신됨: RFC-0042` pointer line although Updated-by names the section — rfcs/0021-diagnostic-severity-levels.md:8, :117
- [t2] RFC-0021 §코드 → 등급 (정본) — RFC-0022 and RFC-0023 add their codes only in Status Updates entries, with no 근거 cell text; per ruling C9 RFC-0074 fills the cell with a citation of the section holding each rationale (RFC-0022 §Guide-level Explanation; RFC-0023 §Reference-level Specification/1. 코드와 등급) — rfcs/0022-mode-b-observation-surface.md:9-10, :61-66; rfcs/0023-guard-scope-diagnostic.md:6-7, :107-110
- [t2] RFC-0021 §코드 → 등급 (정본) — the `authorization-not-verified` row says `info`, but RFC-0035 §D2 (Accepted, no Updates line) records it raised to `warning` by issue #119 and SEVERITY_OF holds `warning`; no Accepted updater named the row, so RFC-0074 carries `info` — rfcs/0042-extension-diagnostics.md:134; rfcs/0035-authorization-enforcement-deferred-scope.md:96-99; impl/lnpl/diagnostics.py:93
- [t2] RFC-0021 §코드 → 등급 (정본) — the table lists 7 of the 23 live bare codes, and the only sentence calling it a sample (`대표 5개 코드 예시`) is RFC-0042 relation text dropped under C3; of the 16 unlisted codes, `unknown-entity`, `event-source-mismatch`, `event-source-orphaned`, `declared-not-bound`, `stored-row-shape-mismatch`, `respond-field-missing`, `guard-scoped-binding-escape`, `spec-result-reads-input` are defined by no Accepted RFC (some are only mentioned in passing), `rollback-escapes-network` is specified by Accepted RFC-0036 and by Draft RFC-0034, and the other 8 (RFC-0036's included) are recorded per RFC below — rfcs/0042-extension-diagnostics.md:120-121; rfcs/0036-policy-rollback-declaration-effect.md:46, :82-84, :126-129; rfcs/0034-network-call-compensation.md:1 (Draft); impl/lnpl/diagnostics.py:83-166
- [t2] RFC-0021 §코드 → 등급 (정본) — RFC-0025 (Accepted, Updates names RFC-0012 and RFC-0015 only) adds bare code `aggregation-orphaned-list` (`warning`); the table does not list it and nothing is carried (C15) — rfcs/0025-row-sets-and-aggregation.md:190-192; impl/lnpl/diagnostics.py:104
- [t2] RFC-0021 §코드 → 등급 (정본) — RFC-0036 (Accepted, Updates names only RFC-0032) specifies bare code `rollback-escapes-network` (`warning`, issue #112); the table does not list it and nothing is carried (C15) — rfcs/0036-policy-rollback-declaration-effect.md:46, :82-84, :126-129; impl/lnpl/diagnostics.py:134
- [t2] RFC-0021 §코드 → 등급 (정본) — RFC-0053 (its Updates name RFC-0001, RFC-0015, RFC-0016, RFC-0038, RFC-0051, not RFC-0021) adds bare code `optional-field-unguarded-arithmetic` (`warning`); the table does not list it and nothing is carried (C15) — rfcs/0053-optional-field-modifier.md:283-285; impl/lnpl/diagnostics.py:161

**RFC-0075 (Supersedes RFC-0025) — 27건**

- [t1] F30 RFC-0025 §2 — the parser distinguishes Aggregate from Value by the first token (`sum`/`count` versus anything else); stale against the five AggFuncs of RFC-0045 §1 / RFC-0047 §1, which did not name this sentence; kept (U2) — rfcs/0025-row-sets-and-aggregation.md:150-152
- [t5] RFC-0025 (C15 drift) — its §3 adds aggregate rejections "RFC-0015 §3 확장과 같은 층위" and it reverses RFC-0015 §Alternatives "집계를 이번 개정에 넣지 않는 이유", with no Updates entry for RFC-0015 §3 or §Alternatives; nothing folded into RFC-0072 — rfcs/0025-row-sets-and-aggregation.md:162-177, rfcs/0015-value-semantics.md:337
- [t6] RFC-0025 §2 — RFC-0028 names RFC-0025 §2 in its Updates but gives final text for none of its units (its own lead says RFC-0025 §2's other productions stay); it contributes no text to RFC-0075 §2 — rfcs/0028-arithmetic-and-alternative-guards.md:6, rfcs/0028-arithmetic-and-alternative-guards.md:145-149, rfcs/0045-rowset-aggregation-extension.md:10-20
- [t6] RFC-0025 §2 — the kept target lead says the section's other productions (`Condition`/`Value`/`Operand`/`ArithOp`/`Reference`/`Namespace`) are RFC-0015's original text; stale since RFC-0028 §1 (ArithOp) and RFC-0050 §1 (Condition) replaced some of them; kept as target prose (C3) — rfcs/0025-row-sets-and-aggregation.md:128-131
- [t6] RFC-0025 §2 — RFC-0075 §2 is a new carrier of t1 F30 (the first-token rule "`sum`/`count` 대 그 밖" is stale against the five AggFuncs of RFC-0047 §1) — rfcs/0025-row-sets-and-aggregation.md:150-152
- [t6] RFC-0025 §1 — RFC-0038 §1 gives text for one sentence (the last sentence of the third paragraph), not final text for the section (rule 4); applied per C1: line 120 is cut after "원칙 그대로)." and RFC-0038's three paragraphs and production block follow — rfcs/0038-list-where-predicate.md:101-105, rfcs/0025-row-sets-and-aggregation.md:120-121
- [t6] RFC-0025 §3 — RFC-0045 §2 restates table row 3 without the target's last sentence ("§4는 엔티티가 선언은 됐지만 **이 워크플로**가 그것을 `list`하지 않은 경우다"); a revision inside a restated row (C14), not spliced back — rfcs/0025-row-sets-and-aggregation.md:173, rfcs/0045-rowset-aggregation-extension.md:152
- [t6] RFC-0025 §3 — RFC-0045 §2's final text starts at the table; the target lead ("`lower`에서 판정한다 …") stays in RFC-0075 §3 because RFC-0045 says that principle is unchanged (U2, C12) — rfcs/0025-row-sets-and-aggregation.md:166-167, rfcs/0045-rowset-aggregation-extension.md:144-146
- [t6] RFC-0025 §1, RFC-0038 §1 — "RFC-0002 §Full grammar의 `StepLine ::= Verb Word? Word? Word? EOL`" is stale since RFC-0049 made it `Verb Word* EOL` (RFC-0067 §Full grammar); kept as written in RFC-0075 §1 and RFC-0077 §1 (C25a: re-pointing would be a false claim) — rfcs/0025-row-sets-and-aggregation.md:117, rfcs/0038-list-where-predicate.md:124-125, rfcs/0049-emit-payload-mapping.md:205
- [t6] RFC-0025 §5 (brief R7) — RFC-0059's Status and §4 lead say Draft RFC-0048 §4 already updated RFC-0025 §5 with a fifth namespace that stays; that wording exists only because of RFC-0048 and is not carried (the lead is relation text, C3); no RFC-0048 text enters RFC-0075 (grep -c RFC-0048 = 0) — rfcs/0059-respond-aggregate-and-list-terms.md:6-9, rfcs/0059-respond-aggregate-and-list-terms.md:155-157
- [t6] RFC-0025 §5 (brief R7) — RFC-0052 §2's G12.2 lead "**§G12.2 (RFC-0048 §4의 최종 텍스트 위에).** 다섯 이름공간의 규칙은 이 개정이 손대지 않는다." exists only because of Draft RFC-0048; it is excluded from RFC-0075 §5 (the RFC-0070 text RFC-0075 copies starts RFC-0052's paragraph at "단일 행 바인딩의 **바인딩 값**"); RFC-0075 is a new carrier of t4's exclusion for RFC-0012 §G12.2 — rfcs/0052-lookup-key-clause.md:132-135
- [t6] RFC-0025 §5 (C27) — the G12.2 lead paragraph is replaced by RFC-0030 §2's lead (the latest after RFC-0027 §4), copied from RFC-0070 §G12.2; RFC-0075 is a new carrier of t4's C14 finding on the dropped "둘은 같은 바인딩 이름을 공유하지만 …" clause — rfcs/0025-row-sets-and-aggregation.md:213-218, rfcs/0030-create-result-binding-and-payload-seed.md:118-125
- [t6] RFC-0025 §5 (C27, C22) — the two stand-alone sentences RFC-0027 §4 silently dropped ("`Aggregate`의 `Reference`(§2)는 언제나 RowSet 바인딩을 본다." and "두 문법 위치가 겹치지 않으므로 … 넓힌 것이다.") stay as their own paragraph after the lead, as in RFC-0070 §G12.2 — rfcs/0025-row-sets-and-aggregation.md:218-221
- [t6] RFC-0025 §5 (C27) — the single-row bullet "**바인딩 값**은 저장소가 돌려준 행이다." is replaced by RFC-0052 §2's 바인딩 값 paragraph after the single-row list, and RFC-0052's "`update`/`delete`는 `by`가 있어도 바인딩하지 않는다." is the section's last sentence, as in RFC-0070 — rfcs/0025-row-sets-and-aggregation.md:228, rfcs/0052-lookup-key-clause.md:135-138
- [t6] RFC-0025 §5 (C27, C8) — the RowSet 읽기 전용 소비 bullet is replaced by RFC-0059 §4's bullet, which names RFC-0025 §5 directly — rfcs/0025-row-sets-and-aggregation.md:240-241, rfcs/0059-respond-aggregate-and-list-terms.md:159-161
- [t6] RFC-0025 §5 (C27) — RFC-0027 §4's 네트워크 결과 바인딩 list and RFC-0030 §2's 생성 결과 바인딩 list are added, and the target paragraph "`create`·`update`·`delete`는 어느 이름 공간에도 바인딩하지 않는다" is replaced by RFC-0030 §2's update/delete paragraph; none of RFC-0027, RFC-0030, RFC-0052 names RFC-0025 §5 in Updates outside a parenthesis (rule 5) — rfcs/0025-row-sets-and-aggregation.md:243-244, rfcs/0027-network-driver-and-result-binding.md:350-365, rfcs/0030-create-result-binding-and-payload-seed.md:127-146, rfcs/0030-create-result-binding-and-payload-seed.md:6-8
- [t6] RFC-0025 §5 — the kept target lead still says the text below is RFC-0012 §G12.2's final text and that RFC-0012's other sections are untouched; it now introduces text composed from RFC-0027 §4, RFC-0030 §2, RFC-0052 §2 and RFC-0059 §4; kept as target prose (C3) — rfcs/0025-row-sets-and-aggregation.md:207-209
- [t6] RFC-0025 §6.2 (C27) — the ⓒ row is replaced by RFC-0052 §2's row, which (after RFC-0030 §3) names `read`/`query` again; the kept target lead ("ⓒ만 바뀐다"), the kept Old line and the "`query`를 뺀 이유" paragraph now contradict the row; RFC-0075 is a new carrier of t4's G12.5 ⓒ finding — rfcs/0025-row-sets-and-aggregation.md:281-298, rfcs/0052-lookup-key-clause.md:145
- [t6] RFC-0025 §6.2 (C27) — RFC-0030 §3's paragraph and RFC-0052 §2's G12.5 paragraphs (멤버십, 조회 키 고유 규칙 table, 두 거부의 문구) are carried after the "`query`를 뺀 이유" paragraph, as in RFC-0070 §G12.5; neither RFC names RFC-0025 §6.2 (rule 5) — rfcs/0030-create-result-binding-and-payload-seed.md:160-163, rfcs/0052-lookup-key-clause.md:147-168
- [t6] RFC-0025 §6.1 — RFC-0075 §6.1 is a new carrier of t4's finding that the kept last paragraph ("§6.2(G12.5 ⓒ)가 `query`만 있고 `read`가 없는 엔티티로의 한정 참조 자체를 컴파일 거부로 막은 뒤로는") is false against the effective ⓒ — rfcs/0025-row-sets-and-aggregation.md:269-277
- [t6] RFC-0075, carried updater text — relative references that pointed into their source RFC now read as pointing into RFC-0075: RFC-0038 §1 "이 RFC §Motivation", RFC-0047 §1 "§5가" and "§Reference-level Specification/2의 표" (the table is RFC-0075 §3), RFC-0045 §2 "(§Guide-level Explanation, §Alternatives 2)", RFC-0030 §2 "§1로 확장", "§1 ⓑ", "(§3)", "(§4)", RFC-0052 §2 "§3이 파생한 키"; and RFC-0030 §2's "(RFC-0075 §5)" (re-pointed in RFC-0070) now cites its own section; kept as written (C26b) — rfcs/0038-list-where-predicate.md:118-119, rfcs/0047-aggregate-field-type-carriage.md:135, rfcs/0047-aggregate-field-type-carriage.md:141-142, rfcs/0045-rowset-aggregation-extension.md:153, rfcs/0030-create-result-binding-and-payload-seed.md:121-139, rfcs/0052-lookup-key-clause.md:136
- [t6] RFC-0025 §5, §7 (C15 drift) — RFC-0038 §4 extends the driver contract to `query(entity_id, predicate=None, order=None, limit=None)` and `list where` filters the RowSet, while its Updates name only RFC-0025 §1; RFC-0075 §5 ("`query(entity_id)`가 돌려준 행 리스트") and §7 keep RFC-0025's contract; nothing folded in (C15) — rfcs/0038-list-where-predicate.md:203-228, rfcs/0025-row-sets-and-aggregation.md:306-315
- [t6] RFC-0025 §4 (C15 drift) — RFC-0059 §2 extends `aggregation-orphaned-list` to `respond` aggregate terms without an Updates entry naming RFC-0025 §4; nothing folded in — rfcs/0059-respond-aggregate-and-list-terms.md:130-134
- [t6] RFC-0025 §2, §3 (C15 drift) — RFC-0053 §9 makes `sum`/`avg`/`min`/`max` skip `optional` fields with no Updates entry naming RFC-0025 or RFC-0045; nothing folded in — rfcs/0053-optional-field-modifier.md:303-313
- [t6] RFC-0025 §Guide-level Explanation, §Examples — Money aggregation is described as a compile rejection ("Money·Decimal은 정적 거부 — RFC-0015 §3과 같은 이유", the 정적 거부 — Money 필드 집계 example); stale since RFC-0045 §2 lets `sum`/`avg` take Money; kept, and both RFC-0015 citations stay as written (C25a) — rfcs/0025-row-sets-and-aggregation.md:90-92, rfcs/0025-row-sets-and-aggregation.md:528-542, rfcs/0045-rowset-aggregation-extension.md:153
- [t6] RFC-0025 §Open Questions — items 1 (필터·정렬·페이지네이션) and 3 (`min`/`max`/`avg`) were answered by RFC-0038 and RFC-0045; stale, kept — rfcs/0025-row-sets-and-aggregation.md:557-558, rfcs/0025-row-sets-and-aggregation.md:563-565
- [t6] RFC-0025 §Motivation — RFC-0075 is a new carrier of t5's finding on the quoted RFC-0015 sentence "(RFC-0012 §G12.2)"; kept as written (quoted text, C25) — rfcs/0025-row-sets-and-aggregation.md:36

**RFC-0076 (Supersedes RFC-0028) — 20건**

- [t5] RFC-0028 §2 — adds a compile rejection for a literal 0 divisor while saying it adds no row to RFC-0015 §3; RFC-0072 carries that paragraph in §4, so the rejection is absent from the §3 table — rfcs/0028-arithmetic-and-alternative-guards.md:215-222
- [t5] RFC-0028 (C15 drift) — its §6 adds multiplication, division and or-guard lowering that RFC-0015 §5 (addi/subi, cmpi, andi only) describes, and its §Alternatives reverses RFC-0015 §Alternatives "곱셈·나눗셈을 넣지 않는 이유", stating it does not name §5; nothing folded into RFC-0072 — rfcs/0028-arithmetic-and-alternative-guards.md:28-32,529, rfcs/0015-value-semantics.md:259-263,361
- [t4] RFC-0028 §4 — says §2.5 is "RFC-0014 원문 그대로", ignoring RFC-0022's Accepted update of §2.5 — rfcs/0028-arithmetic-and-alternative-guards.md:244-247, rfcs/0022-mode-b-observation-surface.md:6
- [t4] RFC-0060 §7 / RFC-0028 §4 — call evaluations an "RFC-0014 원문 불변 필드", but RFC-0014 §2.4's table has no evaluations row — rfcs/0060-assigned-field-guard-and-otherwise.md:360, rfcs/0014-guard-skip-observability.md:139-145
- [t7] RFC-0028 §1 — RFC-0050 names RFC-0028 §1 in its Updates line but replaces no unit RFC-0028 §1 carries (its final text covers RFC-0015 §1's `Condition`/`Presence` and the `and` paragraph); RFC-0076 §1 keeps RFC-0028's own text, whose lead "다른 생산 규칙(`Condition`/`Presence`/…)은 RFC-0015·RFC-0025 원문이 그대로 유효" is stale against RFC-0050 §1 — rfcs/0050-numeric-guard-predicate.md:6,107-114, rfcs/0028-arithmetic-and-alternative-guards.md:145-149
- [t7] RFC-0028 §6 — RFC-0051 §6 states a delta ("그 끝에 아래 문단 하나가 붙는다") instead of final text (rule 4); RFC-0076 §6 applies it in RFC-0051's own words after RFC-0050 §5's final text (C1) — rfcs/0051-money-arithmetic-in-set-and-guards.md:306-309
- [t7] RFC-0028 §4 (2.4) — RFC-0028 declares Updates RFC-0027 §6 and says its §4 replaces RFC-0014 §2 whole, yet its 2.4 final text (and RFC-0050 §4 and RFC-0060 §7 after it) drops RFC-0027 §6's statement that network result binding fields are not masked, without saying so; RFC-0076 keeps that stand-alone sentence as the last 2.4 paragraph (U2), the same unit RFC-0069/RFC-0071 2.4 carry (t4 a29) — rfcs/0028-arithmetic-and-alternative-guards.md:9,21-23,281-302, rfcs/0027-network-driver-and-result-binding.md:401-404
- [t7] RFC-0028 §4 — says it replaces RFC-0014 §2 whole, but its text drops RFC-0014's 2.4 steps-reason and status-vocabulary paragraphs and 2.6's restore paragraphs without saying so; RFC-0076 does not carry them: RFC-0014 is RFC-0028's own Updates target, RFC-0076 re-declares no Updates of RFC-0014 (only of RFC-0027 §6, analysis S2), and RFC-0071 §2 carries those paragraphs under C11 — rfcs/0028-arithmetic-and-alternative-guards.md:244-247, rfcs/0014-guard-skip-observability.md:147-154,174-185
- [t7] RFC-0028 §4 (2.4) — RFC-0060 §7's lead names the changed parts as "첫 문장과 mode·condition·steps·evaluations 행", but its final text also changes the rounds row ("`when`·`otherwise`면 없음"); RFC-0076 carries the final text as written — rfcs/0060-assigned-field-guard-and-otherwise.md:342-344,359, rfcs/0050-numeric-guard-predicate.md:213
- [t7] RFC-0028 §3, §4 — RFC-0060 names RFC-0028 only inside parentheses (Guard row, 2.1, 2.4) and RFC-0054 names only RFC-0001 for the Guard row, so RFC-0028 has no Updated-by line or pointer for either; its header updater list (RFC-0050, RFC-0051) misses the text RFC-0076 §3 and §4 take from them (C2, C13) — rfcs/0060-assigned-field-guard-and-otherwise.md:8,11-12, rfcs/0054-text-equality-guards.md:9, rfcs/0028-arithmetic-and-alternative-guards.md:10-11
- [t7] RFC-0028 §3 — the kept target lead "다른 20개 kind의 행과 표 서두의 산문(공통 필드 설명)은 RFC-0001 원문 그대로다" is stale: RFC-0056 added the `Rejection` kind and other rows changed (RFC-0015, RFC-0053, RFC-0056) — rfcs/0028-arithmetic-and-alternative-guards.md:226-228, rfcs/0056-fail-business-rejection.md:6
- [t7] RFC-0076 §1-§4 leads — the kept target relation prose names RFC-0015, RFC-0025, RFC-0001 and RFC-0014 원문 as the text of the rest of each section (e.g. "§2.2·§2.3·§2.5는 RFC-0014 원문 그대로"); all four are Superseded in this run (by RFC-0072, RFC-0075, RFC-0066, RFC-0071); kept as written (C3 target prose, C4, C25) — rfcs/0028-arithmetic-and-alternative-guards.md:145-149,199-201,226-228,244-247
- [t7] RFC-0076 carried bare self-references (C26b, not rewritten) — "§3(정적 거부, …)" now resolves to RFC-0076 §3 (the Guard row), "(§Differential Equivalence …)" and "§Reference-level Specification/7 D5" have no target, "(§5 4항)" resolves to RFC-0076 §5, and "§3의 평탄화된 값" (from RFC-0027 §6) resolves to RFC-0076 §3 — rfcs/0028-arithmetic-and-alternative-guards.md:135,215-216,347,382, rfcs/0060-assigned-field-guard-and-otherwise.md:205, rfcs/0027-network-driver-and-result-binding.md:402
- [t7] RFC-0028 Guide-level Explanation, §2 — "RFC-0015 원문 불변" for §3 (정적 거부) is kept as provenance but is stale: RFC-0051, RFC-0053, RFC-0054 and RFC-0060 updated RFC-0015 §3 (C25a) — rfcs/0028-arithmetic-and-alternative-guards.md:135,216, rfcs/0060-assigned-field-guard-and-otherwise.md:6
- [t7] RFC-0028 §6 — "RFC-0008 G8" names a label RFC-0008 does not have (G8 is a docs/ROADMAP.md work item); kept as written because "RFC-0069 G8" would be equally false (C25a) — rfcs/0028-arithmetic-and-alternative-guards.md:357,398, docs/ROADMAP.md:147
- [t7] RFC-0028 Motivation — "RFC-0015의 설계 규칙" ("표현식으로 안 되는 계산은 동사로 흡수한다") is kept as written: neither RFC-0015 nor RFC-0072 states that rule in those words, so re-pointing would claim something RFC-0072 does not say (C25) — rfcs/0028-arithmetic-and-alternative-guards.md:76-78
- [t7] RFC-0076 Status — nothing in RFC-0076 names which of its sections is the final text for RFC-0027 §6 (rule 4): RFC-0028 said so in its Status prose ("RFC-0027 §6이 §2.4의 마스킹 범위만 다시 갱신했다. 이 문서는 §2 전체(§2.1~§2.6)를 치환하므로"), which brief R3c drops; only the 통합 출처 row for the 2.4 masking paragraph hints at it, so a reader following RFC-0027's `> 갱신됨: RFC-0076` pointer must infer §4 2.4; not added because the brief fixes the Status layout — rfcs/0028-arithmetic-and-alternative-guards.md:21-23, rfcs/0027-network-driver-and-result-binding.md:384-386
- [t3] RFC-0028 §4 / RFC-0060 §7 — call `evaluations` an "RFC-0014 원문 불변 필드", but RFC-0014 §2.4's table never had an evaluations row; same defect as the [t4] finding for RFC-0069 — rfcs/0028-arithmetic-and-alternative-guards.md:295, rfcs/0060-assigned-field-guard-and-otherwise.md:360, rfcs/0014-guard-skip-observability.md:139-145@a310017
- [t3] RFC-0028 §4 2.4 — omits the target's `steps`-reason paragraph and shortens the status paragraph to "원문 불변" without declaring removal; both kept from RFC-0014 (U2) — rfcs/0028-arithmetic-and-alternative-guards.md:281-302, rfcs/0014-guard-skip-observability.md:147-154@a310017
- [t3] RFC-0028 §4 2.6 — drops the target's mode-B restore sentence, the until-unroll paragraph and the RFC-0008 §5 paragraph without declaring it (kept, U2), and cites "RFC-0014 원문의 드모르간 우려", which RFC-0014 does not contain (grep -c 드모르간 rfcs/0014-guard-skip-observability.md -> 0) — rfcs/0028-arithmetic-and-alternative-guards.md:306-316, rfcs/0014-guard-skip-observability.md:174-185@a310017

**RFC-0077 (Supersedes RFC-0038) — 6건**

- [t1] F14a RFC-0038 §Reference-level Specification — defines ListTail, OrderBy, Limit (list where/order by/limit surface syntax) without an Updates entry for RFC-0002 §Full grammar; not folded in (C15) — rfcs/0038-list-where-predicate.md:113-115
- [t6] RFC-0038 §3 — RFC-0077 §3 is a new carrier of t5's findings: the kept target lead ("아래는 그 끝에 새 절 하나를 더한 것이다") is stale above RFC-0054 §6's whole-section text; RFC-0051 §1 reworded 3.1's closing paragraphs (C14, not re-inserted); the kept RFC-0051 §1 거부 메시지 paragraph sits under 3.3 — rfcs/0038-list-where-predicate.md:170-174, rfcs/0038-list-where-predicate.md:190-201, rfcs/0051-money-arithmetic-in-set-and-guards.md:198-204
- [t6] RFC-0038 §1, §2 (C15 drift) — RFC-0050 §2 rejects `is-numeric` in a `list where` predicate without an Updates entry naming RFC-0038; RFC-0077 §1 still says `Condition` is reused with no redefinition; nothing folded in — rfcs/0050-numeric-guard-predicate.md:39-40, rfcs/0050-numeric-guard-predicate.md:160-162, rfcs/0038-list-where-predicate.md:118-119
- [t6] RFC-0038 §Motivation — "(RFC-0003 §Runtime)" names no RFC-0003 section (RFC-0003's title is Runtime); re-pointed to RFC-0068 like t5's P15, the section name is still absent — rfcs/0038-list-where-predicate.md:37
- [t6] RFC-0038 §Motivation — "RFC-0016의 차원 규칙이 등가 비교에는 지나치게 좁다" and "`_dimension_of`(RFC-0016 §3)는 Integer/DateTime이 아닌 선언 타입을 전부 거부한다" describe RFC-0016 §3 before RFC-0038, RFC-0051 and RFC-0054 changed it; kept as written (C25: re-pointing to RFC-0073 would be false) — rfcs/0038-list-where-predicate.md:53-55
- [t6] RFC-0038 §Open Questions 1 — "avg/min/max/group by … `sum`/`count`(RFC-0025) 이상으로 넓히는 것" is half answered by RFC-0045 (avg/min/max); stale, kept; its `group by` wording is RFC-0038's own text (Accepted 2026-08-27), not RFC-0048-derived, so brief R7 does not exclude it — rfcs/0038-list-where-predicate.md:365-367, rfcs/0048-collections-non-goal-and-rowset-group-by.md:5

**그 밖 — 37건**

- [t1] F11 RFC-0052 §1 — cites Reference as RFC-0012 §G12.1's CamelName-dot-CamelName form; the effective Reference is RFC-0015 §1's Namespace form — rfcs/0052-lookup-key-clause.md:112
- [t1] F14b RFC-0039 — defines a `note` StepLine form (StringLiteral, with Reference+) without an Updates entry for RFC-0002 §Full grammar; not folded in (C15) — rfcs/0039-note-verb-and-canonical-line.md:122
- [t1] F14c RFC-0040 — defines EventBody and ConsumeLine (subscribe/consume by under event) without an Updates entry for RFC-0002 §Full grammar; not folded in (C15) — rfcs/0040-event-consumption-contract.md:154-155
- [t1] F14d RFC-0044 — defines MoneyLiteral and CurrencyCode without an Updates entry for RFC-0002 §Full grammar; not folded in (C15) — rfcs/0044-money-arithmetic.md:169-170
- [t1] F18 RFC-0052 §1 / RFC-0062 §1 — RepoStepLine uses the nonterminal `Entity`, which no production of §Full grammar defines — rfcs/0062-cached-read-through-clause.md:96-98
- [t1] F20 carried updater prose — unqualified self-references ("이 RFC", bare §N, §Motivation, §Alternatives, Guide-level Explanation) now read as RFC-0067's own sections; kept verbatim (U1). — rfcs/0015-value-semantics.md:147,155
- [t1] F20 carried updater prose — unqualified self-references ("이 RFC", bare §N, §Motivation, §Alternatives, Guide-level Explanation) now read as RFC-0067's own sections; kept verbatim (U1). — rfcs/0025-row-sets-and-aggregation.md:145
- [t1] F20 carried updater prose — unqualified self-references ("이 RFC", bare §N, §Motivation, §Alternatives, Guide-level Explanation) now read as RFC-0067's own sections; kept verbatim (U1). — rfcs/0028-arithmetic-and-alternative-guards.md:169,184,185
- [t1] F20 carried updater prose — unqualified self-references ("이 RFC", bare §N, §Motivation, §Alternatives, Guide-level Explanation) now read as RFC-0067's own sections; kept verbatim (U1). — rfcs/0047-aggregate-field-type-carriage.md:135,137,141-142
- [t1] F20 carried updater prose — unqualified self-references ("이 RFC", bare §N, §Motivation, §Alternatives, Guide-level Explanation) now read as RFC-0067's own sections; kept verbatim (U1). — rfcs/0050-numeric-guard-predicate.md:133
- [t1] F20 carried updater prose — unqualified self-references ("이 RFC", bare §N, §Motivation, §Alternatives, Guide-level Explanation) now read as RFC-0067's own sections; kept verbatim (U1). — rfcs/0052-lookup-key-clause.md:128
- [t1] F20 carried updater prose — unqualified self-references ("이 RFC", bare §N, §Motivation, §Alternatives, Guide-level Explanation) now read as RFC-0067's own sections; kept verbatim (U1). — rfcs/0062-cached-read-through-clause.md:119
- [t1] F21 RFC-0052 §1 vs RFC-0062 §1 — RFC-0052's error text for read verbs (only `by <ref>` accepted) is not replaced by name while RFC-0062 gives a different text for read verbs; both kept (U2) — rfcs/0052-lookup-key-clause.md:117-122, rfcs/0062-cached-read-through-clause.md:107-112
- [t1] F23 RFC-0009 §Open Questions item 2 — still says Condition is `Presence | Comparison`, stale against RFC-0015 §1 and RFC-0050 §1 — rfcs/0009-guard-condition-open-question.md:73-74
- [t1] F31 RFC-0009 §Open Questions item 5 — still says the goal clause's lowering target is open, while the carried RFC-0002 §부록 A (A.5 and the 2026-07-31 구현 note) resolves it as BusinessRule — rfcs/0009-guard-condition-open-question.md:87-89, rfcs/0002-syntax.md:600-615
- [t1] none from RFC-0048 (brief R7) — RFC-0052 §1 has no RFC-0048-derived text — rfcs/0052-lookup-key-clause.md:99-131
- [t5] none from RFC-0048 (C8) — every carried source range has 0 RFC-0048 hits — grep -c 'RFC-0048' over the 17 carried source ranges of the t5 design recipe -> 0 each
- [t5] RFC-0044 (C15 drift) — calls itself the type-system revision RFC-0015 §Open Questions item 4 points to, without an Updates entry; item 4 still reads open in RFC-0072 — rfcs/0044-money-arithmetic.md:16-17, rfcs/0060-assigned-field-guard-and-otherwise.md:182-183
- [t5] RFC-0047 (C15 drift) — adds the optional `agg_field_type` key to the Assignment IR node RFC-0015 §2 describes ("`required`는 위 다섯이고") without naming RFC-0015 §2; RFC-0072 §2 keeps RFC-0015's text, and the key's text reaches RFC-0072 only inside §1 through the AggFunc chain — rfcs/0015-value-semantics.md:192, rfcs/0047-aggregate-field-type-carriage.md:122-144
- [t5] RFC-0055 (C15 drift) — answers RFC-0016 Open Question 6 (주입식 `now`의 승격) and says it is not an Updates; item 6 still reads open in RFC-0073 — rfcs/0055-injected-now-and-generated-id-field-markers.md:15-17, rfcs/0016-time-and-schedule-semantics.md:341
- [t5] RFC-0027 (stale citation, best-effort) — says `set`'s left side takes only Integer and DateTime fields "— RFC-0015 §3"; RFC-0051 later opened Money in `set`, and RFC-0072 §3 no longer states that rule — rfcs/0027-network-driver-and-result-binding.md:109-110
- [t5] RFC-0020 (stale citation, best-effort) — cites "RFC-0015 §G15.2" for the input namespace; RFC-0015 has no such section (the rule is RFC-0015 §3's `input.<field>` row and §Guide-level Explanation) — rfcs/0020-spec-given-input-namespace.md:9,36,68
- [t5] RFC-0062 (C15 drift) — keeps its mode-B rejection of cached reads in its own §6 and does not add a row to RFC-0016 §5's equivalence table, so RFC-0073 §5 does not list cached reads — rfcs/0062-cached-read-through-clause.md:25-28
- [t4] RFC-0022 — gives no section-shaped final text for RFC-0014 §2.5 (rule 4); only its paragraph 92-96 is appended to §2.5 (C10-rev) — rfcs/0022-mode-b-observation-surface.md:6-8, rfcs/0022-mode-b-observation-surface.md:92-96
- [t4] RFC-0060 §7 — says the condition string is "RFC-0008 §4 불변" while its or-joined form is a third shape that RFC-0008 §4 (two single-term shapes) does not list — rfcs/0060-assigned-field-guard-and-otherwise.md:357, rfcs/0008-guard-conditions.md:180-184
- [t8] after the rfc-conformance.md edit nothing checks Supersedes notation — rfc_lint does not, and the rfc-conformance AI gate is told it is out of its scope (recorded, not fixed)
- [t7] RFC-0053 (C15 drift, best-effort) — adds a mode-B build rejection for guards reading `optional` fields, inside the guard-lowering scope RFC-0028 §6 describes, without naming RFC-0028 §6; nothing folded into RFC-0076 — rfcs/0053-optional-field-modifier.md:314-320
- [t7] RFC-0054 (C15 drift, best-effort) — adds a mode-B build rejection for guards reading Text-class fields, inside the scope RFC-0028 §6 describes, without naming RFC-0028 §6; nothing folded into RFC-0076 — rfcs/0054-text-equality-guards.md:186-192
- [t7] RFC-0060 (C15 drift, best-effort) — adds two mode-B recorded-exception rejections (`otherwise`, guards reading assigned fields) in its own §8 without naming RFC-0028 §6; nothing folded into RFC-0076 — rfcs/0060-assigned-field-guard-and-otherwise.md:380-416
- [t7] none from RFC-0048 (C8) — every carried source range has 0 RFC-0048 hits (0060:197-205, 0054:153-156, 0060:308-367, 0027:401-404, 0050:230-307, 0051:311-329) and RFC-0048 names no RFC-0028 section
- [t3] RFC-0027 — names RFC-0003 §Execution Model (`NetworkCall` 행) but gives neither row text nor a delta sentence (rule 4); its §5 timeout paragraph is carried in RFC-0068 as its own paragraph after the Effect table (C12(1)) and kept against RFC-0056 §3, which restates the row without it (U2) — rfcs/0027-network-driver-and-result-binding.md:6-8, rfcs/0027-network-driver-and-result-binding.md:369-377, rfcs/0056-fail-business-rejection.md:163
- [t3] RFC-0027 §6 — the masking update is a prose delta (rule 4); RFC-0028 §4, RFC-0050 §4 and RFC-0060 §7 restate §2.4 without it and do not say they remove it; kept in RFC-0071 §2.4 (U2, C11); its "§3의 평탄화된 값" means RFC-0027 §3 and now reads as RFC-0071 §3 — rfcs/0027-network-driver-and-result-binding.md:401-404
- [t3] RFC-0022 — names RFC-0014 §2.5·§2.6 with no section-shaped final text (rule 4); only the grain/where paragraph is appended to RFC-0071 §2.5 (C10-rev); RFC-0028 §4 later declares §2.5 "RFC-0014 원문 그대로" without naming RFC-0022 (rule 5); same defect as the [t4] finding for RFC-0069 §2.5 — rfcs/0022-mode-b-observation-surface.md:6-8, rfcs/0022-mode-b-observation-surface.md:92-96, rfcs/0028-arithmetic-and-alternative-guards.md:244-247
- [t3] RFC-0032 §Examples/타임라인 C — the final-text block carries relation text ("(이전 서술과의 차이)", "타임라인 C의 이 부분은 바뀌지 않는다"; dropped, C3) and omits the target's ERROR and deadline bullets and closing paragraph without saying so; kept (U2) — rfcs/0032-transaction-boundary-and-rollback-enforcement.md:196, rfcs/0032-transaction-boundary-and-rollback-enforcement.md:203-207, rfcs/0003-runtime.md:384-393@a310017
- [t3] RFC-0062 §7 — the CacheAccess row is given as a blockquoted row whose cell ends in a period, unlike the other rows; carried as written with the container stripped — rfcs/0062-cached-read-through-clause.md:214
- [t3] RFC-0060 §7 — declares changes to the first sentence and the mode/condition/steps/evaluations rows, but the rounds row changes too (`when`·`otherwise`) — rfcs/0060-assigned-field-guard-and-otherwise.md:342-345, rfcs/0060-assigned-field-guard-and-otherwise.md:359
- [t9] RFC-0048 paragraph after the Updates block (규칙 5 연쇄 — "이미 갱신된 절은 대상 RFC와 직전 갱신 RFC를 모두 지목한다") now describes chain parentheses the re-targeted block no longer carries; left unchanged per plan D20, the dated 2026-10-28 note explains the drop — rfcs/0048-collections-non-goal-and-rowset-group-by.md:15-18

**판정:** 기록만 한다. 통합본은 사용자 결정 U1(효력 있는 계약을 그대로 옮기고 모순은 기록만 한다)에 따라 이 발견을 고치지 않았다. 예외는 항목 아래 들여쓴 줄에 적은 t9의 오타 수준 정정(RFC-0007 §2.1)뿐이다.

**영향도:** 낮음 — 효력 있는 계약은 바뀌지 않았다. 각 항목은 후속 Updates RFC나 이슈의 입력이다.

---

### 발견 F9: 여러 통합본에 실린 같은 단위 — Updates는 모든 사본을 지목해야 한다 (2026-10-29 기록)

**사실:** 통합은 대상마다 효력 있는 텍스트를 따로 실었다. 그래서 한 갱신 RFC가 여러 대상을 고친 단위는 이제 둘 이상의 통합본에 같은 사본으로 있다. 아래 표는 RFC-0066~0077을 줄 단위로 잰 결과다: 앞의 `> ` 인용 표시와 앞뒤 공백을 벗긴 줄 가운데 30자 이상이고 제목·표 구분선·코드 펜스 줄이 아니며 `## Status` 밖에 있는 줄이 두 RFC 이상에 똑같이 나오면 사본으로 셌다(t9 측정 스크립트 `.claude/tmp/t9/shared_lines.py`, 커밋하지 않음 — 2026-10-29 트리, 2차 통합 리뷰 뒤). "같은 줄 수"는 그 단위에서 둘 이상의 RFC에 나오는 서로 다른 줄의 수다. 이 측정은 줄바꿈 위치가 다른 사본과 30자 미만 줄을 놓친다. 그래서 목록은 최선 노력이고 완전하다고 주장하지 않는다.

| 단위 | 사본이 있는 통합본(절, 줄) | 같은 줄 수 |
|------|---------------------------|-----------|
| 문법 생산 규칙(EBNF 블록과 그 문단) | RFC-0067 §Full grammar, RFC-0069 §1, RFC-0070의 RFC-0002 §Full grammar / `Condition` 절, RFC-0072 §1, RFC-0073 §1, RFC-0075 §2, RFC-0076 §1 | 114 |
| RFC-0008 §1 꼬리(예약어 추가·Comparator 집합·기각된 형태 목록) | RFC-0067 §Full grammar(l.475-486), RFC-0069 §1(l.101-112). 그중 기각된 형태 `3단 이상의 경로` 항목(3줄)은 RFC-0070의 RFC-0008 §Reference-level Specification / 1. Full Grammar 절(l.102-104)에도 있고, RFC-0070 그 절의 머리 문장은 목록의 나머지(1~4토큰 자유 구, 논리 결합, 멤버십 연산)를 다른 문면으로 되풀이한다 | 8 |
| 실행 스코프 G12.1–G12.7 | RFC-0068 §Guard, RFC-0070의 RFC-0003 §Guard 절(둘 다 G12.1–G12.7). G12.2·G12.4·G12.5는 RFC-0075 §5·§6.1·§6.2에도 | 145 |
| 가드 런타임 §2(2.1–2.6) | RFC-0068 §Guard, RFC-0069 §2, RFC-0071 §2. 2.1·2.4·2.6의 일부는 RFC-0076 §4에도 | 79 |
| 피연산자의 차원 규칙(RFC-0016 §3, 3.1–3.3 — RFC-0054 §6 텍스트 포함) | RFC-0073 §3, RFC-0077 §3 | 74 |
| `list` 표면 문법(RFC-0038 §1이 쓴 `ListTail`·`OrderBy`·`Limit` 블록과 그 문단) | RFC-0075 §1(l.111-132), RFC-0077 §1(l.96-117, `> ` 인용) | 16 |
| 값 도메인과 실패(RFC-0015 §4 — RFC-0028 §2의 표) | RFC-0072 §4, RFC-0076 §2 | 14 |
| 노드 카탈로그 Guard 행 블록 | RFC-0066 §노드 카탈로그, RFC-0076 §3 | 16 |
| 노드 카탈로그의 그 밖 줄 | RFC-0066 §노드 카탈로그와 RFC-0072 §2(13줄), RFC-0073 §4(3줄) | 16 |

표에서 뺀 것 — 비규범 사본: Examples·Guide-level·골든 예제의 코드 줄(예: `set report.totalClicks to sum link.clicks`)과, RFC-0075 §Open Questions(l.670)의 한 줄을 RFC-0077 §Motivation(l.21)이 `> `로 인용한 것. 범위 밖 사본: 통합이 실어 온 갱신 RFC 원문 쪽 — 예컨대 RFC-0075 §3의 5줄은 Accepted 갱신 RFC-0045 §2(대상 RFC-0025는 Superseded)에도 있다. 이 표는 RFC-0066~0077만 쟀다. 측정이 찾은 같은 줄은 모두 491개이고, 표의 482개와 뺀 비규범 줄 9개가 그 전부다.

**규칙:** 이런 단위를 고치는 Updates RFC는 그 단위의 모든 사본을 지목해야 한다. 한 사본만 지목하면 그 RFC가 Accepted되는 순간 나머지 Accepted 사본과 모순되고(RFC-0007 §2.2 규칙 2), 규칙 7 검사(`rule7_check`)도 역링크 검사도 사본 사이의 차이를 보지 못한다. 첫 적용: Draft RFC-0048의 `Updates:`는 G12.2의 세 사본(RFC-0070 §G12.2, RFC-0068 §Guard/G12.2, RFC-0075 §Reference-level Specification/5)과 `list` 표면 문법의 두 사본(RFC-0075 §Reference-level Specification/1, RFC-0077 §Reference-level Specification/1)을 지목한다(2026-10-29). RFC-0048의 대상 절마다 위와 같은 줄 단위 측정을 RFC-0066~0077과 RFC-0045에 돌린 결과(`.claude/tmp/t9/copies_lines.py`): RFC-0066 §Open Questions/1과 RFC-0077 §2는 사본 0줄, RFC-0077 §Open Questions/1은 RFC-0045에 1줄(RFC-0045 §Open Questions/1은 이미 대상이다), RFC-0075 §3은 위 범위 밖 사본(RFC-0045 §2)만 있다. 이 결과도 측정의 사각지대(줄바꿈이 다른 사본, 30자 미만 줄)를 벗어나지 않는다.

**처리:** 위 단위를 고치는 후속 Updates(열린 이슈 #233·#240 등)의 작성자는 표의 모든 사본을 `Updates:`에 적고, 각 사본 대상 머리에 `Updated-by:`를 단다. 표가 완전하다고 기대지 말고, 고칠 줄을 rfcs/ 전체에서 다시 찾는다.

**영향도:** 중간 — 사본 하나만 고친 Updates가 Accepted되면 효력 있는 계약이 두 갈래가 된다. 이것을 잡는 기계 검사가 없어 리뷰가 막아야 한다.

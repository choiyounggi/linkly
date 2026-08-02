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

**N1 부재 대조.** 카탈로그 19종에 없는 가짜 kind `FileWrite`를 같은 명령에 넣으면 `0`이다
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
| 3 | Semantic Type | `0001:169-171` "**사용자 정의 타입은 refinement만 허용한다** … 새 원시 타입의 창설은 금지한다"; `0002:136-139` "`TypeName`은 … 18종 PascalCase 표기를 그대로 쓰는 **닫힌 열거**다. 임의 타입명은 문법 오류다" | 일치 (문법이 IR 카탈로그를 좁히기만 함) |
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
| `undefined kind injected: Foo` | 카탈로그 19종 밖 kind 주입 | `anyOf` 19분기 판별이 실효함 |
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
| RFC-0006 (Agent Protocol) | ① 역할표 권한 구멍 — Constraint를 제안할 수 있는 역할이 그것을 Service/Workflow의 `constraints`에 붙일 권한이 없다 ② 의도적·검토 가능한 노드 제거 표현(RefactoringAgent의 전제) | **대기 중.** 권한표와 제거 연산이라 한 절에 그치지 않으므로, `Updates`로 충분한지 전면 대체가 필요한지는 착수 시 판단한다 | 이슈 #2 |

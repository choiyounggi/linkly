# RFC-0005: Knowledge Base

## Status

- Status: Draft

## Motivation

Charter(`CHARTER.md` §Knowledge Base)는 Knowledge Base를 "가장 중요한 구성
요소이다. Language보다 중요하다"로 규정하고, "모든 AI Agent는 동일한 KB를
사용한다"를 요구한다. 용어 정의의 정본은 `docs/GLOSSARY.md`의 "Knowledge Base
(KB)" 항목이며 이 RFC는 그 정의를 참조만 하고 재정의하지 않는다.

같은 지식을 에이전트마다 다르게 기억하면 파이프라인(Planner → … → Release
Agent)의 산출물이 발산한다. 이를 막으려면 KB가 다음을 계약으로 고정해야 한다:

- **무엇이 문서인가** — 문서 스키마(frontmatter 필수 필드, 본문 규칙)
- **어떻게 분류되는가** — 카테고리 체계(Charter 12종 고정)
- **어떻게 찾아 읽는가** — 라우팅 구조와 로딩 규약(progressive disclosure)
- **어떻게 읽히는가(연산)** — 소비 인터페이스 3종의 논리 시그니처
- **어떻게 갱신되는가** — 문서 수명주기와 병합 규칙

이 RFC가 정의하는 것은 위 다섯 가지 전부이며, 정의하지 않는 것은 두 가지다:
소비 인터페이스의 **전송 표현**(JSON-RPC 메서드화 — RFC-0006 소유)과 **실제 KB
시드 문서의 집필**(ROADMAP Phase 3 소유).

## Guide-level Explanation

에이전트가 KB를 쓰는 경험은 세 걸음이다. 작업을 받으면 먼저 **라우팅
인덱스**(항상 로드 가능한 얇은 목차 계층)에서 자기 작업 서술과 맞는 트리거를
찾는다. 트리거가 맞은 문서만 **본문**을 로드해 지시를 적용한다. 본문이 "부속
체크리스트를 참조하라"처럼 명시적으로 지시할 때만 **부속 리소스**를 추가로
연다. 어떤 단계에서도 다음 단계의 내용을 미리 로드하지 않는다 — 필요가
확인되기 전의 로드는 없다.

이 3단 구조의 근거는 Anthropic Agent Skills의 progressive disclosure 패턴이다.
Agent Skills는 ① 스킬의 메타데이터(이름+설명)만 상시 로드하고 ② 매칭될 때
본문(SKILL.md)을 로드하며 ③ 부속 리소스는 본문이 지시할 때만 로드하는 3단
로딩으로 컨텍스트 토큰 소비를 필요 시점까지 미루는, 이미 검증된 구조다
(조사 기록: `docs/RESEARCH-NOTES.md` §5 —
<https://bdtechtalks.com/2025/10/20/anthropic-agent-skills/>,
<https://www.newsletter.swirlai.com/p/agent-skills-progressive-disclosure>).
KB의 라우팅 인덱스·문서 본문·부속 리소스는 이 3단과 각각 동형이다.

예를 들어 Coder 에이전트가 Login 워크플로의 `generate token` step을 구현할 때:
루트 인덱스에서 Security 카테고리로 라우팅하고, `security/index.md`의 트리거
"JWT 토큰을 발급·서명하는 코드를 생성할 때"에 매칭된 `security-jwt-issuance`
문서만 로드해 그 지시대로 토큰 발급 코드를 생성한다. 나머지 11개 카테고리와
Security의 다른 문서들은 로드되지 않는다. 전체 흐름은 `## Examples` 참조.

## Reference-level Specification

### Document Schema

KB 문서는 **Markdown + YAML frontmatter** 단일 파일이다.

frontmatter 필수 필드는 다음 6종이며, 하나라도 없으면 유효한 KB 문서가 아니다:

| Field | Type | 규칙 |
|-------|------|------|
| `id` | string | kebab-case, **카테고리 소문자 접두** 필수 (예: `security-jwt-issuance`). KB 전역 유일 |
| `category` | enum | 아래 `### Categories`의 12종 중 하나, Charter 표기 그대로 (예: `Security`) |
| `triggers` | list of string | 이 문서를 로드해야 하는 **상황 서술**의 목록, 최소 1개. 라우팅 인덱스에 그대로 노출된다 |
| `version` | string | semver `MAJOR.MINOR.PATCH` (예: `1.0.0`) |
| `status` | enum | `draft` \| `verified` \| `deprecated`. **KB 문서의 상태 축이며 RFC 수명주기(Draft/Review/Accepted/Superseded)와는 별개 축이다** |
| `sources` | list of string | 근거 링크 목록, 최소 1개. 근거 없는 지시는 KB에 들어올 수 없다 |

본문 규칙:

- 지시는 **긍정형**으로 쓴다 — "X 상황엔 Y를 한다". 금지형("~하지 마라")은
  실패 시 피해가 남는 **안전 임계**에만 허용한다.
- 본문은 **500줄 이하**로 유지한다. 초과하면 문서를 분할한다 — progressive
  disclosure의 로드 단위(한 번의 트리거 매칭 = 한 번의 본문 로드)를 지키기
  위함이며, 분할된 각 문서는 자체 frontmatter 6종을 온전히 갖는다.
- 대형 스키마·체크리스트·예제 파일은 본문에 인라인하지 않고 부속 리소스로
  분리한 뒤 본문에서 명시적으로 지시한다(`### Repository Layout & Routing` ③).

### Categories

카테고리는 Charter(`CHARTER.md` §Knowledge Base)의 12종으로 **고정**한다.
추가·누락·개명은 이 RFC의 개정 없이 불가하다(개정 절차는 `## Open Questions`
③). 각 카테고리의 정의와 대표 문서 예는 다음과 같다:

| Category | 정의 | 대표 문서 예 |
|----------|------|--------------|
| Architecture | 서비스·모듈 경계와 계층 구조 등 시스템 구조 결정 지침 | `architecture-service-boundaries` |
| Naming | Entity·필드·워크플로 등 식별자 명명 규약 | `naming-entity-field-conventions` |
| Performance | 응답 예산·캐싱·쿼리 비용 등 성능 목표 달성 지침 | `performance-response-budget-caching` |
| Security | 인증·인가·토큰·비밀값 취급 등 보안 결정 지침 | `security-jwt-issuance` |
| Testing | 테스트 수준·케이스 최소셋·검증 가능성 기준 | `testing-workflow-step-coverage` |
| Concurrency | 병렬 실행·fan-out/merge·경쟁 상태 회피 지침 | `concurrency-parallel-merge-fanout` |
| Database | 스키마·인덱스·트랜잭션 등 데이터 저장 결정 지침 | `database-postgres-index-selection` |
| Cloud | 클라우드 자원 프로비저닝·배포 대상 선택 지침 | `cloud-redis-cache-provisioning` |
| Patterns | 재사용 가능한 검증된 구현 패턴 카탈로그 | `patterns-repository-call` |
| AntiPatterns | 반복 실패로 확인된 회피 대상 패턴 카탈로그 | `antipatterns-unbounded-retry` |
| Style | 코드·선언 표기 스타일 규약 | `style-declaration-format` |
| Framework | 프레임워크·Capability 바인딩별 사용 지침 | `framework-capability-bindings` |

### Repository Layout & Routing

KB 저장소의 파일 레이아웃은 다음과 같이 고정한다. 카테고리 디렉토리명은 12종
카테고리명의 소문자다(`architecture`, `naming`, `performance`, `security`,
`testing`, `concurrency`, `database`, `cloud`, `patterns`, `antipatterns`,
`style`, `framework`):

```
kb/
├── INDEX.md                          # ① 루트 라우팅 인덱스
└── <category>/                       # 예: security/
    ├── index.md                      # ① 카테고리 라우팅 인덱스
    ├── <doc-id>.md                   # ② 문서 본문 (예: security-jwt-issuance.md)
    └── resources/                    # ③ 부속 리소스
        └── <파일명>
```

라우팅은 **3단 progressive disclosure**로 규정하며, 각 단의 로딩 규약은 다음과
같다:

**① 라우팅 인덱스 — 항상 로드 가능한 목차 계층.**
루트 `kb/INDEX.md`는 카테고리→"route here when" 1줄의 표이고, 각 카테고리
`index.md`는 문서 메타데이터(id + 1줄 트리거)만의 표다. 인덱스에는 문서 본문
내용이 들어가지 않는다 — 메타데이터만 노출해 어느 시점에 전부 로드해도 저비용을
유지한다. 루트 인덱스는 llms.txt 관례를 준용한 **평문 마크다운**으로 쓴다
(링크와 1줄 설명의 평면 목록 — 파싱 전용 포맷·HTML 금지).

**② 문서 본문 — 트리거 매칭 시에만 로드.**
에이전트는 인덱스의 트리거와 자기 작업 서술이 매칭될 때만 해당 문서의 본문을
로드한다. 본문은 500줄 이하이므로(`### Document Schema`) 한 번의 매칭이
로드하는 양은 유계다.

**③ 부속 리소스 — 본문이 명시적으로 지시할 때만 로드.**
스키마·체크리스트·예제 파일은 `resources/`에 두고, 본문이 "…는
`resources/<파일명>`을 참조하라"고 지시한 경우에만 로드한다. 인덱스에서
리소스로 직접 라우팅하지 않는다 — 리소스의 진입점은 언제나 본문이다.

### Consumption Interface

에이전트가 KB를 읽는 논리 연산은 다음 3종이다. 아래 시그니처는 **논리
계약**이며, 이 이름과 인자 그대로 상위 RFC들이 참조한다:

```
kb.route(task_description) -> [doc_id]
kb.load(doc_id) -> document
kb.verify(doc_id, version) -> bool
```

- **`kb.route(task_description) -> [doc_id]`** — 작업 서술(자연어)을 받아
  라우팅 인덱스(①)의 트리거와 매칭해 로드할 문서 id 목록을 반환한다. 매칭되는
  문서가 없으면 빈 목록을 반환한다(오류가 아니다). 매칭 알고리즘(키워드·시맨틱
  등)은 구현 정의이되, **① 라우팅 인덱스의 정보만으로 수행해야 한다** — 문서
  본문을 로드해 매칭하는 구현은 progressive disclosure 규약 위반이다.
- **`kb.load(doc_id) -> document`** — 문서 id로 해당 문서의 전문(파싱된
  frontmatter + 본문 Markdown)을 반환한다. 존재하지 않는 id는 오류다.
- **`kb.verify(doc_id, version) -> bool`** — **버전 핀 검증**: 에이전트가 이전에
  기록해 둔 `doc_id@version` 핀이 여전히 유효한지 확인한다. 문서가 존재하고
  현재 `version`이 인자 `version`과 정확히 일치하면 `true`, 그 외에는 `false`다.
  `false`는 핀 이후 문서가 개정(또는 삭제)되었음을 뜻하므로 에이전트는
  `kb.route`/`kb.load`부터 다시 수행한다.

이 3종의 **전송 표현**(JSON-RPC 메서드명·파라미터 스키마·오류 코드)은
**RFC-0006 Agent Protocol이 정의한다**. 이 RFC는 논리 시그니처와 의미론만
소유한다.

### Update Lifecycle

KB 문서의 갱신 수명주기는 frontmatter `status` 축 위에서 다음과 같이 규정한다:

1. **진입은 `draft`** — 신규 지식은 예외 없이 `draft`로 들어온다. 이 시점에도
   frontmatter 6종(특히 `sources` 최소 1개)은 갖춰야 한다.
2. **승격은 근거 검증 후 `verified`** — `sources`의 근거가 실제로 지시 내용을
   지지하는지 검증을 통과해야 `verified`로 승격한다. 에이전트가 지시의 근거로
   신뢰하는 대상은 `verified` 문서다.
3. **폐기는 `deprecated`** — 더 이상 유효하지 않은 문서는 삭제 대신
   `deprecated`로 전환해 버전 핀(`kb.verify`)의 판정 대상을 보존한다.
4. **충돌 시 병합 우선** — 신규 지식이 기존 문서와 주제·트리거가 겹치면 **기존
   문서에 병합**하는 것을 우선하고, 신규 문서 생성은 병합이 불가능할 때만
   한다(신규 문서 남발 금지 — 인덱스 비대화는 라우팅 품질을 깎는다).
5. **개정은 semver 증가** — 병합·개정 시 `version`을 semver 규칙으로 올린다.
   지시의 의미가 바뀌면 MAJOR, 지시 추가는 MINOR, 오탈자·링크 정비는 PATCH.

## Examples

골든 시나리오 "Login"을 사용한다(정본: `plans/rfc-suite/plan.md` §골든 시나리오
"Login" — RFC-0000 §5 규칙에 따라 참조만 하고 재정의하지 않는다).

**흐름 — Coder 에이전트가 `generate token` step을 구현한다.** Login 워크플로의
단계 중 `generate token`을 받은 Coder는 먼저 라우팅한다:

```
kb.route("Login 워크플로의 generate token step 구현 — jwt capability 사용")
  -> ["security-jwt-issuance"]
```

루트 인덱스 `kb/INDEX.md`에서 매칭된 행(발췌):

```markdown
| Category | Route here when |
|----------|-----------------|
| [Security](security/index.md) | 인증·인가·토큰 발급·비밀값 취급을 결정·구현할 때 |
```

카테고리 인덱스 `kb/security/index.md`에서 매칭된 행(발췌):

```markdown
| Doc | Trigger |
|-----|---------|
| [security-jwt-issuance](security-jwt-issuance.md) | JWT 토큰을 발급·서명하는 코드를 생성할 때 |
```

이어서 본문을 로드하고(`kb.load("security-jwt-issuance") -> document`), 문서
지시대로 토큰 발급 코드를 생성한 뒤, 사용한 문서의 버전을 핀으로 기록한다.
이후 Reviewer 에이전트는 같은 핀을 검증한다:

```
kb.verify("security-jwt-issuance", "1.0.0") -> true
```

`false`가 반환되면 문서가 개정된 것이므로 라우팅부터 다시 수행한다.

**예시 문서 전문 — `kb/security/security-jwt-issuance.md`:**

```markdown
---
id: security-jwt-issuance
category: Security
triggers:
  - JWT 토큰을 발급·서명하는 코드를 생성할 때
  - Workflow의 generate token 류 step을 구현할 때
  - 토큰 만료·클레임 구성을 결정할 때
version: 1.0.0
status: verified
sources:
  - https://datatracker.ietf.org/doc/html/rfc7519
  - https://datatracker.ietf.org/doc/html/rfc8725
---

# JWT 발급

## When this applies

JWT 기반 인증 토큰을 발급·서명하는 코드를 생성하거나 리뷰할 때.

## Do this

1. 서명 알고리즘은 배포 환경 설정에서 고정하고(예: RS256), 토큰 헤더의 `alg`를
   수신 측에서 재확인한다 — 검증 시 허용 알고리즘 목록을 명시한다 (RFC 8725 §3.1).
2. `exp`(만료)는 항상 설정한다. Login 시나리오의 Performance 제약(`cache 5m`)과
   별개로, 토큰 수명은 Security 정책으로 정한다.
3. 클레임은 최소로 구성한다 — `sub`, `iat`, `exp`에 서비스가 실제 소비하는
   클레임만 더한다 (RFC 7519 §4).
4. 서명 키는 Capability(`jwt`)가 주입하는 키 저장소에서 읽는다. 키 검증
   체크리스트는 `resources/jwt-key-checklist.md`를 참조하라.

## Safety line

- 서명 없는 토큰(`alg: none`)은 어떤 환경에서도 발급·수용하지 않는다 (RFC 8725 §2.1).
```

이 예시 문서는 frontmatter 필수 6종(`id`/`category`/`triggers`/`version`/
`status`/`sources`)을 모두 갖추고, 긍정형 지시(1~4)와 안전 임계에만 쓰인
금지형(Safety line), 부속 리소스 지시(4)까지 본 RFC의 스키마 규칙을 전부
시연한다.

## Alternatives

**① 단일 평면 문서(전체 상시 로드) — 기각.** 12개 가이드를 하나의 대형 문서로
합쳐 항상 로드하는 방식은 구현이 가장 단순하지만, 작업과 무관한 지식까지 매
호출의 컨텍스트에 실린다. progressive disclosure로 토큰 소비를 필요 시점까지
미루는 Agent Skills 패턴(`docs/RESEARCH-NOTES.md` §5)에 정면으로 역행해 기각.

**② 임베딩/벡터 검색 단독 라우팅 — 기각.** 인덱스 없이 임베딩 유사도만으로
문서를 찾는 방식은 라우팅 결과의 재현성·결정론이 부족하고(같은 질의가 모델·
인덱스 상태에 따라 다른 문서를 반환), `kb.route`가 요구하는 "① 라우팅 인덱스의
정보만으로 매칭" 규약과 양립하지 않는다. 인덱스 라우팅의 **보조 수단**으로
도입할 가능성만 `## Open Questions` ②로 남긴다.

**③ 2단 라우팅(D9 원안: 인덱스→본문) — 개정.** 부속 리소스 계층이 없으면 대형
스키마·체크리스트·예제가 본문에 인라인되어 500줄 예산을 압박하고, 로드 단위가
비대해진다. 본문이 명시적으로 지시할 때만 여는 세 번째 계층을 추가한 3단
구조로 개정했다(plan.md D9의 개정판 — Agent Skills의 3단 로딩과도 동형).

## Open Questions

1. **KB 저장소의 동기화·배포** — 여러 에이전트가 물리적으로 분산되어 있을 때
   동일한 KB 스냅샷을 보게 하는 방법(저장소 복제·버전 태깅·CDN 등). 소비
   연산의 전송은 RFC-0006이 정의하지만, 저장소 운영 방식은 ROADMAP에서 다룬다.
2. **임베딩 기반 보조 라우팅** — 트리거 매칭의 재현율을 올리기 위해 인덱스
   라우팅의 후순위 보조로 임베딩 검색을 둘 것인가. 결정론 요건과의 절충 필요.
3. **카테고리 개정 절차** — Charter 12종 고정을 전제로 하되, 실사용에서 새
   카테고리 수요가 확인될 때의 개정 경로(본 RFC의 Supersede 필요 여부 포함).

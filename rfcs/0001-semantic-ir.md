# RFC-0001: Semantic IR

## Status

- Status: Draft <!-- Draft | Review | Accepted | Superseded -->

## Motivation

LNPP는 AST를 버린다(CHARTER §Semantic IR). 기존 컴파일러의 AST 노드 —
Assignment, BinaryExpression, BlockStatement, IfStatement — 는 소스의 *구문*을
보존할 뿐, 개발자가 선언한 *의도*(무엇을 검증하고, 어떤 부수효과를 일으키며,
어떤 제약 아래 실행되는가)를 소실시킨다. Semantic IR은 구문 대신 의미를 1급
노드로 삼는 중간 표현이다: BusinessRule, Validation, NetworkCall,
RepositoryCall, CacheAccess, Transaction 같은 노드가 프로그램의 단위가 된다.
Semantic IR은 플랫폼의 설계 허브다(plan.md D1) — 표면 언어 LNPL(워킹네임,
RFC-0000 §4)은 Semantic IR로 lowering되는 표기일 뿐이고(RFC-0002), 런타임
(RFC-0003)·컴파일러(RFC-0004)·에이전트 프로토콜(RFC-0006)은 모두 이 IR의
소비자로 정의된다. 이 문서의 노드 카탈로그와 Semantic Type 표가 그 계약이다.

IR의 구조는 인라인 중첩 트리가 아니라 **평탄(flat) 노드 테이블 + id 참조**다
(plan.md D17). 근거는 세 가지다. 첫째, LLM 에이전트가 IR 조각을 constrained
decoding으로 직접 생성하려면 스키마가 중첩 ≤5레벨 등 구조적 제약 안에 있어야
하는데(OpenAI Structured Outputs 제약 — docs/RESEARCH-NOTES.md §2), 자식을 id
배열로만 참조하는 평탄 구조는 노드가 아무리 깊게 조합되어도 이 한계를 구조적으로
충족한다. 둘째, 노드가 문서 최상위의 독립 행이므로 노드 단위 diff와 fragment
교환(에이전트 간 부분 IR 전송)이 저비용이다. 셋째, 노드의 직렬화 순서가 안정되어
LLM 추론 시 KV-cache 프리픽스 재사용이 가능하다(MoonBit의 "중첩 축소" 원칙 —
docs/RESEARCH-NOTES.md §2).

## Guide-level Explanation

개발자는 코드를 쓰지 않고 의도를 선언한다(CHARTER §핵심 철학 2). 골든 시나리오
"Login"에서 개발자가 선언하는 것은 Entity `User`, Service `LoginService`,
6단계 Workflow `Login`, 그리고 Policy(`retry 3`, `rollback`, `timeout 3s`)·
Security(`jwt`)·Performance(`response < 50ms`, `cache 5m`) 제약이 전부다.
이 선언이 Semantic IR로 lowering되면, IR 문서에는 `if`나 대입문이 아니라
"입력을 검증한다(Validation)", "저장소에서 User를 읽는다(RepositoryCall)",
"사용자를 캐시에 쓴다(CacheAccess)" 같은 의미 노드가 남는다. 구현 방법 —
어떤 라이브러리로 JWT를 만들지, 어떤 드라이버로 postgres에 붙을지 — 는 IR에
없다. 그것은 선언된 Capability와 제약을 보고 컴파일러가 결정한다.

모든 노드는 네 대분류 중 하나에 속한다:

- **Declaration** — 무엇이 존재하는가: Entity, Service, Workflow, Event, Capability
- **Behavior** — 무엇을 하는가: BusinessRule, Validation, WorkflowStep, Pipeline, Concurrency
- **Effect** — 어떤 부수효과를 일으키는가: NetworkCall, RepositoryCall, CacheAccess, Transaction, Authorization, EventEmit
- **Constraint** — 어떤 제약 아래 실행되는가: Policy, Security, Performance

IR 문서는 이 노드들의 **평탄한 테이블**이다. 어떤 노드도 다른 노드를 인라인으로
품지 않는다. Workflow가 6개 단계를 가진다는 사실은 Workflow 노드의
`children: ["wf.login.step.1", …]` — 즉 id 배열 — 로만 표현되고, 각 단계는
테이블의 독립한 행이다. 타입 역시 String·Long 같은 원시 타입이 아니라 도메인
의미를 담은 Semantic Type(Email, Money, UUID …)을 쓰며, 각 타입은 validation
rule을 내장해 검증·OpenAPI·프런트엔드 검증 코드 자동 생성의 원천이 된다
(CHARTER §Semantic Type System). 용어의 정의 정본은 `docs/GLOSSARY.md`이며
이 문서는 재정의하지 않는다.

## Reference-level Specification

### 공통 필드

모든 노드는 아래 필드를 가진다. 이 4개 외의 공통 필드는 없다.

| 필드 | 필수 | 형식 | 의미 |
|------|------|------|------|
| `kind` | 필수 | 아래 카탈로그의 19개 PascalCase 식별자 중 하나 | 노드 종별의 유일 판별자. 대분류(Declaration/Behavior/Effect/Constraint)는 카탈로그 표의 분류 축일 뿐 노드 필드가 아니다 |
| `id` | 필수 | dot-path 문자열, 정규식 `^[a-z][a-z0-9]*(\.[a-z0-9]+)*$` | 노드 고유 식별자. 소문자·숫자 세그먼트를 `.`로 연결하고 첫 세그먼트는 문자로 시작. IR 문서 내에서 유일. 예: `svc.login`, `wf.login.step.3` |
| `meta` | 선택 | 객체 | 부가 정보. 정의된 키: `source`(원본 소스 위치 문자열), `origin`(`human` \| `agent:<이름>` — 생성 주체). 추가 키의 허용 여부와 형식은 직렬화 스키마(RFC-0001 부록 A, 후속 태스크)가 규정 |
| `children` | 선택 | id 배열 | 소유(containment) 참조. 아래 구조 규칙 참조 |

### 구조 규칙 (평탄 노드 테이블)

1. **평탄 테이블**: IR 문서는 노드의 평탄한 집합이다. 노드가 다른 노드를 인라인
   중첩 객체로 품는 것을 금지한다 — 자식은 오직 `children`의 id 배열로 참조한다.
2. **소유 유일**: 한 노드는 최대 1개 노드의 `children`에만 등장한다. 어느
   `children`에도 등장하지 않는 노드는 문서의 진입(top-level) 노드이며,
   Declaration 노드만 진입 노드가 될 수 있다.
3. **순서 유의미**: `children` 배열의 순서는 의미를 가진다 — Workflow의 단계
   순서는 실행 순서, Pipeline의 순서는 데이터 흐름 순서, Concurrency의 각
   child는 병렬 브랜치이고 배열의 끝이 병합 지점이다.
4. **순환 금지**: `children`이 이루는 소유 그래프는 비순환이어야 한다.
5. **참조 2계층**: ① `children` = 소유 참조. ② 명명 참조 필드(`requires`,
   `constraints`, `entity`, `event`, `target`, `source.ref`) = 비소유 참조.
   Constraint 노드는 children으로 소유되지 않고 `constraints` 필드로만 참조된다.
6. **dangling 금지**: 모든 참조(소유·비소유)는 같은 IR 문서 내의 `id`로
   해소되어야 한다. 기계 검증(스키마·스크립트)은 직렬화 태스크가 규정한다.

### 노드 카탈로그

19개 kind — 아래 4표가 전부이며 행의 추가·삭제는 이 RFC의 개정 사항이다.
공통 필드(kind/id/meta/children)는 각 행에서 생략한다. 필드 값의 문자 표기
(표현식 문법 등)는 RFC-0002가, 실행 의미(순서·실패·재시도의 동작)는 RFC-0003이
정의한다. D15의 "Workflow Step"은 kind 식별자로는 공백을 제거한 `WorkflowStep`
(PascalCase 단일 토큰)으로 표기한다 — 이 정규화가 하위 태스크의 정본이다.

**Declaration** — 무엇이 존재하는가. 진입 노드가 될 수 있는 유일한 대분류.

| kind | 필수 필드 | 선택 필드 | children 허용 |
|------|----------|----------|--------------|
| Entity | `name`, `fields`(배열: `{name, type(Semantic Type명 또는 refinement), required(기본 true)}`) | `constraints`(Constraint id[]) | Validation(엔티티 불변식) |
| Service | `name` | `requires`(Capability id[]), `constraints` | Workflow, Pipeline, BusinessRule |
| Workflow | `name` | `constraints` | WorkflowStep(순서=실행 순서) |
| Event | `name` | `payload`(Entity.fields와 동형 배열), `source`(`{ref: <노드 id>, on: create\|update\|delete}`) | (없음) |
| Capability | `name`(예: `postgres`) | `version`(요구 버전 표기) | (없음) |

**Behavior** — 무엇을 하는가.

| kind | 필수 필드 | 선택 필드 | children 허용 |
|------|----------|----------|--------------|
| BusinessRule | `name`, `statement`(규칙의 산문 서술) | `expression`(형식 표현 — 표기는 RFC-0002) | (없음) |
| Validation | `target`(노드 id 또는 `<entity id>.<field name>` 경로), `rule`(타입 내장 rule 참조 또는 refinement 제약) | `message`(실패 메시지) | (없음) |
| WorkflowStep | `name`(동사구 — 예: `validate input`) | `constraints` | Validation, BusinessRule, NetworkCall, RepositoryCall, CacheAccess, Transaction, Authorization, EventEmit, Concurrency, Pipeline |
| Pipeline | `name` | `constraints` | WorkflowStep(순서=데이터 흐름 순서) |
| Concurrency | `mode`(초기 허용값 `parallel` 하나 — CHARTER §Concurrency) | `merge`(병합 방식 서술 — 기본: 전 브랜치 완료 대기) | WorkflowStep(각 child = 병렬 브랜치, 배열 끝 = 병합 지점) |

**Effect** — 어떤 부수효과를 일으키는가. 부수효과의 1급 노드화가 이 IR의 핵심이다.

| kind | 필수 필드 | 선택 필드 | children 허용 |
|------|----------|----------|--------------|
| NetworkCall | `target`(호출 대상 서비스명/URL) | `protocol`(`http` \| `grpc` \| `graphql`), `operation` | (없음) |
| RepositoryCall | `entity`(Entity id 참조), `operation`(`create` \| `read` \| `update` \| `delete` \| `query`) | `query`(질의 조건 서술) | (없음) |
| CacheAccess | `key`(캐시 키 템플릿), `operation`(`get` \| `set` \| `invalidate`) | (없음 — TTL은 Performance 제약의 `cache` 예산이 소유한다. 중복 지정 금지) | (없음) |
| Transaction | (공통 필드 외 없음 — 스코프 노드) | `isolation`(격리 수준 서술) | RepositoryCall, NetworkCall, CacheAccess, EventEmit, BusinessRule, Validation |
| Authorization | `requirement`(요구 권한 서술 — 예: `role admin`) | `subject`(검사 대상) | (없음) |
| EventEmit | `event`(Event id 참조) | `payloadMap`(필드 매핑 서술) | (없음) |

Event와 EventEmit은 분리된다: 선언(Event, Declaration)은 이벤트의 존재와
페이로드를, 발행 행위(EventEmit, Effect)는 특정 지점에서 그 이벤트를 내보내는
부수효과를 나타낸다.

**Constraint** — 어떤 제약 아래 실행되는가. children으로 소유되지 않으며
Service·Workflow·WorkflowStep·Effect 노드의 `constraints` 필드로 참조된다.

| kind | 필수 필드 | 선택 필드 | children 허용 |
|------|----------|----------|--------------|
| Policy | `rules`(배열: `{name, value?}` — 초기 name 카탈로그: `retry`, `rollback`, `timeout`, `parallel`. 신규 name 추가는 이 RFC의 개정 사항) | (없음) | (없음) |
| Security | `mechanisms`(문자열 배열 — 초기 카탈로그: `jwt`, `role <r>`, `encrypt <field>`) | (없음) | (없음) |
| Performance | `budgets`(배열: `{metric, value}` — 초기 metric 카탈로그: `response`, `cache`, `parallel`, `prefetch`, `batch`) | (없음) | (없음) |

### Semantic Type 시스템

원시 타입을 최소화하고 도메인 의미를 타입에 직접 담는다(CHARTER §Semantic Type
System). 초기셋은 도메인 타입 13종 + 원시 보조 5종(표의 "보조" 표기)으로
고정한다(plan.md D16). 각 타입은 validation rule을 내장하며, 이 rule이 검증
코드·OpenAPI·프런트엔드 검증의 자동 생성 원천이다. 복합 타입의 내부 필드
타입은 이 표의 타입만 사용한다(자기완결). 표기 중 `!`는 필수 필드를 뜻한다.

| 타입 | 의미 | 내장 validation rule |
|------|------|---------------------|
| UUID | 전역 유일 식별자 | RFC 4122 canonical 형식(8-4-4-4-12 hex) |
| Money | 금액+통화 복합 | `{amount!: Decimal, currency!: Currency}` — 이진 부동소수점 표현 금지(합산 오차) |
| Email | 이메일 주소 | RFC 5322 addr-spec 형식 |
| Phone | 전화번호 | E.164 형식(`+`+국가코드 포함 최대 15자리). 텍스트로 취급하며 산술 금지(선행 0과 `+`가 데이터) |
| Password | 비밀 자격증명 | 로그·직렬화·에러 메시지 노출 금지(마스킹 의무 — 런타임 계약은 RFC-0003). 강도 정책은 Security/Policy 제약으로 위임 |
| Address | 우편 주소 복합 | `{line1!, line2, city!, region, postalCode, country!: ISO 3166-1 alpha-2}` |
| Image | 이미지 참조 | `{uri!, mediaType!: image/*}` — 바이너리 본문을 IR/저장 행에 내장하지 않고 객체 저장소 참조로 표현 |
| File | 파일 참조 | `{uri!, mediaType, sizeBytes}` — Image와 동일 원칙 |
| Currency | 통화 코드 | ISO 4217 alpha-3(정확히 3자) |
| GeoLocation | 지리 좌표 | `{lat!: Decimal ∈ [-90, 90], lng!: Decimal ∈ [-180, 180]}` |
| Json | 구조 미정 데이터 | RFC 8259 유효 JSON 문서 |
| Html | HTML 조각 | well-formed 마크업. 렌더 전 sanitize 의무는 Security 제약과 RFC-0003 계약이 규정 |
| Markdown | 마크다운 텍스트 | CommonMark 파싱 가능 |
| Text | 자유 텍스트(보조) | UTF-8 문자열. 길이·패턴 제약은 refinement로 부과 |
| Integer | 정수(보조) | 64-bit signed 범위 |
| Decimal | 십진수(보조) | 임의 정밀도 십진 — 이진 부동소수점 의미론 금지 |
| Boolean | 진리값(보조) | `true`/`false` 2값 |
| DateTime | 시각(보조) | RFC 3339(ISO 8601 프로파일), UTC 저장·오프셋 명시. 표시 시간대 변환은 표현 계층의 몫 |

**사용자 정의 타입은 refinement만 허용한다**: 위 18종 중 하나를 `base`로 지정하고
제약을 강화(범위·패턴·열거·길이 추가)하는 방식으로만 새 타입을 정의할 수 있다.
새 원시 타입의 창설은 금지한다 — 임의 원시 타입은 validation rule 자동 생성
체인을 깨뜨린다. refinement의 직렬화 표기는 부록 A(후속 태스크)가 규정한다.

### 경계

이 문서는 IR의 개념 모델·노드 카탈로그·타입 시스템만 규정한다. JSON 직렬화
문법과 JSON Schema, 검증 스크립트는 이 RFC의 **부록 A**로 후속 태스크(02)가
추가한다. `.lnpl` 문법 표기는 RFC-0002, 실행 의미는 RFC-0003의 소유다.

## Examples

골든 시나리오 "Login"을 사용한다(정본: `plans/rfc-suite/plan.md` §골든 시나리오
— RFC-0000 §5에 따라 참조만 하고 재정의하지 않는다). 아래는 시나리오 전체를
평탄 노드 테이블로 lowering한 결과다. 표의 각 행이 IR 문서의 노드 하나다.

| id | kind | 주요 필드 | children |
|----|------|----------|----------|
| svc.login | Service | name=LoginService, requires=[cap.postgres, cap.redis, cap.jwt], constraints=[policy.login, security.login, perf.login] | [wf.login] |
| entity.user | Entity | name=User, fields=[{id, UUID}, {email, Email}, {password, Password}, {createdAt, DateTime}] | [] |
| event.user.created | Event | name=UserCreated, source={ref: entity.user, on: create} | [] |
| wf.login | Workflow | name=Login | [wf.login.step.1, wf.login.step.2, wf.login.step.3, wf.login.step.4, wf.login.step.5, wf.login.step.6] |
| wf.login.step.1 | WorkflowStep | name="validate input" | [wf.login.step.1.check] |
| wf.login.step.1.check | Validation | target=entity.user.email, rule=Email(타입 내장) | [] |
| wf.login.step.2 | WorkflowStep | name="authenticate" | [wf.login.step.2.repo] |
| wf.login.step.2.repo | RepositoryCall | entity=entity.user, operation=read | [] |
| wf.login.step.3 | WorkflowStep | name="cache user" | [wf.login.step.3.cache] |
| wf.login.step.3.cache | CacheAccess | key="user:{id}", operation=set | [] |
| wf.login.step.4 | WorkflowStep | name="generate token" | [] |
| wf.login.step.5 | WorkflowStep | name="audit login" | [] |
| wf.login.step.6 | WorkflowStep | name="return token" | [] |
| policy.login | Policy | rules=[{retry, 3}, {rollback}, {timeout, 3s}] | [] |
| security.login | Security | mechanisms=[jwt] | [] |
| perf.login | Performance | budgets=[{response, <50ms}, {cache, 5m}] | [] |
| cap.postgres | Capability | name=postgres | [] |
| cap.redis | Capability | name=redis | [] |
| cap.jwt | Capability | name=jwt | [] |

참조 관계(화살표 목록):

- 소유(children): `svc.login → wf.login` / `wf.login → wf.login.step.1 ~ wf.login.step.6`(6단계, 순서 고정) / `wf.login.step.1 → wf.login.step.1.check` / `wf.login.step.2 → wf.login.step.2.repo` / `wf.login.step.3 → wf.login.step.3.cache`
- 비소유(명명 참조): `svc.login -requires→ cap.postgres, cap.redis, cap.jwt` / `svc.login -constraints→ policy.login, security.login, perf.login` / `wf.login.step.2.repo -entity→ entity.user` / `wf.login.step.1.check -target→ entity.user.email` / `event.user.created -source→ entity.user`

주: step 4~6(generate token / audit login / return token)은 children이 없는
순수 단계다 — 토큰 생성의 구현은 `cap.jwt`와 `security.login`(jwt) 제약을 보고
컴파일러가 결정하며(CHARTER §핵심 철학 2 "구현은 Compiler와 AI가 결정한다"),
IR은 의도만 보존한다. `event.user.created`는 User *생성* 시 발행되는 이벤트
선언이므로 Login workflow의 어느 단계도 이를 EventEmit하지 않는다.

## Alternatives

1. **구문 AST 유지** — 기각. Charter가 "AST를 버린다"를 명시한다. Assignment·
   IfStatement 같은 구문 노드는 언어 표면에 종속되고, 검증·부수효과·제약이라는
   의도를 제어 흐름 속에 흩어 놓아 컴파일러·에이전트가 의미를 재추론해야 한다.
2. **인라인 중첩 트리 IR** — 기각. 자식을 인라인 객체로 품는 트리는
   constrained decoding의 중첩 한계(≤5레벨)를 조합 깊이에 따라 초과하고, 노드
   단위 diff·fragment 교환이 고비용이며, 직렬화 순서가 불안정해 KV-cache
   프리픽스 재사용을 깨뜨린다(Motivation 둘째 문단, plan.md D17).
3. **사용자 정의 원시 타입의 자유 창설** — 기각. validation rule을 내장하지
   않는 임의 타입은 검증·OpenAPI·프런트엔드 검증 자동 생성 체인(D16의 목적)을
   깨뜨린다. 확장은 기존 타입 제약 강화(refinement)로만 허용한다.

## Open Questions

1. **제네릭/컬렉션 타입** — List·Map·Optional을 Semantic Type 시스템에 어떻게
   넣을 것인가(타입 파라미터 허용 범위, 중첩 컬렉션의 validation rule 합성).
2. **바이너리 직렬화 포맷** — D4가 미결로 남긴 항목. JSON 대비 어느 규모부터
   이득인지, canonical form(RFC 8785)과의 동등성 보장 방법 포함.
3. **IR 버전 마이그레이션** — 이 RFC가 Accepted된 뒤 노드 카탈로그·타입 표가
   개정될 때 기존 `.lir.json` 문서의 이행 절차(버전 필드, 자동 마이그레이션
   패스, Supersede 규칙과의 관계).
4. **노드 카탈로그 확장 절차** — 신규 kind 추가가 이 RFC의 개정인가 새 RFC로의
   Supersede인가, 그리고 실험적 kind의 네임스페이스 규칙.

# RFC-0002: Syntax

## Status

- Status: Draft <!-- Draft | Review | Accepted | Superseded -->

## Motivation

Semantic IR(RFC-0001)이 플랫폼의 설계 허브이지만(plan.md D1), 인간 개발자와 LLM
에이전트가 의도를 *작성*할 표면 표기가 필요하다. LNPL(워킹네임 — RFC-0000 §4,
소스 확장자 `.lnpl`)은 그 표면 언어다: 모든 문법 구성은 Semantic IR 노드로
lowering되는 표기일 뿐이며(lowering 매핑 표는 이 RFC의 후속 부록이 규정),
문법 자체는 어떤 실행 의미도 소유하지 않는다(실행 의미는 RFC-0003).

문법의 형태는 **라인 지향 + 키워드 구획**이다(plan.md D5). 이 선택은 두 기존
진영의 문제를 동시에 회피한다. 중괄호 언어(Java·Go류)는 포맷팅 토큰 —
공백·개행·중괄호 — 이 코드 토큰의 ~24.5%를 차지하는 비용을 치르고, 짝이 안
맞는 중괄호라는 문법 오류 부류를 만든다. 오프사이드 언어(Python류)는 들여쓰기가
문법이라 포맷팅을 제거할 수 없고(평균 6.51%만 절감), 스트리밍 생성 중 들여쓰기
한 칸의 오류가 파싱을 깨뜨린다(docs/RESEARCH-NOTES.md §1). LNPL은 블록 경계를
키워드가 정하고 들여쓰기를 비유의미로 두어, 포맷팅은 제거 가능하고 블록 짝
오류는 문법적으로 불가능하게 만든다.

## Guide-level Explanation

LNPL 프로그램은 선언의 나열이다. 골든 시나리오 "Login"에서 개발자가 쓰는 것은
`entity User`와 4개 필드, `service LoginService`와 그 제약(policy·security·
performance), 6단계 `workflow Login`, `event UserCreated`, 그리고 3개의
`capability` 선언 — 이것이 전부다. `if`도, 대입문도, 중괄호도 없다. 각 라인은
키워드로 시작하거나(선언·절·제어), 절/본문의 내용 라인이다. 파서는 라인 첫
토큰이 키워드인지만 보고 구조를 결정하므로, 사람도 LLM도 파일을 위에서 아래로
한 줄씩 읽으며 지금 어느 블록에 있는지 항상 안다.

블록은 여닫는 기호가 아니라 키워드로 구획된다. `entity User` 다음에 오는
`field` 절은 다음 절 키워드나 다음 최상위 선언 키워드가 나타나는 순간 닫힌다.
`service LoginService` 블록은 `workflow Login`이라는 최상위 키워드가 등장하는
순간 자동 종결된다. 명시적 종결 키워드를 가지는 블록은 단 하나 — `parallel`
블록만 `merge`로 닫힌다(CHARTER §Concurrency 예제 그대로). 들여쓰기는 읽기
편의를 위한 관례(4칸 권장)일 뿐 파서는 무시한다.

### LLM-친화 설계 4원칙

CHARTER §LLM Friendly Design의 4원칙 각각이 구체 문법 결정으로 실현된다:

- **Predictable** — 라인 지향(한 줄 한 선언·한 줄 한 step)과 고정 키워드
  카탈로그(최상위 5·절 10·제어 6) 덕분에, 스트리밍 생성 중 각 라인이 그
  자체로 유효성 판정 가능하고 다음 토큰의 후보 집합이 항상 작다. 생성이 어느
  라인에서 중단되어도 그 앞까지는 완결된 프로그램 접두사다.
- **Deterministic** — 블록 경계를 키워드가 정하므로 중괄호 짝 오류·들여쓰기
  오류라는 문법 오류 부류가 존재하지 않는다. 파싱은 포맷팅에 불변이다: 같은
  토큰열은 들여쓰기·공백과 무관하게 항상 같은 구조로 파싱된다.
- **Semantic** — 모든 최상위 키워드는 Semantic IR의 Declaration kind와 1:1이다
  (`entity`→Entity … `capability`→Capability). 제어 어휘도 구문(`if`/`for`)이
  아니라 의도(`when`/`repeat`/`parallel`/`until`/`pipeline`)를 말한다 —
  CHARTER §핵심 철학 3.
- **Low Ambiguity** — 키워드는 전부 소문자로 고정되고, `if`/`for`/`while`/
  `switch`는 예약되어 사용 금지이며, workflow step은 동사 선두·토큰 상한이
  있는 동사구로 제한되고, 문맥에 따라 재사용되는 키워드(`when`·`parallel`)는
  현재 블록 종류 하나로 판별된다(Reference-level의 문맥 한정 규칙). 하나의
  의도에 하나의 표기만 존재하도록 좁힌다.

### Prior Art

LNPL이 참조한 선행 3건과 각각에서 채택/기각한 것(원문 링크:
docs/RESEARCH-NOTES.md §1):

- **MoonBit** (AI-native 언어 — https://www.moonbitlang.com/blog/moonbit-ai ,
  ICSE LLM4Code 2024 https://dl.acm.org/doi/10.1145/3643795.3648376) — 채택:
  중첩 축소·최상위 명시 선언이 KV-cache 프리픽스 재사용에 유리하다는 원칙
  (중첩 ≤2·평탄한 선언 나열로 반영). 기각: 인간 지향 범용 표현식 문법(패턴
  매칭·함수형 축약) — 의도 선언 언어에는 불요.
- **"The Hidden Cost of Readability"** (arXiv:2508.13666 —
  https://arxiv.org/html/2508.13666) — 채택: 포맷팅 토큰이 코드 토큰의
  ~24.5%라는 실측 → 들여쓰기를 비유의미로 두어 포맷팅 전체를 제거 가능하게
  설계. 기각: 오프사이드 룰 — 포맷팅이 문법이 되면 제거 불가(평균 6.51%만
  절감)라는 것이 이 연구의 교훈.
- **Armin Ronacher, "A Language For Agents"** (2026-02 —
  https://lucumr.pocoo.org/2026/2/9/a-language-for-agents/) — 채택:
  significant whitespace는 LLM 작업에 불리하다는 진단 → 키워드 구획 채택.
  기각: 기존 범용 언어를 에이전트용으로 재사용하는 노선 — LNPP는 의도 선언
  전용의 신규 표면 언어를 만든다(CHARTER §Vision).

### 골든 시나리오에 없는 절의 소예제 (비규범)

`goal`·`database` 절(CHARTER §핵심 철학 2 예제)과 `spec` 절(CHARTER §Testing
예제)은 골든 시나리오에 포함되지 않으므로 Examples가 아닌 여기서만 형태를
보인다:

```
service UserService
    goal
        authenticate user
        cache profile
    database
        postgres
```

```
workflow Login
    validate input
    authenticate
    spec
        given
            valid account
        when
            login
        expect
            status 200
            token exists
```

제어 어휘의 형태(CHARTER §Concurrency 예제 + 가드 라인):

```
workflow LoadDashboard
    when profile missing
    parallel
        fetch user
        fetch permissions
        fetch settings
    merge
```

## Reference-level Specification

이 절만으로 파서를 구현할 수 있어야 한다. 문법은 논리 라인(logical line) 위에
정의된다: 소스는 UTF-8 텍스트이고, 각 라인은 행 종결(EOL)로 끝나며, 파서는
라인 선두의 공백을 완전히 무시한다.

### Lexical

- **식별자** — `PascalName`(대문자 시작: entity·service·workflow·event 이름과
  타입명), `CamelName`(소문자 시작: 필드명), `CapabilityName`(소문자·숫자만:
  `postgres`·`redis`·`jwt`), `Word`(소문자 시작 일반 단어: step·구 내용).
  키워드(아래 카탈로그 전체)와 예약어는 식별자·Word로 사용할 수 없다.
- **타입명** — `TypeName`은 RFC-0001 Semantic Type 표의 18종 PascalCase 표기를
  그대로 쓰는 닫힌 열거다: `UUID` `Money` `Email` `Phone` `Password` `Address`
  `Image` `File` `Currency` `GeoLocation` `Json` `Html` `Markdown` `Text`
  `Integer` `Decimal` `Boolean` `DateTime`. 임의 타입명은 문법 오류다
  (refinement 타입의 표면 표기는 Open Questions ③).
- **리터럴** — `Integer`(십진 정수: `3`, `200`), `Duration`(정수+단위:
  `3s`, `5m`, `50ms`). 단위 카탈로그는 골든 시나리오 실증 3종 `ms`/`s`/`m`만
  (확장은 Open Questions ④).
- **비교식** — `Comparison ::= CamelName Comparator (Duration | Integer)`,
  `Comparator`는 `<` `<=` `>` `>=` 4종. 예: `response < 50ms`.
- **주석** — `#`부터 행 끝까지. 파서는 주석과 빈 라인을 무시한다.

### Keywords

| 분류 | 키워드 | 개수 |
|------|--------|------|
| 최상위 선언 | `entity` `service` `workflow` `event` `capability` | 5 |
| 절 | `field` `goal` `policy` `security` `performance` `database` `spec` `given` `when` `expect` | 10 |
| 제어 | `when` `repeat` `parallel` `until` `pipeline` `merge` | 6 |
| 선언 수식 | `on` (+ enum `create` `update` `delete`) | 1(+3) |

최상위 선언 키워드 5종은 RFC-0001 Declaration kind 5종(Entity/Service/
Workflow/Event/Capability)과 1:1이다. 키워드는 전부 소문자다.

**문맥 한정 규칙** — 두 키워드는 블록 문맥으로 판별된다(파서 상태는 "현재
블록 종류" 하나로 충분하며 판별은 결정적이다):

- `when` — `spec` 절 내부에서는 `expect` 앞의 구획 키워드, workflow 본문에서는
  제어 가드. 두 문맥은 겹치지 않는다(spec 절은 workflow 본문의 마지막에만 온다
  — 아래 Clauses).
- `parallel` — `policy`/`performance` 절 내부에서는 내용 라인의 어휘(RFC-0001
  Policy rule name·Performance metric), workflow 본문에서는 제어 블록 개시.

**라인 분류 규칙** — 라인의 첫 토큰이 키워드면 그 키워드의 구조로, 아니면
현재 블록의 내용 라인(FieldLine·StepLine·PhraseLine 등)으로 해석한다. 이
규칙 하나가 전체 파싱을 결정적으로 만든다.

### 예약어 (Reserved Words)

`if` `for` `while` `switch` 4종은 **예약만 하고 사용을 금지한다**(CHARTER
§핵심 철학 3). 이들에 대한 생산규칙은 존재하지 않으며, 식별자·Word로도 쓸 수
없다. 제어 의도는 `when` `repeat` `parallel` `until` `pipeline`로만 표현한다.

### Block structure (D5 개정판)

1. **키워드 구획** — 블록 경계는 키워드가 정한다. 최상위 선언 키워드는 이전
   블록 전체를 자동 종결한다. 절 키워드는 소속 선언의 하위 구획을 열고, 다음
   절 키워드 또는 최상위 키워드에서 닫힌다. 명시적 종결 키워드를 가지는 블록은
   `parallel`(→ `merge`) 하나뿐이다.
2. **들여쓰기 비유의미** — 파서는 라인 선두 공백을 무시한다. 관례 4칸·탭
   금지는 style 권장일 뿐 문법이 아니다. 같은 토큰열은 포맷팅과 무관하게 항상
   같은 구조로 파싱된다.
3. **중첩 ≤2** — 선언 = 레벨 0, 절과 제어 블록 = 레벨 1, 그 내부 구획
   (`given`/`when`/`expect`, `parallel`의 브랜치 step) = 레벨 2. 그 이상의
   중첩은 문법적으로 불가능하다 — `ParallelBlock`과 `PipelineBlock`의 본문은
   `StepLine`만 허용하므로(아래 EBNF) parallel 안의 parallel, spec 안의 spec은
   생산규칙 차원에서 존재하지 않는다.
4. **한 줄 한 선언** — 모든 선언·절 개시·step·내용 항목은 정확히 한 라인이다.

### Declarations

| 형식 | lowering 대상(비규범 힌트) |
|------|---------------------------|
| `entity <PascalName>` + `field` 절 | Entity |
| `service <PascalName>` + 절들 | Service |
| `workflow <PascalName>` + step 본문 | Workflow |
| `event <PascalName> [on <PascalName> (create\|update\|delete)]` | Event(`on …` → `source={ref, on}`) |
| `capability <CapabilityName> [<Version>]` | Capability |

- `capability`는 한 줄이 한 선언이다(블록형 아님 — Alternatives ③). 골든
  시나리오의 3개 capability는 3개의 선언 라인이다.
- `event`의 `on` 수식은 RFC-0001 Event의 `source={ref, on: create|update|
  delete}` 필드의 표면 표기다. enum 3값은 IR 표기를 그대로 쓴다.
- **귀속(인접성) 규칙** — `workflow` 선언은 소스에서 가장 가까운 *선행*
  `service` 선언에 귀속된다(선언 순서 유의미). 선행 service가 없으면 독립
  진입 선언이다(RFC-0001 구조 규칙 2 — Declaration만 진입 노드). 이 귀속의
  정식 lowering 매핑은 후속 부록이 규정한다.

### Clauses

| 절 | 소속 | 내용 라인 |
|----|------|-----------|
| `field` | entity | `FieldLine ::= CamelName TypeName` — required 기본 true(optional 표기는 Open Questions ④) |
| `goal` | service | `GoalLine` = StepLine과 동형(동사구) |
| `policy` | service | `'retry' Integer \| 'rollback' \| 'timeout' Duration \| 'parallel'` — RFC-0001 Policy rule name 초기 카탈로그와 1:1 |
| `security` | service | `'jwt' \| 'role' Word \| 'encrypt' CamelName` — RFC-0001 Security mechanism 초기 카탈로그와 1:1 |
| `performance` | service | `'response' Comparator Duration \| 'cache' Duration \| 'parallel' \| 'prefetch' \| 'batch'` — RFC-0001 Performance metric 초기 카탈로그와 1:1 |
| `database` | service | `DatabaseLine ::= CapabilityName` |
| `spec` | workflow | 이름 인자 없음(소속 workflow가 대상). 내부에 `given`(선택)·`when`(필수)·`expect`(필수) 구획, 각 구획의 내용은 `PhraseLine`(1~4 토큰의 구 또는 비교식 — `valid account`, `login`, `status 200`, `token exists`). **spec 절은 workflow 본문의 마지막에만 온다**(step 라인과 PhraseLine의 중의성 차단) |

정책·보안·성능 어휘가 닫힌 열거인 것은 RFC-0001 Constraint 카탈로그(consume-
only)의 귀결이다 — 신규 어휘 추가는 RFC-0001의 개정 사항이지 이 문법의 확장이
아니다.

### Workflow body & control

workflow 본문의 각 라인은 step이거나 제어 구조다:

- **StepLine** — `Verb Word? Word? Word?`: 동사 선두 1~4토큰. 권장형은
  동사+목적어 2~4토큰(`validate input`, `generate token`)이고, 목적어가
  자명한 경우 단독 동사를 허용한다(골든 시나리오의 `authenticate`). 자유
  텍스트(5토큰 이상, 동사 비선두)는 금지다. 토큰 상한이 실측 없는 설계
  가설임은 Open Questions ①에 명시한다. step의 `name`은 RFC-0001
  WorkflowStep의 `name`(동사구) 계약과 정합한다.
- **가드 라인** — `when <Condition>`·`repeat <Integer>`·`until <Condition>`은
  **직후 1개의** step 또는 parallel/pipeline 블록에 적용되는 접두 가드다.
  별도 블록을 열지 않으므로 적용 범위가 항상 명확하다. `Condition`은 비교식
  또는 1~4토큰 구다. 가드의 실행 의미(조건 평가·반복 종료)는 RFC-0003 소유다.
- **`parallel` 블록** — `parallel` 라인으로 열고 `merge` 라인으로 닫는다
  (유일한 명시 종결 — CHARTER §Concurrency 예제 그대로). 본문의 각 StepLine이
  병렬 브랜치다.
- **`pipeline` 블록** — `pipeline` 라인으로 열고, 이후의 StepLine들이 데이터
  흐름 순서의 스테이지가 된다. 다음 키워드(제어·절·최상위)에서 닫힌다.

### Full grammar (W3C-style EBNF)

```
/* ---- 구조 ---- */
SourceFile        ::= (Declaration | Comment | BlankLine)*
Declaration       ::= EntityDecl | ServiceDecl | WorkflowDecl | EventDecl
                    | CapabilityDecl

EntityDecl        ::= 'entity' PascalName EOL FieldClause+
ServiceDecl       ::= 'service' PascalName EOL ServiceClause*
ServiceClause     ::= GoalClause | PolicyClause | SecurityClause
                    | PerformanceClause | DatabaseClause
WorkflowDecl      ::= 'workflow' PascalName EOL WorkflowItem* SpecClause?
EventDecl         ::= 'event' PascalName EventSource? EOL
EventSource       ::= 'on' PascalName ('create' | 'update' | 'delete')
CapabilityDecl    ::= 'capability' CapabilityName Version? EOL

/* ---- 절 ---- */
FieldClause       ::= 'field' EOL FieldLine+
FieldLine         ::= CamelName TypeName EOL
GoalClause        ::= 'goal' EOL GoalLine+
GoalLine          ::= StepLine
PolicyClause      ::= 'policy' EOL PolicyLine+
PolicyLine        ::= ('retry' Integer | 'rollback' | 'timeout' Duration
                    | 'parallel') EOL
SecurityClause    ::= 'security' EOL SecurityLine+
SecurityLine      ::= ('jwt' | 'role' Word | 'encrypt' CamelName) EOL
PerformanceClause ::= 'performance' EOL PerformanceLine+
PerformanceLine   ::= ('response' Comparator Duration | 'cache' Duration
                    | 'parallel' | 'prefetch' | 'batch') EOL
DatabaseClause    ::= 'database' EOL DatabaseLine+
DatabaseLine      ::= CapabilityName EOL
SpecClause        ::= 'spec' EOL GivenSection? WhenSection ExpectSection
GivenSection      ::= 'given' EOL PhraseLine+
WhenSection       ::= 'when' EOL PhraseLine+
ExpectSection     ::= 'expect' EOL PhraseLine+
PhraseLine        ::= (Comparison | Word PhraseToken? PhraseToken? PhraseToken?) EOL
PhraseToken       ::= Word | Integer | Duration

/* ---- workflow 본문·제어 ---- */
WorkflowItem      ::= StepLine | GuardedItem | ParallelBlock | PipelineBlock
GuardedItem       ::= (WhenGuard | RepeatGuard | UntilGuard)
                      (StepLine | ParallelBlock | PipelineBlock)
WhenGuard         ::= 'when' Condition EOL
RepeatGuard       ::= 'repeat' Integer EOL
UntilGuard        ::= 'until' Condition EOL
ParallelBlock     ::= 'parallel' EOL StepLine+ 'merge' EOL
PipelineBlock     ::= 'pipeline' EOL StepLine+
StepLine          ::= Verb Word? Word? Word? EOL
Verb              ::= Word
Condition         ::= Comparison | Word Word? Word? Word?

/* ---- 렉시컬 ---- */
Comment           ::= '#' [^#xA#xD]* EOL
BlankLine         ::= EOL
PascalName        ::= [A-Z] [A-Za-z0-9]*
CamelName         ::= [a-z] [a-zA-Z0-9]*
CapabilityName    ::= [a-z] [a-z0-9]*
Word              ::= [a-z] [a-zA-Z0-9]*
Version           ::= [0-9] [A-Za-z0-9.]*
TypeName          ::= 'UUID' | 'Money' | 'Email' | 'Phone' | 'Password'
                    | 'Address' | 'Image' | 'File' | 'Currency' | 'GeoLocation'
                    | 'Json' | 'Html' | 'Markdown' | 'Text' | 'Integer'
                    | 'Decimal' | 'Boolean' | 'DateTime'
Integer           ::= [0-9]+
Duration          ::= Integer DurationUnit
DurationUnit      ::= 'ms' | 's' | 'm'
Comparator        ::= '<' | '<=' | '>' | '>='
Comparison        ::= CamelName Comparator (Duration | Integer)
EOL               ::= #xA | #xD #xA
```

주: 생산규칙 이름들은 후속 lowering 매핑 표의 좌변이 되는 안정 계약이다 —
이름 변경은 이 RFC의 개정 사항이다. 키워드·예약어는 `PascalName`·`CamelName`·
`CapabilityName`·`Word`의 값에서 제외된다(렉시컬 우선순위: 키워드 > 식별자).

### 경계

이 문서는 표면 문법만 규정한다. 문법 구성 → IR 노드의 lowering 매핑 표와
`examples/login.lnpl` 파일 추출은 이 RFC의 후속 부록(태스크 04)이, 노드·타입
정의는 RFC-0001이, 실행 의미(가드 평가·병렬 병합·재시도)는 RFC-0003이,
IR 직렬화는 RFC-0001 부록 A가 소유한다.

## Examples

골든 시나리오 "Login"의 완전한 `.lnpl` 소스다(정본: `plans/rfc-suite/plan.md`
§골든 시나리오 — RFC-0000 §5에 따라 참조만 하고 재정의하지 않는다). 이 코드
블록은 후속 태스크가 `examples/login.lnpl`로 그대로 추출한다.

```
# login.lnpl — 골든 시나리오 "Login" (정본: plans/rfc-suite/plan.md)

capability postgres
capability redis
capability jwt

entity User
    field
        id UUID
        email Email
        password Password
        createdAt DateTime

event UserCreated on User create

service LoginService
    policy
        retry 3
        rollback
        timeout 3s
    security
        jwt
    performance
        response < 50ms
        cache 5m

workflow Login
    validate input
    authenticate
    cache user
    generate token
    audit login
    return token
```

골든 시나리오 요소 → 소스 대조:

| 골든 요소 | 소스 표현 |
|-----------|----------|
| Entity User 4필드 | `entity User` + `field` 절의 `id UUID`·`email Email`·`password Password`·`createdAt DateTime` |
| Service LoginService | `service LoginService` |
| Workflow Login 6단계(순서 고정) | `workflow Login` 본문의 6개 StepLine — service 직후이므로 귀속 규칙에 따라 LoginService 소유 |
| Policy 3종 | `policy` 절의 `retry 3`·`rollback`·`timeout 3s` |
| Security jwt | `security` 절의 `jwt` |
| Performance 2종 | `performance` 절의 `response < 50ms`·`cache 5m` |
| Event UserCreated(User 생성 시 발행) | `event UserCreated on User create` |
| Capability 3종 | `capability postgres`·`capability redis`·`capability jwt` |

최상위 선언 5종이 모두 등장한다: `capability`×3, `entity`×1, `event`×1,
`service`×1, `workflow`×1. step 6개 중 `authenticate`는 단독 동사 step의
실례다(Reference-level StepLine 규정).

## Alternatives

1. **오프사이드 룰(들여쓰기 유의미)** — 기각. 포맷팅이 문법이 되어 제거
   불가능하고(arXiv:2508.13666 — 평균 6.51%만 절감), 스트리밍 생성 중
   들여쓰기 오류가 파싱을 깨뜨린다(Ronacher). docs/RESEARCH-NOTES.md §1의
   3건이 초안의 오프사이드 룰을 기각한 근거다.
2. **중괄호 구획** — 기각. 포맷팅 토큰 비용(~24.5%의 주요 성분)을 치르고,
   짝이 안 맞는 중괄호라는 문법 오류 부류를 만든다 — Deterministic 원칙 위반.
3. **capability 블록형 표기**(CHARTER §Package Manager의 `capability` 아래
   이름 나열) — 기각. "한 줄 한 선언"(plan.md D5)과 IR의 Capability 노드
   1선언=1노드 대응을 위해 `capability postgres` 한 줄 형식으로 변경했다.
4. **최상위 `spec Login` 선언**(CHARTER §Testing 표기) — 기각. 최상위 선언
   키워드는 RFC-0001 Declaration kind 5종과 1:1이어야 하는데 spec은
   Declaration이 아니다. spec은 workflow의 절로 재배치했다(이름 인자도 소속
   workflow로 대체).
5. **자유 텍스트 step** — 기각. step을 임의 산문으로 허용하면 파싱 결정성과
   lowering 안정성(WorkflowStep `name` 계약)이 깨진다. 동사 선두 1~4토큰으로
   제한한다.

## Open Questions

1. **step 토큰 상한은 실측 없는 설계 가설이다** — "동사+목적어 2~4토큰 권장,
   단독 동사 허용, 상한 4토큰"은 LLM 생성 품질·표현력에 대한 실측 없이 정한
   값이다. 골든 시나리오의 `authenticate`(1토큰)와 계획 규정(2~4토큰)의
   충돌을 "동사 선두 1~4토큰 허용 + 2~4토큰 권장"으로 조정한 것도 같은 가설의
   일부다. 참조 인터프리터(plan.md D14·D20) 단계에서 실측 후 재검토한다.
2. **가드 조건식의 표현력** — `Condition`은 현재 비교식+1~4토큰 구가 전부다.
   부정·논리 결합(and/or)·멤버십 검사가 필요해지면 문법 확장이 필요하다.
3. **refinement 타입의 표면 표기** — RFC-0001은 사용자 정의 타입을 기존 18종
   base의 제약 강화(refinement)로만 허용하는데, 그 표면 문법(`field age
   Integer …범위…` 류)은 미정이다.
4. **Duration 단위 확장과 필드 optional 표기** — 단위는 실증 3종(`ms`/`s`/
   `m`)만 규정했다(`h`/`d` 등 확장 미정). `FieldLine`의 required 기본 true에
   대한 optional 표기도 미정이다.
5. **goal 절의 lowering 대상** — `goal` 절이 IR의 어느 노드(BusinessRule?
   Workflow 자동 합성?)로 lowering되는지는 후속 lowering 매핑 표(태스크 04)로
   넘긴다.

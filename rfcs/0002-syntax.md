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

### 부록 A: Lowering 매핑

문법 구성 → Semantic IR 노드의 매핑을 확정한다(본문 §경계가 이 부록에 위임한
항목). 본 부록은 위 본문(EBNF·키워드·블록 규칙)을 변경하지 않으며, IR 쪽
정의(RFC-0001 노드 카탈로그·`schemas/lir.schema.json`)도 변경하지 않는다 —
**충돌 시 IR이 정본**이다(plan.md D1).

**A.1 표기 규약.** A.2 표는 3열이다: `문법 생산규칙`(본문 §Full grammar의 이름
— 안정 계약) · `IR 노드 kind`(생성되는 노드 종별) · `매핑 규칙 비고`. 규칙 1회
매치당 노드 1개를 생성하는 것이 기본이다. kind 열이 `—`인 규칙은 노드를 만들지
않으며, 비고의 첫 토큰에 사유 태그를 붙인다:

- `[구문]` — 순수 구문 규칙(선택 분기·구획 키워드·종결자·렉시컬 성분). IR에
  흔적을 남기지 않거나 다른 값의 일부로만 남는다.
- `[필드흡수]` — 노드를 만들지 않고 부모 노드의 **필드 값 또는 참조**로 흡수된다.
- `[공백]` — IR v0.1에 대응 kind가 없다. A.4에 미해소 항목으로 등재한다.

소유·참조의 전역 규칙 4종(각 행이 이를 인용한다):

- **R1(문서)** — 소스 파일 1개 = IR 문서 1개(`{lir_version, module, nodes[]}`),
  `module` = 소스 파일명 stem(`login.lnpl` → `"login"`).
- **R2(workflow 귀속)** — `workflow` 선언은 소스에서 가장 가까운 선행 `service`
  선언의 `children`에 append된다(본문 §Declarations 귀속 규칙 + RFC-0001 구조
  규칙 2 소유 유일). 선행 service가 없으면 진입 노드다.
- **R3(capability 요구 — 잠정)** — 모듈 내 각 `capability` 선언은 Capability
  노드를 만들고, 그 id를 모듈 내 모든 Service의 `requires`에 **선언 순서대로**
  등재한다. 이 규칙은 Service가 1개인 골든 시나리오로만 실증되었다 — 다중
  Service 모듈의 귀속은 미해소이므로 **잠정 규칙**이다(A.4-⑧).
- **R4(제약 참조)** — Policy·Security·Performance 노드는 `children`으로 소유되지
  않고 소속 Service의 `constraints`로만 참조된다(RFC-0001 구조 규칙 5).

노드 `id`의 **도출 규칙은 이 부록이 규정하지 않는다** — RFC-0001은 id의 형식
(dot-path 정규식)만 규정하며, A.3의 id는 골든 예제의 실제 값을 대조 대상으로
인용한 것이다(A.4-⑦).

**A.2 생산규칙 → IR 노드 kind 매핑.** 본문 §Full grammar의 51개 생산규칙 전량이
행으로 존재한다(행 순서 = EBNF 등장 순서).

| 생산규칙 | IR 노드 kind | 매핑 규칙 비고 |
|----------|-------------|----------------|
| `SourceFile` | — | `[구문]` R1 — 파일 1개가 IR 문서 1개에 대응하며 그 자체로는 노드가 아니다 |
| `Declaration` | — | `[구문]` 5택 선택 규칙 — 노드는 각 하위 규칙이 만든다 |
| `EntityDecl` | Entity | 노드 1개. `name` = PascalName, `fields` = FieldClause의 내용 |
| `ServiceDecl` | Service | 노드 1개. `name` = PascalName. 절이 `constraints`(R4)를, 귀속 workflow가 `children`(R2)을, R3가 `requires`를 채운다 |
| `ServiceClause` | — | `[구문]` 5택 선택 규칙 |
| `WorkflowDecl` | Workflow | 노드 1개. `name` = PascalName, `children` = 본문 항목이 만든 노드의 소스 순서(RFC-0001 구조 규칙 3). 소유자는 R2 |
| `EventDecl` | Event | 노드 1개. `name` = PascalName. children 없음 |
| `EventSource` | — | `[필드흡수]` 부모 Event의 `source = {ref: 대상 Entity 노드 id, on: create\|update\|delete}`. enum 3값은 IR 표기 그대로 |
| `CapabilityDecl` | Capability | 노드 1개. `name` = CapabilityName, `Version`이 있으면 `version`(문자열). 추가로 R3(**잠정** — A.4-⑧)에 따라 각 Service의 `requires`에 등재 |
| `FieldClause` | — | `[구문]` 구획 키워드 — 내용은 부모 Entity의 `fields`로 간다 |
| `FieldLine` | — | `[필드흡수]` `fields[]` 항목 `{name: CamelName, type: TypeName}`. `required` 키를 생략하면 필수(true)로 해석된다(RFC-0001 부록 A.4) |
| `GoalClause` | — | `[구문]` 구획 키워드 — 생성 노드의 소유자는 소속 Service |
| `GoalLine` | BusinessRule | 라인 1개 = 노드 1개. `name` = `statement` = 동사구 원문, `expression`은 v0.1에서 미기입(표현식 표기가 Open Questions ②③로 미정). 소속 Service의 `children`에 소스 순서로 append. → 본문 Open Questions ⑤의 해소(A.5) |
| `PolicyClause` | Policy | 절 1개 = 노드 1개. `rules[]`는 PolicyLine들이 채우고, 소속 Service는 R4로 참조한다 |
| `PolicyLine` | — | `[필드흡수]` `rules[]` 항목: `retry N` → `{name:"retry", value:N}`(수치), `rollback` → `{name:"rollback"}`(value 없음), `timeout D` → `{name:"timeout", value:"3s"}`(문자열), `parallel` → `{name:"parallel"}` |
| `SecurityClause` | Security | 절 1개 = 노드 1개. `mechanisms[]`를 SecurityLine이 채우고 R4로 참조된다 |
| `SecurityLine` | — | `[필드흡수]` `mechanisms[]`의 문자열 항목 — `jwt` → `"jwt"`, `role admin` → `"role admin"`, `encrypt password` → `"encrypt password"`(RFC-0001 초기 카탈로그 표기 그대로) |
| `PerformanceClause` | Performance | 절 1개 = 노드 1개. `budgets[]`를 PerformanceLine이 채우고 R4로 참조된다 |
| `PerformanceLine` | — | `[필드흡수]` `budgets[]` 항목: `response < 50ms` → `{metric:"response", value:"<50ms"}`(Comparator와 Duration을 공백 없이 연결), `cache 5m` → `{metric:"cache", value:"5m"}`. 값 없는 `parallel`·`prefetch`·`batch`는 스키마가 `value`를 필수로 요구하므로 v0.1 미해소(A.4-⑤) |
| `DatabaseClause` | — | `[구문]` 구획 키워드 — 노드를 만들지 않는다 |
| `DatabaseLine` | — | `[필드흡수]` 소속 Service의 `requires`에 해당 Capability id를 멱등 등재(R3로 이미 있으면 추가하지 않는다). 노드 생성은 `CapabilityDecl`이 소유하며, 선언되지 않은 이름은 dangling 참조 금지(RFC-0001 구조 규칙 6) 위반이다 |
| `SpecClause` | — | `[공백]` IR 카탈로그 19종에 테스트 명세 노드가 없다. spec은 IR 노드가 아니라 채택 요건 ④ 테스트 스위트 아티팩트(plan.md D20)로 산출된다(A.4-②) |
| `GivenSection` | — | `[공백]` 사전 조건 — SpecClause와 동일(A.4-②) |
| `WhenSection` | — | `[공백]` 실행 트리거 — SpecClause와 동일(A.4-②) |
| `ExpectSection` | — | `[공백]` 기대 결과 — SpecClause와 동일(A.4-②) |
| `PhraseLine` | — | `[공백]` spec 절 내부 전용 내용 라인(A.4-②) |
| `PhraseToken` | — | `[구문]` PhraseLine의 토큰 성분 |
| `WorkflowItem` | — | `[구문]` 4택 선택 규칙 |
| `GuardedItem` | — | `[구문]` 피가드 항목(StepLine·ParallelBlock·PipelineBlock)만 노드가 되고 가드 자체는 lowering에서 소실된다(A.4-①) |
| `WhenGuard` | — | `[공백]` 조건을 담을 노드 kind가 없다. Policy 등 다른 kind로의 대체 매핑을 금지한다 — 의미가 달라진다(A.4-①) |
| `RepeatGuard` | — | `[공백]` `repeat N`(N회 반복)은 Policy `retry N`(실패 시 재시도)과 의미가 다르므로 접지 않는다(A.4-①) |
| `UntilGuard` | — | `[공백]` 종료 조건 — WhenGuard와 동일(A.4-①) |
| `ParallelBlock` | Concurrency | 노드 1개, `mode: "parallel"`. 본문의 각 StepLine이 `children`(각 child = 병렬 브랜치, 배열의 끝 = 병합 지점)이며 `merge` 필드는 기본(전 브랜치 완료 대기)을 쓰므로 미기입한다. `merge` 키워드는 종결자로 노드를 만들지 않는다. workflow 본문 직속일 때의 소유 경로는 A.4-⑥ |
| `PipelineBlock` | Pipeline | 노드 1개. 본문의 StepLine들이 `children`(순서 = 데이터 흐름). 스키마가 `name`을 필수로 요구하는데 문법이 이름 토큰을 제공하지 않는다(A.4-④). 소유 경로는 A.4-⑥ |
| `StepLine` | WorkflowStep | 라인 1개 = 노드 1개. `name` = 라인 원문(토큰 사이 단일 공백으로 정규화). 소유자는 문맥이 정한다 — workflow 본문 직속이면 Workflow, `parallel` 내부면 Concurrency, `pipeline` 내부면 Pipeline의 `children`에 소스 순서로. step 하위의 Effect·Validation 노드는 문법이 표현하지 않는다(A.4-③) |
| `Verb` | — | `[구문]` StepLine의 첫 토큰 — `name` 문자열의 일부로만 남는다 |
| `Condition` | — | `[공백]` 가드 전용 — 대응 kind가 없다(A.4-①) |
| `Comment` | — | `[구문]` 파서가 무시한다. `meta.source`(선택 필드)는 v0.1에서 미기입 |
| `BlankLine` | — | `[구문]` 파서가 무시한다 |
| `PascalName` | — | `[필드흡수]` 선언 노드의 `name` 값, `EventSource`에서는 참조 대상(`source.ref`)의 지시자 |
| `CamelName` | — | `[필드흡수]` FieldLine의 `name`, Comparison의 좌변, `encrypt <field>`의 필드명 |
| `CapabilityName` | — | `[필드흡수]` Capability의 `name`, DatabaseLine의 참조 대상 |
| `Word` | — | `[필드흡수]` step·구·`role <r>`의 토큰 — 문자열 값의 성분 |
| `Version` | — | `[필드흡수]` Capability의 `version`(문자열) |
| `TypeName` | — | `[필드흡수]` `fields[].type` 문자열 — v0.1은 Semantic Type명을 문자열로 담는다(RFC-0001 부록 A.6) |
| `Integer` | — | `[필드흡수]` Policy `retry`의 value(수치), PhraseToken의 성분. RepeatGuard 문맥은 A.4-① |
| `Duration` | — | `[필드흡수]` Policy `timeout`의 value 문자열(`"3s"`), Performance value의 성분 |
| `DurationUnit` | — | `[구문]` Duration 리터럴의 단위 성분(`ms`·`s`·`m`) |
| `Comparator` | — | `[필드흡수]` Performance value 문자열의 접두(`"<50ms"`), Comparison의 성분 |
| `Comparison` | — | `[필드흡수]` PerformanceLine `response` 예산의 값 문자열. Condition 문맥은 A.4-① |
| `EOL` | — | `[구문]` 논리 라인의 종결자 |

집계: 노드를 만드는 규칙 12개(EntityDecl · ServiceDecl · WorkflowDecl ·
EventDecl · CapabilityDecl · GoalLine · PolicyClause · SecurityClause ·
PerformanceClause · ParallelBlock · PipelineBlock · StepLine) + `—` 39개 = 51.

**A.3 골든 예제 대응표.** `examples/login.lnpl`(위 §Examples 코드 블록을 그대로
추출한 33줄)의 각 줄과 `examples/login.lir.json`의 노드를 짝지운다. `줄`은
`.lnpl` 파일의 1-기반 줄 번호다.

| 줄 | 소스 라인 | 생산규칙 | IR 노드 id(kind) 또는 흡수 위치 |
|----|-----------|----------|--------------------------------|
| 1 | `# login.lnpl — …` | `Comment` | — |
| 2 | (공란) | `BlankLine` | — |
| 3 | `capability postgres` | `CapabilityDecl` | `cap.postgres`(Capability) + `svc.login.requires[0]`(R3) |
| 4 | `capability redis` | `CapabilityDecl` | `cap.redis`(Capability) + `svc.login.requires[1]`(R3) |
| 5 | `capability jwt` | `CapabilityDecl` | `cap.jwt`(Capability) + `svc.login.requires[2]`(R3) |
| 6 | (공란) | `BlankLine` | — |
| 7 | `entity User` | `EntityDecl` | `entity.user`(Entity) |
| 8 | `field` | `FieldClause` | — `[구문]` |
| 9 | `id UUID` | `FieldLine` | `entity.user`.`fields[0]` |
| 10 | `email Email` | `FieldLine` | `entity.user`.`fields[1]` |
| 11 | `password Password` | `FieldLine` | `entity.user`.`fields[2]` |
| 12 | `createdAt DateTime` | `FieldLine` | `entity.user`.`fields[3]` |
| 13 | (공란) | `BlankLine` | — |
| 14 | `event UserCreated on User create` | `EventDecl` + `EventSource` | `event.user.created`(Event), `source = {ref: "entity.user", on: "create"}` |
| 15 | (공란) | `BlankLine` | — |
| 16 | `service LoginService` | `ServiceDecl` | `svc.login`(Service) |
| 17 | `policy` | `PolicyClause` | `policy.login`(Policy) = `svc.login.constraints[0]`(R4) |
| 18 | `retry 3` | `PolicyLine` | `policy.login`.`rules[0]` = `{retry, 3}` |
| 19 | `rollback` | `PolicyLine` | `policy.login`.`rules[1]` = `{rollback}` |
| 20 | `timeout 3s` | `PolicyLine` | `policy.login`.`rules[2]` = `{timeout, "3s"}` |
| 21 | `security` | `SecurityClause` | `security.login`(Security) = `svc.login.constraints[1]`(R4) |
| 22 | `jwt` | `SecurityLine` | `security.login`.`mechanisms[0]` = `"jwt"` |
| 23 | `performance` | `PerformanceClause` | `perf.login`(Performance) = `svc.login.constraints[2]`(R4) |
| 24 | `response < 50ms` | `PerformanceLine` | `perf.login`.`budgets[0]` = `{response, "<50ms"}` |
| 25 | `cache 5m` | `PerformanceLine` | `perf.login`.`budgets[1]` = `{cache, "5m"}` |
| 26 | (공란) | `BlankLine` | — |
| 27 | `workflow Login` | `WorkflowDecl` | `wf.login`(Workflow) = `svc.login.children[0]`(R2 — 16행 service에 귀속) |
| 28 | `validate input` | `StepLine` | `wf.login.step.1`(WorkflowStep) |
| 29 | `authenticate` | `StepLine` | `wf.login.step.2` |
| 30 | `cache user` | `StepLine` | `wf.login.step.3` |
| 31 | `generate token` | `StepLine` | `wf.login.step.4` |
| 32 | `audit login` | `StepLine` | `wf.login.step.5` |
| 33 | `return token` | `StepLine` | `wf.login.step.6` |

workflow 6단계는 소스 28~33행과 `wf.login.children`의 `wf.login.step.1` ~
`wf.login.step.6`이 **순서까지 1:1**로 대응한다(RFC-0001 구조 규칙 3 — children
순서 = 실행 순서).

역방향(소스에 대응 줄이 없는 IR 노드) 3개 — 문법 → IR이 **부분사상**임을 보이는
지점이다:

- `wf.login.step.1.check`(Validation, `target=entity.user.email`, `rule=Email`)
- `wf.login.step.2.repo`(RepositoryCall, `entity=entity.user`, `operation=read`)
- `wf.login.step.3.cache`(CacheAccess, `key="user:{id}"`, `operation=set`)

이 3종은 v0.1 문법에 표면 표기가 없어 소스에서 도출되지 않는다(A.4-③).
집계: 골든 IR 19노드 = 소스 라인 대응 16 + 소스 무대응 파생 3.

**A.4 미해소 lowering 공백.** 아래 8항은 이 부록이 해소하지 못한 항목이며 각각
해소 소유자를 명시한다. 공백을 감추지 않는 것이 이 표의 검증 가치다(plan.md D6).

| # | 공백 | 해소 소유자 |
|---|------|-------------|
| ① | `when`·`repeat`·`until` 가드와 `Condition`에 대응하는 IR kind가 없다(카탈로그 19종). RFC-0003도 가드의 실행 의미를 규정하지 않는다. 결과: 가드는 lowering에서 소실되고 피가드 항목만 노드가 된다 | RFC-0001 개정(조건·가드 kind 신설) + RFC-0003(평가 의미) |
| ② | `spec`·`given`·`when`·`expect`·`PhraseLine`에 대응 kind가 없다 — 테스트 명세는 IR 노드가 아니라 채택 요건 ④ 테스트 스위트로 산출한다 | ROADMAP Phase 1(`tests/` 신설) |
| ③ | 골든 IR의 `Validation`·`RepositoryCall`·`CacheAccess`(step 1~3의 자식)에 대응하는 표면 표기가 없다 — 이 3종은 선언된 의도로부터 컴파일러·에이전트가 도출하는 노드다 | RFC-0002 개정(표면 표기 신설) 또는 RFC-0004(도출 패스 규정) |
| ④ | `PipelineBlock`은 이름 토큰을 갖지 않는데 IR `Pipeline`은 `name`이 필수다 | RFC-0002 개정(이름 인자 추가) 또는 RFC-0001 개정(`name` 선택화) |
| ⑤ | 값이 없는 Performance metric 3종(`parallel`·`prefetch`·`batch`)은 `budgets[]` 항목이 `value`를 필수로 요구해 직렬화할 수 없다. 골든은 값이 있는 2종만 실증한다 | RFC-0001 부록 A(스키마 개정) |
| ⑥ | workflow 본문 직속의 `ParallelBlock`·`PipelineBlock`이 만든 Concurrency·Pipeline 노드는 `Workflow`의 children 허용 종별(WorkflowStep만)에 부착할 수 없다 — 소유 경로가 미해소다. 본문 §Guide-level의 `LoadDashboard` 비규범 예제가 이 형태다 | RFC-0001 개정(Workflow children 확장) 또는 RFC-0002 개정(블록을 step 하위로 한정) |
| ⑦ | 노드 `id`의 도출 규칙이 없다(형식만 규정됨). 골든의 `LoginService` → `svc.login`(접미사 제거), `UserCreated` → `event.user.created`(PascalCase 분해)는 기계 규칙이 자명하지 않다 | RFC-0001 개정 또는 ROADMAP Phase 1 파서 구현 |
| ⑧ | **R3은 Service 1개 모듈로만 실증된 잠정 규칙이다** — "모듈의 모든 capability를 모든 Service의 `requires`에 등재"는 골든과 정합하는 유일한 규칙이지만, Service가 2개 이상인 모듈에서 어느 Service가 어느 capability를 요구하는지(귀속)는 미해소다 | RFC-0002 개정(명시적 requires 표기 신설) 또는 RFC-0001 |

**A.5 Open Questions ⑤(goal 절의 lowering 대상) 해소.** `GoalLine`은
**BusinessRule** 노드로 lowering된다(라인 1개 = 노드 1개, `name` = `statement` =
동사구 원문). 근거: RFC-0001 Service의 children 허용 종별이 {Workflow, Pipeline,
BusinessRule}이므로 goal 라인을 WorkflowStep으로 Service에 직속시킬 수 없고,
"goal 절에서 Workflow를 자동 합성"하는 대안은 소스에 없는 실행 순서를 발명하므로
IR 정본 원칙(plan.md D1)에 반한다. goal 절은 실행 순서가 아니라 달성해야 할
규칙의 서술이므로 BusinessRule의 `name` + `statement` 계약과 정합한다.
`expression`(형식 표현)은 표기가 미정이므로 v0.1에서 비운다(Open Questions ②③).

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

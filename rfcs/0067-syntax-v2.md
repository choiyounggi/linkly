# RFC-0067: Syntax v2

## Status

- Status: **Accepted** (RFC-0067, 2026-10-28)
- Supersedes: RFC-0002

**통합 출처**

| 절 | 효력 있는 텍스트의 출처 |
|----|------------------------|
| Block structure (D5 개정판) | RFC-0060 §5 (RFC-0058 개정판을 전문 치환한 텍스트) |
| Workflow body & control | 가드 라인 항목은 RFC-0009 (RFC-0002 §Workflow body & control / 가드 라인 치환 텍스트), 나머지 항목은 RFC-0002 |
| Full grammar (W3C-style EBNF) | EBNF 블록의 `EventDecl`·`EventSource`·`Recurrence`·`TimeOfDay`·`Zone`·`Duration`은 RFC-0016 §1, `Comparison`·`Comparator`·`Value`·`Operand`·`Reference`·`Namespace`·`Integer`는 RFC-0015 §1, `Guard`·`AltGuard`·`ArithOp`는 RFC-0028 §1, `Condition`·`Term`·`Presence`·`NumericPred`는 RFC-0050 §1, `AssignStep`·`Aggregate`는 RFC-0025 §2, `AggFunc`는 RFC-0047 §1 (RFC-0045 §1 전체를 치환), `StepLine`은 RFC-0049 §Reference-level Specification (RFC-0002 §Full grammar 치환 텍스트 절), `RepoStepLine`·`ReadVerb`·`LookupClause`·`CacheClause`는 RFC-0062 §1 (RFC-0052 §1의 생산규칙을 치환), `GuardedItem`·`GuardTarget`·`OtherwiseItem`은 RFC-0060 §4, 그 밖의 생산규칙(`DurationUnit` 포함)은 RFC-0002. EBNF 뒤 문단은 RFC-0002의 두 문단에 이어 RFC-0008 §1 (기각된 형태 목록의 마지막 항목은 RFC-0012의 RFC-0008 §1 치환 텍스트), RFC-0012 (RFC-0002 §Full grammar / `Condition` 치환 텍스트), RFC-0015 §1 (`and` 항목은 RFC-0050 §1), RFC-0016 §1, RFC-0025 §2, RFC-0028 §1, RFC-0047 §1, RFC-0050 §1, RFC-0052 §1, RFC-0060 §4, RFC-0062 §1 순서다 |
| Open Questions | 항목 1·2·4·5는 RFC-0009 (RFC-0002 §Open Questions 치환 텍스트), 항목 3은 RFC-0002 본문의 해소 기록(커밋 95eafee, 2026-08-04) |

이 표에 없는 절은 RFC-0002의 텍스트 그대로다.

## Motivation

Semantic IR(RFC-0066)이 플랫폼의 설계 허브이지만(plan.md D1), 인간 개발자와 LLM
에이전트가 의도를 *작성*할 표면 표기가 필요하다. LNPL(워킹네임 — RFC-0000 §4,
소스 확장자 `.lnpl`)은 그 표면 언어다: 모든 문법 구성은 Semantic IR 노드로
lowering되는 표기일 뿐이며(lowering 매핑 표는 이 RFC의 후속 부록이 규정),
문법 자체는 어떤 실행 의미도 소유하지 않는다(실행 의미는 RFC-0068).

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

위 3건은 **문법 층위**의 선행 사례다. 플랫폼 층위(의도 선언 → 실행까지의 전체
파이프라인)의 선행 사례는 아래에서 다룬다.

#### 플랫폼 층위 선행 사례와 갈림점

같은 문제 — "LLM이 코드를 쓰는 시대의 개발 파이프라인" — 를 다루는 프로젝트가
이미 있다. 세 건을 직접 읽고 대조했다(2026-07-31 조사, 원문 링크·수치는
`docs/RESEARCH-NOTES.md` §7).

| 프로젝트 | 입력 표면 | IR의 역할 | 구현이 결정되는 지점 | 산출 |
|----------|----------|-----------|---------------------|------|
| [lhaig/intent](https://github.com/lhaig/intent) | 자체 문법 (계약 중심: 사전·사후조건, 불변식) | 컴파일 IR (`internal/ir/`) | 컴파일러 (결정적) + Z3 SMT 검증 | Rust · JS · Wasm 트랜스파일 |
| [l3yx/intentlang](https://github.com/l3yx/intentlang) | Python 임베드 (신규 문법 없음) | **프롬프트 구조화용** XML Intent IR | **런타임 LLM 생성** (생성→실행→관측→재투입, 최대 30회) | Python 바이트코드 |
| [pboueri/intentc](https://github.com/pboueri/intentc) | `.ic` 마크다운 + YAML frontmatter (피처 DAG) | 피처 의존 DAG | **빌드 시 에이전트 호출**(피처당 1회), `.icv` 실행 명세로 검증 | 타깃 언어 소스 코드 |
| **LNPP** | LNPL 선언 (`.lnpl`) | **의미 IR = 허브**(스키마 검증·조각 교환 가능한 정본) | **결정적 lowering**(MLIR 패스); 에이전트는 소스가 아니라 **IR을 제안** | 네이티브 바이너리 |

**핵심 갈림점은 "구현이 언제·누가 결정하는가"다.** intentlang과 intentc는
**합성(synthesis)** 노선이다 — 빌드 또는 런타임에 LLM이 *타깃 언어 소스를
생성*하고, 그 결과가 산출물이 된다. 같은 입력이 같은 출력을 낸다는 보장은
모델·프롬프트·반복 횟수에 의존한다. LNPP는 **결정적 lowering** 노선이다 —
LLM 에이전트는 IR 조각을 *제안*하고(RFC-0006 `ir.propose`, 승인 2단계), 승인된
IR에서 기계 코드까지는 컴파일러 패스가 결정적으로 내린다(RFC-0004). 재현성과
검증 가능성을 그 대가로 얻는다.

lhaig/intent는 같은 결정적 노선에 있어 가장 가까운 선행 사례다. 남는 차이는
셋이다: ① IR이 **구문/계약 중심이 아니라 의미 중심**이다(`BusinessRule`·
`RepositoryCall`·`CacheAccess` 같은 Effect 노드가 1급 — RFC-0066 §노드 카탈로그)
② 하강 경로가 트랜스파일이 아니라 **MLIR → 네이티브**다(RFC-0004 §파이프라인)
③ **Knowledge Base가 1급 구성요소**다 — 세 프로젝트 모두 에이전트가 공유하는
지식 계층을 구성요소로 두지 않는다(RFC-0005). 에이전트 협업 표면도 문서 규약
(`AGENTS.md`)이 아니라 와이어 프로토콜로 규정한다(RFC-0006, A2A/MCP 정렬).

**채택한 것.** intentc의 `.icv`(실행 가능한 검증 명세를 소스와 함께 두는 방식)는
LNPL `spec` 절의 산출 방향과 같다 — 이 RFC는 `spec` 절을 IR 노드가 아니라
테스트 스위트 아티팩트로 산출한다고 규정하며(부록 A.4-②), 그 판단은 intentc의
선례로 보강된다.

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
- **타입명** — `TypeName`은 `BaseTypeName`과 `RefinedTypeName`의 합이다
  (2026-08-04 개정 — Open Questions ③ 해소). `BaseTypeName`은 RFC-0066 Semantic
  Type 표의 18종 PascalCase 표기를 그대로 쓰는 닫힌 열거다: `UUID` `Money`
  `Email` `Phone` `Password` `Address` `Image` `File` `Currency` `GeoLocation`
  `Json` `Html` `Markdown` `Text` `Integer` `Decimal` `Boolean` `DateTime`.
  `RefinedTypeName`은 `refine` 선언(아래 Declarations)이 만든 이름 또는 내장
  preset 이름이며 형태는 `PascalName`이다. 어휘 우선순위는
  `BaseTypeName` > `RefinedTypeName`.
  따라서 **임의 타입명은 더 이상 문법 오류가 아니다** — 선언되지 않은 이름은
  문법이 아니라 **이름 해소** 단계에서 걸리며, 컴파일 패스가 오류를 일으켜야
  한다(RFC-0066 부록 A.6.1의 해소 순서와 A.7 불변식 ⓐ). 이는 규범이며 v0.1
  참조 구현에는 아직 그 검사가 없다.
- **리터럴** — `Integer`(십진 정수: `3`, `200`), `Duration`(정수+단위:
  `3s`, `5m`, `50ms`). 단위 카탈로그는 골든 시나리오 실증 3종 `ms`/`s`/`m`만
  (확장은 Open Questions ④).
- **비교식** — `Comparison ::= CamelName Comparator (Duration | Integer)`,
  `Comparator`는 `<` `<=` `>` `>=` 4종. 예: `response < 50ms`.
- **주석** — `#`부터 행 끝까지. 파서는 주석과 빈 라인을 무시한다.

### Keywords

| 분류 | 키워드 | 개수 |
|------|--------|------|
| 최상위 선언 | `entity` `service` `workflow` `event` `capability` `refine` | 6 |
| 절 | `field` `goal` `policy` `security` `performance` `database` `spec` `given` `when` `expect` | 10 |
| 제어 | `when` `repeat` `parallel` `until` `pipeline` `merge` | 6 |
| 선언 수식 | `on` (+ enum `create` `update` `delete`) `of` | 2(+3) |

최상위 선언 키워드 6종은 RFC-0066 Declaration kind 6종(Entity/Service/
Workflow/Event/Capability/Refinement)과 1:1이다. 키워드는 전부 소문자다.

facet 이름 6종(`pattern` `minLength` `maxLength` `min` `max` `enum`)은
키워드가 **아니다** — `policy` 절의 `retry`·`rollback`처럼 소속 블록의 내용
라인 어휘이며, 블록 밖에서는 평범한 `Word`로 남는다.

**문맥 한정 규칙** — 두 키워드는 블록 문맥으로 판별된다(파서 상태는 "현재
블록 종류" 하나로 충분하며 판별은 결정적이다):

- `when` — `spec` 절 내부에서는 `expect` 앞의 구획 키워드, workflow 본문에서는
  제어 가드. 두 문맥은 겹치지 않는다(spec 절은 workflow 본문의 마지막에만 온다
  — 아래 Clauses).
- `parallel` — `policy`/`performance` 절 내부에서는 내용 라인의 어휘(RFC-0066
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

2. **들여쓰기 비구조성** — 파서는 라인 선두 공백으로 블록을 만들지 않는다.
   관례 4칸·탭 금지는 style 권장일 뿐 문법이 아니다. **수용되는 모든
   프로그램에서, 같은 토큰열은 포맷팅과 무관하게 항상 같은 구조로 파싱된다.**

3. **모순 들여쓰기의 거부** — 다만 들여쓰기가 2항이 정한 구조와 **모순되는**
   프로그램은 수용 집합에서 제외한다(컴파일 에러). 들여쓰기는 구조를 만들지
   못하고 오직 프로그램을 반증할 수만 있으므로, 2항의 보장은 유지된다.
   모순은 다음 셋이며, 이 목록은 닫혀 있다.

   a. **가드 스코프 모순.** 가드(`when`/`until`/`repeat`) 또는 `otherwise`가 자기보다
      깊은 열의 항목을 소유할 때, 그 다음에 오는 첫 줄(최상위 항목이나 `otherwise`)이
      여전히 가드보다 깊은 열에 있으면 거부한다. 가드와 `otherwise`는 항목 하나만
      소유하므로(RFC-0069 §5.2) 그 줄은 밖에서 작동하는데, 열은 안에 있다고 말하기
      때문이다.

   b. **spec 꼬리 모순.** `spec` 절의 섹션(`given`/`when`/`expect`)이 `spec`보다
      깊은 열에 있을 때, 그 블록 안의 내용 줄이 `spec`과 같거나 더 얕은 열에
      있으면 거부한다. 워크플로의 항목은 `spec` 앞에 오므로(§Full grammar:
      `WorkflowItem* SpecClause?`) 그 줄은 항목이 될 수 없는데, 열은 항목인 것처럼
      말하기 때문이다.

   c. **파이프라인 암묵 종결 모순.** `pipeline`이 열려 있을 때, 그 `pipeline` 줄보다
      깊은 열에 제어 키워드(`when`/`until`/`repeat`/`pipeline`/`parallel`) 또는
      `otherwise`가 오면 거부한다. `pipeline`은 다음 키워드에서 저절로 닫히므로(1항) 그
      키워드는 파이프라인 밖에서 작동하는데, 열은 안에 있다고 말하기 때문이다. 에러
      문면은 닫히는 파이프라인(이름, 이름이 없으면 그 줄 번호)과 고치는 법을 싣는다:
      가드나 `otherwise`면 파이프라인 자신의 열로 내어 쓰거나 뒤 스텝을 새 `pipeline`으로
      묶을 것, 블록 개시면 파이프라인 자신의 열로 내어 쓸 것. 열린 `parallel`에는 적용되지
      않는다 — `parallel`은 `merge`로만 닫히고, 그 안의 가드·`otherwise`·블록 개시는 이미
      거부된다(4항). 선언 키워드나 파일 끝에서 닫히는 경우도 대상이 아니다.

   세 규칙 모두 **레이아웃이 정보를 담을 때만** 발동한다: 가드와 그 항목이 같은
   열이면 a가, 섹션과 `spec`이 같은 열이면 b가, 키워드가 `pipeline` 줄과 같거나 더
   얕은 열이면 c가 발동하지 않는다. 전부 같은 열에 쓴 프로그램은 이 항의 적용을
   받지 않는다.

4. **중첩 ≤2** — 선언 = 레벨 0, 절과 제어 블록 = 레벨 1, 그 내부 구획
   (`given`/`when`/`expect`, `parallel`의 브랜치 step) = 레벨 2. 그 이상의
   중첩은 문법적으로 불가능하다 — `ParallelBlock`과 `PipelineBlock`의 본문은
   `StepLine`만 허용하므로(§Full grammar의 EBNF) parallel 안의 parallel,
   spec 안의 spec은 생산규칙 차원에서 존재하지 않는다. `otherwise`는 가드의 형제라
   레벨을 더하지 않는다. 그래서 자리가 닫혀 있다 — 다음은 전부 컴파일 에러다:
   `when` 가드의 항목 바로 다음 줄이 아닌 곳의 `otherwise`(가드 없음, 사이에 다른
   항목이 낀 경우 포함), 한 가드의 두 번째 `otherwise`, `until`/`repeat` 가드 뒤의
   `otherwise`(거짓 가지가 없다), 열린 `parallel` 안의 `otherwise`, 아직 항목이 없는
   가드 뒤의 `otherwise`, `otherwise` 바로 다음의 가드(`else if` 없음), 아무것도
   소유하지 않고 선언이 끝나는 `otherwise`, 같은 줄에 낱말이 붙은 `otherwise`.

5. **한 줄 한 선언** — 모든 선언·절 개시·step·내용 항목은 정확히 한 라인이다.

### Declarations

| 형식 | lowering 대상(비규범 힌트) |
|------|---------------------------|
| `entity <PascalName>` + `field` 절 | Entity |
| `service <PascalName>` + 절들 | Service |
| `workflow <PascalName>` + step 본문 | Workflow |
| `event <PascalName> [on <PascalName> (create\|update\|delete)]` | Event(`on …` → `source={ref, on}`) |
| `capability <CapabilityName> [<Version>]` | Capability |
| `refine <PascalName> of <BaseTypeName>` + facet 라인 1개 이상 | Refinement(`name`/`base`/`facets` → RFC-0066 부록 A.6) |

- `capability`는 한 줄이 한 선언이다(블록형 아님 — Alternatives ③). 골든
  시나리오의 3개 capability는 3개의 선언 라인이다.
- `event`의 `on` 수식은 RFC-0066 Event의 `source={ref, on: create|update|
  delete}` 필드의 표면 표기다. enum 3값은 IR 표기를 그대로 쓴다.
- `refine`은 블록형이다 — 선언 라인 뒤에 facet 라인이 **1개 이상** 와야 하며,
  다음 최상위 키워드에서 닫힌다. facet 어휘 6종과 base별 적용 가능성은
  RFC-0066 부록 A.6.3이 소유하는 닫힌 열거다. `URL`·`Slug`·`PositiveInteger`는
  선언 없이 쓰는 내장 preset이고 그 이름은 재선언할 수 없다(부록 A.6.4).
- **귀속(인접성) 규칙** — `workflow` 선언은 소스에서 가장 가까운 *선행*
  `service` 선언에 귀속된다(선언 순서 유의미). 선행 service가 없으면 독립
  진입 선언이다(RFC-0066 구조 규칙 2 — Declaration만 진입 노드). 이 귀속의
  정식 lowering 매핑은 후속 부록이 규정한다.

### Clauses

| 절 | 소속 | 내용 라인 |
|----|------|-----------|
| `field` | entity | `FieldLine ::= CamelName TypeName` — required 기본 true(optional 표기는 Open Questions ④) |
| `goal` | service | `GoalLine` = StepLine과 동형(동사구) |
| `policy` | service | `'retry' Integer \| 'rollback' \| 'timeout' Duration \| 'parallel'` — RFC-0066 Policy rule name 초기 카탈로그와 1:1 |
| `security` | service | `'jwt' \| 'role' Word \| 'encrypt' CamelName` — RFC-0066 Security mechanism 초기 카탈로그와 1:1 |
| `performance` | service | `'response' Comparator Duration \| 'cache' Duration \| 'parallel' \| 'prefetch' \| 'batch'` — RFC-0066 Performance metric 초기 카탈로그와 1:1 |
| `database` | service | `DatabaseLine ::= CapabilityName` |
| `spec` | workflow | 이름 인자 없음(소속 workflow가 대상). 내부에 `given`(선택)·`when`(필수)·`expect`(필수) 구획, 각 구획의 내용은 `PhraseLine`(1~4 토큰의 구 또는 비교식 — `valid account`, `login`, `status 200`, `token exists`). **spec 절은 workflow 본문의 마지막에만 온다**(step 라인과 PhraseLine의 중의성 차단) |

정책·보안·성능 어휘가 닫힌 열거인 것은 RFC-0066 Constraint 카탈로그(consume-
only)의 귀결이다 — 신규 어휘 추가는 RFC-0066의 개정 사항이지 이 문법의 확장이
아니다.

### Workflow body & control

workflow 본문의 각 라인은 step이거나 제어 구조다:

- **StepLine** — `Verb Word? Word? Word?`: 동사 선두 1~4토큰. 권장형은
  동사+목적어 2~4토큰(`validate input`, `generate token`)이고, 목적어가
  자명한 경우 단독 동사를 허용한다(골든 시나리오의 `authenticate`). 자유
  텍스트(5토큰 이상, 동사 비선두)는 금지다. 토큰 상한이 실측 없는 설계
  가설임은 Open Questions ①에 명시한다. step의 `name`은 RFC-0066
  WorkflowStep의 `name`(동사구) 계약과 정합한다.
- **가드 라인** — `when <Condition>`·`repeat <Integer>`·`until <Condition>`은
  **직후 1개의** step 또는 parallel/pipeline 블록에 적용되는 접두 가드다.
  별도 블록을 열지 않으므로 적용 범위가 항상 명확하다. `Condition`은
  `Presence | Comparison`이다(RFC-0008 §Full grammar). 가드의 실행 의미(조건
  평가·반복 종료)는 RFC-0068 소유다.
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
                    | CapabilityDecl | RefineDecl

EntityDecl        ::= 'entity' PascalName EOL FieldClause+
ServiceDecl       ::= 'service' PascalName EOL ServiceClause*
ServiceClause     ::= GoalClause | PolicyClause | SecurityClause
                    | PerformanceClause | DatabaseClause
WorkflowDecl      ::= 'workflow' PascalName EOL WorkflowItem* SpecClause?
EventDecl    ::= 'event' PascalName EventSource? EOL
EventSource  ::= 'on' PascalName ('create' | 'update' | 'delete')
               | 'on' 'schedule' Recurrence 'at' TimeOfDay Zone
Recurrence   ::= 'daily'
TimeOfDay    ::= Digit Digit ':' Digit Digit          (* 00:00 ~ 23:59 *)
Zone         ::= 'UTC'
CapabilityDecl    ::= 'capability' CapabilityName Version? EOL
RefineDecl        ::= 'refine' PascalName 'of' BaseTypeName EOL FacetLine+
FacetLine         ::= ('pattern' Regex | 'minLength' Integer
                    | 'maxLength' Integer | 'min' Number | 'max' Number
                    | 'enum' EnumValue+) EOL

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
GuardedItem       ::= WhenGuard GuardTarget OtherwiseItem?
                    | (RepeatGuard | UntilGuard) GuardTarget
GuardTarget       ::= StepLine | ParallelBlock | PipelineBlock
OtherwiseItem     ::= 'otherwise' EOL GuardTarget
WhenGuard         ::= 'when' Condition EOL
RepeatGuard       ::= 'repeat' Integer EOL
UntilGuard        ::= 'until' Condition EOL
ParallelBlock     ::= 'parallel' EOL StepLine+ 'merge' EOL
PipelineBlock     ::= 'pipeline' EOL StepLine+
StepLine ::= Verb Word* EOL
RepoStepLine   ::= ReadVerb Entity LookupClause? CacheClause? EOL
                 | ('update' | 'delete') Entity LookupClause? EOL
                 | ('create' | 'insert') Entity ('as' CamelName)? EOL
ReadVerb       ::= 'find' | 'read' | 'load' | 'authenticate'
LookupClause   ::= 'by' Reference
CacheClause    ::= 'cached'
Verb              ::= Word
Condition    ::= Presence | Term ('and' Term)*
Term         ::= Comparison | NumericPred
Presence     ::= Reference ('exists' | 'missing')
NumericPred  ::= Reference ('is-numeric' | 'is-not-numeric')
Guard        ::= 'when' Condition AltGuard* | 'until' Condition
AltGuard     ::= 'or' Condition
Value        ::= Operand (ArithOp Operand)?
Operand      ::= Reference | Integer | Duration
ArithOp      ::= '+' | '-' | '*' | '/'
Reference    ::= CamelName | Namespace '.' CamelName
Namespace    ::= 'input' | CamelName
AssignStep    ::= 'set' Reference 'to' (Value | Aggregate)
Aggregate     ::= AggFunc Reference
AggFunc      ::= 'sum' | 'count' | 'avg' | 'min' | 'max'

/* ---- 렉시컬 ---- */
Comment           ::= '#' [^#xA#xD]* EOL
BlankLine         ::= EOL
PascalName        ::= [A-Z] [A-Za-z0-9]*
CamelName         ::= [a-z] [a-zA-Z0-9]*
CapabilityName    ::= [a-z] [a-z0-9]*
Word              ::= [a-z] [a-zA-Z0-9]*
Version           ::= [0-9] [A-Za-z0-9.]*
TypeName          ::= BaseTypeName | RefinedTypeName
BaseTypeName      ::= 'UUID' | 'Money' | 'Email' | 'Phone' | 'Password'
                    | 'Address' | 'Image' | 'File' | 'Currency' | 'GeoLocation'
                    | 'Json' | 'Html' | 'Markdown' | 'Text' | 'Integer'
                    | 'Decimal' | 'Boolean' | 'DateTime'
RefinedTypeName   ::= PascalName
Regex             ::= [^#x9#xA#xD#x20#x23]+
Number            ::= '-'? [0-9]+ ('.' [0-9]+)?
EnumValue         ::= Word | Number
Integer      ::= [0-9]+
Duration     ::= Integer ('ms' | 's' | 'm' | 'h' | 'd')
DurationUnit      ::= 'ms' | 's' | 'm'
Comparator   ::= '<' | '<=' | '>' | '>=' | '==' | '!='
Comparison   ::= Value Comparator Value
EOL               ::= #xA | #xD #xA
```

주: 생산규칙 이름들은 후속 lowering 매핑 표의 좌변이 되는 안정 계약이다 —
이름 변경은 이 RFC의 개정 사항이다. 키워드·예약어는 `PascalName`·`CamelName`·
`CapabilityName`·`Word`의 값에서 제외된다(렉시컬 우선순위: 키워드 > 식별자).
같은 층위에서 `BaseTypeName` > `RefinedTypeName`이다 — 18종과 같은 철자는
언제나 base로 읽히므로 `TypeName`의 두 분기는 중의적이지 않다.

`Regex`가 공백·탭·`#`를 배제하는 것은 임의 제약이 아니라 렉서의 귀결이다:
토큰은 공백으로 분리되고(`Line.tokens = body.split()`), `#`부터 행 끝은 주석으로
버려지며, 탭은 거부된다(본문 §Block structure). 따라서 정규식 안에 공백이
필요하면 `\s`나 `[ ]`로, `#`가 필요하면 `\x23`으로 쓴다. 부록 A.6.4의 내장
preset 정규식 3종은 모두 이 제약을 만족한다.

**예약어 추가:** `exists`, `missing`을 예약어에 등록하여 필드명으로 사용 불가하게 한다.

**Comparator 집합** (RFC-0002 이미 정의):
- `<`, `<=`, `>`, `>=`, `==`, `!=`

**기각된 형태:**
- 1~4토큰 자유 구 (`Word Word? Word? Word?`)
- 논리 결합 (`and`, `or`, `not`) — 별도 계획 RFC-000X 대상
- 멤버십 연산
- **3단 이상의 경로**(`a.b.c`) — 바인딩은 행 하나이고 행의 필드는 스칼라다. 중첩 경로를
  받으려면 평가기가 중첩 구조를 순회해야 하는데, 참조 구현의 행은 평면 dict이므로 그 순회가
  평가할 대상이 없다. RFC-0008이 "평가기 없는 생산 규칙"을 제거한 것과 같은 판정이다.

`CamelName ::= [a-z] [a-zA-Z0-9]*` 는 RFC-0002 §Lexical 원문 그대로다. 점(`.`)은 `CamelName`에
속하지 않으므로 `Reference`의 두 조각은 각각 `CamelName`이어야 하며, 조각은 **정확히 1개 또는
2개**다. `a.b.c`는 이 생산 규칙에 해당하지 않는다.

세 가지 제한은 누락이 아니라 결정이다.

- **`or`·`not`·괄호 없음.** 이 RFC는 이슈 #47의 5개 요구를 덮는 최소 표면을 정의한다.
  생산규칙 하나를 더할 때마다 인터프리터와 방출된 MLIR **양쪽**에 같은 평가기를
  유지해야 한다. 표현력 확장은 다음 RFC의 몫이다(RFC-0008 §Alternatives가 세운 순서
  그대로: 검증 가능한 등가를 먼저 세우고 그 위에 쌓는다).
- **`and`는 비교식과 숫자 형태 술어만 잇는다.** 모드 B는 존재 여부를 실행당 boolean
  하나(`run_binary(skip=…)`)로 판정하고 비교는 i64 파라미터로 판정한다. 한 조건에 두
  채널이 섞이면 모드 B가 모드 A와 다른 스텝 집합을 낼 수 있다. 그래서 존재 검사는
  여전히 단독 가드로 쓴다. 숫자 형태 술어에는 이 우려가 없다 — 모드 B에 그 술어의
  채널이 아예 없고, 술어를 쓴 워크플로는 모드 B가 빌드를 거부한다(§4). 섞일 두
  번째 컴파일 채널이 없다.
- **산술은 중첩하지 않는다.** `a - b - c`는 우선순위 규칙을 요구하고, 우선순위 규칙은
  저자가 조용히 틀릴 수 있는 종류의 것이다. 곱셈·나눗셈은 없다(§Alternatives).

**리터럴은 부호가 없다.** 계산 **결과**는 음수일 수 있다. 모드 B가 상수를
`%c<value>_i64`라는 SSA 이름으로 선언하므로 `%c-3_i64`는 유효한 이름이 아니다.

**정규화.** 항은 소스 순서대로 ` and `로 잇고, 비교는 `<left> <op> <right>`, 산술은
`<a> <op> <b>`, 공백은 정확히 1칸이다. Duration은 최적 단위로 되돌린다(`60000` → `1m`).
이 문자열이 IR에 실리고, 두 모드가 그것을 비교하며, RFC-0071의 skip 레코드가 그것을
싣는다.

`h` = 3600000 ms, `d` = 86400000 ms. 주(`w`)·월·년은 넣지 않는다: 월과 년은 길이가
가변이라 정수 상수로 정의할 수 없다.

`Value`와 `Aggregate`는 **결합하지 않는 별개 생산 규칙**이다 — 기존 `Value`(산술)를
넓혀 집계를 흡수하면 `sum x + 1`이 파싱되게 되는데, 이는 Guide-level Explanation이
명시적으로 금지한 형태다. `AssignStep`이 두 우변 중 하나를 택일해 받는 것으로,
표현력의 결합 없이 집계라는 세 번째 값 출처를 더한다.

`Reference`는 RFC-0072 §1이 정의한 그대로다(`CamelName | Namespace '.' CamelName`).
`count link`의 `Reference`는 한 조각(RowSet 바인딩 이름), `sum link.clicks`의
`Reference`는 두 조각(RowSet 바인딩 이름 + 필드)이다. 파서 층위에서 `Aggregate`와
`Value`는 첫 토큰(`sum`/`count` 대 그 밖)으로 구별되며, 렉서·`given`/`expect`
phrase 라인의 토큰화(`Line.tokens = body.split()`)는 바뀌지 않는다.

**정규화.** `Assignment.expression`(RFC-0072 §2)에 싣는 문자열은 `<func> <ref>`,
공백 1칸 — `"sum link.clicks"`, `"count link"`. `Assignment` 노드의 다른 필드
(`kind`/`id`/`target`/`entity`)와 스키마(`schemas/lir.schema.json`의
`nodeAssignment`)는 바뀌지 않는다: `expression`은 이미 자유 문자열이고
(`"type": "string"`, 패턴 제약 없음), 정규화된 새 형태를 싣는 데 스키마 변경이
필요 없다.

`AltGuard`는 `Condition`을 그대로 재사용한다 — 새 생산 규칙이 아니라 **기존
`Condition` 하나를 여러 번 쓰는 구조**다. `and`가 `Comparison`을 묶듯, `or`는
`Condition` 전체(대안 하나)를 묶는다. 그래서 대안 하나가 `and`로 여러 항을 가질
수 있으면서도(`Condition`의 기존 정의 그대로), 대안끼리는 절대 한 `Condition`
안에서 섞이지 않는다 — `or`가 `Condition` 문법 안으로 들어가는 경로가 애초에
없기 때문이다. 이것이 §Motivation이 말한 "연산자가 아니라 구조"의 문법적 근거다.

`Guard`가 `('when'|'until') Condition` 하나의 생산 규칙에서 두 갈래로 갈라진
것은 실질 변경이지만, 두 갈래 모두 `Condition`을 정확히 한 번 요구하는 것은
그대로다 — `until`이 잃는 것은 없다.

**리터럴은 부호가 없다** (RFC-0015 §1 불변, 재확인). `/`의 나눗셈 결과가
음수일 수 있는 것은 계산 **결과**이지 리터럴이 아니므로 이 제약과 모순하지
않는다 — `-3`을 나눗셈으로 만드는 것과 `product.price * -1`처럼 리터럴 자리에
음수를 직접 쓰는 것은 다르다. 후자는 여전히 거부된다(모드 B가 `%c<value>_i64`로
상수를 선언하므로 `%c-3_i64`는 유효한 SSA 이름이 아니다 — RFC-0015 §1 원문의
사유 그대로 `*`/`/`에도 적용된다).

**나눗셈은 절삭(truncating)이다.** `a / b`는 `int(a / b)`가 아니라 C의 정수
나눗셈과 같은 절삭 방식으로 정의한다: 몫을 0 방향으로 자른다. 이 언어의 값
도메인(§4)은 부호 있는 64비트 정수이고 피연산자가 음수일 수 있으므로(계산
결과가 음수일 수 있다는 §1 원문이 이미 인정한 사실), "버림"(floor, `-7 // 2
== -4`)과 "절삭"(truncate, `-7 / 2 == -3`)이 갈린다. 절삭을 고른 이유는 모드
B가 컴파일하는 `arith.divsi`(MLIR standard dialect의 부호 있는 정수 나눗셈)가
바로 이 의미론이기 때문이다 — 모드 A가 다른 규칙(Python `//`, floor)을 쓰면
`stock=-7, batch=2`류의 입력에서 두 모드가 다른 몫을 내고, `EQUIVALENT`가 그
차이를 조용히 넘기게 된다. 모드 A는 Python에서 `math.trunc(a / b)`가 아니라
`int(a / b)`가 이미 절삭이 아니라 0을 향한 버림과 다르게 동작할 수 있는 함정이
있어(부동소수 경유), 정수 전용 절삭 연산(`-(-a // b) if (a < 0) != (b < 0) else
a // b`류, 또는 동등한 정수 전용 절삭식)으로 구현해야 한다 — 실측 요구 조건은
"모드 A/B가 같은 몫을 낸다"이지 "Python이나 C 중 어느 쪽 관용구를 쓰는가"가
아니다.

`count link`·`sum link.clicks`처럼
`avg link.clicks`·`min link.clicks`·`max link.clicks`도 `Reference`가
두 조각(RowSet 바인딩 이름 + 필드)이다. 정규화 문자열
(`Assignment.expression`에 싣는 `<func> <ref>`)의 `<func>` 자리에
`avg`/`min`/`max`가 그대로 들어간다 — RFC-0025 §2의 "정규화" 문단이 세운
"정규화된 새 형태를 싣는 데 스키마 변경이 필요 없다"는 판단은 **이
정규화 표현에 한정해서** 지금도 유효하다: `expression`은 여전히
`"type": "string"`, 패턴 제약 없는 자유 문자열이고, `avg`/`min`/`max`를
그 문자열에 싣는 데 스키마 변경이 필요 없었다는 사실은 바뀌지 않는다.

**새로 여는 것 — `nodeAssignment.agg_field_type` (RFC-0047).** 위
정규화 판단과는 **별개의 관심사**로, `nodeAssignment`가 선택 필드 하나를
새로 받는다:

```json
"agg_field_type": {"enum": ["Integer", "DateTime", "Money"]}
```

- **새 IR 노드가 아니다** — `kind: "Assignment"`는 그대로다. 기존
  `nodeAssignment`가 선택 키 하나를 더 받을 뿐이다.
- **필수 필드가 아니다** — `required`에 들어가지 않는다. 집계가 아닌
  `Assignment`(보통의 산술 `set`, `format`)와 `count`(필드가 아니라
  엔티티를 세므로 base 타입이 없다)에는 이 키가 없다. 옛 컴파일러가 낸
  문서에도 없다 — §5가 그 부재를 하위호환 계약으로 다룬다.
- **`additionalProperties: false`는 그대로다** — `nodeAssignment`가
  받는 키의 전체 집합에 하나를 더할 뿐, 스키마의 폐쇄성 자체는 이 RFC가
  건드리지 않는다.
- 값은 `_check_aggregate`(lower.py)가 정적으로 판정하는 base 타입과
  같은 어휘(`Integer`/`DateTime`/`Money`) — `sum`/`avg`는 그중
  Integer·Money만, `min`/`max`는 셋 다 받을 수 있다는 §Reference-level
  Specification/2의 표는 이 RFC가 바꾸지 않는다. `agg_field_type`은 그
  표가 이미 내린 판정을 실행까지 나르는 채널일 뿐, 새 판정을 더하지
  않는다.

구현: `impl/lnpl/lexer.py`의 `NUMERIC_PREDICATE_KINDS = ("is-numeric",
"is-not-numeric")`와(같은 파일로 옮긴 `PRESENCE_KINDS = ("exists", "missing")`),
`impl/lnpl/condition.py`의 `NumericPredicate(field, kind)` 노드. 두 낱말은
참조 이름이 될 수 없다(`and`/`to`/`exists`/`missing`과 같은 예약). 정규화 문자열은
`<field> <kind>`이고, `and` 항 안에서도 소스 순서 그대로 ` and `로 이어진다 — IR의
`Guard.condition`은 여전히 문자열 하나다(RFC-0015 §2 불변, 스키마 변경 없음).

`lnpl vocab`(및 MCP `lnpl_vocabulary`)의 `keywords`는 `presence_kinds`와
`numeric_predicate_kinds`를 싣는다.

`Reference`는 RFC-0070 §G12.1의 생산 규칙(`CamelName ('.' CamelName)?`)이다. `by`는
렉서 키워드가 아니다 — `as`·`with`·`where`처럼 꼬리 토큰의 첫 자리에서 위치로 읽는다.
기존 `by` 토큰(`consume … by <group>`, `expose <verb> <Entity> by <field>`, `list … order
by <field>`)은 전부 다른 절 위치에 있어 충돌하지 않는다.

`ReadVerb`·`update`·`delete` 뒤의 꼬리 토큰이 비어 있지도, 정확히 `by <Reference>`도
아니면 컴파일 오류다:

```
line <N>: `<verb> <object>` accepts either no trailing words or `by <ref>`, got <tokens>
```

`create`/`insert`의 꼬리 규칙과 오류 문구(`create accepts either no trailing words or 'as
<name>', got …`)는 바뀌지 않는다 — `by`는 그 문구로 거부된다.

IR: `RepositoryCall` 노드가 선택적 문자열 필드 `lookup`을 갖는다 — 값은 참조 원문
(`"input.productId"`). `by`가 없으면 필드 자체가 없다 — `by` 없는 프로그램의 IR은 이 RFC
이전과 바이트 단위로 같다. `schemas/lir.schema.json`의 `nodeRepositoryCall.lookup`
(`type: string`, `required` 아님)이 이를 닫는다.

`WhenGuard` 뒤의 `or` 줄은 RFC-0076 §1의 `Guard`/`AltGuard`
생산규칙 그대로다.

`OtherwiseItem`은 `Condition`을 갖지 않는다 — 조건 문법(RFC-0072 §1, RFC-0076 §1)은 그대로다.
`OtherwiseItem` 안에 다시 `GuardedItem`이 오는 생산규칙은 없다(`else if` 없음).

`cached`는 렉서 키워드가 아니다 — `by`처럼 꼬리 토큰에서 위치로 읽는다. 어휘 문서와
provenance의 `vocabulary_digest`는 바뀌지 않는다.

읽기 동사의 꼬리 토큰이 비어 있지도, `by <Reference>`도, `cached`도, `by <Reference> cached`도
아니면 컴파일 오류다:

```
line <N>: `<verb> <object>` accepts either no trailing words, `by <ref>`, `cached`, or `by <ref> cached`, got <tokens>
```

`update`/`delete`의 꼬리 규칙과 오류 문구(`accepts either no trailing words or `by <ref>``)는
바뀌지 않는다 — `cached`는 그 문구로 거부된다. `cached cached`, `cached by <ref>`, 그리고 그
밖의 모든 낱말도 위 문구로 거부된다.

IR: `RepositoryCall` 노드가 선택적 불리언 필드 `cached`를 갖는다. 절이 없으면 필드 자체가
없다 — 절 없는 프로그램의 IR은 이 RFC 이전과 바이트 단위로 같다(코퍼스 48개 파일 전수).
`schemas/lir.schema.json`의 `nodeRepositoryCall.cached`(`type: boolean`, `required` 아님)가
이를 닫는다.

### 경계

이 문서는 표면 문법만 규정한다. 문법 구성 → IR 노드의 lowering 매핑 표와
`examples/login.lnpl` 파일 추출은 이 RFC의 후속 부록(태스크 04)이, 노드·타입
정의는 RFC-0066이, 실행 의미(가드 평가·병렬 병합·재시도)는 RFC-0068이,
IR 직렬화는 RFC-0066 부록 A가 소유한다.

### 부록 A: Lowering 매핑

문법 구성 → Semantic IR 노드의 매핑을 확정한다(본문 §경계가 이 부록에 위임한
항목). 본 부록은 위 본문(EBNF·키워드·블록 규칙)을 변경하지 않으며, IR 쪽
정의(RFC-0066 노드 카탈로그·`schemas/lir.schema.json`)도 변경하지 않는다 —
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
  선언의 `children`에 append된다(본문 §Declarations 귀속 규칙 + RFC-0066 구조
  규칙 2 소유 유일). 선행 service가 없으면 진입 노드다.
- **R3(capability 요구 — 잠정)** — 모듈 내 각 `capability` 선언은 Capability
  노드를 만들고, 그 id를 모듈 내 모든 Service의 `requires`에 **선언 순서대로**
  등재한다. 이 규칙은 Service가 1개인 골든 시나리오로만 실증되었다 — 다중
  Service 모듈의 귀속은 미해소이므로 **잠정 규칙**이다(A.4-⑧).
- **R4(제약 참조)** — Policy·Security·Performance 노드는 `children`으로 소유되지
  않고 소속 Service의 `constraints`로만 참조된다(RFC-0066 구조 규칙 5).

노드 `id`의 **도출 규칙은 이 부록이 규정하지 않는다** — RFC-0066은 id의 형식
(dot-path 정규식)만 규정하며, A.3의 id는 골든 예제의 실제 값을 대조 대상으로
인용한 것이다(A.4-⑦).

**A.2 생산규칙 → IR 노드 kind 매핑.** 본문 §Full grammar의 58개 생산규칙 전량이
행으로 존재한다(행 순서 = EBNF 등장 순서).

| 생산규칙 | IR 노드 kind | 매핑 규칙 비고 |
|----------|-------------|----------------|
| `SourceFile` | — | `[구문]` R1 — 파일 1개가 IR 문서 1개에 대응하며 그 자체로는 노드가 아니다 |
| `Declaration` | — | `[구문]` 6택 선택 규칙 — 노드는 각 하위 규칙이 만든다 |
| `EntityDecl` | Entity | 노드 1개. `name` = PascalName, `fields` = FieldClause의 내용 |
| `ServiceDecl` | Service | 노드 1개. `name` = PascalName. 절이 `constraints`(R4)를, 귀속 workflow가 `children`(R2)을, R3가 `requires`를 채운다 |
| `ServiceClause` | — | `[구문]` 5택 선택 규칙 |
| `WorkflowDecl` | Workflow | 노드 1개. `name` = PascalName, `children` = 본문 항목이 만든 노드의 소스 순서(RFC-0066 구조 규칙 3). 소유자는 R2 |
| `EventDecl` | Event | 노드 1개. `name` = PascalName. children 없음 |
| `EventSource` | — | `[필드흡수]` 부모 Event의 `source = {ref: 대상 Entity 노드 id, on: create\|update\|delete}`. enum 3값은 IR 표기 그대로 |
| `CapabilityDecl` | Capability | 노드 1개. `name` = CapabilityName, `Version`이 있으면 `version`(문자열). 추가로 R3(**잠정** — A.4-⑧)에 따라 각 Service의 `requires`에 등재 |
| `RefineDecl` | Refinement | 선언 1개 = 노드 1개. `name` = PascalName, `base` = BaseTypeName, `facets` = FacetLine들이 채운다. 진입 노드이며 어떤 `children`에도 등장하지 않는다(RFC-0066 구조 규칙 2). id는 A.4-⑦ 규칙 + kind 접두 `refine`(`Slug` → `refine.slug`). 사용된 내장 preset도 같은 형태의 노드로 방출된다(RFC-0066 부록 A.6.4 emit-on-use) |
| `FacetLine` | — | `[필드흡수]` 부모 Refinement의 `facets` 객체에 키 1개. `pattern`/`min`/`max`는 값 1개, `enum`은 `EnumValue+`를 배열로. 같은 facet의 중복 지정은 오류다(객체 키는 유일) |
| `FieldClause` | — | `[구문]` 구획 키워드 — 내용은 부모 Entity의 `fields`로 간다 |
| `FieldLine` | — | `[필드흡수]` `fields[]` 항목 `{name: CamelName, type: TypeName}`. `required` 키를 생략하면 필수(true)로 해석된다(RFC-0066 부록 A.4) |
| `GoalClause` | — | `[구문]` 구획 키워드 — 생성 노드의 소유자는 소속 Service |
| `GoalLine` | BusinessRule | 라인 1개 = 노드 1개. `name` = `statement` = 동사구 원문, `expression`은 v0.1에서 미기입(표현식 표기가 Open Questions ②③로 미정). 소속 Service의 `children`에 소스 순서로 append. → 본문 Open Questions ⑤의 해소(A.5) |
| `PolicyClause` | Policy | 절 1개 = 노드 1개. `rules[]`는 PolicyLine들이 채우고, 소속 Service는 R4로 참조한다 |
| `PolicyLine` | — | `[필드흡수]` `rules[]` 항목: `retry N` → `{name:"retry", value:N}`(수치), `rollback` → `{name:"rollback"}`(value 없음), `timeout D` → `{name:"timeout", value:"3s"}`(문자열), `parallel` → `{name:"parallel"}` |
| `SecurityClause` | Security | 절 1개 = 노드 1개. `mechanisms[]`를 SecurityLine이 채우고 R4로 참조된다 |
| `SecurityLine` | — | `[필드흡수]` `mechanisms[]`의 문자열 항목 — `jwt` → `"jwt"`, `role admin` → `"role admin"`, `encrypt password` → `"encrypt password"`(RFC-0066 초기 카탈로그 표기 그대로) |
| `PerformanceClause` | Performance | 절 1개 = 노드 1개. `budgets[]`를 PerformanceLine이 채우고 R4로 참조된다 |
| `PerformanceLine` | — | `[필드흡수]` `budgets[]` 항목: `response < 50ms` → `{metric:"response", value:"<50ms"}`(Comparator와 Duration을 공백 없이 연결), `cache 5m` → `{metric:"cache", value:"5m"}`. 값 없는 `parallel`·`prefetch`·`batch`는 스키마가 `value`를 필수로 요구하므로 v0.1 미해소(A.4-⑤) |
| `DatabaseClause` | — | `[구문]` 구획 키워드 — 노드를 만들지 않는다 |
| `DatabaseLine` | — | `[필드흡수]` 소속 Service의 `requires`에 해당 Capability id를 멱등 등재(R3로 이미 있으면 추가하지 않는다). 노드 생성은 `CapabilityDecl`이 소유하며, 선언되지 않은 이름은 dangling 참조 금지(RFC-0066 구조 규칙 6) 위반이다 |
| `SpecClause` | — | `[공백]` IR 카탈로그 20종에 테스트 명세 노드가 없다. spec은 IR 노드가 아니라 채택 요건 ④ 테스트 스위트 아티팩트(plan.md D20)로 산출된다(A.4-②) |
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
| — (동사 사전) | EventEmit | `emit <eventName>`·`publish <eventName>`: 목적어가 발행할 이벤트를 지목하고, id는 R2 규칙을 이벤트 이름에 적용해 얻는다(`userCreated` → `event.user.created`). 목적어가 없으면 참조할 대상이 없으므로 컴파일 오류다(2026-07-31 구현) |
| `Verb` | — | `[구문]` StepLine의 첫 토큰 — `name` 문자열의 일부로만 남는다 |
| `Condition` | — | `[공백]` 가드 전용 — 대응 kind가 없다(A.4-①) |
| `Comment` | — | `[구문]` 파서가 무시한다. `meta.source`(선택 필드)는 v0.1에서 미기입 |
| `BlankLine` | — | `[구문]` 파서가 무시한다 |
| `PascalName` | — | `[필드흡수]` 선언 노드의 `name` 값, `EventSource`에서는 참조 대상(`source.ref`)의 지시자 |
| `CamelName` | — | `[필드흡수]` FieldLine의 `name`, Comparison의 좌변, `encrypt <field>`의 필드명 |
| `CapabilityName` | — | `[필드흡수]` Capability의 `name`, DatabaseLine의 참조 대상 |
| `Word` | — | `[필드흡수]` step·구·`role <r>`의 토큰 — 문자열 값의 성분 |
| `Version` | — | `[필드흡수]` Capability의 `version`(문자열) |
| `TypeName` | — | `[필드흡수]` `fields[].type` 문자열 — base 이름 또는 Refinement 이름을 담는다. 노드 id가 아니라 **이름**이며 해소 순서는 RFC-0066 부록 A.6.1 |
| `BaseTypeName` | — | `[필드흡수]` `Refinement.base`(18종 닫힌 열거), 그리고 `TypeName`으로 쓰일 때는 `fields[].type` |
| `RefinedTypeName` | — | `[필드흡수]` `fields[].type` — 선언된 refinement 또는 내장 preset의 이름. 해소되지 않는 이름은 문법 오류가 아니라 이름 해소 오류다(A.6.1) |
| `Regex` | — | `[필드흡수]` `facets.pattern` 문자열. 공백·탭·`#` 불가(본문 §Full grammar 주) |
| `Number` | — | `[필드흡수]` `facets.min`·`facets.max`의 값, `EnumValue`의 수치 분기 |
| `EnumValue` | — | `[필드흡수]` `facets.enum` 배열의 항목(문자열 또는 수치) |
| `Integer` | — | `[필드흡수]` Policy `retry`의 value(수치), PhraseToken의 성분. RepeatGuard 문맥은 A.4-① |
| `Duration` | — | `[필드흡수]` Policy `timeout`의 value 문자열(`"3s"`), Performance value의 성분 |
| `DurationUnit` | — | `[구문]` Duration 리터럴의 단위 성분(`ms`·`s`·`m`) |
| `Comparator` | — | `[필드흡수]` Performance value 문자열의 접두(`"<50ms"`), Comparison의 성분 |
| `Comparison` | — | `[필드흡수]` PerformanceLine `response` 예산의 값 문자열. Condition 문맥은 A.4-① |
| `EOL` | — | `[구문]` 논리 라인의 종결자 |

집계: 노드를 만드는 규칙 13개(EntityDecl · ServiceDecl · WorkflowDecl ·
EventDecl · CapabilityDecl · RefineDecl · GoalLine · PolicyClause ·
SecurityClause · PerformanceClause · ParallelBlock · PipelineBlock · StepLine)
+ `—` 45개 = 58.

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
`wf.login.step.6`이 **순서까지 1:1**로 대응한다(RFC-0066 구조 규칙 3 — children
순서 = 실행 순서).

역방향(소스에 대응 줄이 없는 IR 노드) 3개 — 문법 → IR이 **부분사상**임을 보이는
지점이다:

- `wf.login.step.1.check`(Validation, `target=entity.user`, `rule=semantic-types`)
- `wf.login.step.2.repo`(RepositoryCall, `entity=entity.user`, `operation=read`)
- `wf.login.step.3.cache`(CacheAccess, `key="user:{id}"`, `operation=set`)

이 3종은 v0.1 문법에 표면 표기가 없어 소스에서 도출되지 않는다(A.4-③).
집계: 골든 IR 19노드 = 소스 라인 대응 16 + 소스 무대응 파생 3.

**A.4 미해소 lowering 공백.** 아래 8항은 이 부록이 해소하지 못한 항목이며 각각
해소 소유자를 명시한다. 공백을 감추지 않는 것이 이 표의 검증 가치다(plan.md D6).

| # | 공백 | 해소 소유자 |
|---|------|-------------|
| ① | ~~`when`·`repeat`·`until` 가드와 `Condition`에 대응하는 IR kind가 없다~~ → **해소(2026-07-31)**: 3개 kind가 아니라 **`Guard` 하나**를 신설했다(RFC-0001 노드 카탈로그 20번째 kind). 필드는 `mode`(`when`\|`until`\|`repeat` 닫힌 enum) + `condition`(when·until) 또는 `count`(repeat) + `children`(피가드 항목 1개). 실행 의미는 RFC-0068 §Guard: `when`=조건 1회 평가 후 거짓이면 건너뜀, `repeat`=count회 반복, `until`=조건 성립까지 반복(데드라인·라운드 상한으로 유계). 조건식 문법 자체는 여전히 Open Questions ②가 소유하며, 참조 구현은 `<필드> missing\|exists`만 평가하고 그 밖은 **거부한다**(추측 금지) | 해소됨 — 조건식 확장은 OQ② |
| ② | ~~`spec`·`given`·`when`·`expect`·`PhraseLine`에 대응 kind가 없다~~ → **해소(2026-07-31)**: 의도대로 IR 노드를 만들지 않고 **테스트 스위트 아티팩트**로 산출한다(D20 ④). 산출물은 생성된 코드가 아니라 **선언적 매니페스트**(`.spec.json`)이며 별도 러너가 인터프리터에 대해 실행한다 — 코드 생성을 끼우면 선언과 실행 사이에 합성 단계가 들어가고, 그것은 이 플랫폼이 기각한 노선이다(§Prior Art). 기대 어휘는 동사 사전처럼 **닫힌 집합**이고, 평가할 수 없는 기대는 조용히 통과하지 않고 실패한다. 참조 구현 `impl/lnpl/spec.py`, 골든 매니페스트 `examples/login.spec.json` | 해소됨 |
| ③ | ~~골든 IR의 `Validation`·`RepositoryCall`·`CacheAccess`에 대응하는 표면 표기가 없다~~ → **해소(R1, 2026-07-31)**: 표면 표기를 신설하지 않고 **닫힌 동사 사전**으로 결정적 도출한다. StepLine의 첫 토큰은 문법이 Verb로 강제하므로 도출은 추론이 아니라 조회다 — `validate`→Validation, `authenticate`/`load`/`find`/`read`→RepositoryCall(read), `create`/`insert`→RepositoryCall(create), `update`→(update), `delete`→(delete), `cache`→CacheAccess(set), `invalidate`→(invalidate), `call`/`request`→NetworkCall, `authorize`→Authorization. **사전에 없는 동사는 Effect를 도출하지 않는다**(침묵하되 추측하지 않는다). 필드값은 선언 스코프에서 해소한다: 목적어가 필드명이면 그 필드를 target으로, `input`(또는 목적어 없음)이면 엔티티 전체를 target·rule=`semantic-types`로. 참조 구현: `impl/lnpl/lower.py` `VERB_LEXICON` | 해소됨 — 사전 확장은 이 RFC 개정 사항 |
| ④ | ~~`PipelineBlock`은 이름 토큰을 갖지 않는데 IR `Pipeline`은 `name`이 필수다~~ → **해소(2026-07-31)**: 문법이 **선택적 이름**을 받는다(`pipeline Enrich`). 이름이 없으면 lowering이 `pipeline.<n>`으로 파생하므로 RFC-0066의 `name` 필수 제약은 그대로 유지된다(스키마 무변경) | 해소됨 |
| ⑤ | ~~값이 없는 Performance metric 3종(`parallel`·`prefetch`·`batch`)은 `budgets[]`가 `value`를 필수로 요구해 직렬화가 불가능하다~~ → **해소(2026-07-31)**: 플래그에 값을 요구한 것이 스키마 결함이었다. `budgets[].value`를 **선택**으로 바꿨다 — `Policy.rules[].value`가 이미 같은 이유로 선택이었다(`rollback`은 값이 없다). 값을 주면 오히려 오류다 | 해소됨 |
| ⑥ | ~~workflow 본문 직속의 `ParallelBlock`·`PipelineBlock`이 만든 Concurrency·Pipeline 노드를 `Workflow.children`(WorkflowStep만 허용)에 부착할 수 없다~~ → **해소(2026-07-31)**: RFC-0001을 개정해 `Workflow.children`이 WorkflowStep·Guard·Concurrency·Pipeline을 허용한다. 문법이 본문에 가드·블록을 직접 허용하므로 IR 쪽이 그 사실을 담는 것이 맞다(IR 정본 원칙은 *충돌 시 IR 정의를 따른다*는 것이지, IR을 고치지 않는다는 뜻이 아니다) | 해소됨 |
| ⑦ | ~~노드 `id`의 도출 규칙이 없다~~ → **해소(R2, 2026-07-31)**: 균일 규칙 하나. `id = <kind 접두>.<이름을 PascalCase 경계로 분해·소문자화·`.`으로 연결>`이며, **kind 자신의 낱말을 중복하는 후행 세그먼트는 제거**한다(세그먼트가 2개 이상일 때만). 그래서 Service인 `LoginService`는 `svc.login`이 되고, Event인 `UserCreated`는 `created`가 `event`와 다르므로 `event.user.created`가 된다. kind 접두: entity/svc/wf/event/cap/policy/security/perf. step은 `<workflow id>.step.<1기반 순번>`, 파생 Effect는 `<step id>.<kind 슬러그>`(Validation→check, RepositoryCall→repo, CacheAccess→cache, NetworkCall→net, Transaction→tx, Authorization→authz, EventEmit→emit, BusinessRule→rule), Constraint는 `<접두>.<소유 Service 세그먼트>`. 이 규칙은 골든 19노드의 id와 순서를 전량 재현한다(참조 구현 `impl/lnpl/lower.py` `derive_id`, 회귀 `impl/tests/test_golden.py`) | 해소됨 |
| ⑧ | ~~R3은 Service 1개 모듈로만 실증된 잠정 규칙이다~~ → **해소(2026-07-31)**: 규칙으로 확정했다. 서비스는 **자기 `database` 절이 지명한 capability**를 `requires`로 가진다. `database` 절이 없으면 — 모듈에 서비스가 **1개일 때만** 모듈 전체 capability를 귀속하고, **2개 이상이면 컴파일 오류**다(추측하지 않는다). 골든은 서비스 1개이므로 기존 결과가 유지된다 | 해소됨 |

**A.5 Open Questions ⑤(goal 절의 lowering 대상) 해소.** `GoalLine`은
**BusinessRule** 노드로 lowering된다(라인 1개 = 노드 1개, `name` = `statement` =
동사구 원문). 근거: RFC-0066 Service의 children 허용 종별이 {Workflow, Pipeline,
BusinessRule}이므로 goal 라인을 WorkflowStep으로 Service에 직속시킬 수 없고,
"goal 절에서 Workflow를 자동 합성"하는 대안은 소스에 없는 실행 순서를 발명하므로
IR 정본 원칙(plan.md D1)에 반한다. goal 절은 실행 순서가 아니라 달성해야 할
규칙의 서술이므로 BusinessRule의 `name` + `statement` 계약과 정합한다.
`expression`(형식 표현)은 표기가 미정이므로 v0.1에서 비운다(Open Questions ②③).

> **2026-07-31 구현.** 이 매핑은 참조 구현에 반영됐다(`impl/lnpl/lower.py`).
> 그 전까지 `goal` 절은 파서를 통과한 뒤 lowering에서 조용히 사라졌다 — 명세가
> 규정한 매핑을 구현이 갖고 있지 않은 상태였고, 선언이 아무 일도 하지 않는 것은
> 명세와 구현이 어긋나는 방식 중 가장 나쁜 쪽이다. 회귀는
> `impl/tests/test_lower.py::TestStructure::test_a_goal_clause_becomes_business_rules_owned_by_the_service`가 잡는다.

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
2. **가드 조건식의 표현력 — 해소됨(RFC-0008).** `Condition`은
   `Presence | Comparison`이다(RFC-0008 §Full grammar). 평가기가 없던
   `Word Word? Word? Word?` 대안은 제거됐고, 파서가 파스 시점에 거부한다.
   남은 확장 여지는 두 갈래로 갈린다:
   - **부정·논리 결합(and/or)** — RFC-0069 §Open Questions 3(논리 결합의
     표현력)이 이어받는다. 이 항목에서는 다루지 않는다.
   - **멤버십 검사** — 어느 RFC도 추적하지 않으므로 **이 항목에 남긴다.**
     필요해지면 문법 확장이 필요하다.
3. ~~**refinement 타입의 표면 표기** — RFC-0001은 사용자 정의 타입을 기존 18종
   base의 제약 강화(refinement)로만 허용하는데, 그 표면 문법(`field age
   Integer …범위…` 류)은 미정이다.~~ → **해소(2026-08-04)**: 제약을 `FieldLine`에
   인라인으로 붙이지 않고 **최상위 블록 선언 `refine`** 을 신설했다 —
   `refine Slug of Text` + facet 라인. `FieldLine ::= CamelName TypeName`은
   두 토큰 그대로 유지되고(인라인 제약 문법 없음), 필드는 refinement의 *이름*만
   참조한다. facet 어휘 6종(`pattern` `minLength` `maxLength` `min` `max` `enum`)
   과 base별 적용 가능성, 내장 preset 3종(`URL`·`Slug`·`PositiveInteger`)의 정확한
   제약값은 RFC-0066 부록 A.6이 소유하는 닫힌 열거다. IR 쪽은 `Refinement`
   노드(카탈로그 21번째 kind)로 직렬화된다 | 해소됨 — facet 어휘 확장은 RFC-0066 개정 사항
4. **Duration 단위 확장과 필드 optional 표기** — 단위는 실증 3종(`ms`/`s`/
   `m`)만 규정했다(`h`/`d` 등 확장 미정). `FieldLine`의 required 기본 true에
   대한 optional 표기도 미정이다.
5. **goal 절의 lowering 대상** — `goal` 절이 IR의 어느 노드(BusinessRule?
   Workflow 자동 합성?)로 lowering되는지는 후속 lowering 매핑 표(태스크 04)로
   넘긴다.

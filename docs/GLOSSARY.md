# GLOSSARY — LNPP 공통 용어집

Charter와 모든 RFC가 공유하는 용어의 정의 정본. 각 용어의 정의는 `CHARTER.md`의
해당 절과 `plans/rfc-suite/plan.md`의 Decisions(D#)에 근거한다. 표기 규칙은
RFC-0000 §4(한국어 본문 + 영어 식별자)를 따르며, 용어 헤딩은 영어 식별자를 쓴다.

## Intent

구현 방법(How)이 아니라 만들 목표(What)를 기술한 선언. LNPP에서 개발자가 작성하는
유일한 입력이며, 요구사항·비즈니스 규칙·목표 정의로 구성된다. Architecture 설계와
구현·검증·배포는 Compiler와 AI가 수행한다.

근거: CHARTER.md §핵심 철학 2 "Code가 아니라 Intent를 작성한다", §최종 목표.

## Semantic IR

AST를 대체하는 의미 중심 중간 표현(Intermediate Representation). 노드가 구문
(Assignment, IfStatement)이 아니라 의미(BusinessRule, Validation, NetworkCall,
Transaction 등)를 나타낸다. 플랫폼의 설계 허브 — 문법(LNPL)은 Semantic IR로
lowering되는 표면 표기이고, 컴파일러·런타임·에이전트는 모두 Semantic IR의
소비자로 정의된다.

근거: CHARTER.md §Semantic IR; plan.md D1(설계 허브), D15(노드 대분류).

## Semantic Type

String·Long 같은 원시 타입을 최소화하고 도메인 의미를 직접 담는 타입 체계.
초기셋은 UUID, Money, Email, Phone, Password, Address, Image, File, Currency,
GeoLocation, Json, Html, Markdown 13종(+원시 보조 Text, Integer, Decimal,
Boolean, DateTime). 각 타입은 validation rule을 내장해 검증·OpenAPI·프런트엔드
검증 코드의 자동 생성 원천이 된다.

근거: CHARTER.md §Semantic Type System; plan.md D16(초기셋 고정).

## Capability

패키지가 코드가 아니라 능력 단위로 설치되는 개념(예: `postgres`, `redis`, `jwt`,
`s3`, `kafka`). 개발자는 필요한 Capability를 선언만 하고, 그것을 충족하는 구현체는
Compiler가 자동 선택한다.

근거: CHARTER.md §Package Manager.

## Workflow

비즈니스 흐름을 순서가 고정된 단계열로 선언하는 단위. 골든 시나리오의
`workflow Login`은 `validate input → authenticate → cache user → generate token
→ audit login → return token` 6단계로 구성된다.

근거: CHARTER.md §Language Design(Workflow); plan.md §골든 시나리오 "Login".

## Policy

실행 정책을 코드가 아닌 제약으로 선언하는 블록. `retry 3`, `rollback`,
`timeout 3s`처럼 재시도·복구·시간 제한 등의 동작 방식을 지정하며, 적용 방법은
컴파일러·런타임이 결정한다.

근거: CHARTER.md §Language Design(Policy); plan.md §골든 시나리오 "Login".

## Knowledge Base (KB)

모든 AI Agent가 공유하는 지식 저장소. Architecture·Naming·Performance·Security·
Testing 등의 가이드와 Patterns/Anti Patterns로 구성되며, Charter는 이를
"Language보다 중요"한 가장 중요한 구성 요소로 규정한다. 문서 포맷과 로딩 구조는
RFC-0005가 정의한다.

근거: CHARTER.md §Knowledge Base; plan.md D9(문서 포맷·progressive disclosure).

## Agent Pipeline

Planner → Architect → Coder → Reviewer → Tester → Performance Analyzer →
Security Auditor → Refactoring Agent → Release Agent로 이어지는 AI 에이전트
체인. 모든 Agent는 동일한 KB를 사용하고 Semantic IR를 공유하며 협업한다.

근거: CHARTER.md §AI Pipeline.

## Lowering

상위 표현을 의미를 보존하며 더 낮은 수준의 표현으로 변환하는 것. LNPP에서는
두 층위로 쓰인다: ① 문법(LNPL 소스) → Semantic IR (표면 표기의 lowering),
② Semantic IR → 컴파일러 dialect → LLVM → Native (컴파일 경로의 progressive
lowering).

근거: plan.md D1(문법은 IR로 lowering되는 표면 표기), D18(MLIR progressive
lowering); CHARTER.md §Native Compiler의 변환 파이프라인.

## LNPL

LNPP 플랫폼의 표면 언어에 대한 워킹네임(working name). 소스 파일 확장자는
`.lnpl`. 추후 개명 가능성이 있으므로 각 RFC는 언어명 첫 언급 시 워킹네임임을
명시한다(RFC-0000 §4).

근거: plan.md D3(워킹네임·확장자·개명 가능).

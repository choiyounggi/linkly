# linkly

[English](README.md) | **한국어**

**LLM 네이티브 프로그래밍 플랫폼**: 언어 · Semantic IR · 네이티브 컴파일러 · 런타임 ·
공유 Knowledge Base · 에이전트 프로토콜을 하나의 시스템으로 설계한다.

기존 언어는 **사람이 쓰기 쉽도록** 설계됐다. 앞으로 대부분의 코드는 LLM이 생성한다.
그렇다면 언어는 타이핑하는 사람이 아니라 **LLM이 이해하고 추론하고 최적화하기 쉽도록**
설계돼야 한다.

linkly는 새 언어 하나가 아니다. 그 전제가 요구하는 플랫폼 전체다:

```
개발자 → Intent(무엇을) → LLM → Semantic IR → Native Optimizer → Machine Code
```

개발자는 구현을 쓰지 않는다. 목표와 비즈니스 규칙(*무엇을*)만 선언하고, 컴파일러와 AI
에이전트 파이프라인이 나머지(*어떻게*)를 설계·구현·검증·최적화·배포한다.

> **상태: 설계 단계.** RFC 7편, 전부 `Draft`. 구현은 아직 없다 —
> [로드맵](docs/ROADMAP.md) 참조. RFC 본문은 한국어이고, 식별자·키워드·스키마 필드명은
> 영어다.

---

## 두 개의 설계 축

### 1. 코드가 아니라 Intent를 쓴다

표면 언어 **LNPL**(워킹네임, `.lnpl`)은 선언만 담는다:

```
entity User
    field
        id UUID
        email Email
        password Password
        createdAt DateTime

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

`if` / `for` / `while` / `switch`는 없다 — 예약어로 두고 사용을 금지한다. 제어 어휘는
`when` / `repeat` / `parallel` / `until` / `pipeline`이다. 블록은 **키워드**가 구획하고
들여쓰기는 **의미를 갖지 않는다**(4칸은 표기 관례일 뿐). 그래서 중괄호 짝 오류도
들여쓰기 오류도 문법적으로 표현될 수 없다.

### 2. Semantic IR이 허브다

AST를 버린다. 의미가 1급이다: `BusinessRule` · `Validation` · `NetworkCall` ·
`RepositoryCall` · `CacheAccess` · `Transaction` · `Authorization` · `EventEmit` ·
`Policy` · `Security` · `Performance` 등. 문법은 IR로 **lowering되는** 표면 표기일
뿐이고, 컴파일러 · 런타임 · 9종 AI 에이전트는 모두 IR의 **소비자**다.

IR은 중첩 트리가 아니라 **평탄한 노드 테이블 + id 참조**다. 이 구조가 constrained
decoding의 중첩 한계를 구조적으로 충족하고, 노드 단위 diff와 조각 교환을 싸게 만들고,
직렬화 순서를 안정적으로 유지해 KV-cache 프리픽스를 재사용할 수 있게 한다.

---

## RFC 스위트

| RFC | 내용 |
|-----|------|
| [0000 RFC Process](rfcs/0000-rfc-process.md) | 수명주기, 번호 체계, 고정 7섹션 템플릿 |
| [0001 Semantic IR](rfcs/0001-semantic-ir.md) | 노드 19종, Semantic Type 18종, 평탄 구조, canonical JSON 직렬화 |
| [0002 Syntax](rfcs/0002-syntax.md) | 라인 지향·키워드 구획 EBNF(51 생산규칙) + 문법→IR lowering 매핑 |
| [0003 Runtime](rfcs/0003-runtime.md) | actor, structured concurrency, 정책 집행, 메모리 프리미티브, 관측성 계약 |
| [0004 Compiler](rfcs/0004-compiler.md) | MLIR progressive lowering 7단계, 패스 불변조건, Optimizer 3종 책임 축 |
| [0005 Knowledge Base](rfcs/0005-knowledge-base.md) | 12 카테고리, 3단 progressive disclosure 라우팅, 소비 인터페이스 |
| [0006 Agent Protocol](rfcs/0006-agent-protocol.md) | 역할 9종, JSON-RPC 메서드 8종, 구조화 오류, 멱등, 태스크 수명주기 |

`Accepted` 승격에는 교차 정합성 전항 통과 **그리고** 소유자 승인이 필요하다(RFC-0000 §2).

---

## 각 결정의 근거

직관이 아니라 외부 근거 위에 세웠다. 전량은
[docs/RESEARCH-NOTES.md](docs/RESEARCH-NOTES.md).

| 결정 | 근거 |
|------|------|
| 들여쓰기를 **비유의미**로(오프사이드 룰 기각) | 공백·들여쓰기·개행이 코드 토큰의 ~24.5%인데 오프사이드 언어는 이를 제거할 수 없다 ([arXiv:2508.13666](https://arxiv.org/html/2508.13666)) |
| 중첩 축소, 최상위 선언 명시 | AI-native 언어 MoonBit — 중첩이 적을수록 KV-cache에 친화적 |
| IR canonical form = **RFC 8785 (JCS)** | canonical 규칙을 직접 발명하지 않는다 |
| IR 스키마 = constrained-decoding 호환 부분집합 | `oneOf` 금지, `default` 금지, 중첩 ≤5 — 에이전트가 IR 조각을 structured output으로 생성할 수 있어야 한다 |
| LLVM IR 직행 대신 **MLIR** 경유 | 고수준 시맨틱이 살아있는 동안 최적화하고 단계적으로 하강 |
| 프로토콜 = JSON-RPC 2.0, **A2A / MCP 정렬** | 에이전트↔에이전트는 A2A, 에이전트↔도구는 MCP와 같은 베이스 |
| KB = **3단 progressive disclosure** | Anthropic Agent Skills 패턴(메타데이터 → 본문 → 리소스) |
| MVP는 LLVM보다 **인터프리터 먼저** | WebAssembly 관례 — 참조 인터프리터는 실행 가능한 명세다 |

---

## 검증

명세가 산문만은 아니다. 골든 시나리오 "Login" 하나가 7개 문서를 관통하고(문법 → IR →
런타임 → 컴파일 패스 → KB → 에이전트 메시지), 그 양끝이 서로에 대해 기계 검증된다.

```bash
python3 -m pip install --user jsonschema

# 골든 IR이 스키마에 유효한가
python3 scripts/validate_ir.py examples/login.lir.json

# 검증기 자체가 실패할 수 있는가 (positive 1 + negative 3)
python3 scripts/validate_ir.py --self-test
```

`--self-test`는 골든 예제가 통과하는 것만 확인하지 않는다. 고의로 망친 3가지 — 필수 필드
삭제, 미정의 `kind` 주입, 미정의 추가 필드 주입 — 이 **모두 거부돼야** exit 0이다. 성공만
확인하는 검사는 검사가 아니다.

교차 정합성 판정(C1~C9, 각 항목에 음성 대조 포함)은
[docs/CONSISTENCY-CHECK.md](docs/CONSISTENCY-CHECK.md)에 있다.

---

## 알려진 공백 (숨기지 않는다)

설계 단계 스위트이므로 미해소 항목이 있다. 각각 **해소 소유자**와 인용 위치를 갖는다:

- **문법 → IR은 부분사상이다.** 골든 IR의 19노드 중 3노드(`Validation`,
  `RepositoryCall`, `CacheAccess`)에 대응하는 표면 표기가 없다 — 이 3종은 선언된
  의도로부터 컴파일러와 에이전트가 **도출**하는 노드다. 파싱만으로는 16노드까지다.
- **노드 `id` 도출 규칙이 없다.** 형식(dot-path 정규식)만 규정돼 있다.
- **heap 프리미티브의 런타임 계약이 없다.** RFC-0003은 arena와 pool 2종만 정의한다.
- **가드(`when` / `repeat` / `until`)에 대응하는 IR kind가 없어** lowering에서 소실된다.

전량은 RFC-0002 부록 A.4(8항)와 [로드맵](docs/ROADMAP.md)의 Phase 1 리스크 R1~R6에
색인돼 있다.

---

## 로드맵

| Phase | 내용 | 완료 기준 |
|-------|------|-----------|
| **1** | Rust 파서(`.lnpl` → `.lir.json`) + **IR 인터프리터**로 골든 시나리오 실행 | 골든 실행이 RFC-0003 타임라인과 일치, 테스트 스위트 신설 |
| **2** | LLVM 백엔드(모드 B) + 자동 생성물 1종(OpenAPI) | 두 실행 모드의 관측 가능 동작이 동등 |
| **3** | KB 12카테고리 시드 + 에이전트 2종 프로토콜 왕복 | RFC-0006 Examples 사이클 재현 |

---

## 선행 사례

같은 문제를 다루는 프로젝트들이 있다: [lhaig/intent](https://github.com/lhaig/intent)
(AI 생성 코드를 위한 계약 기반 언어),
[l3yx/intentlang](https://github.com/l3yx/intentlang)(Python에 임베드된 intent 언어),
[pboueri/intentc](https://github.com/pboueri/intentc). linkly는 네 가지가 다르다:
IR이 **구문이 아니라 의미**(`BusinessRule` / `Effect` 노드)이고, 하강 경로가
**MLIR → 네이티브**이고, Knowledge Base가 **1급 구성요소**이고, 프로토콜이
**A2A / MCP 정렬**이다.

---

## 구조

```
CHARTER.md                  0단계 비전 문서(원문 보존 — 정본 설계는 rfcs/)
rfcs/0000..0006             RFC 7편
schemas/lir.schema.json     IR JSON Schema (draft 2020-12)
examples/login.lnpl         골든 시나리오 소스
examples/login.lir.json     같은 시나리오의 IR
scripts/validate_ir.py      스키마 검증 + 자기검사
docs/GLOSSARY.md            용어 정본
docs/RESEARCH-NOTES.md      설계 결정의 외부 근거
docs/CONSISTENCY-CHECK.md   교차 정합성 판정(C1~C9)
docs/ROADMAP.md             3 Phase + 리스크
plans/rfc-suite/            이 스위트를 만든 계획(결정 20건, 태스크 10개)
```

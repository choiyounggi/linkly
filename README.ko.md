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

> **상태: RFC 7편 전부 `Accepted`(2026-07-31). 로드맵 3 Phase 전부 완료.**
> `.lnpl`이 파싱되고 Semantic IR로 lowering돼 IR 인터프리터에서 실행되며(모드 A),
> MLIR을 거쳐 **네이티브 바이너리**로 컴파일된다(모드 B). 차동 검증이 RFC-0004가
> 지명한 관측 가능 4종에 대해 두 모드의 일치를 확인한다. OpenAPI도 IR에서 생성된다.
> 골든 시나리오는 손으로 유지하는 파일이 아니라 컴파일러가 **생성**한다. 남은 것:
> 커스텀 `lnpl` MLIR dialect(C++ TableGen 빌드 필요) — [로드맵](docs/ROADMAP.md) 참조.
> RFC 본문은 한국어이고, 식별자·키워드·스키마 필드명은 영어다.

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

7편 전부 2026-07-31자로 `Accepted`다 — 교차 정합성 전항 통과와 소유자 승인이 모두
충족됐다(RFC-0000 §2). 이후 실질 변경은 편집이 아니라 **대체(Supersede)** 로 한다.
승격 근거는 [docs/CONSISTENCY-CHECK.md](docs/CONSISTENCY-CHECK.md)에 기록돼 있다.

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

## 실행해보기

```bash
# 프로젝트는 Python을 venv로 고정한다 — PATH의 `python3`가 무엇이든 검증이 같게 돈다.
python3 -m venv .venv && .venv/bin/pip install jsonschema
export PYTHONPATH=impl

# 의도 -> Semantic IR
.venv/bin/python -m lnpl compile examples/login.lnpl | head -20

# 모드 A — IR 인터프리터로 실행
.venv/bin/python -m lnpl run examples/login.lnpl

# `spec` 블록은 테스트 매니페스트가 되고, 러너가 실행한다
.venv/bin/python -m lnpl spec examples/login.lnpl --run

# IR에서 생성되는 OpenAPI 3.1 문서
.venv/bin/python -m lnpl openapi examples/login.lnpl | head -30

# Knowledge Base, 그리고 그것을 참조하는 에이전트 사이클
.venv/bin/python -m lnpl kb --lint
.venv/bin/python -m lnpl agents examples/login.lnpl
```

에이전트 사이클이 볼 만한 부분이다:

```
agent cycle over Login (6 step(s))
  validate input   kb=(none)                             (nothing proposed)
  authenticate     kb=patterns-repository-call           (nothing proposed)
  cache user       kb=cloud-redis-cache-provisioning     (nothing proposed)
  generate token   kb=security-jwt-issuance              proposal=prop-0001 -> completed applied=['wf.login.step.4', 'wf.login.step.4.authz']
  audit login      kb=(none)                             (nothing proposed)
  return token     kb=security-jwt-issuance              (nothing proposed)
IR nodes: 19 -> 20 | proposals applied: ['prop-0001']
```

6단계 중 4개가 **아무것도 제안하지 않는데**, 그게 설계가 동작하는 모습이다. Coder는
무엇을 낼지 자기 지식으로 정하지 않는다 — step을 KB로 라우팅하고, KB가 처방하는 것이
없으면 멈춘다. 유일하게 무언가를 얻은 step은 `ir.propose`(문서를 변경하지 않는다)와
Reviewer의 `agent.report` 승인을 거쳐야 노드가 문서에 닿고, 출처를 함께 남긴다:
`meta.source = "kb:security-jwt-issuance@0.1.0"`.

### 모드 B — 네이티브 바이너리

모드 B는 MLIR/LLVM 도구가 필요하다(`brew install llvm`, ~1.8GB, keg-only).

```bash
# IR -> MLIR -> LLVM IR -> 네이티브 바이너리, 그리고 실행
.venv/bin/python -m lnpl build examples/login.lnpl --run

# 그리고 정작 중요한 검사: 두 모드가 일치하는가?
.venv/bin/python -m lnpl diff examples/login.lnpl
```

```
PASS 1/4 execution order — 6 step(s): validate input -> authenticate -> cache user -> generate token -> audit login -> return token
PASS 2/4 policy outcome — status=completed
PASS 3/4 observability signals — 3 effect(s) per step match
PASS 4/4 masking — no secret marker in either mode's output
differential: EQUIVALENT
```

이 4종이 RFC-0004가 두 모드에게 요구하는 일치 항목의 전부다 — 그리고 RFC는 달라도
되는 것도 똑같이 명시한다: 스케줄러 구조, 메모리 배치, 명령 선택, op 개수, 실행 시간.
검사는 앞의 것만 비교하고 뒤의 것은 무시한다. 시간을 비교하는 검사는 계약이 허용하는
이유로 실패할 테고, 그건 검사가 없는 것보다 나쁘다.

```
workflow Login -> completed  (33ms, correlation_id=cid-0001)
  step validate input     6ms attempts=1 [Validation -]
  step authenticate       6ms attempts=1 [RepositoryCall found=True]
  step cache user         6ms attempts=1 [CacheAccess ttl_ms=300000]
  step generate token     5ms attempts=1
  step audit login        5ms attempts=1
  step return token       5ms attempts=1
  response SLO 50ms: met (measured, not enforced)
```

소스 어디에도 *어떻게* 검증하고 읽고 캐시할지는 없다. `retry 3`·`timeout 3s`·
`cache 5m` 선언이 실제 런타임 동작이 된다 — 저장소를 비운 채 실행하면(`--no-row`)
`attempts=4`(초기 1회 + `retry 3`), 상한 있는 지수 백오프, 그리고 초과했지만
**집행되지 않는** response SLO 보고를 볼 수 있다. RFC-0003이 규정한 그대로다.

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

```bash
# 구현 자체의 테스트 스위트
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl

# 그리고 뮤테이션 검사: 저 스위트가 실제로 실패할 수 있는가?
.venv/bin/python impl/tests/mutation_check.py
```

`mutation_check.py`는 명세 규칙을 하나씩 제거한다 — 18종: id 도출의 후행 세그먼트
제거, 동사 사전 항목, 재시도 상한, 가드 의미, Password 마스킹, 메트릭 라벨 allowlist,
캐시 TTL 필수, SLO 비집행, capability 귀속, 모드 B의 step 순서와 effect 호출, 차동
검증 자신의 툴체인 가드, OpenAPI가 빈 스키마를 내지 않는다는 규칙 — 그리고 각각에
대해 스위트가 빨간불이 되기를 요구한다. 지금까지 실제 결함 2건을 찾았다: ① 재시도가
시도 상한만으로 묶여 있고 RFC-0003이 요구하는 workflow 데드라인을 보지 않아, 상한을
잃은 런타임은 실패하는 대신 무한히 돌았다 ② 모드 B 파이프라인이 `cf` dialect에서
하강을 멈춰 `when` 가드가 있는 프로그램이 컴파일되지 않았다.

교차 정합성 판정(C1~C9, 각 항목에 음성 대조 포함)은
[docs/CONSISTENCY-CHECK.md](docs/CONSISTENCY-CHECK.md)에 있다.

---

## 해소된 공백과 아직 열린 것

RFC-0002 부록 A.4가 설계 시점에 기록한 공백 8항이 전부 해소됐다:

| 공백 | 해소 |
|------|------|
| Effect 노드에 표면 표기가 없었다 | **닫힌 동사 사전**으로 결정적 도출. 사전에 없는 동사는 아무것도 만들지 않는다 |
| 노드 `id` 도출 규칙이 없었다 | 균일 규칙 하나(kind 접두 + PascalCase 분해 + kind 중복 세그먼트 제거)로 골든 id 전량 재현 |
| heap 프리미티브 계약이 없었다 | RFC-0003의 **`transfer`**: 선언된 이전 경계에서만 생성, 참조 카운트, GC 스캔 없음 |
| 가드에 IR kind가 없었다 | 3개가 아니라 **`Guard` 하나** + `mode`(`when`/`until`/`repeat`) |
| `spec`에 IR kind가 없었다 | 있어야 하는 게 아니었다 — `spec`은 **선언적 테스트 매니페스트**가 되고 러너가 실행한다 |
| 문법이 `Pipeline.name`을 주지 않았다 | 문법에 선택적 이름 + 없으면 lowering이 파생 |
| 값 없는 `performance` metric 직렬화 불가 | `budgets[].value`를 선택으로 — 플래그에는 값이 없다 |
| capability 귀속이 잠정이었다 | 규칙으로 확정: 서비스 자기 `database` 절, 또는 (단일 서비스 모듈) 전체, 또는 **컴파일 오류** — 추측은 없다 |

남은 미결은 각 RFC의 `## Open Questions`에 있고 이슈로 추적한다:

| 이슈 | 미뤄진 것 |
|------|-----------|
| [#1](https://github.com/choiyounggi/linkly/issues/1) | RFC-0004 S4 — 커스텀 `lnpl` MLIR dialect(C++ TableGen 빌드 필요) |
| [#2](https://github.com/choiyounggi/linkly/issues/2) | 에이전트 9종 중 6종, 그리고 자기 기준으로 반려할 수 있는 Reviewer |
| [#3](https://github.com/choiyounggi/linkly/issues/3) | 가드 조건식 문법(RFC-0002 OQ②) — 모드 B의 `until`도 여기에 막혀 있다 |

그것들은 *유보한 결정*이지 계약의 구멍이 아니다. 참조 구현은 결정할 수 없는 것을
추측하지 않고 거부한다: 미등록 동사, 평가 불가 조건, 귀속 불가 capability, 미지원
spec 기대 — 전부 그 질문을 소유한 RFC 조항을 인용하며 오류를 낸다.

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
impl/lnpl/                  Phase 1 참조 구현(렉서·파서·lowering·인터프리터)
impl/tests/                 단위 스위트 + mutation_check.py(스위트가 실패할 수 있음을 증명)
kb/                         시드된 Knowledge Base(12 카테고리, RFC-0005 레이아웃)
```

---

## 라이선스

MIT — [LICENSE](LICENSE) 참조.

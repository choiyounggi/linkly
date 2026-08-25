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

제안서가 아니라 동작하는 구현이다. `.lnpl`이 IR 인터프리터에서 실행되고 MLIR을 거쳐
네이티브 바이너리로 컴파일되며, 차동 검증이 두 모드를 같은 관측 가능 동작에 묶는다.
[상세 상태는 아래](#상태).

---

## 두 개의 설계 축

### 1. 코드가 아니라 Intent를 쓴다

표면 언어 **LNPL**(워킹네임, `.lnpl`)은 선언만 담는다:

```lnpl
entity User
    field
        id UUID
        email Email
        password Password
        createdAt DateTime

entity Session
    field
        id UUID
        issuedAt DateTime

service LoginService
    policy
        retry 3
        timeout 3s
    security
        jwt
    performance
        response < 50ms
        cache 5m

workflow Login
    validate user
    authenticate user
    cache user
    create session
```

위 네 스텝은 전부 실제 Effect를 만든다 — `Validation` · `RepositoryCall` ·
`CacheAccess` · `RepositoryCall` — 그리고 워크플로는 `completed`로 끝난다. 선언 중
둘은 실행을 **바꾸지 않으며**, 컴파일러가 그 사실을 진단으로 말해준다: `security jwt`는
기본 경로에서 토큰을 발급하지도 검증하지도 않고(요청마다 bearer 토큰을 검증하는 것은
`lnpl serve --jwt-secret-env NAME`이다), `performance response`는 측정·보고만 하고
초과를 막지 않는다.

동사 어휘는 **닫혀 있다.** 그 밖의 낱말은 에러가 아니라, 아무 효과도 내지 않는 스텝으로
컴파일되고 문서 옆에 `unknown-verb` 진단이 붙는다. 어휘 정본은
[`plugins/lnpl/skills/lnpl-authoring/references/verbs.md`](plugins/lnpl/skills/lnpl-authoring/references/verbs.md)이며
컴파일러의 테이블에서 생성된다.

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

## 실행해보기

아래 명령이 돌리는 `examples/login.lnpl`은 이슈 #36의 회귀 픽스처다 — 어휘 밖 동사
셋(`generate` / `audit` / `return`)을 **일부러** 담고 있어서, 효과 없는 스텝이 어떻게
보이는지와 `unknown-verb` 진단이 그것을 뭐라고 말하는지를 출력으로 보여준다. 따라 쓸
모범이 아니라 재현 케이스다. 깨끗한 쪽은 `examples/checkout.lnpl`이다.

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

모드 B는 MLIR/LLVM 도구가 필요하다(`brew install llvm`, ~1.8GB, keg-only). 전제조건은
그것뿐이다 — 커스텀 `lnpl` dialect는 `mlir/lnpl.irdl.mlir`에 선언적으로 정의돼 표준
`mlir-opt`가 `--irdl-file`로 읽으므로, C++ 컴파일러·cmake·TableGen 빌드가 필요없다.

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

---

## 상태

로드맵 3 Phase 전부 완료.

- **모드 A** — `.lnpl`이 파싱되고 Semantic IR로 lowering돼 IR 인터프리터에서 실행된다.
- **모드 B** — 같은 소스가 MLIR을 거쳐 네이티브 바이너리로 컴파일된다. 커스텀 `lnpl`
  dialect는 IRDL로 선언하고 스톡 `mlir-opt`에 얹으므로 C++ TableGen 빌드가 없다
  (RFC-0004 S4).
- **차동 검증** — RFC-0004가 지명한 관측 가능 4종(실행 순서·정책 결과·관측 신호·마스킹)
  에 대해 두 모드를 묶는다.
- 가드 조건식(`when` / `until`)이 두 모드 모두에서 런타임에 평가된다. RFC-0008 G8이
  argv 파라미터 전달로 페이로드에서 조건 필드를 뽑는다.
- OpenAPI가 IR에서 생성되고, 골든 시나리오도 마찬가지다 — 손으로 유지하는 파일이 아니라
  컴파일된다. 에이전트 9역할도 전부 구현됐다.

**테스트 2588개 전부 통과**, 그리고 그 스위트가 실제로 실패할 수 있음을 증명하는
77종 뮤테이션 하네스. 둘 다 [검증](#검증)의 명령으로 재현한다.

**RFC 33편 — 32편 `Accepted`, RFC-0000은 RFC-0007로 `Superseded`.** RFC-0007은
2026-08-03에 정식 Accepted가 됐고, 효력은 RFC-0000이 대체된 2026-07-31부터였다
([이슈 #11](https://github.com/choiyounggi/linkly/issues/11)).
[로드맵](docs/ROADMAP.md) 참조.

RFC 본문은 한국어이고, 식별자·키워드·스키마 필드명은 영어다. 중심 문서인
[RFC-0001 Semantic IR](docs/rfc-0001-semantic-ir.en.md)에는 영어 요약이 있다 —
나머지 스위트가 그것을 기준으로 정의된다.

---

## RFC 스위트

| RFC | 내용 |
|-----|------|
| [0000 RFC Process](rfcs/0000-rfc-process.md) | *0007로 대체됨* — 수명주기, 번호 체계, 고정 7섹션 템플릿 |
| [0007 RFC Process v2](rfcs/0007-rfc-process-v2.md) | `Updates` 관계 신설 — RFC를 대체하지 않고 지목한 **절**만 갱신 |
| [0001 Semantic IR](rfcs/0001-semantic-ir.md) — [영어 요약](docs/rfc-0001-semantic-ir.en.md) | 노드 21종, Semantic Type 18종, 평탄 구조, canonical JSON 직렬화 |
| [0002 Syntax](rfcs/0002-syntax.md) | 라인 지향·키워드 구획 EBNF(58 생산규칙) + 문법→IR lowering 매핑 |
| [0003 Runtime](rfcs/0003-runtime.md) | actor, structured concurrency, 정책 집행, 메모리 프리미티브, 관측성 계약 |
| [0004 Compiler](rfcs/0004-compiler.md) | MLIR progressive lowering 7단계, 패스 불변조건, Optimizer 3종 책임 축 |
| [0005 Knowledge Base](rfcs/0005-knowledge-base.md) | 12 카테고리, 3단 progressive disclosure 라우팅, 소비 인터페이스 |
| [0006 Agent Protocol](rfcs/0006-agent-protocol.md) | 역할 9종, JSON-RPC 메서드 8종, 구조화 오류, 멱등, 태스크 수명주기 |
| [0008 Guard Conditions](rfcs/0008-guard-conditions.md) | 가드 조건식: 존재 검사·비교식 2형태, 명세 정정, 모드 B 컴파일. *0002 §Full grammar·0003 §Guard 갱신* |
| [0009 Guard Condition OQ](rfcs/0009-guard-condition-open-question.md) | 문법이 확정됐으므로 RFC-0002 미결 ②를 해소. *0002 §Open Questions 갱신* |
| [0010 Proposal Intent](rfcs/0010-proposal-intent.md) | 역할이 저작 권한 없는 노드에 자기 노드를 부착하는 법, 그리고 참조가 이동할 때의 의미론. *0006 §Agent Roles & IR Access·§Methods/ir.propose 갱신* |
| [0011 Refinement enum 정합과 이름 충돌](rfcs/0011-refinement-enum-and-name-collisions.md) | 어떤 refinement 이름이 적법한가, 그리고 선언 둘이 한 이름을 주장할 때 무엇이 이기는가. *0001 §부록 A.6.3·§부록 A.7 갱신* |
| [0012 실행 스코프와 스텝 결과 바인딩](rfcs/0012-execution-scope.md) | 가드 조건식이 무엇을 가리킬 수 있는가, 그리고 한 step의 결과가 다음 step에 어떻게 묶이는가. *0002 §Full grammar·0008 §Reference-level Specification/1. Full Grammar·0003 §Guard 갱신* |
| [0013 Step Attempt Ceiling](rfcs/0013-step-attempt-ceiling.md) | 선언된 `retry` 예산을 읽지 않는 절대 시도 상한 — 그 예산을 잃어도 무한 루프가 아니라 실패로 끝나게 한다. *0003 §Policy Enforcement 갱신* |
| [0014 가드 스킵의 관측 가능성](rfcs/0014-guard-skip-observability.md) | 스킵된 스텝이 더 이상 완주한 스텝으로 위장되지 않는다 — 스킵이 INFO 한 줄이 아니라 기록되는 계약 신호가 된다. *0008 §Guard Runtime Semantics 갱신* |
| [0015 값 의미론](rfcs/0015-value-semantics.md) | 가드가 무엇을 비교할 수 있고 `set`이 무엇을 쓸 수 있는가 — 필드 참조, 이항 산술 1개, `and` 결합, `input.` 페이로드 네임스페이스. 집계(`sum`/`count`)는 행 집합 표현이 먼저라 로드맵이 §Alternatives에 있다. *0001 §A.4·0002 §Full grammar·0008 §1 갱신* |
| [0016 시간 값 의미론과 스케줄 트리거](rfcs/0016-time-and-schedule-semantics.md) | DateTime을 epoch-ms 코덱으로 두어 기간이 i64가 되고 두 모드가 같게 비교한다. `event … on schedule daily at HH:MM UTC`는 IR과 OpenAPI까지 도달하고 집행되지 않는다. *0001 §A.4·0002 §Full grammar·0008 §1 갱신* |
| [0017 guarded.lnpl 예제 정정](rfcs/0017-guarded-example-correction.md) | 가드가 빨개진 예제를 예외로 빼지 않고 다시 쓴 이유. *0008 §5.2 갱신* |
| [0018 반복 스텝 관측의 fold 규칙](rfcs/0018-repeated-step-observation-fold.md) | 두 번 이상 도는 스텝이 하나의 관측으로 접히는 방식 — 그래야 모드 간 비교를 이름으로 할 수 있다. *0017 §Open Questions 1 갱신* |
| [0019 구조와 모순되는 들여쓰기의 거부](rfcs/0019-misleading-indentation.md) | 들여쓰기는 의미가 없지만, 블록 구조와 모순되는 들여쓰기는 거부한다 — 스코프에 대한 조용한 거짓말이 관례 부재보다 나쁘다. *0002 §Block structure 갱신* |
| [0020 spec `given`의 입력 네임스페이스](rfcs/0020-spec-given-input-namespace.md) | `spec` 케이스가 실행 payload의 필드를 지목하는 법 — 그래야 `input.` 가드를 계약할 수 있다. |
| [0021 진단 등급과 `--strict` 문턱](rfcs/0021-diagnostic-severity-levels.md) | 등급 사다리와 `--strict[=LEVEL]`가 게이팅하는 것. `warning`은 프로그램을 고치면 사라지는 것, `info`는 플랫폼이 자기가 하는 일을 진술한 것. |
| [0022 mode B의 관측 표면](rfcs/0022-mode-b-observation-surface.md) | 네이티브 빌드가 스킵된 스텝과 `--field` 도달을 무엇으로 말해야 하는가 — "돌았다"와 "건너뛰었다"가 구별되도록. *0014 §2.5·§2.6·0021 §코드 갱신* |
| [0023 가드 밖으로 새어 나간 상태 변경](rfcs/0023-guard-scope-diagnostic.md) | 가드는 다음 항목 하나만 소유하므로 뒤의 스텝이 가드가 지키려던 상태를 바꿀 수 있다. `guard-orphaned-steps`가 그것을 컴파일 타임에 말한다 — 형태가 아니라 결과로 판정한다. *0021 §코드 갱신* |
| [0024 집행 진단에 소스 line 병기](rfcs/0024-enforcement-diagnostic-line.md) | 집행 진단(`declared-not-enforced`/`declared-measured-only`/`authorization-not-verified`)이 노드 id에 더해 `(line N)`을 갖는다 — 한 절의 선언 둘이 같은 노드 id를 공유해도 더는 위치로 구별 불가능하지 않다. *0023 §5 갱신* |
| [0025 행 집합(Row Set)과 집계](rfcs/0025-row-sets-and-aggregation.md) | `list`가 엔티티의 전 행을 RowSet — 단일 행 바인딩과 별개의 이름공간 — 으로 읽고, `set`의 `sum`/`count`가 그것을 집계한다. mode B는 집계 값을 계산하지 않지만 `lnpl diff`는 관측 4클래스의 합의를 그대로 증명한다. *0012 §G12.2·0015 §1 갱신* |
| [0026 unknown-verb의 line과 suggestion](rfcs/0026-unknown-verb-line-and-suggestion.md) | `unknown-verb`/`guard-orphaned-steps`/`guard-skipped-steps`가 구조화 `line`을 갖고, 어휘 밖 동사는 2단 did-you-mean을 받는다 — 의미 동의어는 수제 별칭 테이블(`persist` → `create`), 철자 오타는 difflib. *0024 §Scope 갱신* |
| [0027 네트워크 드라이버와 결과 바인딩](rfcs/0027-network-driver-and-result-binding.md) | `call`/`request`가 `NetworkDriver`(`--network fake\|http`) 뒤의 실제 아웃바운드 호출이 되고, `as <이름>`이 응답을 바인딩해 가드가 `status`로 분기한다 — 바인딩된 호출의 접속 실패는 예외가 아니라 값(`status` 0)이다. *0003 §Execution Model·0012 §G12.2·0014 갱신* |
| [0028 산술 연산자 확장과 대안 가드](rfcs/0028-arithmetic-and-alternative-guards.md) | `*`/`/`가 `+`/`-`에 합류한다(정수, 절삭 나눗셈 — 0 나눗셈은 리터럴 0이 아닌 한 컴파일 에러가 아니라 `RunError`다), `when A` / `or B`는 가드 두 줄을 대안 가드로 승격한다 — `Condition` 문법의 연산자가 아니라 구조다. *0001 §노드 카탈로그/Guard·0014 §2·0015 §1 §4 갱신* |
| [0029 Clock 계약과 `--clock real` 바인딩](rfcs/0029-clock-contract-and-real-binding.md) | `timeout`/`retry`/`CacheAccess`가 이미 공유하던 시간 소스를 Clock 계약으로 이름 붙이고, 두 번째 바인딩을 더한다 — `--clock real`은 `CacheAccess` TTL을 실제 벽시계 경과에 묶는다. 기본 virtual 바인딩과, `--clock`을 아예 받지 않는 `diff`/`spec`은 바뀌지 않는다. *0003 §Execution Model 갱신* |
| [0030 `create` 결과 바인딩과 payload 시드](rfcs/0030-create-result-binding-and-payload-seed.md) | `create <명사> as <이름>`이 RFC-0027의 결과 바인딩 표기를 확장해 생성 행에 `set`/`format`/`respond`를 쓸 수 있게 한다. 별개로, `as` 유무와 무관하게 생성 행이 payload의 동명 비-`derived` 필드로 시드된다 — "뼈대 행" 갭의 해소. `as` 없는 `create`는 컴파일 표면에서 이전과 바이트 동일하다(`result` 필드도, 새 스코프 편입도 없다). *0012 §G12.2·§G12.5 갱신* |
| [0031 다중 파일 컴파일 단위](rfcs/0031-multi-file-compilation-unit.md) | 컴파일 단위가 파일 집합으로 확장된다 — `lnpl <cmd> <src...>`는 명시한 파일들을 인자 순서로 병합하고, `lnpl <cmd> <dir>`은 그 디렉터리의 `*.lnpl`을 파일명 정렬로 수집한다. 선언 이름은 전역 유일 — 서로 다른 파일에서 이름이 겹치면 거부하며 두 `<파일>:<줄>` 위치를 함께 병기한다. 문법·lexer는 불변이고, 소스 인자 1개는 바이트 동일하다. *0004 §Reference-level Specification(파이프라인 표 S1 행) 갱신* |
| [0032 트랜잭션 경계와 rollback 집행](rfcs/0032-transaction-boundary-and-rollback-enforcement.md) | 워크플로 실행이 암묵적 트랜잭션 하나가 된다(명시적 `Transaction` IR 노드는 아직 없다) — 성공 시 commit, 실패 시 rollback(실패한 실행이 등록한 이벤트 emission 포함). `policy rollback`은 `unenforced`에서 `enforced`로 승격된다. *0003 §Execution Model·§Policy Enforcement·§Examples 갱신* |

32편이 `Accepted`이고 0000은 0007로 대체됐으며 그 0007은 2026-08-03에 정식
Accepted가 됐다(이슈 #11). 교차 정합성 검사는 전항 통과했고 소유자도 승인했다.
이후 실질 변경은 **어떤 경우에도 본문 편집이 아니다**. 바꾸는 방법은 두 가지이고
범위에 비례한다(RFC-0007 §2.2): **Supersedes**는 RFC를 통째로 대체하고 종결시키며,
**Updates**는 지목한 **절**만 갱신하고 대상은 `Accepted`를 유지한다. 두 번째 관계를 둔
이유는, 전면 대체만 있으면 한 줄 개정에 전체 재서술이 필요해지고 — 그만큼 비싼 규율은
결국 사람이 어기는 규율이 되기 때문이다. 승격 근거는
[docs/CONSISTENCY-CHECK.md](docs/CONSISTENCY-CHECK.md)에 기록돼 있다.

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

```bash
# 구현 자체의 테스트 스위트
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl

# 그리고 뮤테이션 검사: 저 스위트가 실제로 실패할 수 있는가?
.venv/bin/python impl/tests/mutation_check.py
```

```
Ran 2588 tests in 88.227s
OK
```

모드 B 테스트에는 MLIR/LLVM 도구가 `PATH`에 있어야 한다([모드 B](#모드-b--네이티브-바이너리)
참조). 없으면 개수는 같지만 수십 건이 툴체인 부재로 에러가 난다. `bash scripts/dev_doctor.sh`는
환경이 갖춰졌으면 exit 0이고, 아니면 무엇이 빠졌는지 그대로 찍어준다.

`mutation_check.py`는 명세 규칙을 하나씩 제거한다 — 77종 — 그리고 각각에 대해 스위트가
빨간불이 되기를 요구한다. 맨 앞에는 **no-op 대조군**이 있다: 동작을 바꿀 수 없음이
자명한 변형이고, 이것은 반드시 *생존*해야 한다. 이 대조군은 형식이 아니다. 이전 버전의
하네스는 `impl/`만 뮤테이션 트리에 복사했는데 테스트는 `__file__`에서 레포를 찾으므로,
모든 변형이 규칙 실행 전에 파일 부재로 죽었다 — "전부 잡힘"을 보고하면서 아무것도
증명하지 않았고, 독립 감사가 그것을 적발했다. 대조군이 빨간불이면 하네스는 즉시 멈추고
다른 것은 측정되지 않았다고 보고한다.

스위트와 하네스, 그리고 두 차례의 적대적 감사가 모든 층에서 실제 결함을 찾았다:

- **런타임.** 재시도가 시도 상한만으로 묶여 workflow 데드라인을 보지 않은 것. 모드 B
  파이프라인이 `cf` dialect에서 하강을 멈춰 `when` 가드가 컴파일되지 않은 것.
- **어떤 테스트도 단정하지 않던 규칙 3건** — 비멱등 재시도·SLO 계측·at-least-once emit.
  앞의 둘은 깨진 하네스에 가려져 있었다. 세 번째는 더 나쁜 것에 가려져 있었다: 규칙을
  *이름으로 부르는* 테스트가 있었지만 픽스처를 아무것도 실패하지 않게 깔아서, 런타임이
  무슨 짓을 해도 `attempts == 1`이 참이었다. 테스트는 초록불이고 이름도 정확한데 아무것도
  단정하지 않을 수 있다.
- **Reviewer, 다섯 번.** 첫 소유 검사는 신규 노드만 봐서 편집으로 표현된 제거가 통과했다.
  이어서: 출처를 존재 여부만 보고 형식은 안 본 것, 형식은 맞지만 아무것도 가리키지 않는
  출처, 같은 제거를 `children` 대신 `constraints`로 통과시킨 것(리뷰 게이트와 적용
  게이트가 서로 다른 질문을 하고 있었다), 한 홉보다 긴 소유 순환, 기존 id에 kind만 바꿔
  끼우는 교체, 한 노드에 소유자 둘. 고칠 때마다 **인접한 변형**에 다시 뚫렸고, 이미 알려진
  실패 사례가 아니라 RFC-0001 구조 규칙(2·4·6)에서 검사를 다시 쓴 뒤에야 닫혔다.

일반화되는 교훈: 사례별로 쓴 게이트는 사례별로 뚫린다. 규칙에서 쓴 게이트가 계열을 닫는다.

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

RFC 승격 이후 명세↔구현 갭 3건을 더 닫았다. 셋 다 같은 모양이다 — 명세가 규정한 것을
구현이 하지 않고 있었다:

- **`goal` 절이 조용히 사라졌다.** RFC-0002 부록 A.2는 `GoalLine`을 `BusinessRule`
  노드로 매핑하는데 lowering이 절을 통째로 무시했다. 저자가 쓴 선언이 아무 일도 하지
  않은 것이다. 이제 각 goal 라인이 소속 service가 소유하는 `BusinessRule`이 된다.
- **모듈이 엔티티 1개로 제한돼 있었다.** 게다가 그 거부가 이미 다른 이유로 해소된
  항목을 인용했다. 이제 여러 개를 선언할 수 있다: step의 목적어가 엔티티를 지목하고
  (`load order`), 단일 엔티티 모듈은 목적어를 생략할 수 있고, 모호한 step은 선언 순서로
  고르지 않고 **후보를 열거하는 오류**를 낸다.
- **`emit`이 lowering을 거부했다.** 이제 목적어로 이벤트를 받고
  (`emit userCreated` → `event.user.created`), 인터프리터가 RFC-0003대로 유일한
  dedupe 가능 id와 마스킹된 페이로드로 발행을 등록한다.

남은 미결은 각 RFC의 `## Open Questions`에 있고 이슈로 추적한다:

| 이슈 | 미뤄진 것 |
|------|-----------|
| [#7](https://github.com/choiyounggi/linkly/issues/7) | RFC-0004 S5 — `lnpl` 모듈을 진짜 MLIR 패스로 하강하고, dialect에 region을 줘 동시성을 표현할 수 있게 |
| [#9](https://github.com/choiyounggi/linkly/issues/9) | 모드 B가 RFC-0003의 cache-TTL 계약을 강제하지 않는다 — 모드 A는 예산 없이 거부하는데 모드 B는 안 한다 |
| [#11](https://github.com/choiyounggi/linkly/issues/11) | RFC-0007이 `Status: Draft`인데 Accepted RFC 둘이 그 위에 서 있다 |
| [#12](https://github.com/choiyounggi/linkly/issues/12) | 모드 A는 Presence 가드 조건을 payload에서 읽고 모드 B는 별도 `skip` 플래그를 받는다 |

그것들은 *유보한 결정*이지 계약의 구멍이 아니다. 참조 구현은 결정할 수 없는 것을
추측하지 않고 거부한다: 미등록 동사, 평가 불가 조건, 귀속 불가 capability, 미지원
spec 기대 — 전부 그 질문을 소유한 RFC 조항을 인용하며 오류를 낸다.

전량은 RFC-0002 부록 A.4(8항)와 [로드맵](docs/ROADMAP.md)의 Phase 1 리스크 R1~R6에
색인돼 있다.

---

## 로드맵

| Phase | 내용 | 완료 기준 |
|-------|------|-----------|
| **1** | 파서(`.lnpl` → `.lir.json`) + **IR 인터프리터**로 골든 시나리오 실행 | 골든 실행이 RFC-0003 타임라인과 일치, 테스트 스위트 신설 |
| **2** | LLVM 백엔드(모드 B) + 자동 생성물 1종(OpenAPI) | 두 실행 모드의 관측 가능 동작이 동등 |
| **3** | KB 12카테고리 시드 + 에이전트 2종 프로토콜 왕복 | RFC-0006 Examples 사이클 재현 |

참조 구현 언어는 **Python**이다. 로드맵은 원래 Rust를 골랐는데 — 근거가 LLVM 바인딩과
단일 바이너리 배포였고 그건 Phase 2의 요구다. Phase 1 참조 인터프리터는 WebAssembly
관례대로 **명확성 우선의 실행 가능한 명세**에 가깝다. 이 변경은
[docs/ROADMAP.md](docs/ROADMAP.md) §0(결정 D10)에 기록돼 있다.

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
rfcs/0000~0032              RFC (0000은 Superseded, 나머지 29편은 Accepted)
schemas/lir.schema.json     IR JSON Schema (draft 2020-12)
examples/login.lnpl         골든 시나리오 소스
examples/login.lir.json     같은 시나리오의 IR
scripts/validate_ir.py      스키마 검증 + 자기검사
docs/rfc-0001-semantic-ir.en.md   RFC-0001 영어 요약 (RFC 본문은 한국어)
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

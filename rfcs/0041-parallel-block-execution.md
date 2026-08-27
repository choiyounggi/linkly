# RFC-0041: `parallel` 블록 실행 — mode A 구조적 동시성 집행

## Status

- Status: **Accepted** (RFC-0041, 2026-08-27)
- Updates: RFC-0003 §Reference-level Specification/Execution Model (Concurrency 문단 — 구체적 집행 메커니즘)
- Updates: RFC-0003 §Reference-level Specification/Policy Enforcement (`Policy.parallel N` 행 신설)

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목한다. `Execution Model`의
Concurrency 문단과 `Policy Enforcement`의 `Policy.parallel` 행은 RFC-0027
(NetworkCall 행)·RFC-0029(Clock 문단)·RFC-0032(Transaction·EventEmit 행,
`Policy.rollback` 행)가 건드리지 않은 대상이므로 이번이 그 둘의 첫 갱신이다
(규칙 5의 연쇄 갱신 대상 아님) — Concurrency 문단은 RFC-0003 원문에 이미
있었지만(구조적 동시성 계약 ①-④), 그 계약을 실제로 **집행**하는 구체적
메커니즘(상한값 출처, 쓰기충돌 거부, 데드라인 상호작용)은 이번이 처음
적는다. `Policy.parallel` 행은 표에 아예 없던 행이므로 신설이다.

## Motivation

`parallel` 블록은 문법·IR(`Concurrency` 노드, RFC-0001)·RFC-0003의 구조적
동시성 계약(①-④)까지 전부 이미 있었다. 없던 것은 **집행**뿐이었다 —
`interp.py`의 실행 루프(`_flatten_items`)가 `Concurrency` 노드를 만나면
자식들을 그저 선언 순서로 평탄화해 순차 실행했다. `parallel` … `merge`로
문서를 쓴 저자에게 런타임은 그 선언을 조용히 무시하고 있었다 — 정확히
`diagnostics.ENFORCEMENT[("policy","parallel")]`이 스스로
`unenforced`("parsed, but the execution plan never reads it")라고 신고하던
그 간극이다. 외부 서비스 3개를 부르는 워크플로는 반드시 순차로 불렸다 —
200ms 호출 3개가 600ms가 됐다.

이것은 issue #79/RFC-0032가 `policy rollback`에 대해 이미 닫은 것과 같은
모양의 간극이다: RFC-0003이 계약을 선언했지만 Phase 1 구현이 그 계약을
집행할 메커니즘을 아직 갖지 못한 상태. RFC-0032가 실행-스코프 트랜잭션
경계를 만들어 `rollback`을 `enforced`로 올렸듯, 이 RFC는 블록-스코프 실행기를
만들어 `parallel`을 `enforced`로 올린다.

표준 사례가 수렴하는 지점은 하나다 — **fail-fast + 구조적 스코프 + 동시성
상한**:

| 사례 | 실패 의미론 |
|---|---|
| [AWS Step Functions `Parallel` state](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html) | 한 브랜치가 실패하면 상태 전체가 실패하고, 진행 중인 다른 브랜치는 중단된다 |
| [Java 21 `StructuredTaskScope.ShutdownOnFailure`](https://docs.oracle.com/en/java/javase/21/core/structured-concurrency.html) | 하위 작업 하나가 실패하면 스코프 전체 취소, join 지점에서 예외 |
| [Go `errgroup.WithContext`](https://pkg.go.dev/golang.org/x/sync/errgroup) | 첫 에러가 ctx를 취소, `Wait()`가 그 에러 반환 |
| [Step Functions `Map` `maxConcurrency`](https://docs.aws.amazon.com/step-functions/latest/dg/sample-batch-fan-out.html) | 동시 실행 상한 — 무제한 팬아웃 금지 |

이 넷이 공유하는 계약은 RFC-0003 §Execution Model의 Concurrency 문단이 이미
①-④로 적어 둔 것과 같다. 이 RFC가 하는 일은 그 문단이 이미 약속한 것을
`interp.py` 위에 실제로 짓는 것이다.

**문법 확장은 0이다** — `parallel` … `merge` 블록 문법, 중첩 금지, 가드
불가는 전부 그대로다. 구현 도중 딱 하나의 좁은 예외가 필요하다는 것이
드러났다: `policy parallel`은 값을 받지 않는 플래그였는데(`_parse_policy_line`
의 일반 분기), 이 RFC의 동시성 상한(§Reference-level Specification)과 issue
#108의 완료 기준 자체가 `policy parallel <N>`을 리터럴로 요구한다. 이것은
`retry <N>`이 이미 갖고 있는 것과 같은 모양의 인자 하나를 `parallel`에도
주는 것뿐이며(§절 이름·문법 요소 자체의 확장이 아니라 기존 정책 이름 하나의
값 arity 확장), 코디네이터가 구현 중 승인했다(§Reference-level Specification
의 arity 절).

## Guide-level Explanation

저자는 아무것도 새로 배우지 않는다 — `parallel` … `merge` 블록은 이미 쓸 수
있었다. 달라지는 것은 그 블록이 실제로 하는 일뿐이다:

```lnpl
parallel
    call PricingService as pricing
    call InventoryService as inventory
    call ShippingService as shipping
merge
```

이 세 `call`은 이제 동시에 나간다. 셋 다 200ms가 걸리는 서비스라면, 이
블록의 벽시계 비용은 순차였다면 600ms였을 것이 200ms에 가까워진다.

**하나가 실패하면 블록 전체가 실패한다.** `InventoryService`가 에러를
던지면 `PricingService`/`ShippingService`가 아직 시작하지 않았다면 취소되고
(이미 시작한 것은 자기 시도가 끝날 때까지는 계속한다 — 스레드는 강제
종료할 수 없다), 워크플로는 실패로 종결한다. `result["failed_step"]`은
실패한 스텝의 이름을 그대로 담는다 — 순차 실행이 실패했을 때와 같은 모양.

**동시성에는 상한이 있다.** `policy parallel 2`를 선언하면 이 블록은 한
번에 최대 2개 스텝만 동시 실행한다(선언이 없으면 상한은 그 블록의 스텝
수 — 자연 상한, `parallel`은 중첩할 수 없어 애초에 낮다).

**같은 entity에 쓰는 두 스텝을 한 블록에 넣을 수 없다.** `parallel` 블록
안에는 순서가 없으므로, 두 스텝이 같은 행을 쓰면 어느 쪽이 "이겼는지"가
실행마다 달라진다 — 컴파일러가 이것을 거부한다:

```lnpl
parallel
    update product          # line 12
    update product          # line 13
merge
```

```
LowerError: workflow Restock: `parallel` block has 2 steps writing Product
at lines 12, 13 — same-entity writes inside one `parallel` block are
non-deterministic ...
```

읽기와 쓰기가 섞이거나, 서로 다른 entity를 쓰는 것은 그대로 허용된다 —
경합하는 것은 같은 행에 대한 쓰기 순서뿐이다.

## Reference-level Specification

### RFC-0003 §Execution Model — Concurrency 문단 (치환 후 최종 텍스트)

**Concurrency(mode=parallel) = structured concurrency.** 각 child는 병렬
브랜치이고 children 배열의 끝이 병합 지점이다(RFC-0001 Concurrency 행).
계약: ① 전 브랜치가 완료되어야 병합 지점을 통과한다(기본 merge = 전 브랜치
완료 대기). ② 한 브랜치가 실패하면 형제 브랜치에 취소를 전파하고, 전 브랜치
종결 후 부모로 실패를 전파한다. ③ 부모의 취소(데드라인 초과 포함)는 전
브랜치로 전파된다. ④ 브랜치는 병합 지점을 넘어 생존할 수 없다 — 고아 작업
금지. 동시성 상한은 `Policy.parallel N`이 선언돼 있으면 N, 없으면 그 블록의
브랜치 수다. 같은 entity에 쓰는 두 브랜치가 한 블록 안에 있으면 컴파일
거부다 — 병합 지점에 순서가 없는 블록 안에서 쓰기 순서에 결과가 의존하면
그 결과는 실행마다 달라질 수 있기 때문이다(RFC-0012 §G12.2의 순서-의존
바인딩 규칙과 충돌).

(다른 문단 — Actor·Workflow step·Effect 실행 의미·Clock·Guard — 은 이 갱신의
대상이 아니며 바뀌지 않는다.)

### RFC-0003 §Policy Enforcement — `Policy.parallel N` 행 신설 (치환 후 최종 텍스트)

| 항목 | 런타임 의미(계약) |
|------|------------------|
| `Policy.parallel N` | `parallel` 블록의 동시성 상한(§Execution Model Concurrency 문단). 선언값 N이 있으면 그 블록의 동시 실행 스텝 수는 N을 넘지 않는다 — 없으면 상한은 그 블록의 브랜치 수(자연 상한, 병목 없음). 블록 하나가 스코프다: 실행기는 블록 시작 시 만들어지고 병합 지점 통과 전에 반드시 종료한다(고아 작업 금지, §Execution Model ④). 한 브랜치가 실패하면 아직 시작하지 않은 형제 브랜치는 취소되고, 이미 시작한 브랜치는 자신의 현재 시도가 끝날 때까지 진행한 뒤 합류한다(재시도가 있는 브랜치는 **다음** 재시도부터 중단 — 스레드는 강제 종료할 수 없다). 보고는 완료 순서가 아니라 **선언 순서**다 — 병합 후 일괄 기록되므로 `steps <N>`은 순차 실행이었을 때와 같은 모양이다. `Policy.timeout`의 잔여 데드라인은 블록 전체에도 적용된다: 블록의 스텝들이 성공적으로 끝났어도 그 시점에 데드라인을 이미 넘겼으면 그 실행은 여전히 `TimedOut`으로 종결한다 |

(다른 행 — `Policy.retry`·`Policy.rollback`·`Policy.timeout`·
`Performance.cache`·`Performance.response` — 은 이 갱신의 대상이 아니며
바뀌지 않는다.)

### `policy parallel` 문법 — 선택적 정수 인자 (신설, §Motivation 참조)

`impl/lnpl/lower.py`의 `_parse_policy_line`이 `retry`와 같은 모양의 분기를
얻는다: 값 없이 `parallel`만 쓰면(기존 문법 그대로) 캡은 위 표의 폴백을
따른다. `parallel <N>`(N은 정수)이면 캡은 N이다. 다른 형태(비정수, 인자
2개 이상)는 `LowerError`. IR의 `Policy` 노드가 갖는 `rules` 항목은 값이 없을
때 `{"name": "parallel"}`, 값이 있을 때 `{"name": "parallel", "value": N}` —
`retry`/`timeout`이 이미 쓰는 것과 같은 모양이다.

### 실행 메커니즘 (mode A, `impl/lnpl/interp.py`)

`_flatten_items`는 더 이상 `Concurrency` 노드를 평탄화하지 않는다 — 자식
step id 목록을 담은 `_ParallelGroup` 마커를 낸다. `run_workflow`의 메인
루프가 이를 만나면 `_run_parallel_block`으로 위임한다:

1. **실행기.** `ThreadPoolExecutor(max_workers=cap)` — 블록마다 새로 만들고
   `with`로 닫는다(장수 풀 없음, 블록이 스코프). 스텝마다 워커 하나를
   `submit`한다.
2. **Fail-fast.** `concurrent.futures.wait(futures,
   return_when=FIRST_EXCEPTION)`로 첫 실패를 감지한다. 감지되면 아직
   시작하지 않은 future는 `cancel()`(시작한 것에는 무효), 재시도 루프가
   매 시도 전에 확인하는 공유 `threading.Event`를 set한다(진행 중인 시도는
   끝까지, 다음 시도부터 중단). `with` 블록의 `__exit__`이 이미 시작한
   모든 작업을 join한 뒤에야 이 메서드가 반환한다 — 성공이든 실패든 이
   블록을 벗어나 살아남는 작업은 없다.
3. **상태 안전.** `threading.RLock` 하나(`_run_parallel_block`이 매번 새로
   만든다). 워커 스레드가 저장소/캐시 드라이버를 호출하거나
   `bindings`/`rowsets`/trace/diagnostics를 건드리는 동안은 이 락을 쥔다.
   **예외는 `NetworkDriver.call`뿐** — 그 호출 바로 앞에서 풀고 반환/예외
   직후 다시 잡는다(`_run_effect`의 `NetworkCall` 분기). 병렬이 주는
   이득의 실체가 바로 이 구간이다. sqlite 커넥션은
   `check_same_thread=False`로 열리지만(`drivers.py`), 이 락이 직렬화를
   보장하므로 RFC-0032의 실행당 트랜잭션 1개 의미론은 바뀌지 않는다 —
   `begin`/`commit`/`rollback`은 여전히 메인 스레드에서만 호출된다.
4. **보고는 선언 순서.** 스팬(`root.children`)과 `result["steps"]` 항목은
   완료 순서가 아니라 **블록에 쓰인 순서**로, 전 작업이 join된 뒤 일괄
   기록된다 — `spec.py`의 `steps <N>`이 순차 실행이었을 때와 같은 모양을
   내는 이유다. 시작도 못 하고 취소된 스텝은 항목이 없다(순차 실패 뒤의
   미실행 스텝과 같은 모양). 각 스텝 스팬의 `start_ms`/`end_ms`는 이
   워크플로의 다른 모든 스팬이 쓰는 가상 `Clock`이 아니라 **실제 벽시계**
   (`time.monotonic()`)다 — 형제 스팬이 결정론적 카운터 하나를 공유하면
   겹칠 수가 없고, 겹침이 바로 실제 동시 실행의 증거이기 때문이다. 가상
   `Clock`은 그대로 전진한다(락 아래, 데드라인/백오프 계산용) — 스팬
   타임스탬프만 실제 시각을 쓴다.
5. **데드라인.** 블록의 각 스텝은 자신의 시도 시작 시점에 데드라인을
   확인한다(`_run_step`의 기존 진입 가드, 변경 없음). 블록 전체가
   join된 뒤에도 한 번 더 확인한다 — 스텝 전부가 개별적으로는
   성공했더라도, 그 시점에 누적 가상 시간이 데드라인을 이미 넘겼다면
   그 실행은 `TimedOut`으로 종결한다(순차 실행의 "step 완료 후" 검사와
   같은 계약, §Policy Enforcement 위 표). 어느 스텝을 탓할지는 선언
   순서의 마지막 스텝으로 보고한다 — 동시 실행에는 순차와 달리 "정확히
   그 스텝이 넘겼다"고 말할 단일한 인과 지점이 없다.
6. **회귀 없음.** `_run_step`/`_run_effect`는 `lock=None`(기본값)일 때
   위 1-5 어느 것도 실행하지 않는다 — `if lock is not None` 가드가
   전부 스킵된다. `parallel` 없는 워크플로를 처리하는 메인 루프는 이
   RFC 이전과 같은 코드 경로를 그대로 쓴다(별도 인라인 순차 로직 —
   `_execute_step_with_retry`와 공유하지 않는다, 회귀 없음을 리팩터링에
   기대지 않기 위해).

### 쓰기 충돌 컴파일 거부 (`impl/lnpl/lower.py`)

`_check_parallel_write_conflict`가 각 `Concurrency` 노드의 직계 자식(항상
`WorkflowStep` — `parallel`은 중첩·가드 불가)을 스캔해, RepositoryCall
operation이 쓰기 계열(`create`/`update`/`delete` — `insert` 동사도
`create` operation으로 도출된다, `VERB_LEXICON`)인 Effect가 같은 entity를
두 번 이상 겨누면 `LowerError`를 낸다. 메시지는 워크플로 이름·entity
이름·**두 스텝의 줄번호를 모두** 담는다. 읽기 하나 + 쓰기 하나, 또는 서로
다른 entity에 대한 쓰기 둘은 허용된다 — 경합하는 것은 같은 행에 대한 쓰기
순서뿐이다(§Reference-level Specification 위 Concurrency 문단).

### 집행 매트릭스 승격 (`impl/lnpl/diagnostics.py`, `docs/ENFORCEMENT-MATRIX.md`)

`ENFORCEMENT[("policy","parallel")]`이 `UNENFORCED`에서 `ENFORCED`로
바뀐다 — `enforced` 행은 진단 코드가 없으므로(`declared-not-enforced`가
`ENFORCED` 항목을 건너뛴다, `_declaration_diagnostics`) `policy parallel`을
선언해도 더 이상 그 진단이 뜨지 않는다. `retry`/`timeout`/`rollback`이
이미 그렇듯, 선언한 그대로 실행되는 것은 보고할 간극이 아니다.

`performance parallel`/`prefetch`/`batch`는 **이 RFC의 대상이 아니며
`UNENFORCED`로 남는다.** 이름은 비슷하지만 뜻이 다르다 — `policy
parallel`은 워크플로 **안 스텝의 실행 순서**를 바꾸고, 이 셋은 저장소
호출 하나를 **어떻게** 내보내는지(prefetch·batch)를 말하는 저장소
접근 패턴 선언이다. 그 의미는 질의 술어(issue #116의 이웃)가 있어야
채워지고, 이 RFC의 범위 밖이다.

### mode B와 차동 검증 (`impl/lnpl/differential.py`, `docs/backends.md` §6)

mode B는 이 RFC로 바뀌지 않는다 — 여전히 모든 블록을 순차 실행한다
(RFC-0004 §5(#7), 계속 미결). `differential.compare_observations`는 네
관측 클래스(실행 순서+skips, 정책 결과, 관측 신호, 마스킹) 중 어느 것도
실제 동시 실행 여부를 보지 않으므로(실행 순서는 선언 순서로 보고되어
mode B와 우연히 같은 모양이 된다), `parallel` 블록이 있는 워크플로의
리포트에 미검증 차원 한 줄을 추가한다: `note: N \`parallel\` block(s) —
mode B runs them sequentially (unverified dimension, docs/backends.md §6)`.
issue #116의 `list where` 술어 노트와 같은 설계 — `EQUIVALENT` 판정 자체는
바뀌지 않는다(네 클래스가 실제로 일치할 때는 참인 판정이다), 다만 그것이
"동시성까지 검증됐다"로 읽히지 않게 한다.

## Examples

### Golden Scenario: Login

`examples/login.lnpl`은 `parallel` 블록을 쓰지 않는다 — 이 RFC로 그
실행이 바뀌지 않는다(§Motivation의 "회귀 없음" 문단, DoD 7). 골든의 6단계
실행 순서·`policy(retry 3, rollback, timeout 3s)` 집행·trace 모양은
RFC-0003/RFC-0032가 이미 고정한 그대로다.

### 인접 예제 — 병렬 팬아웃과 실패 전파

골든이 다루지 않는 기능(RFC-0007 §6)이므로, 위 §Guide-level Explanation의
스니펫을 확장해 실패 시나리오를 보인다:

```lnpl
entity Order
    field
        id UUID

service FanOutService
    policy
        parallel 2
        timeout 5s

workflow FanOut
    parallel
    call PricingService as pricing
    call InventoryService as inventory
    call ShippingService as shipping
    merge
    create order
```

`InventoryService`가 실패하면:

```
trace tr-108  (workflow=FanOut, deadline 5000ms)
└── span wf.FanOut                       status=Failed
    ├── span call PricingService         [ 0 →  ~Tms]  (완료 또는 취소)
    ├── span call InventoryService       [ 0 →  ~Tms]  실패
    └── (ShippingService — 시작 전이면 취소, steps 항목 없음)
result: status=failed, failed_step="call InventoryService"
```

세 브랜치가 겹쳐 시작했다는 사실(벽시계 스팬)과, `create order`가 아예
실행되지 않았다는 사실(블록 실패 → 워크플로 fail-fast, §Reference-level
Specification 위 §Execution Model ②)이 이 예제의 요지다. `policy parallel
2`이므로 동시 실행은 최대 2개로 제한된다 — 이 예제에는 브랜치가 3개이므로
그중 하나는 다른 하나가 끝날 때까지 대기했을 수 있다(어느 쪽인지는
스케줄러가 결정, 계약 대상 아님).

## Alternatives

1. **asyncio로 전환한다** — 기각. `interp.py`는 스레드-퍼-요청 모델(`wsgi.py`)
   위에서 이미 동기 코드로 짜여 있다 — 이벤트 루프 하나를 위한 전면 재작성은
   이 이슈의 범위(모드 A의 `parallel` 블록 실행 하나)를 훨씬 넘는다.
   `ThreadPoolExecutor`는 기존 동기 코드베이스에 최소 침습으로 들어맞는다.
2. **장수 스레드풀(워크플로 전역, 또는 프로세스 전역)을 둔다** — 기각.
   RFC-0003 §Execution Model ④("브랜치는 병합 지점을 넘어 생존할 수 없다")가
   이미 구조적 동시성을 계약으로 못박았다 — 블록 스코프 실행기만이 "블록이
   끝나면 살아 있는 작업이 없다"를 코드 구조로 증명한다. 장수 풀은 그 증명을
   포기하고 수동 정리에 의존하게 만든다.
3. **`performance parallel`/`prefetch`/`batch`도 함께 `enforced`로 올린다**
   — 기각. 이 셋은 저장소 접근 패턴 선언이고, 그 뜻은 질의 술어(issue #116의
   이웃, `list where`)가 있어야 정해진다 — 지금 올리면 아직 정의되지 않은
   의미를 집행하겠다고 약속하는 꼴이다.
4. **상한 없이 무제한 팬아웃을 허용한다(선언 없으면 무제한)** — 기각.
   Step Functions `Map`의 `maxConcurrency` 교훈(§Motivation) — 상한 없는
   동시성은 하류 서비스를 압도한다. 블록의 브랜치 수를 자연 상한으로 쓰는
   것은 `parallel`이 중첩 불가라 그 수 자체가 이미 작다는 사실에 기댄다.

## Open Questions

1. **mode B 동시성** — RFC-0004 §5(#7)가 이미 미결로 들고 있던 질문 그대로,
   이 RFC로도 열려 있다. 네이티브 컴파일 백엔드에 구조적 동시성을 어떻게
   내릴지(스레드? 코루틴? region 문법?)는 후속 이슈다.
2. **`performance prefetch`/`batch`의 의미** — issue #116의 질의 술어
   이웃. 저장소 접근 패턴으로서 무엇을 "선언"하고 무엇을 "집행"으로 볼지는
   그 이슈(또는 후속)의 몫이다.
3. **`parallel` 중첩·가드 결합의 확장** — 지금은 RFC-0002 문법이 둘 다
   막는다. 저자 요청이 쌓이면 별도 RFC가 문법 확장(이 RFC는 0으로
   유지했다)과 함께 다뤄야 한다 — 중첩이 열리면 §Reference-level
   Specification의 쓰기 충돌 검사가 재귀로 확장돼야 한다는 점도 그때
   같이 결정한다.

# RFC-0029: Clock 계약과 `--clock real` 바인딩

## Status

- Status: **Accepted** (RFC-0029, 2026-08-24)
- Updates: RFC-0003 §Reference-level Specification/Execution Model (Clock 계약 신설)

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목한다. RFC-0003 §Execution Model은
Actor·await 지점·structured concurrency·Effect 표를 규정하면서 `Policy.timeout`의
데드라인 기산, `Policy.retry`의 backoff 대기, `CacheAccess`의 TTL 판정이 전부
"경과 시간"을 공유한다고 암묵적으로 전제하지만, 그 시간 소스 자체는 이름 붙여진
적이 없다. 이 문서는 그 소스를 **Clock 계약**으로 처음 명명한다 — Execution Model의
다른 어떤 기존 서술(Actor, await 지점, structured concurrency, Effect 표의 각
행)도 건드리지 않는다. Effect 표의 `NetworkCall` 행은 RFC-0027이 이미 갱신했지만,
그 갱신과 이 문서가 신설하는 Clock 절은 서로 다른 스코프이므로(RFC-0027은
"§Execution Model (`NetworkCall` 행)"만 지목했다) 겹치지 않는다 — 규칙 5(연쇄
갱신)는 **같은 스코프**를 다시 갱신할 때만 적용되며, Clock은 이번이 첫 갱신이므로
지목할 직전 갱신 RFC가 없다.

## Motivation

이슈 #100. `impl/lnpl/drivers.py`의 `CacheDriver` docstring이 이미 실측해 스스로
기록해 둔 공백이다:

> RFC-0003 denominates a cache TTL in the run's injected clock, which starts at 0
> in every process. A persisted entry would be compared against a fresh clock and
> read as live forever, so "a persistent cache" would be a store whose expiry
> contract is untrue.

`interp.Clock`은 프로세스 로컬 카운터이고 `step_cost_ms`(참조 구현: 5ms)만큼
`advance()` 호출로만 전진한다 — 벽시계와 무관하다. 이것은 결함이 아니라
**의도된 결정성**이다: `lnpl diff`의 mode A/mode B 동등성 검증과 spec 골든
산출물은 동일 입력이 항상 동일 시각열을 내야 하고, virtual Clock이 그것을
보장한다. 문제는 이 유일한 바인딩이 **운영 시나리오와 검증 시나리오를 구분하지
않는다**는 것이다 — TTL을 벽시계 경과에 묶어야 하는 운영 배치(장시간 구동되는
`serve`, 영속 저장소와 짝지어 쓰는 캐시)에도 같은 결정적·프로세스 로컬 시계가
강제된다. `docs/backends.md` §5는 이것을 `redis` 실바인딩을 하지 않는 이유로
기록해 두었다.

이 문서는 새 바인딩을 하나 추가해 그 공백을 좁힌다 — **가상 시계를 대체하지
않는다.** 기본값은 그대로 virtual이고, 그 값·순서·결정성은 이 개정으로
**바뀌지 않는다.**

## Guide-level Explanation

`.lnpl`을 쓰는 쪽에서 달라지는 것은 없다 — Clock은 IR에 나타나지 않는 순수
운영자 선택이다. 오퍼레이터가 `lnpl run --clock real`을 선택했을 때만 달라진다:

- 기본(`--clock` 생략, 또는 `--clock virtual`): 지금까지와 동일한 결정적
  가상 시계. `Policy.timeout` 데드라인, retry backoff, `CacheAccess` TTL이
  전부 이 프로세스 로컬 카운터를 읽는다.
- `--clock real`: 위 셋이 대신 단조 증가하는 **실제 벽시계**(`time.monotonic_ns`)를
  읽는다. `CacheAccess`의 `set`이 기록한 TTL은 실제 경과 시간으로 만료된다 —
  이것이 이 바인딩의 첫 소비처다(§Motivation의 공백).

`lnpl diff`와 `lnpl spec`은 `--clock`을 받지 않는다 — 결정성이 요구되는 두
검증 경로에 비결정적 바인딩이 섞여 들어올 표면 자체가 없다(§Reference-level
Specification의 폐쇄 표).

## Reference-level Specification

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0003 §Execution Model에 **신설되는**
절의 최종 텍스트다. 기존 절(Actor, Workflow step, Concurrency, Effect 실행
의미)의 뒤, `### Guard` 앞에 붙는다.

---

**Clock.** 런타임의 모든 경과 시간 판정 — `Policy.timeout` 데드라인 기산과
잔여 시간 전파, `Policy.retry`의 backoff 대기, `CacheAccess`의 TTL 판정, trace
span의 시각 — 은 단일 **Clock 계약**을 통해서만 읽힌다: `now`(현재 시각의
판독값, 밀리초 정수)와 `advance(ms=None)`(시각을 전진시키는 연산; 인자를
생략하면 구현이 정한 기본 단위만큼 전진한다). 이 계약에는 두 바인딩이 있고,
선택은 폐쇄 표다:

| 바인딩 | 선택자 | 시간원 | `advance()` | 결정성 |
|--------|--------|--------|--------------|--------|
| **virtual**(기본) | 생략 또는 `--clock virtual` | 프로세스 로컬 카운터. `0`에서 시작하며 벽시계와 무관하다 | 카운터를 전진시킨다 — step 경계마다 고정 단위(참조 구현: 5ms)만큼 자동 호출된다 | 완전 결정적: 동일 입력은 항상 동일 시각열을 낸다 |
| **real** | `--clock real` | 단조 증가하는 실제 벽시계(`time.monotonic_ns`) | 무의미하다 — 벽시계는 호출과 무관하게 전진하므로 no-op | 비결정적: 벽시계 경과에 좌우된다 |

`--clock`을 생략한 모든 기존 실행 경로(`run`의 기본값, `spec`, `diff`)는
virtual 바인딩을 그대로 쓴다 — 이 개정 전후로 그 경로들의 관측 가능한
시각열·순서·판정은 **바뀌지 않는다.** `lnpl diff`의 mode A/mode B 동등성
검증과 spec 골든 산출물은 virtual 바인딩 위에서만 유효하다 — `--clock`
선택자는 `diff`/`spec` 서브커맨드에 존재하지 않으며(폐쇄 표는 `run`에만
있다), real 바인딩으로 실행한 run은 비결정적이므로 애초에 그 비교 대상이
될 수 없다.

real 바인딩의 첫 소비처는 `CacheAccess`의 TTL 판정이다 — `Performance.cache
T`(§Policy Enforcement)가 소유하는 예산 자체는 바뀌지 않지만, `--clock real`
아래에서는 그 예산이 벽시계 경과에 묶인다. capability 드라이버가 TTL을
어떻게 집행하는가(클록 비교 vs 스토어 네이티브 만료 위임)의 세부는 이
RFC의 관할이 아니다 — `CacheDriver` 계약(코드 수준 docstring,
`docs/backends.md` §5)이 소유한다.

---

**참조 구현.** 두 바인딩은 `impl/lnpl/interp.py`의 `Clock`(virtual, 기존
구현 그대로)과 `RealClock`(신설)이다. 선택자는 `open_clock`(닫힌 표
`("virtual", "real")`, `--backend`/`--network`의 `open_repository`/
`open_network`와 같은 모양 — 미인식 값은 rc 2로 거부되고 허용 집합을
함께 출력한다)이며 `impl/lnpl/cli.py`의 `run` 서브커맨드에만 있다.
`Interpreter.__init__`은 이미 `clock=None` 키워드를 받아 생략 시 기본
`Clock()`을 만든다(issue #25 이전부터) — 이번 개정은 그 자리에 넣을 두
번째 바인딩을 추가했을 뿐, 기존 시그니처나 기본 경로를 바꾸지 않는다.

## Examples

골든 시나리오 "Login"(정본: `plans/rfc-suite/plan.md` §골든 시나리오
"Login"). RFC-0003 §Examples의 세 타임라인은 모두 **virtual 바인딩** 위의
관측이며, 이 개정으로 바뀌지 않는다 — 타임라인 A의 `CacheAccess(set, ...,
TTL=5m)`과 타임라인 B의 "5분 내 재실행 → 적중"은 여전히 같은 프로세스 로컬
카운터가 판정한다.

골든이 다루지 않는 real 바인딩은 골든 인접 예제로 제시한다(RFC-0007 §6).
`--clock real`로 같은 `login` workflow를 같은 캐시 인스턴스에 두 번 실행하되
`Performance.cache`를 `50ms`로 좁힌 변형:

```
$ lnpl run login.lnpl --clock real --backend sqlite:./s.db
workflow login -> completed  (41ms, ...)
  step cache-user  ...  [CacheAccess set key="user:{id}" ttl_ms=50]

$ sleep 0.1   # 실제 100ms 경과 — TTL 50ms를 넘는다

$ lnpl run login.lnpl --clock real --backend sqlite:./s.db
workflow login -> completed  (43ms, ...)
  step cache-user  ...  [CacheAccess get key="user:{id}" -> miss]   # 벽시계로 만료
```

virtual 바인딩(기본)에서는 두 `lnpl run` 호출이 각자 새 프로세스이므로
캐시가 애초에 공유되지 않는다 — 이 예제가 관측 가능해지려면 real 바인딩과
함께 캐시가 두 호출에 걸쳐 살아있는 배치(예: 장시간 구동되는 임베딩)가
필요하다. 참조 구현 수준의 대응은 `impl/tests/test_clock.py`가 단일
`Interpreter`/`FakeCache` 인스턴스에 대해 real Clock으로 이 시나리오를
직접 구성해 증명한다 — `lnpl serve`(`impl/lnpl/serve.py`)가 요청마다 새
`Interpreter`를 만드는 현재 구조에서는 이 RFC가 만드는 바인딩 하나만으로
캐시가 요청 경계를 넘어 살아남지 않으며, 그 경계를 바꾸는 것은 이 RFC의
범위 밖이다(`serve.py`는 별도 소유).

## Alternatives

**① virtual Clock의 시작값·전진 단위를 조작해 벽시계에 맞춘다**(예: 매
`now` 읽기마다 `time.monotonic_ns()`로 재동기화). 기각한다: virtual
바인딩의 유일한 가치는 완전한 결정성이고, 벽시계 재동기화는 그 결정성을
정확히 깨뜨린다 — `lnpl diff`가 실행마다 다른 시각열을 비교하게 된다.

**② 새 바인딩 대신 `CacheDriver` 구현이 각자 알아서 벽시계를 읽게 한다**
(Clock 계약을 우회). 기각한다: `Policy.timeout`·`Policy.retry`도 같은
"프로세스 로컬 vs 벽시계" 문제를 겪는데, 캐시만 예외로 두면 한 실행 안에
서로 다른 시간원이 섞인다 — 데드라인은 결정적인데 캐시 TTL은 벽시계인
실행은 trace가 자기모순적으로 읽힌다. 단일 계약이 세 소비처 모두를
같은 바인딩으로 묶어야 한다.

**③ `--clock`을 `diff`/`spec`에도 노출하고 문서로만 "쓰지 말라"고 적는다.**
기각한다: 문면 금지는 실수를 막지 못한다 — `--clock real`로 돌린 diff가
`DIVERGENT`를 내면 그것이 real 바인딩의 비결정성 때문인지 실제 회귀인지
구분할 수 없다. 선택자 자체를 그 서브커맨드에 두지 않는 쪽이 실수를
구조적으로 없앤다.

## Open Questions

1. **real 바인딩과 EventEmit/Transaction의 상호작용.** 이 RFC는 `CacheAccess`
   TTL을 첫 소비처로 삼았을 뿐, `Policy.timeout`/`Policy.retry`가 real
   바인딩 아래에서 실제로 벽시계 대기를 강제할지(현재는 두 바인딩 모두
   `advance()` 호출이 실제 sleep을 만들지 않는다 — virtual은 원래 그렇고,
   real은 자연 경과만 반영한다)는 별도 검토가 필요하다. 이 범위를 넘는다.
2. **`RealClock`이 여러 `Interpreter` 인스턴스에 걸쳐 공유돼야 하는가.**
   `lnpl serve`가 요청마다 새 `Interpreter`(따라서 새 캐시)를 만드는 한
   `--clock real`은 "같은 프로세스 안에서 오래 사는 캐시" 시나리오에서만
   의미가 있다. 요청 경계를 넘는 캐시 공유는 `serve.py`의 소유이며 이
   RFC는 그 경계를 만들지도 넓히지도 않는다.
3. **캐시 스탬피드 보호(RFC-0003 §Open Questions 4)는 여전히 미결이다.**
   real 바인딩은 만료를 관측 가능하게 만들 뿐, 동시 재계산 보호는 다루지
   않는다.

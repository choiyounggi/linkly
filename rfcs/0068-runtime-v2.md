# RFC-0068: Runtime

## Status

- Status: **Accepted** (RFC-0068, 2026-10-28)
- Supersedes: RFC-0003

**통합 출처.** 갱신 RFC에서 온 텍스트와 그 출처는 다음과 같다(RFC-0007 §2.2 규칙 3·5, 연쇄를 끝까지 따른 최신 Accepted 텍스트).

| 절 | 효력 있는 텍스트의 출처 |
|----|------------------------|
| §Reference-level Specification/Execution Model | Concurrency 문단: RFC-0041 §Reference-level Specification. Effect 머리 문장과 표: RFC-0056 §3(그 표의 `Transaction`·`EventEmit` 행은 RFC-0032 §Reference-level Specification과 같은 텍스트), 단 `CacheAccess` 행은 RFC-0062 §7. 표 바로 뒤 문단(`NetworkCall`의 타임아웃 접합): RFC-0027 §5(후속 갱신이 말없이 뺀 요소, 유지). Clock 문단과 그 표, 뒤의 두 문단: RFC-0029 §Reference-level Specification |
| §Reference-level Specification/Guard | 상수 정의부터 2.6 끝까지: RFC-0008 §2를 갱신한 RFC-0014 §2의 연쇄 최신 텍스트로, RFC-0071 §Reference-level Specification/2와 같은 텍스트다. 바탕은 RFC-0014 §2(상수 정의, 2.1~2.6 제목, 2.2·2.3 본문, 2.5 첫 두 문단). 2.1 본문: RFC-0060 §6. 2.4 머리 문장·표·결합 문단: RFC-0060 §7. 2.4 마지막 문단: RFC-0027 §6(후속 갱신이 말없이 뺀 요소, 유지). 2.5 마지막 문단: RFC-0022 §Reference-level Specification/표 1 — 관측 신호별 모드 대조. 2.6 둘째·셋째 문단: RFC-0028 §4. 2.4의 `steps` 사유 문단과 status 어휘 문단, 2.6 첫 문단과 마지막 두 문단: RFC-0014 원문(RFC-0028 §4·RFC-0060 §7이 말없이 뺀 요소, 유지). G12.1~G12.7: RFC-0012 §RFC-0003 §Guard의 연쇄 최신 텍스트로, RFC-0070 §Reference-level Specification/G12.1~G12.7과 같은 텍스트다. 바탕은 RFC-0012 §RFC-0003 §Guard. G12.2 — 머리 문단: RFC-0030 §2. 머리 문단 뒤 문단(`Aggregate`의 `Reference`는 … 넓힌 것이다): RFC-0025 §5 — RFC-0027 §4가 말없이 뺀 두 문장, 유지. 단일 행 바인딩: RFC-0025 §5, 단 바인딩 값 문장은 RFC-0052 §2. RowSet 바인딩: RFC-0025 §5, 단 읽기 전용 소비 항목은 RFC-0059 §4. 네트워크 결과 바인딩: RFC-0027 §4. 생성 결과 바인딩과 `update`·`delete` 문단: RFC-0030 §2. 마지막 문장(`by`가 있어도 바인딩하지 않는다): RFC-0052 §2. G12.4 — 표의 둘째 행과 마지막 문단: RFC-0025 §6.1. G12.5 — 표의 ⓒ 행: RFC-0052 §2. 절 끝 문단들, 이 순서로: RFC-0025 §6.2(`query`를 뺀 이유), RFC-0030 §3, RFC-0052 §2(멤버십 문단, 조회 키 고유 규칙 표, 두 거부의 문구). G12.6 — 마지막 문단: RFC-0052 §6. 마지막 세 문단(`Guard` 노드와 세 모드의 범위, `repeat`와 `Policy.retry`의 구분, 조건식의 표현력): RFC-0003 원문(RFC-0008 §2가 절 전체를 갱신하며 말없이 뺀 요소, 유지) |
| §Reference-level Specification/Policy Enforcement | 절 전체: RFC-0013 §Reference-level Specification. 단 `Policy.rollback` 행은 RFC-0032 §Reference-level Specification, `Policy.parallel N` 행은 RFC-0041 §Reference-level Specification |
| §Examples/타임라인 C — 재시도 소진과 rollback | 코드 블록과 둘째 글머리(`INFO` 로그 한 줄): RFC-0032 §Examples |

표에 없는 절과, 표에 있는 절에서 출처를 적지 않은 텍스트는 RFC-0003 원문 그대로다.

## Motivation

CHARTER §Runtime은 런타임의 목표를 "최소 메모리 사용, GC 최소화, Zero Copy,
Async Native, Event Driven, Actor Model, Lock Free"로 선언하지만, 이는 성질의
나열이지 계약이 아니다. RFC-0001은 Semantic IR의 노드 카탈로그를 규정하면서
"실행 의미(순서·실패·재시도의 동작)는 RFC-0003이 정의한다"(RFC-0001 §노드
카탈로그·§경계)고 명시적으로 위임했다. 이 문서가 그 위임의 이행이다 — IR의
Behavior·Effect·Constraint 노드가 런타임에서 갖는 **관측 가능한 실행 의미**를
계약 수준으로 고정한다.

이 계약이 필요한 이유는 소비자가 둘 이상이기 때문이다. LNPP의 실행 모드는
두 가지다(plan.md D14): MVP의 **IR 인터프리터**와 Phase 2의 **네이티브
컴파일 바이너리**. 컴파일러(RFC-0004)는 이 문서의 메모리 프리미티브·actor
계약을 소비해 lowering을 결정하고, 두 실행 모드는 이 계약이 규정하는 관측
가능한 동작 — 실행 순서, 정책 집행, 관측성 신호, 마스킹 — 에 대해 **동등**해야
한다. 계약이 없으면 인터프리터에서 검증한 프로그램이 네이티브에서 다르게
동작하는 것을 막을 방법이 없다.

또한 RFC-0001의 Password 타입은 "로그·직렬화·에러 메시지 노출 금지(마스킹
의무 — 런타임 계약은 RFC-0003)"를 이 문서에 위임했다. §Observability가 그
계약을 정의한다.

## Guide-level Explanation

LNPL(워킹네임, RFC-0000 §4)로 개발자가 선언하는 것은 의도뿐이다 — service,
workflow의 단계, policy·security·performance 제약. 스레드를 만들거나, 락을
잡거나, 커넥션 풀을 설정하거나, 트레이싱 라이브러리를 붙이는 코드는 존재하지
않는다. 그 전부가 런타임의 기본 동작이기 때문이다.

골든 시나리오 "Login"으로 보면: 개발자는 `workflow Login`의 6단계와
`policy(retry 3, rollback, timeout 3s)`를 선언했을 뿐이지만, 실행 시점에는 —

- `LoginService`의 각 인스턴스는 **actor**다. 요청은 메일박스에 쌓여 한 번에
  하나씩 처리되므로, 서비스 상태에 대한 데이터 레이스가 구조적으로 없다.
  개발자는 락을 본 적도 없다.
- workflow의 각 step은 **await 지점**이다. `authenticate`의 저장소 호출이
  끝나야 `cache user`가 시작된다. 그 순서는 IR의 `children` 배열이 이미
  말하고 있다.
- `parallel` 블록(IR의 Concurrency 노드)은 **structured concurrency**로
  실행된다: 모든 브랜치가 끝나야 병합 지점을 지나고, 하나가 실패하면 나머지는
  취소되며, 부모가 취소되면 전 브랜치가 함께 취소된다. 고아 작업(fire-and-
  forget)은 만들 수 없다.
- `timeout 3s`는 workflow 전체의 데드라인이 되어 모든 하위 호출에 잔여 시간이
  전파되고, `retry 3`은 멱등한 step에만 자동 적용되며, `cache 5m`은 캐시 쓰기의
  TTL이 된다.
- 실행 1회마다 trace(step = span)·상관ID·duration 메트릭·구조화 JSON 로그가
  자동 생성된다. `password` 필드는 어디에도 평문으로 찍히지 않는다.

요약하면: 개발자가 선언한 의도(IR)가 곧 실행 계획이고, 이 문서는 그 실행이
정확히 어떻게 관측되는가에 대한 약속이다.

## Reference-level Specification

이 절의 계약은 두 실행 모드(인터프리터·네이티브 — plan.md D14) 모두에
동일하게 적용된다. 계약의 단위는 **관측 가능한 동작**이다: 실행 순서, 정책
집행 결과, 관측성 신호(trace/메트릭/로그), 마스킹. 내부 구현(스케줄러 구조,
메모리 배치 선택)은 계약 대상이 아니며, 배치 선택 알고리즘은 RFC-0004 소유다.

### Execution Model

**Actor.** `service` 인스턴스 하나 = actor 하나다. actor는 직렬 메일박스를
가진다: 인스턴스로 들어오는 workflow 실행 요청은 메일박스에 적재되고 한 번에
하나씩 꺼내져 처리되므로, 서비스 인스턴스의 상태 접근은 메시지 처리 순서로
직렬화된다. 이것이 CHARTER §Runtime의 "Lock Free"의 이행이다 — 상호배제가
필요 없도록 공유를 제거한 것이지, 락을 다른 동기화로 바꾼 것이 아니다.
개발자에게 thread·lock API는 노출되지 않는다(CHARTER §Concurrency).

**Workflow step = await 지점.** Workflow의 `children` 배열 순서(RFC-0066
구조 규칙 3)가 실행 순서다. 각 step은 자신이 소유한 Effect가 완료되어야
종결되고, 다음 step은 선행 step 종결 후에 시작한다. step 경계가 곧 유일한
await 지점이므로, 실행 타임라인은 IR에서 정적으로 읽힌다.

**Concurrency(mode=parallel) = structured concurrency.** 각 child는 병렬
브랜치이고 children 배열의 끝이 병합 지점이다(RFC-0066 Concurrency 행).
계약: ① 전 브랜치가 완료되어야 병합 지점을 통과한다(기본 merge = 전 브랜치
완료 대기). ② 한 브랜치가 실패하면 형제 브랜치에 취소를 전파하고, 전 브랜치
종결 후 부모로 실패를 전파한다. ③ 부모의 취소(데드라인 초과 포함)는 전
브랜치로 전파된다. ④ 브랜치는 병합 지점을 넘어 생존할 수 없다 — 고아 작업
금지. 동시성 상한은 `Policy.parallel N`이 선언돼 있으면 N, 없으면 그 블록의
브랜치 수다. 같은 entity에 쓰는 두 브랜치가 한 블록 안에 있으면 컴파일
거부다 — 병합 지점에 순서가 없는 블록 안에서 쓰기 순서에 결과가 의존하면
그 결과는 실행마다 달라질 수 있기 때문이다(RFC-0070 §G12.2의 순서-의존
바인딩 규칙과 충돌).

**Effect 실행 의미.** Effect 대분류 7종 전부의 계약은 다음 표와 같다.

| Effect kind | 실행 의미(계약) |
|-------------|----------------|
| NetworkCall | 비동기 아웃바운드 호출 = await 지점. 모든 호출에 명시적 connect timeout + request timeout 필수 — 무한 기본값 금지(타임아웃 없는 호출 하나가 pool을 고갈시킨다). 잔여 데드라인과 상관ID를 자동 전파한다. 실패 유형별 재시도 판정은 §Policy Enforcement의 표를 따른다 |
| RepositoryCall | capability 커넥션 pool을 통해 실행되는 await 지점. 커넥션 획득은 operation당 1회이며, 다른 pool 자원을 획득하기 전에 반환해야 한다(같은 pool에 대한 중첩 획득은 pool 만석 시점에 데드락 — 금지). operation별 멱등성은 §Policy Enforcement의 판정 표를 따른다 |
| CacheAccess | `get` = miss가 오류가 아니라 정상 경로인 조회(miss 시 원천 조회로 폴백). `set` = TTL 필수 — TTL 값은 Performance 제약의 `cache` 예산이 소유한다(RFC-0066 CacheAccess 행). `invalidate` = 삭제. 캐시는 성능 계층일 뿐 정합성 메커니즘이 아니다 — 캐시 불가용 시 원천으로 폴백하되 동시성 상한 안에서만(무제한 폴백 herd는 캐시 장애를 원천 장애로 만든다). 읽기 동사의 `cached` 절(RFC-0062)이 `get`에 닿는 표면이다 — hit이면 원천 조회를 생략하고, miss면 원천을 읽어 같은 키로 `set`한다. |
| Transaction | 원자적 스코프 노드: children 전부 성공 시 커밋, 하나라도 실패 시 abort — 부분 쓰기는 관측되지 않는다. `isolation` 서술은 힌트이며 집행 수준은 해당 capability가 결정한다. Policy `rollback`의 보상 경계가 이 노드다(§Policy Enforcement). **Phase 1은 이 노드를 선언할 문법이 없다**(`VERB_LEXICON`이 어떤 동사도 `Transaction`으로 도출하지 않는다) — 그 공백 동안 워크플로 실행 전체가 유일한 암묵적 경계다: 실행 시작 시 열리고, 완주 시 커밋되며, 실패 시 그 실행에서 이뤄진 모든 쓰기를 롤백한다(RFC-0032). 명시적 `Transaction` 노드가 도입되면 이 암묵적 경계는 "children으로 아무 `Transaction`도 갖지 않는 워크플로"의 경계로 좁혀진다 — 지금은 모든 워크플로가 그 경우다 |
| Authorization | 소유 step의 다른 Effect보다 먼저 평가되는 게이트. **거부(deny)는 비재시도 실패다** — 같은 요청은 다시 보내도 같은 결과이므로 재시도 대상이 아니다. 검사 서비스 불가용(전송 실패)과 거부는 구분되며, 전자만 재시도 판정 대상이다 |
| EventEmit | 비동기 발행 — step의 동기 구간은 발행 요청 등록까지다. Transaction의 children으로 소유된 EventEmit은 **커밋 성공 후에만** 발행된다(롤백된 트랜잭션의 이벤트 유출 금지). Phase 1은 명시적 `Transaction` 노드가 없으므로(위 Transaction 행), 모든 EventEmit은 워크플로 실행 전체의 암묵적 경계가 그 소유자다 — 등록(`record_emission`)은 그 경계의 커밋과 함께만 durable해지고, 실행이 실패해 롤백되면 등록 자체가 저장소에 남지 않는다(RFC-0032, issue #102). 전달 보장은 at-least-once이며, 소비자가 event id로 dedupe할 수 있도록 발행마다 유일한 event id를 부여한다(발행 메커니즘의 구현은 §Open Questions ③) |
| Rejection | 저자가 선언한 업무 거절(RFC-0056). 도달하면 그 step이 실패하고 실행이 `failed`로 끝난다: `failure_kind = "rejected"`, `failure_reason` = `code`, `failed_step` = 그 step 이름. 실행이 실패했으므로 위 Transaction 행의 암묵적 경계가 그 실행의 모든 쓰기와 발행 등록을 롤백한다 — 별도 경로가 없다. **비재시도 실패다**: 가드가 이미 이 실행의 바인딩에 대해 참이었으므로 다시 시도해도 같은 결과다(Authorization 거부와 같은 이유, §Policy Enforcement "요청 자체의 오류" 행). 가드가 거짓이면 이 step은 실행되지 않으며 스킵 기록(RFC-0071 §2.4)만 남는다 |

`Policy.timeout`이 선언되면 `_run_step`이 갖고 있는 `deadline`(밀리초, 워크플로
시작 시각 기준)에서 `self.clock.now`를 뺀 **잔여** 예산을 `NetworkDriver.call`의
`timeout_ms`로 넘긴다 — RFC-0003 §Execution Model이 "잔여 데드라인을
전파한다"고 규정한 것이 실제로 접합되는 첫 지점이다. `Policy.timeout`이
선언되지 않으면(`deadline is None`) `DEFAULT_NETWORK_TIMEOUT_MS = 30_000`(30초)를
쓴다 — 무한 기본값은 결코 쓰지 않는다(backend/common/reliability/timeouts-and-retries:
"library defaults are unreliable and some are infinite; 하나의 무한 타임아웃이
pool을 고갈시킨다"). 이 값은 이 RFC가 새로 정하는 상수이며, 워크플로가 스스로
`timeout`을 선언하면 언제나 그 예산이 이긴다.

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

### Guard

**상수 정의:**
```
_UNTIL_ROUND_CAP = 16
```

이 상수는 모드 A(런타임 평가) 및 모드 B(컴파일)가 모두 따라야 하는 계약값이다.

#### 2.1 `when` 모드

조건을 **1회 평가**한다. 대안 가드가 없으면(§Reference-level Specification/1의
`AltGuard*`가 0개) RFC-0014 원문 그대로 — 조건이 참이면 피가드 항목을 실행하고,
거짓이면 건너뛴다.

**대안 가드가 있으면**, 조건과 모든 대안을 소스 순서대로 **전부 평가**한다
(단락 평가 없음 — RFC-0014가 `and`의 각 항을 전부 평가하는 것과 같은 이유:
조건은 순수하므로 결과는 같고, 트레이스는 평가되지 않은 항이 있으면 그 항의
값을 영영 보여줄 수 없다). **하나라도 참이면** 피가드 항목을 실행한다. 실행되는
경우, 트레이스는 참으로 판정된 첫 항이 조건 자신인지 몇 번째 대안인지를
`INFO` 레벨로 남긴다(§2.4에서 정의하는 스킵 레코드와는 다른 채널 — 스킵이
아니라 **실행됐다**는 사실의 관측이므로):

```
guard alternative matched: alt=0 condition="input.channel == 1"
```

조건 자신이 참이면 `alt=<primary>`로 남긴다(대안 번호가 아니라 원 조건이
참이었다는 뜻) — 이 경우는 대안 가드가 없는 기존 프로그램과 관측이 달라지지
않는다는 것을 보장하기 위한 표기이지, 새 요구 사항이 아니다: **대안이 없는
`when`은 이 로그를 전혀 내지 않는다**(하위 호환. `evaluations`가 issue #83에서
그랬듯, 새 신호는 그것을 켠 프로그램에서만 나타난다).

**전부 거짓이면**(대안 가드가 없을 때의 "거짓"과 동형), 건너뛴 사실은 trace에
기록되며, §2.4의 스킵 레코드 하나를 남긴다.

**`otherwise` 항목이 있으면**(RFC-0060), 판정은 위와 같고 그 결과로 두 항목 중 정확히
하나가 실행된다. 전부 거짓이면 피가드 항목의 스킵 레코드를 남긴 **뒤** `otherwise`
항목을 실행한다. 하나라도 참이면 피가드 항목을 실행한 **뒤** `otherwise` 항목에 대한
`mode: "otherwise"` 스킵 레코드 하나를 남긴다. 조건은 어느 쪽이든 한 번만 판정한다 —
`otherwise`는 조건을 다시 평가하지 않는다. 가드가 읽는 참조는 그 가드에 도달한 시점의
값이다 — 앞선 스텝이 `set`/`format`으로 바꾼 필드면 바뀐 값을 읽는다(RFC-0060 §1).

#### 2.2 `until` 모드

조건이 참이 될 때까지 피가드 항목을 반복한다. 반복은 **두 경계에 의해 유계**된다:

1. **시간 경계**: 매 라운드 시작 전 `clock.now >= deadline`이면 중단 (workflow의
   `timeout`이 선언된 경우)
2. **라운드 경계**: `rounds >= _UNTIL_ROUND_CAP`이면 중단

`timeout` 미선언 시에도 라운드 상한은 그대로 `_UNTIL_ROUND_CAP`이다. 중단 사유를
구분하여 WARN에 남긴다:
- `reason="deadline"` — 시간 경계 도달
- `reason="round_cap"` — 라운드 상한 도달

**첫 평가가 이미 참이어서 한 라운드도 실행하지 않은 경우**(`rounds == 0`),
`when`의 거짓 분기와 **동형으로** trace에 기록하고 §2.4의 스킵 레코드 하나를
남긴다. 라운드가 1회 이상 실행된 경우에는 아무 레코드도 남기지 않는다 — 그 경우
건너뛴 것이 없기 때문이다. 이 대칭은 규범이다: 두 경로 모두 "선언된 스텝이
실행되지 않았다"는 같은 사실이므로, 하나만 관측 가능한 상태는 관측 불가능한
분기를 만든다.

#### 2.3 실행 의미 표

| mode | 종료 보장 | 설명 |
|------|----------|------|
| `when` | 자명 | 조건 1회 평가 후 분기(반복 없음) |
| `repeat` | 자명 | 선언된 `count` 횟수 반복(유한 상수) |
| `until` | 두 경계로 유계 | 조건 성립 또는 `timeout`/`_UNTIL_ROUND_CAP` 도달 시 중단 |

#### 2.4 스킵 레코드 (신설)

실행 결과는 **스킵 매니페스트**를 가진다. 피가드 항목을 실행하지 않은 가드마다, 그리고
가드가 참이어서 실행하지 않은 `otherwise` 항목마다(RFC-0060) 레코드가 하나씩, 만난
순서대로 들어간다.

| 필드 | 의미 |
|------|------|
| `guard` | 가드 노드의 IR id. 모드 A 전용 — 모드 간 비교에서 제외한다 |
| `mode` | `"when"` 또는 `"until"`. **갱신 (RFC-0060)**: `otherwise` 항목의 레코드는 `"otherwise"` |
| `condition` | **갱신**: 대안이 없으면 정규화된 조건 문자열 그대로(RFC-0008 §4 불변). 대안이 있으면 조건과 모든 대안을 소스 순서대로 `" or "`로 이어붙인 문자열 — `"input.channel == 1 or input.amount <= 100"`. 이 결합은 **표시/비교 전용**이며 `parse_condition`으로 재파싱되지 않는다(§Reference-level Specification/3). `mode: "otherwise"` 레코드에서는 **참이었던** 그 가드의 같은 문자열이다(RFC-0060) |
| `steps` | 그 레코드가 가리키는 항목(피가드 항목, 또는 `otherwise` 항목)이 감싼 **모든 WorkflowStep의 이름**, 선언 순서. 중첩 블록(`Concurrency`·`Pipeline`)까지 하강해 수집한다. 피가드 항목의 레코드는 `otherwise` 항목의 스텝을 담지 않는다(RFC-0060) |
| `rounds` | `when`·`otherwise`면 없음(`null`), `until` 0라운드면 `0` |
| `evaluations` | (issue #83, RFC-0014 원문 불변 필드) **갱신**: 대안이 있으면 조건 자신의 항들에 이어 각 대안의 항들도 소스 순서대로 같은 리스트에 담는다 — 어느 항이 어느 대안 소속인지는 이 리스트의 위치가 아니라 `ref`가 가리키는 값으로 읽는다(추가 태깅 없음, RFC-0014가 이미 "다섯 키는 불변"이라 적은 원칙을 존중해 `evaluations`의 원소 shape을 넓히지 않는다). **갱신 (RFC-0050)**: 숫자 형태 술어 항도 한 원소를 남긴다 — 존재 검사와 같은 모양으로 `{"ref": <필드>, "value": <해소한 값, 없으면 null>, "op": "is-numeric" 또는 "is-not-numeric", "expected": null, "holds": <판정>}`. `and` 안의 술어 항은 다른 항과 함께 소스 순서대로 담긴다. **갱신 (RFC-0060)**: `mode: "otherwise"` 레코드에서는 빈 배열이다 — 가드는 참이었고, 참인 판정의 항은 이 채널이 아니라 트레이스(§2.1)가 싣는다 |

`condition`의 결합 표기는 `restore_skips`(모드 B 재구성)와 `_skip_record`(모드
A 실측)가 **같은 함수**로 만든다 — 이름은 §Reference-level Specification/5가
고정한다. 두 모드가 각자 결합하면 공백 하나의 실수가 `differential.verify`를
거짓 양성/거짓 음성으로 만든다.

`steps`가 이름이고 id가 아닌 이유는 규범적이다. 모드 B의 관측 표면에는 IR 노드
id가 없으므로(`step <index> <name>` 라인만 존재), 노드 id로 키잉된 매니페스트는
모드 B가 **원리적으로 생산할 수 없다**. 두 모드가 같은 신호를 관측해야 한다는
RFC-0004의 요구가 shape을 결정한다.

**status 어휘는 변경되지 않는다.** terminal status는 `completed`와 `failed`
둘뿐이며, 스킵은 status와 직교하는 신호다. 특히 스킵은 검증 실패·저장소 실패와
**다른 결과 클래스**다 — 후자는 `failed`이고 `failed_at`을 가진다.

네트워크 결과 바인딩 필드(`paymentResult.status`, `paymentResult.<bodyKey>`,
§3의 평탄화된 값)는 가드 평가 트레이스(`evaluations`)에서 **마스킹되지
않는다** — 바디 필드에 토큰이나 카드번호 같은 sensitive 값이 담겨도 그대로
trace에 남는다는 뜻이다.

#### 2.5 진단과 종료 코드 (신설)

스킵 레코드마다 진단 하나를 낸다: 코드 `guard-skipped-steps`, severity
`warning`. 진단은 기존 진단 채널을 그대로 쓴다 — 새 레코드 타입·누산기·포매터를
만들지 않는다.

기본 실행의 종료 코드는 바뀌지 않는다(스킵이 있어도 `completed`는 rc 0). 엄격도는
호출자가 고른다: `--strict`를 준 실행에서만 진단을 보고한 클린 종료가 rc 2로
승격된다. 이는 기존 `--strict` 게이트의 재사용이며 새 종료 코드 규약이 아니다.

`스킵 진단`의 그레인 차이는 **의도된 것이다.** mode A는 어떤 가드가 어떤 스텝들을
소유하는지 알고 있어 가드당 한 건을 낸다. mode B의 관측 표면에는 가드가 없고 계획된
스텝만 있으므로, 가드 단위로 묶으면 갖고 있지 않은 정보를 발명하게 된다. 같은
이유로 mode B 진단의 `where`는 가드 노드 id가 아니라 **워크플로 id**다 — 그것이 mode
B가 정직하게 지목할 수 있는 가장 세밀한 노드 id다.

#### 2.6 모드 A/B 동등성 (신설)

두 모드는 스킵을 **같게** 관측해야 한다. 비교는 `guard`를 제외하고 스텝 단위로
편 투영 위에서 이루어진다 — `{mode, condition, step, rounds}`. 모드 A는 레코드
하나를 그 `steps` 수만큼의 항목으로 펴고, 모드 B는 "계획에 있으나 출력에 없는
스텝"으로 같은 항목을 복원한다.

`condition`이 대안을 포함한 결합
문자열일 때도 이 넷은 그대로 비교 대상이다 — §2.4가 두 모드에게 같은 결합
규칙을 강제하므로 새 비교 클래스나 새 필드가 필요 없다.

모드 B에서 대안 가드는 `arith.ori`로 각 대안의 `arith.cmpi` 결과를 접어
하나의 i1로 만든다(§Reference-level Specification/6). `until`은 대안 가드를
가질 수 없으므로(§Reference-level Specification/1), 이 접기는 `negate`
경로와 만나지 않는다 — RFC-0014 원문의 드모르간 우려(`and`의 `until` 부정)는
대안 가드에는 적용되지 않는다.

모드 B에서 `until`은 라운드 상한까지 언롤되지만, 조건은 실행 중 상수이므로 라운드
수는 0 아니면 상한이다. 따라서 **라운드 1의 부재만** 0라운드 스킵으로 센다.
라운드 2 이상의 부재는 정상 종료이며 항목을 만들지 않는다.

이 비교는 RFC-0069 §5가 이미 규정한 대로 RFC-0004의 **실행 순서 분류(1/4) 안에서**
수행한다. 새 비교 클래스를 만들지 않는다.

#### G12.1 이름 공간

조건 평가 시점의 이름 공간은 두 갈래이며, 갈래는 `Reference`의 **형태로** 결정된다.

| 형태 | 가리키는 것 |
|------|-------------|
| `CamelName` (bare) | 워크플로에 전달된 **입력 payload**의 필드 |
| `CamelName '.' CamelName` (한정) | `binding '.' field` — 바인딩된 **행**의 필드 |

#### G12.2 무엇이 바인딩되는가

이 실행에서 완료된 `RepositoryCall`은 그 `operation`에 따라, 완료된
`NetworkCall`은 `result` 필드의 유무에 따라 네 이름공간 중 하나에
바인딩을 남길 수 있다. 한 엔티티는 최대 단일 행 바인딩 1개 + RowSet
바인딩 1개를 동시에 가질 수 있다(RFC-0075 §5). 네트워크 결과 바인딩과
**생성 결과 바인딩**은 엔티티 자신의 바인딩 이름이 아닌, 저자가 이름
붙인 네 번째 이름공간이며, 단일 행 바인딩과 같은 문법 위치
(`<binding>.<field>`)를 쓴다 — 그래서 이름이 겹칠 수 없다는 것이
lowering 시점의 정적 거부다(RFC-0027 §2, §1로 확장).

`Aggregate`의 `Reference`(§2)는 언제나 RowSet
바인딩을 본다. 두 문법 위치가 겹치지 않으므로 충돌은 없다 — RFC-0012 §G12.3이
bare/한정 이름 사이에 이미 세운 것과 같은 "문법 형태가 가른다"는 원칙을 두
바인딩 종류 사이로 넓힌 것이다.

**단일 행 바인딩** (`operation == "read"`인 호출만 — `query`는 더는 여기 속하지
않는다.):

- **바인딩 이름**은 Entity의 선언 이름을 camelCase로 바꾼 것이다: `Product` →
  `product`. IR의 노드 id에서 유도하지 않는다.
- **마지막 쓰기가 이긴다.** 같은 Entity를 다시 `read`하면 바인딩이 갱신된다.

단일 행 바인딩의 **바인딩 값**은 "저장소가 그 read의 키 아래에서 돌려준 행"이다 —
`by <ref>`가 있는 read는 §3이 파생한 키 아래의 행을, 없는 read는 지금처럼 payload `id` 키
아래의 행을 바인딩한다.

**RowSet 바인딩** (`operation == "query"`인 호출만 — 이 RFC가 처음 도달시키는
경로, §Motivation 참조):

- **바인딩 이름**은 단일 행 바인딩과 같은 규칙(camelCase 선언 이름)이되, 별개
  이름 공간에 놓인다.
- **바인딩 값**은 드라이버의 `query(entity_id)`가 돌려준 행 리스트다(§7).
  드라이버가 행을 하나도 못 찾으면 빈 리스트다 — 부재가 아니라 **빈 RowSet**이며,
  §4의 규칙대로 그 위의 집계는 실패하지 않고 0을 낸다.
- **마지막 쓰기가 이긴다.** 같은 Entity를 다시 `list`하면 RowSet이 갱신된다.
- RowSet은 **읽기 전용 소비**다 — `<binding>.<field>` 형태의 단일 필드
  참조로도, 다른 쓰기 대상으로도 쓸 수 없다. 집계(§2)와, RFC-0059이 정한
  `respond`의 두 항 — 이름 붙인 집계 항과 목록 항 — 으로만 소비된다.

**네트워크 결과 바인딩** (`operation == "call"`이 아니라, 이 RFC가 처음
도달시키는 `NetworkCall.result` 필드가 있는 완료된 호출):

- **바인딩 이름**은 소스의 `as <name>`이 준 이름 그대로다 — Entity 선언에서
  유도하지 않는다(NetworkCall에는 대상 Entity가 없다).
- **바인딩 값**은 평탄화된 `{"status": <Integer>, **body}`다 — 응답 바디의
  최상위 키가 `status`와 같은 딕셔너리에 나란히 놓인다(`Reference`가 두
  조각까지만 받으므로, §Guide-level Explanation이 적은 대로 중첩된
  `body.<key>` 접근은 문법 밖이다). `<name>.status`, `<name>.<bodyKey>`로
  읽는다. `status`가 바디의 같은 이름 키보다 이긴다.
- **마지막 쓰기가 이긴다.** 같은 이름으로 다시 호출하면 갱신된다 — 단일 행
  바인딩과 같은 규칙, 다른 이름공간.
- **읽기 전용 소비**다 — 다른 쓰기 대상(`set`의 좌변)으로 쓸 수 없다.
  `NetworkCall`은 저장소에 쓰지 않으므로 `persist`할 행이 없다.
- `as` 없는 `call`/`request`는 어느 이름공간에도 바인딩하지 않는다 —
  RFC-0027 §3의 후방 호환 규칙 그대로다.

**생성 결과 바인딩** (`operation == "create"`이고, `result` 필드가 있는
완료된 `RepositoryCall` — `RepositoryCall.result`는 이 RFC가 처음
도달시킨다):

- **바인딩 이름**은 소스의 `as <name>`이 준 이름 그대로다 — Entity의
  선언 이름(camelCase)에서 유도하지 않는다(§1 ⓑ가 그 둘이 겹치는 것을
  이미 막는다).
- **바인딩 값**은 새로 만든 행이다 — 생성 시점에 payload의 동명 필드
  (`derived` 제외)를 초기값으로 복사한 것(§3). 단일 행 바인딩과 달리
  그 Entity의 **선언된 필드 형태를 그대로** 갖는다(네트워크 결과
  바인딩과 다른 점 — 응답 바디는 선언된 형태가 없다).
- **쓰기 가능**하다 — 네트워크 결과 바인딩과 달리 `set`/`format`의
  좌변이 될 수 있다(§4). 같은 이름으로 다시 `create ... as`를 쓰면
  갱신된다 — 마지막 쓰기가 이긴다는 같은 규칙, 다른 이름공간.
- `as` 없는 `create`/`insert`는 어느 이름공간에도 바인딩하지 않는다 —
  RFC-0027 §3의 후방 호환 규칙과 같은 모양.

`create`·`insert` 이외 — **`update`·`delete`는 여전히 바인딩하지
않는다** — RFC-0012 원문의 이유(영향 행 수만 돌려주므로 바인딩할 행
내용이 없다) 그대로다.

`update`/`delete`는 `by`가 있어도 바인딩하지 않는다.

#### G12.3 충돌 시 우선순위

**충돌이 존재하지 않는다.** bare 이름은 결코 바인딩으로 해석되지 않고, 한정 이름은 결코
payload로 해석되지 않는다. 분리는 우선순위 서열이 아니라 **문법 형태**로 이루어진다.

이 규정의 관측 가능한 결과: 이 RFC 이전에 작성된 프로그램은 조건이 전부 bare 형태이므로,
평가 결과가 하나도 달라지지 않는다.

두 Entity의 바인딩 이름이 같아질 수는 없다 — 선언 이름이 모듈 안에서 유일하기 때문이다.

#### G12.4 해석되지 않는 이름

값이 없을 때의 의미는 RFC-0008 이전부터의 동작과 같다. 네 경우 모두 **같은 한 규칙**을 따른다:
해석 결과가 없으면 `Presence`는 부재로, `Comparison`은 거짓으로 평가된다.

| 상황 | `exists` | `missing` | `Comparison` |
|------|----------|-----------|--------------|
| payload에 그 필드가 없다 | 거짓 | 참 | **거짓** |
| 바인딩이 아직 없다(읽기 전) | 거짓 | 참 | **거짓** |
| 바인딩은 있으나 행에 그 필드가 없다 | 거짓 | 참 | **거짓** |
| 값이 정수로 해석되지 않는다 | 거짓 | 참 | **실행 오류** |

마지막 행만 예외다: 비교 대상이 존재하는데 숫자가 아닌 것은 부재가 아니라 오류이며,
참조 구현은 필드 이름과 조건 문자열을 담은 실행 오류를 낸다.

`read`가 행을 찾지 못하면 그 스텝이 실패하므로 후속 가드에 도달하지 못한다. 이
RFC 이전에는 두 번째 행이 실제로 관측되는 경로가 `query`가 행을 찾지 못한 경우였다
— `query`도 그때는 단일 행 바인딩에 참여했기 때문이다(RFC-0012 원문 §G12.2). §5가
`query`를 그 이름 공간에서 빼고, §6.2(G12.5 ⓒ)가 `query`만 있고 `read`가 없는
엔티티로의 한정 참조 자체를 컴파일 거부로 막은 뒤로는, 그 경로가 더는 존재하지
않는다. 두 번째 행이 이제 실제로 관측되는 유일한 경로는 **읽기 전**이다 — 가드나
`expect`가 프로그램 순서상 그 엔티티의 `read`보다 앞서 있어서, 그 시점엔 아직
바인딩이 생기지 않은 경우(G12.5 ⓒ는 워크플로 **어딘가에** `read`가 있으면 만족되고,
그 `read`가 참조보다 뒤에 와도 된다).

#### G12.5 컴파일 시점 거부

한정 참조는 **문서를 읽을 수 있는 시점**(lowering)에 검사되며, 아래 셋 중 하나라도 어긋나면
컴파일이 실패한다. 셋 다 런타임까지 살아 나가지 않는다.

| # | 검사 | 어긋났을 때 |
|---|------|-------------|
| ⓐ | `binding`이 선언된 Entity의 바인딩 이름과 일치한다 | 컴파일 실패 |
| ⓑ | 그 Entity가 `field`를 선언한다 | 컴파일 실패 |
| ⓒ | 이 워크플로가 그 Entity를 `read`/`query`로 부르거나, `create ... as <binding>`으로 그 Entity의 행을 만든다. 조회 키 `by <binding>.<field>`도 같은 검사를 받는다 | 컴파일 실패 |

ⓒ가 없으면 바인딩이 결코 생기지 않는 참조가 G12.4의 "바인딩이 아직 없다"로 흡수되어
**조용히 거짓**이 된다. 평가할 수 없는 조건을 파스 시점에 거부한다는 RFC-0008의 판정을
한정 참조까지 넓힌 것이다.

`query`를 뺀 이유는 §5(G12.2)가 그 결과다 — `query`는 이제 단일 행이 아니라
RowSet을 바인딩하므로, `query`만 있고 `read`가 없는 워크플로에서 `<binding>.<field>`
한정 참조를 허용하면 결코 채워지지 않는 단일 행 바인딩을 조용히 참조하게 된다
(G12.4 "바인딩이 아직 없다"로 흡수돼 조용히 거짓이 되는데, 그 침묵이 §Motivation이
연 질문 — "죽은 경로가 틀린 채로 살아난다" — 을 반복한다). 이 갱신 전에는 `query`가
죽은 경로였으므로 ⓒ의 이 분기는 결코 참이 되지 않았다 — 관측 가능한 프로그램의
의미는 바뀌지 않는다. `read`(및 `authenticate`/`load`/`find`— 전부 `operation="read"`로
lower되는 동의어)만 있던 기존 프로그램의 컴파일 결과도 그대로다.

"쓰려면 먼저 읽어라"였던 유일한 해법에 "또는 만들면서 이름을
붙여라"가 더해진다 — G12.4의 "바인딩이 아직 없다"로 흡수되어 조용히
거짓이 되는 것을 막는다는 원래 취지(ⓒ가 없으면 벌어지는 일)는 그대로
지켜진다.

ⓒ는 **워크플로 전체의 멤버십**이다 — 그 읽기·생성이 참조보다 앞에 있는지는 보지 않는다.
참조보다 뒤에서 읽히는 바인딩(자기 참조 `find order by order.productId` 포함)은 컴파일을
통과하고, 그 스텝이 실행될 때 바인딩이 아직 없으면 §3의 명명된 `RunError`로 실패한다.

조회 키 고유 규칙(참조 형태별):

| 참조 | 판정 |
|------|------|
| bare 이름(`productId`) — payload 필드 | 허용, 실행 시점에 해석 |
| `input.<field>` | 필드가 어떤 Entity에 선언돼 있으면 허용(그 필드가 `derived`나 Password여도 — payload 값이다) |
| `caller.subject` / `caller.role` | 허용 |
| `call ... as <name>`의 `<name>.<field>` — 네트워크 결과 | 허용, 실행 시점에 해석(RFC-0027 §2) |
| `<binding>.<field>` — 선언된 비-`derived`, 비-Password 필드 | 허용(ⓒ 적용) |
| `<binding>.<field>` — `derived` 필드 | 거부 — 서버 계산 필드는 값이 믿을 만하게 있지 않다(RFC-0030 §3) |
| `<binding>.<field>` — base가 Password인 필드 | 거부 — 저장 키를 마스킹 필드로 만들 수 없다(issue #43의 마스킹 초크포인트) |

두 거부의 문구:

```
workflow <W>: lookup key '<ref>' names field '<f>', which is `derived` (server-computed, RFC-0030 §3) -- a row cannot be addressed by a field whose value is not reliably present
workflow <W>: lookup key '<ref>' has declared type <T>, whose base is Password -- a stored key must not be built from a masked field (issue #43's masking chokepoint, RFC-0052 §Static checks)
```

#### G12.6 모드 B

RFC-0004 §Execution modes의 네 관측 대상(실행 순서·정책 결과·관측 신호·마스킹)에서 두 모드가
일치해야 한다는 계약은 그대로다. 조건 필드 값은 모드 B에서도 **같은 스코프 규칙으로** 유도된다.

모드 B의 생성 모듈은 저장소 상태를 모델링하지 않는다(RFC-0004: 저장소 결과는 문서에서
유도 가능한 질문으로 답한다). 따라서 한정 참조의 값은 **호스트가 시드 규칙으로부터 정적으로
투영해** 주입한다. 시드 규칙으로 재현할 수 없는 행을 호출자가 모드 A에만 준 경우, 두 모드의
비교는 **수행되지 않고 거부된다** — 배선 차이를 모드 불일치로 보고하지 않기 위해서다.
이는 시드 조건이 어긋날 때 비교를 거부하는 기존 규정과 같은 처리다.

모드 B의 저장소 판정(read가 행을 찾는가, create가 충돌하는가)은 "한 실행은 payload
하나를 가지므로 엔티티 E의 모든 호출이 같은 키를 가리킨다"는 단일 키 투영에 기댄다.
조회 키(RFC-0052)는 그 투영을 깨므로, 워크플로 안의 어떤 `RepositoryCall`이든
`lookup`을 가지면 모드 B는 그 워크플로를 **빌드하지 않는다** — MLIR을 내기 전에
`BackendError`로 거부한다:

```
step <step>: <entity_id> uses a lookup key (by <ref>), which the single-key seed projection cannot model (RFC-0052 §Mode B) — run it in mode A
```

`lnpl build --backend`와 `lnpl diff`는 이를 `backend error: …`(rc=4)로 보고한다.
차동 하네스(`differential.verify`)는 툴체인 확인 **전에** 같은 워크플로를
`DifferentialError`(기록된 예외, RFC-0052 §Mode B)로 거부한다 — 비교를 수행하지 않으며
거짓 EQUIVALENT를 내지 않는다. `by`가 없는 워크플로의 모드 B 동작은 바뀌지 않는다.

#### G12.7 `spec … expect` 어휘

`expect`는 가드와 **같은 스코프**를 읽는다. 어휘는 닫혀 있고, 평가할 수 없는 기대는
조용한 통과가 아니라 오류다. 기존 7종(`completed` `failed` `steps` `slo` `duration`
`cache` `attempts`)의 의미는 이 RFC가 바꾸지 않는다.

| 단언 대상 | 형태 | 읽는 것 |
|-----------|------|---------|
| 반환값 | `result <Reference> <op> <value>` / `result <Reference> exists\|missing` | G12.1의 이름 공간. 문법도 평가기도 가드의 것을 그대로 쓴다 |
| 엔티티 상태 | `rows <Entity> <N>` | 실행 후 저장소의 행 수 |
| 이벤트 | `emitted <Event>` / `emitted <Event> count <N>` / `emitted <Event> payload <field> exists\|missing` | 아웃박스 |
| 실패 | `error step <name…>` / `error reason <substring…>` | 실패한 스텝과 사유 |
| 효과 | `effects <N>` / `effects complete` | 실행된 각 스텝이 수행한 Effect |

키가 `entity`/`event`가 **아닌** 이유: 둘 다 최상위 선언 키워드(`lexer.KEYWORDS_TOP`)라
`expect` 줄 첫 토큰으로 쓰면 파서가 선언으로 읽는다. 그래서 `rows`/`emitted`다.

**`effects complete`** — 이 실행에서 **실행된 모든 스텝이 Effect를 최소 하나 수행했다**.
이슈 #39의 두 번째 수용 기준이다. `VERB_LEXICON` 밖의 동사는 Effect를 유도하지 않으므로
(이슈 #36) 그 스텝은 실행되고 아무것도 하지 않는데, `expect steps N`은 그것까지 세고
통과한다 — 구현이 비어 있는데 spec이 초록인 상태다. 이 형태가 그것을 빨갛게 만들고,
아무 일도 하지 않은 스텝의 이름을 보고한다.

**자동이 아니라 명시(opt-in)다.** 서술용 스텝은 LNPL을 쓰는 정당한 방법이며
(`diagnostics.py`가 그렇게 기록한다), 골든 `examples/login.lnpl`이 세 개를 쓴다
(`generate token`·`audit login`·`return token`). `unknown-verb` 진단이 있는 모든 모듈의
spec을 자동으로 실패시키면 **골든 시나리오 자체를 거부**하게 된다. 그래서 저자가 그 보증을
의도하는 곳에서 직접 적는다.

**범위는 이 실행이 수행한 것이다.** 닫힌 가드 아래의 no-op 스텝은 실행되지 않았으므로
여기서 세지 않는다. 그 경우를 보고하는 것은 컴파일 시점의 `unknown-verb` 진단이며,
`lnpl spec`이 이제 그것을 출력한다(이전에는 `compile`·`run`만 출력했다 — 검증이 본업인
명령이 유일하게 침묵했다).

RFC-0066의 `Guard` 노드(2026-07-31 신설)는 피가드 항목 하나를 감싸며, `mode`에 따라
실행 의미가 갈린다. 세 모드 모두 **피가드 항목의 실행 여부·횟수만** 바꾸고, 그 항목
자체의 의미(step의 Effect, 블록의 구조)는 건드리지 않는다.

**`repeat`와 `Policy.retry`는 다르다.** `repeat N`은 성공하든 실패하든 N회 실행하는
선언이고, `retry N`은 실패한 step을 최대 N회 다시 시도하는 정책이다. 하나를 다른
하나로 접으면 IR의 의미가 왜곡된다(RFC-0067 부록 A.2 P10).

**조건식의 표현력.** `condition`의 문법은 RFC-0002 Open Questions ②가 소유한다. 런타임
계약은 "평가할 수 없는 조건은 **거부한다**"는 것뿐이다 — 참으로 간주하고 진행하면
선언된 가드가 조용히 사라지고, 거짓으로 간주하면 선언된 작업이 조용히 사라진다. 어느
쪽도 관측 가능한 실패보다 나쁘다.

### Policy Enforcement

Constraint 노드(RFC-0066: Policy·Security·Performance)의 런타임 의미.
Security의 `mechanisms`는 컴파일러가 구현을 선택하는 입력이며(CHARTER §핵심
철학 2), 런타임 계약으로는 Authorization 게이트(위 표)와 §Observability의
마스킹 의무가 해당한다. Policy·Performance의 집행 계약은 다음 표와 같다.

| 항목 | 런타임 의미(계약) |
|------|------------------|
| `Policy.retry N` | 실패한 **step**의 재실행. 최대 N회 재시도(초기 시도는 별도 — `retry 3` = 실패 후 최대 3회 더 시도). 대기는 capped exponential backoff + full jitter. 재시도는 2중 게이트를 모두 통과할 때만: ① step이 소유한 Effect 전부가 아래 멱등 판정 표에서 멱등 ② 실패 유형이 아래 실패 유형 표에서 재시도 가능. 모든 재시도는 `Policy.timeout`의 잔여 데드라인 안에서만 수행한다 |
| `Policy.rollback` | 실패 시 보상의 경계는 **Transaction 노드**다(§Execution Model Transaction 행). Phase 1은 이 노드를 선언할 문법이 없으므로, 그 공백 동안은 워크플로 실행 전체가 유일한 경계다: 실행이 실패로 종결하면(재시도 소진, 데드라인 초과, 또는 step 순회 자체를 중단시키는 구성 오류를 포함해 `status`가 `failed`로 확정되거나 예외가 전파되는 모든 경로) 그 실행에서 커밋되지 않은 모든 쓰기가 롤백된다 — 그리고 경계가 실행 전체이므로 "이미 커밋된 선행 Transaction"은 존재할 수 없다(있었다면 그것은 이전 실행이 커밋한 데이터이고, 이번 rollback의 대상이 아니다). 명시적 `Transaction` 노드가 도입되면 한 워크플로 안에 여러 개가 존재할 수 있고, 그때는 원래 서술대로 진행 중이던 것만 abort, 이미 커밋된 선행 Transaction들은 역순 보상 대상이 된다. Transaction 경계(현재는 실행 전체) 밖의 Effect(예: 외부 NetworkCall)는 여전히 자동 보상이 불가하다 — rollback이 보장하는 범위는 그 경계까지이며, 그 밖의 보상은 계약하지 않는다(한계는 §Open Questions ③과 연결) |
| `Policy.timeout T` | workflow 실행 전체의 데드라인. 실행 시작 시각에 기산하고, 모든 하위 Effect 호출에 **잔여 데드라인을 전파**한다(호출받은 쪽은 잔여 시간을 자신의 타임아웃 상한으로 삼는다). 초과 시: in-flight Effect에 취소를 전파하고(아무도 읽지 않을 일을 계속하지 않는다), actor 메일박스의 해당 실행 작업을 폐기하며, workflow는 `TimedOut` 실패로 종결한다 |
| `Policy.parallel N` | `parallel` 블록의 동시성 상한(§Execution Model Concurrency 문단). 선언값 N이 있으면 그 블록의 동시 실행 스텝 수는 N을 넘지 않는다 — 없으면 상한은 그 블록의 브랜치 수(자연 상한, 병목 없음). 블록 하나가 스코프다: 실행기는 블록 시작 시 만들어지고 병합 지점 통과 전에 반드시 종료한다(고아 작업 금지, §Execution Model ④). 한 브랜치가 실패하면 아직 시작하지 않은 형제 브랜치는 취소되고, 이미 시작한 브랜치는 자신의 현재 시도가 끝날 때까지 진행한 뒤 합류한다(재시도가 있는 브랜치는 **다음** 재시도부터 중단 — 스레드는 강제 종료할 수 없다). 보고는 완료 순서가 아니라 **선언 순서**다 — 병합 후 일괄 기록되므로 `steps <N>`은 순차 실행이었을 때와 같은 모양이다. `Policy.timeout`의 잔여 데드라인은 블록 전체에도 적용된다: 블록의 스텝들이 성공적으로 끝났어도 그 시점에 데드라인을 이미 넘겼으면 그 실행은 여전히 `TimedOut`으로 종결한다 |
| `Performance.cache T` | 해당 workflow의 CacheAccess `set`에 적용되는 TTL 예산. TTL의 소유권은 Performance 제약에 있다(RFC-0066 CacheAccess 행 — 중복 지정 금지). 런타임 계약: TTL 없는 `set`은 금지된다 — 모든 key는 TTL을 가진다(무효화가 유실돼도 TTL이 백스톱) |
| `Performance.response X` | **SLO 선언이다 — 집행 대상이 아니다.** 런타임은 초과 요청을 차단하지 않는다(유효한 요청을 자기 손으로 실패시키는 것은 SLO 개선이 아니다). 대신 계측·경보한다: step/workflow duration histogram의 **p50/p95/p99**를 SLO와 비교하고 위반 시 경보를 발화한다. 평균 단독 비교는 금지 — 평균은 사용자가 실제로 겪는 꼬리 지연을 가린다 |

**retry 시도 상한.** `retry N`이 선언한 예산과 **무관한 절대 상한**이 하나 더
있다: 한 step의 총 시도 횟수(초기 시도 포함)는 **100회**를 넘지 않는다. 이 상한은
`retry` 값을 읽지 않고 판정하며, `retry`보다 **먼저** 평가된다. 따라서 관측 가능한
시도 횟수는 `min(retry + 1, 100)`이다.

상한이 하나뿐인 재시도 루프는 그 하나를 잃는 순간 실패가 아니라 **무한 루프**가
된다(`kb/antipatterns/antipatterns-unbounded-retry.md`). 위 `Policy.timeout`의
데드라인은 이 자리를 대신하지 못한다 — `timeout`을 선언하지 않은 service에는
데드라인이 없고, 그러면 남는 상한이 `retry` 하나뿐이기 때문이다.

`retry`를 100 이상으로 선언하는 것은 지원되는 모드가 아니라 **설정 오류다.**
선언한 만큼 재시도되지 않으며, 런타임은 이를 진단하지 않고 100에서 멈춘다.
유효한 설정은 이 상한에 닿지 않는다 — 이 레포 전체에서 가장 큰 `retry` 선언은
5이고, 실제 재시도 예산은 2~3회를 쓴다. 상한은 정책이 아니라 백스톱이다.

상한은 **두 실행 모드 모두**에 있다(RFC-0004 §실행 모드와 semantic equivalence의
관측 대상 2 "정책 집행 결과 — retry 판정"). 어느 한쪽에만 두면 `retry >= 100`에서
두 모드의 시도 횟수가 갈리고 `lnpl diff`가 `DIVERGENT`를 보고한다.

**retry 멱등 판정 기준.** 어떤 Effect가 멱등인가의 정의: *동일 Effect를 2회
실행한 최종 상태와 외부에서 관측 가능한 부수효과가 1회 실행과 같으면 멱등이다.*
타임아웃된 요청은 실제로는 실행되었을 수 있으므로, 이 기준을 통과하지 못하는
Effect의 재전송은 부수효과를 복제한다. kind×operation 판정 표:

| Effect kind | operation | 멱등 판정 |
|-------------|-----------|----------|
| RepositoryCall | `read`, `query` | 멱등 — 상태를 바꾸지 않는다 |
| RepositoryCall | `delete` | 멱등 — 이미 삭제된 대상의 재삭제는 부수효과가 없다 |
| RepositoryCall | `update` | 절대값 쓰기(full replace)만 멱등. 상대 연산(증분·누적)은 비멱등 |
| RepositoryCall | `create` | 비멱등 — 멱등키가 선언된 경우에만 재시도 가능(키 저장·응답 재생 계약은 RFC-0006의 멱등키 규정과 정렬) |
| CacheAccess | `get`, `set`, `invalidate` | 멱등 — get은 무부수효과, set은 절대 상태 쓰기(last-write-wins), invalidate는 삭제 |
| NetworkCall | (operation별) | operation이 멱등으로 선언되었거나 멱등키를 전파하는 경우에만 멱등 취급. 선언 없는 NetworkCall은 비멱등으로 간주한다 |
| Authorization | — | 검사 자체는 멱등(무부수효과). 단 거부는 재시도 대상이 아니다(위 표) |
| EventEmit | — | event id 기반 dedupe가 가능한 조건에서만 멱등 취급(at-least-once 전제) |
| Transaction | — | children 전부가 멱등일 때만 스코프 단위 재시도 가능 |

**실패 유형별 재시도 판정.** 멱등 게이트를 통과했더라도 실패 유형이 재시도를
허용해야 한다:

| 실패 유형 | 판정 |
|-----------|------|
| 도달 전 실패(connection refused, connect timeout) | 재시도 — 요청이 핸들러에 도달하지 않았다 |
| 전송 후 무응답(request timeout) | 멱등 게이트 통과 시에만 재시도 — 요청은 실행되었을 수 있다 |
| 일시 오류 응답(5xx류, 과부하 신호) | 재시도 예산 내에서 재시도, 반복 실패 시 실패 확정 |
| 요청 자체의 오류(4xx류, Authorization 거부, Validation 실패) | 재시도 금지 — 같은 요청은 다시 보내도 같은 결과다 |

### Memory Model

개발자는 메모리를 다루지 않는다(CHARTER §Memory Model — Stack/Heap/Arena/
Pool은 컴파일러가 자동 선택). 이 절은 그 선택이 전제할 수 있도록 **런타임이
제공해야 하는 프리미티브 2종의 계약만** 정의한다. **어떤 값을 어느 배치로
보낼지의 선택 알고리즘은 RFC-0004 소유다** — 이 문서는 관여하지 않는다.

| 프리미티브 | 계약 |
|-----------|------|
| **arena** | workflow 실행 1회당 하나 생성된다. 수명 = **workflow 실행 수명**: 실행 시작 시 생성되고, 실행 종결 시 — 성공·실패·취소를 불문하고 — 일괄 해제된다. step 사이를 흐르는 중간 데이터의 기본 거처이며, 개별 해제·GC 추적이 없다(CHARTER §Runtime "GC 최소화"의 이행 수단) |
| **pool** | capability 커넥션(postgres·redis 등) 전용 자원 풀. ① 크기는 다운스트림 용량 기준으로 정한다 — 유입 부하 기준이 아니다(다운스트림 용량을 넘는 커넥션은 대기열을 다운스트림 안으로 옮겨 처리량을 낮춘다). ② bounded — 고갈 시 무한 대기가 아니라 fail-fast로 거부한다(무한 대기열은 피크 시점의 메모리 붕괴를 유예한 것일 뿐이다). ③ 획득은 operation당 1회, 다른 자원 획득 전 반환 — 중첩 획득 금지(§Execution Model RepositoryCall 행과 동일 규칙) |

| **transfer** | arena 수명을 넘겨 생존해야 하는 값 전용. **선언된 이전 경계에서만 생성된다** — 현재 두 곳뿐이다: EventEmit의 페이로드, workflow의 반환값. 참조 카운트로 관리하며 마지막 참조가 사라질 때 해제된다. GC 스캔은 없다(CHARTER §Runtime "GC 최소화"). 이전 경계 밖에서 arena를 탈출하는 값은 문법적으로 만들 수 없으므로, 탈출 분석의 판정은 "이 값이 선언된 이전 경계를 지나는가"라는 이진 질문으로 축소된다 |

세 계약이 있으면 컴파일러는 "step 간 전달 값은 arena, capability I/O는 pool,
이전 경계를 지나는 값은 transfer"라는 전제 위에서 Stack 승격·탈출 분석을
수행할 수 있다. 그 결정 자체(escape analysis, 배치 선택)는 RFC-0004의 최적화
패스가 소유한다.

> **transfer는 2026-07-31 개정으로 추가됐다**(교차 정합성 C8 — `docs/CONSISTENCY-CHECK.md`).
> 그 전까지 이 절은 arena·pool 2종만 정의했는데 RFC-0004는 배치 대상으로 Heap을
> 선택하고 있었다 — 즉 arena 수명을 넘기는 값의 할당·해제 책임이 어느 RFC에도
> 없었다. `transfer`가 RFC-0004의 Heap 행에 대응하는 런타임 계약이다.

### Observability

모든 workflow 실행은 추가 코드 없이 다음을 자동 생성한다(CHARTER
§Observability, plan.md D12). 이 절 전체가 두 실행 모드 공통 의무다.

**Trace.** workflow 실행 1회 = trace 1개, step = span. span의 부모-자식
관계는 IR의 `children` 소유 구조를 그대로 따른다(Concurrency 브랜치는 병렬
형제 span). Effect는 소유 step span의 하위 span으로 기록된다.

**상관ID.** 진입점(edge)에서 요청의 상관ID를 수용하고, 없으면 생성한다.
이후 모든 하위 Effect 호출(NetworkCall·RepositoryCall·CacheAccess·EventEmit)과
모든 로그 라인에 자동 전파·포함된다. 사건 조사는 이 ID 하나로 trace·로그를
관통한다.

**메트릭.** step duration histogram을 기본 생성한다 — p50/p95/p99 백분위로
조회 가능해야 한다(`Performance.response` SLO 비교의 원천). 메트릭 라벨은
다음 **허용 목록 5개만** 사용한다:

```
module / service / workflow / step / kind
```

다섯 라벨의 값은 전부 IR 선언에서 오는 유한 집합이다. **무한 카디널리티 값은
라벨로 금지한다** — 사용자ID, UUID, 이메일, raw URL이 대표적 금지 예다. 유일한
값 하나가 시계열 하나를 만들므로, 사용자ID를 라벨에 넣는 순간 시계열 수가
사용자 수만큼 폭발한다. per-user 조사가 필요하면 사용자ID는 **로그 라인과
trace attribute에** 넣고 메트릭은 집계로 유지한 뒤, 상관ID로 join한다.

**로그.** 구조화 JSON, UTC 타임스탬프, 상관ID 필수 포함. 레벨 의미론: ERROR는
"사람이 봐야 한다"는 뜻으로 예약한다 — 예상된 비즈니스 거부(검증 실패, 인가
거부)는 INFO/WARN이다. 전부가 ERROR면 ERROR 신호는 소음이 된다.

**Password/Secret 자동 마스킹.** RFC-0001 Password 타입의 "로그·직렬화·에러
메시지 노출 금지(마스킹 의무 — 런타임 계약은 RFC-0003)" 위임의 이행:
Password(및 Security 제약이 `encrypt <field>`로 지정한 secret) 값은 로그·trace
attribute·에러 메시지·직렬화 출력에서 런타임이 자동 마스킹한다. 마스킹 지점은
**중앙 1곳** — 로거/직렬화 파이프라인의 serializer 필터 — 이며, 콜사이트별
수동 마스킹은 계약 위반이다(콜사이트는 잊힌다; 중앙 초크포인트는 잊힐 수 없다).

## Examples

골든 시나리오 "Login"을 사용한다(정본: `plans/rfc-suite/plan.md` §골든 시나리오
— RFC-0000 §5에 따라 참조만 하고 재정의하지 않는다). 노드 id는 RFC-0066
Examples의 IR 표를 그대로 인용한다: `wf.login.step.1`~`.6`, `policy.login`
(retry 3, rollback, timeout 3s), `perf.login`(response < 50ms, cache 5m).

### 타임라인 A — 첫 실행 (캐시 **미적중** 경로, retry 1회 발생)

상관ID `cid-7f3a`는 edge에서 생성되어 전 span·로그에 전파된다.
`policy.login`의 `timeout 3s` = 데드라인 3000ms, 시작 시각 기산. 각 step에
잔여 데드라인이 전파된다.

```
trace tr-001  (workflow=login, cid-7f3a, deadline 3000ms)
└── span wf.login                        [   0 → 45ms]
    ├── span wf.login.step.1  "validate input"   [ 0 →  2ms]  잔여 3000ms
    │   └── Validation(entity.user.email, rule=Email) → pass
    ├── span wf.login.step.2  "authenticate"     [ 2 → 30ms]  잔여 2998ms
    │   ├── RepositoryCall(entity.user, read) 시도 1 → connection refused
    │   │     판정: 도달 전 실패 + read=멱등 → 재시도 허용 (retry 1/3)
    │   ├── backoff+jitter 7ms 대기 (잔여 데드라인 2989ms 내)
    │   └── RepositoryCall 시도 2 → 성공  [pool(cap.postgres) 획득→반환]
    ├── span wf.login.step.3  "cache user"       [30 → 33ms]  잔여 2970ms
    │   └── CacheAccess(set, key="user:{id}") — 키 부재(미적중 상태에서의 신규
    │         기록), TTL=5m ← perf.login의 cache 예산이 소유
    ├── span wf.login.step.4  "generate token"   [33 → 40ms]  잔여 2967ms
    ├── span wf.login.step.5  "audit login"      [40 → 43ms]  잔여 2960ms
    └── span wf.login.step.6  "return token"     [43 → 45ms]  잔여 2957ms
```

- 총 45ms. `perf.login`의 `response < 50ms`는 **집행되지 않는다** — 이 실행이
  55ms였어도 차단되지 않았을 것이다. 대신 step duration histogram에 적재되어
  p95가 50ms를 넘으면 경보가 발화한다(계측·경보 대상, §Policy Enforcement).
- 로그 라인 예(step 2, 구조화 JSON — password 자동 마스킹):

```json
{"ts":"2026-07-28T06:55:01Z","level":"INFO","cid":"cid-7f3a",
 "workflow":"login","step":"authenticate","kind":"RepositoryCall",
 "msg":"retry 1/3 after connection refused",
 "user":{"id":"018f3a2e-…","password":"****"}}
```

user의 id는 per-user 조사를 위해 로그 라인에 두는 것이 허용 경로다(라벨 금지와
구분 — §Observability). password는 중앙 serializer 필터가 자동 마스킹했다.

- 메트릭 라벨은 `module/service/workflow/step/kind`뿐이다. `cid-7f3a`나 user의
  UUID는 라벨이 아니라 위 로그·trace attribute에만 있다(카디널리티 계약).

### 타임라인 B — 5분 내 재실행 (캐시 **적중** 경로)

동일 workflow가 TTL(5m) 내에 다시 실행되면, step 3의 key `user:{id}`가
살아있다:

```
trace tr-002  (workflow=login, cid-9c21, deadline 3000ms)
└── span wf.login                        [   0 → 39ms]
    ├── step.1  validate input           [ 0 →  2ms]
    ├── step.2  authenticate             [ 2 → 27ms]  (재시도 없음)
    ├── step.3  cache user               [27 → 28ms]
    │   └── CacheAccess(set, key="user:{id}") — 키 생존(적중): 동일 값 확인 후
    │         TTL 갱신(재기록 생략). miss 경로(타임라인 A)와 달리 원천 재기록
    │         비용이 없다
    ├── step.4~6                         [28 → 39ms]
```

적중/미적중은 오류가 아니라 두 정상 경로이며, 차이는 span duration과
`kind=CacheAccess` 메트릭으로 관측된다.

### 타임라인 C — 재시도 소진과 rollback

step 2의 postgres가 계속 불가용하면:

```
trace tr-003  (workflow=login, cid-e08d, deadline 3000ms)
└── span wf.login                        [ 0 → 388ms]  status=Failed
    ├── step.1  validate input           → pass
    └── step.2  authenticate
        ├── 시도 1~4 (초기 1 + retry 3/3, 매회 connection refused,
        │    backoff+jitter — 전부 잔여 데드라인 내)
        ├── retry 소진 → step 실패
        └── policy.login rollback 평가:
              보상 경계 = 워크플로 실행 전체(RFC-0032 — Phase 1은 명시적
              Transaction 노드를 선언할 문법이 없다). driver.rollback()이
              실제로 호출된다. Login IR의 step 1(validate)은 쓰기가 없고
              step 2(authenticate)는 read만 시도했으므로, 이 실행이 커밋한
              쓰기는 애초에 없다 — 되돌릴 것이 없을 뿐, rollback이 no-op으로
              "정의돼서" 그런 것이 아니다. 쓰기가 있는
              워크플로라면(RFC-0032 §Reference-level Specification 참조,
              `impl/tests/test_transactions.py`가 두 번째 쓰기가 실패하는
              변형을 정확히 이 방식으로 검증한다) 첫 번째 쓰기도 이번
              rollback으로 함께 사라졌을 것이다.
```

- workflow는 `Failed`로 종결, 원인(connection refused ×4)이 보존된다.
- `policy.login`이 `rollback`을 선언했고 실행이 실패로 끝났으므로, trace에
  `INFO` 로그 한 줄이 추가된다: "rollback: execution boundary rolled back,
  writes made during this run are discarded"(§실행 경계).
- ERROR 로그 1건 발화 — 사람이 봐야 하는 상황이다(의존성 불가용). 시도별
  중간 실패는 WARN이다(레벨 의미론).
- 만약 backoff 대기 중 잔여 데드라인이 먼저 소진되면 재시도는 중단되고
  in-flight 호출에 취소가 전파되며 workflow는 `TimedOut`으로 종결한다
  (`timeout 3s`의 취소 전파 계약).

세 타임라인으로 `policy.login`·`perf.login`의 5개 항목 전부 — `retry 3`
(A: 1회 소비, C: 소진), `rollback`(C), `timeout 3s`(A·B·C의 데드라인
전파, C의 소진 분기), `response < 50ms`(A의 SLO 계측), `cache 5m`(A 미적중
set, B 적중) — 의 런타임 의미가 나타난다.

## Alternatives

1. **thread/lock API 노출** — 기각. CHARTER §Concurrency가 "Thread를 직접
   다루지 않는다"를 명시한다. 스레드를 노출하는 순간 데이터 레이스·데드락이
   개발자 책임이 되고, actor 직렬화·structured concurrency가 주는 구조적
   안전이 우회 가능해진다.
2. **`Performance.response`의 런타임 강제(초과 시 요청 차단)** — 기각.
   데드라인을 넘겼다고 유효한 요청을 자기 손으로 실패시키는 것은 SLO를
   개선하지 않고 오류율만 높인다. response는 계측·경보 대상이며, 강제 종료가
   필요한 상한은 별도 선언인 `Policy.timeout`이 담당한다 — 두 제약의 역할
   분리가 이 설계의 요점이다.
3. **GC 전면 의존 메모리 관리** — 기각. CHARTER §Runtime이 "GC 최소화"를
   목표로 명시한다. workflow 실행 수명에 정렬된 arena 일괄 해제 + capability
   pool 계약이 추적식 GC의 자리를 대체하며, 나머지 배치 결정은 RFC-0004의
   컴파일러 분석이 담당한다.
4. **unstructured concurrency(fire-and-forget 브랜치)** — 기각. 병합 지점
   없는 브랜치는 실패·취소가 부모에 전파되지 않아 조용히 유실되는 부수효과를
   만든다. Concurrency 노드의 IR 구조(배열 끝 = 병합 지점)가 이미 structured
   형태이므로, 런타임도 그 구조 그대로를 집행한다.

## Open Questions

1. **actor 메일박스 백프레셔** — 메일박스는 bounded여야 하는가, 가득 찼을 때
   거부 응답의 형태(즉시 실패 vs 대기 상한)는 무엇인가. pool의 fail-fast
   계약과 정렬이 필요하다.
2. **분산 actor** — 멀티 노드 배포에서 service 인스턴스(actor)의 배치·라우팅·
   위치 투명성. 이 문서의 actor 계약은 단일 노드 관점만 규정했다.
3. **EventEmit 전달 보장의 구현** — "Transaction 커밋 후 발행 + at-least-once"
   계약을 무엇으로 구현하는가(transactional outbox 채택 여부, 발행 실패 시
   재발행 책임). 계약만 이 RFC가 소유하고 구현은 미결이다.
4. **캐시 스탬피드 보호** — 만료 동시 재계산(thundering herd)에 대한
   single-flight / stale-while-revalidate를 런타임 기본 계약에 포함할지,
   capability 구현 선택에 맡길지.

# RFC-0003: Runtime

## Status

- Status: Accepted (2026-07-31) <!-- Draft | Review | Accepted | Superseded -->
- Updated-by: RFC-0008 (§Guard)
- Updated-by: RFC-0012 (§Guard)

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

**Workflow step = await 지점.** Workflow의 `children` 배열 순서(RFC-0001
구조 규칙 3)가 실행 순서다. 각 step은 자신이 소유한 Effect가 완료되어야
종결되고, 다음 step은 선행 step 종결 후에 시작한다. step 경계가 곧 유일한
await 지점이므로, 실행 타임라인은 IR에서 정적으로 읽힌다.

**Concurrency(mode=parallel) = structured concurrency.** 각 child는 병렬
브랜치이고 children 배열의 끝이 병합 지점이다(RFC-0001 Concurrency 행).
계약: ① 전 브랜치가 완료되어야 병합 지점을 통과한다(기본 merge = 전 브랜치
완료 대기). ② 한 브랜치가 실패하면 형제 브랜치에 취소를 전파하고, 전 브랜치
종결 후 부모로 실패를 전파한다. ③ 부모의 취소(데드라인 초과 포함)는 전
브랜치로 전파된다. ④ 브랜치는 병합 지점을 넘어 생존할 수 없다 — 고아 작업
금지.

**Effect 실행 의미.** Effect 대분류 6종 전부의 계약은 다음 표와 같다.

| Effect kind | 실행 의미(계약) |
|-------------|----------------|
| NetworkCall | 비동기 아웃바운드 호출 = await 지점. 모든 호출에 명시적 connect timeout + request timeout 필수 — 무한 기본값 금지(타임아웃 없는 호출 하나가 pool을 고갈시킨다). 잔여 데드라인과 상관ID를 자동 전파한다. 실패 유형별 재시도 판정은 §Policy Enforcement의 표를 따른다 |
| RepositoryCall | capability 커넥션 pool을 통해 실행되는 await 지점. 커넥션 획득은 operation당 1회이며, 다른 pool 자원을 획득하기 전에 반환해야 한다(같은 pool에 대한 중첩 획득은 pool 만석 시점에 데드락 — 금지). operation별 멱등성은 §Policy Enforcement의 판정 표를 따른다 |
| CacheAccess | `get` = miss가 오류가 아니라 정상 경로인 조회(miss 시 원천 조회로 폴백). `set` = TTL 필수 — TTL 값은 Performance 제약의 `cache` 예산이 소유한다(RFC-0001 CacheAccess 행). `invalidate` = 삭제. 캐시는 성능 계층일 뿐 정합성 메커니즘이 아니다 — 캐시 불가용 시 원천으로 폴백하되 동시성 상한 안에서만(무제한 폴백 herd는 캐시 장애를 원천 장애로 만든다) |
| Transaction | 원자적 스코프 노드: children 전부 성공 시 커밋, 하나라도 실패 시 abort — 부분 쓰기는 관측되지 않는다. `isolation` 서술은 힌트이며 집행 수준은 해당 capability가 결정한다. Policy `rollback`의 보상 경계가 이 노드다(§Policy Enforcement) |
| Authorization | 소유 step의 다른 Effect보다 먼저 평가되는 게이트. **거부(deny)는 비재시도 실패다** — 같은 요청은 다시 보내도 같은 결과이므로 재시도 대상이 아니다. 검사 서비스 불가용(전송 실패)과 거부는 구분되며, 전자만 재시도 판정 대상이다 |
| EventEmit | 비동기 발행 — step의 동기 구간은 발행 요청 등록까지다. Transaction의 children으로 소유된 EventEmit은 **커밋 성공 후에만** 발행된다(롤백된 트랜잭션의 이벤트 유출 금지). 전달 보장은 at-least-once이며, 소비자가 event id로 dedupe할 수 있도록 발행마다 유일한 event id를 부여한다(발행 메커니즘의 구현은 §Open Questions ③) |

### Guard

> 갱신됨: RFC-0008

RFC-0001의 `Guard` 노드(2026-07-31 신설)는 피가드 항목 하나를 감싸며, `mode`에 따라
실행 의미가 갈린다. 세 모드 모두 **피가드 항목의 실행 여부·횟수만** 바꾸고, 그 항목
자체의 의미(step의 Effect, 블록의 구조)는 건드리지 않는다.

| mode | 실행 의미 | 종료 보장 |
|------|----------|-----------|
| `when` | `condition`을 **1회** 평가한다. 참이면 피가드 항목을 실행하고, 거짓이면 건너뛴다(건너뛴 사실은 trace에 남긴다 — 조용한 생략은 관측 불가능한 분기를 만든다) | 자명(반복 없음) |
| `repeat` | 피가드 항목을 `count`회 실행한다. `count`는 1 이상 정수이며 런타임이 아니라 선언에서 온다 | 자명(유한 상수) |
| `until` | `condition`이 성립할 때까지 피가드 항목을 반복한다. 첫 평가가 이미 참이면 한 번도 실행하지 않는다 | **두 경계로 유계**: ① workflow 데드라인(§Policy Enforcement `timeout`) ② 라운드 상한. 어느 쪽이든 먼저 닿으면 반복을 중단하고 그 사실을 `WARN`으로 남긴다 |

`until`에 종료 경계를 둘 부여하는 이유는 조건이 부작용 없이 참이 되지 않을 수 있기
때문이다 — 데드라인만으로는 데드라인이 선언되지 않은 workflow에서 무한 루프가 되고,
라운드 상한만으로는 상한 안에서 데드라인을 초과할 수 있다. 둘 중 하나라도 없으면
종료가 보장되지 않는다.

**`repeat`와 `Policy.retry`는 다르다.** `repeat N`은 성공하든 실패하든 N회 실행하는
선언이고, `retry N`은 실패한 step을 최대 N회 다시 시도하는 정책이다. 하나를 다른
하나로 접으면 IR의 의미가 왜곡된다(RFC-0002 부록 A.2 P10).

**조건식의 표현력.** `condition`의 문법은 RFC-0002 Open Questions ②가 소유한다. 런타임
계약은 "평가할 수 없는 조건은 **거부한다**"는 것뿐이다 — 참으로 간주하고 진행하면
선언된 가드가 조용히 사라지고, 거짓으로 간주하면 선언된 작업이 조용히 사라진다. 어느
쪽도 관측 가능한 실패보다 나쁘다.

### Policy Enforcement

Constraint 노드(RFC-0001: Policy·Security·Performance)의 런타임 의미.
Security의 `mechanisms`는 컴파일러가 구현을 선택하는 입력이며(CHARTER §핵심
철학 2), 런타임 계약으로는 Authorization 게이트(위 표)와 §Observability의
마스킹 의무가 해당한다. Policy·Performance의 집행 계약은 다음 표와 같다.

| 항목 | 런타임 의미(계약) |
|------|------------------|
| `Policy.retry N` | 실패한 **step**의 재실행. 최대 N회 재시도(초기 시도는 별도 — `retry 3` = 실패 후 최대 3회 더 시도). 대기는 capped exponential backoff + full jitter. 재시도는 2중 게이트를 모두 통과할 때만: ① step이 소유한 Effect 전부가 아래 멱등 판정 표에서 멱등 ② 실패 유형이 아래 실패 유형 표에서 재시도 가능. 모든 재시도는 `Policy.timeout`의 잔여 데드라인 안에서만 수행한다 |
| `Policy.rollback` | 실패 시 보상의 경계는 **Transaction 노드**다. 진행 중이던 Transaction은 원자적으로 abort되고(부분 쓰기 없음), 이미 커밋된 선행 step의 Transaction들은 역순으로 보상을 실행한다. Transaction 밖의 Effect(예: 외부 NetworkCall)는 자동 보상이 불가하다 — rollback이 보장하는 범위는 Transaction 경계까지이며, 그 밖의 보상은 계약하지 않는다(한계는 §Open Questions ③과 연결) |
| `Policy.timeout T` | workflow 실행 전체의 데드라인. 실행 시작 시각에 기산하고, 모든 하위 Effect 호출에 **잔여 데드라인을 전파**한다(호출받은 쪽은 잔여 시간을 자신의 타임아웃 상한으로 삼는다). 초과 시: in-flight Effect에 취소를 전파하고(아무도 읽지 않을 일을 계속하지 않는다), actor 메일박스의 해당 실행 작업을 폐기하며, workflow는 `TimedOut` 실패로 종결한다 |
| `Performance.cache T` | 해당 workflow의 CacheAccess `set`에 적용되는 TTL 예산. TTL의 소유권은 Performance 제약에 있다(RFC-0001 CacheAccess 행 — 중복 지정 금지). 런타임 계약: TTL 없는 `set`은 금지된다 — 모든 key는 TTL을 가진다(무효화가 유실돼도 TTL이 백스톱) |
| `Performance.response X` | **SLO 선언이다 — 집행 대상이 아니다.** 런타임은 초과 요청을 차단하지 않는다(유효한 요청을 자기 손으로 실패시키는 것은 SLO 개선이 아니다). 대신 계측·경보한다: step/workflow duration histogram의 **p50/p95/p99**를 SLO와 비교하고 위반 시 경보를 발화한다. 평균 단독 비교는 금지 — 평균은 사용자가 실제로 겪는 꼬리 지연을 가린다 |

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
— RFC-0000 §5에 따라 참조만 하고 재정의하지 않는다). 노드 id는 RFC-0001
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
              보상 경계 = Transaction 노드. Login IR에는 커밋된 선행
              Transaction이 없으므로 보상 목록이 비어 있다 — rollback은
              no-op으로 종결되고, 이것 자체가 계약 준수다(보상은 Transaction
              경계까지만 보장된다는 §Policy Enforcement의 서술).
```

- workflow는 `Failed`로 종결, 원인(connection refused ×4)이 보존된다.
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

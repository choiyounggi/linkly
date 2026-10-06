# RFC-0061: 이벤트 발행 SPI — `lnpl.publishers`, `EventPublisher` 계약, 레퍼런스 릴레이 스킴 디스패치

## Status

- Status: Draft
- Updates: RFC-0040 §Motivation, RFC-0040 §Reference-level Specification/7. 오류 분류 — 3갈래 (D7), RFC-0040 §Reference-level Specification/8. 레퍼런스 릴레이 — `lnpl relay` (D8), RFC-0040 §Reference-level Specification/9. 문서 — `subscribe` vs `consume by` (D9), RFC-0040 §Alternatives

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목하고, 규칙 4에 따라 각 절의 **치환 후
최종 텍스트**를 §8에 싣는다. RFC-0040은 이 RFC 외에 어떤 갱신도 받은 적이 없어
직전 갱신 RFC를 함께 지목할 필요가 없다.

번호가 0061인 이유: 이 RFC는 원래 0053으로 등록됐으나(issue #191), 같은 번호를 쓴
origin/main의 PR #217이 0053부터 0060까지 먼저 병합되어 겹쳤다. RFC-0007 §3은
신규 RFC에 고유한 순차 번호를 부여하므로, 겹친 자리를 재사용하지 않고 0061로
재번호했다.

## Motivation

outbox 이벤트(이슈 #102)가 프로세스 밖으로 나가는 길은 둘뿐이다 — `outbox drain`
뒤에 손으로 짠 컨슈머 코드, 또는 `lnpl relay --target <base-url>`(RFC-0040 §8,
HTTP 전용, 다른 `lnpl` 프로세스의 `/-/events/<slug>`로만). 어느 쪽도 실제 브로커에
닿으려면 재시도·순서·dead-letter 코드를 매번 새로 써야 한다(이슈 #191).

이슈 #88의 원칙 — 코어는 아웃박스 테이블 스키마와 drain/ack 의미론만 소유하고 실제
브로커 퍼블리셔는 릴레이 구현체의 몫 — 은 RFC-0040이 소비 쪽에 대칭 적용했다:

> 코어는 **구독 선언 + 인입 엔드포인트 + 멱등/오류-분류 의미론**을 소유한다.
> 브로커에서 읽어 그 엔드포인트를 찌르는 것은 릴레이의 몫이다.

이 RFC는 같은 원칙을 **발행 쪽**에 적용한다. 바뀌는 것은 한 가지다: 코어가 이제
"어느 드라이버로 발행할지 고르는 레지스트리 지점"(`lnpl.publishers`)도 소유한다.
실제 브로커 클라이언트 코드(카프카 등)는 그 레지스트리에 등록하는 외부 패키지의
몫으로 남는다 — 드라이버 SPI(#75/#132, `lnpl.cache`/`lnpl.network` 등)와 같은 판단이다.

at-least-once 전달은 "발행이 확인된 뒤에만 ack"라는 규율에서 나온다. 확인 전에
ack하면 프로세스가 죽을 때 이벤트가 조용히 사라지고, 확인 후 ack 전에 죽으면
재발행(중복)이 생기므로 소비자는 멱등이어야 한다. 이것이 transactional outbox
패턴의 표준 형태다(microservices.io, "Transactional outbox") — RFC-0040 §6의
멱등 클레임이 그 소비자 쪽 짝이다.

## Guide-level Explanation

기존 사용법은 그대로다:

```
lnpl relay app.lnpl --backend sqlite:app.db --target http://other:8080 --once
```

스킴이 `http`/`https`가 아니면 등록된 발행 드라이버가 받는다:

```
lnpl relay app.lnpl --backend sqlite:app.db --target kafka://broker:9092/topic --once
```

`--target`의 스킴이 고르는 순서는 고정이다 — ① `http`/`https`면 기존 경로(바이트
동일, 아무것도 바뀌지 않았다) ② 아니면 `lnpl.publishers` entry-points에서 그
스킴 이름을 찾아 드라이버를 만든다 ③ 어디에도 없으면 스킴·내장 목록·등록된
이름을 담은 오류로 거부한다.

드라이버를 만드는 쪽(외부 패키지)은 `pyproject.toml`에 팩토리를 등록하고
`EventPublisher`를 구현한다. 등록 모양과 TCK 사용법은 `docs/backends.md` §15에
있다. 소비 쪽은 바뀌지 않는다 — 브로커에서 읽는 일은 여전히 "드라이버가 브로커 ->
HTTP `/-/events` 브리지를 제공"하는 것이다.

## Reference-level Specification

### 1. `EventPublisher` 계약 (D1)

```python
# impl/lnpl/drivers.py
PUBLISHERS = ("http", "https")
PUBLISHERS_ENTRY_POINT_GROUP = "lnpl.publishers"

class PublishRejected(DriverError): ...   # permanent rejection -> ack + dead-letter

class EventPublisher:
    def publish(self, envelope): ...      # raises PublishRejected or DriverError
    def publish_batch(self, envelopes): ... # default: loop, stop at first raise
    def close(self): ...
```

`envelope`는 CloudEvents structured-mode dict(`specversion`/`id`/`source`/`type`/
`data`) 한 건이다. **ack-after-confirm**: 호출자는 `publish`/`publish_batch`가
예외 없이 돌아온 때에만 outbox 행을 ack한다.

실패는 두 갈래다: `PublishRejected`는 "다시 보내도 같은 결과"인 영구 거부(ack +
dead-letter), 그 외 `DriverError`는 "확인하지 못함"(ack 안 함, 다음 드레인이
재시도). `publish_batch`의 기본 구현은 순서대로 `publish`를 부르다 첫 예외에서
멈춘다 — 드라이버가 실제 배치 API로 재정의해도 순서를 지켜야 하고 중간 실패를
삼키면 안 된다. `close()`는 여러 번 불러도 안전하다. `lnpl relay`의 글루는
emission마다 `publish`를 부른다.

### 2. `lnpl.publishers` entry-points와 `open_publisher` (D2, D4, D6)

`open_publisher(target)`은 `urllib.parse.urlsplit(target).scheme.lower()`로 고른다:

- `http`/`https` → `None`을 돌려준다(기존 릴레이 경로가 처리한다). 이 검사는
  entry-points 조회보다 **먼저** 실행되므로 어떤 패키지도 이 두 이름을 가릴 수 없다.
- `lnpl.publishers` 그룹에 그 스킴 이름이 있으면 팩토리를 로드해 **`--target`의
  전체 원문 문자열**로 부른다. `open_cache` 같은 DSN형 값과 달리 `partition(":")`으로
  나머지만 넘기지 않는다 — 콜론 기준 분할은 스킴만 떼어 내고 `//`는 남기지만,
  팩토리는 자기 `urlsplit`을 쓰므로 스킴째 전체를 받는 쪽이 정보 손실이 없다.
- 그룹에도 없으면 `ValueError`로 거부한다. 메시지는 **받은 스킴**, `PUBLISHERS`,
  등록된 이름 목록(없으면 `none`)을 싣고 **`--target` 전체는 싣지 않는다** —
  `user:pass@` userinfo에 크리덴셜이 실릴 수 있다.
- entry-point의 `.load()`가 실패하면 `ImportError` 등을 그대로 흘리지 않고
  `DriverError`로 번역한다(원인 체인 보존).

### 3. `lnpl relay --target` 스킴 디스패치 (D3)

```
lnpl relay <source...> --backend sqlite:<path> --target <scheme>://... [--once]
```

`open_publisher`가 `None`이면 `cli._relay_drain_once`/`_relay_post` 경로가
그대로 돈다 — 이 두 함수의 코드는 이 RFC가 바꾸지 않으며 `http(s)://` 동작은
바이트 동일하다. 그 외 스킴은 `cli._relay_drain_once_via_publisher`가 같은 봉투
모양·같은 `seq` 오름차순 drain 순서로 `EventPublisher.publish`를 부른다.
릴레이 종료 시 `publisher.close()`를 부른다.

### 4. 오류 분류 대칭 — 발행 쪽 (D5)

RFC-0040 §7이 소비 쪽에 3갈래 표를 두었다면(§8의 §7 치환 텍스트에 원문 그대로),
발행 쪽의 대칭 표는 아래다:

| 발행 결과 | outbox 행 | 이유 |
|-----------|-----------|------|
| `publish()`/`publish_batch()`가 예외 없이 반환 | ack | 발행이 확인됐다 |
| `PublishRejected` | ack + stderr에 dead-letter 경고 한 줄 | 재시도해도 같은 결과(RFC-0040 §7의 422 갈래와 대칭) |
| 그 외 `DriverError` | ack 안 함, 다음 드레인이 재시도 | 확인하지 못했다(RFC-0040 §7의 503 갈래와 대칭) |

`DriverError`도 `PublishRejected`도 아닌 예외는 분류하지 않고 흘려보낸다 — 이
RFC는 세 번째 갈래를 발명하지 않는다. 선언되지 않은 이벤트 id를 가리키는 행은
기존 http(s) 경로와 같이 ack하지 않고 stderr에 경고한다.

### 5. `EventPublisherTCK` (D8)

`lnpl.testing.EventPublisherTCK`가 외부 드라이버의 적합성을 검사한다:
발행 확인 뒤에만 ack, 실패는 미ack(다음 드레인이 재시도), 재시작 뒤 미확인 행
재발행, `id="outbox-<seq>"` 기준 순서 보존. 이 TCK는 `cli._relay_drain_once_via_publisher`를
직접 불러 검사하므로 **글루가 규율을 어기면 TCK가 실패한다.**

적합성 의무: TCK가 실제로 위반을 잡는다는 증거로, "발행 전에 ack하는" 글루와
"오류를 삼키고 ack하는(drop-on-error)" 글루 둘 다에서 같은 케이스가 실패하는
discriminating test를 둔다. 외부 드라이버가 자기 CI에서 돌리는 TCK도 같은 규율을
검사해야 한다.

### 6. 소비 측 브리지 (사용자 결정, 확정)

소비는 "드라이버가 브로커 -> HTTP `/-/events` 브리지를 제공한다"로 남는다.
이 RFC는 **소비 쪽 SPI를 추가하지 않는다.**

### 7. CloudEvents 바인딩과 중복제거 키 (D9)

structured 모드만 쓰고 RFC-0040 §5의 봉투 검증을 그대로 재사용한다.
중복제거·순서 키는 `id="outbox-<seq>"`이다 — 기존 http(s) 경로가 이미 부여하는
같은 안정값이므로 같은 행은 어느 드라이버를 거쳐도 같은 키를 갖는다.

### 8. RFC-0040 갱신 — 치환 후 최종 텍스트 (RFC-0007 §2.2 규칙 4)

각 소절은 RFC-0040의 현재 텍스트를 먼저 인용하고, 이어서 **치환 후 최종 텍스트**를
싣는다. 독자는 RFC-0040을 열 필요가 없다.

#### 8.1 §Motivation

현재 텍스트:

> 코어는 **구독 선언 + 인입 엔드포인트 + 멱등/오류-분류 의미론**을 소유한다.
> 브로커에서 읽어 그 엔드포인트를 찌르는 것은 릴레이의 몫이다.

최종 텍스트:

> 코어는 **구독 선언 + 인입 엔드포인트 + 멱등/오류-분류 의미론**을 소유한다.
> 브로커에서 읽어 그 엔드포인트를 찌르는 것은 릴레이의 몫이다.
> 발행 쪽에서는 코어가 어느 발행 드라이버를 쓸지 고르는 레지스트리 지점
> (`lnpl.publishers`)도 소유한다 — 실제 브로커 드라이버는 여전히 외부의 몫이다
> (RFC-0061).

#### 8.2 §Reference-level Specification/7. 오류 분류 — 3갈래 (D7)

현재 텍스트(RFC-0040 §7, 소비 쪽 분류)는 아래 전체이며, 최종 텍스트는 이 전체를
**한 글자도 바꾸지 않고** 두고 마지막에 한 문단만 더한다:

`map_consume_result(result)`가 `run_workflow`의 결과를 분류한다 —
일반 워크플로 POST 라우트의 M6-M9 사다리(`map_result`)와 **다른** 함수다:
그 사다리는 "이 호출자가 뭘 잘못했나"를 답하고, 이 함수는 "이 봉투를 다시
밀어도 되는가"를 답한다.

| 결과 | HTTP | code |
|------|------|------|
| `status == "completed"` | 200 | — |
| `failure_kind == "deadline"` | 503 + `Retry-After: 1` | `event-retry-later` |
| `failure_kind == "conflict"` | 422 | `event-rejected` |
| 실패 스텝의 effect에 `RepositoryCall`/`NetworkCall` 포함(그 외) | 503 + `Retry-After: 1` | `event-retry-later` |
| 그 외 전부(`Validation` 거부, 명시적 비즈니스/가드 RunError) | 422 | `event-rejected` |

**순서가 중요하다**: `conflict`는 실패 스텝이 여전히 `RepositoryCall`
effect를 갖지만(생성 충돌도 결국 그 effect다), D7이 명시적으로 영구
실패라고 이름 붙였으므로 effect-only 분기보다 먼저 확인해야 한다 —
그렇지 않으면 재시도해도 절대 성공할 수 없는 충돌이 "재시도하라"는 503을
받아, 릴레이가 영원히 재시도하고 멱등 클레임도 절대 확정되지 않는다.

내부 예외 이스케이프(런타임 버그 등, `run_workflow` 자체가 raise)도
503으로 분류한다 — 진짜 원인이 불확실하므로 422(영구)라고 단정하지 않고,
같은 D6 r2 논리로 멱등 클레임을 `idempotency_release`로 반납한다(확정도,
방치도 아니다).

(추가) 위 표와 규칙은 **소비 쪽** 분류다. 발행 쪽의 대칭 계약 —
`PublishRejected` -> ack + dead-letter, 그 외 `DriverError` -> 미ack — 은
RFC-0061 §4가 정의한다.

#### 8.3 §Reference-level Specification/8. 레퍼런스 릴레이 — `lnpl relay` (D8)

최종 텍스트는 RFC-0040 §8 전체이며 바뀌는 곳은 둘이다: 사용 줄의 `--target` 값 표기,
그리고 3번 항목. 나머지 항목(1, 2, 4)과 뒤 문단은 RFC-0040 원문 그대로다:

```
lnpl relay <source...> --backend sqlite:<path> --target <base-url|scheme://...> [--once]
```

`source`는 emission의 이벤트 id를 이벤트 선언 이름으로 되돌리는 데만
컴파일한다(재실행 없음). 매 드레인 사이클마다:

1. `repository.drain_outbox()` — 미배달 emission 전부.
2. 각 emission을 CloudEvents 봉투로: `id="outbox-<seq>"`(안정값 — 같은
   행은 항상 같은 멱등성 키), `source`=모듈명, `type`=이벤트 선언 이름,
   `data`=emission의 payload.
3. `<target>`이 `http(s)://`이면 그대로 POST한다(바이트 동일); 그 외 스킴이면 RFC-0061 §2/§3이 정의한 `open_publisher`/스킴 디스패치로 발행한다.
4. 응답별 ack 결정: 200 → ack. 422 → ack + stderr에 dead-letter 경고 한
   줄(재시도해도 같은 결과이므로). 503 또는 응답 없음(연결 실패) → ack 안
   함, 다음 드레인이 재시도(at-least-once, 성공 후에만 커밋하는
   오프셋-커밋 규율). 그 외 예기치 못한 상태(예: 대상이 그 슬러그에
   `consume by`를 선언하지 않아 404)도 안전한 쪽(ack 안 함)으로 접는다 —
   이 레퍼런스 릴레이는 D7이 정의하지 않은 네 번째 갈래를 발명하지 않는다.

`--once`는 한 사이클만 돌고 rc 0으로 끝난다(테스트·cron이 미는 모양).
기본은 무한 반복(고정 폴링 간격) — `--interval` 같은 튜닝 플래그는 내지
않는다(이슈가 `--once` 하나만 요구했다, §Alternatives #5).

브로커 의존 없음. `lnpl-relay-kafka` 같은 실바인딩은 이 RFC의 범위 밖 —
드라이버 SPI(#75/#132)와 같은 판단.

(추가) 등록된 발행 드라이버 경로의 ack 결정은 RFC-0061 §4다.

#### 8.4 §Reference-level Specification/9. 문서 — `subscribe` vs `consume by` (D9)

현재 텍스트(RFC-0040 §9)는 아래 전체이며, 최종 텍스트는 이 전체를 **한 글자도 바꾸지
않고** 두고 마지막에 한 문단만 더한다:

`docs/serving.md`에 대조표 + E1-E7 매핑표 신설(§Guide-level Explanation의
표 형태와 동일). `docs/backends.md §5`에 소비 측 대칭 경계 1문단 — 발행
쪽 #88 원칙이 소비 쪽에도 그대로 적용됨을 명시. 라우팅↔OpenAPI 대조는
`build_routes()`가 이미 강제한다: `event-consume` 라우트 테이블은 그
계약-검사 **뒤에** 합류하므로, 대조가 깨지면 `lnpl serve`가 기동 시점에
거부한다(스케줄 트리거와 같은 안전장치).

(추가) 발행 쪽 SPI는 `docs/backends.md` §15(`lnpl.publishers` 등록·TCK)와
`plugins/lnpl/skills/lnpl-authoring/cli-surface.md`의 relay 절이 설명한다.

#### 8.5 §Alternatives 5번 행

현재 텍스트와 최종 텍스트(끝에 한 문장 추가):

| # | 검토한 대안 | 기각 사유 |
|---|------------|----------|
| 5 | **`lnpl relay`에 `--interval`/`--concurrency` 등 운영 튜닝 플래그** | 이슈가 요구한 것은 `--once` 하나뿐이다. 레퍼런스 구현이 프로덕션 운영 도구로 확장되기 시작하면 범위가 무한정 넓어진다 — 실제 운영 규모의 릴레이는 애초에 별도 패키지(§8, `lnpl-relay-kafka`류)의 몫이다. 스킴 디스패치는 운영 튜닝 플래그가 아니라 레지스트리 지점이므로 이 기각을 다시 열지 않는다(RFC-0061) |

## Examples

골든 시나리오 "Login"은 `consume by`도, 스킴으로 고르는 발행도 선언하지 않는다 —
RFC-0040의 Examples와 같은 비간섭 증명이다: 이 RFC는 문법·IR을 바꾸지 않으므로
Login의 컴파일 결과(IR, 생성물)는 바이트 그대로 불변이다.

골든 인접 예제는 명령행 하나다(새 `.lnpl` 블록 없음 — 이 RFC는 문법을 더하지 않는다):

```
lnpl relay app.lnpl --backend sqlite:app.db --target kafka://broker/topic --once
```

`kafka` 스킴이 `lnpl.publishers`에 등록돼 있으면 그 팩토리가 전체 문자열
`kafka://broker/topic`을 받는다. 등록돼 있지 않으면 받은 스킴(`kafka`)·내장
목록(`http`, `https`)·등록된 이름("none")을 담은 오류로 거부되며 target 전체는
출력되지 않는다.

## Alternatives

| # | 검토한 대안 | 기각 사유 |
|---|------------|----------|
| 1 | **http(s)도 `EventPublisher` 경로로 통합** | 이미 테스트된 `_relay_drain_once`/`_relay_post`를 동작 변화 없이 다시 써야 한다 — 이득 없이 회귀 위험만 얻는다. `http(s)`는 `None`을 돌려주고 기존 경로가 처리한다(§2, §3) |
| 2 | **`open_cache`의 `partition(":")` 규약 재사용**(콜론 뒤 나머지만 팩토리에 전달) | 콜론 분할은 스킴만 떼어 내고 `//`를 남긴다 — URL 모양의 값은 팩토리 자기 `urlsplit`에 전체 문자열이 가는 편이 정보 손실이 없다(§2) |
| 3 | **미등록 스킴 오류에 `--target` 전체를 싣는다** | `user:pass@` userinfo로 크리덴셜이 로그·터미널에 노출된다. 받은 스킴만 싣는다(§2) |
| 4 | **`NetworkDriverTCK`식 전송 계층 실패 주입 훅을 TCK에 둔다** | 브로커 종류마다 실패 모양이 달라 일반화되지 않는다. TCK는 `publish`가 던지는 예외 두 종류로만 실패를 모델링한다(§1, §5) |

## Open Questions

1. 첫 실브로커 드라이버(카프카 등)를 어느 별도 레포에서 출시할 것인가 — 이슈 #191
   변경안 5, 확정된 사용자 결정에 따라
   이 RFC의 범위 밖이다.
2. `lnpl_enforcement`의 `delivery` 축(RFC-0043)을 `publishers`까지 확장할 것인가 —
   이 RFC의 범위 밖이며 열어 둔다.

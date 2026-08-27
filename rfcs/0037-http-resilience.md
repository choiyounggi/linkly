# RFC-0037: 아웃바운드 HTTP 회복성 계층

## Status

- Status: **Accepted** (RFC-0037, 2026-08-27)
- Updates: RFC-0027 §Reference-level Specification/1 (`NetworkDriver` 계약)

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목한다. RFC-0027 §Reference-level
Specification/1이 `NetworkDriver.call`의 계약(`-> (status, body)`, 메서드 고정
POST)을 정한 이래 이 절의 갱신은 이번이 처음이다 — 사이에 있었던 이슈 #101
(`capability http`에 `method get/post`·`auth` 절을 더한 변경)은 RFC 없이
들어갔고, 이 절을 갱신하지 않았다. 이 RFC는 그 미기록 변경(폐집합이 실은
`get`/`post` 둘이었다는 사실)까지 포함해 §1의 "치환 후 최종 텍스트"를 다시
쓴다 — RFC-0007 §2.2 규칙 4(자기완결)가 부분 diff가 아니라 절 전체의 유효한
최종 상태를 요구하기 때문이다.

번호가 0037인 이유: 0036까지 점유됐다(RFC-0036, 2026-08-26). RFC-0007 §3은
번호 재사용을 금지한다.

## Motivation

이슈 #109가 실측한 대로, 아웃바운드 호출은 회복성 계층 없이 맨몸이다.
`impl/lnpl/drivers.py`의 `HttpNetworkDriver.call`이 가진 것은 timeout
하나뿐이었다:

```python
HTTP_METHODS = ("get", "post")               # lower.py:189 (RFC-0037 이전)
HTTP_AUTH_KINDS = ("bearer", "apikey")
```

없던 것을 열거하면: PUT/PATCH/DELETE를 선언할 수 없었고, 경로 파라미터
(`/orders/{id}`)를 조립할 방법이 없어 `endpoint`가 고정 URL 하나뿐이었고,
`policy retry`는 워크플로 **스텝** 재시도라 HTTP 세부(429의 `Retry-After`,
5xx만 재시도하고 4xx는 즉시 포기하는 구분, 백오프·지터)를 전혀 몰랐고, 죽은
다운스트림에 서킷브레이커 없이 계속 요청을 보냈고, `NetworkDriver.call`의
반환값이 `(status, body)` 둘뿐이라 응답 헤더(`Retry-After`·`Location`·`ETag`)
를 읽을 방법이 없었다.

업계 수렴점은 하나로 모인다 — Polly v8(.NET)의 기본 재시도(지수 백오프 +
지터), Resilience4j(Java)의 `IntervalFunction`(백오프와 지터를 분리된
설정으로), Envoy/서비스메시의 "서킷브레이커는 재시도와 별개 프리미티브"
원칙, gRPC retry config·AWS SDK의 "멱등 메서드만 자동 재시도" 규칙. 이 RFC는
이 넷을 `capability http` 선언 문법 셋(`retry`/`breaker`/`path`)과 드라이버
런타임으로 옮긴다.

## Guide-level Explanation

`capability http` 블록에 절 셋을 더한다 — 전부 선택이며, 선언하지 않으면
RFC-0027/이슈 #101 시절 그대로 동작한다(재시도 0, 브레이커 없음, 경로는
`endpoint`의 것 그대로):

```lnpl
capability http PaymentGateway
    method post
    auth bearer from PAYMENT_TOKEN
    retry 3 backoff 200ms jitter
    breaker after 10 within 1m
    path "/orders/{}"
```

**`method`**가 받는 값이 `get`/`post` 둘에서 `get`/`post`/`put`/`patch`/
`delete` 다섯으로 넓어진다 — 폐집합은 유지한다(임의 문자열 금지).

**`retry <N> backoff <duration> [jitter]`** — 연결 실패·408·429·5xx(501
제외)만 재시도한다. 그 외 4xx는 즉시 실패다. 지연은 `<duration> × 2^(시도
번호-1)`(지수 백오프), `jitter`를 쓰면 그 지연의 `[0, 지연)` 구간에서 고르게
뽑는 full jitter(AWS 권장 — 재시도 폭풍을 가장 잘 막는다)로 대체한다. 429/503
응답에 정수 초 `Retry-After`가 있으면 계산된 지연과 그 값 중 큰 쪽을 쓴다
(HTTP-date 형식은 지원하지 않는다 — 수요가 없다). `method post`/`patch`에
`retry`를 같이 선언하면 컴파일이 `retry-on-non-idempotent` 경고를 낸다 —
비멱등 메서드의 재시도는 효과를 중복시킬 수 있어서다(RFC 9110 §9.2.2).

**`breaker after <N> within <duration>`** — 이 capability로의 호출이 연속
`N`회 실패하면 그 창(`<duration>`) 동안 열린다. 열려 있으면 호출을 시도조차
하지 않고 즉시 실패한다(메시지에 `breaker-open`을 싣는다). 창이 지나면
half-open 1회 시도 — 성공하면 닫히고, 실패하면 즉시 다시 열린다.

**`path "<template>"`** — 호출부의 `call <Target> with <ref>...`가 이
템플릿의 `{}` 자리에 순서대로 채워 넣는다(`{}` 개수와 `with`의 인자 수가
일치해야 함을 lowering이 검사한다 — `format` 동사의 `condition.parse_format`
과 같은 검사, 파서만 재사용하고 런타임 치환은 따로 둔다: 이쪽은 경로
인젝션을 막기 위해 각 값을 반드시 이스케이프한다). `path`를 선언하지 않으면
`with`도 쓸 수 없다 — endpoint의 경로가 그대로 쓰인다.

## Reference-level Specification

### 1. `NetworkDriver` 계약 — RFC-0027 §Reference-level Specification/1 갱신 (치환 후 최종 텍스트)

> RFC-0037 §Reference-level Specification/1이 이 절을 갱신했다. RFC-0007
> §2.2 규칙 3에 따라 효력 있는 텍스트는 RFC-0037의 해당 절(아래)이다.

```python
class NetworkDriver:
    """The `NetworkCall` effect's adapter contract."""

    def call(self, target, payload, timeout_ms, trace_headers=None,
             path_args=None):
        """target으로 한 번 호출한다(재시도가 있으면 그 시도 하나).

        -> (status: int, body: dict, headers: dict). headers는 소문자 키
        dict — 5xx를 포함해 응답을 받은 모든 경우는 예외가 아니라 정상
        반환이다(§3). 접속 자체가 안 됐거나(연결 거부, DNS 실패, 타임아웃)
        이 target의 breaker가 열려 있으면(메시지에 `breaker-open`)
        DriverError. `timeout_ms`는 시도 하나의 예산이며, 무한 기본값을
        허용하지 않는다(RFC-0003 §Execution Model). `path_args`는 `with
        <ref>...`가 바인딩한, 아직 이스케이프하지 않은 원본 값의 리스트 —
        드라이버가 이 target의 `path` 템플릿에 `urllib.parse.quote(safe="")`
        로 이스케이프해 순서대로 채운다.
        """
        raise NotImplementedError

    def close(self):
        raise NotImplementedError
```

`HTTP_METHODS`(`impl/lnpl/lower.py`)는 `get`/`post`/`put`/`patch`/`delete`
다섯으로 닫혀 있다 — 이슈 #101이 `get`/`post` 둘로 넓힌 뒤 이 RFC가 셋을
더한다.

`capabilities` 딕셔너리(`{logical name -> {...}}`, 이슈 #101이 연 자리)의
항목 모양이 넓어진다: `method`(다섯 중 하나)·`headers`(선택, 미지정 시
`{}`)·`retry`(선택, `{"count", "backoff_ms", "jitter"}`)·`breaker`(선택,
`{"threshold", "window_ms"}`)·`path`(선택, 문자열 템플릿). 넷 다 선택이며,
전부 미지정이면 이슈 #101 시절과 바이트 동일하게 동작한다.

**`FakeNetworkDriver`**: `stubs`의 각 값이 `(status, body)`(2-튜플, 기존과
동일 — `spec.py`의 `given` 스텁이 만드는 모양)이거나 `(status, body,
headers)`(3-튜플)이거나, 그런 튜플의 **리스트**(이슈 #109 신규 — 시도마다
하나씩 순서대로 쓰고, 소진되면 마지막 항목에 고정)일 수 있다. `capabilities`
를 읽어 아래 §2의 회복성 코어를 `HttpNetworkDriver`와 동일하게 적용한다.

**`HttpNetworkDriver`**: 메서드는 `capabilities[target]["method"]`(미지정
시 여전히 `POST`)를 그대로 쓴다 — RFC-0027이 "고정 POST"라 적었던 것은 이슈
#101이 이미 깬 서술이었고, 이 RFC가 공식화한다. 응답 헤더는
`response.getheaders()`를 소문자 키로 모아 셋째 자리에 싣는다.

### 2. 회복성 코어 — 재시도·백오프·지터·Retry-After·서킷브레이커 (D2/D3/D5)

`impl/lnpl/drivers.py`에 `FakeNetworkDriver.call`과 `HttpNetworkDriver.call`
이 공유하는 함수 `_call_with_resilience(target, cap, clock_now, sleep_fn,
rand, breakers, attempt_fn)`를 더한다 — `attempt_fn()`이 시도 하나를 실행해
`(status, body, headers)`를 돌려주거나 `DriverError`를 던지면, 이 함수가
재시도 루프·백오프 계산·브레이커 게이트를 그 위에 얹는다. 한 곳에 있어야
두 드라이버가 같은 선언을 다르게 채점할 수 없다 — `NetworkDriverTCK`(§3)가
바로 그 사실을 검사한다.

재시도 대상: 연결 실패(`attempt_fn`이 `DriverError`를 던짐)·408·429·5xx
(501 제외). 그 외 4xx는 즉시 그 값을 반환한다. `retry` 미선언이면
`attempts = 1`이라 항상 시도 1회 — 이슈 #109 이전과 바이트 동일한 경로다.

백오프: `backoff_ms × 2^(attempt-1)`(1-index, 시도 1 실패 후 대기가
`backoff_ms × 2^0`). `jitter`가 있으면 `rand.uniform(0, 지연)`으로 대체한다
(full jitter). 429/503 응답에 정수형 `Retry-After`가 있으면
`max(계산된 지연, Retry-After × 1000ms)`를 쓴다 — HTTP-date 형식은 파싱하지
않고 무시한다(계산된 지연을 그대로 쓴다).

브레이커: `capability`(logical name)별 인프로세스 상태(`_Breaker`) — 연속
**호출**(그 호출 내부의 재시도 전부가 아니라) 실패가 `threshold`에 닿으면
연다. 열려 있으면 시도 자체를 하지 않고 `DriverError("breaker-open: ...")`
를 던진다. 창이 지나면 half-open 1회 — 성공하면 닫히고(카운터 리셋),
실패하면 즉시 다시 연다. 시계는 생성자 주입 `clock`(기본은 프로세스
monotonic 시계) — `interp.Clock`/`interp.RealClock`과 같은 `.now` 자리를
duck-typing으로 읽는다(`drivers.py`는 ONE DIRECTION 규칙상 `interp`를
import할 수 없다).

RNG는 생성자 주입 `rand`(기본 `random.Random()`), 대기 함수는 생성자 주입
`sleep`(기본 `time.sleep`) — 둘 다 테스트가 시드를 고정하거나 실제 대기를
건너뛸 수 있게 한다.

### 3. `NetworkDriverTCK` (D8)

`impl/lnpl/testing.py`에 `RepositoryDriverTCK`/`TokenProviderTCK`와 같은
자리, 같은 mixin 관례로 더한다. `RepositoryDriverTCK`의 무인자
`make_driver()`와 달리 `make_driver(target, capabilities, script)` —
`NetworkDriver`의 두 구현이 상태를 쥐는 방식이 비대칭이기 때문이다
(`FakeNetworkDriver`는 생성자 dict, `HttpNetworkDriver`는 서브클래스가 세운
실제 서버). 메서드·재시도·브레이커·헤더를 검사하고, 타임아웃은
`make_slow_driver()`가 `None`을 돌려주면(`FakeNetworkDriver`처럼 실 I/O가
없는 드라이버) 건너뛴다 — `RepositoryDriverTCK`의 낙관적 버전 충돌 검사가
`observed_version` 속성 유무로 건너뛰는 것과 같은 opt-in 모양이다.

### 4. 경로 템플릿 — 문법과 이스케이프 (D6)

`impl/lnpl/lower.py`의 `_derive_effect` `NetworkCall` 분기가 `call`/
`request <Target>` 뒤 `with <ref> [<ref>...]` 절을 읽는다(`as <name>`과
함께 쓸 수 있고, 순서는 `with` 먼저 `as` 나중). 각 `ref`는
`condition._is_reference_name`이 받는 모양(camelCase 또는
`binding.field`)이어야 한다. 대상 capability의 `path` 템플릿이 가진 `{}`
개수와 `with`가 준 인자 수가 다르면 컴파일 에러 — `condition.parse_format`
이 `format` 동사에 이미 쓰는 것과 같은 검사(파서 로직만 재사용; 이스케이프가
필요해 런타임 치환 함수는 따로 둔다, `drivers._assemble_path`). `path`를
선언하지 않은 capability에 `with`를 쓰면 컴파일 에러다. `path` 템플릿
자체도 `{}`를 최소 하나 가져야 한다 — 없으면 어떤 `with`도 채울 자리가
없어 선언이 파싱되고도 실행이 아무 일도 하지 않는, 이 언어가 금지하는
모양이 되므로(고정 경로는 `path`가 아니라 endpoint URL에 적는다) 컴파일
에러다.

`NetworkCall` IR 노드에 선택 필드 `path_args`(문자열 리스트)가 붙는다.
`interp.py`의 `NetworkCall` 실행은 각 참조를 `resolve_reference`로 값에
해석해(해석 실패 시 `RunError`) 원본 그대로 `network.call(...,
path_args=[...])`에 넘긴다 — 이스케이프(`urllib.parse.quote(safe="")`)는
드라이버 쪽(`_assemble_path`)이 한다: 그래야 `FakeNetworkDriver`와
`HttpNetworkDriver`가 같은 값을 같은 방식으로 이스케이프한다는 것을
`NetworkDriverTCK`가 아니라 `test_network_path_template.py`(둘을 직접
나란히 검사)가 증명할 수 있다 — TCK 자체의 스코프(§3)에는 넣지 않았다.

## Examples

```lnpl
capability http PaymentGateway
    method post
    auth bearer from PAYMENT_TOKEN
    retry 3 backoff 200ms jitter
    breaker after 10 within 1m

capability http OrdersApi
    method get
    path "/orders/{}"

entity Order
    field
        id UUID

service Checkout
    policy
        timeout 5s

workflow ChargeCard
    call PaymentGateway as paymentResult
    when paymentResult.status == 200
        find order
        call OrdersApi with order.id as orderResult
```

`PaymentGateway`는 실패 시 최대 3회, 200ms 기준 지수 백오프(+지터)로
재시도하고, 연속 10회 실패하면 1분간 브레이커가 열린다. `method post`에
`retry`가 같이 있으므로 컴파일은 `retry-on-non-idempotent` 경고를 낸다 —
경고이지 거부가 아니다(선언 자체는 유효하다).

`OrdersApi`는 재시도·브레이커가 없다(선언하지 않았으므로 0회/없음).
`call OrdersApi with order.id as orderResult`는 `order.id`가 예컨대
`"a/b"`일 때 실제 경로를 `/orders/a%2Fb`로 조립한다 — `/`가 그대로
들어갔다면 요청이 `/orders/a/b`가 되어 두 번째 세그먼트가 생겼을 것이다.

### 컴파일 거부 — 경로 인자 개수 불일치

```lnpl
    call OrdersApi with order.id order.sku as r
```

`OrdersApi`의 `path "/orders/{}"`는 `{}`가 하나인데 `with`가 인자 둘을
주므로 거부된다: "capability http OrdersApi's `path` '/orders/{}' has 1
`{}` placeholder(s) but `with` gives 2 argument(s)".

### 회귀 — 선언 없는 GET/POST는 바이트 동일

`retry`/`breaker`/`path` 중 아무것도 선언하지 않은 capability는 이슈 #109
이전과 요청·응답 처리 경로가 완전히 같다 — `test_network_binding_runtime.py`
가 인터프리터 레벨에서, `test_network_driver.py`가 드라이버 레벨에서 각각
증명한다(`impl/tests/`).

## Alternatives

| # | 대안 | 기각 이유 |
|---|------|-----------|
| 1 | 재시도 예산(전체 트래픽 대비 재시도 비율 상한)을 함께 도입한다 | 기각(이번 라운드는 아님). 업계 수렴점의 일부지만 이슈 #109 완료 기준 9항목 중 어디도 요구하지 않는다 — 예산 계산은 프로세스 전역 상태(현재 정상 요청량 대비 비율)가 필요해 이 capability-스코프 회복성 계층보다 큰 결정이다. 필요해지면 별도 이슈로 연다 |
| 2 | 커넥션 풀을 이 RFC에서 함께 연다 | 기각. `docs/backends.md` §외부 드라이버가 이미 "통합 테스트 없는 바인딩 금지" 원칙을 세워 뒀고, stdlib `http.client`로 직접 풀을 관리하는 것은 무리다 — `lnpl.drivers` SPI(#132)로 실드라이버를 외부 패키지에 맡기는 것이 이슈 #109 자신의 제안이다. 매 호출 연결은 유지한다 |
| 3 | `retry`/`breaker`의 설정을 `lower.py`가 아니라 `--network http`의 CLI 플래그로 받는다 | 기각. #101 "URL은 환경, 계약은 선언" 원칙과 어긋난다 — 재시도·브레이커 정책은 이 capability의 계약이지 배포 환경의 사실이 아니다. `method`/`auth`가 이미 선언인 것과 같은 이유로 선언에 둔다 |
| 4 | 브레이커 연속 실패를 호출이 아니라 시도(재시도 포함) 단위로 센다 | 기각. `breaker after N`은 "N번의 나쁜 호출"로 읽히지, "N번의 나쁜 시도"로 읽히지 않는다 — 재시도가 있는 호출 하나가 내부적으로 여러 번 실패해도 그 호출 자체는 (성공했다면) 성공이다. 시도 단위로 세면 `retry count`가 클수록 브레이커가 훨씬 빨리 열려, 두 절이 서로의 의미를 바꿔 버린다 |

## Open Questions

1. **mTLS·프록시·스트리밍·비-JSON 바디** — 이슈 #109 자신이 "이 이슈가 열거만 하고 별도 이슈로 미룬다"고 명시한 축이다. 이 RFC도 다루지 않는다.
2. **재시도 예산** — §Alternatives 1. 실제 운영에서 재시도 폭풍이 관측되면 별도 RFC가 연다.
3. **`lnpl.networks` SPI로의 승격** — 이슈 #109 자신의 제안: 코어는 `NetworkDriver` 계약과 TCK만 갖고, 커넥션 풀이 있는 실드라이버(`urllib3`/`httpx` 기반)는 외부 패키지가 `lnpl.drivers` 진입점(이슈 #75가 연 경계)으로 등록한다. 이 RFC는 그 SPI 표면 자체(#132)를 열지 않는다 — `capabilities` 딕셔너리 모양(§Reference-level Specification/1)이 이미 그 표면이 그대로 물려받을 계약이라는 것만 남겨 둔다.

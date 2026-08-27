# RFC-0027: 네트워크 드라이버와 결과 바인딩

## Status

- Status: **Accepted** (RFC-0027, 2026-08-18)
- Updates: RFC-0012 §G12.2 (RFC-0025 §5가 이미 갱신한 절 — 이 개정은 그 절의
  최종 텍스트 위에 세 번째 바인딩 이름공간을 더한다), RFC-0003
  §Reference-level Specification/Execution Model (`NetworkCall` 행), RFC-0014
  §Reference-level Specification/2.4 스킵 레코드 (마스킹 범위)
- Updated-by: RFC-0037 (§Reference-level Specification/1 — `NetworkDriver` 계약)

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목하고, 규칙 5(연쇄 갱신)에 따라
RFC-0012 §G12.2를 이미 갱신한 RFC-0025 §5도 함께 지목한다 — G12.2의 효력 있는
텍스트는 RFC-0012 원문이 아니라 RFC-0025 §5에 있으므로, 그 위에 세 번째
이름공간을 더하는 이 개정은 둘 다 지목해야 어느 텍스트가 이기는지 기계적으로
확인할 수 있다. RFC-0003 §Execution Model의 `NetworkCall` 행은 지금도 "명시적
timeout 필수·잔여 데드라인 전파·실패 유형별 재시도 판정은 §Policy Enforcement를
따른다"고 규정하지만, 이 레포에 그 규정을 실행하는 드라이버가 지금까지 하나도
없었다 — 이 RFC가 그 규정의 첫 번째 실행 가능한 부분(타임아웃 접합, §5)을
채운다. RFC-0014 §2.4는 가드 스킵 레코드의 `evaluations`가 엔티티 sensitive
필드만 마스킹한다고 규정하는데, 이 RFC가 여는 세 번째 이름공간(네트워크 결과
바인딩)은 엔티티가 아니므로 그 마스킹 규칙이 닿지 않는다는 것을 명시적으로
갱신해 둔다(§6). 셋 다 지목하지 않으면 RFC-0007 §2.2 규칙 1(누락 없는
지목)·규칙 2(모순 금지) 위반이다.

번호가 0027인 이유: 0026까지 점유됐다(RFC-0026, t4). RFC-0007 §3은 번호
재사용을 금지한다.

## Motivation

이슈 #64와 #76이 여는 질문은 하나의 관측에서 나온다. `impl/lnpl/interp.py`의
`_run_effect`에서 `NetworkCall`의 실행 의미는 이 한 줄이 전부다:

```python
elif kind == "NetworkCall":
    child.attrs["target"] = effect.get("target")
```

target을 trace에 기록하는 것 말고는 아무 일도 일어나지 않는다 — 실제 요청이
나가지 않고, 응답이 없고, 실패 분기도 없다. RFC-0003 §Execution Model은 이미
`NetworkCall`에 대해 "명시적 connect timeout + request timeout 필수", "잔여
데드라인과 상관ID 자동 전파", "실패 유형별 재시도 판정은 §Policy Enforcement의
표를 따른다"고 규정해 두었다 — 그러나 그 규정을 실행할 드라이버가 없으므로,
지금까지는 전부 실행되지 않는 문서였다.

관측 가능한 형태로 다시 적으면, 이 RFC가 다루는 것은 죽은 표면이 아니라 **버려지는
표면**이다. `impl/lnpl/lower.py`의 `_WfContext._step`은 `obj = line.tokens[1]`
만 읽고 그 뒤 토큰은 아무 것도 하지 않는다 — 오늘 `call PaymentGateway as p`를
쓰면 컴파일은 통과하고, `PaymentGateway`까지만 읽히고, `as p`는 조용히
버려진다. RFC-0025 §Motivation이 "어휘 밖 동사"(이슈 #36)의 반대 방향
사례("어휘가 결코 만들지 않는 내부 상수")를 지적했던 것과 같은 결함 계열의
세 번째 자리다: 이번엔 표면 문법이 이미 그 토큰들을 받아 주는데(`RFC-0002
§Full grammar`의 `StepLine ::= Verb Word? Word? Word? EOL`은 verb 뒤 세 단어까지
받는다 — `call`/`PaymentGateway`/`as`/`p`는 정확히 네 토큰, 문법을 넓힐 필요가
없다), lowering이 그중 뒤 두 개를 조용히 버린다.

`RepositoryDriver`(#25, RFC-0025)가 이미 같은 문제를 캐패시티 어댑터 계층에서
풀었다 — 선언과 실 백엔드 사이의 계약을 표준화하고, 실패를 `DriverError` 하나로
좁혀 `interp`가 그것을 `RunError`로 번역하게 했다. `NetworkCall`에는 그 계층이
아직 없다. 이 RFC는 `NetworkDriver` 계약을 더하고(이슈 #64), `call`/`request`가
그 결과를 바인딩해 후속 가드가 성공/실패를 분기할 수 있게 한다(이슈 #76).
둘을 한 RFC로 묶는 이유는 후자가 전자 없이는 검증 불가능하기 때문이다 — 응답을
바인딩할 값이 없으면 "가드가 status로 분기한다"는 이슈 #76의 완료 기준을 증명할
방법이 없다.

## Guide-level Explanation

저자가 새로 쓸 수 있게 되는 것은 두 가지다.

**1. 네트워크 응답을 이름에 바인딩한다.**

```
workflow ChargeCard
    find order
    call PaymentGateway as paymentResult
    when paymentResult.status == 200
        update order
    when paymentResult.status != 200
        set order.failureCode to paymentResult.code
```

`call <target> as <name>`(또는 `request <target> as <name>`)은 그 호출의 응답을
`<name>`에 바인딩한다. 값은 **평탄화된** 딕셔너리다 — `status`(Integer)와, 응답
바디의 최상위 키가 그대로 같은 자리에 놓인다(`<name>.<bodyKey>`). 중첩 없이
한 단계인 이유는 `Reference`의 문법(RFC-0012 §G12.1: `CamelName ('.'
CamelName)?`, **두 조각까지**)이 이미 그렇게 정해져 있기 때문이다 —
`<name>.body.<key>`(세 조각)는 이 문법 안에 있지 않다. `status`가 바디의
같은 이름 키보다 항상 이긴다(§Reference-level Specification/3) — 그렇지
않으면 응답 바디가 자신이 실어 나르는 접속 상태 자체를 가릴 수 있다. 후속
가드나 `set`은 엔티티 바인딩과 정확히 같은 문법 위치(`<binding>.<field>`,
RFC-0012 §G12.1)에서 이 값을 읽는다 — 새 문법을 배울 필요가 없다.

**`as` 없는 기존 `call`/`request`는 오늘과 똑같이 동작한다.** 응답은 여전히
어디에도 바인딩되지 않는다(§Reference-level Specification/3) — 명시적으로 이름을
준 경우에만 값을 받는다는 것이 이 RFC의 핵심 결정이다(§Alternatives 2).

**2. 실패도 분기 가능한 값이다.** 접속 자체가 안 되는 경우(연결 거부·타임아웃)는
바인딩된 호출에서 `status=0`(바디 필드 없음)으로 관측된다 — 워크플로가 죽지
않고 가드가 그 값으로 분기한다:

```
    call PaymentGateway as paymentResult
    when paymentResult.status == 0
        authorize incidentEscalation
```

(`set`의 좌변은 Integer·DateTime 필드만 받는다 — RFC-0015 §3, 평가기가
Text·Money 등에는 없다는 기존 제약이며 이 RFC가 손대지 않는다. 그래서 응답
바디의 텍스트 값을 엔티티에 저장하는 예는 이 RFC에 없다 — `set
order.failureCode to paymentResult.code`(§Guide-level Explanation 1)처럼
Integer 필드로만 흘려보낼 수 있다. 위 예는 그 제약 밖에서도 분기 자체는
가능하다는 것만, `set`이 아닌 임의의 스텝(`authorize`)으로 보인다.)

5xx 응답도 마찬가지로 값이다(`status`가 그대로 500 등을 담는다) — 예외가 아니라
읽을 수 있는 상태다. **바인딩 없는** 호출의 접속 실패는 다르다: 관측할 이름이
없는데 호출은 실제로 실행됐으므로, 기존 저장소·캐시 호출과 같은 규약대로
`RunError`가 된다(조용히 삼키지 않는다 — §Reference-level Specification/3).

**3. 어떤 드라이버로 나가는지는 `--network`가 고른다.** `--backend`가
`postgres`의 실 구현을 고르는 것과 같은 자리에, `--network fake|http`가
`NetworkCall`의 실 구현을 고른다. 기본값 `fake`는 스텁 테이블에서 응답을
찾고, 없으면 결정적으로 `200`/빈 바디를 돌려준다(§Reference-level
Specification/2). `http`는 `target`을 URL로 읽어 `http.client`(표준
라이브러리, 의존성 0)로 실제 요청을 보낸다.

**4. spec에서 응답을 스텁한다.**

```
        given
            call PaymentGateway returns 500 body.code 42
        when
            chargeCard
        expect
            completed
            result paymentResult.status == 500
```

`given call <target> returns <status>`가 그 target으로의 호출이 받을 응답을
고정한다 — `stored`가 저장소 행을 고정하는 것과 같은 자리다. 스텁하지 않은
target은 fake 드라이버의 기본값(200/빈 바디)을 결정적으로 받는다.

## Reference-level Specification

### 1. `NetworkDriver` 계약 (D1)

> RFC-0037 §Reference-level Specification/1이 이 절을 갱신했다. RFC-0007
> §2.2 규칙 3에 따라 효력 있는 텍스트는 RFC-0037의 해당 절이다.

`impl/lnpl/drivers.py`에 `RepositoryDriver`/`CacheDriver`/`TokenProvider`와
같은 자리에 신규 계약을 더한다. 기존 관례("raise NotImplementedError" 문서화된
메서드, ABC 없음)를 그대로 따른다.

```python
class NetworkDriver:
    """The `NetworkCall` effect's adapter contract."""

    def call(self, target, payload, timeout_ms):
        """target으로 한 번 호출한다.

        -> (status: int, body: dict). 접속 자체가 안 되면(연결 거부, DNS 실패,
        타임아웃) DriverError — 5xx를 포함해 응답을 받은 모든 경우는 예외가
        아니라 정상 반환이다(§3). `timeout_ms`는 이 호출 하나의 예산이며,
        무한 기본값을 허용하지 않는다(RFC-0003 §Execution Model).
        """
        raise NotImplementedError

    def close(self):
        raise NotImplementedError
```

**`FakeNetworkDriver`** (reference implementation, `interp`가 기본 구성):
`{target: (status, body)}` 스텁 테이블로 만든다. `call`은 테이블에 있으면 그
값을, 없으면 결정적으로 `(200, {})`를 돌려준다 — 예외를 던지지 않는다(D4의
"스텁 미지정 = 결정적 기본"). `close`는 no-op이다.

**`HttpNetworkDriver`** (`http.client`, 표준 라이브러리만 — 의존성 0 원칙):
`target`을 `urllib.parse.urlsplit`으로 읽어 `http.client.HTTPConnection(host,
port, timeout=timeout_ms / 1000)`을 열고, `payload`를 JSON으로 인코딩해 `POST`로
보낸다. 메서드를 고정 `POST`로 정한 이유: 이 RFC가 다루는 시나리오(결제·외부
API 호출)는 페이로드를 보내는 것이 핵심이고, `GET`/`PUT` 등 메서드별 분기는
이슈 #64/#76 어느 완료 기준도 요구하지 않는다(§Open Questions 4). 응답
바디는 JSON으로 파싱을 시도하고, 파싱되지 않으면 `{}`다(값의 모양을 dict로
고정해 두는 것이 소비자 쪽 계약을 단순하게 만든다 — RFC-0003 §Execution
Model이 이미 요구하는 것 이상을 시도하지 않는다). 연결 실패·타임아웃은
`http.client`/`socket`이 던지는 예외(`OSError`, `http.client.HTTPException`
계열)를 잡아 `DriverError`로 번역한다 — **5xx는 정상 응답이므로 이 경로를
타지 않는다**: HTTP 상태 줄을 받은 시점에 이미 접속은 성공했다.

**선택 스위치** (D1, `--backend`의 거울상). `drivers.py`에 닫힌 표와 디스패처를
더한다:

```python
NETWORKS = ("fake", "http")

def open_network(spec):
    if spec == "fake":
        return None   # Interpreter가 자신의 FakeNetworkDriver를 만든다
    if spec == "http":
        return HttpNetworkDriver()
    raise ValueError("unknown network %r (accepted: %s)"
                     % (spec, ", ".join(NETWORKS)))
```

`cli.py`는 `_open_backend`/`_REJECTED`와 같은 자리에 `_open_network`를 더하고,
`run` 서브커맨드에 `--network fake|http`(기본 `fake`)를 추가한다 —
`--backend`가 `run`/`serve`에는 있고 `spec`에는 없는 것과 같은 자리다.
`spec`은 노출하지 **않는다**: `run_manifest`는 이미 자기 `Interpreter`를
직접 만들고(`--backend` 선택도 받지 않는다), 매 케이스가 자신의 `given`
스텁으로 결정적인 `FakeNetworkDriver`를 새로 만든다(§7) — `--network http`를
허용하면 스텁이 적용되지 않는 실 호출이 케이스의 결정성 자체를 깨므로,
`spec`이 `--backend`를 갖지 않는 것과 같은 이유로 이 스위치를 갖지 않는다.
`serve.py`에도 노출하지 않는다 — §Alternatives 1이 이월을 기록한다.

### 2. `as` 결과 바인딩 문법 (D2)

**문법은 바뀌지 않는다.** `StepLine ::= Verb Word? Word? Word? EOL`(RFC-0002
§Full grammar, RFC-0025 §1이 이미 확인했듯 이 RFC도 손대지 않는다)은 verb
뒤 세 단어까지 받는다 — `call PaymentGateway as p`는 정확히 네 토큰이므로
이미 문법 안에 있다. 닫힌 어휘 판정은 여느 때처럼 문법이 아니라 lowering이
한다.

**`as`는 `lexer.RESERVED`에 넣지 않는다.** `RESERVED`에 들어간 토큰은 소스
어디에 나타나든(값 리터럴 포함) LexError다 — `given`/`expect` phrase의 값
토큰이나 다른 문맥에서 우연히 "as"라는 단어를 써야 하는 경우까지 전부
막아버리므로, 이 RFC가 실제로 필요로 하는 것보다 넓게 언어를 깨뜨린다.
대신 RFC-0025의 `AGG_FUNCS`(`lexer.py`, 렉서 전역이 아니라 `set`의 우변
위치에서만 닫힌 어휘로 소비되는 상수)와 같은 자리를 따른다: `as`는
`lower._derive_effect`의 `NetworkCall` 분기가, **오직 `call`/`request` 스텝
줄의 셋째 토큰 위치에서만** 닫힌 키워드로 읽는다. 그 밖의 모든 문맥에서
"as"는 여느 단어와 같다.

**`_derive_effect`가 나머지 토큰을 받는다.** 오늘은 `obj = line.tokens[1]`만
넘어가고 그 뒤는 버려진다(§Motivation). `_WfContext._step`이
`line.tokens[2:]`를 `_derive_effect`에 추가로 넘기도록 시그니처를 넓힌다
(호출부가 `_step` 안 한 곳뿐이므로 다른 verb의 호출은 영향받지 않는다 —
기본값 `()`로 그 verb들은 인자를 무시한다). `NetworkCall` 분기의 판정표:

| `tokens[2:]` | 판정 |
|---|---|
| `()` (없음) | 바인딩 없음 — §3의 "바인딩 없는 호출" 그대로(후방 호환, 골든 무발화) |
| `("as", name)` | `name`이 §아래 두 검사를 통과하면 `result=name` 필드를 노드에 싣는다 |
| 그 밖의 모든 형태 | 컴파일 거부(`LowerError`, rc=2) — `line %d: call/request accepts either no trailing words or 'as <name>', got %r` |

**세 번째 형태를 조용히 버리지 않고 거부하는 이유**가 바로 §Motivation이 연
질문이다 — 저자가 `as`를 오타 냈거나 문법을 착각했을 때, 오늘처럼 조용히
버려지면 "왜 응답이 안 잡히지"가 몇 단계 뒤(가드 평가)에서야, 그것도
"아직 바인딩 없음"(G12.4)이라는 무관해 보이는 형태로 관측된다 — RFC-0025
§Motivation이 "죽은 경로가 틀린 채로 살아난다"고 부른 것과 같은 침묵이다.

**`name`의 두 가지 컴파일 시점 검사** (둘 다 `LowerError`, rc=2):

1. **형태.** `name`은 다른 모든 바인딩 이름과 같은 lexical 형태를 따라야
   한다(`condition._is_camel_name`: `[a-z][a-zA-Z0-9]*`) — `<name>.status`가
   유효한 `Reference`(RFC-0012 §G12.1)가 되려면 그것이 이미 요구하는
   형태다. `PaymentResult`(대문자 시작)나 `payment_result`(스네이크)는
   거부된다.
2. **이름 충돌.** `name`은 이 모듈에 선언된 어떤 Entity의 camelCase 바인딩
   이름과도 같을 수 없다. RowSet(RFC-0025 §5)은 단일 행 바인딩과 이름이
   겹쳐도 안전한데, 두 문법 위치가 다르기 때문이다(`Aggregate`의
   `AggFunc Reference`는 `<binding>.<field>`와 첫 토큰에서부터 갈린다).
   네트워크 결과 바인딩은 다르다 — `<name>.status`는 엔티티 단일 행 바인딩의
   `<binding>.<field>`와 **문법적으로 구별되지 않는 같은 자리**를 쓴다.
   `as`로 준 이름이 엔티티 이름과 겹치면 `<name>.field` 참조가 어느 바인딩을
   읽는지 결정할 방법이 없다 — RFC-0012 §G12.3이 이미 "충돌이 존재하지
   않는다"고 선언한 것은 두 Entity의 바인딩 이름이 모듈 안에서 유일하기
   때문이었는데, 세 번째 이름 출처(저자가 자유롭게 고르는 이름)가 그 유일성
   가정을 깰 수 있으므로, 이 RFC가 그 가정을 지키는 검사를 더한다.

**스키마.** `schemas/lir.schema.json`의 `nodeNetworkCall`에 선택 필드를
더한다(`additionalProperties: false`이므로 필드 자체를 열어야 한다):

```json
"result": { "type": "string" }
```

`required`는 바꾸지 않는다 — `result`는 선택이다.

### 3. 실행 의미 — mode A (D3)

`_run_effect`의 `NetworkCall` 분기를 다음으로 바꾼다. **드라이버는 바인딩
여부와 무관하게 항상 호출된다** — §Motivation이 지적한 시뮬레이션(오늘의
no-op)을 실 호출로 만드는 것이 이슈 #64의 요지이며, "바인딩되지 않은 호출은
호출되지 않은 것처럼 취급한다"로 되돌아가면 그 요지를 반만 채우게 된다.

```python
elif kind == "NetworkCall":
    remaining_ms = ((deadline - self.clock.now) if deadline is not None
                    else DEFAULT_NETWORK_TIMEOUT_MS)
    try:
        status, body = self.network.call(effect["target"], payload, remaining_ms)
    except DriverError as exc:
        if effect.get("result"):
            status, body = 0, {}     # D3: 바인딩된 호출의 접속 실패 = 값
        else:
            raise RunError(str(exc)) from exc   # D3: 바인딩 없어도 실패는 삼키지 않는다
    child.attrs["target"] = effect.get("target")
    if effect.get("result"):
        child.attrs["status"] = status
        # 평탄화 — §4: body의 최상위 키가 status와 나란히 놓인다. status가
        # 이긴다(같은 이름의 body 키보다 우선).
        bound = dict(body) if isinstance(body, dict) else {}
        bound["status"] = status
        bindings[effect["result"]] = bound
```

`_run_effect`가 `deadline`을 받도록 시그니처를 넓힌다(`_run_step`이 이미 그
값을 갖고 있고 호출부가 한 곳뿐이므로 하위 호환이 깨지지 않는다 — §5). 이것이
**다섯 번째** `except DriverError` 번역 지점이다(Assignment의 persist,
RepositoryCall의 query·execute, CacheAccess에 이어).

**바인딩 없는 호출**은 §Motivation의 후방 호환 요구를 정확히 지킨다:
`child.attrs`에는 오늘과 같이 `target`만 남고(§2 판정표의 첫 행이 `result`
필드를 아예 싣지 않으므로 `effect.get("result")`가 항상 거짓), 5xx나 성공
응답은 관측되지 않고 버려진다(오늘의 no-op과 골든 시나리오 관점에서 구별
불가능 — `--network fake`의 기본 응답은 예외를 던지지 않으므로 새 `RunError`
경로도 열리지 않는다). **접속 자체가 안 되면**(`--network http`를 명시적으로
쓴 경우에만 실제로 일어날 수 있다) `RunError`가 된다 — "관측만 하던 스텝이
실패를 조용히 삼키면 안 된다"는 D3의 요구이자, 다른 모든 Effect kind가 이미
따르는 "`DriverError`는 하나의 예외 없이 `RunError`가 된다" 규약(drivers.py
모듈 docstring)의 그대로의 적용이다.

**바인딩된 호출**은 실패도 값이다: `status=0`은 실제 정수이므로 `when
result.status == 0`으로 분기할 수 있다(RFC-0012 §G12.4의 "해석되지 않는
이름" 표와는 다른 경로다 — 이건 이름이 해석**되고** 있고, 값이 0일 뿐이다).
5xx는 `HttpNetworkDriver.call`이 예외 없이 돌려주므로 `status`가 그 값 그대로
바인딩된다.

### 4. 실행 스코프 — RFC-0012 §G12.2 갱신 (치환 후 최종 텍스트) (D2)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0012 §G12.2(RFC-0025 §5가 이미 갱신한
최종 텍스트) 위에 세 번째 이름공간을 더한 **치환 후 최종 텍스트**다.

#### G12.2 무엇이 바인딩되는가

이 실행에서 완료된 `RepositoryCall`은 그 `operation`에 따라, 완료된
`NetworkCall`은 `result` 필드의 유무에 따라 세 이름공간 중 하나에 바인딩을
남길 수 있다. 한 엔티티는 최대 단일 행 바인딩 1개 + RowSet 바인딩 1개를 동시에
가질 수 있다(RFC-0025 §5). 네트워크 결과 바인딩은 엔티티에 속하지 않는
**저자가 이름 붙인** 세 번째 이름공간이며, 단일 행 바인딩과 **같은 문법
위치**(`<binding>.<field>`)를 쓴다 — 그래서 이름이 겹칠 수 없다는 것이 lowering
시점의 정적 거부다(RFC-0027 §2).

**단일 행 바인딩**과 **RowSet 바인딩**의 규칙은 RFC-0025 §5 그대로다(이
개정이 손대지 않는다).

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

### 5. `--network` 예산 접합 (D6)

`Policy.timeout`이 선언되면 `_run_step`이 갖고 있는 `deadline`(밀리초, 워크플로
시작 시각 기준)에서 `self.clock.now`를 뺀 **잔여** 예산을 `NetworkDriver.call`의
`timeout_ms`로 넘긴다 — RFC-0003 §Execution Model이 "잔여 데드라인을
전파한다"고 규정한 것이 실제로 접합되는 첫 지점이다. `Policy.timeout`이
선언되지 않으면(`deadline is None`) `DEFAULT_NETWORK_TIMEOUT_MS = 30_000`(30초)를
쓴다 — 무한 기본값은 결코 쓰지 않는다(backend/common/reliability/timeouts-and-retries:
"library defaults are unreliable and some are infinite; 하나의 무한 타임아웃이
pool을 고갈시킨다"). 이 값은 이 RFC가 새로 정하는 상수이며, 워크플로가 스스로
`timeout`을 선언하면 언제나 그 예산이 이긴다.

`FakeNetworkDriver.call`은 `timeout_ms`를 받되 쓰지 않는다(실제 I/O가 없으므로
쓸 곳이 없다) — 계약의 시그니처는 두 구현이 공유하고, 의미는 구현마다
다르다는 것이 `RepositoryDriver.execute`의 `entity_id`가 sqlite에서만 SQL
바인드 파라미터가 되는 것과 같은 전례다.

### 6. 관측 — RFC-0014 §2.4 갱신 (마스킹 범위) (D3)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0014 §2.4(스킵 레코드)의 마스킹
규칙에 대한 갱신이다. §2.4 D3(이슈 #83)는 `evaluations`의 `ref`가 가리키는
**엔티티** 필드가 sensitive면 그 `value`를 마스킹한다고 규정했다 — `input.*`
참조는 엔티티가 아니므로 마스킹 규칙이 닿지 않고 원값이 남는다는 것도 이미
정해져 있었다(`interp._masked_evaluation`).

이 RFC가 여는 세 번째 이름공간(네트워크 결과 바인딩)도 엔티티가 아니다.
`_masked_evaluation`은 `interp._entity_id_for_binding(binding)`으로 `ref`의
바인딩 이름이 어느 Entity에서 왔는지 찾는데, `as <name>`으로 준 이름은 그
역방향 맵(`binding_name(entity) -> entity.id`, RFC-0027 §2의 이름 충돌 검사가
지켜 주는 바로 그 유일성 덕분에 안전하게 조회된다)에 없으므로 `None`이
돌아오고 `entry`가 원값 그대로 반환된다 — **코드 변경이 필요 없다**, 기존
`input.*` 경로가 이미 답을 갖고 있었다. 이 RFC가 갱신하는 것은 텍스트뿐이다:
네트워크 결과 바인딩 필드(`paymentResult.status`, `paymentResult.<bodyKey>`,
§3의 평탄화된 값)는 가드 평가 트레이스(`evaluations`)에서 **마스킹되지
않는다** — 바디 필드에 토큰이나 카드번호 같은 sensitive 값이 담겨도 그대로
trace에 남는다는 뜻이다. 이 RFC는 새 마스킹 메커니즘을 열지 않는다
(§Open Questions 5) — `input.*`과 같은 취급을 받는다는 것을 명시적으로
기록해 둘 뿐이며, 침묵보다 명시가 낫다(RFC-0025 §Motivation이 세운 원칙
그대로).

### 7. spec 스텁 — `call <target> returns <status>` (D4)

`impl/lnpl/spec.py`의 `GIVEN_FORMS`에 두 항목을 더한다:

```python
("network-stub", "call <target> returns <status>",
 "네트워크 응답 스텁(issue #76). status는 정수. 스텁 없는 target은 fake "
 "드라이버 기본값(200/빈 바디)을 결정적으로 받는다"),
("network-stub-body", "call <target> returns <status> body.<key> <value>",
 "네트워크 스텁에 바디 필드 하나를 더한다. 한 줄 한 필드 — `stored`가 "
 "행 필드를 쌓는 것과 같은 자리"),
```

**문법 위치**는 `given` 절의 `PhraseLine`(기존 `stored`와 같은 자리) —
렉서·파서 변경이 없다. `_check_given`이 `tokens[0] == "call"`을 인식해
4토큰(`call <target> returns <status>`) 또는 6토큰(`... body.<key> <value>`)
형태를 판정한다. `<target>`은 선언된 이름을 참조하지 않는 자유 문자열이다 —
`NetworkCall.target` 자체가 어떤 레지스트리에도 검사되지 않는 자유 문자열이기
때문이다(§2, `_derive_effect`의 `NetworkCall` 분기는 `_resolve_entity`를
부르지 않는다). `<status>`는 정수여야 한다(그 외 형태는 `SpecError`).

**의미.** `run_manifest`가 케이스마다 `{target: (status, body)}` 스텁 테이블을
`given`에서 조립해 `FakeNetworkDriver(stubs)`를 만들고, `Interpreter(document,
repo_rows=rows, network=stubbed_driver)`로 넘긴다. 드라이버 계약은 여전히
`status`/`body`를 따로 돌려준다(§1) — 평탄화(§3)는 `_run_effect`가 결과를
바인딩하는 시점에 일어나는 것이지, 스텁 테이블의 모양이 바뀌는 것이 아니다.
**스텁하지 않은 target은
fake 드라이버의 결정적 기본값(200/빈 바디)을 받는다** — D4의 "새 진단 없음"
결정 그대로다: 기본값 자체가 결정적이므로 재현성이 깨지지 않고, 스텁을
빠뜨렸다는 경고를 새로 만들 근거가 없다(RFC-0025 §4의 `aggregation-orphaned-list`와
달리, 빠진 스텁의 결과가 0이 아니라 200/빈 바디로 항상 같기 때문에 "의도하지
않은 값"이 될 위험이 구조적으로 작다).

**`empty repository`와의 상호작용 없음**: 네트워크 스텁은 저장소 상태가
아니므로 `empty repository`와 모순하지 않는다 — `_validate_given`의 기존
모순 검사를 넓힐 필요가 없다.

집계(RFC-0025 §9)와 같은 이유로 **새 `expect` 어휘는 없다** — `expect result
paymentResult.status == 500`이 기존 `_expect_result`(RFC-0012 §G12.7)로 그대로
단언된다. 네트워크 결과 바인딩이 `bindings`(§4)에 놓이기 때문이다.

### 8. mode B — 관측 클래스는 그대로, 아무것도 새로 계산하지 않는다 (D5/D9)

RFC-0025 §10이 세운 원칙이 여기 그대로 적용된다: **네트워크 결과 바인딩의
값(`status`, 바디의 평탄화된 필드들 — §3)은 RFC-0004의 네 관측 클래스(실행
순서+skips, 정책 결과, 관측 신호=effect kind, 마스킹) 중 어느 것도 아니다.**
RFC-0015의 산술
할당이 mode B에서 상수로 접히지 않는 것, RFC-0025의 집계 값이 mode B의 비교
대상이 아닌 것과 정확히 같은 이유로, `paymentResult.status`가 실제로 몇인지도
비교 대상이 아니다 — `_render_std`(mode B의 방출부)는 오늘도 `NetworkCall`
효과의 kind와 target만 구조적으로 낸다. 이 RFC는 mode B에 **새 계산을 더하지
않는다**: 실제 HTTP 호출도, fake 스텁 조회도, mode B는 하지 않는다.

**D9가 실제로 채우는 것.** mode B는 `NetworkCall`이 실패**하는지**는 여전히
정적으로 예측하지 않는다 — `NetworkCall`은 이미 `backend.py`의 `_failure_attempts`에서
"재시도 1회만"으로 취급되고(`kind in ("NetworkCall", "EventEmit"): return 1`),
RFC-0025 §10이 고친 `READ_OPS`/`fail_at` 스캔은 애초에 `RepositoryCall`
전용이라 `NetworkCall`을 건드리지 않는다 — 이 RFC 이전에도 이후에도
`NetworkCall`은 mode B의 정적 실패 예측에서 "성공한다고 가정" 취급이다(값이
아니라 **구조**만 mode B의 관심사이므로, 실행이 실패할지 자체를 예측할
근거가 없다 — 실 HTTP 응답은 빌드 시점에 알 수 없다).

`result` 필드(§2)는 `_render_std`가 전혀 읽지 않는다 — 코드 변경이 필요
없다는 것을 실측으로 확인했다(아래). 이유는 `differential.compare_observations`
자체에 있다: `observe_mode_a`는 `result["bindings"]`를 관측에 싣지만
`observe_mode_b`는 애초에 `"bindings"` 키를 만들지 않는다(mode B는 저장소도
네트워크도 상태를 갖지 않으므로 바인딩이라는 개념이 없다 — G12.6과 같은
자리). 네 비교 클래스 중 `bindings`를 직접 보는 것은 없다: 순서·skip은
스텝 이름만, 정책 결과는 `status` 문자열만, 관측 신호는 effect **kind**만,
마스킹은 `text`에 섞인 값이 SECRET_MARKERS를 포함하는지만 본다. 그래서
`result` 필드의 존재는 mode B의 구조적 출력에 어떤 영향도 주지 않고, 이
RFC는 `backend.py`를 전혀 건드리지 않는다.

**동치는 세 입력으로 증명한다, 단 가드 없이** (D5, 이슈 #64/#76의 완료
기준): 성공(200) / 5xx / 접속 실패(바인딩된 호출의 `status=0`)를
`paymentResult.status`를 **읽기만** 하고 **분기하지 않는** 워크플로
(`set order.failureCode to paymentResult.status` 뒤에 무조건 다음 스텝으로
진행)로 증명한다. 세 입력 모두 mode A에서는 `FakeNetworkDriver`의 스텁으로
서로 다른 `status`가 실제로 계산되어 `bindings`에 남지만, `differential`의
비교는 그 값을 보지 않으므로(위 문단) 세 입력 다 같은 결과
(`differential.verify`가 `ok=True`)를 낸다 — RFC-0025 §10의 집계 값과
정확히 같은 자리다. `_normalise_skips`(differential.py)의 ALLOW-list는 이
RFC가 건드리는 대상이 아니다 — 네트워크 결과 바인딩은 guard skip 레코드의
필드가 아니라 `bindings`에 놓이므로, 그 함수가 이미 관여하지 않는
영역이다.

**가드가 네트워크 결과를 읽으면 동치는 성립하지 않는다 — 실측으로 확인한
한계다.** `when paymentResult.status == 200`처럼 네트워크 바인딩 필드로
**분기**하는 워크플로를 같은 방법으로 검증하면 mode A/B가 실행 순서 자체에서
갈라진다: mode A는 스텁된 실제 `status`로 분기하지만, mode B의 가드 조건
평가(`backend.condition_field_names`/`repo_policy.seed_bindings`,
RFC-0012 §G12.6)는 **시드 규칙에서 정적으로 투영한 값**만 안다 — 시드
규칙은 저장소 상태를 위한 것이지 네트워크 응답을 위한 것이 아니므로,
투영할 값 자체가 없다(관측된 기본값은 0). 엔티티 필드 가드는 `repo_rows`가
mode A와 mode B 양쪽에 같은 값을 주므로 이 문제가 없다 — 네트워크 결과는
mode B가 재현할 시드 규칙이 아예 없는 첫 사례다. 이것은 버그가 아니라
`sqlite` 백엔드 경로가 이미 차동 검증 대상이 아닌 것(`docs/backends.md`
§6)과 같은 종류의, 원천적인 모델링 공백이다 — **가드가 네트워크 결과
바인딩의 필드를 읽는 워크플로는 `lnpl diff`의 대상이 아니다.** mode A
자신의 분기 동작(§3, §7의 spec 테스트)은 이 한계와 무관하게 완전히
검증된다 — 영향받는 것은 mode A/B 두 실행기 사이의 **동치 증명**뿐이다.
§Open Questions 6에 남긴다.

## Examples

### 골든 시나리오 "Login" (RFC-0007 §6)

`Login` 워크플로는 `call`/`request`를 쓰지 않는다 — 이 RFC가 다루는 기능을
쓰지 않으므로 정본은 참조만 하고 재정의하지 않는다. `examples/login.lir.json`은
불변이다.

### 골든 인접 예제 — 결제 승인/거부

```
entity Order
    field
        id UUID
        failureCode Integer

service Checkout
    policy
        timeout 5s

workflow ChargeCard
    find order
    call PaymentGateway as paymentResult
    when paymentResult.status == 200
        update order
    when paymentResult.status != 200
        set order.failureCode to paymentResult.code
    spec
        given
            stored Order id 1
            call PaymentGateway returns 200
        when
            chargeCard
        expect
            completed
            result paymentResult.status == 200
```

**5xx 경계** — 같은 워크플로, 스텁만 바꿔:

```
        given
            stored Order id 1
            call PaymentGateway returns 500 body.code 42
        when
            chargeCard
        expect
            completed
            result paymentResult.status == 500
            result order.failureCode == 42
```

**접속 실패 경계** — `--network http`로 존재하지 않는 호스트를 가리켰을 때
(spec이 아니라 `lnpl run`으로 관측되는 경계, mode A):

```
result["bindings"]["paymentResult"] == {"status": 0}
```

정본 픽스처(로컬 `ThreadingHTTPServer` 픽스처 포함)는 이 RFC가 만들지 않는다 —
Task order §02(드라이버 계약 테스트)·§05(spec)·§06(모드 B 동치)이
`impl/tests/`에 추가한다. RFC-0025가 남긴 것과 같은 순서다: 문서가 계약을
고정하고, 구현이 그 계약을 채우는 파일을 가져온다. §06의 동치 픽스처는 위
`ChargeCard`(가드로 분기)가 아니라 §8이 규정한 대로 **가드 없이** `status`를
`set`으로만 흘리는 변형을 쓴다 — 가드 분기 자체는 §8의 한계 밖이다.

### 컴파일 거부 — 잘못된 trailing 토큰

```
workflow BadCall
    call PaymentGateway to p
```

→ `LowerError`, rc=2: `line 2: call/request accepts either no trailing words
or 'as <name>', got ('to', 'p')`. `to`는 `set`의 것이지 `call`의 것이 아니다.

### 컴파일 거부 — 이름 충돌

```
entity Payment
    field
        id UUID

workflow BadBinding
    find payment
    call PaymentGateway as payment
```

→ `LowerError`, rc=2 — `payment`가 이미 `Payment` 엔티티의 단일 행 바인딩
이름이다(§2).

## Alternatives

| # | 검토한 대안 | 기각 사유 |
|---|------------|----------|
| 1 (D1) | **`--network`를 `serve.py`에도 노출한다** | 이슈 #64/#76의 DoD는 CLI(`run`)만 요구한다. serve 경로의 배선(요청별 드라이버 수명, 서버 기동 시 실 HTTP를 기본으로 켜는 것의 운영 위험)은 별도 결정이 필요한 독립 질문이다 — §Open Questions 2로 이월 |
| 2 | **모든 `call`을 자동으로 target 기반 이름에 바인딩한다**(`as` 없이도) | 후방 호환이 깨진다 — 기존 `call PaymentGateway`가 오늘 골든 무발화인 것은 아무것도 바인딩하지 않기 때문이다. 자동 바인딩은 이름 충돌 검사(§2)를 모든 기존 프로그램에 소급 적용하게 만들어, 이 RFC 이전에는 유효했던 문서를 컴파일 실패로 바꿀 수 있다. 명시적 `as`가 저자의 의도를 요구하는 것이 RFC-0025 §Alternatives 2가 이미 세운 것과 같은 판단이다 — 다만 그때는 "새 표기 없이 푼다"였고, 이번엔 새 표기(`as`)가 꼭 필요한 경우(단일 행과 같은 문법 위치를 쓰므로 이름을 명시해야 충돌 검사가 가능하다)라는 점이 다르다 |
| 3 (D3) | **실패도 값이 아니라 항상 `RunError`로 통일한다** | 이슈 #76의 핵심 요구를 언어로 표현할 수 없게 만든다 — "가드가 status로 분기한다"는 실패가 예외가 아니라 읽을 수 있는 값이어야 성립한다. 접속 실패를 전부 예외로 두면, "결제 실패를 저장하고 계속 진행"류의 흔한 패턴이 이 언어로 표현 불가능해진다 |
| 4 (D2) | **이름 충돌을 허용하고 우선순위 규칙(예: 네트워크 바인딩이 항상 이긴다)으로 해결한다** | RFC-0012 §G12.3이 이미 "충돌이 존재하지 않는다 — bare/한정 이름의 분리가 우선순위가 아니라 문법 형태로 이루어진다"고 선언했다. 우선순위 규칙을 도입하면 그 불변식이 깨지고, 같은 이름이 프로그램 순서에 따라 다른 것을 가리키는 조용한 오독을 만든다 — RFC-0025 §Alternatives 4가 "조용한 축소"를 기각한 것과 같은 이유 |
| 5 | **retry policy를 네트워크 실패 유형과 완전히 접합한다**(5xx는 재시도, 4xx는 안 함, 등) | RFC-0003 §Policy Enforcement가 이미 그 표를 규정해 두었지만, `_retryable`이 `NetworkCall`을 무조건 비재시도로 취급하는 것은 이 RFC 이전부터의 결정이고, 이슈 #64/#76의 DoD는 응답 바인딩과 실패 분기까지만 요구한다. 재시도 엔진을 실패 유형별로 다시 설계하는 것은 이 RFC 하나가 지기에는 범위가 다른 독립 작업이다 — §Open Questions 1로 이월 |
| 6 (D9) | **모드 B가 실제 HTTP 호출이나 fake 스텁 조회를 수행해 `status`/`body` 값을 계산한다** | RFC-0025 §10이 집계에 대해 확인한 사실이 여기서도 그대로 성립한다 — mode B의 방출부는 애초에 계산된 값을 SSA로 들고 있지 않고, 네트워크 응답 값은 RFC-0004의 네 관측 클래스 어디에도 없다. 게다가 mode B에서 실제 I/O를 수행하는 것은 "저장소 상태를 실행 시점에 정하지 않는다"(RFC-0012 §G12.6)는 원칙을 네트워크까지 넓히는 훨씬 큰 결정이며, 이슈 #64/#76 어느 완료 기준도 요구하지 않는다 |

## Open Questions

1. **retry policy와 네트워크 실패 유형의 완전한 접합.** RFC-0003
   §Policy Enforcement의 "실패 유형별 재시도 판정" 표(도달 전 실패/전송 후
   무응답/5xx/4xx)를 `NetworkCall`에 실제로 연결하는 것은 이 RFC의 범위
   밖이다(§Alternatives 5). `_retryable`은 오늘처럼 `NetworkCall`을 무조건
   비재시도로 둔다.
2. **`serve.py`에서의 `--network` 노출.** 서버 기동 인자, 요청별 드라이버
   수명, 운영 중 실 외부 호출을 기본으로 켜는 것의 안전장치는 별도 이슈다
   (§Alternatives 1).
3. **바디의 중첩 깊이.** 지금은 응답 바디의 **최상위 키만** 결과 바인딩에
   평탄화된다(`paymentResult.code`) — `Reference`가 두 조각까지만
   받으므로(RFC-0012 §G12.1) 중첩된 객체·배열 인덱싱은 이 문법 밖이다.
   그런 접근을 열려면 `Reference`를 다단 경로로 넓히는 별도의 문법
   개정이 필요하며, 이슈 #64/#76 어느 완료 기준도 요구하지 않는다.
4. **HTTP 메서드 선택.** 지금은 `POST` 고정이다(§Reference-level
   Specification/1). `GET`/`PUT`/`DELETE` 등을 프로그램이 선언하게 하려면
   `NetworkCall`에 새 필드(예: `method`)가 필요하며, 이슈 #64/#76은 이를
   요구하지 않는다.
5. **네트워크 결과 바인딩 필드의 마스킹.** §6이 기록했듯 이 이름공간은 지금
   마스킹되지 않는다. 바디의 평탄화된 필드가 실제로 sensitive 값을 담는
   사례가 나오면, 그 필드를 마스킹 대상으로 선언하는 문법(예: `capability`
   선언에 sensitive 필드 목록을 붙이는 것)이 별도로 필요하다.
6. **네트워크 결과 바인딩을 읽는 가드의 mode A/B 동치.** §8이 실측으로 확인한
   한계다 — mode B는 네트워크 응답을 재현할 시드 규칙이 없으므로,
   `when <networkBinding>.<field> ...` 형태의 가드가 있는 워크플로는
   `lnpl diff`의 비교 대상이 아니다(값이 아니라 **분기 자체**가 갈린다는
   점에서 RFC-0025의 집계 값 제외보다 근본적이다). mode B가 그런 가드를
   무엇으로 평가해야 하는지(항상 거짓으로 고정? 컴파일 시점에 거부?
   네트워크 스텁을 빌드 시점 상수로 받는 새 배선?) — 이 RFC는 결정하지
   않는다. 이슈 #64/#76의 완료 기준은 mode A의 분기(§3, §7)만 요구한다.

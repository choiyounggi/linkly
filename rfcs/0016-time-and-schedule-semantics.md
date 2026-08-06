# RFC-0016: 시간 값 의미론과 스케줄 트리거

## Status

- Status: **Accepted** (RFC-0016, 2026-08-06)
- Updates: RFC-0001 §Appendix A/A.4 Node catalogue(`Event.source`에 스케줄 분기 1종 추가), RFC-0002 §Full grammar(`EventSource`·`Duration` 생산규칙), RFC-0008 §Reference-level Specification/1. Full Grammar(`Condition` 피연산자의 타입 규칙)

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목한다. 가드 조건의 피연산자 타입 규칙은
RFC-0015 §Reference-level Specification이 "Integer 한정"으로 세웠고 이 문서가 그것을
**차원(dimension) 규칙으로 대체**한다. 표현력을 **추가**할 뿐 기존에 컴파일되던 형태의
의미를 바꾸지 않는다(규칙 2) — 다만 RFC-0015가 `DateTime`을 "평가기 없음"으로 거부하던
문면은 이 문서가 무효화한다. 그 형태는 **여전히 거부되지만 사유가 다르다**(아래 §3).

`when`/`until`의 실행 의미(RFC-0008 §2, RFC-0014가 갱신), skip의 관측 계약(RFC-0014),
값 도메인(RFC-0015 §Value domain, i64)은 지목하지 않는다. 시간 값은 그 계약들을
**그대로** 탄다.

번호가 0016인 이유: 0015까지가 점유되어 있다. RFC-0007 §3은 번호 재사용을 금지한다.

## Motivation

2026-08-05 프로덕션 준비도 실측(`qa/REPORT.md`)이 남긴 두 공백이다.

**t2 F-5 — "결제 후 30일 이내 환불"을 쓸 수 없었다.** 저작자는 세 번 시도했다.
`refund.requestedAt - payment.createdAt <= 30d`는 `30d`가 유효한 피연산자가 아니어서
거부됐다(기간 단위가 `ms`/`s`/`m`에서 끝났다). `payment.createdAt <= 43200m`은
컴파일을 통과한 뒤 런타임에서 `Cannot compare non-numeric` 으로 죽었다. 남은 길은
`ageDays Integer` 필드를 미리 계산해 넣고 `when payment.ageDays <= 30`을 쓰는 것뿐인데,
이것은 **행의 나이를 갱신할 책임을 플랫폼 밖(데이터 적재층)으로 옮긴다.** 그 필드는
누군가 매일 갱신해 주지 않으면 조용히 틀린다.

**t3 F-2 — "매일 자정 실행"에 어휘가 없었다.** `schedule`·`cron`·`daily`·`timer`·
`midnight`·`interval`은 생성 참조 3개 파일에 대해 **0 hits**다. 유일하게 존재하는
비슷한 이름 `performance batch`는 파싱되지만 집행 매트릭스가 `unenforced`로 적고 있는,
바로 그 함정이다 — 언어 안에 우회가 없었다.

두 공백은 같은 뿌리를 갖는다. 언어에는 값이 있었지만 **시간이라는 값**이 없었다.

## Guide-level Explanation

시간창은 새 절이나 새 동사를 요구하지 않는다. RFC-0015가 세운 가드 문법이 이미
`<값> <비교> <값>`이고 값에 이항 산술 하나를 허용하므로, 넓힐 것은 **피연산자의 타입**
하나뿐이었다.

```lnpl
entity Payment
    field
        id UUID
        createdAt DateTime

entity Refund
    field
        id UUID
        requestedAt DateTime

workflow RefundPayment
    read payment
    when input.requestedAt - payment.createdAt <= 30d
    create refund
```

두 `DateTime`을 빼면 **경과 시간**이 나오고, 그것을 `30d`와 견준다. `ageDays` 같은
파생 필드가 사라진다 — 나이는 이제 가드가 계산하고, 갱신할 것이 없다.

**"지금"은 이미 표현할 수 있다.** 위의 `input.requestedAt`이 그것이다. 호출자가 순간을
payload로 주입하면 두 모드가 기존 i64 파라미터 채널로 **같은 값**을 본다. 언어에 벽시계
원시값(`now`)을 넣지 않은 이유는 §Alternatives에 있다.

기간 단위에 `h`와 `d`가 생겼다: `ms` `s` `m` `h` `d`.

배치 트리거는 기존 `event` 선언의 소스 형태로 들어온다.

```lnpl
event DailyRollup on schedule daily at 00:00 UTC
```

**이 선언은 집행되지 않는다.** 스케줄러가 없다. 선언은 IR과 OpenAPI의
`x-lnpl-schedules`까지 도달하고 거기서 멈추며, 컴파일할 때마다 그 사실을 진단으로
말한다. 실행기는 이슈 #26(서빙 계층)이 소유한다. 이 문서가 트리거를 언어에 넣으면서도
집행 상태를 함께 발행하는 이유는 t3 F-2가 지적한 함정 — 이름은 있고 아무 일도 하지
않으며 **아무 말도 하지 않는** 선언 — 을 되풀이하지 않기 위해서다.

## Reference-level Specification

### 1. 문법 델타

RFC-0002 §Full grammar와 RFC-0008 §1에서 **바뀌는 생산규칙만** 적는다.

```ebnf
(* 값: 기간 단위 테이블만 넓어진다 *)
Duration     ::= Integer ('ms' | 's' | 'm' | 'h' | 'd')

(* 이벤트 소스: 분기 하나 추가 *)
EventDecl    ::= 'event' PascalName EventSource? EOL
EventSource  ::= 'on' PascalName ('create' | 'update' | 'delete')
               | 'on' 'schedule' Recurrence 'at' TimeOfDay Zone
Recurrence   ::= 'daily'
TimeOfDay    ::= Digit Digit ':' Digit Digit          (* 00:00 ~ 23:59 *)
Zone         ::= 'UTC'
```

`Guard`·`Condition`·`Comparison`·`Value`·`Operand`·`ArithOp`·`Reference`·`AssignStep`은
바뀌지 않는다.

`h` = 3600000 ms, `d` = 86400000 ms. 주(`w`)·월·년은 넣지 않는다: 월과 년은 길이가
가변이라 정수 상수로 정의할 수 없다.

### 2. 시간 값의 인코딩

비교·산술에 들어가는 `DateTime`은 **UTC epoch-millisecond i64**로 인코딩된다.
RFC-0015 §Value domain의 i64 계약을 그대로 쓰며, 새 값 채널을 열지 않는다.

인코더는 `condition.encode_instant()` **하나**다. mode A(`interp.eval_value`)와
mode B(`backend.encode_condition_value`)가 둘 다 이 함수를 호출한다 — 두 번째 파서는
두 번째 문법이므로.

**존 지정자는 필수다.** `Z`(또는 `z`)나 수치 오프셋(`+09:00`/`+0900`)이 없는 값은
비교에 들어갈 수 없다. 존 없는 타임스탬프는 읽는 기계의 존에 묶여 **기계마다 다른
순간**을 가리키므로, 비교할 단일 값이 없다. 존 약어(`KST`, `EST`)도 받지 않는다 —
모호하다. 오프셋은 UTC로 정규화된다. 소수 초는 밀리초로 절단한다(내림).

선언·저장·와이어 표면은 바뀌지 않는다. `DateTime`은 계속 RFC 3339 문자열이고
OpenAPI `format: date-time`이다. **정수는 평가 채널 안에만 존재한다.**

`types.py`의 `DATETIME_RE`(필드 검증 규칙)는 이 RFC가 건드리지 않는다. 존 요구는
비교 경계에서만 적용된다 — 필드 검증 전반을 조이는 것은 별개의 변경이다.

### 3. 피연산자의 차원 규칙

RFC-0015의 "Integer 한정"을 **차원 규칙**이 대체한다.

- `instant` — 선언 타입이 `DateTime`이거나 base가 `DateTime`인 refinement
- `scalar` — `Integer`, base가 `Integer`인 refinement, 정수 리터럴, **Duration 리터럴**

| 식 | 결과 |
|----|------|
| `instant - instant` | `scalar` (경과 밀리초) |
| `instant + scalar`, `instant - scalar` | `instant` |
| `scalar ± scalar` | `scalar` |
| `instant + instant` | **컴파일 거부** |
| `<X> <cmp> <Y>`, `dim(X) == dim(Y)` | 허용 |
| `<X> <cmp> <Y>`, `dim(X) != dim(Y)` | **컴파일 거부** |

선언 타입을 문서에서 알 수 없는 피연산자(맨이름)는 어느 차원도 아니며, 오늘과 같이
정적 검사를 통과하고 런타임이 판정한다. **신규 거부가 생기지 않는다.**

이 규칙이 t2 F-5 ③(`payment.createdAt <= 43200m`)을 `instant` vs `scalar`로 거부한다.
RFC-0015도 이 형태를 거부했으나 사유가 "DateTime은 평가기가 없다"였다. 이제 평가기가
있으므로, 거부 사유는 **두 양이 같은 종류가 아니라는 것**이다.

`Money`와 합성 타입은 여전히 어느 차원도 아니며 컴파일 거부다(RFC-0015 §D6 유지).

### 4. 스케줄 트리거

**IR.** `Event.source`가 두 분기의 `oneOf`가 된다. 엔티티 소스는 오늘의 shape 그대로다.

```json
{ "kind": "Event", "id": "event.daily.rollup", "name": "DailyRollup",
  "source": { "every": "daily", "at": "00:00", "zone": "UTC" } }
```

`required: ["every","at","zone"]`, `additionalProperties: false`.
엔티티 소스 문서는 바이트 동일하게 유효하다.

**OpenAPI.** 문서 루트의 `x-lnpl-schedules` 확장에 실린다. 스케줄이 없으면 키 자체가
없으므로 이 RFC 이전 문서의 출력은 바이트 동일하다.

```json
"x-lnpl-schedules": [
  { "event": "event.daily.rollup", "every": "daily", "at": "00:00",
    "zone": "UTC", "enforcement": "unenforced" }
]
```

스케줄은 HTTP operation이 **아니다.** 경로를 만들지 않는다 — 아무도 서빙하지 않는
엔드포인트를 계약에 넣는 일이 되기 때문이다. `enforcement` 값은 집행 매트릭스에서
읽는다(문서가 코드에 없는 상태를 주장할 수 없도록).

**집행.** `ENFORCEMENT[("event","schedule")] = ("unenforced", …)`. 스케줄 소스를 가진
`event`마다 `declared-not-enforced` 진단(severity `warning`)이 **반드시** 발생한다.

**실행기는 이 RFC의 범위 밖이다.** 언어 표면·IR·문서 표면·관측 신호까지가 여기서
정해지고, 실제로 발화시키는 주체는 이슈 #26(서빙 계층)이 소유한다. 이 문서는 스케줄이
언제 발화하는지, 겹치면 어떻게 되는지, 다운타임 뒤 따라잡는지를 **정의하지 않으며,
정의하지 않았음을 명시한다** — 언어가 미리 정하면 실행기가 못 지킬 약속이 된다.

### 5. mode A/B 등가

| 관측 클래스 | 판정 |
|---|---|
| 실행 순서 + i44 `skips` | **반드시 일치** — 시간 비교는 기존 i64 파라미터 채널을 탄다 |
| 정책 결과(status/attempts) | **반드시 일치** |
| 관측 신호(effects) | 불변 — 시간 문법은 새 effect를 만들지 않는다 |
| 마스킹 | 불변(i43) |
| 스케줄 트리거 | **비교 대상 아님** — 워크플로 스텝을 만들지 않아 두 모드 모두 관측할 것이 없다 |
| 명령 선택(subi/cmpi 형태) | 허용된 차이 |

등가 주장의 범위: "시간 값이 두 모드에서 같은 i64로 인코딩되고, 같은 스텝 집합과 같은
status를 낸다." **스케줄의 실제 발화는 어느 모드도 관측하지 않으므로 등가 주장에
포함하지 않는다.**

### 6. 실패·거부 신호

새 결과 클래스를 만들지 않는다.

- **시간창 가드가 거짓** → i44 계약 그대로: `status`는 `completed`, `skipped` 레코드 +
  `guard-skipped-steps` 진단 + `--strict` rc=2.
- **시간 값 실패**(존 없음, 형식 불량, i64 밖) → mode A는 `RunError`, CLI가
  `runtime error:` rc=3으로 보고한다. 이것은 잘못된 조건 값이 이미 갖고 있던 경로다
  (RFC-0016 이전의 `Cannot compare non-numeric`이 같은 길을 갔다). mode B는
  `BackendError`(rc=4). 스텝 실행 중 실패의 계약(`status: failed`, rc=1)과는 다르다 —
  가드는 스텝 목록을 펼치는 동안, 어떤 스텝도 실행되기 전에 평가된다.

## Examples

30일 환불 창, 경계 포함(`<=`는 포함이다):

```lnpl
workflow RefundPayment
    read payment
    when input.requestedAt - payment.createdAt <= 30d
    create refund
```

| `requestedAt - createdAt` | 판정 |
|---|---|
| `30d - 1ms` | 창 안 — `create refund` 실행 |
| 정확히 `30d` | 창 안 (포함) |
| `30d + 1ms` | 창 밖 — 스킵, `status`는 `completed` |
| `0` (동시각) | 창 안 |
| 음수 (환불이 결제보다 앞섬) | 창 안 — 이 창은 **늦음**을 제한하지 순서를 제한하지 않는다 |

거부되는 형태:

```lnpl
when payment.createdAt <= 43200m       # instant vs scalar — 컴파일 거부
when payment.createdAt + input.requestedAt <= 30d   # instant + instant — 거부
event X on schedule weekly at 00:00 UTC             # 주기는 daily뿐
event X on schedule daily at 24:00 UTC              # 시각 범위 밖
event X on schedule daily at 00:00 Asia/Seoul       # 존은 UTC뿐
```

스케줄 트리거와 그 IR:

```lnpl
event DailyRollup on schedule daily at 00:00 UTC
```

```json
{ "kind": "Event", "id": "event.daily.rollup", "name": "DailyRollup",
  "source": { "every": "daily", "at": "00:00", "zone": "UTC" } }
```

컴파일이 함께 내는 진단:

```
warning declared-not-enforced at event.daily.rollup
  subject: event schedule
  message: declared but unenforced: no scheduler runs it; the declaration
           reaches the IR and the OpenAPI schedule metadata only —
           issue #26 (the serving layer) owns the executor
```

## Alternatives

1. **epoch-day 정수 인코딩 — 기각.** 하루 단위로 절단하면 09:00과 23:59가 같은 값이
   되어, "30일 이내"의 경계가 **호출 시각에 따라 하루 흔들린다.** i64에 epoch-ms가
   약 2.9억 년 들어가므로(2^63-1 ms) 절단이 사줄 범위 이득도 없다. 밀리초 인코딩은
   경계를 정확히 단언할 수 있게 하고, 그것이 시간창 정책의 요점이다.

2. **`instant`/`duration`/`number` 3차원 격자 — 기각(이번에는).** Duration 리터럴은
   문자 그대로 밀리초의 i64 정수이고, 가드에서 Duration을 쓰는 기존 프로그램은 이
   저장소에 0건이다. 3차원으로 나누면 `stock <= 30d` 같은 형태에 **새 거부만 생기고
   이슈 #49가 요구한 것은 하나도 더 닫히지 않는다.** §Open Questions로 이월.

3. **벽시계 `now` 원시값 — 기각.** 재현성과 모드 등가를 동시에 깨뜨린다. mode B의
   컴파일된 모듈은 벽시계를 관측하지 않으므로 `now`를 담은 프로그램은 두 모드가 다른
   값을 본다. differential은 그 차이를 회귀로 보고할 수밖에 없다. 대신 **주입식**을
   택했다: 호출자가 순간을 payload 필드로 넘기면 기존 i64 파라미터 채널로 두 모드가
   같은 값을 본다. 이슈 #49가 요구한 30일 창은 그것으로 완전히 닫힌다.

4. **IANA 존 이름(`Asia/Seoul`) — 기각(이번에는).** 임의의 IANA 이름을 받으려면 tz
   데이터베이스를 조회해야 하는데, 최소 컨테이너 이미지에는 지역 존 설정이 없다.
   그러면 **컴파일러가 받아들이는 언어가 빌드 기계마다 달라진다** — 존을 숨은 입력으로
   두는 바로 그 결함이다. UTC는 "하루 정확히 한 번 발화"의 정답이기도 하다: DST가 있는
   존의 `02:30`은 봄에는 존재하지 않고 가을에는 두 번 온다. §Open Questions로 이월.

5. **cron 식(`0 0 * * *`) — 기각.** cron 식은 그 자체로 하나의 언어다. 닫힌 어휘
   원칙과 정면으로 충돌하고, 두 모드가 똑같이 해석해야 할 두 번째 파서를 들여온다.

6. **새 최상위 선언 `schedule` — 기각.** `event`는 이미 "무엇이 이 이벤트를
   생산하는가"를 소스로 답하는 선언이다. `on Order create`가 엔티티 변경이라면
   `on schedule daily`는 시각이다. 새 최상위 키워드는 같은 개념을 두 자리에 두게 된다.

7. **트리거를 아예 넣지 않고 스코프 제외로 기록 — 기각.** 이슈 #49의 완료 기준 [3]이
   허용하는 선택지였다. 그러나 실측 결과 기존 `event ... on <Entity> create`가 **이미**
   IR까지만 가고 실행되지 않는 트리거였다. 스케줄 트리거를 같은 자리에 얹으면 집행
   수준이 기존 트리거와 정확히 같아지므로 새로운 거짓말을 만들지 않으며, 집행 매트릭스와
   진단이 그 사실을 말한다. 선언을 넣는 쪽이 저작자에게 더 정직하다.

## Open Questions

1. **엔티티 소스 트리거의 집행 상태.** `on <Entity> create`도 오늘 아무것도 발화하지
   않는다. 집행 매트릭스에 행을 주는 것이 맞지만, 그러면 기존 문서의 모든 `event`
   선언에서 새 경고가 나오기 시작한다 — 이슈 #49가 요구하지 않은 동작 변경이다.
   실행기(#26)와 함께 정하는 편이 낫다.

2. **IANA 존.** tz 데이터베이스를 벤더링하면 `Asia/Seoul`을 받을 수 있다. 그때
   §Alternatives 4의 근거가 해소된다. DST 경계에서 "하루 한 번"이 깨지는 문제는
   그대로 남으므로, 받아들이더라도 경고를 함께 내야 한다.

3. **`hourly`/`weekly`/`monthly`.** `daily` 하나로 시작한 이유는 이슈가 그것만
   요구했기 때문이다. 넓히는 일 자체는 테이블 행 추가지만, `monthly`는 "31일이 없는
   달"이라는 판정을 요구한다.

4. **3차원 차원 격자.** §Alternatives 2. `stock <= 30d`를 거부하려면 Duration을
   `scalar`에서 떼어내야 하고, 그것은 기존에 컴파일되던 형태에 대한 새 거부다.
   RFC-0007 §2.2 규칙 2에 따라 별도 RFC가 필요하다.

5. **스케줄 실행기의 의미론(#26이 소유).** 언어가 정하지 않기로 한 것들의 목록이며,
   실행기를 만들 때 반드시 답해야 한다: 이전 실행이 안 끝났을 때 겹쳐 도는가
   (동시 실행 허용 / 건너뜀 / 이전 것을 죽임), 건너뛴 실행을 나중에 따라잡는가, 그리고
   따라잡는다면 어느 시각 범위를 처리하는가. 스케줄러는 결국 겹치므로 핸들러의 멱등성은
   그 답과 무관하게 요구된다.

6. **주입식 `now`의 승격.** 지금은 관례다 — 호출자가 payload 필드로 순간을 넘긴다.
   `input.<field>`가 `DateTime`임을 문서가 알고 있으므로, "이 필드가 실행 시각"이라는
   표식을 언어가 갖는 편이 나을 수 있다. 그 표식이 생기면 서빙 계층이 자동으로 채울 수
   있고, 재현성은 여전히 호출자가 값을 고정할 수 있다는 사실에서 나온다.

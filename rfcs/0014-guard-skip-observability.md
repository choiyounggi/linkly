# RFC-0014: 가드 스킵의 관측 가능성

## Status

- Status: **Accepted** (RFC-0014, 2026-08-06)
- Updates: RFC-0008 §Reference-level Specification/2. Guard Runtime Semantics
- Updated-by: RFC-0027 (§Reference-level Specification/2.4 스킵 레코드), RFC-0028 (§Reference-level Specification/2)

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목한다. 가드의 실행 의미론은
RFC-0003 §Guard에 있었으나 RFC-0008 §2가 그 절을 이미 갱신했으므로, **효력 있는
계약은 RFC-0008 §2**이고 이 문서는 그 절만 갱신한다. RFC-0003 §Guard 본문과는
모순하지 않는다 — 이 개정은 기록 의무를 **추가**할 뿐 `when`/`until`의 실행 의미를
바꾸지 않는다(규칙 2).

RFC-0008 §5 Differential Equivalence는 지목하지 **않는다.** 그 절은 이미
"skip 집합"과 "`until` 라운드 수"를 실행 순서 분류 안에서 비교하라고 규정하고
있으며, 이 개정에 수반한 구현은 그 규정의 **이행**이지 변경이 아니다.

번호가 0013이 아니라 0014인 이유: 0013은 `main`의 RFC-0013(Step Attempt
Ceiling)이 이미 점유했다. RFC-0007 §3은 번호 재사용을 금지한다.

## Motivation

이슈 #44는 두 증상을 보고한다. 둘 다 "선언한 것이 실행되지 않았다"는 사실이
관측되지 않는 문제다.

**증상 ① — 스킵이 성공으로 위장된다.** 가드가 거짓이면 피가드 스텝이 실행되지
않는데, 워크플로는 `completed`·rc=0으로 끝난다. 재고 부족 주문이 "성공"으로
완주하고(t1 F-5), 한도 초과 결제의 거절과 승인 성공이 최상위 신호로 구별되지
않는다(t2 F-6). 실측된 유일한 흔적은 `result["skipped"]`의 IR 노드 id 나열과
trace의 INFO 한 줄뿐이며, 어느 쪽도 문서화된 계약이 아니었다.

**증상 ② — 두 스킵 경로가 비대칭이다.** RFC-0008 §2.1은 `when`의 거짓 분기에
"건너뛴 사실은 trace에 기록된다"는 의무를 두지만, §2.2의 `until`에는 같은 의무가
없다. 그래서 조건이 처음부터 참이어서 **0라운드**로 끝난 `until`은 아무 표지도
남기지 않았고, "실행 안 됨"의 두 경로가 트레이스에서 구별되지 않았다(t4 F-9).

증상 ①이 status 어휘의 문제로 보이는 것은 착시다. 가드 스킵을 모두 "거부"로
승격하면 `when tokenCache missing`(§5.2 `examples/guarded.lnpl`)의 **캐시 적중**
스킵까지 거부로 오분류된다 — 그것은 정상 최적화다. 어떤 가드가 정책 게이트인지
**선언**하는 문법이 언어에 없으므로, 런타임은 "스킵됐다"까지만 사실로 말할 수
있고 "거부됐다"의 판정은 그 사실을 읽는 쪽에 남는다. 따라서 이 개정은 스킵을
**관측 가능한 1급 신호**로 만들되 terminal status 어휘는 건드리지 않는다.

## Guide-level Explanation

가드가 피가드 항목을 실행하지 않으면, 실행 결과에 그 사실이 **레코드 하나**로
남는다. `when`이 거짓이어서 건너뛴 경우와 `until`이 한 라운드도 돌지 않은 경우가
같은 모양의 레코드를 만든다.

```
$ lnpl run order.lnpl --payload stock-0.json
workflow PlaceOrder -> completed  (1 step(s) skipped by guard)  (6ms, correlation_id=cid-0001)
  step validate order      6ms attempts=1 [Validation -]
  skipped by `when stock > 0`: create order
```

같은 프로그램을 재고가 있는 payload로 돌리면 첫 줄에 스킵 표기가 없다. 이것이
"성공과 거부를 최상위 신호로 구별한다"의 의미다.

세 결과가 서로 다른 신호를 갖는다:

| 결과 | 언제 | `status` | 신호 | 기본 rc | `--strict` rc |
|------|------|----------|------|---------|---------------|
| 완주 | 실패도 스킵도 없음 | `completed` | 스킵 레코드 없음 | 0 | 0 |
| 거부 | 가드가 거짓이어서 스텝이 실행되지 않음 | `completed` | 스킵 레코드 ≥1 + `guard-skipped-steps` 진단 + 첫 줄의 카운트 | 0 | **2** |
| 실패 | 검증 위반·저장소 실패·데드라인 초과 | `failed` | `failed at: <스텝명>` | 1 | 1 |

거부가 `failed`가 아닌 이유는 실패가 아니기 때문이다 — 프로그램이 지시한 대로
가드가 판정했고, 어떤 스텝도 실패하지 않았다. 거부가 rc를 기본값에서 바꾸지 않는
이유는 캐시 적중 스킵이 정상 경로이기 때문이며, 하드 게이트가 필요한 호출자는
`--strict`로 엄격도를 **선택**한다.

## Reference-level Specification

아래는 RFC-0008 §Reference-level Specification/2. Guard Runtime Semantics를
**치환한 최종 텍스트**다(RFC-0007 §2.2 규칙 4). 상수 정의와 §2.3 실행 의미 표는
변경 없이 유지되므로 그대로 다시 싣는다.

### 2. Guard Runtime Semantics (RFC-0003 §Guard 갱신)

**상수 정의:**
```
_UNTIL_ROUND_CAP = 16
```

이 상수는 모드 A(런타임 평가) 및 모드 B(컴파일)가 모두 따라야 하는 계약값이다.

#### 2.1 `when` 모드

조건을 **1회 평가**한다. 참이면 피가드 항목을 실행하고, 거짓이면 건너뛴다.
건너뛴 사실은 trace에 기록되며, **아울러 §2.4의 스킵 레코드 하나를 남긴다.**

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

실행 결과는 **스킵 매니페스트**를 가진다. 피가드 항목을 실행하지 않은 가드마다
레코드가 하나씩, 가드를 만난 순서대로 들어간다.

| 필드 | 의미 |
|------|------|
| `guard` | 가드 노드의 IR id. 모드 A 전용 — 모드 간 비교에서 제외한다 |
| `mode` | `"when"` 또는 `"until"` |
| `condition` | 정규화된 조건 문자열(RFC-0008 §4) |
| `steps` | 그 가드가 감싼 **모든 WorkflowStep의 이름**, 선언 순서. 중첩 블록(`Concurrency`·`Pipeline`)까지 하강해 수집한다 |
| `rounds` | `when`이면 없음(`null`), `until` 0라운드면 `0` |

`steps`가 이름이고 id가 아닌 이유는 규범적이다. 모드 B의 관측 표면에는 IR 노드
id가 없으므로(`step <index> <name>` 라인만 존재), 노드 id로 키잉된 매니페스트는
모드 B가 **원리적으로 생산할 수 없다**. 두 모드가 같은 신호를 관측해야 한다는
RFC-0004의 요구가 shape을 결정한다.

**status 어휘는 변경되지 않는다.** terminal status는 `completed`와 `failed`
둘뿐이며, 스킵은 status와 직교하는 신호다. 특히 스킵은 검증 실패·저장소 실패와
**다른 결과 클래스**다 — 후자는 `failed`이고 `failed_at`을 가진다.

#### 2.5 진단과 종료 코드 (신설)

스킵 레코드마다 진단 하나를 낸다: 코드 `guard-skipped-steps`, severity
`warning`. 진단은 기존 진단 채널을 그대로 쓴다 — 새 레코드 타입·누산기·포매터를
만들지 않는다.

기본 실행의 종료 코드는 바뀌지 않는다(스킵이 있어도 `completed`는 rc 0). 엄격도는
호출자가 고른다: `--strict`를 준 실행에서만 진단을 보고한 클린 종료가 rc 2로
승격된다. 이는 기존 `--strict` 게이트의 재사용이며 새 종료 코드 규약이 아니다.

#### 2.6 모드 A/B 동등성 (신설)

두 모드는 스킵을 **같게** 관측해야 한다. 비교는 `guard`를 제외하고 스텝 단위로
편 투영 위에서 이루어진다 — `{mode, condition, step, rounds}`. 모드 A는 레코드
하나를 그 `steps` 수만큼의 항목으로 펴고, 모드 B는 "계획에 있으나 출력에 없는
스텝"으로 같은 항목을 복원한다.

모드 B에서 `until`은 라운드 상한까지 언롤되지만, 조건은 실행 중 상수이므로 라운드
수는 0 아니면 상한이다. 따라서 **라운드 1의 부재만** 0라운드 스킵으로 센다.
라운드 2 이상의 부재는 정상 종료이며 항목을 만들지 않는다.

이 비교는 RFC-0008 §5가 이미 규정한 대로 RFC-0004의 **실행 순서 분류(1/4) 안에서**
수행한다. 새 비교 클래스를 만들지 않는다.

## Examples

### 예 1 — `when`이 거짓인 실행 (t1 F-5 / t2 F-6 동형)

```lnpl
entity Order
    field
        id UUID
        stock Integer
workflow PlaceOrder
    validate order
    when stock > 0
    create order
```

`stock = 0` payload로 실행하면 매니페스트는 다음 한 건을 갖는다:

```json
{"guard": "wf.place.order.guard.1", "mode": "when",
 "condition": "stock > 0", "steps": ["create order"], "rounds": null}
```

`stock = 1`이면 매니페스트는 비어 있고, 첫 출력 줄에 스킵 표기가 없다. 두 실행의
최상위 신호가 다르다는 것이 이슈 #44의 완료 기준이다.

### 예 2 — `until`이 0라운드인 실행 (t4 F-9)

<!-- lnpl-check: skip — drift: `step <이름>`은 pre-RFC-0002 폐기 문법이다 — Start/Loop/End는 실제 동사가 아니라 라운드 계수 의미론을 설명하려는 자리표시 스텝 이름인데, 미선언 동사는 강한 실패가 아니라 no-op 경고로 통과한다(컴파일러: "warning: unknown-verb ... step ... is outside VERB_LEXICON: this step derives no Effect and runs as a descriptive no-op"). 조각도 자리표시자(`...`)도 아니다 — 그럴듯한 낱말이 파싱에 성공하고 아무것도 하지 않는, AGENTS.md가 말하는 바로 그 실패 모드가 이 문서 예제 자체에서 재현된다. Accepted RFC 본문 직접 수정 금지 — 올바른 수정은 현재 문법으로 다시 쓰는 RFC-0007 Updates 개정이다 -->
```lnpl
workflow W
    step Start
    until counter >= 10
    step Loop
    step End
```

`counter = 100`이면 조건이 처음부터 참이므로 `step Loop`는 한 번도 실행되지
않는다. 개정 전에는 아무 표지도 남지 않았다. 개정 후:

```json
{"guard": "wf.w.guard.1", "mode": "until",
 "condition": "counter >= 10", "steps": ["step Loop"], "rounds": 0}
```

`counter = 0`이면 라운드가 실행되므로 레코드는 없다.

## Alternatives

### "거부"를 제3의 terminal status로 두는 안 (기각)

`status`에 `rejected`를 추가해 가드 스킵이 있는 실행을 그 값으로 끝내는 안을
검토했고 기각했다. 기각 사유는 반례다: `examples/guarded.lnpl`의
`when tokenCache missing`은 캐시가 **적중**했을 때 토큰 조회를 건너뛴다. 그것은
정상 최적화이지 거부가 아니며, 그 실행을 `rejected`로 표기하면 런타임이 참이
아닌 것을 주장하게 된다.

근본 원인은 언어에 있다 — 어떤 가드가 정책 게이트이고 어떤 가드가 최적화인지
**선언**할 문법이 없다. 그 문법이 생기기 전에 런타임이 대신 판정하는 것은
추측이다. 그래서 이 개정은 "스킵됐다"는 사실과 그 조건·스텝을 관측 가능하게
만드는 데서 멈추고, "거부인가"의 판정은 그 사실을 읽는 쪽에 남긴다.

하위 호환 비용도 같은 방향을 가리킨다. `spec` 블록의 `expect` 어휘는
`completed`/`failed` 둘뿐이고, 모드 B의 status는 종료 코드에서 파생되므로
(`rc == 0 ? completed : failed`) 제3의 값을 실을 자리가 없다.

### 스킵을 `failed`로 접는 안 (기각)

검증 실패와 같은 클래스로 만들면 두 사실이 하나의 신호로 뭉개진다. 검증 실패는
입력이 계약을 어긴 것이고 스킵은 계약이 지시한 분기다. 접으면 `retry` 정책이
스킵된 스텝에 적용되는 등 의미가 왜곡된다.

### 진단 대신 새 출력 채널을 만드는 안 (기각)

진단 채널은 "플랫폼이 이 프로그램이 말한 것을 하지 않고 있다"를 보고하기 위해
존재한다. 스킵은 정확히 그 클래스의 사실이며, 두 번째 채널을 만들면 그 채널이
해결한 문제(같은 사실을 두 가지 방식으로 표현하는 것)를 한 단계 위에서 재생산한다.

## Open Questions

1. **"거부" 판정의 소유자.** 이 개정은 스킵을 관측 가능하게 만들 뿐, 어떤 스킵이
   비즈니스적 거부인지는 여전히 호출자가 판정한다. 가드를 정책 게이트로 선언하는
   문법(그리고 그 게이트가 거짓일 때의 종결 의미)은 이슈 #47·#49의 값 의미론
   작업에 속한다. 그 작업이 도착하면 §2.4의 레코드가 그 판정의 입력이 된다.

2. **중첩 가드의 조건 손실.** 현행 문법은 가드 연쇄(`when` 다음 `when`)를
   파서에서 거부하므로 중첩 가드는 표현 불가능하다. 문법이 논리 결합이나 연쇄를
   허용하게 되면 모드 B의 언롤이 안쪽 조건을 바깥 조건으로 덮어쓰는 현행 동작이
   드러난다. 그 시점에 §2.6의 투영이 조건을 어떻게 담을지 재검토해야 한다.

3. **`repeat 0`.** 현행 문법의 `count`는 1 이상이므로 "선언됐으나 0회 실행"이
   `repeat`에서는 발생하지 않는다. `count`가 런타임 값에서 오게 되면 `repeat`도
   §2.4의 대상이 되어야 하는가?

# RFC-0034: NetworkCall 보상(compensation) 방식 결정 — `compensate` 절 + `rollback-escapes-network`

## Status

- Status: Draft

## Motivation

RFC-0032가 `policy rollback`을 `enforced`로 올렸다 — 그러나 §Open Questions ②가
스스로 명시하듯 그 보장은 **저장소 트랜잭션 경계까지만**이다: "외부
`NetworkCall`처럼 저장소 트랜잭션에 속하지 않는 효과의 실패 시 처리(사가·보상
트랜잭션)는 이 RFC가 명시적으로 배제한 범위다." `policy rollback`을 선언한
워크플로에 `NetworkCall` 스텝이 있으면, 그 호출은 실행됐고 되돌아가지 않는데
`rollback`이라는 이름은 "이 실행은 스스로를 되돌린다"고 계속 주장한다 —
linkly가 스스로 세운 원칙("선언과 집행이 어긋나면 기계가 말한다")이 여기서만
말이 없었다.

issue #112는 이것을 두 단계로 나눈다. **단계 1**은 그 침묵을 진단으로 바꾸는
것 — `rollback-escapes-network`(warning)이 이미 그 단계를 끝냈다
(`impl/lnpl/diagnostics.py`의 `CODES`/`SEVERITY_OF`, `impl/lnpl/lower.py`의
`_check_rollback_escapes_network`, `impl/tests/test_rollback_escapes_network.py`).
**단계 2**는 이슈 본문이 제시한 세 방식 — (a) 금지, (b) 명시적 보상 선언,
(c) outbox 방식 — 중 무엇으로 나아갈지 **결정**하는 것이다. 이 RFC가 그
결정이다. RFC-0007 §5(구현과 명세가 어긋났을 때)의 반대 방향 절차이기도
하다: 아직 구현되지 않은 것에 대해, 구현이 시작되기 **전에** 계약을 먼저
고정한다.

이 RFC는 **결정만 한다** — `compensate` 절 문법을 지금 추가하지 않는다
(§Alternatives, §Open Questions). 어휘 확장은 linkly의 닫힌 어휘 원칙상 별도
승인·구현 절차(Batch B)를 거쳐야 하고, 이 RFC가 그 절차의 입력이 되는 계약을
남긴다.

## Guide-level Explanation

오늘(이 RFC가 Draft인 동안) `policy rollback`을 선언한 서비스의 워크플로에
`call`/`request` 스텝이 있으면 컴파일러가 `rollback-escapes-network`
(warning)를 그 스텝 줄에 낸다 — 이것이 이미 채택되어 동작하는 부분이다.

이 RFC가 결정하는 것은 **그다음**이다: 저자가 "이 호출은 실패해도 스스로
되돌릴 방법이 있다"고 선언할 길을 열지, 아니면 `NetworkCall`을 `policy
rollback` 워크플로에서 영구히 금지할지. 답은 **하이브리드**다 — 아래
가상의(문법 미도입) 형태가 결정의 모양을 보인다:

```
workflow Pay
    call PaymentGateway as p
        compensate refundPayment    # 아직 문법에 없다 — 이 RFC는 결정만 한다
```

`compensate` 절이 있는 `call`/`request`는 `rollback-escapes-network`를
내지 않는다 — 실패 시 실행이 그 보상 액션을 실행한다는 계약을 진 것이므로.
`compensate` 절이 없는 `call`/`request`는 오늘과 동일하게 경고를 받는다.
즉 (a) 금지와 (b) 명시적 보상 선언을 **함께** 쓴다: 기본은 금지(경고로
신고)이고, 저자가 명시적으로 보상을 선언하면 그 금지가 풀린다. (c) outbox
방식(호출을 큐에 넣고 비동기로 처리)은 채택하지 않는다 — §Reference-level
Specification과 §Alternatives가 이유를 정밀화한다.

## Reference-level Specification

### 결정된 방식 — (b) 명시적 보상 선언 + (a) 기본 금지의 하이브리드

`policy rollback`을 선언한 서비스가 소유한 워크플로의 `NetworkCall` 스텝
(`call`/`request`)마다, 그 스텝에 향후 도입될 `compensate <동사> <대상>` 절이
있는지가 분기를 결정한다:

| 스텝의 상태 | 결과 |
|---|---|
| `compensate` 절 없음 | `rollback-escapes-network`(warning) — Task 01이 이미 구현·배포한 형태. 이 RFC가 Draft인 동안에도, 그리고 이 RFC가 Accepted된 뒤에도(문법이 아직 없으므로) 유일하게 발화 가능한 경로다 |
| `compensate` 절 있음 | 경고를 내지 않는다. 실행이 실패로 끝나면 런타임이 그 호출에 대해 선언된 보상 액션을 실행한다 (**구현은 이 RFC의 범위 밖 — §Open Questions에서 후속으로 넘긴다**) |

`compensate` 절의 정확한 문법(동사 어휘, 인자 형태, 워크플로 내 위치 제약)은
이 RFC가 정의하지 않는다 — 그것은 Batch B가 다룰 닫힌 어휘 확장이다. 이 RFC가
고정하는 것은 **그 절이 존재하면 이 진단을 침묵시킨다는 계약**과, 아래 세
미결 질문에 대한 답뿐이다.

### (c) outbox 방식의 기각 근거

issue #112 본문이 제시한 (c)는 `NetworkCall`을 커밋 후 처리되는 outbox
레코드로 바꿔 트랜잭션 경계 **안으로** 끌어들이는 방식이다(RFC-0032가 이미
`EventEmit`에 쓰는 것과 같은 수법). 이것은 `call`/`request`의 결과 바인딩
계약과 정면으로 충돌한다:

- RFC-0027 §2는 `call X as p`가 **동기** 결과를 `p.status`/`p.body` 등으로
  즉시 바인딩한다고 계약한다 — 같은 워크플로의 다음 스텝이 그 바인딩을 읽을
  수 있다.
- RFC-0030은 그 바인딩이 `create ... as name`과 같은 문법 위치를 공유한다고
  못박는다(이름 충돌 검사가 그 계약 위에 서 있다).
- outbox로 바꾸면 호출이 비동기가 된다 — 커밋된 **후**에야 실제로 나가므로,
  같은 실행 안에서 `p.status`를 읽는 다음 스텝은 그 시점에 응답이 존재하지
  않는다. 바인딩 자체가 성립할 수 없다.

`EventEmit`이 outbox로 갈 수 있었던 이유는 정확히 그것이 **바인딩이 없는**
발행-후-망각(fire-and-forget) 효과이기 때문이다(RFC-0003 §Execution Model
EventEmit 행) — `NetworkCall`은 그 성질을 공유하지 않는다. 이 비대칭이 (c)를
기각하는 근거다.

### 미결 질문 3개의 답 (issue #112가 요구)

① **보상 호출 자체가 실패하면?** 실행은 `Failed`로 종결한다(오늘의 실패
종결과 동일한 최종 상태). 다만 `failure_reason`에 보상 실패를 **원인 실패와
별도로** 명시하고, 보상되지 못한 호출의 목록을 canonical line(trace의 결과
요약 줄)에 싣는다 — 원인 실패 하나만 보이고 "그런데 보상도 못 했다"는 사실이
조용히 삼켜지는 것을 막는다. 미보상 호출이 있는 실행과 완전히 보상된 실행은
운영자가 trace만 보고 구분할 수 있어야 한다.

② **보상을 재시도하는가?** 한다 — 다만 `policy retry`(원래 스텝의 재시도
정책)와는 **독립된** 상한을 쓴다. 원래 호출의 재시도 횟수와 보상 호출의
재시도 횟수를 같은 카운터로 묶으면 "결제는 3번 재시도했는데 환불은 1번만
됐다" 같은 비대칭이 생긴다. 그리고 보상은 **멱등이어야 한다**는 것을 문서
계약으로 못박는다 — 재시도가 있는 한 정확히-한-번 실행을 보장할 방법이
없으므로, 계약의 책임을 (한 번만 실행되는 런타임이 아니라) "여러 번 실행돼도
안전한 보상 액션을 작성하는 저자" 쪽에 둔다. `policy retry`가 이미 같은
전제(effects are idempotent, `_check_derived_never_assigned` 근방 주석 참조)
위에 서 있으므로 새로운 종류의 요구가 아니다.

③ **`parallel` 블록 안의 `call`이 보상 대상이면?** **컴파일 에러**로
시작한다. 보상은 본질적으로 "무엇을 실행했는지"의 역순 되감기 개념을
요구하는데(나중에 성공한 것부터 되돌린다), `parallel`은 순서를 선언하지
않는다(issue #108, `performance parallel`이 오늘도 `UNENFORCED`인 이유와
같은 축) — 역순이 정의되지 않은 곳에 보상을 얹으면 어떤 순서로 되감을지
런타임이 추측해야 한다. 안전한 시작점은 "안 된다고 말한다"이지 "추측한다"가
아니다. `parallel` 실행 자체의 설계(issue #108)가 순서 보장 수단을 갖추면
이 제약은 재검토 대상이 된다 — 그전까지는 컴파일 에러가 유일한 답이다.

### D10 — 이 RFC는 구현하지 않는다

이 RFC가 Accepted 되어도 `compensate` 절은 파싱되지 않는다. 도입에는
`VERB_LEXICON`이 아니라 문법 자체의 확장(스텝에 붙는 새로운 하위 절)이
필요하고, RFC-0002(문법 정본)의 개정을 요구한다 — 그것은 이 RFC의 범위가
아니라 Batch B가 다루는 문법 변경 묶음의 일부다(linkly의 닫힌 어휘 원칙:
학습 데이터에 없는 새 키워드는 그럴듯하게 파싱되고 런타임은 조용히 무시할
위험이 있으므로, 문법 확장은 항상 그 자체로 검토 대상이다). 지금 이 RFC가
고정하는 것은 **방향과 계약**뿐이다 — 문법이 생겼을 때 그 문법이 무엇을
약속해야 하는지.

## Examples

골든 시나리오 "Login"(정본: `plans/rfc-suite/plan.md` §골든 시나리오
"Login"). Login은 `NetworkCall` 스텝이 없으므로 이 RFC의 영향을 받지 않는다
— `examples/login.lir.json`은 이 RFC로 재생성이 필요하지 않다.

**골든 인접 예제(가상, 미구현)** — Login이 다루지 않는 기능(RFC-0007 §6)이므로
별도 예제로 보인다. Task 01의 `rollback-escapes-network`는 이미 실제로 이
형태에서 발화한다(`impl/tests/test_rollback_escapes_network.py`의
`ONE_CALL_WITH_ROLLBACK`):

```
service Checkout
    policy
        rollback

workflow Pay
    call PaymentGateway
```

`compile`하면 `rollback-escapes-network`(warning)가 `call PaymentGateway`
줄을 지목한다. 이 RFC가 결정한 미래형은, `compensate` 문법이 도입된 뒤
아래처럼 바뀌면 그 경고가 사라지는 것이다(문법은 가상 — Batch B 몫):

```
workflow Pay
    call PaymentGateway as p
        compensate refundPayment
```

## Alternatives

**(a) `NetworkCall`을 `policy rollback` 워크플로에서 전면 금지 (컴파일
에러)** — 단독 채택은 기각. `rollback-escapes-network`가 이미 강한 신호
(warning, `--strict=warning`로 게이팅 가능)를 주므로 컴파일 에러까지 갈
필요는 저자에게 탈출구를 안 주는 것뿐이다 — 결제·배송처럼 네트워크 호출이
구조적으로 필요한 워크플로에 `rollback` 자체를 못 쓰게 만드는 부작용이 크다.
다만 **기본값**으로는 채택한다(`compensate` 없는 호출은 경고로 남는다) —
전면 금지가 아니라 "명시적으로 풀지 않는 한 금지"다.

**(c) outbox(비동기 큐) 방식** — 기각. §Reference-level Specification에
근거를 적었다: `NetworkCall`의 동기 결과 바인딩(RFC-0027 §2, RFC-0030)과
구조적으로 충돌한다.

**아무것도 하지 않는다(진단만 유지, 단계 2 자체를 열지 않는다)** — 기각.
issue #112 본문이 단계 2를 명시적으로 요구했고, 진단만으로는 "이 워크플로는
왜 항상 이 경고를 받는가"에 대해 저자에게 줄 답이 "네트워크 호출을 빼라"
하나뿐이다. 결제·배송처럼 빼는 것이 불가능한 경우를 위한 탈출구가 필요하다는
점이 issue #112가 단계 2를 요구한 이유이기도 하다.

## Open Questions

1. **`compensate` 절의 정확한 문법** — 동사 어휘(예: `compensate refundPayment`
   처럼 새 verb를 참조하는가, 아니면 새 하위 절 안에 인라인 워크플로 스텝을
   허용하는가), 인자 전달(원래 호출의 응답을 보상 호출이 읽을 수 있는가),
   워크플로 내 허용 위치(스텝에 붙는 하위 절인가, 별도 최상위 선언인가)는
   Batch B가 RFC-0002 개정으로 결정한다. 이 RFC는 "존재하면 경고를
   침묵시킨다"는 계약만 고정한다.
2. **보상 실행의 런타임 구현** — `run_workflow`가 실패 처리 경로에서
   보상 호출을 어떻게 스케줄하는지(RFC-0032의 `rollback()` 호출과 같은
   시점인가, 그 이후인가), `failure_reason`의 정확한 스키마(canonical line
   포맷)는 문법이 확정된 뒤 별도 RFC에서 정의한다.
3. **`parallel` 실행 순서 설계(issue #108)와의 재접속** — §Reference-level
   Specification ③이 지금은 컴파일 에러로 막았다. issue #108이 `parallel`의
   실행 순서 보장 메커니즘을 설계하면, 그 설계 위에서 이 제약을 완화할지는
   이 RFC가 결정하지 않는다 — #108의 몫이다.

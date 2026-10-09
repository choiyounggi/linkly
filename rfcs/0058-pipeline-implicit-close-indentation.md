# RFC-0058: 파이프라인 암묵 종결과 모순되는 들여쓰기의 거부

## Status

- Status: Draft
- Updates: RFC-0002 §Block structure (+RFC-0019)

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목하고, 규칙 5(연쇄 갱신)에 따라 이미
갱신된 절은 대상과 **직전 갱신 RFC를 모두** 지목한다. RFC-0002 §Block structure의
현행 텍스트는 RFC-0019의 §Reference-level Specification이다 — RFC-0002 파일의 본문은
RFC-0019 이전의 4항짜리 그대로이고 `> 갱신됨: RFC-0019` 표지만 달려 있다. 이 RFC는
그 RFC-0019 텍스트를 기준으로 3항에 하위 항목 하나(c)를 더한다. Draft이므로 대상
RFC에 `Updated-by:` 포인터를 달지 않는다(Accepted가 되는 시점의 일이다).

RFC-0019와 같이 **어떤 토큰열이 어떤 구조로 파싱되는가**는 그대로 두고, **어떤
프로그램이 수용되는가**만 좁힌다. §Full grammar의 생산규칙, §Lexical, 부록 A의
lowering 매핑은 지목하지 않으며 어느 것도 바꾸지 않는다.

이슈 #211 제안 1·2를 닫는다. 제안 3(RFC-0015 Open Question 1)과 4(`otherwise` 가지)는
이 RFC의 범위가 아니다.

## Motivation

2026-10-02 QA(main `c5e1679`, 이슈 #211 (3))에서 저자는 이렇게 썼다.

```
workflow PlaceOrder
    find product
    when product.stock >= input.quantity
    pipeline place
        create order as o
        call PaymentGateway as pay
        when pay.status == 200
            set o.paid to 1
        update order
```

컴파일은 rc=0, 진단 0건이었다. `lnpl run --dry-run`은 다른 구조를 보여 준다.

```
  step find product
  guard when product.stock >= input.quantity
    pipeline place
      step create order as o
      step call PaymentGateway as pay
  guard when pay.status == 200         ← pipeline이 여기서 닫혔다
    step set o.paid to 1
  step update order                    ← 어떤 가드에도 속하지 않는다
```

저자는 `update order`를 재고 가드 아래에 썼다고 믿는다. 실제로는 재고가 부족해도
실행된다.

원인은 RFC-0002 §Block structure 1항이다: `pipeline`은 명시적 종결 키워드가 없고 다음
키워드에서 저절로 닫힌다. 들여쓰기는 "안에 있다"고 말하지만 컴파일러는 그 `when`에서
파이프라인을 닫는다. RFC-0019는 같은 계보의 모순 둘(3항 a 가드 스코프, b spec 꼬리)을
거부하게 했으나 그 목록은 닫혀 있었고, **블록을 암묵 종결시키는 들여 쓴 제어
키워드**는 그 안에 없었다. `_check_guard_layout`(3항 a)도 이 경우를 보지 못한다 —
`when product.stock …`과 `pipeline place`가 같은 열이라 가드 쪽 레이아웃은 아무 말도
하지 않기 때문이다.

경고가 아니라 거부여야 하는 이유는 RFC-0019 §Motivation "왜 경고로는 부족한가"와 같다.

## Guide-level Explanation

RFC-0019의 세 줄 요약은 그대로다.

- 들여쓰기로 **구조를 만들 수는 없다.**
- 들여쓰기로 **구조를 반박할 수는 있다** — 이 개정은 반박의 세 번째 경우를 더한다.
- 레이아웃이 아무 말도 하지 않는 프로그램 — 전부 같은 열에 쓴 것 — 은 **영향받지
  않는다.**

열린 `pipeline`의 줄보다 깊은 열에 `when`/`until`/`repeat`/`pipeline`/`parallel`을
쓰면, 그 키워드는 파이프라인을 닫으면서 안에 있는 것처럼 보인다. 이제 컴파일
에러이며, 문면이 닫히는 파이프라인의 이름과 고치는 법을 말한다. 고치는 법은 경로에
따라 다르다.

- **가드**(`when`/`until`/`repeat`): 가드를 파이프라인 자신의 열로 내어 쓴다. 또는
  뒤 스텝들을 새 `pipeline`으로 묶어 가드가 그 블록을 소유하게 한다.
- **블록 개시**(`pipeline`/`parallel`): 이미 블록이므로 "새 pipeline으로 묶어라"는
  고치는 법이 아니다. 형제 블록을 뜻했다면 파이프라인 자신의 열로 내어 쓴다.

### 다단 조건 흐름: 가드된 파이프라인 연쇄

"확인 → 실행 → 결과를 보고 다음 단계"는 가드된 `pipeline`을 잇달아 쓰고, 뒤 가드가 앞
파이프라인이 만든 바인딩을 읽게 한다. 정본 예제는 `examples/staged.lnpl`이다.

```
    when product.stock >= input.quantity
    pipeline place
        create order as o
        call PaymentGateway as pay
    when pay.status == 200
    pipeline confirm
        format o.status from "confirmed"
        update order
```

이 패턴은 다음 계약에 기댄다: **비교 연산은 한쪽 피연산자가 바인딩되지 않은 참조로
해석되면 거짓이다**(RFC-0012 §G12.4 표의 "바인딩이 아직 없다" 행,
`impl/lnpl/interp.py::_comparison_holds`의 "Unresolved reference -> False"). 앞 가드가
거짓이면 `pipeline place`가 통째로 건너뛰어져 `pay`가 결코 바인딩되지 않고, 뒤 가드의
`pay.status == 200`은 특별취급 없이 거짓이 되어 `pipeline confirm`도 건너뛴다. 오류도
아니고 공허하게 참도 아니다.

이 계약을 고정하는 테스트:

- `impl/tests/test_runtime.py::TestStepResultBinding::test_an_unbound_reference_is_false_not_an_error`
- `impl/tests/test_runtime.py::TestStepResultBinding::test_an_unbound_reference_does_not_exist`
- `impl/tests/test_staged_example.py::TestStagedFlow::test_a_false_first_guard_leaves_pay_unbound_and_the_second_guard_false`
  — 패턴 그대로: 앞 가드가 거짓일 때 뒤 가드의 건너뜀 기록이 `pay.status`를 값 없음,
  `holds: false`로 남긴다.

## Reference-level Specification

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0002 §Block structure를 치환하는 **최종
텍스트 전문**이다 — RFC-0019가 공표한 본문에 이 개정의 항목 하나(3항 c)를 더하고, 3항의
목록 수를 맞춘 것이다.

---

### Block structure (RFC-0058 개정판)

1. **키워드 구획** — 블록 경계는 키워드가 정한다. 최상위 선언 키워드는 이전
   블록 전체를 자동 종결한다. 절 키워드는 소속 선언의 하위 구획을 열고, 다음
   절 키워드 또는 최상위 키워드에서 닫힌다. 명시적 종결 키워드를 가지는 블록은
   `parallel`(→ `merge`) 하나뿐이다.

2. **들여쓰기 비구조성** — 파서는 라인 선두 공백으로 블록을 만들지 않는다.
   관례 4칸·탭 금지는 style 권장일 뿐 문법이 아니다. **수용되는 모든
   프로그램에서, 같은 토큰열은 포맷팅과 무관하게 항상 같은 구조로 파싱된다.**

3. **모순 들여쓰기의 거부** — 다만 들여쓰기가 2항이 정한 구조와 **모순되는**
   프로그램은 수용 집합에서 제외한다(컴파일 에러). 들여쓰기는 구조를 만들지
   못하고 오직 프로그램을 반증할 수만 있으므로, 2항의 보장은 유지된다.
   모순은 다음 셋이며, 이 목록은 닫혀 있다.

   a. **가드 스코프 모순.** 가드(`when`/`until`/`repeat`)가 자기보다 깊은 열의
      항목을 소유할 때, 그 가드 다음에 오는 첫 최상위 항목이 여전히 가드보다
      깊은 열에 있으면 거부한다. 가드는 항목 하나만 소유하므로(RFC-0008 §5.2)
      그 항목은 가드 밖에서 실행되는데, 열은 안에 있다고 말하기 때문이다.

   b. **spec 꼬리 모순.** `spec` 절의 섹션(`given`/`when`/`expect`)이 `spec`보다
      깊은 열에 있을 때, 그 블록 안의 내용 줄이 `spec`과 같거나 더 얕은 열에
      있으면 거부한다. 워크플로의 항목은 `spec` 앞에 오므로(§Full grammar:
      `WorkflowItem* SpecClause?`) 그 줄은 항목이 될 수 없는데, 열은 항목인 것처럼
      말하기 때문이다.

   c. **파이프라인 암묵 종결 모순.** `pipeline`이 열려 있을 때, 그 `pipeline` 줄보다
      깊은 열에 제어 키워드(`when`/`until`/`repeat`/`pipeline`/`parallel`)가 오면
      거부한다. `pipeline`은 다음 키워드에서 저절로 닫히므로(1항) 그 키워드는
      파이프라인 밖에서 작동하는데, 열은 안에 있다고 말하기 때문이다. 에러 문면은
      닫히는 파이프라인(이름, 이름이 없으면 그 줄 번호)과 고치는 법을 싣는다: 가드면
      파이프라인 자신의 열로 내어 쓰거나 뒤 스텝을 새 `pipeline`으로 묶을 것, 블록
      개시면 파이프라인 자신의 열로 내어 쓸 것. 열린 `parallel`에는 적용되지 않는다 —
      `parallel`은 `merge`로만 닫히고, 그 안의 가드와 블록 개시는 이미 거부된다(4항).
      선언 키워드나 파일 끝에서 닫히는 경우도 대상이 아니다.

   세 규칙 모두 **레이아웃이 정보를 담을 때만** 발동한다: 가드와 그 항목이 같은
   열이면 a가, 섹션과 `spec`이 같은 열이면 b가, 키워드가 `pipeline` 줄과 같거나 더
   얕은 열이면 c가 발동하지 않는다. 전부 같은 열에 쓴 프로그램은 이 항의 적용을
   받지 않는다.

4. **중첩 ≤2** — 선언 = 레벨 0, 절과 제어 블록 = 레벨 1, 그 내부 구획
   (`given`/`when`/`expect`, `parallel`의 브랜치 step) = 레벨 2. 그 이상의
   중첩은 문법적으로 불가능하다 — `ParallelBlock`과 `PipelineBlock`의 본문은
   `StepLine`만 허용하므로(§Full grammar의 EBNF) parallel 안의 parallel,
   spec 안의 spec은 생산규칙 차원에서 존재하지 않는다.

5. **한 줄 한 선언** — 모든 선언·절 개시·step·내용 항목은 정확히 한 라인이다.

---

참조 구현: `impl/lnpl/parser.py::_check_pipeline_layout`. `parallel`/`pipeline`을 여는
자리와 가드를 여는 자리, 두 곳에서 열린 파이프라인을 닫기 직전에 부른다.

## Examples

**거부 ③ — 가드가 파이프라인을 닫는다 (이슈 #211 (3)).**

```
workflow PlaceOrder
    find product
    when product.stock >= input.quantity
    pipeline place
        create order as o
        call PaymentGateway as pay
        when pay.status == 200
            set o.paid to 1
        update order
```

```
compile error: line 7: this `when` is indented as if it were inside `pipeline
place`, but a `pipeline` closes at the next keyword, not by indentation — so it
runs outside the pipeline. Dedent it to the pipeline's own column, or wrap the
following steps in a new `pipeline` block so a guard can own that instead
(RFC-0058, RFC-0002 §Block structure)
```

**수용 ④ — 가드를 파이프라인 자신의 열로.** 뒤 단계도 가드가 소유해야 하면 새
`pipeline`으로 묶는다. `examples/staged.lnpl`의 형태다.

```
workflow PlaceOrder
    find product
    when product.stock >= input.quantity
    pipeline place
        create order as o
        call PaymentGateway as pay
    when pay.status == 200
    pipeline confirm
        format o.status from "confirmed"
        update order
```

**거부 ⑤ — 블록 개시가 파이프라인을 닫는다.**

```
workflow Restock
    pipeline prepare
        validate order
        parallel
            notify order
        merge
```

```
compile error: line 4: this `parallel` is indented as if it were inside
`pipeline prepare`, but a `pipeline` closes at the next keyword, not by
indentation — so it runs outside the pipeline. Dedent it to the pipeline's own
column if you meant a new sibling block here, not one nested inside it
(RFC-0058, RFC-0002 §Block structure)
```

**수용 ⑥ — 형제 블록으로 내어 쓰기.** 파이프라인 안의 `parallel`은 4항(`PipelineBlock`
본문은 `StepLine`만)에 따라 애초에 존재하지 않으므로, 이것이 그 의도의 유일한 철자다.

```
workflow Restock
    pipeline prepare
        validate order
    parallel
        notify order
    merge
```

## Alternatives

**① 그대로 둔다 / ② 거부 대신 경고 / ④ 들여쓰기를 구조적으로 만든다.** RFC-0019
§Alternatives ①·②·④와 같은 이유로 기각한다.

**⑦ 선언 키워드·파일 끝에서의 종결도 거부한다.** 열린 파이프라인이 워크플로 끝까지
가서 다음 최상위 선언에서 닫히는 경우를 네 번째 사례로 넣는 안. 기각 — 최상위 선언
키워드는 코퍼스 관례상 언제나 0열에 쓰이므로 "안에 있다"고 말하는 레이아웃 신호가
없다. 이슈 #211 제안 1이 지목한 것도 다섯 제어 키워드뿐이고, 범위를 더 넓히는 것은
RFC-0019 Open Question ①(강도 문제)을 한 단계 위에서 되풀이한다.

**⑧ 하나의 고치는 법 문장을 모든 경로에 쓴다.** 기각 — `pipeline`/`parallel` 경로에서
"새 `pipeline`으로 묶어라"는 이미 참인 상태라 고치는 법이 아니다. 문면은 경로별로
갈린다.

## Open Questions

① RFC-0019 Open Question ①(`when`/`until`에도 같은 강도가 맞는가)과 ②(포매터가
정본이 되어야 하는가)는 3항 c에도 그대로 걸리며, 이 RFC는 둘 다 답하지 않는다.

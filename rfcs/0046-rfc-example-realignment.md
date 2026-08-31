# RFC-0046: RFC 예제 문법 재정렬 — RFC-0037/0008/0014 §Examples

## Status

- Status: **Accepted** (RFC-0046, 2026-08-31)
- Updates: RFC-0037 §Examples, RFC-0008 §Examples, RFC-0014 §Examples

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목한다. 세 절 모두 `## Examples` —
RFC 하나가 이번에 처음으로 다시 쓴다. `grep -n 'Updated-by' rfcs/0037-*.md
rfcs/0008-*.md rfcs/0014-*.md`로 확인한 대로, 세 RFC 모두 이미 다른 절의
`Updated-by:` 항목을 갖고 있지만(RFC-0008은 §Reference-level
Specification/1·2, RFC-0014는 §Reference-level Specification/2.4·2를 각각
RFC-0012/0014, RFC-0027/0028에 내줬다) `§Examples`를 지목한 이전 갱신은
없다 — 그래서 RFC-0007 §2.2 규칙 5("연쇄 갱신")가 요구하는 직전 갱신 RFC
지목은 필요 없다. 이슈 2건(#155, #156)을 한 RFC로 묶는 이유: `Updates:`는
쉼표 구분 다중 지목을 허용하고(§7 템플릿), 세 파일 각각에 필요한 등록
갱신(`README.md`/`README.ko.md`/`gen_plugin_references.py`)은 RFC 하나가
한 번에 실행하는 편이 두 번 나눠 하는 것보다 등록 지점의 충돌 여지가 작다.
번호는 **0046**이다 — 0045까지 점유됐고(RFC-0007 §3은 재사용을 금지한다),
이 RFC는 그와 같은 런에서 다음 번호를 받는다.

**구현이 필요 없다.** 이 RFC는 세 Accepted RFC의 `## Examples` 절이 담은
예제 코드를 현재 문법으로 재정렬할 뿐 — 언어나 컴파일러의 계약을 바꾸지
않는다.

## Motivation

`scripts/check_doc_snippets.py`(이슈 #145 계열 게이트, `--strict=warning`)가
`rfcs/**/*.md`의 모든 ` ```lnpl ` 블록을 실제로 컴파일하면서 RFC-0037 /
RFC-0008 / RFC-0014의 `## Examples`가 셋 다 실패를 감춰 왔다는 사실이
드러났다(이슈 #155, #156):

- **RFC-0037 §Examples**(`rfcs/0037-http-resilience.md:210`)의 대표 예제는
  `when paymentResult.status == 200` 가드 아래 `find order`/
  `call OrdersApi ...` 두 줄을 나란히 인덴트한다. 가드는 스텝을 정확히
  하나만 소유하므로(RFC-0002 §Block structure) 이 블록은 **컴파일 에러**다
  — `a guard owns exactly one step or block ... Wrap the steps in a
  \`pipeline\` block`(§Reference-level Specification/1이 실측 원문을 그대로
  옮긴다).
- **RFC-0008 §Examples**(`rfcs/0008-guard-conditions.md:202`)와 **RFC-0014
  §Examples**(`rfcs/0014-guard-skip-observability.md:195`)는 `inputs`/
  `step <이름>`/`guard when`/`effect`/`kind` 같은 pre-RFC-0002 폐기 문법을
  쓴다. 미선언 동사는 강한 실패가 아니라 no-op 경고로 통과하므로("어휘가
  닫혀 있고 학습 데이터에 없어서, 그럴듯한 낱말은 파싱에 성공하고 런타임이
  아무것도 하지 않는다" — AGENTS.md) 평범한 `lnpl compile`은 오늘까지
  rc=0을 돌려줬다. `--strict=warning`으로 돌리기 전에는 이 실패가 보이지
  않았다. RFC-0008 §Examples가 가리키는 실제 파일 `examples/guarded.lnpl`은
  현재 문법(`validate`/`find`/`cache`/`call`)으로 이미 다시 쓰여 있어
  인라인 사본과 어긋난다.

세 블록 모두 `check_doc_snippets.py`의 `lnpl-check: skip — drift: ...`
마커로 CI를 초록으로 유지하고 있다(이슈 #145의 게이트 설계). 이슈 #155/#156의
`## Auto-expiry` 절은 "이 이슈를 고치는 순간 마커도 함께 제거해야 CI가
초록으로 남는다"고 적지만, 그 전제는 **Accepted RFC 본문은 직접 수정하지
않는다**(AGENTS.md, RFC-0007 §2.1)는 같은 이슈의 `## Fix` 절과 충돌한다.
RFC-0007 §2.2 규칙 3–4에 따르면 갱신 RFC는 치환 후 최종 텍스트를 **자기
본문에** 담고, 대상 RFC의 원문은 그대로 남는다 — 효력 있는 계약은 독자가
합성해서 얻는 것이지 파일이 덮어써지는 것이 아니다. 따라서 이 RFC가
Accepted된 뒤에도 **대상 RFC 세 곳의 인라인 블록은 여전히 컴파일되지
않는다**(원문이 안 바뀌었으므로). `check_doc_snippets.py`의 낡은 예외
검사는 "마커가 붙었는데 블록이 이제 컴파일된다"는 조건에서만 발동하고
(스크립트 150–158행), 그 조건은 성립하지 않는다 — 마커를 지우면 오히려
게이트가 빨개진다. 이 RFC는 세 마커를 지우지 않고, 각 이유 문자열 끝에
이 RFC를 가리키는 해소 문장을 덧붙인다(§Reference-level Specification의
세 절 각각, 그리고 대상 RFC 파일 자체의 편집).

## Guide-level Explanation

세 절 각각 무엇이 바뀌는지는 다음과 같다:

- **RFC-0037**: 가드 본문을 `pipeline` 블록으로 감싼다. `pipeline`은 가드가
  스텝 하나만 소유하는 제약(RFC-0002 §Block structure) 아래에서 여러
  스텝을 한 단위로 묶는 기존 문법이다 — 새 문법이 아니다. `method post`에
  `retry`를 같이 선언해 `retry-on-non-idempotent` 경고를 내는 것은 그대로
  둔다: RFC-0037 §Guide-level Explanation이 바로 그 조합을 "경고이지 거부가
  아니다"라고 서술하는 의도된 예시이기 때문이다(이슈 #155 `## Non-issue`가
  이미 확인했다). 그 결과 이 RFC의 §Reference-level Specification/1 블록은
  **`--strict=warning`에서 경고 하나(`retry-on-non-idempotent`)가 남는다**
  — `check_doc_snippets.py`는 `skip`/`prelude` 두 지시어만 지원하고
  "경고를 기대한다"는 세 번째 지시어가 없으므로(스크립트 150행, 164행),
  이 블록은 RFC-0037:52가 이미 같은 이유로 쓰고 있는 것과 **같은 성격의**
  `skip — fragment:` 마커를 하나 단다. 이 RFC의 다른 두 블록(RFC-0008,
  RFC-0014분)은 마커 없이 깨끗하게 컴파일된다 — 그 둘이 실제로 고쳐졌다는
  유일한 기계적 증거다.
- **RFC-0008**: 인라인 예제를 그 절이 가리키는 실제 파일
  `examples/guarded.lnpl`과 동기화한다 — `inputs`/`step`/`guard`/`effect`/
  `kind` 자리표시 문법을 실제 동사(`validate`/`find`/`when ... exists`/
  `cache`/`when ... >`/`call`)로 바꾼다. 가드 스코프(바로 다음 항목
  하나)와 존재 검사·비교식 두 형태를 실증하는 목적은 그대로다.
- **RFC-0014**: `step Start`/`step Loop`/`step End` 자리표시 스텝 이름을
  실제 동사로 바꾼다 — 라운드 계수 의미론(`until` 가드가 처음부터 거짓이면
  피가드 스텝이 0라운드 실행되고 `rounds: 0` 레코드를 남긴다)은 원문의
  가드 조건(`counter >= 10`)과 guard id(`wf.w.guard.1`)를 그대로 유지해
  보존한다 — 바뀌는 것은 스텝 이름뿐이다.

## Reference-level Specification

### 1. RFC-0037 §Examples 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래는 `rfcs/0037-http-resilience.md`의
`## Examples`(대표 예제) 블록에 대한 **치환 후 최종 텍스트**다. 블록
아래의 산문("`PaymentGateway`는 실패 시 최대 3회 ... 재시도한다")은
RFC-0037 원문 그대로 유효하며 이 RFC가 손대지 않는다.

<!-- lnpl-check: skip — fragment: 의도적 warning 예시 — `pipeline` 블록으로 감싸 원본의 guard-owns-one-step 컴파일 에러(RFC-0002 §Block structure, "a guard owns exactly one step or block")는 사라졌다. 남은 유일한 진단은 의도된 `retry-on-non-idempotent` 경고뿐이다 — RFC-0037 §Guide-level Explanation이 "경고이지 거부가 아니다"라고 직접 서술하는 그 경고이고, `rfcs/0037-http-resilience.md:52`가 이미 같은 이유로 단 마커와 같은 성격이다. `--strict=warning` 게이트가 경고도 위반으로 잡고 `check_doc_snippets.py`에는 skip/prelude 두 지시어뿐이라 마커가 필요하지만, 컴파일러 동작 자체는 이 RFC와 RFC-0037 본문이 말하는 그대로다 -->
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
        pipeline
            find order
            call OrdersApi with order.id as orderResult
```

바뀐 것은 `find order`/`call OrdersApi ...` 두 줄을 `pipeline` 블록 안으로
옮긴 것뿐이다 — 가드가 `pipeline` 블록 하나를 소유하고, 그 블록이 두
스텝을 순서대로 묶는다. 다른 선언(`capability`/`entity`/`service`)은
원문과 바이트 동일하다.

### 2. RFC-0008 §Examples 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래는 `rfcs/0008-guard-conditions.md`의
`## Examples` §5.2 블록에 대한 **치환 후 최종 텍스트**다 — `examples/
guarded.lnpl`(RFC-0008이 가리키는 그 파일)의 선언부와 바이트 동일하다.

```lnpl
capability postgres
capability redis

entity Token
    field
        id UUID
        cachedAt DateTime
        retryBudget Integer

service TokenService
    policy
        retry 3
    performance
        cache 5m

workflow RetrieveWithCache
    validate token
    find token
    when token.cachedAt exists
    cache token
    when token.retryBudget > 0
    call token
    spec
        given
            valid token
        when
            retrieveWithCache
        expect
            completed
            effects complete
```

가드는 바로 다음 항목 하나만 소유한다(`references/grammar.md` §가드의
스코프) — `cache token`은 존재 검사(`when token.cachedAt exists`) 아래에,
`call token`은 비교식(`when token.retryBudget > 0`) 아래에 있고, 앞의
`validate token`·`find token`은 조건과 무관하게 늘 실행된다. 이 두 형태
(Presence·Comparison)를 한 워크플로에서 실증한다는 원문의 목적은 바뀌지
않는다.

### 3. RFC-0014 §Examples 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래는 `rfcs/0014-guard-skip-observability.md`의
`## Examples` "예 2 — `until`이 0라운드인 실행" 블록에 대한 **치환 후
최종 텍스트**다.

```lnpl
entity Job
    field
        id UUID
        counter Integer

workflow W
    validate job
    until counter >= 10
    create job
    update job
```

`counter = 100`이면 조건이 처음부터 참이므로 `create job`은 한 번도
실행되지 않는다. 개정 전에는 아무 표지도 남지 않았다(RFC-0014가 여는
계약이 바로 이 표지다). 개정 후:

```json
{"guard": "wf.w.guard.1", "mode": "until",
 "condition": "counter >= 10", "steps": ["create job"], "rounds": 0}
```

가드 조건(`counter >= 10`)과 guard id(`wf.w.guard.1`)는 원문과 동일하다
— 바뀐 것은 피가드 스텝의 이름(`step Loop` → `create job`)과 그 앞뒤
스텝(`step Start`/`step End` → `validate job`/`update job`)뿐이다.
`counter = 0`이면 라운드가 실행되므로 레코드는 없다는 원문의 판정도
그대로 성립한다.

## Examples

### 골든 시나리오 "Login" (RFC-0007 §6)

`Login` 워크플로는 가드도 `pipeline`도 쓰지 않는다 — 이 RFC가 갱신하는
세 절 어느 것과도 무관하다. 정본을 참조만 하고 재정의하지 않는다. 골든
자체는 바뀌지 않는다(`examples/login.lir.json` 불변).

## Alternatives

| # | 검토한 대안 | 기각 사유 |
|---|------------|----------|
| 1 | **대상 RFC 세 건의 본문을 직접 고친다** | RFC-0007 §2.1이 금지한다 — Accepted RFC의 실질 변경은 본문 편집이 아니라 Supersedes/Updates 둘뿐이다. AGENTS.md도 같은 규칙을 되풀이한다 |
| 2 | **RFC를 2개(#155용 1개, #156용 1개)로 나눈다** | `Updates:`는 쉼표 구분 다중 지목을 허용한다(RFC-0007 §7). 나눠도 등록 지점(`README.md`/`README.ko.md`/`gen_plugin_references.py`) 세 파일을 두 RFC가 각각 건드려야 해서 충돌 여지만 늘어난다 |
| 3 | **RFC-0037의 `method post`+`retry` 조합을 바꿔 경고 자체를 없앤다** | RFC-0037 본문이 바로 그 조합을 "경고이지 거부가 아니다"의 의도된 예시로 쓴다(이슈 #155 `## Non-issue`) — 경고를 없애면 그 예시의 목적 자체가 사라진다. 대신 §Reference-level Specification/1에 RFC-0037:52와 같은 성격의 `skip — fragment:` 마커를 단다 |
| 4 | **`check_doc_snippets.py`에 `expect-warning` 지시어를 추가해 마커 없이 통과시킨다** | 이 RFC의 범위가 아니다(게이트 자체 수정은 이 태스크 범위 밖) — §Open Questions 1로 이월한다 |
| 5 | **대상 RFC의 `drift:` 마커를 지운다** | F3(스크립트 150–158행)에 따르면 낡은 예외 검사는 "마커가 붙었는데 블록이 이제 컴파일된다"는 조건에서만 발동한다. 이 RFC가 Accepted된 뒤에도 대상 RFC의 인라인 블록은 여전히 컴파일되지 않으므로(원문이 안 바뀌었다) 마커를 지우면 그 조건 없이 게이트가 빨개진다 |

## Open Questions

1. **`check_doc_snippets.py`의 `expect-warning` 지시어.** 이 RFC의
   §Reference-level Specification/1은 `skip`을 "의도된 경고"의 대용으로
   쓴다 — 진짜 필요한 것은 "이 블록은 정확히 이 경고만 내야 통과"를
   기계적으로 검사하는 세 번째 지시어이지, 컴파일 여부를 아예 검사하지
   않는 `skip`이 아니다. 이 RFC는 그 지시어를 추가하지 않는다(§Alternatives
   4) — 이 게이트가 다른 예제에서도 같은 패턴(의도된 경고)을 반복해서
   맞닥뜨리면, 그때 게이트 자체를 다루는 후속 이슈로 연다.

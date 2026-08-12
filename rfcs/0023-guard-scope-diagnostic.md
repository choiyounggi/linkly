# RFC-0023: 가드 밖으로 새어 나간 상태 변경의 컴파일 타임 진단

## Status

- Status: **Accepted** (RFC-0023, 2026-08-09)
- Updates: **RFC-0021 §코드 → 등급 (정본)** — 코드 하나를 추가한다:
  `guard-orphaned-steps` = `warning`. 사다리와 `--strict` 문턱의 의미는 그대로다.

Supersedes는 없다. RFC-0002의 가드 스코프 규칙(가드는 다음 항목 하나를 소유한다)을
**바꾸지 않는다** — 그 규칙이 조용히 배신하는 자리에 진단을 하나 놓을 뿐이다.
기존 문장을 무효로 만드는 조항이 없으므로 상류 RFC의 Status는 Accepted로 유지된다
(RFC-0007 §2.2).

번호가 0023인 이유: 0022까지 점유됐다. RFC-0007 §3은 번호 재사용을 금지한다.

언어 워킹네임은 **LNPL**(소스 확장자 `.lnpl`)이다.

## Motivation

2026-08-09 사용성 실측에서, 다음 프로그램이 **진단 0건**으로 컴파일되는 것을
확인했다.

```
workflow PlaceOrder
    validate order
    authorize order
    find product
    when product.stock >= input.quantity
    create order
    set product.stock to product.stock - input.quantity
    update product
```

작성자의 의도는 명백하다 — 재고가 충분할 때만 주문을 만들고 재고를 깎는다.
실제 동작은 다르다. RFC-0002 §Block structure대로 가드는 **바로 다음 항목
하나**만 소유하므로, 가드가 거짓인 실행에서 건너뛰는 것은 `create order`뿐이고
재고 차감과 `update product`는 **조건과 무관하게 돈다.**

같은 입력을 mode A로 돌리면 그제서야 드러난다:

```
skipped: [{'guard': 'wf.place.order.guard.1', 'mode': 'when',
           'condition': 'product.stock >= input.quantity',
           'steps': ['create order']}]
```

문법은 이 사실을 정확히 적어 두었고(`references/grammar.md` §가드의 스코프),
런타임은 `guard-skipped-steps`로 말한다. 부족했던 것은 **작성 시점의 신호**다.

| 기존 신호 | 시점 | 무엇을 말하나 | 부족한 것 |
|-----------|------|---------------|-----------|
| `references/grammar.md` | 읽을 때 | 가드는 항목 하나를 소유한다 | 읽지 않으면 없는 것과 같다 |
| `guard-skipped-steps` (RFC-0014) | 런타임 | 가드가 실제로 건너뛴 스텝 | 가드가 **소유하지 못한** 스텝은 말하지 않는다 |
| (없음) | 컴파일 | — | 이 RFC가 채운다 |

재고 미달인데 차감이 도는 프로그램이 CI를 초록으로 통과한다는 것이 이 RFC가
해결하는 결함이다.

## Guide-level Explanation

가드 뒤에 스텝이 오는 것은 정상이다. 모든 워크플로가 그렇게 생겼다. 경고할
값어치가 있는 것은 **가드가 지키려던 바로 그 상태를 가드 밖에서 만지는** 스텝이다.

그래서 진단은 형태(shape)가 아니라 결과(consequence)로 정의된다:

> 가드 조건이 참조하는 엔티티가 그 가드의 **보호 집합**이다. 같은 워크플로에서
> 그 가드보다 뒤에 있으면서 어떤 가드에도 속하지 않는 스텝이 보호 집합의
> 엔티티를 읽거나 쓰면, 그 스텝에 대해 `guard-orphaned-steps`를 낸다.

형태로 정의했다면 가드 뒤에 스텝이 오는 정상적인 프로그램 전부에서 발화했을
것이고, 그때 하는 일은 예외 목록을 키우는 것뿐이다. 예외마다 하나씩 늘어나는
가드는 아무것도 측정하지 않는다 — 이 레포는 이슈 #35에서 같은 실패를 이미 한 번
겪었다.

`examples/guarded.lnpl`이 조용한 이유는 **여기서 정확히 적어 둘 값어치가 있다.**
"가드 둘이 서로 다른 관심사를 다루기 때문"이라고 말하고 싶어지지만 그것은 이
판정이 실제로 하는 일이 아니다. 그 파일이 조용한 이유는 둘이다: (1) 첫 가드
뒤의 최상위 항목이 또 다른 `Guard`라 §3의 건너뛰기가 적용되고, (2) 그 가드가
소유한 스텝이 `call`이어서 `NetworkCall`을 파생하는데, §4의 표에 따라 그것은
보호 집합에 아무것도 기여하지 않는다. **(2) 하나만으로도 조용하다.** 그래서
`guarded.lnpl`은 §3 건너뛰기의 통제가 되지 못한다. 그 역할은 같은 엔티티를 두고
가드가 둘 서 있는 입력이 맡는다(`TwoGuardsOverTheSameEntity`).

진단은 저자가 **옮겨야 할 스텝**의 줄을 가리키고, 어떤 가드가 배신당했는지
인용하며, 문법이 이미 문서화한 두 해법을 제시한다.

```
warning: guard-orphaned-steps [line 16] set product.stock to product.stock - 1 —
  `when product.stock > 0` owns only the next item, so
  `set product.stock to product.stock - 1` runs whether or not that condition held.
  Repeat the guard line before this step, or wrap both in a `parallel` block.
```

두 해법은 실제로 통한다 — 그 사실 자체가 테스트로 고정돼 있다
(`TheRemediesItRecommendsActuallyWork`). 권하는 고침이 진단을 없애지 못한다면
그 문면은 거짓 안내이기 때문이다.

## Reference-level Specification

### 1. 코드와 등급

| 코드 | 등급 | 방출 시점 |
|------|------|-----------|
| `guard-orphaned-steps` | `warning` | lowering (컴파일 타임) |

`warning`인 근거는 RFC-0021의 정의다 — "프로그램을 고치면 사라지는 것"은
`warning`, "고쳐도 사라지지 않는 플랫폼 상태의 진술"은 `info`. 이 진단은 스텝을
가드 안으로 옮기면 사라지므로 `warning`이다. 따라서 `--strict`와 `--strict=warning`
둘 다에서 종료 코드를 막는다.

### 2. 보호 집합

가드 노드가 `condition`을 가질 때에만 판정한다(`repeat`은 조건이 아니라 횟수를
담으므로 대상이 아니다). 조건 해석은 `condition.parse_condition()`을 통한다 —
RFC-0008이 정한 유일한 진입점이며, 조건 문법을 두 번 파싱하지 않는다.

조건의 각 참조 `<binding>.<field>`에서 `<binding>`을 취해, 이 모듈이 선언한
엔티티의 바인딩 이름(`repo_policy.binding_name`)으로 해석한다. 해석된 엔티티
id들의 집합이 그 가드의 **보호 집합**이다.

보호 집합이 비면 판정하지 않는다. `input.<field>`만 참조하는 조건이 그 경우다 —
`input`은 실행 payload이지 이 워크플로가 소유한 행이 아니므로, 지킬 상태가 없다.

### 3. 대상 스텝

워크플로의 **최상위 자식 목록**(소스 순서)에서 가드의 위치 뒤에 오는 항목들을
본다. 항목이 `Guard`이면 그 하위 전체를 건너뛴다 — 가드 아래 있는 것은 이미
조건부이고, "그 가드가 옳은 가드인가"는 이 진단이 묻는 질문이 아니다.
블록(`parallel` / `pipeline`)이면 그 안의 `WorkflowStep`들로 내려간다.

### 4. 스텝이 만지는 엔티티

스텝의 낱말이 아니라 그 스텝이 파생한 **Effect 노드**에서 읽는다. Effect는 실행이
실제로 작용하는 대상이고, 두 실행 모드가 이미 합의한 production derivation이다.

| Effect | 기여하는 엔티티 |
|--------|-----------------|
| `RepositoryCall` | `entity` |
| `Assignment` | `entity` |
| `Validation` | `target` |
| `CacheAccess` | **없음** — 엔티티가 아니라 키를 담는다 |
| 그 외 | 없음 |

`CacheAccess`가 기여하지 않는 것은 의도된 범위 제한이다. 이 진단이 말하는
결과는 **저장된 상태의 변경**이며, 캐시 쓰기는 그 범주가 아니다.

### 5. `where`

`where`는 **고아 스텝**의 소스 줄이다 — 가드 줄이 아니다. 저자가 옮겨야 하는
것이 그 스텝이기 때문이다. IR 노드는 위치가 아니라 의미를 담으므로 줄 번호를
싣지 않는다. 그래서 lowering이 스텝 id와 줄 번호를 짝지어 기록해 두고
(`_WfContext.step_lines`), 이 판정이 그 표를 읽는다.

## Examples

### 발화한다

```
workflow Place
    validate product
    find product
    when product.stock > 0
    create order
    set product.stock to product.stock - 1     <- line 16, 발화
```
→ `guard-orphaned-steps` 1건. 정본 픽스처: `impl/tests/lnpl_fixtures/guard_orphan_fail.lnpl`

고아가 둘이면 둘 다 각자의 줄로 보고된다.

### 발화하지 않는다

```
workflow Place
    validate product
    find product
    when product.stock > 0
    create order
    cache order              <- 가드와 무관한 관심사
```
→ 진단 0건. 정본 픽스처: `impl/tests/lnpl_fixtures/guard_orphan_pass.lnpl`

커밋된 예제 넷(`checkout` / `guarded` / `login` / `shorten`)도 전부 0건이다.
`guarded.lnpl`이 조용한 기전은 §Guide-level Explanation에 적어 두었다 — 그 파일은
이 진단의 오탐 통제가 **아니다.**

`CacheAccess`가 기여하지 않는다는 §4의 결정은 그 자체로 반증 가능해야 한다.
가드가 지키는 바로 그 엔티티를 가드 밖에서 `cache`하는 입력이 그 통제이며
(`CACHE_ON_THE_PROTECTED_ENTITY`), 진단 0건이어야 한다. `guard_orphan_pass.lnpl`은
이 역할을 하지 못한다 — 그 `cache order`는 보호 집합과 애초에 다른 엔티티다.

### 고치는 두 방법

```
when product.stock > 0          # ① 가드 줄을 스텝마다 반복한다
create order
when product.stock > 0
set product.stock to product.stock - 1
```
```
when product.stock > 0          # ② 블록으로 묶으면 블록 전체가 가드 안이다
parallel
create order
set product.stock to product.stock - 1
merge
```
둘 다 진단 0건이 되는 것을 테스트가 고정한다.

## Alternatives

**(a) 문법을 바꿔 가드가 여러 스텝을 소유하게 한다.** 근본 해결이지만 RFC-0002의
블록 구조, mode B의 정적 가드 유도, `guard-skipped-steps`의 그레인, 골든 IR을
전부 건드린다. 이 RFC는 **현재 문법 아래에서** 함정을 보이게 하는 데 그친다.
문법 변경은 별도 RFC의 몫이며, 그때 이 진단은 불필요해질 수 있다.

**(b) 형태로 판정한다 — "가드 뒤에 스텝이 있으면 경고".** 구현이 훨씬 짧다.
그러나 `examples/guarded.lnpl`을 포함해 정상적인 프로그램 다수에서 발화하고,
대응은 예외 목록을 키우는 것이 된다. 이슈 #35에서 이 레포가 이미 겪은 실패
모드다. 채택하지 않았다.

**(c) `error`로 낸다.** 컴파일을 거부하면 의도적으로 그렇게 쓴 프로그램이
막힌다 — 가드 밖 스텝이 정말로 무조건 실행되기를 바라는 경우가 있다.
RFC-0021의 사다리가 이미 그 선택을 `--strict`로 위임한다.

**(d) 런타임 `guard-skipped-steps`를 확장한다.** 런타임은 가드가 **거짓인
실행에서만** 말할 수 있다. 가드가 참인 입력만 도는 CI에서는 영원히 조용하다.

## Open Questions

1. `CacheAccess`가 보호 집합에 기여하지 않는 범위 제한(§4)이 실전에서 놓치는
   사례를 만드는가. 캐시 키(`order:{id}`)에서 엔티티를 역산하는 것은 가능하지만,
   키 표기가 계약이 아니어서 지금은 하지 않는다.
2. 보호 집합을 **필드 단위**로 좁힐 여지가 있다 — 지금은 엔티티 단위라
   `when product.stock > 0` 뒤의 `update product`가 `stock`을 건드리지 않아도
   발화한다. 실측에서 오탐이 보고되면 좁힌다.
3. 블록 안의 가드(중첩 깊이 2 제한 아래)에 대해 이 판정을 확장할지. 현재는
   최상위 목록만 본다.

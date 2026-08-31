# RFC-0033: 선언 이름공간 — 디렉터리 스코프와 `internal/` 가시성

## Status

- Status: **Accepted** (RFC-0033, 2026-08-30)
- Updates: RFC-0031 §Guide-level Explanation (전역 유일 이름 규칙 — 네임스페이스가
  있는 컴파일 단위에서는 네임스페이스 내 유일로 완화), RFC-0031
  §Reference-level Specification > 로더: `load_sources(paths)` (중복 선언 검사가
  이제 네임스페이스를 본다)

번호가 0033인 이유: 0032까지 점유됐다(RFC-0032). RFC-0007 §3은 번호 재사용을
금지한다.

## Motivation

issue #117: RFC-0031이 다중 파일 컴파일 단위를 열었지만, 그 RFC 본문이 직접
적듯 "이 병합된 집합에서 선언 이름은 전역에서 유일해야 한다 — 이름공간이나
가시성 규칙은 없다." 이슈는 **구현 전에 규모 압력을 실측**할 것을 요구했다
— "지금 이 이슈에 적힌 갭은 전부 '커지면 문제가 될 것'이지 관측된 고통이
아니다."

t117이 그 실측을 했다(`docs/scale-pressure-measurement.md`). 엔티티 10/30/50
규모에서, 도메인마다 **전용 명사 20개**(N과 함께 자라고 도메인 간 겹치지
않음)를 쓰되 각 도메인이 엔티티의 약 1/3을 5개 도메인이 공유하는 **4개짜리
공용 명사**(`Order`/`Item`/`Status`/`Event`)에서 독립적으로 뽑게 했을 때
(r1 리뷰 F1 — 앞선 버전은 엔티티 전부를 10개 고정 풀에서 복원추출해
`collision_events ≥ N-10`이 되는 비둘기집 산술이었다; 이 모델은 도메인
전용 이름을 단 한 건도 충돌시키지 않고도 같은 현상을 측정한다):

| 측정 | N=10 | N=30 | N=50 |
|---|---|---|---|
| 이름 충돌 이벤트 수(전부 공유 명사 4개에서만) | 2 | 7 | **11** |
| 겹친 도메인 쌍 수(전체 C(5,2)=10) | 2 | 10(전체) | 10(전체) |
| `unknown-entity` 후보 목록 길이 | 10 | 30 | **50** (1,210바이트, 단일 컴파일 에러) |
| 컴파일 벽시계(중앙값) | 0.06s | 0.07s | 0.08s |
| OpenAPI 스키마 충돌 | 0건 | 0건 | 0건(구조적으로 도달 불능) |

`docs/scale-pressure-measurement.md`의 판정 기준(§결론, Task 03 step 1)은
"50개 규모에서 충돌 빈도가 0"을 "지금은 불필요"의 필요조건으로 뒀다. 실측
충돌 빈도는 0이 아니라 **11**이었으므로 그 조건이 깨진다 — 이것이 이 RFC를
쓰는 근거다. 도메인 전용 이름은 전혀 충돌하지 않았다는 점이 중요하다: 이
11건은 "이름이 부족해서"가 아니라 "서로 다른 5개 도메인이 흔한 명사 4개를
각자 독립적으로 재사용해서" 난다 — N=30부터 이미 도메인 쌍 전부가 겹친다.
(다른 세 조건 중 컴파일 시간·OpenAPI는 문제 없었고, `unknown-entity` 후보
목록은 50 규모에서 사람이 읽기 부담스러운 길이가 됐다 — 이 RFC의 설계가
그 목록도 함께 줄인다, §Reference-level Specification "짧은 이름 해소"
참조.)

RFC-0031이 `use` 선언을 기각한 근거(닫힌 어휘 + 학습 데이터에 없는 키워드는
파싱은 성공하고 런타임은 무동작이 되는 실패 모드)는 issue #117도 "지금도
유효하다"고 명시한다. 이 RFC는 그 결정을 뒤집지 않는다 — **문법을 한 글자도
바꾸지 않고** 네임스페이스와 가시성을 도입한다. Go의 `internal/`이 선례다:
키워드 0개로, 디렉터리 경로 규약만으로 가시성을 만든다. RFC-0031이 "파일명
정렬 수집"을 이미 경로 규약으로 다룬 것과 같은 수법을 한 단계 더 밀어붙인다.

## Guide-level Explanation

RFC-0031의 디렉터리 컴파일(`lnpl compile billing/`)은 오늘 그 디렉터리
바로 아래의 `*.lnpl`만 파일명 정렬로 모은다(재귀 없음). 이 RFC는 **그
디렉터리 바로 아래에 하위 디렉터리가 있는 경우**를 새로 정의한다 — 이런
레이아웃을 준 컴파일 단위를 "네임스페이스 루트"라고 부른다:

```
$ lnpl compile shop/
shop/
  billing/
    order.lnpl      # entity Order
  shipping/
    order.lnpl       # entity Order  — billing과 이름이 같아도 이제 충돌이 아니다
  catalog/
    product.lnpl
```

각 1단계 하위 디렉터리 이름이 그 디렉터리 안 선언들의 **네임스페이스**다.
문법은 바뀌지 않는다 — `entity Order`는 `billing/order.lnpl`에서나
`shipping/order.lnpl`에서나 똑같이 쓴다. 네임스페이스는 소스에 적는 것이
아니라 **경로에서 유도**된다(Go `internal/`과 정확히 같은 수법). 정규화
이름은 `<네임스페이스>.<선언이름>`으로 **표시**되지만(에러 메시지, IR
node id, OpenAPI 스키마명), 소스 문법에 `.`으로 참조하는 새 구문을 넣지
않는다 — §Reference-level Specification의 "짧은 이름 해소"가 참조를
전부 오늘과 같은 맨 이름(bare identifier) 토큰으로 처리한다.

`billing/internal/`처럼 이름이 정확히 `internal`인 2단계 디렉터리는
**가시성 경계**다: 그 안의 선언은 `billing/`과 `billing/internal/`
자신에서만 참조 가능하고, `shipping/`이나 컴파일 단위 루트에서는 참조할
수 없다(Go `internal/` 규칙 그대로). `internal/`은 네임스페이스를 새로
만들지 않는다 — `billing/internal/refund.lnpl`의 `entity Refund`는
`billing.Refund`로 정규화된다(`billing`의 일부), 가시성만 좁아진다.

하위 디렉터리가 없는 컴파일 단위(오늘의 모든 예제 — `examples/*.lnpl`,
그리고 RFC-0031의 `impl/tests/lnpl_fixtures/linkhub/`처럼 파일만 있는
디렉터리)는 네임스페이스가 전혀 없다 — RFC-0031 이전과 **바이트 단위로
동일**하게 동작한다. 이 RFC는 새 레이아웃(하위 디렉터리가 있는 경우)에만
관여한다.

## Reference-level Specification

### 네임스페이스 유도 — `load_sources`가 소유

`load_sources(paths)`(RFC-0031)가 디렉터리 하나를 받을 때, 오늘은 그
디렉터리 바로 아래 `*.lnpl`만 모은다. 이 RFC는 그 수집 규칙 앞에 레이아웃
판별을 추가한다:

- 주어진 디렉터리 바로 아래에 `*.lnpl` 파일이 있으면 → **네임스페이스
  없음**(오늘과 동일, RFC-0031 그대로). 하위 디렉터리가 있어도 무시한다 —
  파일과 디렉터리가 섞여 있으면 파일 우선, 네임스페이스 레이아웃이 아니다
  (혼합 레이아웃을 허용하면 "이 파일은 네임스페이스가 있고 저 파일은
  없다"는 비대칭이 생긴다; 명확히 하려면 파일들을 하위 디렉터리로 옮기게
  한다).
- 바로 아래 `*.lnpl` 파일이 0개이고 하위 디렉터리만 있으면 → **네임스페이스
  루트**. 각 1단계 하위 디렉터리를 순회(디렉터리 이름 정렬 순서 —
  RFC-0031의 파일명 정렬과 같은 결정성 원칙)하고, 그 안의 `*.lnpl`을
  파일명 정렬로 모은다. 하위 디렉터리 이름이 그 파일들 전부의
  네임스페이스가 된다.
- 2단계를 넘는 하위 디렉터리(`billing/eu/order.lnpl`)는 `LoaderError`로
  거부한다 — 깊이는 `internal/` 한 층까지만 허용한다(아래). 깊이 제한을
  두는 이유는 이슈 #117이 요구한 것이 "도메인 5~10개를 평평하게 나누기"이지
  임의 깊이 트리가 아니기 때문이다 — 필요해지면 별도 RFC가 다룬다
  (§Open Questions).
- 하위 디렉터리 이름이 `internal`이면 그 디렉터리는 **네임스페이스를
  만들지 않는다** — 부모 디렉터리 이름을 네임스페이스로 물려받고, 대신
  가시성 태그 `internal`을 각 선언에 붙인다(아래 "가시성 검사").

각 `Decl`이 이제 `namespace`(문자열 또는 없음)와 `internal`(bool) 두
속성을 추가로 지닌다 — `parser.parse()`가 채우는 것이 아니라 `load_sources`
가 파일 경로에서 계산해 각 `Decl`에 얹는다(파서·lexer는 여전히 한 글자도
안 바뀐다).

### 중복 선언 검사 — 네임스페이스 내 유일로 완화

오늘 `load_sources`의 `declared_in` 딕셔너리는 `decl.name`(맨 이름)으로만
키를 잡는다. 이 RFC는 키를 `(decl.namespace, decl.name)`으로 바꾼다.
네임스페이스가 없는 선언(위 "네임스페이스 없음" 레이아웃, 또는
네임스페이스 루트 밖에서 온 선언은 애초에 존재하지 않음)은
`decl.namespace is None`이라 오늘과 정확히 같은 전역 유일 검사를 받는다
— 회귀 없음. 네임스페이스가 있는 선언은 **같은 네임스페이스 안에서만**
유일해야 한다. 에러 메시지는 정규화 이름을 쓴다:

```
compile error: duplicate declaration 'billing.Order': first declared at
shop/billing/order.lnpl:1, again at shop/billing/order2.lnpl:1
```

서로 다른 네임스페이스의 동명 선언(`billing.Order`와 `shipping.Order`)은
**충돌이 아니다** — 이것이 이 RFC의 핵심 완화다.

### 짧은 이름 해소 — 미결 질문 ①에 대한 답

워크플로 스텝(`find order`, `load order` 등)은 오늘도 맨 이름만 쓴다.
`_resolve_entity`(`impl/lnpl/lower.py`)의 객체 매칭 규칙이 다음 순서로
바뀐다:

1. **같은 네임스페이스 우선**: 그 스텝이 속한 워크플로 선언의 네임스페이스
   안에서, 맨 이름이 일치하는 엔티티가 정확히 1개면 그것을 쓴다. (오늘의
   "이 파일이 선언한 엔티티" 개념을 "이 네임스페이스가 선언한 엔티티"로
   넓힌 것 — RFC-0031이 이미 여러 파일을 한 스코프로 병합했으므로 자연스러운
   확장이다.)
2. **전역 유일 폴백**: 1에서 못 찾았고, 컴파일 단위 전체(네임스페이스
   무관)에서 맨 이름이 일치하는 엔티티가 정확히 1개면 그것을 쓴다. (오늘의
   "엔티티가 1개뿐이면 그것" 폴백의 일반화 — 오늘 코드는 이미 이 폴백에서
   `diagnostics`에 `unknown-entity` 경고를 기록한다; 이 RFC도 그 경고를
   그대로 남긴다.)
3. **후보 나열 에러**: 1도 2도 안 되면(둘 이상의 네임스페이스에 후보가
   있고, 같은 네임스페이스 안에는 없음) `LowerError`를 던지되, **일치하는
   후보만** 정규화 이름으로 나열한다:

```
line 2: `find order` does not say which entity it means — declared in
2 namespaces (billing.Order, shipping.Order). Name the entity with its
namespace prefix (e.g. `find billingorder`) or move the step into one
of those namespaces.
```

이것이 측정 항목 4가 지적한 문제(50 규모에서 후보 목록이 **선언된 엔티티
전부**를 나열해 1,210바이트가 됨)를 구조적으로 고친다 — 후보 목록 길이가
이제 "그 규모의 총 엔티티 수"가 아니라 **실제로 이름이 겹치는 후보 수**로
줄어든다(측정값: 50 규모에서 colliding 이름은 4개뿐(전부 공유 명사), 총
엔티티 50개의 1/12.5). 네임스페이스가 아예 없는 컴파일 단위(하위 디렉터리 없음)는 1이
정의상 적용 불가하므로 오늘과 동일하게 2 → (엔티티가 2개 이상이면) 3으로
떨어진다 — 회귀 없음.

**정규화 이름으로 명시 참조**: `.`을 문법에 넣지 않으므로(§Guide-level
Explanation), 네임스페이스를 명시하고 싶은 스텝은 오늘의 맨 이름 매칭
규칙(`"".join(split_pascal(name))`)을 네임스페이스+이름 연결에도 그대로
적용한 토큰을 쓴다 — `billing.Order`는 `billingorder`. 새 구두점 없음,
기존 렉서 그대로.

### `derive_id` — 미결 질문 ②에 대한 답 (골든 IR 재생성 비용)

오늘: `derive_id(name, kind)` → `".".join([KIND_PREFIX[kind]] +
derive_segments(name, kind))` (예: `entity.order`).

이 RFC: `derive_id(name, kind, namespace=None)`. `namespace`가 주어지면
`KIND_PREFIX[kind]`와 `derive_segments(name, kind)` 사이에
`split_pascal(namespace)`의 세그먼트를 끼운다 — 예: `entity Order`가
`billing` 네임스페이스에 있으면 id는 `entity.billing.order`.
`namespace=None`(네임스페이스 없는 컴파일 단위 — 오늘의 모든 호출)이면
**오늘과 바이트 단위로 동일**한 id를 낸다. `internal/`은 id에 영향이
없다(가시성 태그이지 네임스페이스가 아니다, §Guide-level Explanation).

**골든 재생성 비용, 실측(D7, `docs/scale-pressure-measurement.md`)에
근거**: 테스트 스위트가 바이트 비교하는 골든 `.lir.json`은
`examples/*.lir.json` 5개뿐이고(`impl/tests/fixtures.py`), **전부
네임스페이스 없는(하위 디렉터리 없는) 단일 파일 컴파일**이다. 이 RFC의
`derive_id`는 `namespace=None`일 때 오늘과 바이트 동일이므로, **이 RFC를
받아들이는 시점의 골든 재생성 비용은 0이다** — 다섯 예제 중 어느 것도
네임스페이스 레이아웃으로 바뀌지 않는 한. 어떤 예제를 네임스페이스
레이아웃으로 마이그레이션하기로 하면, 그 시점에 그 예제 **하나**의 id가
바뀐다(측정된 상한: `login`19/`linkhub`24/`checkout`20/`guarded`17/
`shorten`23개 id 필드 — 마이그레이션하는 예제 파일 수만큼만 청구된다,
5개 전부가 아니라).

### `internal/` 가시성 검사

`load_sources`가 네임스페이스 계산 뒤에 한 번 더 순회한다: `internal=True`
인 `Decl`을 참조하는(워크플로 스텝의 객체, `respond`/`set`의 바인딩) 다른
네임스페이스의 선언이 있으면 `LoaderError`. 판정은 "참조하는 선언의
네임스페이스 == internal 선언의 네임스페이스"인가다 — 같으면 허용
(`billing/*.lnpl`이 `billing/internal/*.lnpl`을 참조), 다르면 거부
(`shipping/*.lnpl`이 `billing/internal/*.lnpl`을 참조하면 에러). 이
검사는 §짧은 이름 해소의 3단계(후보 나열) **이전에** 돈다 — `internal`
선언은애초에 다른 네임스페이스의 후보 목록에도 나타나지 않는다(가시성이
없으므로 "후보"가 아니다).

### OpenAPI `components/schemas` — 미결 질문 ③에 대한 답

오늘 `openapi.py`의 `schemas[entity["name"]] = ...`는 정규화 이름을 쓰도록
바뀐다: 네임스페이스가 있으면 `schemas["billing.Order"] = ...`. OpenAPI
3.1/JSON Schema의 컴포넌트 키 정규식(`^[a-zA-Z0-9._-]+$`)은 `.`을 명시적으로
허용하므로 문법 위반이 아니다. **이름이 길어진다**(이슈가 이미 예상한
비용) — 하지만 측정 항목 5가 보인 구조적 사실(§Motivation 표, 0건 관측,
`load_sources`/`lower()`가 이미 모든 이름 충돌을 선행 차단)은 이 변경 뒤에도
그대로 유지된다: 네임스페이스가 있으면 충돌 여지가 오히려 **줄어든다**
(같은 이름이 다른 네임스페이스에 있어도 이제 유효한 상태이므로 로더
단계에서 막히지 않고, `schemas` 딕셔너리 키도 네임스페이스로 이미
구분되어 있다). URL 경로(`_slug()`가 만드는 것)는 이 RFC의 범위에서
바뀌지 않는다 — `_slug()`는 서비스/엔티티 이름을 kebab-case로 만드는
기존 함수이고, 네임스페이스 프리픽스를 경로에 반영할지는 별도 결정이
필요하므로 미결로 남긴다(§Open Questions).

`openapi.py`의 "name collision in components/schemas" 검사는 오늘 도달
불능이다(위 §Motivation, [issue #122](https://github.com/choiyounggi/linkly/issues/122)).
이 RFC가 구현되면 그 검사가 **처음으로 발화 가능해진다** — 구현 시점에
issue #122를 함께 닫거나(검사가 실제로 살아났다면) 갱신해야 한다.

## Examples

**골든 시나리오 "Login"** — 이 RFC는 Login에 영향이 없다.
`examples/login.lnpl`은 하위 디렉터리 없는 단일 파일이므로 네임스페이스가
전혀 유도되지 않고(§Reference-level Specification "네임스페이스 유도"의
첫 갈래), `derive_id`는 `namespace=None`으로 호출되어 오늘과 바이트
동일한 id를 낸다. `examples/login.lir.json`은 이 RFC로 재생성이
필요하지 않다.

**골든 인접 예제 — 네임스페이스 레이아웃** (구현됨; entity 노드 순서는 `load_sources`의
파일명 정렬 규칙대로이므로 아래 트랜스크립트와 한 글자 차이 — 실제 산출은
`impl/tests/test_namespace_directories.py`가 검증한다):

```
$ find shop -name '*.lnpl'
shop/billing/order.lnpl
shop/billing/internal/ledger.lnpl
shop/shipping/order.lnpl

$ cat shop/billing/order.lnpl
entity Order
    field
        id UUID
        total Money

workflow FindOrder
    find order              # 짧은 이름 — 같은 네임스페이스(billing) 우선으로 해소

$ cat shop/billing/internal/ledger.lnpl
entity Ledger
    field
        id UUID

$ cat shop/shipping/order.lnpl
entity Order
    field
        id UUID
        carrier Text

$ lnpl compile shop/ -o shop.lir.json
wrote shop.lir.json (... nodes)
$ python3 -c "import json; d=json.load(open('shop.lir.json')); \
  print([n['id'] for n in d['nodes'] if n['kind']=='Entity'])"
['entity.billing.order', 'entity.billing.ledger', 'entity.shipping.order']
```

`billing.Order`와 `shipping.Order`는 공존한다(오늘은 `duplicate
declaration` 컴파일 에러). `shop/shipping/order.lnpl`이 `find ledger`를
쓰면 `billing/internal/ledger.lnpl`을 볼 수 없다는 `LoaderError`가 난다
— `shipping`이 `billing`의 `internal/`을 참조했기 때문이다.

## Alternatives

**`use <path>` 선언(명시적 import, 이슈의 (c))** — 기각 유지. RFC-0031의
기각 사유(닫힌 어휘 + 학습 데이터에 없는 키워드의 파싱-성공·런타임-무동작
실패 모드)가 issue #117 본문이 스스로 확인하듯 지금도 유효하다. 이 RFC는
그 결정을 뒤집지 않는다 — 문법 변경 0개로 네임스페이스를 얻는다.

**`internal/` 규약만 단독 채택(디렉터리=네임스페이스 없이)** — 기각.
`internal/`은 가시성만 만들고 이름 충돌 자체(측정 항목 1의 핵심 발견,
50 규모에서 11건, 전부 도메인 간 공유 명사 재사용)는 그대로 둔다. 이슈의 (a)+(b) 권장을 따라 함께
채택한다 — 서로 직교하는 기제이므로 하나만 골라야 할 이유가 없다.

**RFC-0031이 이미 기각한 "파일별 독립 이름공간"과 이 RFC의 관계** —
RFC-0031 §Alternatives는 **파일 하나하나**가 독립 스코프가 되는 안을
기각했다("파서·lowering 양쪽에 '지금 어느 파일을 보고 있는가'라는 새
상태를 흘려야" 하는 비용 때문에). 이 RFC는 파일이 아니라 **디렉터리**
(그것도 명시적으로 하위 디렉터리가 있는 레이아웃에서만)를 스코프로 쓴다
— 그 상태는 이미 `load_sources`가 파일 경로를 순회하며 갖고 있는 정보이고,
파서·lowering에는 `namespace`라는 데이터 필드 하나만 흘러 들어간다(제어
흐름 변경 없음). RFC-0031의 기각 사유가 겨냥한 비용(문법·파서 상태 확장)이
이 안에는 적용되지 않는다 — 다른 안이다.

**전면 새 키워드 없는 다른 스코프 단위(예: 파일 첫 줄의 `# namespace:
billing` 주석 규약)** — 기각. 주석은 문법이 무시하는 텍스트라 강제할
방법이 없고(오탈자 나도 조용히 무시됨), 결국 디렉터리 경로만큼 신뢰할
수 있는 신호가 못 된다. 디렉터리 이름은 파일시스템이 이미 유일성을
보장한다(같은 부모 아래 동명 디렉터리는 존재할 수 없다) — 별도 검증
코드가 필요 없다.

## Open Questions

1. **네임스페이스 깊이 2단계 초과(`billing/eu/order.lnpl`)** — 이 RFC는
   명시적으로 거부한다(§Reference-level Specification). 이슈 #117이 요구한
   규모(도메인 5~10개, 평평한 분배)에는 불필요하고, 깊이를 열면
   `internal/`의 "부모 하나" 규칙이 "어느 조상까지"로 다시 열려야 한다.
   실제 필요가 생기면 별도 RFC.
2. **OpenAPI URL 경로에 네임스페이스 프리픽스를 반영할지** —
   `_slug()`가 만드는 경로(`/{service}/{workflow}`)는 이 RFC에서 안 바꾼다.
   스키마명(`components/schemas`)만 정규화 이름을 쓴다. 경로까지 바꾸면
   기존 서비스의 API 계약(이미 배포된 URL)이 깨질 수 있어 더 신중한 검토가
   필요하다 — `lnpl serve`/`docs/serving.md`를 다루는 별도 RFC.
3. **명시적 파일 나열(디렉터리 아님)과 네임스페이스의 상호작용** —
   `lnpl compile a.lnpl shop/billing/order.lnpl`처럼 네임스페이스 루트
   밖의 파일을 섞어 나열하면 어떻게 되는가는 이 RFC가 정의하지 않는다.
   네임스페이스 유도는 "디렉터리 하나를 준 경우"에만 정의되므로(RFC-0031의
   기존 갈래 그대로), 혼합 나열은 오늘처럼 전부 네임스페이스 없음으로
   취급하는 것이 가장 단순하지만, 사용자가 실수로 네임스페이스 레이아웃의
   파일 일부만 나열했을 때 조용히 잘못된(네임스페이스 없는) 결과를 낼
   위험이 있다 — 구현 시점에 결정한다.

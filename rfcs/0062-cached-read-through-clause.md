# RFC-0062: 읽기 동사의 `cached` 절 — read-through

## Status

- Status: Draft
- Updates: RFC-0002 §Full grammar (+RFC-0012, RFC-0052, RFC-0060),
  RFC-0003 §Reference-level Specification/Execution Model (+RFC-0032, RFC-0056)

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목하고, 규칙 5(연쇄 갱신)에 따라 이미
갱신된 절은 대상과 **직전 갱신 RFC를 모두** 지목한다. 괄호 안이 직전 갱신이다. 그중
RFC-0052·RFC-0060은 아직 Draft다 — 먼저 Accepted되는 쪽이 직전 갱신이 되고, 나중 쪽이
승격할 때 그 사실을 `Updates:`에 반영한다(RFC-0051·RFC-0052 선례).

- **문법(RFC-0002 §Full grammar).** 아래 §1의 최종 텍스트는 RFC-0052 §1의 `RepoStepLine`
  **위에** 읽기 동사의 두 번째 꼬리 절을 더한 것이다. RFC-0012는 그 생산규칙을 손대지
  않았고, RFC-0060은 `GuardedItem`만 바꿨다 — 같은 절이므로 셋 모두 지목한다.
- **실행 모델(RFC-0003 §Execution Model).** 아래 §7의 최종 텍스트는 CacheAccess 행 하나다.
  RFC-0032와 RFC-0056이 그 절의 다른 행을 갱신했으므로 지목한다.

Draft이므로(RFC-0007 §2.2 규칙 6: 개정은 Accepted 시점에 효력이 발생한다) 대상 RFC들에
`Updated-by:` 줄이나 절 머리 포인터를 아직 달지 않는다.

지목하지 **않는** 것:

- RFC-0016 §5(mode A/B 등가 표). 모드 B 거부는 RFC-0053~RFC-0060처럼 이 RFC의 §6에 둔다.
  RFC-0051·0052는 그 표에 행을 더했지만, 더 최근의 RFC들이 표를 건드리지 않고 거부를
  자기 문서에 두는 쪽을 택했고 이 RFC도 그 선례를 따른다 — 누락이 아니라 선택이다.

## Motivation

probe-v0.8 s4 F-2(issue #188): 같은 행을 반복해 읽는 요청을 보낸 뒤 `redis MONITOR`를
보면 `SET`/`DEL`은 있어도 `GET`이 한 번도 없다. `.lnpl`로 쓰는 쪽이 캐시를 **쓸**
수는 있지만(`cache`, RFC-0003) **읽을** 수단이 없기 때문이다.

- RFC-0003 §Execution Model은 CacheAccess `get`을 이미 정의한다 — "miss가 오류가 아니라
  정상 경로인 조회(miss 시 원천 조회로 폴백)". 인터프리터의 CacheAccess 분기도
  `get`을 실행한다.
- 그러나 어떤 동사도 `get`으로 내려가지 않는다. `find`/`read`/`load`/`authenticate`는
  전부 `RepositoryCall`로 내려가므로, "캐시를 먼저 보고 없으면 저장소를 읽는" read-through를
  한 줄로 쓸 방법이 없다.

사용자 결정(issue #188): 새 동사를 만들지 않고, **기존 읽기 동사에 절을 더한다.** 정확한
키워드는 이 RFC가 정한다.

## Guide-level Explanation

읽기 동사 넷이 선택적 꼬리 절 하나를 더 받는다:

```
find|read|load|authenticate <Entity> [by <ref>] [cached]
```

- `cached`가 없으면 지금과 같다.
- `cached`가 있으면 그 스텝은 **같은 키로 캐시를 먼저 읽는다.** hit이면 저장소를 부르지
  않고 캐시의 행을 바인딩한다. miss이면 저장소를 읽고, 읽은 행을 캐시에 기록한 뒤 바인딩한다.
- `cached`는 `by <ref>` **뒤에** 온다. `find product by input.sku cached`는 되고
  `find product cached by input.sku`는 컴파일 오류다.
- 캐시 항목의 TTL은 소유 서비스의 `performance cache <duration>` 예산이다. 그 예산이 없는
  서비스의 워크플로에 `cached`를 쓰면 컴파일 오류다 — 모든 캐시 키는 TTL을 가진다.
- 같은 워크플로가 `cached`로 읽은 엔티티를 `update`/`delete`/`set`으로 **쓰면** 컴파일
  오류다. 캐시 hit은 낙관적 버전(issue #92)을 싣지 않으므로 그 위의 쓰기는 무조건 쓰기가
  되기 때문이다.

```lnpl
capability postgres
capability redis

entity Product
    field
        id Text
        sku Text
        name Text

service Catalog
    performance
        cache 5m

workflow GetProduct
    find product by input.sku cached
    respond product.name
```

같은 `sku`로 두 번 요청하면 첫 요청은 저장소를 읽고 캐시에 기록하며, 두 번째 요청은
저장소를 부르지 않는다.

## Reference-level Specification

### 1. 문법 — RFC-0002 §Full grammar 갱신 (치환 후 최종 텍스트)

RFC-0052 §1의 `RepoStepLine` 첫 대안을 아래로 치환한다. 나머지 두 대안(`update`/`delete`,
`create`/`insert`)은 그대로다:

```
RepoStepLine   ::= ReadVerb Entity LookupClause? CacheClause? EOL
                 | ('update' | 'delete') Entity LookupClause? EOL
                 | ('create' | 'insert') Entity ('as' CamelName)? EOL
ReadVerb       ::= 'find' | 'read' | 'load' | 'authenticate'
LookupClause   ::= 'by' Reference
CacheClause    ::= 'cached'
```

`cached`는 렉서 키워드가 아니다 — `by`처럼 꼬리 토큰에서 위치로 읽는다. 어휘 문서와
provenance의 `vocabulary_digest`는 바뀌지 않는다.

읽기 동사의 꼬리 토큰이 비어 있지도, `by <Reference>`도, `cached`도, `by <Reference> cached`도
아니면 컴파일 오류다:

```
line <N>: `<verb> <object>` accepts either no trailing words, `by <ref>`, `cached`, or `by <ref> cached`, got <tokens>
```

`update`/`delete`의 꼬리 규칙과 오류 문구(`accepts either no trailing words or `by <ref>``)는
바뀌지 않는다 — `cached`는 그 문구로 거부된다. `cached cached`, `cached by <ref>`, 그리고 그
밖의 모든 낱말도 위 문구로 거부된다.

IR: `RepositoryCall` 노드가 선택적 불리언 필드 `cached`를 갖는다. 절이 없으면 필드 자체가
없다 — 절 없는 프로그램의 IR은 이 RFC 이전과 바이트 단위로 같다(코퍼스 48개 파일 전수).
`schemas/lir.schema.json`의 `nodeRepositoryCall.cached`(`type: boolean`, `required` 아님)가
이를 닫는다.

### 2. 키와 TTL

- **키.** `cached` 읽기가 캐시에 쓰고 읽는 키는 그 읽기가 저장소에 실행할 키와 **같은**
  문자열이다(RFC-0052 §3): `by <ref>`가 있으면 `row_key(entity_id, {"id": <ref의 값>})`,
  없으면 `row_key(entity_id, payload)`. `cache` 동사의 `<base>:{id}` 키 템플릿과는
  **별개의 이름공간**이다 — `invalidate <Entity>` 동사는 읽기 경유 키를 지우지 않는다(§8).
- **TTL.** 소유 서비스(RFC-0002 A.2 R2)의 `performance cache <duration>` 예산이다. TTL의
  소유권은 Performance 제약에 있다(RFC-0003) — 이 절은 TTL을 따로 지정하지 못한다.
- **예산이 없으면** 컴파일 오류다. RFC-0003이 TTL 없는 `set`을 금지하는 것과 같은 이유다:

```
line <N>: `<verb> <object> ... cached` needs a `performance cache <duration>` budget on the owning service — every cache key carries a TTL (RFC-0003, RFC-0062)
```

### 3. 모드 A 실행

`RepositoryCall`이 `cached`를 가지면, 키를 계산한 뒤 저장소를 부르기 전에:

1. **hit.** `cache.get(key)`가 행을 돌려주면 저장소 `execute`를 부르지 않고 그 행을 같은
   바인딩 이름·같은 키로 바인딩한다.
2. **miss.** 행이 없으면 지금과 같은 `execute`로 저장소를 읽고, 행이 dict이면
   `cache.set(key, row, <performance cache TTL>)`로 기록한 뒤 바인딩한다.
3. **not-found.** miss인데 저장소에도 행이 없으면 지금과 같은 타입 지정 `not-found`
   `RunError`(issue #197)로 실패한다. 부재는 값이 아니므로 **아무것도 캐시하지 않는다**
   (부정 캐시 없음).
4. **캐시 장애.** `cache.get`의 `DriverError`는 miss로 센다 — 저장소를 읽는다.
   miss 뒤 `cache.set`의 `DriverError`는 무시한다(읽기는 이미 성공했다). RFC-0003의
   "원천으로 폴백하되 동시성 상한 안에서만"의 상한은 기존 `parallel` 블록의 상한이다 —
   `cached` 읽기는 스레드를 더하지 않는다.
5. **쓰기 뒤 무효화.** 이 문서의 어떤 `cached` 읽기가 가리키는 엔티티를 `update`/`delete`로
   쓰거나 `set`/`format`의 `persist`로 저장하면, 그 쓰기가 만진 키를 **저장소 커밋이
   끝난 뒤에** `invalidate`한다(트랜잭션 안이 아니다 — 열린 트랜잭션 안에서 지우면 동시
   읽기가 쓰기 이전의 행을 다시 캐시에 올려 TTL 내내 남긴다). 롤백이나 커밋 실패는 쓰기가
   반영되지 않았으므로 아무것도 지우지 않는다. 무효화의 `DriverError`는 무시하고 TTL이
   낡음의 상한이 된다.
6. **롤백 폐기.** 실행이 롤백되면(예: 가드된 `fail`) 그 실행이 miss 뒤에 기록한 키를
   `invalidate`한다. 롤백된 실행 안에서 읽은 행이 롤백 뒤에 서빙되는 일을 막는다.
7. **trace와 메트릭.** `cached` 읽기의 `RepositoryCall` span은 `attrs["cache_hit"]`(`true`/
   `false`)를 갖는다. 절 없는 읽기의 span은 지금과 같다. 읽기마다 메트릭 하나 —
   `cache.hit` 또는 `cache.miss`, 값 1, 라벨 `{"step": <스텝 이름>}`(RFC-0003의 라벨 허용
   목록 안) — 를 기록한다.

`CacheDriver` SPI는 바뀌지 않는다. 등록된 외부 드라이버(`lnpl.caches`)도 같은 경로를 탄다:
같은 드라이버를 공유하는 두 번째 동일 요청은 저장소를 부르지 않는다. 효과는 계속
`("RepositoryCall", "read")`이므로 `IDEMPOTENT_OPS`는 그대로다.

### 4. 정적 검사 — 같은 워크플로의 쓰기

한 워크플로가 엔티티 E를 `cached`로 읽고 E를 `update`/`delete`로(키와 무관하게), 또는
E의 기본 바인딩을 머리로 가진 `set`/`format`으로 **쓰면** 컴파일 오류다:

```
workflow <W>: line <A> reads <E> with `cached` and line <B> writes it — a row this workflow modifies must be read without `cached` (RFC-0062)
```

`create E as <name>`은 다른 바인딩을 쓰므로 합법이다. 이유: 캐시 hit은 낙관적 버전
(issue #92)을 싣지 않아 그 위의 쓰기는 무조건 쓰기가 된다.

### 5. spec 관측

`cache` 기대 키에 두 문구를 더한다 — `cache hit`(실행 중 `cached` 읽기가 한 번 이상 hit),
`cache miss`(한 번 이상 miss). 새 기대 키도, 새 `given` 형태도 없다: 한 케이스 안에서 같은
행을 `cached`로 두 번 읽으면 miss 하나와 hit 하나가 나온다.

### 6. 모드 B

모드 B에는 소비할 캐시 상태가 없으므로 `cached` 읽기가 있는 워크플로를 **지원하지 않고
거부한다** — 기록된 예외다. 거부 없이는 `lnpl diff`가 모드 B의 일반 읽기와 비교해
거짓 `EQUIVALENT`를 낸다. MLIR을 내기 전에 `BackendError`로, 툴체인 확인 **전에**:

```
step <S>: <E> is read with `cached`, and mode B has no cache state to consult (RFC-0062 §Mode B, recorded exemption) — run it in mode A
```

`lnpl build <source> --workflow <W>`, `emit_mlir`, `lnpl diff <source> --workflow <W>`는 같은
첫 거부를 보고한다(CLI는 `backend error: …`, rc=4). 차동 하네스
(`differential.verify`)는 같은 워크플로를 `DifferentialError`로 거부한다 — 비교를 수행하지
않는다:

```
workflow <W> reads with `cached` — mode B has no cache state to consult (RFC-0062 §Mode B, recorded exemption); differential comparison is not attempted
```

거부 순서(`build`와 `verify` 공통): Money, 조회 키(RFC-0052), optional, Text, fill-source,
`fail`, respond 항목, 할당 필드 가드, `otherwise`(RFC-0060), **`cached` 읽기(이 RFC)**, 숫자
술어(RFC-0050). `cached`가 없는 워크플로의 모드 B 동작은 바뀌지 않는다.

### 7. RFC-0003 §Execution Model 갱신 (치환 후 최종 텍스트)

CacheAccess 행을 아래로 치환한다:

> | CacheAccess | `get` = miss가 오류가 아니라 정상 경로인 조회(miss 시 원천 조회로 폴백). `set` = TTL 필수 — TTL 값은 Performance 제약의 `cache` 예산이 소유한다(RFC-0001 CacheAccess 행). `invalidate` = 삭제. 캐시는 성능 계층일 뿐 정합성 메커니즘이 아니다 — 캐시 불가용 시 원천으로 폴백하되 동시성 상한 안에서만(무제한 폴백 herd는 캐시 장애를 원천 장애로 만든다). 읽기 동사의 `cached` 절(RFC-0062)이 `get`에 닿는 표면이다 — hit이면 원천 조회를 생략하고, miss면 원천을 읽어 같은 키로 `set`한다. |

(행의 앞 문장들은 현행 RFC-0003 텍스트를 그대로 옮긴 것이고, 마지막 문장만 더해졌다.)

### 8. Compatibility

- **`cached` 없는 프로그램.** IR은 바이트 단위로 같고(코퍼스 48개 파일 전수), 런타임 키·
  모드 B 출력도 같다. 골든 쿼텟은 바뀌지 않는다.
- **`invalidate <Entity>` 동사.** 키 이름공간(`<base>:{id}`)이 읽기 경유 키(`entity#id`)와
  달라 읽기 경유 항목을 지우지 않는다. 이 문서의 쓰기가 읽기 경유 항목을 비우는 것은 §3의
  5번이 한다.
- **드라이버.** `CacheDriver` SPI와 `CacheDriverTCK`는 바뀌지 않는다 — `get` 경로 케이스가
  이미 계약 전부다.
- **어휘.** `vocabulary_digest`와 생성된 어휘 참조의 digest 줄은 바뀌지 않는다. 생성된
  `verbs.md`의 읽기 동사 행에 `cached` 문장이, `rfcs.md`에 이 RFC 행이, `spec.md`의 `cache`
  행에 새 문구가 더해진다.

## Examples

### 골든 시나리오 "Login" (RFC-0007 §6)

골든 시나리오는 `authenticate`에 꼬리 절을 쓰지 않는다. 이 RFC 뒤에도
`examples/login.lnpl`의 IR과 모드 B 출력은 바이트 단위로 같다.

### 골든 인접 예제 — 카탈로그 read-through (RFC-0007 §6, 골든이 다루지 않는 기능)

Guide-level의 `GetProduct`가 이 예제다. 같은 `sku`의 두 번째 요청은 `cache hit`이고
저장소를 부르지 않는다. `Catalog`에서 `cache 5m`을 지우면 컴파일이 §2의 오류로 실패한다.

### 컴파일 거부 — 순서가 바뀐 절, 쓰기 동사의 `cached`

<!-- lnpl-check: skip — 거부되는 형태를 보이는 예시다: 순서가 바뀐 절, 쓰기 동사의 `cached`, 예산 없는 서비스 -->
```lnpl
workflow Broken
    find product cached by input.sku
    update product cached
```

첫 줄은 §1의 "accepts either no trailing words, `by <ref>`, `cached`, or `by <ref> cached`"로,
둘째 줄은 `update`의 기존 문구로 거부된다.

## Alternatives

### 새 동사 (기각)

`lookup`/`fetch` 같은 새 읽기 동사. 사용자 결정(issue #188)으로 기각됐다 — 어휘가 닫혀 있고
읽기 동사마다 바인딩·키·시드 규칙이 이미 있어, 새 동사는 그 전부를 다시 정의해야 한다.

### `find ... from cache` 수식 (기각)

더 길고, `from`은 이미 `format`에서 템플릿 원천을 뜻한다. 한 낱말 `cached`가 `by`와
같은 위치 규칙으로 읽힌다.

### 엔티티 선언 수준의 캐시 정책 (기각)

issue #188의 선택지 (a)·(c). 엔티티에 정책을 달면 읽기가 스텝에서 보이지 않게 된다 —
어떤 읽기가 저장소를 건너뛸 수 있는지를 문서를 읽는 사람이 한 줄에서 알 수 없다.

### 모드 B가 고정된 예측으로 지원하는 안 (기각)

모드 B에는 캐시 상태가 없어 hit/miss를 예측하려면 어느 쪽인지를 가정해야 한다. 가정은
등가 주장을 거짓으로 만든다. RFC-0050~RFC-0060이 세운 "거부 + 기록된 예외" 모양을 따른다.

## Open Questions

1. **스탬피드 보호.** 인기 키가 만료될 때 동시 miss가 저장소를 한꺼번에 읽는다. single-flight나
   stale-while-revalidate는 넣지 않았다 — 모드 A는 `Interpreter` 하나가 요청 하나를 돌리고,
   `cache` 동사에도 없다. 한쪽에만 넣으면 캐시 동작이 둘이 된다.
2. **TTL 지터.** 같이 기록된 키가 같이 만료되는 문제. 같은 이유로 넣지 않았다.
3. **`invalidate <Entity>`가 읽기 경유 키에 닿게 하는 방법.** 두 이름공간(`<base>:{id}`와
   `entity#id`)을 잇는 표기가 필요하다.
4. **조회 키 항목의 낡음.** `by <ref>`로 `cached` 읽기한 항목(키 `entity#<ref의 값>`)은
   `id` 키로 쓰는 쓰기(`update`/`delete`/`set`의 키는 `entity#<payload id>`)가 무효화하지
   않는다. 같은 행을 두 키로 부르는 문서에서는 그 항목이 최대 한 TTL 동안 낡을 수 있다.
5. **캐시 키의 호출자 차원.** 키에 호출자가 없다 — 저장소 읽기 키에도 없기 때문이다. 호출자에
   따라 행이 달라지는 저장소 드라이버는 `cached`와 함께 쓰면 안 된다.
6. **실제 Redis 검증.** issue #188의 인수 조건인 `redis MONITOR`로 `GET`을 확인하는 일은 이
   저장소에서 돌리지 않았다. 저장소 안의 캐시 SPI 픽스처(`lnpl.caches`로 등록한 데모 드라이버)
   테스트가 "두 번째 동일 요청은 저장소를 부르지 않는다"를 대신 보인다. `lnpl-redis`로의
   검증은 후속 작업이다.
7. **모드 B 지원.** 캐시 상태를 모델링하는 방법이 생기면 거부를 풀 수 있다.

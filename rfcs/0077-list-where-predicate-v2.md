# RFC-0077: `list where` — 질의 술어, order by/limit, 드라이버 푸시다운

## Status

- Status: **Accepted** (RFC-0077, 2026-10-28)
- Supersedes: RFC-0038

**통합 출처.** 갱신 RFC에서 온 텍스트와 그 출처는 다음과 같다(RFC-0007 §2.2 규칙 3·5, 연쇄를 끝까지 따른 최신 Accepted 텍스트).

| 절 | 효력 있는 텍스트의 출처 |
|----|------------------------|
| §Reference-level Specification/3. 등가 비교의 타입 규칙 | 머리 문단 뒤 본문(`#### 3.1`~`#### 3.3` 포함): RFC-0054 §6. 절 끝 문단(거부 메시지는 모두 …): RFC-0051 §1 — RFC-0054 §6이 말없이 뺀 문단, 유지 |

표에 없는 절과, 표에 있는 절에서 출처를 적지 않은 텍스트는 RFC-0038 원문 그대로다.

## Motivation

이슈 #116이 여는 질문은 RFC-0025 §Open Questions 1이 이미 이월해 둔 것이다:

> **필터·정렬·페이지네이션.** D4가 이월한 것 그대로. `list`가 `Condition` 문법을
> 빌려 쓸지, 페이지네이션이 커서 기반일지 오프셋 기반일지는 후속 이슈가 결정한다.

`list link`는 지금까지 항상 엔티티의 전 행을 RowSet으로 바인딩했다(RFC-0075 §5).
워크플로 안에서 "이 고객의 주문만"을 표현할 방법이 없었으므로, 필터가 필요한
워크플로는 전 행을 받아 온 뒤 `sum`/`count`로도 골라낼 수 없는 부분집합을
다뤄야 했다 — 이 언어에 `if`/루프가 없기 때문이다(RFC-0068 §Runtime).

이슈의 핵심 통찰은 **새 표현식 언어를 만들지 않는 것**이다. 가드 조건
(`when`/`until`, RFC-0008)이 이미 "필드 비교 + `and`"라는, 정확히 `WHERE` 절에
필요한 만큼의 문법을 갖고 있다 — `condition.py`(705줄, RFC-0008 §Motivation 이후
가드·집계·format 세 소비자가 공유하는 SSOT)를 그대로 재사용하면 파서 두 벌을
같은 뜻으로 다르게 해석하는 결함 계열(RFC-0069 §Motivation이 경고하는 바로 그
것)을 피한다.

두 번째 동기는 인젝션 안전이다. `drivers.py`의 모듈 독스트링은 "STATEMENT TEXT
IS CONSTANT"를 세 규칙 중 하나로 못박는다 — 값이 SQL 문자열에 직접 들어가는
코드는 그 자체가 결함이다. 술어를 lowering 시점에 구조화 노드(필드/연산자/
값)로 낮추고 필드명은 컴파일 시점에 화이트리스트 검증을 마친 것만 driver에
닿게 하면, 드라이버는 값을 바인드 파라미터로만 조립할 수 있고 그 외의 조립
방법이 애초에 존재하지 않는다.

세 번째 동기는 RFC-0016의 차원 규칙이 등가 비교에는 지나치게 좁다는 점이다.
`_dimension_of`(RFC-0016 §3)는 Integer/DateTime이 아닌 선언 타입을 전부
거부한다 — 순서 비교(`<`)에는 맞는 판단이다(Text에 순서가 없다), 하지만 등가
비교(`==`)는 평가기가 필요 없다. `customerId == customer.id`(양쪽 다 UUID)는
그저 두 문자열이 같은지 묻는 것이고, SQL도 파이썬도 이미 그 답을 안다. 이
RFC가 §Reference-level Specification/3에서 좁히는 것이 정확히 이 간극이다.

## Guide-level Explanation

저자가 새로 쓸 수 있게 되는 것은 워크플로 스텝 하나다:

```
workflow SummarizeOrders
    find customer
    find report
    list order where amount > 100 and status == customer.tier
        order by placedAt desc
        limit 5
    set report.totalAmount to sum order.amount
    set report.orderCount to count order
    update report
```

절 순서는 고정이다 — `where` → `order by` → `limit`, 셋 다 개별적으로 생략
가능하다(`where` 없이 `list order`만 쓰는 RFC-0025의 기존 형태는 완전히
그대로다). `where`의 조건 문법은 가드 조건과 **글자 그대로 같다**: `and`만,
괄호 없음, 이항 산술 최대 1개. 다른 점은 좌변의 뜻뿐이다 — 가드에서 맨이름은
`input.<field>`를 뜻하지만, `list where`의 좌변은 **나열 대상 엔티티 자신의
필드**를 뜻한다(그 엔티티는 아직 실행 스코프에 바인딩되지 않았으므로 한정
이름을 쓸 수 없다). 우변은 가드와 똑같은 규칙을 따른다 — 이미 바인딩된 단일
행의 필드(`customer.tier`), `input.<field>`, 또는 정수/Duration 리터럴.

`amount > 100`처럼 순서 비교를 쓰려면 좌변 필드가 Integer나 DateTime이어야
한다 — `expose list ... by <field>`가 이미 요구하던 것과 같은 제약이다. 하지만
`status == customer.tier`처럼 등가를 쓸 때는 그 제약이 풀린다: 양쪽이 같은
선언 타입이기만 하면(UUID든 Text든 Email이든) 통과한다. 미선언 필드는 컴파일
에러이고, 에러 메시지가 그 엔티티의 실제 필드 이름을 후보로 나열한다 — 오탈자를
고치는 데 문서를 다시 열 필요가 없다.

`order by`는 `expose list`의 정렬 필드 규칙을 그대로 물려받는다(Integer나
DateTime만). `limit`은 1 이상의 정수 하나만 받는다. 셋 다 없는 `list order`는
지금까지와 완전히 같은 뜻 — 전 행, 필터 없음 — 이고, 내부적으로도 바이트
단위로 같은 IR 노드를 낸다.

## Reference-level Specification

### 1. `list` 표면 문법 — RFC-0025 §1 갱신 (치환 후 최종 텍스트) (D1)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0025 §Reference-level Specification/1의
치환 후 최종 텍스트다. 첫 세 문단(`VERB_LEXICON` 항목, `operation="query"`
재사용, `StepLine`/`Verb` 생산 규칙이 바뀌지 않는다는 문장)은 그대로 유효하며
이 RFC가 손대지 않는다. "이 RFC가 문법에 더하는 것은 집계 표현식뿐이다"라는
마지막 문장만 아래로 치환된다:

> RFC-0025가 문법에 더한 것은 집계 표현식(§2)이었다. `list`의 **object 뒤
> 트레일링 토큰**(`rest`, `_derive_effect`의 5번째 인자)에는 그 시점까지 아무
> 문법도 없었다 — 있었다면 조용히 버려졌을 것이다. RFC-0038이 그 자리에 문법을
> 채운다:
>
> ```
> ListTail   ::= ('where' Condition (OrderBy)? (Limit)?)?
> OrderBy    ::= 'order' 'by' Word ('desc')?
> Limit      ::= 'limit' Integer
> ```
>
> `Condition`은 RFC-0069 §Reference-level Specification/1이 정의한 그 생산
> 규칙이다(재정의 없음 — condition.py 재사용, 이 RFC §Motivation). `Word`는
> RFC-0067의 렉시컬 항목 그대로. 셋 다 개별적으로 생략 가능하되, `ListTail`이
> 비어 있지 않으면 반드시 `where`로 시작한다 — `order by`/`limit`만 단독으로는
> 쓸 수 없다(D1: 절 순서 고정, `where`가 최소 단위).
>
> `StepLine`의 트레일링 토큰 수 상한(RFC-0002 §Full grammar의 `Word? Word?
> Word?`)은 이 RFC도 다루지 않는다 — RFC-0027의 `with <ref>... as <name>`이
> 이미 그 상한을 넘는 사례를 낸 선례를 따른다. 닫힌 어휘 판정이 문법이 아니라
> `VERB_LEXICON`이 하는 것처럼(RFC-0075 §1), 트레일링 토큰의 의미 판정도
> 문법이 아니라 `_derive_effect`가 `verb`별로 한다.

### 2. 술어 IR — 구조화 노드 (D4)

`where`가 있을 때만 `RepositoryCall` 노드(`operation: "query"`)에 세 필드가
더 실린다. 없을 때는 RFC-0025가 내던 4키 노드(`kind`/`id`/`entity`/`operation`)
그대로다 — 이 RFC의 제약("predicate=None 경로 바이트 동일")이 요구하는 바로
그 규약이다.

```json
{
  "kind": "RepositoryCall", "id": "...", "entity": "entity.order",
  "operation": "query",
  "predicate": [
    {"field": "amount", "op": ">", "value": "100"},
    {"field": "status", "op": "==", "value": "customer.tier"}
  ],
  "order": {"field": "placedAt", "desc": true},
  "limit": 5
}
```

`predicate`는 conjunction 리스트(`and`로 묶인 각 항)다. `field`는 나열 대상
엔티티가 실제로 선언한 필드 이름(컴파일 시점에 검증 완료, 화이트리스트).
`op`는 `<`/`<=`/`>`/`>=`/`==`/`!=` 중 하나(`condition.COMPARATORS`와 동일
어휘). `value`는 우변 `Value`의 정규화된 문자열 표현(`condition.
value_to_string`) — `Assignment.expression`이 이미 쓰는 것과 같은 왕복 가능
직렬화이지, 원문 텍스트를 그대로 옮긴 것이 아니다(D4: "문자열 전달 금지"는
조건 **전체**를 불투명 문자열로 미루지 말라는 것이지, 이미 파싱된 한 항의 값을
정규화된 형태로 싣는 것과 다른 이야기다). `order`는 `{field, desc}` 또는
부재. `limit`은 1 이상의 정수 또는 부재.

`schemas/lir.schema.json`의 `nodeRepositoryCall`에 세 속성이 그 모양대로
추가된다(`additionalProperties: false` 유지 — §D10 스키마 게이트가 셋 다
없는 문서와 있는 문서를 모두 검증한다).

### 3. 등가 비교의 타입 규칙 — RFC-0016 §3 갱신 (치환 후 최종 텍스트) (D2)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0016 §Reference-level Specification/3
"피연산자의 차원 규칙"의 치환 후 최종 텍스트다. 원문 전체(차원 정의, 산술 표,
t2 F-5 ③의 사례, Money/합성 타입 거부)는 **가드 조건(`when`/`until`, RFC-0008)
과 산술(`set`, RFC-0015)에 대해서는 그대로 유효**하며 한 글자도 바뀌지 않는다.
아래는 그 끝에 새 절 하나를 더한 것이다:

RFC-0015의 "Integer 한정"을 **차원 규칙**이 대체한다.

- `instant` — 선언 타입이 `DateTime`이거나 base가 `DateTime`인 refinement
- `scalar` — `Integer`, base가 `Integer`인 refinement, 정수 리터럴, **Duration 리터럴**
- `money` — 선언 타입이 `Money`이거나 base가 `Money`인 refinement (RFC-0051)

| 식 | 결과 |
|----|------|
| `instant - instant` | `scalar` (경과 밀리초) |
| `instant + scalar`, `instant - scalar` | `instant` |
| `scalar ± scalar` | `scalar` |
| `instant + instant` | **컴파일 거부** |
| `money ± money` | `money` |
| `money * scalar`, `scalar * money` | `money` |
| `money * money`, `money / X`, `X / money` | **컴파일 거부** |
| `money ± scalar`, `money ± instant`, `scalar ± money`, `instant ± money` | **컴파일 거부** |
| `<X> <cmp> <Y>`, `dim(X) == dim(Y)` | 허용 |
| `<X> <cmp> <Y>`, `dim(X) != dim(Y)` | **컴파일 거부** |
| `set <T> to <E>`, `dim(T)`와 `dim(E)`가 둘 다 정해지고 다르다 | **컴파일 거부** (RFC-0051) |

선언 타입을 문서에서 알 수 없는 피연산자(맨이름, 네트워크 결과 참조)는 어느
차원도 아니며, 오늘과 같이 정적 검사를 통과하고 런타임이 판정한다. 이 규칙이
기존에 컴파일되던 프로그램에 만드는 **신규 거부는 표의 마지막 행 하나뿐이다** —
`set` 대상과 값의 차원이 다른 경우(예: DateTime 필드에 Integer 식을 넣는
것)로, 이전에는 정적 검사를 통과한 뒤 런타임에 잘못된 값을 저장했다. RFC-0051
시점에 저장소의 모든 `set` 줄(`examples/*.lnpl`, `impl/tests/*.py`, 50건)을 전수
분류해 이 행에 걸리는 기존 프로그램이 0건임을 확인했다.

이 규칙이 t2 F-5 ③(`payment.createdAt <= 43200m`)을 `instant` vs `scalar`로 거부한다.
RFC-0015도 이 형태를 거부했으나 사유가 "DateTime은 평가기가 없다"였다. 이제 평가기가
있으므로, 거부 사유는 **두 양이 같은 종류가 아니라는 것**이다. `money`도 같다:
`when payment.fee > 0`은 "평가기 없음"이 아니라 `money` 대 `scalar` 불일치로 거부된다.

`Money`의 통화는 타입이 아니라 행 데이터이므로 **정적 차원은 통화를 구분하지
않는다** — 같은 `money` 차원의 두 값이 다른 통화인지는 런타임이 판정한다
(RFC-0044 §5).

`Decimal`·`Text`·`Password`와 그 밖의 합성 타입은 여전히 어느 차원도 아니며 컴파일
거부다(RFC-0015 §D6 유지, Decimal은 RFC-0044 §Open Questions 3). 단 가드의
`==`/`!=`는 Text류 필드에 대해 아래 3.3이 연다.

#### 3.1 `list where`의 등가 비교 (RFC-0038)

위 표의 마지막 두 비교 행(`dim(X) == dim(Y)`이면 허용, 다르면 거부)은 `list
where`에서는 **좌변이 Integer나 DateTime일 때**의 규칙이다. `list <Entity> where
<cond>`(RFC-0038)의 좌변은 나열 대상 엔티티 자신의 선언 필드이므로 항상 구체적인
선언 타입을 갖는다 — 그 타입이 Integer도 DateTime도 아닐 때(UUID, Text, Email,
Money 등), 순서 비교(`<`/`<=`/`>`/`>=`)는 컴파일 거부다(등가와 달리 순서에는
평가기가 필요하다 — Text에 `<`가 없다는 원 규칙의 근거는 그대로 유효하고, Money의
순서 평가기는 드라이버 푸시다운에 없다). RFC-0051의 `money` 차원은 가드와 `set`에만
열린다 — `list where`와 `expose list ... by`는 Money를 이 RFC 이전과 똑같이 다룬다.

하지만 등가(`==`/`!=`)는 평가기를 요구하지 않는다 — 두 값이 같은지는 비교
연산자 없이도 판정된다. 그래서 `list where`의 등가는 차원이 아니라 **선언
타입 자체의 일치**로 판정한다: 좌변 필드의 base 타입과 우변이 이름하는
필드의 base 타입이 같으면(둘 다 Text든, 둘 다 UUID든) 허용, 다르면 거부.
우변이 정적으로 알 수 없는 것(맨 `input.<field>`처럼 선언 타입이 문서에
없는 경우)은 원 규칙과 같이 판정을 런타임으로 미룬다.

이 좁힘은 **`list where`에만** 적용된다 — 가드 조건의 등가는 위 표(차원 규칙)와
아래 3.3으로 판정된다. 3.3은 같은 base 일치 규칙을 가드로 가져오지만 대상 base를
더 좁게 잡는다(Money·Password 제외). `list where`는 `Condition` 문법을 재사용하지만,
그 판정 함수(`lower._check_list_predicate`)는 가드의 판정 함수
(`lower._check_dimensions`)와 별개이므로 한쪽을 넓혀도 다른 쪽은 조용히 넓어지지
않는다.

#### 3.2 `optional` 필드의 존재 검사 (RFC-0053)

`exists`/`missing`은 값을 평가하지 않고 키가 있는지만 본다. 그래서 피연산자가
`optional`로 선언된 필드(RFC-0066 §노드 카탈로그/Entity)이면 **선언 타입과 무관하게**
존재 검사를 허용한다 — Text·Money·합성 타입도 포함된다. 값이 `null`이면 키가 없는
것과 같이 `missing`이다. `optional`이 아닌 필드의 존재 검사는 위 규칙 그대로다.
이 예외는 존재 검사에만 있다. `optional` 필드를 비교·산술에 쓰는 것은 위 표가
그 선언 타입대로 판정한다.

#### 3.3 가드 조건의 Text 등가 비교 (RFC-0054)

`when`/`until` 서술과 `or` 대안의 `==`/`!=` 항은, 한쪽 피연산자가 base가 Text류(UUID,
Email, Phone, Currency, Html, Markdown, Text — 그 base의 refinement 포함)인 선언 필드를
직접(산술식 밖에서) 가리키면 **Text 등가 항**이다. 그 항은 이렇게 판정한다:

- 상대쪽이 선언 타입을 아는 참조면 두 base가 같아야 한다(3.1과 같은 규칙). 선언 타입을
  문서에서 알 수 없는 참조(네트워크 결과 등)는 판정을 런타임으로 미룬다.
- 상대쪽이 맨이름(점 없는 이름)이면 그것은 **리터럴**이고 이름의 글자 그대로와
  비교한다. 이 자리 밖의 맨이름은 오늘과 같이 payload 필드다. Text류 필드의 선언 타입이
  `enum` refinement면 리터럴은 그 멤버여야 하며, 아니면 컴파일 거부다(멤버 목록을 대고,
  가까운 멤버가 있으면 제안한다).
- 상대쪽이 숫자 리터럴이거나 Text류가 아닌 차원의 참조면 컴파일 거부다(같은 종류가
  아니다).
- 어느 쪽이든 산술식이면 컴파일 거부다 — Text에는 산술이 없다.

`Password` base 필드는 이 항에 쓸 수 없다(RFC-0066의 마스킹 의무 — 가드 스킵 레코드가
비교한 값을 싣는다). `DateTime`은 `instant` 차원 그대로다. 순서 비교(`<`/`<=`/`>`/`>=`)는
Text류에서 위 규칙대로 컴파일 거부다. Text 등가 항은 `and`로 다른 항과 이을 수 있고 `or`
대안에도 쓸 수 있다.

거부 메시지는 모두 `RFC-0051`을 이름으로 댄다. `Money × Money`/나눗셈은 "multiplies
(divides) two Money values", 그 밖의 섞임은 "combines a Money value with a <차원>
value via '<op>'", 비교 불일치는 RFC-0016의 "compares like with like" 문장 끝에
"Money compares only to Money (RFC-0051)"를, `set` 불일치는 "assigns <값> (<차원>)
to <대상> (<차원>) — RFC-0051 requires the same dimension on both sides"를 낸다.
Decimal 등 차원 없는 타입의 거부는 기존 첫 구절("is neither Integer nor DateTime")을
글자 그대로 유지하고, 괄호 안에서 RFC-0051과 RFC-0044 §Open Questions 3을 댄다.

### 4. `RepositoryDriver.query` 계약 확장 (D5)

```python
def query(self, entity_id, predicate=None, order=None, limit=None):
    ...
```

세 매개변수 모두 기본값 `None` — 이 RFC 이전의 모든 호출부(1개 위치 인자)가
바이트 단위로 그대로 동작한다. `predicate`는 `(field, op, value)` 3-튜플의
리스트(and로 결합), `order`는 `(field, desc)` 또는 `None`, `limit`은 양의
정수 또는 `None`.

**옵트인 푸시다운.** `supports_predicate = True`를 선언한 드라이버만 이 세
인자로 호출된다(§2의 스키마 속성이 있을 때). 선언하지 않은 드라이버(외부
SPI, 이 RFC 이전에 작성된 것 포함)는 절대 이 인자들을 받지 않는다 — 코어
(`interp.Interpreter`)가 대신 `query(entity_id)`만 호출해 전 행을 과다수신한
뒤 `repo_policy.apply_predicate`로 파이썬 쪽에서 걸러/정렬/제한하고, 실행
trace에 INFO 레벨로 한 줄을 남긴다:

```
predicate-not-pushed-down entity=<entity_id>
```

이 옵트인 관용구는 `testing.RepositoryDriverTCK`가 낙관적 버전 충돌
(`observed_version`, 이슈 #92)에 이미 쓰던 것과 같다 — 새 능력을 선언하지
않은 드라이버는 그 능력을 시험하는 TCK 케이스를 건너뛴다.

### 5. sqlite/Fake 구현 (D6)

`SqliteRepositoryDriver.query`는 이슈 #99 D7이 `query_sorted`에 세운 선례를
그대로 따른다 — 필드 이름은 `json_extract(payload, ?)`의 두 번째 인자로,
값은 평범한 바인드 파라미터로 실린다. 비교 연산자는 `condition.COMPARATORS`가
이미 닫아 둔 6개 기호에서 dict 조회로 고르는 고정 SQL 문자열이지, 문서
텍스트가 아니다(`drivers.py`의 "STATEMENT TEXT IS CONSTANT"). 문(statement)은
`AND json_extract(payload, ?) <op> ?` 형태의 고정 조각을 predicate 항 수만큼
이어 붙여 조립한다 — 조립되는 것은 SQL 조각의 **개수**뿐, 내용은 항상 미리
정해진 여섯 리터럴 중 하나다.

`interp.FakeRepository.query`와 `interp.Interpreter`의 비-푸시다운 폴백은
같은 함수(`repo_policy.apply_predicate`)에 위임한다 — 두 경로가 필터/정렬/
제한의 의미를 각자 구현하면 조용히 갈라질 수 있으므로, 의미는 한 곳에만
쓴다. `apply_predicate`는 이미 row_key 오름차순인 리스트를 받아 파이썬의
안정 정렬(`reverse=True`에서도 동순위 항목의 상대 순서를 보존한다는 문서화된
보장)로 `order`를 적용하므로, `desc`가 참이어도 동순위 타이브레이크는 항상
row_key 오름차순이다 — sqlite의 `ORDER BY <field> DESC, row_key`(row_key
자체는 항상 오름차순)와 정확히 같은 결과를 낸다.

### 6. mode B — 관측되지 않는 차원 (D9)

`list where`의 술어는 저장소에 쌓인 행 **값**으로 RowSet을 거른다. RFC-0025
§10이 이미 세운 판단 — RowSet 값(그리고 그로부터 계산되는 `sum`/`count`)은
RFC-0004의 네 관측 클래스(실행 순서+skips, 정책 결과, 관측 신호, 마스킹) 중
어느 것도 아니다 — 이 그대로 술어에도 적용된다. mode B는 술어를 컴파일하지도,
거부하지도 않는다(§2의 `predicate` 필드를 몰라도 `_render_std`는 여전히
effect kind 포인터만 낸다) — 그래서 `differential.compare_observations`가
내는 `EQUIVALENT`는 계속 참이다(네 클래스가 실제로 일치하면).

다만 `EQUIVALENT`만 보면 "걸러진 내용까지 같다"로 읽힐 여지가 있다 —
`docs/backends.md` §6이 sqlite 저장소 상태에 대해 이미 쓴 것과 같은
오독이다. `compare_observations`는 그래서 `document`/`workflow_id`가
주어지고 그 워크플로가 `list where` 스텝을 하나 이상 포함할 때, 판정 줄
뒤에 한 줄을 더 낸다:

```
note: 1 `list where` step(s) — filtered RowSet content is not compared (unverified dimension, docs/backends.md §6)
```

이 줄은 판정(`ok`)을 바꾸지 않는다 — 네 클래스가 정말로 일치하면 여전히
`EQUIVALENT`다. `document`/`workflow_id`를 넘기지 않는 기존 호출부(이
모듈 자신의 조작된-관측 테스트 포함)는 이 RFC 이전과 완전히 같게 동작한다.

## Examples

### 골든 시나리오 "Login" (RFC-0007 §6)

`Login` 워크플로는 `list`도 가드 밖의 조건 필드 참조도 쓰지 않는다 — 정본을
참조만 하고 재정의하지 않는다. 골든 자체는 바뀌지 않는다.

### 골든 인접 예제 — 걸러진 클릭 합계 (RFC-0007 §6, 골든이 다루지 않는 기능)

RFC-0075 §Examples의 클릭 합계 예제를 술어로 확장한다:

```
capability postgres

entity Link
    field
        id UUID
        clicks Integer
        active Boolean

entity Report
    field
        id UUID
        totalClicks Integer
        linkCount Integer

service Analytics
    policy
        timeout 5s

workflow SummarizeClicks
    find report
    list link where clicks > 0 order by clicks desc limit 10
    set report.totalClicks to sum link.clicks
    set report.linkCount to count link
    update report
    spec
        given
            stored Report id 1
            stored Link[0] clicks 5
            stored Link[1] clicks 0
            stored Link[2] clicks 3
        when
            summarizeClicks
        expect
            completed
            result report.totalClicks == 8
            result report.linkCount == 2
```

`clicks 0`인 `Link[1]`은 술어에 걸러져 RowSet에 들어가지 않는다 — 집계는
남은 두 행(5, 3)만 본다.

### 미선언 필드 — 후보 나열

```
workflow BadFilter
    list link where nosuch > 0
```

→ 컴파일 거부: `entity Link has no field 'nosuch' (candidates: active, clicks, id)`.

### 정적 거부 — Text 필드 순서 비교

```
entity Order
    field
        id UUID
        status Text

workflow BadOrder
    list order where status > input.x
```

`status`가 Text이므로 순서 비교(`>`)는 §Reference-level Specification/3의
표대로 컴파일 거부 — `expose list ... by <field>`가 Text 필드를 거부하는 것과
같은 사유(평가기가 없다). `status == input.x`(등가)였다면 §3.1에 따라
허용된다.

## Alternatives

| # | 검토한 대안 | 기각 사유 |
|---|------------|----------|
| 1 | **`where`에 새 표현식 언어를 만든다** | §Motivation의 핵심 통찰과 정면으로 배치된다 — `condition.py`가 이미 정확히 필요한 문법(필드 비교 + `and`)을 갖고 있는데 두 번째 파서를 만들면 두 문법이 조용히 갈라지는 결함 계열(RFC-0069 §Motivation)을 새로 연다. 이슈 #116도 이 재사용을 핵심 통찰로 명시한다 |
| 2 | **커서 기반 페이지네이션을 이번에 함께 넣는다** | RFC-0075 §Alternatives 대안 1과 같은 이유로 기각 — 커서·한계의 계약 설계는 별도 위키 결정(backend/common/api-design/pagination-contract)이 필요한 독립 작업이다. `limit`(오프셋 없는 절대 상한)만으로 이슈 #116의 DoD를 채운다. 커서·prefetch/batch는 이 태스크 체인의 다음 링크(#108)가 소유한다 |
| 3 | **등가의 타입 완화를 가드 조건 전반에 적용한다**(list where뿐 아니라 when/until도) | 이슈가 요구하는 범위를 넘는다 — 가드 조건의 등가를 넓히면 별도의 설계 결정(런타임 마스킹·mode B 관측 표면과의 상호작용 재검토)이 필요하고, 이 RFC의 §Motivation이 든 근거(list where 좌변은 항상 구체 타입을 갖는다)가 가드의 맨이름 좌변에는 그대로 적용되지 않는다. 두 문법 위치를 명시적으로 가르는 것(§Reference-level Specification/3.1)이 RFC-0075 §Alternatives 대안 4의 원칙과도 맞다 |
| 4 | **드라이버가 predicate를 항상 받게 하고, 미지원 드라이버는 예외를 던지게 한다** | 기존 외부 SPI 드라이버(이슈 #75)를 전부 깨뜨린다 — `RepositoryDriverTCK`가 낙관적 버전 충돌에 이미 쓰는 옵트인 관용구(`supports_predicate`)를 재사용하면, 이 RFC 이전에 작성된 드라이버가 아무 수정 없이 계속 동작한다(폴백 경로로) |
| 5 | **`list where`의 술어를 mode B가 정적으로 판정하려 시도한다** | RFC-0075 §Alternatives 대안 6과 같은 이유로 불필요 — RowSet 값은 애초에 mode B의 비교 대상이 아니다(§Reference-level Specification/6). 판정할 게 없는 것을 판정하려는 것은 세우지도 않은 요구를 충족시키는 일이다 |

## Open Questions

1. **avg/min/max/group by.** 이슈 #116 §4가 명시적으로 범위 밖에 둔다 — 집계
   함수를 `sum`/`count`(RFC-0025) 이상으로 넓히는 것과 `group by`는 별개
   설계 질문(다중 그룹의 RowSet 표현)이라 후속 이슈로 이월한다.
2. **커서 페이지네이션.** 위 §Alternatives 대안 2가 이월한 것 그대로 —
   `expose list`의 서빙 계층 페이지네이션과 `list where`의 `limit`이 같은
   커서 개념을 공유해야 하는지는 후속 이슈가 결정한다.
3. **prefetch/batch.** 이 태스크 체인의 다음 링크(#108)가 이 RFC가 내놓는
   구조화 술어 IR을 소비해 N+1 질의를 배치로 묶는 확장을 낼 것으로 예상한다
   — 그 설계는 이 RFC의 범위 밖이다.

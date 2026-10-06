# RFC-0053: optional 필드 수식어

## Status

- Status: Draft
- Updates: RFC-0001 §Reference-level Specification/노드 카탈로그/Entity,
  RFC-0016 §Reference-level Specification/3. 피연산자의 차원 규칙,
  RFC-0038 §Reference-level Specification/3. 등가 비교의 타입 규칙,
  RFC-0015 §Reference-level Specification/3. 정적 거부

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목하고, 규칙 5(연쇄 갱신)에 따라 이미
갱신된 절은 대상과 **직전 갱신 RFC를 모두** 지목한다. 이 RFC는 Draft이므로 대상
RFC에 `Updated-by:` 포인터를 달지 않는다(Accepted가 되는 시점의 일이다).

- **노드 카탈로그/Entity(RFC-0001).** RFC-0001 머리의 `Updated-by:`는 노드 카탈로그의
  Guard 행(RFC-0028)만 가리킨다 — Entity 행은 이번이 첫 갱신이다. 아래 §2가 그 행의
  치환 후 최종 텍스트다.
- **차원 규칙(RFC-0016 §3).** RFC-0038 §3이 이미 갱신한 절이다(RFC-0016 머리의
  `Updated-by: RFC-0038 (§Reference-level Specification/3)`). 그래서 RFC-0016 §3과
  RFC-0038 §3을 함께 지목한다. Draft RFC-0051 §1이 같은 절을 갱신하는 중이므로, 아래
  §6의 최종 텍스트는 RFC-0051 §1의 최종 텍스트 **위에** 3.2 한 항을 더한 것이다.
- **정적 거부(RFC-0015 §3).** RFC-0015 머리의 `Updated-by:`는 §1과 §4만 가리킨다.
  Draft RFC-0051 §2가 §3을 갱신하는 중이므로, 아래 §7의 최종 텍스트는 RFC-0051 §2의
  표 **위에** 두 행을 고치고 한 행을 더한 것이다.

구현은 두 단계로 들어간다. 1단계는 §1–§5, §11의 EVERY 규칙(§11 셋째 항목), §12, 그리고
§8의 진단 코드 **등록**(`CODES`/`SEVERITY_OF`/`HINTS`와 문서 표)이다. 2단계는 §6 3.2,
§7의 바뀐 두 행, §8의 경고 **발행**, §9, §10, §11의 첫째·둘째 항목이다. 두 단계가 모두
들어가기 전까지 2단계 항목은 이 문서에만 있는 계약이다.

## Motivation

엔티티 필드는 선언하면 전부 필수다(issue #208). 필드 하나를 추가하는 순간 그 필드를
모르는 기존 클라이언트의 요청이 전부 `400 validation-failed`가 된다:

```
$ lnpl run g3.lnpl --payload g3.json --json
failed | missing required field 'nickname'
```

Google AIP-180은 "기존 요청 메시지나 리소스에 새 필수 필드를 추가하지 않는다"를
호환성 규칙으로 둔다. 이 언어에서는 모든 필드 추가가 필수 필드 추가라 그 규칙을
지킬 방법이 없다. AIP-203은 필드마다 `REQUIRED`/`OPTIONAL`/`OUTPUT_ONLY`를 선언하게
하는데, `derived`(issue #95)가 `OUTPUT_ONLY` 자리를 채웠고 `OPTIONAL` 자리는 비어
있다. `docs/migration.md`의 expand 단계도 저장된 행에 대한 관용만 다루고, 요청
payload 쪽에는 답이 없었다(`validate`를 떼는 것뿐이었다).

이 RFC는 "없을 수 있다"만 연다. 기본값(`default <값>`)은 별도 결정이다(§Alternatives).

## Guide-level Explanation

필드 선언 끝에 `optional`을 붙이면 그 필드는 보내지 않아도 된다:

```lnpl
entity Customer
    field
        id UUID
        email Email
        nickname Text optional
```

- `validate customer`는 `nickname`이 없거나 `null`이어도 통과한다. 값이 있으면
  예전처럼 타입과 refinement를 검사한다 — `"nickname": 5`는 여전히 400이다.
- `create customer`는 없는 필드를 행에 싣지 않는다. 기본값을 지어내지 않는다.
- 생성되는 OpenAPI에서 `nickname`은 `required`에서 빠진다.
- `lnpl db check`와 `stored-row-shape-mismatch`는 `nickname`이 없는 행을 불일치로
  세지 않는다. `lnpl migrate --set nickname=<값>`은 그대로 쓸 수 있다.
- `respond customer.nickname`과 `emit ... with customer.nickname`은 값이 없으면 그
  키를 빼고 보낸다. `null`을 지어내지 않는다.
- 읽는 쪽은 `when customer.nickname exists`로 부재를 가른다. `optional` 필드에는
  타입과 무관하게 존재 검사가 열린다.

`optional`과 `derived`는 함께 쓸 수 없다 — 서버가 채우는 값에 "입력에서 빠져도
된다"는 말은 뜻이 없다. 필드 이름이 `id`면 `optional`일 수 없다 — 행 키가 `id`에서
나오기 때문이다.

필수로 좁히려면(contract) `optional`을 뗀다. 그 순간부터 그 필드를 보내지 않는 옛
클라이언트는 다시 400을 받는다.

## Reference-level Specification

### 1. 문법 — 필드 수식어

필드 줄은 `<name> <Type> <Modifier>*`이고 수식어는 0–2개다. 수식어 어휘는 닫혀 있다:
`derived`, `optional`. `lower`가 판정한다(파서는 `field` 절을 토큰 줄로만 넘긴다).

| 입력 | 결과 |
|------|------|
| 토큰이 2개 미만이거나 4개 초과 | 컴파일 거부 — 받은 토큰 수를 댄다 |
| 어휘 밖의 수식어 | 컴파일 거부 — 그 낱말과 전체 어휘 `derived, optional`을 댄다 |
| 같은 수식어 두 번 | 컴파일 거부 — 반복된 낱말을 댄다 |
| `derived`와 `optional`을 함께(순서 무관) | 컴파일 거부 — 두 낱말과 RFC-0053를 댄다 |
| 필드 이름 `id`에 `optional` | 컴파일 거부 — 행 키 `row_key`는 `id`가 없으면 모든 행이 같은 `-` 키로 떨어진다 |

수식어 자리는 앞으로 다른 필드 표기가 들어올 수 있게 열어 둔다. 새 낱말은 이 표의
어휘에 더하는 방식으로만 들어온다.

### 2. IR — 노드 카탈로그/Entity 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0001 §노드 카탈로그 표의 Entity 행 치환 후
최종 텍스트다.

> | kind | 필수 필드 | 선택 필드 | children 허용 |
> |------|----------|----------|--------------|
> | Entity | `name`, `fields`(배열: `{name, type(Semantic Type명 또는 refinement), required(기본 true), derived(issue #95), optional(RFC-0053)}`) | `constraints`(Constraint id[]) | Validation(엔티티 불변식) |

- `optional`은 boolean이고, 수식어를 쓴 필드에만 `true`로 실린다. 쓰지 않은 필드에는
  키 자체가 없다(`false`가 아니다) — `optional`을 쓰지 않은 모듈의 IR은 이 RFC 전과
  바이트 단위로 같다. `derived`도 같은 규칙이다.
- `schemas/lir.schema.json`의 `fieldList` 항목은 `optional: boolean`을 받는다.
- `required` 키는 컴파일러가 쓰지 않는다. RFC-0001 §부록 A/A.4의 "생략 시 참" 의미론은
  그대로다. 다만 이 RFC부터 `required`를 읽는 소비자는 없다 — `validate`는 원래 읽지
  않았고, OpenAPI 생성기도 이 RFC에서 `optional`만 읽게 바뀌었다. 선택성의 유일한
  표기는 `optional`이다.

### 3. 입력 경계 — `validate`와 `null`

- **부재와 `null`은 같다.** `optional` 필드에 대해 payload에 키가 없는 것과 값이 JSON
  `null`인 것은 둘 다 "보내지 않음"이다. `optional`이 아닌 필드의 `null`은 예전처럼
  타입 검사에서 거부된다.
- **`validate <entity>`(`semantic-types`).** `optional` 필드가 없거나 `null`이면 건너뛴다.
  값이 있으면 `check_semantic_type`으로 검사한다. `derived` 필드 규칙은 그대로다.
- **`validate <field>`(한 필드 단축형).** 대상 필드가 `optional`이고 없거나 `null`이면
  통과한다. 그 밖에는 예전과 같다.
- 이 판정은 `interp.validate_effect` 한 곳에 있다. 모드 B의 `backend._validation_fails`가
  워크플로를 실행하지 않고 이 함수를 직접 부르므로, `null` 판정도 이 함수 안에 있어야
  한다.
- **실행 경계 정규화.** `Interpreter.run_workflow`는 시작할 때 payload에서 `null`인
  키를 한 번 지운다. 대상은 그 이름을 선언한 엔티티가 **모두** `optional`로 표시한
  이름뿐이다(§11 셋째 항목). 그 뒤의 `validate`, `create`, 수식 없는 `emit`이 모두 같은
  payload를 본다.

### 4. 저장 — `create`, `db check`, `migrate`, `_schema_gen`

- **`create`.** 같은 이름 필드를 payload에서 행으로 복사할 때(issue #97), `optional`
  필드는 payload에 키가 없으면 싣지 않는다. `null`이면 역시 싣지 않는다 — 이 판정은
  만들어지는 엔티티 자신의 선언으로 다시 한다. 다른 엔티티가 같은 이름을 필수로
  선언해 §3의 정규화가 `null`을 남긴 경우를 여기서 막는다. `optional`이 아닌 필드의
  `null`은 예전처럼 그대로 복사된다.
- **`row_shape_mismatches`(`db check`, `stored-row-shape-mismatch`).** `optional` 필드는
  저장된 행에 키가 없거나 값이 `null`이어도 불일치가 아니다. 값이 있는데 타입이 틀리면
  예전처럼 `kind: "type"`이다. 필수 필드의 부재는 예전처럼 `kind: "missing"`이다.
- **`lnpl migrate --set <optional 필드>=<값>`.** 코드 변경이 없다. `optional` 필드도 보통
  `--set` 대상이다 — 의도적 선택이다. "없을 수 있다"는 요청 쪽 관용이고, 저장된 행을
  일괄 채우는 것은 별개의 운영 결정이다. 대상 행은 그 키가 **없는** 행뿐이다. 키가
  있고 값이 `null`인 행은 값이 있는 행으로 보고 건너뛴다(`skipped`).
- **`_schema_gen`.** 해시는 예전처럼 비-`derived` 필드의 `(name, type)` 쌍이다.
  `optional`은 들어가지 않는다. 필드를 `optional`로 바꿔도 저장 타입도, 값이 있을 때의
  모양도 변하지 않는다. 바뀌는 것은 키가 빠질 수 있는지뿐이고, 그것은
  `row_shape_mismatches`가 매번 엔티티 선언에서 다시 읽는다. 그래서 기존 행의 스탬프는
  그대로 유효하고, 이 RFC가 만드는 마이그레이션은 없다.

### 5. 응답·이벤트·OpenAPI

- **`respond`.** 묶인 행에 `optional` 필드가 없거나 값이 `null`이면 그 참조를 응답에서
  뺀다. `respond-field-missing` 경고는 내지 않는다 — 선언된 모양이기 때문이다. 필수
  필드의 부재는 예전처럼 경고 한 건과 함께 빠진다(issue #198).
- **`emit ... with`.** 참조가 `optional` 필드를 가리키고 값이 `null`로 해석되면 그
  키를 이벤트 payload에서 뺀다. `null`을 지어내지 않는다. 묶인 이름의 엔티티는
  `create ... as`의 행이 가진 `entity_id`로, 아니면 기본 바인딩 이름으로 찾는다.
  `input.<field>` 참조의 선택성은 §11 셋째 항목을 따른다.
- **수식 없는 `emit`.** plain `emit`(`with` 절 없음)은 필드별 엔티티 문맥이 없어서
  `create`처럼 엔티티별로 다시 판정할 수 없다. §3의 정규화만 받는다. 그래서 한 엔티티는
  이름을 `optional`로, 다른 엔티티는 필수로 선언한 이름 충돌 모양에서는, plain `emit`이
  그 필드의 `null`을 그대로 내보낼 수 있다. 받아들인 좁은 한계다.
- **OpenAPI 엔티티 스키마.** `optional` 필드는 `required`에서 빠지고 값에 `null`이
  허용된다: 일반 타입은 `"type": ["<type>", "null"]`, refinement는 `{"oneOf": [{"$ref":
  ...}, {"type": "null"}]}`. `Json`의 스키마는 `{}`라 이미 `null`을 받으므로 그대로
  둔다.
- **GET 응답의 비대칭.** GET 단건·목록 응답은 요청과 같은 엔티티 컴포넌트를
  `$ref`한다. 그래서 서버가 `null`을 보내지 않고 키를 omit하는데도, GET 응답
  스키마에는 `optional` 필드가 nullable로 보인다. 받아들인 비대칭이다.
- **`respond` 응답 스키마.** `optional` 필드는 `required`에서 빠지지만 nullable 표시는
  붙지 않는다 — 서버는 키를 빼지 `null`을 보내지 않는다. 묶음의 모든 필드가
  `optional`이면 그 묶음 스키마에는 `required` 키가 없다.

### 6. 피연산자의 차원 규칙 — RFC-0016 §3 / RFC-0038 §3 갱신 (치환 후 최종 텍스트)

RFC-0007 §2.2 규칙 4에 따라, 아래 인용은 RFC-0016 §Reference-level Specification/3의
치환 후 최종 텍스트다(RFC-0038이 붙인 3.1과 Draft RFC-0051 §1의 텍스트 포함). 인용
안의 "RFC-0015"는 RFC-0015 §3을 가리킨다.

> RFC-0015의 "Integer 한정"을 **차원 규칙**이 대체한다.
>
> - `instant` — 선언 타입이 `DateTime`이거나 base가 `DateTime`인 refinement
> - `scalar` — `Integer`, base가 `Integer`인 refinement, 정수 리터럴, **Duration 리터럴**
> - `money` — 선언 타입이 `Money`이거나 base가 `Money`인 refinement (RFC-0051)
>
> | 식 | 결과 |
> |----|------|
> | `instant - instant` | `scalar` (경과 밀리초) |
> | `instant + scalar`, `instant - scalar` | `instant` |
> | `scalar ± scalar` | `scalar` |
> | `instant + instant` | **컴파일 거부** |
> | `money ± money` | `money` |
> | `money * scalar`, `scalar * money` | `money` |
> | `money * money`, `money / X`, `X / money` | **컴파일 거부** |
> | `money ± scalar`, `money ± instant`, `scalar ± money`, `instant ± money` | **컴파일 거부** |
> | `<X> <cmp> <Y>`, `dim(X) == dim(Y)` | 허용 |
> | `<X> <cmp> <Y>`, `dim(X) != dim(Y)` | **컴파일 거부** |
> | `set <T> to <E>`, `dim(T)`와 `dim(E)`가 둘 다 정해지고 다르다 | **컴파일 거부** (RFC-0051) |
>
> 선언 타입을 문서에서 알 수 없는 피연산자(맨이름, 네트워크 결과 참조)는 어느
> 차원도 아니며, 오늘과 같이 정적 검사를 통과하고 런타임이 판정한다. 이 규칙이
> 기존에 컴파일되던 프로그램에 만드는 **신규 거부는 표의 마지막 행 하나뿐이다** —
> `set` 대상과 값의 차원이 다른 경우(예: DateTime 필드에 Integer 식을 넣는
> 것)로, 이전에는 정적 검사를 통과한 뒤 런타임에 잘못된 값을 저장했다. RFC-0051
> 시점에 저장소의 모든 `set` 줄(`examples/*.lnpl`, `impl/tests/*.py`, 50건)을 전수
> 분류해 이 행에 걸리는 기존 프로그램이 0건임을 확인했다.
>
> 이 규칙이 t2 F-5 ③(`payment.createdAt <= 43200m`)을 `instant` vs `scalar`로 거부한다.
> RFC-0015도 이 형태를 거부했으나 사유가 "DateTime은 평가기가 없다"였다. 이제 평가기가
> 있으므로, 거부 사유는 **두 양이 같은 종류가 아니라는 것**이다. `money`도 같다:
> `when payment.fee > 0`은 "평가기 없음"이 아니라 `money` 대 `scalar` 불일치로 거부된다.
>
> `Money`의 통화는 타입이 아니라 행 데이터이므로 **정적 차원은 통화를 구분하지
> 않는다** — 같은 `money` 차원의 두 값이 다른 통화인지는 런타임이 판정한다
> (RFC-0044 §5).
>
> `Decimal`·`Text`·`Password`와 그 밖의 합성 타입은 여전히 어느 차원도 아니며 컴파일
> 거부다(RFC-0015 §D6 유지, Decimal은 RFC-0044 §Open Questions 3).
>
> #### 3.1 `list where`의 등가 비교 (RFC-0038)
>
> 위 표의 마지막 두 비교 행(`dim(X) == dim(Y)`이면 허용, 다르면 거부)은 `list
> where`에서는 **좌변이 Integer나 DateTime일 때**의 규칙이다. `list <Entity> where
> <cond>`(RFC-0038)의 좌변은 나열 대상 엔티티 자신의 선언 필드이므로 항상 구체적인
> 선언 타입을 갖는다 — 그 타입이 Integer도 DateTime도 아닐 때(UUID, Text, Email,
> Money 등), 순서 비교(`<`/`<=`/`>`/`>=`)는 컴파일 거부다(등가와 달리 순서에는
> 평가기가 필요하다 — Text에 `<`가 없다는 원 규칙의 근거는 그대로 유효하고, Money의
> 순서 평가기는 드라이버 푸시다운에 없다). RFC-0051의 `money` 차원은 가드와 `set`에만
> 열린다 — `list where`와 `expose list ... by`는 Money를 이 RFC 이전과 똑같이 다룬다.
>
> 하지만 등가(`==`/`!=`)는 평가기를 요구하지 않는다 — 두 값이 같은지는 비교
> 연산자 없이도 판정된다. 그래서 `list where`의 등가는 차원이 아니라 **선언
> 타입 자체의 일치**로 판정한다: 좌변 필드의 base 타입과 우변이 이름하는
> 필드의 base 타입이 같으면(둘 다 Text든, 둘 다 UUID든) 허용, 다르면 거부.
> 우변이 정적으로 알 수 없는 것(맨 `input.<field>`처럼 선언 타입이 문서에
> 없는 경우)은 원 규칙과 같이 판정을 런타임으로 미룬다.
>
> 이 좁힘은 **`list where`에만** 적용된다 — 가드 조건의 등가(`when status ==
> input.wantedStatus`)는 위 표(차원 규칙)로만 판정되고, Text 필드를 가드에서
> 비교하면 여전히 컴파일 거부다. `list where`는 `Condition` 문법을 재사용하지만,
> 그 판정 함수(`lower._check_list_predicate`)는 가드의 판정 함수
> (`lower._check_dimensions`)와 별개이므로 한쪽을 넓혀도 다른 쪽은 조용히 넓어지지
> 않는다.
>
> #### 3.2 `optional` 필드의 존재 검사 (RFC-0053)
>
> `exists`/`missing`은 값을 평가하지 않고 키가 있는지만 본다. 그래서 피연산자가
> `optional`로 선언된 필드(RFC-0001 §노드 카탈로그/Entity)이면 **선언 타입과 무관하게**
> 존재 검사를 허용한다 — Text·Money·합성 타입도 포함된다. 값이 `null`이면 키가 없는
> 것과 같이 `missing`이다. `optional`이 아닌 필드의 존재 검사는 위 규칙 그대로다.
> 이 예외는 존재 검사에만 있다. `optional` 필드를 비교·산술에 쓰는 것은 위 표가
> 그 선언 타입대로 판정한다.

### 7. 정적 거부 — RFC-0015 §3 갱신 (치환 후 최종 텍스트)

> 문법이 받되 문서를 보면 거부되는 형태들이다. 전부 `lower`에서 판정한다 — 문서만으로
> 결정 가능한 것을 런타임까지 미루면 t2 F-4처럼 인터프리터 내부의 원시 예외가 조작자에게
> 샌다.
>
> | 거부 | 사유 |
> |------|------|
> | 양변이 모두 리터럴(`1 < 2`) | 아무것도 결정하지 않는 가드는 저작 오류다 |
> | 선언 타입이 어느 차원(RFC-0016 §3: Integer·DateTime·Money)도 아닌 피연산자 | 평가기가 없다. 실측: `payment.amount`(Money) 가드가 경고 없이 컴파일된 뒤 `TypeError: '<=' not supported between instances of 'dict' and 'int'`로 죽었다(t2 F-4). Money는 RFC-0051부터 차원이 있으므로 이 행이 아니라 차원 불일치 행으로 판정된다. Decimal은 여전히 이 행이다 |
> | 차원 규칙(RFC-0016 §3)이 거부하는 식·비교·할당 | 두 양이 같은 종류가 아니다 — 인스턴트와 숫자, Money와 숫자, Money와 Money의 곱·몫 |
> | `optional`이 아닌 선언된 Money 필드에 `exists`/`missing` | RFC-0051이 여는 부분집합은 비교와 산술이다. 존재 검사는 열지 않는다(RFC-0051 §Reference-level Specification/7). `optional` Money 필드의 존재 검사는 RFC-0016 §3 3.2가 연다(RFC-0053) |
> | `input.<field>`의 `<field>`를 어떤 엔티티도 선언하지 않음 | payload는 선언된 전 엔티티 필드의 합집합이다. 그 밖의 이름은 오타다 |
> | 엔티티명 `Input` | 바인딩 이름이 `input` 네임스페이스와 충돌한다 |
> | 할당 대상이 `input.…` 또는 맨이름 | 입력은 이 워크플로가 소유한 상태가 아니다 |
> | 할당 대상 엔티티를 워크플로가 read하지 않음 | 바인딩이 존재할 수 없다(RFC-0012 §G12.5와 같은 사유) |
> | 앞선 스텝이 할당한 Reference를 뒤의 가드가 읽음 | 모드 B는 조건 필드를 진입 시 i64 파라미터로 고정 받는다. 그런 프로그램은 두 모드가 다른 값을 본다 |
> | `and` 안의 `exists`/`missing` | §1의 두 채널 사유 |
> | `input.<field>`에 `exists`/`missing`, 그 `<field>`를 선언한 엔티티가 둘 이상인데 `optional` 표시가 엇갈림 | 존재 검사의 허용 여부(RFC-0016 §3 3.2)가 엔티티마다 다르다. 어느 엔티티의 선언을 따를지 정할 근거가 없으므로 선언한 엔티티를 모두 대고 거부한다(RFC-0053) |

바뀐 것은 셋이다: Money 존재 검사 행이 `optional`이 아닌 Money 필드로 좁혀졌고, 맨 아래
`input.<field>` 존재 검사 행이 새로 생겼다. 나머지 행은 RFC-0051 §2와 글자 단위로
같다.

### 8. 산술 경고 — `optional-field-unguarded-arithmetic`

- **코드.** `optional-field-unguarded-arithmetic`, 등급 `warning`(RFC-0021: 프로그램을
  고치면 사라진다). `CODES`·`SEVERITY_OF`·`HINTS`와 `docs/ENFORCEMENT-MATRIX.md` §C에
  등록된다.
- **발행 조건.** `set`의 산술식, 또는 가드 비교의 산술 피연산자가 `optional` 필드를
  읽는데, 그 스텝을 소유한 가장 가까운 가드가 같은 필드의 `when <ref> exists`(대안 없는
  `when` 모드)가 아닐 때. 메시지는 줄 번호와 고칠 방법(그 스텝 앞에 `when <ref>
  exists`를 둔다)을 댄다.
- **가드 조건 자신의 산술은 보호받을 수 없다.** 가드는 스텝 하나나 블록 하나만
  소유하고, 가드 줄은 열린 `pipeline`을 닫으며, `exists`는 `and`와 결합하지 않는다.
  그래서 가드 조건(또는 `or` 대안)의 산술이 `optional` 필드를 읽으면 언제나 경고다.
  고치려면 그 자리에 `optional`이 아닌 필드를 쓴다. 해석되지 않는 참조를 담은 비교는
  런타임에 거짓으로 평가되어(`skipped[].evaluations[].holds`가 `false`) 가드가
  건너뛰어질 뿐 실행이 실패하지는 않는다.
- **값만 읽는 경우는 경고 대상이 아니다.** `set x to customer.nickname`이나 `format ...
  with customer.nickname`처럼 산술 없이 값을 읽는 스텝이 없는 `optional` 필드를 만나면,
  이 RFC 전과 똑같이 그 스텝이 `RunError`로 실패한다("a reference ... resolves to
  nothing"). 이 RFC는 그 동작을 바꾸지 않는다. 경고는 산술만 덮는다.

### 9. 집계·정렬

- **집계.** `sum`/`avg`/`min`/`max`는 `optional` 필드가 없거나 `null`인 행을 건너뛴다.
  `count`는 그대로 행 수다. 건너뛴 결과 남은 값이 없으면 기존의 빈 RowSet 규칙이 그대로
  적용된다. 모든 행에 값이 없는 Money 타입 `optional` 필드의 `sum`은 `agg_field_type`을
  통해 RFC-0047의 Money 모양 0(`{"amount": "0", "currency": null}`)을 낸다. 정수 `0`이
  아니다.
- **정렬.** `order by`와 `expose list ... by`에서 정렬 필드가 없는 행은 오름차순이든
  내림차순이든 **맨 뒤**에 온다. 두 백엔드(fake, sqlite) 모두 같다. 커서 페이지네이션의
  비교도 값이 없는 행을 같은 순서로 다룬다. 커서 토큰의 형식은 바뀌지 않는다.

### 10. 모드 B

모드 B(`lnpl build`, `lnpl diff`)는 `optional` 필드를 읽는 가드가 있는 워크플로를
RFC-0053를 대며 거부한다 — 존재 검사든 비교든 같다. 모드 A는 해석되지 않는 참조를
거짓으로 읽지만, 모드 B의 값 인코딩은 없는 값을 i64 `0`으로 받기 때문에 두 모드가
다른 답을 낸다. `build`와 `diff`는 같은 순서로 거부한다(issue #185). `optional`을
쓰지 않는 프로그램의 모드 B 동작과 RFC-0016 §5의 등가 표는 바뀌지 않는다.

### 11. `input.<field>`의 선택성 — 메커니즘마다 다른 세 규칙

`input.<field>`의 `<field>`는 엔티티 하나의 필드가 아니라 선언된 모든 엔티티 필드의
합집합에서 온다. 그래서 같은 이름을 여러 엔티티가 선언하고 `optional` 표시가 엇갈릴
수 있다. 아래 셋은 서로 다른 메커니즘의 서로 다른 규칙이다. 어느 것도 선언 순서에
기대지 않는다.

- **존재 검사는 컴파일 오류로 막는다.** `when input.note exists`(또는 `missing`)는 `note`를
  선언한 엔티티가 둘 이상이고 그중 하나라도 `optional`이 아니면 compile error다 —
  선언한 엔티티를 이름순으로 모두 댄다. 모두 `optional`이면 §6 3.2대로 컴파일된다.
- **모드 B 거부는 하나라도 표시했으면 선택으로 본다.** §10의 거부를 판정할 때
  `input.note`는 `note`를 선언한 엔티티 중 ANY(하나라도)가 `optional`이면 선택 필드로
  본다 — 보수적인 OR이다.
- **런타임 생략은 모두 표시했을 때만 선택으로 본다.** §3의 `null` 정규화와 §5의
  `emit ... with` 생략은 `input.note`를 `note`를 선언한 엔티티 EVERY(전부)가
  `optional`일 때만 선택 필드로 본다 — 보수적인 AND다. 엇갈리면 그 참조는 필수
  필드처럼 다뤄진다: 정규화가 `null`을 지우지 않고, `emit ... with`는 `null`을 그대로
  싣는다.

### 12. 관측

`wsgi.py`의 표준 구조화 로그 줄이 싣는 `input_digest`는 원래 요청 payload(마스킹 후)로
계산한다. `Interpreter.run_workflow`가 실행되기 전이므로 §3의 정규화보다 앞선다. 그래서
`optional` 필드에 `null`을 담은 요청은 보낸 그대로 digest된다. 결함이 아니라 기록해 둔
사실이다.

## Examples

### 골든 시나리오 "Login" (RFC-0007 §6)

골든 시나리오는 `optional`을 쓰지 않는다. 이 RFC 뒤에도 `examples/login.lnpl`의 IR,
OpenAPI, 모드 B 출력은 바이트 단위로 같다.

### 골든 인접 예제 — issue #208 고객 등록 (RFC-0007 §6, 골든이 다루지 않는 기능)

커밋되는 예제 파일이 아니라 이 RFC 본문의 설계 예시다. 값은 모두 지어낸 것이다.

```lnpl
capability postgres

entity Customer
    field
        id UUID
        email Email
        nickname Text optional

service CustomerService

workflow Register
    validate customer
    create customer
```

| payload | 결과 |
|---------|------|
| `{"id": "00000000-0000-4000-8000-000000000002", "email": "qa@example.com"}` | 완료. 저장된 행에 `nickname` 키가 없다 |
| 위 payload + `"nickname": null` | 완료. 저장된 행에 `nickname` 키가 없다 |
| 위 payload + `"nickname": "Ace"` | 완료. 행에 `"nickname": "Ace"` |
| 위 payload + `"nickname": 5` | `400 validation-failed` — 타입 검사는 그대로다 |

생성되는 `Customer` 스키마(발췌):

```json
{
  "properties": {
    "id": {"type": "string", "format": "uuid"},
    "email": {"type": "string", "format": "email"},
    "nickname": {"type": ["string", "null"]}
  },
  "required": ["id", "email"]
}
```

### 컴파일 거부

```
nickname Text optional derived   → field cannot be both `derived` and `optional`
nickname Text optional optional  → field modifier 'optional' repeated
nickname Text banana             → unknown field modifier 'banana' — valid modifiers are derived, optional
id UUID optional                 → field 'id' cannot be `optional`
```

## Alternatives

### 기본값 `default <값>` (이 RFC에서 제외)

issue #208이 함께 언급하지만 넣지 않는다. 기본값은 "없을 때 무엇으로 볼 것인가"를
정하는 별도 결정이다: 저장할 때 채우는지, 읽을 때 채우는지, 이미 저장된 행에도 소급하는지,
OpenAPI `default`와 어떻게 맞출지가 모두 따로 정해져야 한다. 먼저 "없을 수 있다"만 열고,
기본값은 별도 RFC로 다룬다.

### 타입 쪽 표기 `Text?` (기각)

선택성은 값의 종류가 아니라 필드 행동(AIP-203의 field behavior)이다. 타입 이름에
붙이면 refinement 이름 해소(RFC-0001 부록 A.6.1)와 섞이고, `derived`와 같은 자리에
두는 일관성도 잃는다.

### 기존 `required: false` 키 재사용 (기각)

RFC-0001 카탈로그에 이미 `required(기본 true)`가 있다. 그러나 컴파일러는 그 키를 쓴 적이
없고, `validate`도 읽은 적이 없다 — OpenAPI 생성기만 읽었다. 그 키를 재사용하면 소스의
낱말(`optional`)과 IR의 키(`required: false`)가 이름도 극성도 달라진다. `derived`가 이미
"소스 낱말 = IR 키, 쓴 필드에만 `true`"를 선례로 세웠으므로 그것을 따른다.

### 해시 `_schema_gen`에 `optional` 포함 (기각)

필드의 `optional` 표시만 바꿔도 이후 쓰이는 모든 행의 스탬프가 바뀐다. 그러나 두
스탬프를 비교하는 코드가 없고, 행 모양 판정은 매번 엔티티 선언에서 다시 읽는다. 얻는
것 없이 스탬프만 흔들린다.

### `id`에도 `optional` 허용 (기각)

`id`가 없으면 `row_key`가 모든 행을 같은 `-` 키로 보낸다. 두 번째 `create`가 첫 행을
덮어쓴다.

## Open Questions

1. **기본값.** `default <값>`의 의미론(쓰기 시점·읽기 시점·소급 여부)은 별도 RFC다.
2. **값만 읽는 스텝의 정적 검사.** `set x to customer.nickname`처럼 산술 없이 값을 읽는
   스텝은 지금 런타임 `RunError`다(§8). 이것도 컴파일 경고로 앞당길지는 사용 경험을
   보고 정한다.
3. **plain `emit`의 이름 충돌.** §5의 좁은 한계를 없애려면 plain `emit`에 엔티티 문맥을
   주어야 한다. 이벤트 payload 계약(RFC-0049)과 함께 다룬다.

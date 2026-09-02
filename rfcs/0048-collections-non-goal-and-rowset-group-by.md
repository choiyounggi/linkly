# RFC-0048: 컬렉션 필드 비목표 확정과 RowSet `group by`

## Status

- Status: Draft
- Updates: RFC-0001 §Open Questions/1, RFC-0025 §Reference-level Specification/1
  (RFC-0038 §Reference-level Specification/1이 이미 갱신한 절 — 이 개정은 그
  절의 최종 텍스트 위에 grouped-list 전용 carve-out을 더한다), RFC-0025
  §Reference-level Specification/3 (RFC-0045 §Reference-level Specification/2가
  이미 갱신한 절 — 이 개정은 그 절의 최종 텍스트 위에 그룹-파생 RowSet의 필드
  참조 화이트리스트를 더한다), RFC-0012 §G12.2 (RFC-0025
  §Reference-level Specification/5, RFC-0027 §Reference-level Specification/4,
  RFC-0030 §Reference-level Specification/2가 이미 갱신한 절 — 이 개정은 그
  절의 최종 텍스트 위에 grouped-list의 다섯 번째 바인딩 이름공간을 더한다),
  RFC-0038 §Reference-level Specification/2, RFC-0038 §Open Questions/1,
  RFC-0045 §Open Questions/1

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목하고, 규칙 2에 따라 모순되는
모든 절을 지목하며, 규칙 5(연쇄 갱신)에 따라 이미 갱신된 절은 대상 RFC와
직전 갱신 RFC를 모두 지목한다 — 형식은 RFC-0027 §Status·RFC-0030 §Status의
선례를 따른다.

번호가 0048인 이유: 0047까지 점유됐다(RFC-0047, 집계 필드 타입 이행).
RFC-0007 §3은 번호 재사용을 금지한다.

## Motivation

"컬렉션 타입을 아직 넣지 않았다"와 "컬렉션 타입을 영구히 넣지 않기로 했다"는
결과 문장이 똑같아 보이지만 결정 여부가 완전히 다르다 — 전자는 다음 이슈가
언제든 다시 열 수 있는 자리이고, 후자는 그 자리를 정식으로 닫는다. RFC-0001
§Open Questions 1이 이 질문을 "미결"로 남긴 채 이미 세 번의 RFC(0025 RowSet,
0038 list where, 0045 avg/min/max)를 거쳤고, 그때마다 "컬렉션 대신 RowSet"이라는
같은 방향의 실무 결정이 반복됐다 — 그런데도 §Open Questions 1의 문면은 여전히
열려 있다. 미결로 남은 질문은 그 자체로 다음 세션의 LLM에게 "여기 아직 여지가
있다"는 신호가 되고, 신호가 있으면 지어낼 공간이 생긴다 — `field tags:
List<Text>`처럼 파서는 통과하지 않지만(RFC-0002 Full grammar가 필드 타입
생산 규칙에 컬렉션을 두지 않았으므로) 그 "안 된다"가 규범 문장으로 어디에도
적혀 있지 않은 상태다. 이 RFC는 그 방향성을 결정 문장으로 바꾼다.

`group by`는 그 자체로 두 번 이월된 질문이다. RFC-0038 §Open Questions 1이
"avg/min/max/group by"를 한데 묶어 후속 이슈로 넘겼고, RFC-0045가 avg/min/max만
거두고 group by 절반을 다시 RFC-0045 §Open Questions 1로 이월했다 — 매번 이유는
같다: "그룹마다 결과를 내는 형태를 `set`의 단일 값 계약과 어떻게 조화시킬지"가
안 풀렸기 때문이다(RFC-0045 §Alternatives 1). 이 RFC는 그 조화를 `set` 경로
밖에서 푼다 — 그룹화+집계를 `set`이 아니라 새 파생 RowSet 생성 문장으로 닫는다.

## Guide-level Explanation

**(a) 필드에 컬렉션 타입은 없다.** 관계는 엔티티 참조로 표현하고(예: `field
owner: User`), 다건 조회는 필드가 아니라 `list <Entity> where <cond>`
(RFC-0038)라는 별도 질의 문장으로 얻는다. `field tags: List<Text>`나 `field
items: Map<Text, Integer>` 같은 문장을 쓰고 싶어지면, 그건 아직 없는 문법이
아니라 이 RFC가 영구히 열지 않기로 한 자리다 — 대신 별도 엔티티 + `list ...
where`로 표현한다.

**(b) `group by ... aggregate ...`는 파생 RowSet을 만든다.** `list <alias>
from <entity> where <cond> group by <key> aggregate <func> [<field>]`는
소스 엔티티의 행을 조건으로 거른 뒤 그룹 키로 나누고, 그룹마다 기존 집계
5종(`count`/`sum`/`avg`/`min`/`max`, RFC-0025·RFC-0045) 중 하나를 적용해
(그룹 키, 집계값) 두 컬럼짜리 새 RowSet `<alias>`를 만든다. 이 파생 RowSet은
보통 RowSet처럼 소비한다 — `order by`/`limit`/그 위에 다시 집계 5종을 걸 수
있다. 그룹 수 자체가 필요하면 `count <alias>`로 파생 RowSet의 행 수를 세면
된다(그룹당 집계와는 다른 질문). 그룹별 원본 행 목록(예: "이 그룹에 속한
주문들을 나열해줘")은 이 RFC가 다루지 않는다 — `## Open Questions`로 이월한다.

## Reference-level Specification

### 1. 필드 선언 문법에 컬렉션 생산 규칙을 더하지 않는다 (D1)

RFC-0002 Full grammar의 필드 타입 생산 규칙(`FieldType`, base 18종 +
refinement)에 List/Map/Optional 등 컬렉션류 생산 규칙을 추가하지 않는다 —
**v1의 영구 비목표로 확정한다.** RFC-0001 §Open Questions 1이 미결로 남긴
"제네릭/컬렉션 타입" 질문에 대한 답이 이것이다: 다건 관계는 RowSet(RFC-0025)과
`list where`(RFC-0038)로 이미 표현 가능하므로, 필드 수준 컬렉션은 같은 요구를
문법 표면에 중복해서 여는 것이지 새 표현력을 더하는 것이 아니다.

### 2. 그룹화 RowSet — 문법 (D3)

```
GroupedList  ::= 'list' Word 'from' EntityName 'where' Condition
                 'group' 'by' FieldRef 'aggregate' AggFunc (FieldRef)?
```

`Word`는 파생 RowSet에 붙일 별칭(alias)이다. `EntityName`·`Condition`은
`list where`(RFC-0038)와 같은 생산 규칙을 재사용한다. `FieldRef`는 그룹 키로
쓸, 소스 엔티티가 선언한 필드 하나를 가리킨다(한정 없는 bare 이름). `AggFunc`는
RFC-0045가 넓힌 그 다섯(`sum`/`count`/`avg`/`min`/`max`) 그대로이며, 새 함수를
더하지 않는다. `count`는 두 번째 `FieldRef`를 생략할 수 있다(RFC-0025 §3의
기존 규칙과 같은 모양) — 나머지 넷은 필수다.

**규범:**

(a) `<alias>`는 고정 2컬럼 `key`/`value`의 파생 RowSet이다. 컬럼 이름은 이
    닫힌 어휘 두 개로 고정되며, 사용자가 다른 이름을 붙일 수 없다 — 다른
    RowSet과 달리 컬럼 이름이 필드 선언에서 오지 않기 때문에, 이름을 열어두면
    그 자체가 새 어휘 발명의 자리가 된다.

(b) `group by`의 `where` 조건은 그룹화보다 먼저 평가된다 — 소스 엔티티의
    행을 거른 **다음** 남은 행을 그룹으로 나눈다. 문법 생산 규칙 자체가
    `where`를 필수로 두므로(위 EBNF), 별도의 "조건 없는 그룹화" 형태는
    존재하지 않는다.

(c) 집계 5종은 그룹당 그대로 재사용된다 — 새 집계 함수나 새 표현식 언어를
    만들지 않는다. `value` 컬럼의 타입은 그 집계 함수가 이미 내는 결과 타입
    규칙(RFC-0025 §Reference-level Specification/4, RFC-0045
    §Reference-level Specification/1·3·5)을 그대로 따른다 — `count`는
    Integer, `sum`/`avg`는 소스 필드 타입에 따라 Integer 또는 Money(RFC-0045
    §2의 허용표), `min`/`max`는 Integer·DateTime·Money(같은 표).

(d) 그룹 키(`FieldRef`)로 쓸 수 있는 필드 타입은 집계 대상 필드에 적용하는
    허용표(RFC-0045 §Reference-level Specification/2)를 그대로 적용한다 —
    별도의 그룹 키 타입표를 새로 만들지 않는다. 표를 여기 복사하지 않고
    참조만 한다 — 표가 나중에 넓어지면 그룹 키 허용범위도 같이 넓어져야
    정합하므로, 복사본을 두면 오히려 어긋날 위험이 생긴다.

(e) 파생 RowSet `<alias>`는 기존 RowSet이 이미 지원하는 소비 계약만 받는다 —
    `order by`/`limit`(RFC-0038), 그 위에 다시 집계 5종 적용, 그리고 값이
    Money일 때 RFC-0044가 정의한 직렬화 규칙. **재그룹화는 v1에서 금지한다**
    — `<alias>`에 다시 `group by`를 거는 문장은 정적 거부 대상이다(§5).

(f) 그룹 수는 별도 어휘 없이 `count <alias>`로 도출한다 — 파생 RowSet도
    RowSet이므로 `count`가 이미 갖는 "행 수를 센다"는 의미를 그대로 받는다.

(g) 이 RFC는 **설계를 확정**한다 — 문법·타입·바인딩·정적 거부 규칙을
    규범화하지만, 파서·`lower`·런타임의 실제 구현은 이 RFC의 범위 밖이며
    후속 이슈로 분리한다. Status가 Draft인 이유이자, RFC-0007 §2.2 규칙 6에
    따라 이 개정들은 이 RFC가 Accepted되는 순간부터 효력을 갖는다 — 아직은
    아니다.

### 3. 하강(lowering) — 새 IR 노드 종류, VERB_LEXICON carve-out — RFC-0025 §1 갱신 (연쇄, 치환 후 최종 텍스트) (D3)

> 갱신됨: RFC-0048

RFC-0007 §2.2 규칙 5에 따라, RFC-0025 §Reference-level Specification/1을 이미
갱신한 RFC-0038 §Reference-level Specification/1도 함께 지목한다 — 그 절의
효력 있는 텍스트는 RFC-0025 원문이 아니라 RFC-0038 §1에 있으므로, 이 개정은
그 위에 grouped-list 전용 carve-out만 더한다.

**치환 후 최종 텍스트**: RFC-0038 §1이 정의한 `VERB_LEXICON`의 `list ->
RepositoryCall(query)` 매핑과 `ListTail` 문법(`where`/`order by`/`limit`)은
**비그룹 `list` 형태에만 적용된다.** `group by`를 동반한 `list`(§2의
`GroupedList`)는 `RepositoryCall`로 하강하지 않고, 별도의 IR 노드 종류로
하강한다(가칭 `GroupedQuery` — 정확한 명칭은 구현 시점에 기존 IR 노드 명명
관례에 맞춰 확정하되, "`RepositoryCall`이 아닌 새 종류"라는 결정 자체는 이
RFC가 고정한다). 두 형태는 문법 생산 규칙이 다르므로(`ListTail`은 `group by`를
포함하지 않는다, §2) 파스 시점에 이미 구분되며, 하강 시점에 다시 판별할 필요가
없다.

### 4. 바인딩 — 다섯 번째 이름공간 — RFC-0012 §G12.2 갱신 (연쇄, 치환 후 최종 텍스트) (D3)

RFC-0007 §2.2 규칙 5에 따라, RFC-0012 §G12.2를 이미 갱신한 RFC-0025 §5·
RFC-0027 §4·RFC-0030 §2를 모두 함께 지목한다 — 그 절의 효력 있는 텍스트는
RFC-0012 원문이 아니라 RFC-0030 §2에 있다(단일 행/RowSet/네트워크 결과/생성
결과 네 이름공간을 이미 규정한다).

**치환 후 최종 텍스트**: 위 네 이름공간의 규칙은 이 개정이 손대지 않는다.
grouped-list(§2의 `GroupedList`)는 다섯 번째 이름공간에 바인딩한다 —
**바인딩 이름**은 문장이 명시한 `<alias>`이고(엔티티의 camelCase 선언
이름에서 유도하지 않는다 — RowSet 바인딩과 달리 소스 엔티티 이름과 `<alias>`가
같을 이유가 없다), **바인딩 값**은 §2가 만든 (key, value) 파생 행 목록이다.
마지막 쓰기가 이긴다는 규칙은 그대로다 — 같은 `<alias>`로 다시 grouped-list를
실행하면 바인딩이 갱신된다. 비그룹 `list`(단일 행 바인딩·RowSet 바인딩)의
기존 규칙은 이 개정으로 바뀌지 않는다.

### 5. 필드 참조 화이트리스트 — RFC-0025 §3 갱신 (연쇄, 치환 후 최종 텍스트) + RFC-0038 §2 참조 범위 확인 (D3)

RFC-0007 §2.2 규칙 5에 따라, RFC-0025 §Reference-level Specification/3을 이미
갱신한 RFC-0045 §Reference-level Specification/2도 함께 지목한다 — 그 절의
효력 있는 텍스트는 RFC-0025 원문이 아니라 RFC-0045 §2에 있다.

**치환 후 최종 텍스트**: RFC-0045 §2의 정적 거부 표는 이 개정이 손대지
않는다. 그 위에 grouped-list 전용 행을 더한다:

| 거부 | 사유 |
|------|------|
| grouped-list 파생 RowSet(`<alias>`)에 대한 필드 참조가 `key`/`value` 외의 이름 | §2(a)의 고정 2컬럼 화이트리스트 — 정확히 `{key, value}`만 허용한다 |
| grouped-list 파생 RowSet에 다시 `group by`를 거는 문장(재그룹화) | §2(e)가 v1에서 금지한다 |

RFC-0038 §Reference-level Specification/2(술어 IR의 `predicate.field`
화이트리스트)는 이 개정이 지목하지 않는다 — grouped-list의 `where` 절은
그룹화 이전에, 소스 엔티티에 대해 평가되므로(§2(b)) 그 절이 이미 규정한
"나열 대상 엔티티가 실제로 선언한 필드 이름만 허용"이라는 화이트리스트가
텍스트 변경 없이 그대로 적용된다 — grouped-list가 여는 것은 그 위에 얹히는
그룹 키·집계 대상 필드 참조(§2 (c)(d))와, 결과로 나온 파생 RowSet에 대한
별개의 화이트리스트(위 표)뿐이다.

## Examples

골든 시나리오 "Login"(정본: `plans/rfc-suite/plan.md` §골든 시나리오)은
`group by`를 쓰지 않는다. RFC-0007 §6에 따라 골든을 확장해 기능을 넣지 않고
골든 인접 예제를 대신 보인다 — 아래는 커밋되는 파일이 아니라 이 RFC 본문의
설계 예시이며, §Reference-level Specification/2(g)가 명시하듯 v1 구현 전이므로
컴파일 검증 대상이 아니다.

```lnpl
workflow SummarizeSignupDomains
    list domainCounts from user where createdAt > input.since group by email aggregate count
    set summary.distinctEmails to count domainCounts
```

골든의 `entity User`(`id`/`email`/`password`/`createdAt`)에 필드를 추가하지
않는다(RFC-0009 §Examples 선례와 같은 모양). `domainCounts`는 이메일별 가입
건수의 (key, value) 파생 RowSet이고, `count domainCounts`는 서로 다른 이메일
값의 개수(그룹 수)를 센다.

## Alternatives

1. **최소 List 타입 도입** — 컬렉션 필드를 아주 좁은 형태(예: 스칼라 base의
   `List<T>` 하나만)로 열어주는 안. 기각: refinement-only 원칙과 정면으로
   충돌하고(D1), 한 번 열면 다음 이슈가 "왜 Map은 안 되냐"고 되묻는 자리가
   된다 — 좁게 여는 것도 여는 것이다.
2. **count-groups 스칼라만 도출** — `group by`가 그룹 수만 내고 그룹별 집계값은
   내지 않는 안. 기각: 이슈 문면이 요구하는 "그룹당 집계 5종 재사용"에
   미달한다(사용자 결정) — 그룹별 매출 합계 같은 흔한 요구를 표현할 수 없다.
3. **그룹별 값 배열 + 새 순회 구조** — 그룹마다 소속 행을 배열로 담아 반환하고
   워크플로가 그 배열을 순회하는 안. 기각: linkly는 임의 순회 구조를 열지
   않는다는 기존 원칙(RFC-0025 §Alternatives 6)과 정면으로 충돌한다 — `set`이
   소비할 수 있는 것은 스칼라거나 §2가 정의하는 고정 2컬럼 RowSet뿐이어야 그
   원칙이 유지된다.

## Open Questions

1. **다중 키 그룹화** (`group by a, b`) — 이 RFC의 `GroupedList`는 `FieldRef`
   하나만 받는다. 복합 키를 어떻게 `key` 컬럼 하나에 표현할지(예: 튜플 인코딩)
   후속 이슈로 이월한다.
2. **파생 RowSet 재그룹화** — §Reference-level Specification/2(e)가 v1에서
   정적으로 거부한다. 필요해지면 별도 RFC가 다룬다.
3. **per-group 비집계 투영(그룹별 행 목록)** — "이 그룹에 속한 원본 행을 그대로
   보여줘" 요구는 이 RFC가 닫지 않는다. RFC-0045 §Alternatives 1과 같은 이유로
   여전히 미해결이다: 그룹마다 임의 개수의 행을 내는 구조는 linkly의 "임의
   순회 금지" 원칙과 조화되지 않는다 — 이 RFC가 하는 것은 집계값 하나로 닫는
   경로를 여는 것뿐이고, 행 목록 경로는 재이월한다.
4. **그룹 키가 refinement 필드일 때의 등가 비교 규칙** — `FieldRef`가
   refinement 타입(예: `Slug`)일 때 그룹 등가 판정이 base 타입 비교와 같은지,
   refinement의 `pattern`/`enum` 제약이 그룹 경계에 영향을 주는지는 다루지
   않는다.

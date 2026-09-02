# RFC-0025: 행 집합(Row Set)과 집계

## Status

- Status: **Accepted** (RFC-0025, 2026-08-18)
- Updates: RFC-0012 §G12.2, RFC-0012 §G12.4, RFC-0012 §G12.5, RFC-0015 §1
- Updated-by: RFC-0038 (§Reference-level Specification/1)

RFC-0007 §2.2 규칙 1에 따라 절을 이름으로 지목한다. G12.2가 정의하는 실행 스코프
바인딩 규칙에 RowSet 바인딩을 더하고, G12.5가 정의하는 한정 참조의 컴파일 시점
거부 검사 ⓒ를 "이 워크플로가 그 Entity를 read로 부른다"로 좁힌다 — 아래 §Motivation이
적듯, G12.5 ⓒ의 현재 문구("read 또는 query")는 `query`가 죽은 경로였을 때는 결코
참이 되지 않았지만 `list`가 그 경로를 살리는 순간 잘못된 승인을 낳는다. G12.4의
설명 문단 하나도 그 결과로 갱신한다(§6) — "바인딩이 아직 없다" 행이 실제로 관측되는
경로를 `query가 행을 찾지 못한 경우`라고 적은 문장이, `query`가 단일 행 바인딩에서
빠지면서 더는 사실이 아니게 된다. RFC-0015 §1의 `AssignStep` 생산 규칙에는 집계
대안(`Aggregate`)을 더한다(§2) — 새 생산 규칙이라도 RFC-0015가 "효력 있는 계약"으로
선언한 절을 넓히는 것이므로, RFC-0012·RFC-0015 자신이 각각 RFC-0002의 생산 규칙을
순수 추가로 넓혔을 때도 `Updates:`를 선언한 것과 같은 전례를 따른다. 넷 다 지목하지
않으면 RFC-0007 §2.2 규칙 1(누락 없는 지목)·규칙 2(모순 금지) 위반이다.

번호가 0025인 이유: 0024까지 점유됐다. RFC-0007 §3은 번호 재사용을 금지한다.

언어 워킹네임은 **LNPL**(소스 확장자 `.lnpl`)이다.

## Motivation

이슈 #65가 여는 질문은 RFC-0015가 이미 적어 둔 것이다. RFC-0015 §Alternatives는
집계(`sum`/`count`)를 그 개정에 넣지 않기로 결정하면서 이렇게 적었다:

> 집계는 값 문법이 아니라 **행 집합**을 요구한다. 이 플랫폼의 실행 모형에는 그것이
> 없다: 저장소는 단일 키 조회다(`FakeRepository.execute(entity, operation, key)`).
> 실행 스코프는 엔티티당 행 **하나**를 바인딩한다(RFC-0012 §G12.2). 그 단일 키
> 불변식이 모드 B의 정적 판정을 떠받친다.

그리고 §Open Questions 3에 되돌릴 조건을 명시적으로 남겼다: "집합 타입, 질의 동사,
모드 B의 루프." 이 RFC는 그 세 가지를 채운다.

관측 가능한 형태로 다시 적으면, 이 레포에는 이미 그 방향을 가리키는 죽은 코드가
있다. `impl/lnpl/interp.py:25`와 `impl/lnpl/backend.py:492`의 `IDEMPOTENT_OPS`는
`("RepositoryCall", "query")`를 이미 담고 있고, `schemas/lir.schema.json`의
`nodeRepositoryCall.operation` enum도 이미 `"query"`를 받는다. 그러나 `VERB_LEXICON`
(`impl/lnpl/lower.py`)의 17개 동사 중 어느 것도 `operation="query"`인 `RepositoryCall`을
만들지 않는다 — 표면 동사가 없어서 이 경로는 한 번도 실행되지 않았다. 이슈 #36이
잡은 것과 같은 결함 계열("죽은 표면")을 반대 방향에서 보여주는 사례다: 이번엔 어휘
밖 동사가 아니라 **어휘가 결코 만들지 않는 내부 상수**다.

`impl/lnpl/interp.py`의 `FakeRepository.execute`를 보면 그 죽은 경로의 의도조차
지금은 틀렸다는 것을 알 수 있다: `operation in ("read", "query")`일 때 둘 다
`table.get(key)`로 **행 하나**를 돌려준다. 즉 이 코드가 살아났다 해도 `list`가
필요로 하는 "엔티티의 전 행"을 주지 못한다. 이 RFC는 `query`를 진짜 다중 행 경로로
재정의한다.

## Guide-level Explanation

저자가 새로 쓸 수 있게 되는 것은 두 가지다.

**1. 엔티티의 전 행을 읽는다.**

```
workflow SummarizeClicks
    find report
    list link
    set report.totalClicks to sum link.clicks
    update report
```

`list link`는 `Link` 엔티티의 **모든 행**을 실행 스코프에 RowSet으로 바인딩한다.
`find report`가 하는 단일 행 바인딩(`report.<field>` 형태로 읽는)과는 별개다 —
`link`는 이제 이 워크플로 안에서 "RowSet"이라는 자격으로만 쓸 수 있고, `link.id`
같은 단일 행 필드 참조는 여전히 거부된다(RowSet은 D3의 집계 표현식으로만 소비된다).

**2. 집계해서 필드에 기록한다.**

```
    set report.totalClicks to sum link.clicks
    set report.linkCount to count link
```

`sum <entity>.<field>`는 RowSet의 그 필드를 전부 더한다. `count <entity>`는 행
수를 센다. 두 형태 다 `set`의 새 우변이고, RFC-0015가 이미 허용한 산술
(`product.stock - input.quantity`)과는 **결합하지 않는다** — `sum link.clicks + 1`은
쓸 수 없다. 대상 행이 0개면 `sum`은 0, `count`는 0이다. 빈 목록이 오류가 아니라는
것은 언어 차원의 결정이다: 링크가 하나도 없는 리포트는 흔한 정상 상태이지, 예외가
아니다.

**쓸 수 없는 것**은 §Reference-level Specification/3의 표에 있다. 가장 자주 걸릴
것: `sum`의 대상 필드는 Integer 선언이어야 한다(Money·Decimal은 정적 거부 —
RFC-0015 §3과 같은 이유, 평가기가 없다). 그리고 `list` 없이 `sum`/`count`를 쓰면
컴파일은 되지만 경고가 뜬다 — RowSet이 결코 채워지지 않는 자리를 놓친 흔적이기
때문이다(§Reference-level Specification/4).

**필터·정렬·페이지네이션은 없다.** `list link`는 항상 전 행이다. 부분 집합을
고르거나 순서를 정하거나 페이지로 나누는 표기는 이 RFC의 범위 밖이다
(§Alternatives).

## Reference-level Specification

### 1. `VERB_LEXICON`과 표면 문법 (D1)

> 갱신됨: RFC-0048

`impl/lnpl/lower.py`의 `VERB_LEXICON`에 18번째 항목을 더한다:

```python
"list": ("RepositoryCall", {"operation": "query"}),
```

`operation="query"`는 신설이 아니라 §Motivation이 적은 기존 상수의 **재사용**이다
— `IDEMPOTENT_OPS`(interp.py·backend.py 양쪽), `repo_policy.READ_OPS`,
`schemas/lir.schema.json`의 `nodeRepositoryCall.operation` enum 모두 이미
`"query"`를 담고 있었다. `list`는 그 값에 처음으로 도달하는 표면 동사다.

문법 자체(`RFC-0002 §Full grammar`의 `StepLine ::= Verb Word? Word? Word? EOL`,
`Verb ::= Word`)는 바뀌지 않는다 — `list`는 소문자로 시작하는 임의의 단어이므로
이미 `Verb` 생산 규칙 안에 있다. 닫힌 어휘 판정은 문법이 아니라 `VERB_LEXICON`
딕셔너리가 한다(이슈 #36이 세운 원칙 그대로). 이 RFC가 문법에 더하는 것은
집계 표현식뿐이다(§2).

### 2. 집계 표현식 문법 — RFC-0015 §1 갱신 (치환 후 최종 텍스트) (D3)

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0015 §1의 `AssignStep` 생산 규칙에 대한
**치환 후 최종 텍스트**다. 이 절의 다른 생산 규칙(`Condition`/`Value`/`Operand`/
`ArithOp`/`Reference`/`Namespace`/렉시컬 항목)은 RFC-0015 원문이 그대로 유효하며
이 RFC가 손대지 않는다.

```
AssignStep    ::= 'set' Reference 'to' (Value | Aggregate)
Aggregate     ::= AggFunc Reference
AggFunc       ::= 'sum' | 'count'
```

**Old (RFC-0015 §1):**
```
AssignStep   ::= 'set' Reference 'to' Value
```

`Value`와 `Aggregate`는 **결합하지 않는 별개 생산 규칙**이다 — 기존 `Value`(산술)를
넓혀 집계를 흡수하면 `sum x + 1`이 파싱되게 되는데, 이는 Guide-level Explanation이
명시적으로 금지한 형태다. `AssignStep`이 두 우변 중 하나를 택일해 받는 것으로,
표현력의 결합 없이 집계라는 세 번째 값 출처를 더한다.

`Reference`는 RFC-0015 §1이 정의한 그대로다(`CamelName | Namespace '.' CamelName`).
`count link`의 `Reference`는 한 조각(RowSet 바인딩 이름), `sum link.clicks`의
`Reference`는 두 조각(RowSet 바인딩 이름 + 필드)이다. 파서 층위에서 `Aggregate`와
`Value`는 첫 토큰(`sum`/`count` 대 그 밖)으로 구별되며, 렉서·`given`/`expect`
phrase 라인의 토큰화(`Line.tokens = body.split()`)는 바뀌지 않는다.

**정규화.** `Assignment.expression`(RFC-0015 §2)에 싣는 문자열은 `<func> <ref>`,
공백 1칸 — `"sum link.clicks"`, `"count link"`. `Assignment` 노드의 다른 필드
(`kind`/`id`/`target`/`entity`)와 스키마(`schemas/lir.schema.json`의
`nodeAssignment`)는 바뀌지 않는다: `expression`은 이미 자유 문자열이고
(`"type": "string"`, 패턴 제약 없음), 정규화된 새 형태를 싣는 데 스키마 변경이
필요 없다.

### 3. 정적 거부 (컴파일 에러, rc=2) — RFC-0015 §3 확장과 같은 층위

> 갱신됨: RFC-0048

`lower`에서 판정한다(문서만으로 결정 가능한 것을 런타임까지 미루지 않는다는
RFC-0015 §3의 원칙 그대로).

| 거부 | 사유 |
|------|------|
| `count`의 `Reference`가 두 조각(`count link.clicks`) | `count`는 행 수를 세지 필드를 보지 않는다. 필드를 쓰고 싶다면 `sum`이다 |
| `sum`의 `Reference`가 한 조각(`sum link`) | `sum`은 더할 필드가 필요하다 |
| `Aggregate`의 `Reference`가 가리키는 엔티티가 이 모듈에 선언되지 않음 | §4의 진단과는 다른 판정이다 — 여기서는 이름 자체가 미선언이라 어떤 `list`로도 결코 채울 수 없다. §4는 엔티티가 선언은 됐지만 **이 워크플로**가 그것을 `list`하지 않은 경우다 |
| `sum`의 필드 선언 타입이 Integer가 아님(Money·Decimal 등) | 평가기가 없다. RFC-0015 §3의 같은 행과 동일 사유 |
| `Aggregate` 할당 대상(`report.totalClicks`)의 엔티티를 워크플로가 `read`하지 않음 | RFC-0015 §3의 기존 규칙 그대로 — 바인딩이 존재할 수 없다 |
| `list`의 대상이 선언되지 않은 엔티티 | 여느 `RepositoryCall`과 같은 기존 판정(엔티티 미선언) |

### 4. `list` 없는 집계 참조 — 컴파일 타임 경고 (D3)

정적 거부(§3)와 달리, 이 판정은 대상 엔티티가 선언돼 있고 `Aggregate` 문법도
올바르지만 **이 워크플로가 그 엔티티를 `list`한 적이 없는** 경우다. 컴파일은
통과하지만(실행하면 §5의 규칙대로 RowSet이 비어 있어 0을 낸다 — 저자가 의도하지
않았을 값이다) 경고가 난다.

RFC-0023이 세운 것과 같은 접근(결과 기반 진단, `impl/lnpl/diagnostics.py`의
"no new machinery" 원칙)을 따른다. 신규 코드 하나:

| 코드 | 등급 | 방출 시점 | 근거 |
|------|------|-----------|------|
| `aggregation-orphaned-list` | `warning` | lowering (컴파일 타임) | 프로그램에 `list <entity>`를 추가하면 사라진다 — RFC-0021의 등급 질문("고치면 사라지는가?")에 그렇다로 답하므로 `warning` |

`diagnostics.py`의 `CODES`에 `"aggregation-orphaned-list"`를 추가하고
`SEVERITY_OF`에 `"warning"`으로 매핑한다 — 새 필드도 새 레코드 타입도 없다
(RFC-0021 §Reference-level Specification/"등급은 레코드가 아니라 표가 정한다").
기존 방출 시그니처 `diagnostics.add(code=, where=, subject=, message=)`(RFC-0021이
정한 키워드 전용 형태)를 그대로 쓴다.

판정 규칙: `Aggregate`가 가리키는 RowSet 바인딩 이름이 이 워크플로의 최상위
자식 목록에서 그 `Aggregate`보다 **앞선 순서에** `list`로 나타나지 않으면 발화한다.
가드 아래 있는 `list`는 그 가드가 거짓일 수 있으므로 앞선 것으로 세지 않는다 —
RFC-0023 §3의 "가드 아래 있는 것은 이미 조건부" 판정과 같은 이유다.

### 5. 실행 스코프 — RFC-0012 §G12.2 갱신 (치환 후 최종 텍스트) (D2)

> 갱신됨: RFC-0048

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0012 §G12.2의 **치환 후 최종 텍스트**다.
RFC-0012의 다른 절(G12.1, G12.3, G12.4, G12.6, G12.7)은 이 RFC가 지목하지 않으며
그대로 유효하다(§G12.5는 §6에서 별도로 갱신한다).

#### G12.2 무엇이 바인딩되는가

이 실행에서 완료된 `RepositoryCall`마다 그 `operation`에 따라 **서로 다른 이름
공간**에 바인딩이 하나 생긴다. 한 엔티티는 최대 **단일 행 바인딩 1개 + RowSet
바인딩 1개**를 동시에 가질 수 있다 — 둘은 같은 바인딩 이름(엔티티의 camelCase
선언 이름)을 공유하지만, **어느 쪽이 해석되는지는 참조가 나타나는 문법 위치가
결정한다**: `Condition`/`expect result`의 `<binding>.<field>`(RFC-0012 §G12.1)는
언제나 단일 행 바인딩을 본다. `Aggregate`의 `Reference`(§2)는 언제나 RowSet
바인딩을 본다. 두 문법 위치가 겹치지 않으므로 충돌은 없다 — RFC-0012 §G12.3이
bare/한정 이름 사이에 이미 세운 것과 같은 "문법 형태가 가른다"는 원칙을 두
바인딩 종류 사이로 넓힌 것이다.

**단일 행 바인딩** (`operation == "read"`인 호출만 — `query`는 더는 여기 속하지
않는다. §G12.5도 이 RFC가 함께 갱신한다):

- **바인딩 이름**은 Entity의 선언 이름을 camelCase로 바꾼 것이다: `Product` →
  `product`. IR의 노드 id에서 유도하지 않는다.
- **바인딩 값**은 저장소가 돌려준 행이다.
- **마지막 쓰기가 이긴다.** 같은 Entity를 다시 `read`하면 바인딩이 갱신된다.

**RowSet 바인딩** (`operation == "query"`인 호출만 — 이 RFC가 처음 도달시키는
경로, §Motivation 참조):

- **바인딩 이름**은 단일 행 바인딩과 같은 규칙(camelCase 선언 이름)이되, 별개
  이름 공간에 놓인다.
- **바인딩 값**은 드라이버의 `query(entity_id)`가 돌려준 행 리스트다(§7).
  드라이버가 행을 하나도 못 찾으면 빈 리스트다 — 부재가 아니라 **빈 RowSet**이며,
  §4의 규칙대로 그 위의 집계는 실패하지 않고 0을 낸다.
- **마지막 쓰기가 이긴다.** 같은 Entity를 다시 `list`하면 RowSet이 갱신된다.
- RowSet은 **읽기 전용 소비**다 — `<binding>.<field>` 형태의 단일 필드 참조로도,
  다른 쓰기 대상으로도 쓸 수 없다. 집계(§2)로만 소비된다.

`create`·`update`·`delete`는 어느 이름 공간에도 바인딩하지 않는다 — RFC-0012
원문의 사유(영향 행 수만 돌려주므로 바인딩할 행 내용이 없다) 그대로다.

### 6. 한정 참조 — RFC-0012 §G12.4·§G12.5 갱신 (치환 후 최종 텍스트)

#### 6.1 해석되지 않는 이름 — §G12.4

RFC-0007 §2.2 규칙 4에 따라, 아래는 RFC-0012 §G12.4의 **치환 후 최종 텍스트**다.
바뀌는 것은 표의 두 번째 행 이름과, 그 행을 설명하는 마지막 문단뿐이다 — 네 경우가
같은 한 규칙(해석 결과가 없으면 `Presence`는 부재로, `Comparison`은 거짓으로
평가된다)을 따른다는 것과 마지막 행의 예외(실행 오류)는 원문 그대로다.

| 상황 | `exists` | `missing` | `Comparison` |
|------|----------|-----------|--------------|
| payload에 그 필드가 없다 | 거짓 | 참 | **거짓** |
| 바인딩이 아직 없다(읽기 전) | 거짓 | 참 | **거짓** |
| 바인딩은 있으나 행에 그 필드가 없다 | 거짓 | 참 | **거짓** |
| 값이 정수로 해석되지 않는다 | 거짓 | 참 | **실행 오류** |

**Old (RFC-0012 §G12.4)** 두 번째 행: "바인딩이 아직 없다(읽기 전 / `query`가 행을
못 찾음)".

**마지막 행만 예외다**: 비교 대상이 존재하는데 숫자가 아닌 것은 부재가 아니라
오류이며, 참조 구현은 필드 이름과 조건 문자열을 담은 실행 오류를 낸다(RFC-0012
원문 그대로 — 이 RFC가 손대지 않는다).

`read`가 행을 찾지 못하면 그 스텝이 실패하므로 후속 가드에 도달하지 못한다. 이
RFC 이전에는 두 번째 행이 실제로 관측되는 경로가 `query`가 행을 찾지 못한 경우였다
— `query`도 그때는 단일 행 바인딩에 참여했기 때문이다(RFC-0012 원문 §G12.2). §5가
`query`를 그 이름 공간에서 빼고, §6.2(G12.5 ⓒ)가 `query`만 있고 `read`가 없는
엔티티로의 한정 참조 자체를 컴파일 거부로 막은 뒤로는, 그 경로가 더는 존재하지
않는다. 두 번째 행이 이제 실제로 관측되는 유일한 경로는 **읽기 전**이다 — 가드나
`expect`가 프로그램 순서상 그 엔티티의 `read`보다 앞서 있어서, 그 시점엔 아직
바인딩이 생기지 않은 경우(G12.5 ⓒ는 워크플로 **어딘가에** `read`가 있으면 만족되고,
그 `read`가 참조보다 뒤에 와도 된다).

#### 6.2 한정 참조의 컴파일 시점 거부 — §G12.5

RFC-0012 §G12.5의 검사 ⓒ만 바뀐다. ⓐ와 ⓑ는 원문 그대로 유효하다.

| # | 검사 | 어긋났을 때 |
|---|------|-------------|
| ⓐ | `binding`이 선언된 Entity의 바인딩 이름과 일치한다 | 컴파일 실패 |
| ⓑ | 그 Entity가 `field`를 선언한다 | 컴파일 실패 |
| ⓒ | 이 워크플로가 그 Entity를 **`read`**(`authenticate`/`load`/`find`/`read`)로 부른다 | 컴파일 실패 |

**Old (RFC-0012 §G12.5 ⓒ):** "이 워크플로가 그 Entity를 `read`/`query`로 부른다."

`query`를 뺀 이유는 §5(G12.2)가 그 결과다 — `query`는 이제 단일 행이 아니라
RowSet을 바인딩하므로, `query`만 있고 `read`가 없는 워크플로에서 `<binding>.<field>`
한정 참조를 허용하면 결코 채워지지 않는 단일 행 바인딩을 조용히 참조하게 된다
(G12.4 "바인딩이 아직 없다"로 흡수돼 조용히 거짓이 되는데, 그 침묵이 §Motivation이
연 질문 — "죽은 경로가 틀린 채로 살아난다" — 을 반복한다). 이 갱신 전에는 `query`가
죽은 경로였으므로 ⓒ의 이 분기는 결코 참이 되지 않았다 — 관측 가능한 프로그램의
의미는 바뀌지 않는다. `read`(및 `authenticate`/`load`/`find`— 전부 `operation="read"`로
lower되는 동의어)만 있던 기존 프로그램의 컴파일 결과도 그대로다.

### 7. `RepositoryDriver` 계약 (D5)

`impl/lnpl/drivers.py`의 `RepositoryDriver`에 신규 메서드를 더한다. 기존
`execute(entity_id, operation, key)` 시그니처는 **바뀌지 않는다** — 호출부
전수 열거(`interp.py`의 실행 사이트, 계약 스위트) 부담을 피하려는 D5의 결정이다.

```python
def query(self, entity_id):
    """모든 행을 결정적 순서로. entity_id에 행이 없으면 빈 리스트.

    순서: row_key 오름차순(문자열 비교) — sqlite의 `ORDER BY row_key`와
    FakeRepository의 순회가 같은 순서에 합의하게 하는 것이 이 계약의 일부다.
    삽입 순서에 기대는 구현은 계약을 만족하지 못한다(아래 참조).
    """
    raise NotImplementedError
```

**fake** (`interp.FakeRepository`, drivers.py 문서의 "reference implementation"):
`self.rows.get(entity_id, {})`를 `row_key`로 정렬해 값만 리스트로 돌려준다 —
`[row for _key, row in sorted(table.items())]`. 딕셔너리 삽입 순서에 기대지
않는다: 계약 스위트(아래)가 **삽입 역순으로 시드한 뒤 조회 순서를 단언**하므로,
`dict.values()`를 그대로 쓰면 삽입 순서와 키 순서가 다른 입력에서 sqlite와
불일치한다.

**sqlite** (`SqliteRepositoryDriver`): `SELECT payload FROM lnpl_rows WHERE
entity_id = ? ORDER BY row_key`. sqlite의 기본 TEXT 콜레이션(바이트 비교)이
Python의 문자열 비교와 일치하므로 fake와 결정적으로 합의한다.

**계약 스위트** (`impl/tests/test_driver_contract.py`, D5): 두 드라이버가
공유하는 파라미터화 케이스에 다음을 추가한다:

- 0행: `query`가 빈 리스트를 돌려준다(예외가 아니다).
- 1행: 그 행 하나만 담은 리스트.
- N행, **삽입 역순**으로 시드 후 조회 — 두 드라이버가 같은 순서(row_key 오름차순)로
  합의하는지가 실제로 검증되는 지점이다. 삽입 순서대로만 시드하는 케이스는 순서가
  우연히 일치할 수 있어 이 규칙을 반증하지 못한다.

### 8. spec 다중 행 시드 — 인덱스 폼 (D7)

`impl/lnpl/spec.py`의 `GIVEN_FORMS`에 신규 항목을 더한다:

```python
("stored-indexed", "stored <entity>[<i>] <field> <value>",
 "인덱스 다중 행 시드 — row_key=str(i). 같은 i에 여러 줄을 반복해 필드를 더한다"),
```

**문법 위치**는 기존 `stored` 폼과 같다(`GivenSection`의 `PhraseLine`, 토큰
개수도 4개로 동일 — `stored`, `<entity>[<i>]`, `<field>`, `<value>`). 렉서 변경은
없다: `Line.tokens = body.split()`이 공백으로만 가르므로 `Link[0]`은 이미 토큰
하나다. `impl/lnpl/spec.py`의 `_check_given`이 두 번째 토큰에서 `<entity>[<i>]`
패턴(`re.match(r"^([A-Za-z][A-Za-z0-9]*)\[(\d+)\]$", token)`)을 먼저 시도하고,
일치하지 않으면 기존 `stored` 처리로 떨어진다 — 기존 `stored <entity> <field>
<value>` 폼의 파싱·의미는 이 RFC가 손대지 않는다(후방 호환).

**의미**: `row_key = str(i)`. 같은 `i`에 여러 `given` 줄이 있으면 그 인덱스의
행에 필드가 누적된다(같은 `stored`가 서로 다른 필드에 여러 줄 쓰이는 기존 규칙과
같다). `i`가 다르면 별개 행이다. 결과 시드는 `repository.py`가 이미 쓰는
`{entity_id: {row_key: row}}` 모양 그대로 조립되므로, 런너(`_payload_from_given`이
호출하는 시드 조립부)와 드라이버(§7의 `execute`/`seed`) 어느 쪽도 새 개념을
배우지 않는다 — `str(i)`가 그냥 하나의 `row_key`다.

**`empty repository`와의 상호작용**: 기존 규칙 그대로 — `stored`(인덱스 폼 포함)와
`empty repository`를 같은 spec에 함께 쓰면 `_validate_given`이 거부한다.

### 9. spec 집계 단언 — 새 어휘 없음 (D8)

집계 결과는 `set`이 이미 출력 필드에 쓰므로, 기존 `expect result <Reference> <op>
<value>`(RFC-0012 §G12.7)가 그대로 단언한다:

```
expect
    result report.totalClicks == 8
```

행 수는 기존 `expect rows <Entity> <N>`이 그대로 잰다(RowSet이 아니라 실행 후
저장소 상태를 보는 것이므로 별개 관측이다 — `list`가 몇 행을 봤는지가 아니라
`Link` 테이블에 몇 행이 있는지). 이 RFC는 `expect` 어휘를 추가하지 않는다.

### 10. 모드 B — 관측 클래스는 그대로, 실패 예측만 좁힌다 (D9)

RFC-0015 §Alternatives가 적은 세 조건("집합 타입, 질의 동사, 모드 B의 루프") 중
마지막을 여기서 채운다. 다만 "루프"도 "특수화"도 아니다 — **아무것도 새로 계산하지
않는다.** `_render_std`(mode B의 실제 방출부)를 읽으면 이유가 드러난다: `Assignment`
효과는 `%r<i> = func.call @lnpl_step(...)`와 그 효과 kind를 가리키는 포인터
(`llvm.mlir.addressof`)만 낸다 — 산술이든 대입이든, 계산된 **값**을 SSA로 들고 있지
않는다. RFC-0015 §5(Differential Equivalence)가 이미 이렇게 적어 둔 그대로다:

> 할당이 만든 **값** | **허용된 차이.** 모드 B는 저장소를 모형화하지 않는다

즉 `sum`/`count`가 계산하는 정수는 RFC-0004의 네 관측 클래스(실행 순서+skips,
정책 결과, 관측 신호=effect kind, 마스킹) 중 **어느 것도 아니다** — RFC-0015의
산술 할당(`product.stock - input.quantity`)이 오늘도 mode B에서 상수로 접히지
않는 것과 정확히 같은 이유로, 집계도 접을 필요가 없다. §Alternatives의 기각안 6
("모드 B가 RowSet을 런타임 파라미터로 받는다")이 다시 세우려던 결정(RFC-0012
§G12.6, 저장소 상태를 실행 시점에 정하지 않는다)은 처음부터 위협받지 않았다 —
**빌드 시점 특수화조차 필요 없었다.**

**그러면 D9가 실제로 채우는 것은 무엇인가.** mode B가 값을 계산하지 않아도, 스텝이
**실패하는지**는 예측한다(`_lnpl_ops`의 정적 fail_at 스캔, mode A의 런타임 실패를
문서만으로 미리 판정) — 그리고 그 스캔은 §Motivation의 죽은 경로와 **같은 결함
계열**을 갖고 있었다: `elif kind == "RepositoryCall" and operation in READ_OPS:
if node["entity"] not in seeded_now ...: fail_at = index`. `READ_OPS`(`read`+
`query`)를 쓰면 `list`가 도달하는 순간 이 판정이 `query`를 `read`와 똑같이
취급한다 — "행을 못 찾으면 실패"라는, `read`에게만 맞는 규칙을 `list`에도
적용해서, **시드되지 않은 엔티티를 `list`하기만 해도 mode B가 실패를 예측**하게
된다. mode A는 빈 RowSet을 정상 결과(0행, §5)로 바인딩하지 실패하지 않으므로,
이것은 `--no-row`가 아닌 모든 0행 `list` 워크플로에서 mode A/B가 갈라지는
진짜 결함이다 — RFC-0025 이전에는 `query`가 죽은 경로였으므로 결코 관측되지
않았을 뿐이다(§Motivation과 같은 패턴, 세 번째 자리).

**고치는 것은 그 한 줄이다**: `operation in READ_OPS`를 `operation == "read"`로
좁힌다 — G12.5 ⓒ(§6.2)·`read_entities`(§5)·`READ_VERBS`(§1)·
`repo_policy.seeded_entities`(§5, 아래)에서 이미 낸 것과 같은 판정이다. 같은
파일 안에 `READ_OPS`를 쓰는 자리가 하나 더 있다(재시도 비용 계산, 실패한 효과가
`read`일 때만 `_READ_MISS_COST_MS`를 더한다) — 그 자리도 같은 이유로 좁힌다:
이 수정 이후 `query`는 결코 fail_at이 될 수 없으므로 `in READ_OPS`와 `== "read"`는
그 지점에서 동치이지만, 다음에 이 코드를 읽는 사람이 `READ_OPS`를 보고 "query도
여기 걸리는가"를 다시 묻지 않도록 명시적으로 좁혀 둔다.

**`repo_policy.seeded_entities`도 같은 수정이 필요했다** — mode A/B 양쪽이 이
함수 하나를 공유하므로(모듈 docstring: "mode A(interp.py)와 mode B(backend.py,
Wave 2)가 그것을 같은 입력에서 계산"), 이 함수를 고치면 두 모드가 같이 고쳐진다.
고치기 전에는 `default_rows`(mode A의 CLI/spec 기본 시드)가 `list`-only
엔티티에도 자동으로 행 하나(payload의 사본)를 심었다 — 그 행은 집계가 참조하는
필드를 가질 이유가 없으므로(payload가 그 필드를 안다는 보장이 없다), 0행
경계 스펙 케이스가 조용히 1행을 보거나, 진짜 집계가 "필드가 없다" 런타임
오류로 죽었을 것이다. §5의 결정 그대로: `operation == "read"`만 시드 대상이다.

**`differential._check_seed_agreement`도 한 곳을 좁힌다** — 이 검사는 mode A의
`repo_rows`가 채운 엔티티 집합과 mode B의 `seeded` 집합이 일치하는지 재는데,
`query`로만 도달하는 엔티티는 이 일치 검사에서 뺀다. `seeded`는 mode B의
"이 엔티티가 행 하나로 시작하는가"라는 불리언 조건이고, 그 불리언이 실제로
쓰이는 곳은 `read`(못 찾으면 실패)와 `create`(충돌하면 실패)뿐이다 — `list`는
그 불리언에 대해 결코 의견이 없다(빈 RowSet은 실패가 아니고, 값은 위에서
적었듯 애초에 비교 대상이 아니다). 빼지 않으면 D7의 인덱스 시드로 `Link`를
채운 mode A 입력이, `list`만 있고 `read`는 없는 mode B의 `seeded`(정당하게
`Link`를 언급하지 않는)와 "불일치"로 거부된다 — 배선 실수가 아닌데 배선 실수로
보고하는 것이므로, 이 함수 자신의 존재 이유(§Motivation 인용: "두 입력이
갈라지면 그것이 실제 불일치인지 배선 실수인지")를 어기는 오탐이다.

**동치는 이 네 지점의 수정만으로 증명된다.** `differential.verify`는 그 이상
바뀌지 않는다 — 새 매개변수도, `observe_mode_b`로의 새 배선도 없다. 검증은
0행 입력과 N행 입력 **둘 다**로 한다(§Examples): 대칭 입력(둘 다 같은 고정
N, 또는 둘 다 0)만으로는 "fail_at 판정이 row 존재 여부와 무관해졌다"를
증명하지 못한다 — 정확히 이 버그가 0행에서만 갈라지고 N행에서는 (fail_at
판정이 도달하기 전에 다른 경로로) 우연히 맞아떨어질 수 있는 종류이기
때문이다. 두 입력 모두에서 `differential.verify`가 `ok=True`를 내는 것이
검증 기준이다.

## Examples

### 골든 시나리오 "Login" (RFC-0007 §6)

`Login` 워크플로(`validate input` → `authenticate` → `generate token` →
`audit login` → `return token`)는 이 RFC가 다루는 기능을 쓰지 않는다 —
`list`도 집계도 없다. RFC-0007 §6이 요구하는 대로 정본을 참조만 하고 재정의하지
않는다. 골든 자체는 바뀌지 않는다(`examples/login.lir.json` 불변).

### 골든 인접 예제 — 클릭 합계 (RFC-0007 §6, 골든이 다루지 않는 기능)

```
capability postgres

entity Link
    field
        id UUID
        clicks Integer

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
    list link
    set report.totalClicks to sum link.clicks
    set report.linkCount to count link
    update report
    spec
        given
            stored Report id 1
            stored Link[0] clicks 5
            stored Link[1] clicks 3
        when
            summarizeClicks
        expect
            completed
            result report.totalClicks == 8
            result report.linkCount == 2
```

**0행 경계** — 같은 워크플로, `Link` 시드 없이:

```
        given
            stored Report id 1
        when
            summarizeClicks
        expect
            completed
            result report.totalClicks == 0
            result report.linkCount == 0
```

정본 픽스처는 이 RFC가 만들지 않는다 — Task order §04(spec 시드)·§06(모드 B)이
`impl/tests/lnpl_fixtures/`(정상)와 `impl/tests/`(0행 경계, mode A/B 동치)에
추가한다. RFC-0023이 `guard_orphan_fail.lnpl`/`guard_orphan_pass.lnpl`을 이렇게
남긴 것과 같은 순서다 — 문서가 계약을 고정하고, 구현이 그 계약을 채우는 파일을
가져온다.

### `list` 없는 집계 — 경고 (§4)

```
workflow BadSummary
    find report
    set report.totalClicks to sum link.clicks
```

→ `aggregation-orphaned-list` 1건. `link`가 어느 `list`로도 이 워크플로에서
바인딩되지 않으므로, `report.totalClicks`는 언제나 0이 된다 — 저자가 의도하지
않았을 값이다.

### 정적 거부 — Money 필드 집계

```
entity Payment
    field
        id UUID
        amount Money

workflow BadTotal
    list payment
    set report.total to sum payment.amount
```

`amount`가 Money이므로 §3의 표대로 컴파일 거부 — RFC-0015 §3의 "평가기가 없다"와
같은 사유.

## Alternatives

| # | 검토한 대안 | 기각 사유 |
|---|------------|----------|
| 1 (D4) | **필터·정렬·페이지네이션을 이번 RFC에 함께 넣는다** | 페이지네이션은 커서·한계의 계약 설계가 별도로 필요하다(위키 backend/common/api-design/pagination-contract) — 그 결정 자체가 이 RFC의 범위와 무관한 별개 작업이다. 필터·정렬도 마찬가지로 `Condition` 문법을 `list` 대상에 어떻게 적용할지(단일 행 조건과 같은 문법을 쓸지, WHERE 절에 해당하는 새 생산 규칙을 만들지)가 미결이라 함께 결정하면 이 RFC가 두 개의 독립적 설계 질문을 한 번에 지려 한다. 이슈 #65의 DoD도 요구하지 않는다. §Open Questions로 이월 |
| 2 | **RowSet과 단일 행 바인딩에 별도 이름을 강제한다**(예: `list link as links`) | 새 바인딩 문법(`as` 절)이 필요하고, `VERB_LEXICON`의 다른 어떤 동사도 별칭을 갖지 않는다 — 이 RFC 하나를 위해 새 표기 계열을 여는 것은 비용 대비 이득이 없다. 문법 위치로 이미 충돌 없이 가르는 것(§5)이 새 표기 없이 같은 문제를 푼다 |
| 3 | **`query` 대신 새 operation 문자열을 쓴다**(예: `"list"`) | §Motivation이 적은 죽은 경로 재사용의 이점을 버린다 — `IDEMPOTENT_OPS`·`READ_OPS`·스키마 enum 세 곳이 이미 `"query"`를 알고 있고, 새 문자열은 그 세 곳을 다시 건드리면서 아무것도 더 얻지 못한다 |
| 4 | **RowSet도 단일 행처럼 `<entity>.<field>` 참조를 허용하고 첫 행만 돌려준다** | 조용한 축소다 — 저자가 "전 행의 필드"를 물었는데 "첫 행의 필드"를 받으면 오류가 나지 않고 틀린 답을 낸다. RFC-0012 §G12.3이 세운 "형태가 가른다, 우선순위가 아니라"는 원칙과도 맞지 않는다 — 두 문법 위치가 다른 것을 가리키는 것이 명시적이어야 한다 |
| 5 (§4) | **`list` 없는 집계를 경고가 아니라 컴파일 에러로 낸다** | RFC-0021의 사다리를 따른다 — "프로그램을 고치면 사라지는가"에 그렇다고 답하는 진단은 `warning`이지 `error`가 아니다. `error`는 오늘 예약이며(RFC-0021), 이 RFC가 처음 쓸 이유가 없다. 저자가 정말로 빈 RowSet에서 0을 의도했을 수도 있다(예: 리포트 초기화 워크플로) — 그것을 막을 근거가 없다 |
| 6 (D9) | **모드 B가 집계 값을 계산한다**(런타임 파라미터로 받든, 빌드 시점에 `repo_rows`에서 상수로 접든) | §10에서 실제로 확인한 사실이 이 대안 자체를 불필요하게 만든다 — `_render_std`는 `Assignment`가 계산하는 값을 애초에 SSA로 들고 있지 않고, RFC-0015 §5가 이미 "할당이 만든 값은 허용된 차이"라고 적어 두었다. RFC-0012 §G12.6이 저장소 상태를 실행 시점에 분기하지 못하게 막은 것과 같은 방향의 판단이지만, 여기서는 그 판단을 시험할 필요조차 없다 — 계산할 값이 mode B의 비교 대상에 아예 들어있지 않기 때문이다. RowSet 하나를 위해 값 모델링을 새로 여는 것은 세우지도 않은 요구를 충족시키는 일이다 |

## Open Questions

1. **필터·정렬·페이지네이션.** D4가 이월한 것 그대로. `list`가 `Condition` 문법을
   빌려 쓸지, 페이지네이션이 커서 기반일지 오프셋 기반일지는 후속 이슈가 결정한다.
2. **집계와 산술의 결합.** `sum link.clicks + input.adjustment`처럼 집계 결과를
   RFC-0015의 산술과 잇는 표기는 이 RFC가 도입하지 않는다(§Guide-level
   Explanation이 명시적으로 배제). 필요해지면 `Aggregate`를 `Operand`의 대안으로
   승격하는 문법 개정이 별도로 필요하다.
3. **`min`/`max`/`avg`.** 이슈 #65는 `sum`/`count`만 요구한다. 셋 다 mode B가
   값을 전혀 모델링하지 않는 같은 지형(§10) 위에서 자연스럽게 확장되지만,
   요구되지 않은 표면을 먼저 여는 것은 이 RFC의 범위가 아니다.
4. **RowSet 크기 상한.** 지금은 없다 — `list`는 전 행을 메모리에 올린다
   (모드 A는 파이썬 리스트; 모드 B는 값을 계산하지 않으므로 이 질문이 아예
   발생하지 않는다, §10). 저장소가 커지면 모드 A 쪽 가정이 깨지지만, 그
   시점은 페이지네이션(공개 질문 1)이 함께 해결할 문제다.

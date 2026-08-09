# RFC-0020: spec `given`의 입력 네임스페이스

## Status

- Status: Accepted

## Motivation

RFC-0015 §G15.2는 입력 네임스페이스를 **선언된 전 엔티티 필드의 합집합**으로
정의한다. 실행 경로는 전부 그 정의를 따른다 — `lnpl run`, `lnpl diff`, mode B의
호스트가 모두 전 엔티티에서 payload를 만든다. **`spec` 러너만 그러지 않았다.**
`given`의 필드 형식은 문서의 **첫** 엔티티 필드로만 이름을 풀었고, 기본 payload도
그 한 엔티티에서만 왔다.

2026-08-07 재측정(`qa/rerun/REPORT.md` §6.2)은 그 한 좁힘을 세 갈래로 관측했고,
셋은 서로 다른 사건으로 기록됐다:

| 관측 | 등급 | 증상 |
|------|------|------|
| r1 N-4 | major | `given quantity 2`가 거부 — `quantity`가 둘째 엔티티 필드라서. 입력 경계 spec(qty=0)이 언어 밖으로 밀렸다 |
| r2 N-2 | major | read-행 참조 가드를 참으로 만들 수 없음 — 가드의 다른 항 `input.requestedAt`이 payload에 없고 넣을 수단도 없었다 |
| r4 F-6 | minor | `no priorNotification` 거부 — 같은 이유. 그리고 `no`의 스코프가 문서에 없었다 |

r2 N-2는 `stored`(RFC 없음, issue #39)의 결함으로 읽히기 쉬웠다. 실측은 아니라고
답했다: 케이스를 러너 안에서 열면 `stored`가 지정한 행 값 셋은 **정확히 반영돼
있었고**, payload에 `requestedAt` 하나를 넣자 같은 모듈이 `steps 1`에서 `steps 2`로
바뀌었다. 막힌 축은 저장 행이 아니라 입력이었다.

넷째 관측(r1 F-8)은 시점 문제다. `extract()`는 `given` 토큰을 문자열로 잇기만 했고,
`run_manifest`가 그것을 처음 해석하는 단계였다. 그래서 `--run` 없이 `lnpl spec`을
돌리면 **실행 불가능한 케이스로 가득한 매니페스트가 조용히 쓰였다.**

## Guide-level Explanation

`spec` 블록의 `given`은 입력 payload를 `input.<field>`로 지목한다 — 가드에서 쓰는
바로 그 철자다(RFC-0015 §G15.2).

```
workflow RefundRequest
    read payment
    when input.requestedAt - payment.createdAt <= 30d
    create refund
    spec
        given
            stored payment createdAt 2026-07-31T09:00:00Z
            input.requestedAt 2026-08-01T09:00:00Z
        when
            refund request
        expect
            completed
            steps 2
```

`stored`가 읽힐 행을 깔고, `input.`이 그 행과 비교될 입력을 깐다. 둘이 갖춰져야
read-행 참조 가드의 **정상 경로**가 spec 안에서 실행된다 — 이전에는 이 조합을
표현할 수 없어서 가드-참 경로의 계약이 실행 증적(run/build)으로 밀려나 있었다.

맨이름(`requestedAt`)도 같은 것을 가리킨다. RFC-0015가 가드에서 그렇게 정한 것을
`given`도 따를 뿐이다. 새로 쓰는 spec은 `input.`을 쓴다 — 어느 네임스페이스를
말하는지가 철자에 남는다.

이름이 어느 엔티티에도 없으면 거부된다. 그 거부는 이제 `--run`을 기다리지 않는다:

```
$ lnpl spec inventory-order.lnpl
compile error: workflow PlaceOrder: spec block 1: given 'input.nosuch 5' names
input field 'nosuch', which no declared entity has. The input payload is the union
of every declared entity's fields (RFC-0015 §G15.2). Declared: id, name, placedAt,
price, quantity, status, stock
```

## Reference-level Specification

### 1. 어휘

`given`이 받는 형식은 닫힌 집합이며, 정본은 `impl/lnpl/spec.py`의 `GIVEN_FORMS`
테이블 하나다. 생성 레퍼런스(`references/spec.md`)와 두 검사 단계가 모두 그 테이블을
읽는다 — 문서가 구현 옆에서 따로 유지되지 않는다.

| 형식 | 의미 |
|------|------|
| `valid <아무 명사>` | 서사용 표지. 필드에 영향 없음 |
| `empty repository` | 빈 저장소로 실행. `stored`와 상호 배타 |
| `input.<field> <value>` | 입력 payload 필드를 설정 |
| `no input.<field>` | 입력 payload에서 필드를 뺌 |
| `<field> <value>` | `input.<field> <value>`와 동일 |
| `no <field>` | `no input.<field>`와 동일 |
| `stored <entity> <field> <value>` | 사전 저장소 상태 |

### 2. 이름 해석

- 필드 형식(위 3~6행)의 이름은 **선언된 전 엔티티 필드의 합집합**에서 찾는다.
  합집합에 없는 이름은 거부하며, 진단은 수용되는 이름 전체를 댄다.
- 한 이름을 둘 이상의 엔티티가 선언하면, 값의 타입은 **뒤에 선언된 엔티티**의
  것으로 코어션한다. `interp.sample_payload`가 같은 충돌을 그 순서로 푼다 —
  spec 러너는 `lnpl run`이 같은 모듈에 대해 만들었을 payload를 만들어야 한다.
- `stored`의 엔티티는 선언명(`Payment`)과 바인딩명(`payment`) 둘 다 받는다
  (issue #46).

### 3. 기본 payload의 범위 (합집합이 **아니다**)

기본 payload는 첫 엔티티와 `validate`가 지목한 엔티티의 필드만 샘플로 채운다.
issue #48이 그 범위를 의도적으로 고정했다 — 전 엔티티를 채우면 다른 엔티티의 부재
필드를 읽는 Presence 가드(`when <field> missing`)가 뒤집힌다.

따라서 **해석 네임스페이스(합집합)와 기본 payload(부분집합)는 다르다.** 그 차이가
`input.<field>`가 존재하는 이유다: 기본 범위 밖의 입력 필드는 명시해야 들어간다.

### 4. `no`의 스코프

1. 입력 payload에서 그 필드를 뺀다.
2. 기본 시드 행은 그 payload의 복사본이므로(`repo_policy.default_rows`), 그 행에서도
   사라진다.
3. `stored`는 시드 이후에 적용되므로 `no`보다 뒤에 온다 — 같이 쓰면 `stored`가 이긴다.
4. 이미 없는 필드를 빼는 것은 **부재를 단언하는 no-op**이며 에러가 아니다. Presence
   가드가 계약하는 상태가 그것이다.

### 5. 검사 시점

`given`의 형식과 이름은 **매니페스트 단계**(`extract()`)에서 검사한다. `--run` 여부와
무관하게 거부되며, 진단은 워크플로 이름과 블록 번호를 함께 댄다.

타입과 코어션은 검사하지 않는다 — `extract()`는 `decls`만 보고, refinement 인덱스는
lower 이후에만 존재한다. 그 둘은 러너가 본다. 두 단계는 하나의 분류기를 공유하므로,
한쪽이 받는 줄은 다른 쪽도 받는다.

## Examples

골든 시나리오 "Login"(정본: `plans/rfc-suite/plan.md` §골든 시나리오 "Login" —
참조만 한다). Login은 엔티티가 하나이므로 합집합과 첫 엔티티가 일치하고, 이 RFC
이전과 이후의 동작이 같다 — 회귀 없음의 기준선이다.

```
workflow Login
    validate input
    authenticate
    cache user
    spec
        given
            input.email user@example.com
        when
            login
        expect
            completed
            steps 3
```

골든이 다루지 않는 것은 **다중 엔티티와 read-행 참조 가드**다. §6이 허용하는 골든
인접 예제로 r2 N-2를 그대로 쓴다.

**이전 — 가드-참 경로를 표현할 수 없다.** `requestedAt`은 둘째 엔티티(`Refund`)의
필드라서 `given`으로 넣을 수 없고, 기본 payload에도 없다:

가드는 `input.requestedAt - payment.createdAt <= 30d and input.amountCents <=
payment.amountCents`이다.

```
spec
    given
        stored payment id 3f2504e0-4f89-41d3-9a0c-0305e82c3301
        stored payment amountCents 5
        stored payment createdAt 2026-07-31T09:00:00Z
        amountCents 3
    when
        refund request
    expect
        completed
        steps 2
```

```
FAIL RefundRequest spec 1 — steps 2 (steps=1 want=2)
spec: 10 passed, 1 failed
```

`stored` 세 줄은 반영돼 있었다. 빠진 것은 가드 좌항의 `input.requestedAt`이고,
`requestedAt`은 둘째 엔티티 필드라 `given`으로 넣을 수단이 없었다.

**이후 — 같은 블록에 입력 축을 명시한다:**

```
spec
    given
        stored payment id 3f2504e0-4f89-41d3-9a0c-0305e82c3301
        stored payment amountCents 5
        stored payment createdAt 2026-07-31T09:00:00Z
        input.amountCents 3
        input.requestedAt 2026-08-01T09:00:00Z
    when
        refund request
    expect
        completed
        steps 2
```

```
PASS RefundRequest spec 1 — steps 2 (steps=2 want=2)
spec: 11 passed, 0 failed
```

가드-거짓 방향은 같은 블록에서 날짜만 창 밖으로 옮겨 얻는다(`steps 1`). 두 방향을
모두 돌려야 가드가 계약된다 — 스킵한 실행의 exit 0은 스킵 경로에 대한 증거일 뿐이다.

## Alternatives

**`stored`를 확장해 입력까지 시드한다.** 처음의 유력 후보였다. 실측이 기각했다:
`stored`는 이미 지정한 행 값을 정확히 반영하고 있었고, r2 N-2에서 빠져 있던 것은
행이 아니라 입력이었다. `stored`에 입력 축을 얹으면 한 형식이 저장소와 입력 둘을
가리키게 되어, 두 축이 다른 값을 가져야 하는 케이스(issue #37이 여는 바로 그 케이스)를
다시 표현 불가로 만든다.

**맨이름만 유지하고 `input.`을 도입하지 않는다.** 맨이름의 도메인만 합집합으로
넓히면 세 증상은 닫힌다. 기각한 이유는 관측 가능성이다 — 이름 기반 주입에서 맨이름과
정규화된 점 표기가 갈릴 때, 맨이름은 "비교하지 않는 필드" 쪽으로 조용히 떨어진다.
이 플랫폼에서 이미 관측된 실패다(`--field value=N` 5회가 동일 출력, `measurement.value`로
바꾸자 가드가 뒤집힘). 정본 철자를 문법에 남기는 쪽을 택했다. 맨이름은 RFC-0015가
가드에서 유지하므로 여기서도 동의어로 유지한다.

**기본 payload를 합집합으로 넓힌다.** `lnpl run`과 완전히 일치시키는 가장 단순한 안이고,
기각 사유는 issue #48이다 — 전 엔티티를 채우면 Presence 가드가 뒤집혀 이미 계약된
시나리오(r4의 `priorNotification missing`)가 깨진다. 표현력만 넓히고 러너의 기본
의미는 건드리지 않는다.

**진단을 컴파일 단계(`lower`)로 올린다.** `spec`은 IR 노드가 아니므로(RFC-0002 A.4-2)
lower가 그것을 보지 않는다. 매니페스트 단계가 `given`을 아는 첫 단계다.

## Open Questions

- **기본 payload와 `lnpl run`의 payload는 여전히 다르다.** §3의 부분집합과 실행 경로의
  합집합이 갈린 채로 남는다. 같은 모듈·같은 given이 두 채널에서 다른 Presence 가드
  결과를 낼 수 있다는 뜻이다. 이 RFC는 그것을 닫지 않는다 — 닫으려면 issue #48이 고정한
  Presence 계약을 먼저 개정해야 한다.
- **`expect` 키에는 같은 조기 거부가 없다.** 인식되지 않는 expectation은 여전히
  `run_manifest`의 FAIL 줄로만 나타난다. `given`과 같은 계보의 갭이지만 이 RFC의
  범위 밖이다.
- 다중 엔티티에서 **동명 필드**를 서로 다른 값으로 주는 실행은 `input.`으로도 만들 수
  없다(payload가 평평하다 — r2 N-1). 네임스페이스 평면성은 별도 문제다.

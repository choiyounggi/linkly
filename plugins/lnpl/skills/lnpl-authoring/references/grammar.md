<!-- 생성물 — 손으로 고치지 마라. 정본은 impl/lnpl/의 모듈 상수이고, 이 파일은 `python scripts/gen_plugin_references.py`의 출력이다. 고치면 impl/tests/test_plugin_references.py가 실패한다. -->

# 문법 — 키워드와 예약어

> lnpl 0.4.0 기준.

LNPL은 닫힌 키워드 집합을 쓴다. 아래에 없는 키워드는 문법이 아니다.

## 최상위 선언

`entity` `service` `workflow` `event` `capability` `refine`

## 절(clause)

`field` `goal` `policy` `security` `performance` `database` `spec` `given` `when` `expect`

## 제어 어휘

`when` `repeat` `parallel` `until` `pipeline` `merge`

## 예약어 — 사용 불가

`if` `for` `while` `switch`

이 넷은 **문법적으로 표현 불가능**하다. 쓰면 렉서가 거부한다. 분기가 필요하면 `when`, 반복이 필요하면 `repeat`/`until`을 쓴다.

## 리터럴

기간 단위: `ms` `s` `m` `h` `d`

비교 연산자: `<=` `>=` `==` `!=` `<` `>`

## 값 표현식 (RFC-0015)

산술 연산자: `+` `-`

논리 결합: `and` — `or`·`not`·괄호는 없다.

할당: `set` `to` (`set <바인딩>.<필드> to <값>`)

입력 네임스페이스: `input` (`input.quantity` — 실행 payload의 필드)

가드 조건은 `<값> <비교연산자> <값>`이고 항은 `and`로만 잇는다. 값은 참조·정수·기간이며 이항 산술 **1개**까지 붙일 수 있다(`product.stock - input.quantity`). 중첩·괄호는 문법에 없다.

## 할당(`set`)의 대상

`set <바인딩>.<필드> to <값>`의 바인딩은 이 워크플로가 **읽은** 행이다. 스텝이 엔티티를 읽으면 그 행이 실행 스코프에 바인딩되고(RFC-0012), `set`은 그렇게 생긴 바인딩에만 쓴다.

읽기 동사: `authenticate` `load` `find` `read` — 이 동사들만 바인딩을 만든다.

바인딩을 만들지 않는 동사: `create` `insert` `update` `delete` — 만든 행은 실행 스코프에 들어오지 않는다.

그래서 `create report` 다음의 `set report.total to 1`은 거부된다.

`input.<필드>`는 할당의 **대상이 될 수 없다** — 입력은 이 워크플로가 소유한 상태가 아니다. 값 쪽에는 쓸 수 있다(`set product.stock to product.stock - input.quantity`).

고치는 법: 쓰기 전에 그 엔티티를 `authenticate` / `load` / `find` / `read` 중 하나로 먼저 읽는다. 읽을 수 없는 엔티티라면 그 값은 이 워크플로가 바꿀 수 있는 상태가 아니다.

## 가드의 스코프

가드는 **바로 다음 항목 하나**를 소유한다. 그 항목은 스텝 한 줄이거나 `parallel`/`pipeline` 블록 하나다. 뒤따르는 블록 전체를 감싸지 **않는다** — 가드 다음 스텝 하나만 조건 아래 들어간다.

```
when product.stock > 0
create order          # 가드 안
update product        # 가드 밖 — 조건과 무관하게 늘 실행된다
```

두 스텝을 함께 감싸려면 둘 중 하나를 쓴다:

```
when product.stock > 0    # ① 가드 줄을 스텝마다 반복한다
create order
when product.stock > 0
update product
```
```
when product.stock > 0    # ② 블록으로 묶으면 블록 전체가 가드 안이다
parallel
create order
update product
merge
```

가드를 두 줄 잇달아 쓰면 **파싱 에러**다 — 조건 두 개는 `and`로 이어 한 가드로 쓴다. 선언이 가드로 끝나도(감쌀 항목이 없어도) 에러다.

가드 조건이 참조하는 필드는 **Integer 또는 DateTime**이어야 한다 — 존재 검사(`exists`/`missing`)도 마찬가지다. `Text`·`Money` 필드에 가드를 걸면 lowering이 거부한다(RFC-0016).


## 블록의 시작과 종결

블록은 들여쓰기가 아니라 **키워드**로 끝난다(RFC-0002 §Block structure). 다만 두 블록의 종결 방식이 서로 다르다.

`parallel`은 `merge`로 닫는다. 닫지 않은 채 선언이 끝나면 거부된다:

```
declaration Checkout ends with an unclosed `parallel` block (missing `merge`)
```

`pipeline`은 `merge`로 닫지 않는다 — 다음 제어 키워드가 나오거나 선언이 끝나는 자리에서 저절로 닫힌다. 사이에 낀 스텝들은 그 `pipeline` 안이다.

암묵 종결: `when` `repeat` `parallel` `until` `pipeline`

그래서 `pipeline` 뒤에 `merge`를 쓰면 닫을 `parallel`이 없어 거부된다 — 이 문면이 나오면 블록을 잘못 닫은 것이다:

```
`merge` closes a `parallel` block, but none is open
```

이름: `pipeline`은 이름을 하나까지 받고(`pipeline enrich`), `parallel`은 이름을 받지 않는다.

중첩: 깊이는 2까지다 — `parallel` 안에는 다른 블록도, 가드도 들어갈 수 없다(가드를 쓰려면 `merge`로 먼저 닫는다).

```
pipeline
find order
when order.total > 0    <- 여기서 pipeline이 닫힌다
create order            <- 가드가 소유하는 스텝
```
## 이벤트 소스 (RFC-0016)

`event <이름>`은 소스를 붙일 수 있다. 두 형태뿐이다:

- `on <Entity> create|update|delete`
- `on schedule <주기> at <HH:MM> <존>` — 주기: `daily` / 존: `UTC`

예: `event DailyRollup on schedule daily at 00:00 UTC`

스케줄 트리거는 **집행되지 않는다** — IR과 OpenAPI의 `x-lnpl-schedules`까지만 도달하고 실행기는 없다. 선언하면 `declared-not-enforced` 진단이 나온다(집행 매트릭스 참조).

들여쓰기는 의미가 없다(4칸은 스타일 규약일 뿐). 블록은 키워드로 구분된다 — 그래서 괄호 짝이나 들여쓰기 오류가 문법적으로 표현되지 않는다.

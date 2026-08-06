<!-- 생성물 — 손으로 고치지 마라. 정본은 impl/lnpl/의 모듈 상수이고, 이 파일은 `python scripts/gen_plugin_references.py`의 출력이다. 고치면 impl/tests/test_plugin_references.py가 실패한다. -->

# 문법 — 키워드와 예약어

> lnpl 0.2.0 기준.

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

## 이벤트 소스 (RFC-0016)

`event <이름>`은 소스를 붙일 수 있다. 두 형태뿐이다:

- `on <Entity> create|update|delete`
- `on schedule <주기> at <HH:MM> <존>` — 주기: `daily` / 존: `UTC`

예: `event DailyRollup on schedule daily at 00:00 UTC`

스케줄 트리거는 **집행되지 않는다** — IR과 OpenAPI의 `x-lnpl-schedules`까지만 도달하고 실행기는 없다. 선언하면 `declared-not-enforced` 진단이 나온다(집행 매트릭스 참조).

들여쓰기는 의미가 없다(4칸은 스타일 규약일 뿐). 블록은 키워드로 구분된다 — 그래서 괄호 짝이나 들여쓰기 오류가 문법적으로 표현되지 않는다.

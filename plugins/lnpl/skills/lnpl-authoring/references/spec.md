<!-- 생성물 — 손으로 고치지 마라. 정본은 impl/lnpl/의 모듈 상수이고, 이 파일은 `python scripts/gen_plugin_references.py`의 출력이다. 고치면 impl/tests/test_plugin_references.py가 실패한다. -->

# spec 블록

> lnpl 0.3.0 기준.

워크플로 안의 `spec` 블록은 `given` / `when` / `expect` 세 절을 갖는다.
워크플로당 블록 여러 개를 선언할 수 있고 블록마다 독립 케이스 하나가 된다 —
정상/에러/경계 시나리오는 블록을 나눠 쓴다. 한 블록 안에서 같은 절을 두 번
열면 파싱 에러다 (issue #46).

## `expect`가 받는 키

- `completed`
- `failed`
- `steps`
- `slo`
- `duration`
- `cache`
- `attempts`
- `result`
- `rows`
- `emitted`
- `error`
- `effects`

## `given`이 알아듣는 형식

- `valid <아무 명사>` — 서사용 표지 — 필드에 영향 없음
- `empty repository` — 빈 저장소로 실행 — `stored`와 함께 쓸 수 없다
- `input.<field> <value>` — 입력 payload 필드를 설정. 이름은 선언된 전 엔티티 필드의 합집합에서 찾는다 (RFC-0015 §G15.2). Integer 계열은 int로 코어션된다
- `no input.<field>` — 입력 payload에서 그 필드를 뺀다
- `<field> <value>` — `input.<field> <value>`와 같다 — 맨이름도 입력 payload를 가리킨다
- `no <field>` — `no input.<field>`와 같다
- `stored <entity> <field> <value>` — 사전 저장소 상태 (issue #39). 엔티티는 선언명(`Product`)과 바인딩명(`product`) 둘 다 받는다

선언되지 않은 이름을 쓰면 거부된다 — `--run` 없이 `lnpl spec`만 돌려도 매니페스트 단계에서 거부되고, 진단이 어느 워크플로의 어느 블록인지와 수용되는 이름 전체를 댄다 (issue #54).


## 입력 네임스페이스

필드 형식은 **선언된 전 엔티티 필드의 합집합**에서 이름을 찾는다 (RFC-0015 §G15.2). 맨이름과 `input.<field>`는 같은 것을 가리키며, 새로 쓰는 spec은 `input.`을 쓴다.

단, 기본 payload는 그 합집합이 아니다 — 첫 엔티티와 `validate`가 지목한 엔티티의 필드만 샘플로 채운다 (issue #48: 전 엔티티를 채우면 다른 엔티티의 부재 필드를 읽는 Presence 가드가 뒤집힌다). 그래서 그 밖의 입력 필드는 `input.<field> <value>`로 **명시해야** 하고, read-행 참조 가드를 참으로 만드는 정상 경로도 그렇게 계약화한다 (issue #54).


## `given no`의 스코프

- 입력 payload에서 그 필드를 뺀다
- 기본 시드 행은 그 payload의 복사본이므로, 그 행에서도 사라진다
- `stored`는 시드 이후에 덮어쓰므로 `no`보다 뒤에 적용된다 — 둘을 같이 쓰면 `stored`가 이긴다
- 이미 없는 필드를 빼는 것은 부재를 단언하는 no-op이며 에러가 아니다 — `when <field> missing` 같은 Presence 가드가 계약하는 상태다

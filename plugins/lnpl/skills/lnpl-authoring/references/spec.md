<!-- 생성물 — 손으로 고치지 마라. 정본은 impl/lnpl/의 모듈 상수이고, 이 파일은 `python scripts/gen_plugin_references.py`의 출력이다. 고치면 impl/tests/test_plugin_references.py가 실패한다. -->

# spec 블록

> lnpl 0.4.0 기준.

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


## 저장소 시드와 `create` 충돌

`create`는 같은 키의 행이 이미 있으면 실패한다. 행은 엔티티마다 `<entity_id>#<payload의 id 또는 '-'>` 키 아래 사니까, 충돌은 엔티티 단위가 아니라 **(엔티티, 키)** 단위다.

그런데 기본 시드는 이 워크플로가 읽는 엔티티만 채운다. `create`만 하고 읽지 않는 엔티티는 빈 채로 시작하므로 첫 `create`는 늘 삽입된다.

`stored <엔티티> <필드> <값>`은 **이미 시드된 행의 필드를 덮어쓸 뿐**이다. 읽지 않는 엔티티에는 행을 만들지 않고, 그 사실을 알리는 진단도 없다 — 조용히 무시된다.

그래서 "사전 행이 있어서 `create`가 충돌한다"는 시나리오는 `given`으로 **세울 수 없다**. 표현 수단이 없어서가 아니라 시드 규칙이 그 행을 만들지 않기 때문이다.

충돌은 그 키에 **이미 행이 있을 때** 난다. 실행 중에 행이 생기는 경로는 둘이다 — 그래서 관측 가능한 형태도 그 둘이다:

- **시드** — 이 워크플로가 그 엔티티를 읽는다. 읽는 엔티티는 payload의 복사본으로 채워지므로, `find order` 다음의 `create order`는 충돌한다.
- **앞선 `create`** — 같은 실행에서 그 엔티티를 이미 만들었다. `create order`를 두 번 쓰면 두 번째가 충돌한다.

둘 다 같은 실패로 끝나고, 그 실패는 spec으로 계약할 수 있다:

```
expect
    failed
    error reason conflicts
```

그때 run의 `failure_reason`은 이렇게 된다:

```
repository create conflicts: entity.order already exists
```

읽기가 실패하는 에러 경로를 계약하고 싶으면 `empty repository`를 쓴다 — 시드가 없으니 `find`/`load`가 행을 못 찾고 그 스텝이 실패한다.

이 "엔티티당 행 하나" 불변식이 어디서 오는지는 `rfcs/0015-value-semantics.md` §Alternatives에 있다: 한 실행은 payload 하나를 가지므로 엔티티 E의 테이블에는 행이 최대 하나다.

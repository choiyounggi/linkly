<!-- 생성물 — 손으로 고치지 마라. 정본은 impl/lnpl/의 모듈 상수이고, 이 파일은 `python scripts/gen_plugin_references.py`의 출력이다. 고치면 impl/tests/test_plugin_references.py가 실패한다. -->

# spec 블록

> lnpl 0.2.0 기준.

워크플로 안의 `spec` 블록은 `given` / `when` / `expect` 세 절을 갖는다.

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

- `valid <아무 명사>` — 서사용 표지, 필드에 영향 없음
- `empty repository` — 빈 저장소로 실행
- `<field> <value>` — 선언된 필드를 설정
- `no <field>` — 선언된 필드를 뺌
- `stored <entity> <field> <value>` — 사전 저장소 상태 (issue #39)

선언되지 않은 필드를 쓰면 거부된다.

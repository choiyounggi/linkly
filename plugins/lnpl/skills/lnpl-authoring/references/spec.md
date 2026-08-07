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

- `valid <아무 명사>` — 서사용 표지, 필드에 영향 없음
- `empty repository` — 빈 저장소로 실행
- `<field> <value>` — 선언된 필드를 설정. 기본 payload(샘플 값) 위에 필드 단위로 덮어쓰며, Integer 계열 필드는 int로 변환된다 (issue #46)
- `no <field>` — 선언된 필드를 뺌
- `stored <entity> <field> <value>` — 사전 저장소 상태 (issue #39). 엔티티는 선언명(`Product`)과 바인딩명(`product`) 둘 다 받는다 (issue #46)

선언되지 않은 필드를 쓰면 거부된다.

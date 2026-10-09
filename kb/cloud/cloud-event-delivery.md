---
id: cloud-event-delivery
category: Cloud
triggers:
  - outbox·relay 전달 보장
  - 이벤트 전달 보장·중복 수신
  - 멱등 소비자
  - outbox guarantee
  - outbox relay
  - at-least-once
  - idempotent consumer
  - dead-letter
version: 0.1.0
status: draft
sources:
  - rfcs/0040-event-consumption-contract.md
  - docs/backends.md
  - docs/serving.md
  - rfcs/0061-event-publisher-spi.md
---
# event delivery

이벤트는 최소 한 번(at-least-once) 전달된다 — 503이나 응답 없음처럼
확인이 불확실하면 ack하지 않고 다음 드레인이 다시 보낸다(근거:
rfcs/0040-event-consumption-contract.md "8. 레퍼런스 릴레이 — `lnpl
relay` (D8)"). 그래서 중복 수신이 일어날 수 있고, 그것을 흡수하는 것은
CloudEvents `id`를 멱등성 키로 쓰는 소비자 쪽 메커니즘이다(근거:
rfcs/0040-event-consumption-contract.md "6. 멱등성 (D6)").

이렇게 한다:

## 보장 — at-least-once, 소비자는 멱등

- CloudEvents `id`가 멱등성 키다. 이슈 #113의 멱등성 저장소를 그대로
  재사용한다 — `"in-progress"`면 409, `"done"`이면 저장된 응답을
  재생해 워크플로를 다시 돌리지 않는다. 200과 422만 확정(재생)하고,
  503이나 예외 이스케이프는 클레임을 즉시 반납해 다음 재시도가 깨끗하게
  다시 실행되게 한다(근거: rfcs/0040-event-consumption-contract.md
  "6. 멱등성 (D6)").
- `event <E> consume by <Workflow>`는 CloudEvents 구조화 모드 v1.0만
  받고, 같은 `id`로 이미 실행 중이면 409(`idempotency-in-progress`)를
  돌려준다(근거: docs/serving.md "이벤트 소비 (`consume by`, 이슈
  #118)").

## outbox — 발행 쪽

- `--backend sqlite:...`로 실행한 `EventEmit` 효과는 등록되는 순간
  `lnpl_outbox` 테이블에 한 행으로 남는다 — 삭제가 아니라 `delivered_at`
  마킹이다. 행의 정체성은
  `emission_id`가 아니라 저장소가 소유하는 대리키 `seq`다(근거:
  docs/backends.md "아웃박스 — `lnpl_outbox` (이슈 #102)").
- `lnpl outbox drain`은 미전달 행을 `seq` 오름차순으로 낸다. `lnpl outbox
  ack`는 같은 `seq` 재-ack가 멱등이고, 배치 중 모르는 `seq`가 하나라도
  있으면 아무것도 쓰지 않고 거부한다(근거: docs/backends.md "아웃박스 —
  `lnpl_outbox` (이슈 #102)").

## relay의 ack 규칙

- 소비 쪽(`consume by`)의 결과는 3갈래로 분류된다: `completed`는 200,
  `deadline`이나 `RepositoryCall`/`NetworkCall` 효과의 실패는 503 +
  `Retry-After: 1`(`event-retry-later`), 그 외(`conflict`, 검증 거부,
  비즈니스 거부)는 422(`event-rejected`)다(근거:
  rfcs/0040-event-consumption-contract.md "7. 오류 분류 — 3갈래 (D7)").
- `lnpl relay`는 매 드레인 사이클마다 미배달 emission을 CloudEvents
  봉투로 만들어 POST한다: 200이면 ack, 422면 ack + stderr에 dead-letter
  경고, 503이거나 응답이 없으면(연결 실패) ack하지 않고 다음 드레인이
  재시도한다 — D7이 정의하지 않은 네 번째 갈래는 발명하지 않는다(근거:
  rfcs/0040-event-consumption-contract.md "8. 레퍼런스 릴레이 — `lnpl
  relay` (D8)").

## 발행자 SPI

- `lnpl.publishers` entry-points 그룹이 `http`/`https`가 아닌 스킴의
  실제 브로커 발행을 외부 패키지에 연다 — 내장 스킴은 entry-points
  조회보다 먼저 검사돼 절대 가려지지 않는다(근거: docs/backends.md
  "15. SPI: 외부 이벤트 발행자 등록 (issue #191, RFC-0061)").
- 발행 결과는 이미 분류된다: `publish`/`publish_batch`가 예외 없이
  반환되면 ack, `PublishRejected`(영구 거부)면 ack + dead-letter 경고,
  그 외 `DriverError`면 ack하지 않고 다음 드레인이 재시도한다(근거:
  docs/backends.md "등록").
- RFC-0061(Status: Draft)은 이 분류를 발행 쪽의 대칭 표로 다시 적는다 —
  소비 쪽 3갈래(RFC-0040 §7)와 짝을 맞춘 설명이고, 세 번째 갈래는
  발명하지 않는다(근거: rfcs/0061-event-publisher-spi.md "4. 오류 분류
  대칭 — 발행 쪽 (D5)", Status: Draft).

## 집행 등급

- 미구현 — 워크플로 단위 트랜잭션 경계와 outbox emit의 결합 규칙: 실패한
  실행이 emit한 행이 저장소에 남는지는 아직 정해지지 않았다. 위 권고는
  설계 방향의 서술이지 지금 집행되는 제약이 아니다(근거: docs/backends.md
  "아웃박스 — `lnpl_outbox` (이슈 #102)").
- 미구현 — 코어에 실제 브로커(카프카 등) 발행 드라이버가 없다. SPI와
  TCK만 제공되고 실 바인딩은 외부 패키지의 몫이다. 위 권고는 설계
  방향의 서술이지 지금 집행되는 제약이 아니다(근거: docs/backends.md
  "15. SPI: 외부 이벤트 발행자 등록 (issue #191, RFC-0061)").
- 구현됨 — sqlite 백엔드에서의 outbox 테이블과 drain/ack(근거:
  docs/backends.md "아웃박스 — `lnpl_outbox` (이슈 #102)").
- 구현됨 — 레퍼런스 릴레이 `lnpl relay`(근거:
  rfcs/0040-event-consumption-contract.md "8. 레퍼런스 릴레이 — `lnpl
  relay` (D8)").
- 구현됨 — `lnpl.publishers` 발행자 SPI와 발행 결과 분류(성공→ack,
  `PublishRejected`→ack+dead-letter, 그 외 `DriverError`→재시도)(근거:
  docs/backends.md "등록"). RFC-0061(Status: Draft) §4는 같은 분류를
  대칭 표로 다시 적으며 세 번째 갈래는 발명하지 않는다고 밝힌다(근거:
  rfcs/0061-event-publisher-spi.md "4. 오류 분류 대칭 — 발행 쪽 (D5)",
  Status: Draft).

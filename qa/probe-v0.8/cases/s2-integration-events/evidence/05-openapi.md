# 05-openapi

## orders-lite

```
$ lnpl openapi src/orders-lite/orders.lnpl
```
paths: `/orders-lite/create-order`, `/orders-lite/order/{id}`
(워크플로 POST 라우트 + entity 자동 GET 라우트)

## notifier

```
$ lnpl openapi src/notifier/notifier.lnpl
```
paths: **(없음 — 빈 배열)**

**관측**: `consume by`가 있는 이벤트의 인입 라우트(`POST
/-/events/order-placed`)는 OpenAPI에 **의도적으로 안 실린다** —
RFC-0040 §4: "CloudEvents 인입은 오퍼레이션이 아니다"(OpenAPI 계약검사
**뒤에** route 테이블에 합류). 그런데 notifier.lnpl에는 `service` 선언이
전혀 없어서(이 케이스에서는 필요 없다고 판단해 생략) 일반 워크플로
POST 라우트(`POST /<service>/<workflow>`)조차 생성되지 않는다 — 그
결과 notifier의 OpenAPI 문서는 완전히 빈 `paths`다. `lnpl serve`
자체는 `service` 없이도 정상 기동했고 event-consume 라우트는 정상
작동했다(evidence/06-serve.md, 08-outbox-relay.md) — service 선언은
event-consume 라우트 생성의 필수조건이 아닌 것으로 보인다(정본 확인은
안 함 — impl 열람 금지).

**consume 라우트가 노출되는지 여부**: 이번 태스크 노트 — 소비 라우트가
있는지 확인하려면 OpenAPI가 아니라 `POST /-/events/<slug>`를 직접
찔러봐야 한다(이미 그렇게 검증함). 즉 "이 서비스가 어떤 이벤트를
소비하는지"는 OpenAPI 계약만 보고는 **전혀 알 수 없다** — 통합 문서화
공백(축 doc/ops).

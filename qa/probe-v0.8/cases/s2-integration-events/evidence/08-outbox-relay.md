# 08-outbox-relay — R5/R6

## R5 — outbox 발행이 주문 저장과 함께 커밋되는가

### 정상 경로

```
$ lnpl run src/orders-lite/orders.lnpl --payload src/payloads/order-1.json \
    --backend sqlite:.claude/tmp/s2-store-r5.db \
    --network http --endpoint 'Fx=http://127.0.0.1:35979/fx' --json
rc=0
```
저장소:
```
lnpl_rows:   ('entity.order', 'entity.order#o-1',
              '{"fxStatus":"live","id":"o-1","totalKrw":10,"totalUsd":10}', 3)
lnpl_outbox: (1, 'wf.create.order.step.7.emit#1', 'event.order.placed',
              '{"id":"o-1","totalUsd":10}', 1788627344032, None)
```
같은 order_id(`o-1`)에 대해 order 행과 outbox 행이 **동시에** 존재 — 정상
경로에서 R5의 기본 요구는 충족.

**중요 결함**: outbox emission의 `payload`가 `{"id":"o-1","totalUsd":10}` —
**워크플로 입력 payload 그대로**다. `set`/`format`으로 나중에 채운
`totalKrw`(10, 우회값)와 `fxStatus`("live")는 emission에 **전혀 없다**.
`emit <eventName>` 구문에는 페이로드를 고르는 절이 없다 — `grammar.md`에
`with`/필드 매핑이 없고, `docs/ENFORCEMENT-MATRIX.md`도 "발행할 이벤트를
목적어로 요구한다"고만 적는다. RFC-0001의 `EventEmit.payloadMap`은 IR
필드로만 존재하고 저작 문법에 노출되지 않는다(확인: `.lnpl` 어디에도
payloadMap을 채우는 절이 없다). → **R5 "OrderPlaced{order_id, total_krw,
fx_status}"의 필드 구성은 불가** — `order_id`(≈id)만 자동으로 실리고
`total_krw`/`fx_status`는 실을 방법이 없다.

### 실패 주입 — both-or-neither 증명

가드를 `fxResult.status == 200 and fxResult.rate >= 0`로 바꿔(D14 사다리
(a)에 해당하는, 문서화된 가드 — `retry-on-non-idempotent`류가 아니라
비수치 rate 비교가 항상 크래시하는 것을 이용해 "주문 저장 이후 스텝에서
결정적으로 실패"를 재현) 같은 order-1.json·b1 스텁(rate=1350.5, 항상 이
가드를 크래시시킴)으로 재실행:

```
$ lnpl run <injected>.lnpl --payload order-1.json \
    --backend sqlite:.claude/tmp/s2-store-r5inject.db \
    --network http --endpoint 'Fx=http://127.0.0.1:36069/fx' --json
rc=3
runtime error: Cannot compare non-numeric fxResult.rate=1350.5 in condition
'fxResult.status == 200 and fxResult.rate >= 0'
```
저장소 재조회:
```
lnpl_rows:   []
lnpl_outbox: []
```
**both-or-neither 성립**: `create order`가 내부적으로는 이미 실행됐지만
(스텝 순서상 emit보다 먼저), 이후 스텝의 크래시가 전체 실행을 실패로
끝내자 **주문 행도 outbox 행도 둘 다 저장소에 남지 않았다** — "주문은
됐는데 이벤트가 없는" 상태는 관측되지 않는다. `policy rollback`을 이
서비스에 선언하지 않았는데도 롤백이 일어났다 — docs 교차확인
(rfcs/0036-policy-rollback-declaration-effect.md L45-55: "실행이 실패하면
그 호출된다 — 어느 서비스든, `policy rollback`을 선언했는지와 무관하게")
그대로 실측됨.

### R5 판정

**부분** — both-or-neither 원자성은 충족(정황 증거 + 실패 주입 둘 다
증명). emission 필드 구성("order_id/total_krw/fx_status 3필드")은 불가
(F-항목, task 07에서 blocker로 등재).

## R6 — relay → 소비 → Notification → 웹훅

```
$ lnpl serve src/notifier/notifier.lnpl --host 127.0.0.1 --port 0 \
    --backend sqlite:.claude/tmp/s2-notifier-store.db \
    --network http --endpoint 'Hook=http://127.0.0.1:36095/hook' \
    --log-format json
serving ... on http://127.0.0.1:36102

$ lnpl relay src/orders-lite/orders.lnpl \
    --backend sqlite:.claude/tmp/s2-store-r5.db \
    --target http://127.0.0.1:36102 --once
relay: acked 1 emission(s)
```

notifier 저장소:
```
('entity.notification', 'entity.notification#o-1',
 '{"id":"o-1","orderId":"o-1","status":"delivered"}', 2)
```

hook 스텁 로그(evidence/stub-hook-ok.log):
```
2026-09-05T16:56:57.275152+00:00 POST /hook 200 12
```
— 정확히 1회, 200.

### R6 판정

**충족** — relay가 outbox를 CloudEvents로 감싸 notifier의
`/-/events/order-placed`에 실제로 POST했고, notifier는 그것을 소비해
`Notification` 행을 만들고 실 웹훅을 호출했다. 다만 `Notification.id`가
실질적으로 order id를 재사용한 것(진짜 CloudEvents 이벤트 id는 워크플로
`input`에 노출되지 않는다 — RFC-0040 §6은 `id`를 멱등 클레임에만 쓰고
워크플로 payload는 `data`뿐이라고 명시)이라 "event_id" 개념 자체는
정확히 채울 수 없었다(F-항목, minor — orderId로 대체 가능해 실무 영향은
제한적).

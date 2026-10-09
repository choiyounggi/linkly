# 05 — 실서버(uvicorn) curl A1~A8

서버: `PYTHONPATH=<worktree>/qa/probe-v0.8/cases/s5-baseline-fastapi/src ORDERHUB_DB=<worktree>/.claude/tmp/live.db ORDERHUB_TEST_HOOKS=1 .venv-s5/bin/uvicorn orderhub.app:app --port 8765`
시드: `python -m orderhub.seed` (P1/P2/P3, C1/C2)

## A1 — 표준 주문 (C1, P1×2)
```
$ curl -s -w '\n%{http_code}\n' -X POST localhost:8765/orders -d '{"customer_id":"C1","lines":[{"product_id":"P1","qty":2}]}'
{"id":1,...,"subtotal":3998,"discount":0,"tax":320,"total":4318,...}
201
```
기대(subtotal 3998/discount 0/tax 320/total 4318) 일치.

## A2 — vip 할인 (C2, P1×3)
```
{"id":2,...,"subtotal":5997,"discount":600,"tax":432,"total":5829,...}
201
```
기대(5997/600/432/5829) 일치.

## A3 — 재고 부족 (C1, P1×2 + P3×1)
```
{"type":"...insufficient_stock","status":422,"code":"insufficient_stock"}
422
```
거부 확인.

## A4 — 결제 성공 (order 1, amount 4318, card 4242424242424242)
```
$ curl -s -w '\n%{http_code}\n' -X POST localhost:8765/orders/1/pay -d '{"amount":4318,"card_number":"4242424242424242"}'
{"id":1,"order_id":1,"amount":4318,"card_last4":"4242","status":"captured"}
201
```
응답 본문에 원문 PAN 부재, last4 "4242"만 노출.

## A5 — 금액 불일치 (order 2, amount 100)
```
{"type":"...amount_mismatch","status":422,"detail":"amount 100 != total 5829","code":"amount_mismatch"}
422
```

## A6 — 불법 전이 (order 1: ship 후 cancel)
```
$ curl -s -w '\n%{http_code}\n' -X POST localhost:8765/orders/1/ship
{"id":1,...,"status":"shipped",...}
200
$ curl -s -w '\n%{http_code}\n' -X POST localhost:8765/orders/1/cancel
{"type":"...illegal_transition","status":409,"detail":"cannot transition from shipped to cancelled","code":"illegal_transition"}
409
```
order 1 상태 shipped 유지 확인(에러 응답의 상태 전이 거부로 증명; DB 단언은 pytest A6에서).

## A7 — paid 취소 원자성 (order 2: pay 5829 후 cancel, shipped 이전)
```
$ curl -s -w '\n%{http_code}\n' -X POST localhost:8765/orders/2/pay -d '{"amount":5829,"card_number":"4242424242424242"}'
{"id":2,"order_id":2,"amount":5829,"card_last4":"4242","status":"captured"}
201
$ curl -s -w '\n%{http_code}\n' -X POST localhost:8765/orders/2/cancel
{"id":2,...,"status":"cancelled",...}
200
```

## A8 — 환불 한도 + admin gate (payment 1, A4의 결제 재사용)
```
$ curl -s -w '\n%{http_code}\n' -X POST localhost:8765/payments/1/refund -d '{"amount":100,"reason":"x"}'
{"type":"...forbidden","status":403,"code":"forbidden"}
403
$ curl -s -w '\n%{http_code}\n' -X POST localhost:8765/payments/1/refund -H 'X-Role: admin' -d '{"amount":2000,"reason":"partial1"}'
{"payment_id":1,"refunds":[{"id":2,"amount":2000,...}],"cumulative_refunded":2000}
201
$ curl -s -w '\n%{http_code}\n' -X POST localhost:8765/payments/1/refund -H 'X-Role: admin' -d '{"amount":2000,"reason":"partial2"}'
{"payment_id":1,"refunds":[...2 rows...],"cumulative_refunded":4000}
201
$ curl -s -w '\n%{http_code}\n' -X POST localhost:8765/payments/1/refund -H 'X-Role: admin' -d '{"amount":1000,"reason":"over"}'
{"type":"...refund_exceeds_payment","status":422,"detail":"cumulative refund 5000 exceeds payment 4318","code":"refund_exceeds_payment"}
422
```
비관리자(첫 시도부터 403), 관리자 2회 성공 + 3번째(누적 5000 > 4318) 거부 — 기대와 일치.

## 정리

서버 종료(`kill`) + `rm .claude/tmp/live.db` 실행함(아래 evidence/09-purity.md에서 워크트리
잔존 파일 없음을 재확인).

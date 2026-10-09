# 03-run — B1 실 소켓 호출 + 저장값

## 명령

```
$ nohup .venv/bin/python src/stubs/stub.py --mode b1 --port 0 --log evidence/stub-b1.log &
PORT=34239

$ .venv/bin/lnpl run src/orders-lite/orders.lnpl \
    --payload src/payloads/order-1.json \
    --backend sqlite:.claude/tmp/s2-store-b1.db \
    --network http --endpoint 'Fx=http://127.0.0.1:34239/fx?from=USD&to=KRW' \
    --json
rc=0
```

### stderr

```
warning: guard-skipped-steps [wf.create.order.guard.2] (line 29) fxResult.status != 200 —
the `when` guard did not run set o.totalKrw to o.totalUsd, format o.fxStatus from "fallback";
the workflow still reports completed, so a caller reading only the status cannot tell this
run from one that ran every step
0 info, 1 warning(s), 0 error(s)
```
(정상 — fallback 가드가 실행되지 않은 것은 기대대로다: fx가 200을 냈으므로. `--json`이
아니라 사람용 트레이스를 켰다면 이 경고가 항상 뜨는데, 초록 status만 보는 호출자에게
"이 실행이 두 분기 중 어느 쪽을 탔는지"를 감추는 진짜 관측 공백이다 — R9/F-항목 후보.)

## 스텁 액세스 로그 (실 소켓 증명)

```
$ cat evidence/stub-b1.log
2026-09-05T16:46:23.897968+00:00 GET /fx?from=USD&to=KRW 200 16
```

(두 번째 줄은 self-test 재사용 무관 — 이 로그는 이 run 전용 새 로그 파일이므로 위
한 줄이 이 실행의 유일한 호출. `?from=USD&to=KRW` 쿼리스트링이 실제로 전달됐음을
증명 — `--endpoint`에 준 URL 그대로 소켓에 나간다.)

## 실행 결과 바인딩

```json
{"o": {"id": "o-1", "totalUsd": 10, "totalKrw": 10, "fxStatus": "live"},
 "fxResult": {"rate": 1350.5, "status": 200}}
```

`fxResult.status == 200` 가드가 참으로 평가돼 live 분기를 탔다 — **R1 절반
충족**: 실 소켓 호출과 `fxResult.status`/`fxResult.rate` 실제 반영은 증명됨.
**R1 절반 불가**: `total_krw = round(total_usd × rate)` 계산 자체가 안 됨 —
evidence/01-authoring.md round 6/7 참고. 저장값 `totalKrw: 10`은 `totalUsd`를
그대로 복사한 우회값이지 `10 × 1350.5 = 13505`가 아니다(의미 손실 — 실제
환산이 이뤄지지 않음).

## 저장소 확인 (sqlite 직접 조회 — `lnpl db check`는 형태만 검사하고 값은 안 보여줌)

```
$ sqlite3 질의: SELECT * FROM lnpl_rows
('entity.order', 'entity.order#o-1',
 '{"_schema_gen": "efe6e7b07b96", "fxStatus": "live", "id": "o-1",
   "totalKrw": 10, "totalUsd": 10}', 3)
```

## outbox 확인 — R5 조기 관측 (task 04에서 정식 다룸)

```
$ sqlite3 질의: SELECT * FROM lnpl_outbox
(1, 'wf.create.order.step.7.emit#1', 'event.order.placed',
 '{"id": "o-1", "totalUsd": 10}', 1788626840218, None)
```

**중요 관측**: outbox emission의 `payload`가 `{"id": "o-1", "totalUsd": 10}` —
워크플로 **입력 payload 그대로**다. `set`/`format`으로 나중에 채운
`totalKrw`/`fxStatus`는 emission에 **없다**. `emit orderPlaced` 구문에는
페이로드를 고르는 절이 없다(grammar.md/ENFORCEMENT-MATRIX.md: `emit
<eventName>`은 목적어(이벤트 이름)만 받는다 — `with`/필드 매핑 절 없음,
RFC-0001의 `payloadMap`은 IR 필드로만 존재하고 저작 문법에 노출되지 않는다).
task 04에서 R5 요구사항("OrderPlaced{order_id, total_krw, fx_status}")과의
간극을 정식 F-항목으로 기록한다.

## 정리

```
$ kill <stub-pid>; ps aux | grep stub.py  →  (no output, 정상 종료)
```

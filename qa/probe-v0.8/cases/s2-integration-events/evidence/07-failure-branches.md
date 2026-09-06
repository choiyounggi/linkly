# 07-failure-branches — B2..B5

각 절: 스텁 모드 → 명령 → stdout/stderr → fx_status/total_krw/wall time →
스텁 로그 → 판정.

### B2 — fx 500 항상

```
$ lnpl run src/orders-lite/orders.lnpl --payload src/payloads/order-2.json \
    --backend sqlite:.claude/tmp/s2-store-b2.db \
    --network http --endpoint 'Fx=http://127.0.0.1:34970/fx?from=USD&to=KRW' --json
rc=0, wall≈0.09s
```
stderr: `guard-skipped-steps [...] (line 25) fxResult.status == 200 — the live
guard did not run` (기대대로 — fx가 500이므로 live 분기 스킵은 정상)

저장값: `{"id":"o-2","totalUsd":10,"totalKrw":10,"fxStatus":"fallback"}`
스텁 로그: `... GET /fx?from=USD&to=KRW 500 27` (1회)

**판정: 충족(부분)** — fx_status=fallback, 주문 성공(status completed) 자체는
맞다. 다만 "이전에 성공한 환율을 쓴다"는 요구의 "마지막 성공 rate 캐시"는
구현하지 않았다(round 7에서 이미 산술 자체가 불가라 캐시해도 곱할 수 없음 —
`totalKrw`는 그냥 `totalUsd` 복사). 부분 충족으로 기록.

### B3 — fx 500,500,200 (재시도 관측)

```
$ lnpl run ... --network http --endpoint 'Fx=http://127.0.0.1:35001/fx?from=USD&to=KRW' --json
rc=0
```
스텁 로그(신선한 프로세스, GET **1회만**): `... GET /fx?from=USD&to=KRW 500 27`

3가지 각도로 재확인(evidence/01-authoring.md round 8/9):
- 기본 endpoint(쿼리스트링 포함) — GET 1회
- 쿼리스트링 제거 endpoint — GET 1회
- `policy retry 3`(워크플로 스텝 레벨) 추가 — GET 1회

**판정: 불가** — `capability http Fx`에 `retry 2 backoff 200ms`를 선언했고
컴파일된 IR에도 `retry:{count:2,backoff_ms:200}`가 정확히 실렸지만(round 8
확인), `--network http` 실행에서 재시도가 전혀 일어나지 않는다. 재시도 횟수
자체를 관측할 수 없다 — R3의 "재시도 2회 관측" 요구를 충족할 방법이 없다.
축 rt, severity blocker (task 07에서 F-항목화).

### B4 — fx 3초 지연 (1초 내 타임아웃)

```
$ lnpl run ... --network http --endpoint 'Fx=http://127.0.0.1:43412/fx' --json
rc=0, wall=1.1457s  (< 2s 기준 충족)
```
저장값: `{"id":"o-2","totalUsd":10,"totalKrw":10,"fxStatus":"fallback"}`,
`fxResult: {"status": 0}` (연결/타임아웃 실패의 센티널 — HTTP 상태가 아니라 0)

스텁 로그(클라이언트가 끊은 뒤 서버 쪽 3초 sleep이 자연 종료할 때까지
프로세스를 살려 두고 기다려서 확보): `... GET /fx 200 16`(요청 수신 3초 뒤 —
서버는 결국 응답했지만 클라이언트가 이미 포기한 뒤라는 뜻. 이 한 줄이 "실
소켓 연결이 실제로 열렸다"는 증거다 — 연결도 안 됐다면 서버 로그 자체가
안 남는다)

**판정: 충족** — `policy timeout 1s`(서비스 레벨)를 선언하는 것만으로 실제
1.15초에 끊겼고(요구한 "1초 내"에 근접, 워크플로 자체의 다른 스텝 오버헤드
포함 감안 시 사실상 실측 성공), 워크플로는 크래시하지 않고 `fxResult.status=0`
→ `!= 200` 가드로 자연스럽게 fallback 분기를 탔다. **주의**: 이 결과는
`rfcs/0037-http-resilience.md` §1의 문서화된 계약("접속 실패·타임아웃은
DriverError를 던진다")과 다르다 — 문서대로라면 타임아웃은 예외로 전체 실행을
실패시켜야 하는데, 실측은 정상적인 status=0 값으로 조용히 반환됐다. 결과적으로
이 불일치가 R3의 요구(타임아웃 → fallback, 실행 실패 아님)에는 **유리하게**
작동했다 — doc-vs-runtime 불일치이지만 축 doc(문서가 실제보다 더 나쁘게
서술)로 기록, severity minor(우리에게 유리한 방향의 불일치).

### B5 — fx 200 `{"rate":"abc"}`

```
$ lnpl run ... --network http --endpoint 'Fx=http://127.0.0.1:45781/fx' --json
rc=0
```
저장값(현재 소스, `fxResult.status==200`만 검사): `{"totalKrw":10,"fxStatus":
"live"}` — **오분류**: 응답 바디가 깨졌는데도 live로 기록됨(다만 `totalKrw`
자체는 "abc"가 아니라 `totalUsd` 복사값 10이라 "잘못된 값이 저장되지 않는다"는
글자 그대로는 우연히 지켜짐 — round 7의 산술 불가 우회 덕분).

가드로 형식 검증 시도(round 10): `when fxResult.status == 200 and
fxResult.rate >= 0` → **rc=3, 런타임 에러**로 워크플로 전체가 죽음
("Cannot compare non-numeric fxResult.rate='abc'") — 정상 완료도 fallback도
아닌 크래시.

**판정: 불가** — 응답 본문 형태 검증(비수치 rate 거부)을 이 언어의 가드
어휘로 표현할 방법이 없다. 시도하면 오히려 전체 워크플로가 크래시한다(가드가
"거짓"으로 평가돼 다른 분기로 넘어가는 게 아니라 예외). 축 expr(가드가
타입 판별을 못 함) + rt(예외가 조용한 skip이 아니라 크래시), severity blocker.

## 요약 표

| B | fx_status | wall | 판정 |
|---|-----------|------|------|
| B2 | fallback | 0.09s | 부분(캐시 rate 미구현) |
| B3 | fallback(재시도 없이 즉시) | — | 불가(재시도 미집행) |
| B4 | fallback | 1.15s | 충족(문서와 다른 경로로) |
| B5 | live(오분류) | — | 불가(형식검증 표현 불가, 가드가 크래시) |

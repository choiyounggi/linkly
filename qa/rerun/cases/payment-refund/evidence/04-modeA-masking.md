# 04 — mode A: 경계 매트릭스·가드 커버리지·마스킹 채널 sweep (재측정)

전 실행: `.venv/bin/lnpl run payment-refund.lnpl --workflow <id> --json --payload raw/payloads/<f>.json`
심은 민감 값: cardNumber = `4111111111111111` (전 payload 동일). 네거티브 컨트롤: amountCents.

## 0. 컨트롤 페어 (D5 — 매트릭스 전 선행)

| 실행 | 관측(executed-step 목록) | raw |
|------|--------------------------|-----|
| amountCents=1000000 | `['create payment']` | run-approval-amt1000000.out |
| amountCents=1000001 | `[]` + skipped=`[wf.approval.guard.1]` (condition 원문·스킵 스텝 목록 포함) | run-approval-amt1000001.out |

**플립 확인** — 레버 연결됨. 이후 매트릭스 유효.

## 1. 금액 경계 매트릭스 (D4)

| amountCents | status | executed | skipped | 판정 | raw |
|-------------|--------|----------|---------|------|-----|
| -1 | completed | `[]` | guard.1 | **거부(관측 가능)** | run-approval-amt-1.out |
| 0 | completed | `[]` | guard.1 | **거부(관측 가능)** | run-approval-amt0.out |
| 1 | completed | `['create payment']` | — | 승인 (하한 배제 확인: 0<) | run-approval-amt1.out |
| 500000 | completed | `['create payment']` | — | 승인 (정상) | run-approval-amt500000.out |
| 1000000 | completed | `['create payment']` | — | 승인 (**정확히 한도 — 포함**) | run-approval-amt1000000.out |
| 1000001 | completed | `[]` | guard.1 | **거부(관측 가능)** | run-approval-amt1000001.out |

원 실측 대비: 원 T05에서 0·-1 payload가 **승인**됐다(하한 가드 무진단 탈락, F-2+F-6).
재측정에서는 하한이 `and`로 같은 가드에 있어 0·-1이 거부되고, 거부가 skipped
레코드(가드 id + condition 원문 + 스킵된 스텝 목록)로 관측된다.

## 2. 30일 창 매트릭스 (D4 — createdAt=2026-07-10T00:00:00Z 고정)

| requestedAt | 경과 | executed | 판정 | raw |
|-------------|------|----------|------|-----|
| 2026-07-15T00:00:00Z | 5d | read+create | 창 안 | run-refund-day5.out |
| 2026-08-09T00:00:00Z | **정확히 30d** | read+create | 창 안 (**포함** — RFC-0016 문서와 일치) | run-refund-day30.out |
| 2026-08-09T00:00:01Z | 30d+1s | read만, skipped=guard.1 | 창 밖 거부 | run-refund-day30plus1s.out |

30일 창이 **언어 안에서** 표현·집행됨: `input.requestedAt - payment.createdAt <= 30d`.
ageDays 사전 계산 우회 불필요. 존 없는 DateTime은 런타임 도메인 진단으로 거부
(rc=3, "a zoneless timestamp names a different instant on every machine" — RFC-0016
인용 포함, run-refund-nozone.err) — 원 F-5③의 원시 예외 대비 진단 품질 상향.

## 3. 가드 양방향 대조표 (D3 — executed-step 기준)

| 가드 | true run | false run | true 신호 | false 신호 |
|------|----------|-----------|-----------|------------|
| wf.approval.guard.1 | amt1/500000/1000000 | amt-1/0/1000001 | steps에 create payment | steps=[], skipped 레코드(id·condition·스텝 목록) |
| wf.refund.request.guard.1 | day5/day30 | day30plus1s | read+create | read만, skipped 레코드 |

전 가드 양방향 실행 완료. **F-6 관측성**: 가드 false여도 status=completed·rc=0이나,
(a) `skipped` 배열이 구조화 레코드로 존재, (b) stderr `guard-skipped-steps` 진단이
한계를 명시("a caller reading only the status cannot tell this run from one that ran
every step"), (c) `--strict`면 **rc=2** (run-approval-amt1000001-strict.err). 거절/성공이
기계 판독 가능해짐 — 관측 계약(RFC-0014)이 문서화·집행됨.

## 4. --strict 유/무 구분 (브리프 제약 3)

| 실행 | --strict 없음 | --strict |
|------|---------------|----------|
| 가드 false (amt1000001) | rc=0, completed | **rc=2** + guard-skipped-steps 진단 |
| compile (경고 2건) | rc=0 | rc=2 (compile-b4-strict.err) |

## 5. 부분 payload (원 F-13 재검)

- `{"amountCents": 0}` 단독 → **rc=0 실행**, 가드 평가(false→skip) — 원 "missing
  required field 'id'" 거동 소멸 (run-approval-partial.out)
- `{"amountCents": 5}` 단독(가드 true) → **rc=0, create payment 실행** — 카드번호 미제출로
  경계 프로브 가능 (run-approval-partial-true.out)

F-13 예비 판정: **해소** — 경계 프로브에 민감 필드 제출 강제 없음.

## 6. 마스킹 채널 sweep (D1 — wiki: security-data-masking-verification)

| 채널 | 원문 grep(`4111111111111111`+부분열) | 컨트롤(amountCents) | 마스킹 표기 | 판정 |
|------|---------------------------------------|--------------------|-------------|------|
| ① result.bindings | **0 hits** | 평문 존재 (day5.out:29 `"amountCents": 500000`) | `.result.bindings.payment.cardNumber = "***"` (day5.out:28) | **마스킹 집행** |
| ② trace | **0 hits** | 평문 존재 (day5.out:120) | `.trace.logs[0].payload.cardNumber = "***"` (day5.out:119) | **마스킹 집행** |
| ③ 사람용 기본 출력 | 0 hits | 값 자체 없음 | — | 값-무 채널(설계): 요약 1줄+스텝 행만 출력(run-approval-pretty.out 원문: `workflow Approval -> completed …`), 필드 값이 어떤 것도 실리지 않아 누출 표면 아님 |
| ④ OpenAPI | evidence/07에서 실측 | — | — | (Task 05) |
| ⑤ 에러 출력 | **0 hits** | 값 인용 존재 (`'2026-08-09T00:00:00'` — 채널이 값을 싣음을 증명) | — | **누출 없음** (run-refund-nozone.err) |

**원 F-7 재현 동형 인용** (원: bindings 원문 `"4111111111111111"` 30행 vs trace `"***"`
122행): 재측정 run-refund-day5.out에서 **28행 bindings `"cardNumber": "***"` + 119행
trace `"cardNumber": "***"`** — 양 채널 모두 마스킹, 같은 채널에 컨트롤 필드는 평문.
json 출력 전 파일 grep 전수: 원문 0히트 (raw/*.out, *.err 전체).

## 예비 판정 (F별)

- F-1 (입력 검증 불가): **해소** — Approval은 read 없이 `input.` 가드만으로 입력 검증 (§1)
- F-2 (가드 무진단 탈락): **해소** — 연쇄 가드는 파싱 에러(evidence/02), 0·-1 거부 실측 (§1)
- F-4 (Money 가드 런타임 크래시): **부분** — 컴파일 시점 도메인 진단으로 이동(compile-b1),
  단 Money 가드 자체는 여전히 불가(Integer 센트 모델링 강제)
- F-5 (30일 창 표현 불가): **해소** — 언어 내 표현+집행, 경계 포함 문서 일치 (§2)
- F-6 (조용한 skip): **해소** — 구조화 skipped 레코드+진단+--strict rc=2 (§3·§4)
- F-7 (마스킹 부분 집행): **해소** — 양 채널 마스킹+컨트롤 검증 (§6; ④는 Task 05)
- F-13 (전체 필드 강제): **해소** (§5)

## 신규 관찰 (N-후보)

- **N-1 후보**: payload는 전 엔티티 필드의 합집합이라 동명 필드(amountCents)가 입력
  네임스페이스와 read 행 시드에 **같은 값으로** 들어간다(day5.out bindings: payment 행에
  requestedAt·paymentId까지 복사됨). mode A `run` 단독으로는 `input.amountCents ≠
  payment.amountCents`인 비대칭 주입이 불가 — 전액/부분/초과 구분의 런타임 실측은
  spec `stored` given 또는 mode B `--field`로만 가능. (Task 05·06에서 실측)

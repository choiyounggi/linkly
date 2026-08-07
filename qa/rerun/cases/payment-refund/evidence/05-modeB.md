# 05 — mode B (네이티브) 실측 (재측정)

환경: LLVM PATH + SDK CPATH/LIBRARY_PATH export (evidence/00). 빌드 workdir 기본
`.claude/tmp/lnpl-build`. 전 실행 rc=0, 재시도 0.

## 승인 경계 (mode B)

| 실행 | 관측 | raw |
|------|------|-----|
| `--field input.amountCents=500000` | `effect create payment RepositoryCall` + completed | build-approval-500000.out |
| `--field input.amountCents=0` | effect 없음(스킵) + completed | build-approval-0.out |

## 비대칭 금액 주입 — 전액/부분/초과 (원 F-3 런타임 실측, mode A run에서는 N-1로 불가)

`--field`가 정본 점 표기 이름(input.amountCents, payment.amountCents)을 받아 입력과
저장 행을 **독립** 주입:

| 셀 | input / payment | 관측 | raw |
|----|-----------------|------|-----|
| 부분(<) | 300 / 500 | read + **create refund** | build-refund-partial.out |
| 전액(==경계) | 500 / 500 | read + **create refund** (`<=` 포함) | build-refund-full.out |
| 초과(>) | 600 / 500 | read만 — **create 없음(거부)** | build-refund-over.out |

`==` 단독 구분(probe-b5 RefundFull, `input.amountCents == payment.amountCents`):

| 셀 | input / payment | 관측 | raw |
|----|-----------------|------|-----|
| equal | 500 / 500 | **create refund** | build-b5-eq-equal.out |
| notequal | 300 / 500 | create 없음(스킵) | build-b5-eq-notequal.out |

전액(`==`)/부분(`<`)/초과 거부(`<=` 상한)가 전부 언어 안에서 표현·집행·관측된다.
원 실측의 "주석 문서화" 우회 소멸.

## 원 실측 대비

원: mode B 1회 실행 PASS(우회 누적 후). 재측정: 원형 가드(and·필드 간 비교·DateTime
산술 포함)가 mode B로 하강·실행됨. 생략한 `--field`는 0 기본(문서 명시)이라 refund
창 항은 0-0=0<=30d로 참 — DateTime 필드에 별도 값을 주지 않고도 금액 차원만 분리
실측 가능했다.

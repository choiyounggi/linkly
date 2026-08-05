# 06 — differential (mode A vs mode B) (Task 05)

명령: `.venv/bin/lnpl diff qa/cases/rate-notify/rate-notify.lnpl --payload qa/cases/rate-notify/payloads/rN.json --workdir .claude/tmp/lnpl-diff`
raw: `evidence/raw/diff-r1.txt`, `diff-r2.txt`. 시도 각 1회.

## 결과 (원문 인용)

r1 (가드1·2 참, until 즉시 성립 — 발화 경로), rc=0:

```
PASS 1/4 execution order — 4 step(s): validate measurement -> find measurement -> create notification -> emit notificationSent
PASS 2/4 policy outcome — status=completed
PASS 3/4 observability signals — 4 effect(s) per step match
PASS 4/4 masking — no secret marker in either mode's output
differential: EQUIVALENT
```

r2 (가드1 거짓 — 스킵 경로), rc=0:

```
PASS 1/4 execution order — 3 step(s): validate measurement -> find measurement -> emit notificationSent
PASS 2/4 policy outcome — status=completed
PASS 3/4 observability signals — 3 effect(s) per step match
PASS 4/4 masking — no secret marker in either mode's output
differential: EQUIVALENT
```

## 판정

- **가드 발화 경로(r1)와 스킵 경로(r2) 모두 `EQUIVALENT`** — RFC-0008 §5의
  skip 집합 동치까지 실행 순서 분류(1/4)에서 확인됨 (r2의 3-step 순서에
  create 부재가 양 모드 일치).
- `lnpl diff`는 payload에서 조건 필드를 **스스로 추출해** mode B에 배선한다 —
  수동 `--field` 불필요. 05-modeB.md의 bare-이름 무시 마찰이 diff 경로에는
  없다(도구가 배선을 소유할 때는 안전, 사람이 직접 넘길 때만 위험).
- until 라운드 수 동치는 r1(0라운드)로 커버. 16라운드 경로(r7 payload)의
  diff는 미실행 — 계획 매트릭스가 r1·r2 2건으로 고정한 범위(커버리지 갭으로
  총평에 기록).

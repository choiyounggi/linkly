# evidence/06 — differential (`lnpl diff`) (T06)

명령: `.venv/bin/lnpl diff --workflow <id> --workdir .claude/tmp/t2-diff-<id> qa/cases/payment-refund/payment-refund.lnpl`

두 워크플로 모두 rc=0, 시도 각 1회:

```
PASS 1/4 execution order — 3 step(s): validate payment -> find payment -> update payment
PASS 2/4 policy outcome — status=completed
PASS 3/4 observability signals — 3 effect(s) per step match
PASS 4/4 masking — no secret marker in either mode's output
differential: EQUIVALENT
```

(wf.refund.request도 동일하게 4/4 PASS, EQUIVALENT — 원본: evidence/raw/diff-*.out)

## 마스킹 A/B 비교 노트 (brief tacit — RFC-0004 관찰 클래스)

- differential 검사 4/4가 명시적으로 **masking**을 본다 — "no secret marker in either mode's output".
- 그러나 이 검사 표면은 mode A `--json`의 `result.bindings` 채널을 포함하지 않는다:
  T05에서 실측한 **bindings 원문 누출(4111…/s3cret-value)은 differential이 초록인 채로 존재**한다.
- 즉 "마스킹 differential PASS"는 '비교한 표면에 시크릿 마커 없음'(present)이지
  '모든 출력 채널이 마스킹됨'(verified)이 아니다 — F-기록 참조.

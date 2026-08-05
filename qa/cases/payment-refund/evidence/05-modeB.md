# evidence/05 — mode B (`lnpl build`) (T06)

명령: `.venv/bin/lnpl build --workflow wf.approval --workdir .claude/tmp/t2-build --run qa/cases/payment-refund/payment-refund.lnpl`
(LLVM PATH + CPATH/LIBRARY_PATH export 상태 — evidence/00-env.md)

```
rc=0
native binary: .claude/tmp/t2-build/module
step 1 validate payment
step 2 find payment
step 3 update payment
status completed
exit=0
```

- 시도 1회, **PASS**. 예고된 환경 실패(AGENTS.md의 7F/62E)는 이 워크트리에서는 재현되지 않음 —
  dev_doctor rc=0 상태에서 MLIR→네이티브 빌드·실행 정상.
- mode B stdout은 스텝·effect·status만 출력하고 필드 값을 출력하지 않음 →
  mode B 단독의 마스킹 노출 표면 없음.
- 빌드 workdir은 .claude/tmp(비추적)이며 측정 후 삭제(AGENTS.md 잔존 금지 규칙).
- 원본: evidence/raw/build-approval.{out,err}

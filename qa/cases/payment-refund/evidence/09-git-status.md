# evidence/09 — 스코프 밖 무변경 증명 (T09)

시각: 2026-08-05 21:50 KST, 기준 commit 713a4cba14a5ace278801c193abbc809ab09894e (변동 없음).

```
$ git status --porcelain -uall | grep -v "^?? qa/cases/payment-refund/"
(출력 없음, grep rc=1)
```

- `git status --porcelain -uall`의 모든 항목(46개)이 `?? qa/cases/payment-refund/**` —
  tracked 파일 수정 0건, 스코프 밖 신규 파일 0건.
- 비추적 작업 부산물: `.venv/`(워크트리 자체 venv), `.claude/tmp/`(payload·캡처) —
  둘 다 `.gitignore` 3·8행에 의해 무시되어 status에 나타나지 않음. mode B 빌드
  workdir(.claude/tmp/t2-build 등)은 측정 후 삭제(evidence/05).
- impl/, plugins/, scripts/, rfcs/, mlir/, schemas/, examples/, kb/, docs/ 무변경 —
  파이프라인 마찰은 전부 F-기록으로만 대응(플랫폼 무수정 원칙).

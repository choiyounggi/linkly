# evidence/09-purity — 범위 순수성 증명 (Task 07, D13)

```
$ git status --porcelain -uall
?? qa/cases/inventory-order/CASE-SPEC.md
?? qa/cases/inventory-order/FINDINGS.md
?? qa/cases/inventory-order/evidence/00-env.md
?? qa/cases/inventory-order/evidence/01-authoring.md
?? qa/cases/inventory-order/evidence/02-parse-lower.md
?? qa/cases/inventory-order/evidence/03-validate.md
?? qa/cases/inventory-order/evidence/04-modeA.md
?? qa/cases/inventory-order/evidence/05-modeB.md
?? qa/cases/inventory-order/evidence/06-differential.md
?? qa/cases/inventory-order/evidence/07-openapi.md
?? qa/cases/inventory-order/evidence/08-spec.md
?? qa/cases/inventory-order/inventory-order.lir.json
?? qa/cases/inventory-order/inventory-order.lnpl
?? qa/cases/inventory-order/inventory-order.openapi.json

$ git status --porcelain -uall | grep -cv '^?? qa/cases/inventory-order/'
0
```

판정: `qa/cases/inventory-order/` 밖 변경 0줄 — impl/, plugins/, scripts/,
rfcs/, mlir/, schemas/, examples/, kb/, docs/ 무변경. `.venv/`·`.claude/tmp/`는
gitignore 대상(.gitignore:3,8)이라 출력에 없음(이 evidence 파일 자체는 이 캡처
직후 스코프 안에 추가됨).

주(-uall 사유): 기본 `git status --porcelain`은 미추적 디렉터리를 `?? qa/`로
접어 표시해 경로 필터가 헛돈다 — 파일 단위 증명에는 `-uall`이 필요하다.

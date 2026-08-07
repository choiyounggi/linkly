# 03 — IR 스키마 검증 (재측정)

- `.venv/bin/python scripts/validate_ir.py payment-refund.lir.json` → **rc=0**,
  `PASS: qa/rerun/cases/payment-refund/payment-refund.lir.json` (raw/validate.out)
- 재시도: 0 (1회 통과)

원 실측(4회 재검증 전부 PASS)과 동일하게 스키마 게이트는 통과. 단 검증 스코프 주의:
guard-true-path-coverage(wiki)가 지적하듯 이 단계는 교차 참조 실행 가능성을 보지
않으므로, 가드 뒤 스텝의 실효성은 evidence/04의 가드 양방향 실행이 판정한다.

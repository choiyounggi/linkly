# 09 — 스코프 순수성·플랫폼 무수정 증명 (재측정)

게이트(D8, wiki: qa-process-scope-purity-checks): `git status --porcelain -uall`
(플래그 명시 — `-unormal`의 디렉터리 축약이 필터를 무효화하므로) 전 라인의 경로가
허용 prefix(`qa/rerun/cases/payment-refund/`, `.venv/`, `.claude/tmp/`) 안임을 확인.

## 필터 양방향 검증 (채택 전 — 판별력 증명)

- 합성 인스코프 라인만 투입 → 위반 0 (**pass 방향 확인**)
- 합성 아웃스코프 라인 ` M impl/lnpl/interp.py` 심음 → 그 라인 정확히 검출
  (**fail 방향 확인**)

## 실측

- `git status --porcelain -uall` → **127라인 전부 `?? qa/rerun/cases/payment-refund/…`**
  (원문: raw/git-status-uall.txt)
- 허용 prefix 밖 라인: **0** — impl/·plugins/·scripts/·rfcs/·examples/·kb/·qa/cases/·
  qa/REPORT.md 및 qa/rerun/ 타 케이스 무변경. **플랫폼 무수정.**
- 추적 파일 변경(` M`/`A `) 0 — 신규 파일(untracked)만 존재.
- 빌드 잔여물 정리: `.claude/tmp/lnpl-build`·`lnpl-diff` 삭제(AGENTS.md 규칙).
  `.venv`는 워크트리 자체 소유(gitignore 대상, status 미출현).

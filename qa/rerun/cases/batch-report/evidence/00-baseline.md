# 00-baseline — r3-batch-report 재측정

- 날짜: 2026-08-07 (KST)
- HEAD: 6d84bd6f9f41e4978f916ee191ab4216cf591da9 (main 6d84bd6 기준 워크트리 브랜치 qa/r3-batch-report)
- 원 실측 HEAD: 713a4cb (qa/cases/batch-report/FINDINGS.md 헤더) — 본 재측정은 #43~#50 구현 이후 상태를 측정한다

## 시작 시점 git status --porcelain -uall (allowlist 밖 무변경 확인)
```
?? qa/rerun/cases/batch-report/evidence/00-baseline.md
?? qa/rerun/cases/batch-report/evidence/00-env-doctor.log
```

## purity 게이트 양방향 검증 (D7, wiki: qa-process-scope-purity-checks)

게이트: `git status --porcelain -uall | grep -Ev "^\?\? (qa/rerun/cases/batch-report/|\.venv/|\.claude/tmp/)"` — 라인 0건 = PASS.
`.venv/`·`.claude/tmp/`는 gitignore 확인됨(`git check-ignore` 실측) — status에 아예 나타나지 않으나 방어적으로 allowlist 유지.

- (a) PASS 방향: 현 상태(생성물 전부 qa/rerun/cases/batch-report/ 안) → 위반 0건 ✓
- (b) FAIL 방향: allowlist에서 qa/rerun 항목을 뺀 필터로 재실행 → 기존 in-scope 라인 4건이 위반으로 검출됨 ✓ (게이트가 두 상태를 구분함 — 심은 파일 불요, 기존 라인이 반증 재료)

양방향 모두 실측 — 게이트 채택.

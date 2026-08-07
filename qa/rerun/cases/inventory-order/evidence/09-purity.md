# evidence/09-purity — 스코프 순수성 + 임시 산출물 회수 (재측정 Task 08)

## 임시 산출물 회수 (D14)

세션 스코프 루트 일괄 삭제 — payload·로그·build/diff workdir·프로브 사본 전부
`.claude/tmp/qa-r1/` 아래에만 생성했으므로 한 번에 회수:

```
$ find .claude/tmp/qa-r1 -type f | wc -l
74            # 삭제 전 계수
$ rm -rf .claude/tmp/qa-r1
$ ls .claude/tmp/qa-r1
# 존재하지 않음 — 델타 0 (테스트가 만든 빌드 작업 디렉터리 잔존 0)
```

## 순수성 게이트 (D13 — `-uall` 명시, 양방향 검증)

게이트 커맨드(허용 접두: `qa/rerun/cases/inventory-order/`):

```
git status --porcelain -uall | grep -v '^?? qa/rerun/cases/inventory-order/'
```

| 런 | 조건 | 결과 |
|----|------|------|
| 1 | 현재 트리(전부 in-scope) | 위반 0건 — **PASS** |
| 2 | `touch qa/rerun/OUT-OF-SCOPE-PROBE` 심음 | 출력 `?? qa/rerun/OUT-OF-SCOPE-PROBE` — **FAIL 검출**(게이트 판별력 증명) |
| 3 | 프로브 제거 후 | 위반 0건, grep rc=1 — **PASS** |

최종 `git status --porcelain -uall` 전체 출력(15줄 전부 `??
qa/rerun/cases/inventory-order/` 접두 — 본 파일 포함):

```
?? qa/rerun/cases/inventory-order/DELTA.md
?? qa/rerun/cases/inventory-order/FINDINGS.md
?? qa/rerun/cases/inventory-order/evidence/00-env.md … 09-purity.md (10개)
?? qa/rerun/cases/inventory-order/inventory-order.lir.json
?? qa/rerun/cases/inventory-order/inventory-order.lnpl
?? qa/rerun/cases/inventory-order/inventory-order.openapi.json
```

판정: PASS — 추적 파일 수정 0건(`M`/`A`/`D` 라인 없음), 신규 파일 전부 소유
디렉터리 안. **플랫폼 무수정**(impl/·plugins/·scripts/·rfcs/·examples/·qa/cases/
등 out-of-scope 경로 변경 0) 증명 완료.

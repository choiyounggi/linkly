# 최종 부분집합 파이프라인 요약 — batch-report.lnpl

판정 규칙(D11): PASS=대조군(02-control-pipeline.md, 전 단계 통과)과 동일 수준 통과.
이 환경은 대조군 전 단계 PASS이므로 N/A(env) 없음 — 실패는 전부 케이스 귀속이었을 것.

| 단계 | 명령 | exit | 판정 | 재시도 | 증적 |
|------|------|------|------|--------|------|
| parse+lower | `lnpl compile … -o final/batch-report.lir.json` | 0 | PASS (21 nodes, 의도 경고 1: response measured-only) | 0 | 06-pipeline-compile.log |
| validate | `validate_ir.py final/batch-report.lir.json` | 0 | PASS | 0 | 06-pipeline-validate.log |
| mode A (BuildReport) | `lnpl run … --json` | 0 | PASS (4 steps, status=completed) | 0 | 06-pipeline-modeA-build.log |
| mode A (GetReport) | `lnpl run … --workflow wf.get.report --json` | 0 | PASS (validate→find, RepositoryCall read) | 1 (워크플로 id 표기 발견) | 06-pipeline-modeA-get.log |
| mode B | `lnpl build … --workdir .claude/tmp/final-build --run` | 0 | PASS (status completed) | 0 | 06-pipeline-modeB.log |
| differential (BuildReport) | `lnpl diff … --workdir .claude/tmp/final-diff` | 0 | PASS (4/4 EQUIVALENT) | 0 | 06-pipeline-diff.log |
| differential (GetReport) | `lnpl diff … --workflow wf.get.report --workdir .claude/tmp/final-diff-get` | 0 | PASS (4/4 EQUIVALENT) | 0 | 06-pipeline-diff-get.log |
| openapi | `lnpl openapi … -o final/batch-report.openapi.json` | 0 | PASS | 0 | 06-pipeline-openapi.log |

재시도 상세: `lnpl run --workflow GetReport` → `runtime error: no such workflow:
'GetReport'` exit 3. 워크플로 이름이 아니라 IR 노드 id(`wf.get.report` — camelCase가
점 표기 소문자로 변환)를 요구. 변환 규칙 미문서화, 에러 메시지에 사용 가능 워크플로
목록 없음 — IR JSON을 grep해야 알 수 있었음(F-후보, minor).

두 워크플로 모두 A/B 동치 확인 — 조회 엔드포인트(c)는 파이프라인 끝까지 완주.

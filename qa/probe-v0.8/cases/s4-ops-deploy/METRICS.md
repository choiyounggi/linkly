# METRICS — s4-ops-deploy

| 지표 | 값 | 측정 방법 |
|------|-----|-----------|
| 소스 줄 수 (.lnpl, 공백·주석 제외) | linkhub.lnpl 103 / linkhub.v2.lnpl 106 | `grep -cve '^\s*$'`(주석 라인 포함 집계 — .lnpl은 `#` 주석이 다수라 순수 코드 줄은 이보다 적음, 별도 분리 안 함) |
| 파일 수 | 2 (linkhub.lnpl, linkhub.v2.lnpl) + 보조 1(shorten.lnpl, R4 jwt 플래그 검증 전용) | `src/*.lnpl` |
| authoring 라운드 (편집→재실행 사이클 총계) | 2 (linkhub 그대로 복사·컴파일 1회 성공; v2에 필드 1개 추가·컴파일 1회 성공) | evidence/00, 07 |
| 실행한 CLI 명령 수 | ~140(추정, `~`) | evidence 전체의 `$` 프롬프트 라인 개산 — 정확한 셸 이력 로깅 없음 |
| 첫 컴파일 성공까지 라운드 | 1 (linkhub, v2 둘 다) | evidence/00-env.md, evidence/07-migration.md |
| 첫 spec 전건 통과까지 라운드 | N/A(이 케이스는 serve/ops 실증이 목적이라 `lnpl run`으로 spec 스위트를 별도 실행하지 않음 — linkhub 자체 spec 4블록은 원본 예제가 이미 통과 상태로 검증된 파일) | — |
| spec 시나리오 수 / 단언 수 | 4 스펙 블록 / 12 단언(completed·failed·effects complete·rows 등 단언 키워드 수) | `grep -c "^    spec$"` / `grep -cE '^\s+(completed\|failed\|effects complete\|rows \|cache written\|error )'` linkhub.lnpl |
| 요구사항 충족/부분/불가/우회 (개수) | 충족 7 / 부분 2 / 불가 0 / 우회 0 | FINDINGS.md 커버리지 표 |
| 결함 탐지: spec이 잡은 것 / 사람이 실행 출력을 보고 잡은 것 / 못 잡고 지나간 것 | spec 0(스펙 스위트 미실행, 위 참고) / 사람 7(F-1~F-7 전부 curl·psql·redis·docker 실행 출력 관찰로 발견) / 못 잡고 지나간 것 불명(정의상 알 수 없음) | FINDINGS.md Frictions |
| 읽은 문서 (파일 목록과 대략 줄 수) | docs/backends.md(§8~14, ~350줄) · docs/serving.md(§운영표면~설정파일, ~450줄) · docs/migration.md(§1~3, ~90줄) · plugins/lnpl/skills/lnpl-authoring/references/{verbs,declarations,grammar}.md(발췌 ~60줄) · examples/deploy/{Dockerfile,README.md,.dockerignore}(전문 ~80줄) · examples/{linkhub,shorten}.lnpl(전문 ~150줄) · 외부 3레포 README(lnpl-postgres/redis/otel, 전문 ~350줄) · qa/probe-v0.8/requirements/{README,s4,FINDINGS-SCHEMA}.md(전문 ~200줄) | 이 세션이 실제 Read/gh api로 연 파일 |
| 변경 요청(R-change) 반영: 바뀐 줄 수 / 라운드 / 기존 spec 중 깨진 것 | N/A(이 케이스에 변경 요청 시나리오 없음 — R9의 스키마 추가는 변경 요청이 아니라 계획된 마이그레이션 절차) | — |
| 벽시계 시간 (시작~FINDINGS 완성) | ~51분 (2026-09-05T16:20Z ~ 2026-09-05T17:11Z) | evidence/00-env.md 시작 타임스탬프, 이 파일 완성 시각 |
| 토큰 | (코디네이터가 트랜스크립트로 기입) | token-report.sh |

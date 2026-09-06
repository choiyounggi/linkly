# METRICS — s2-integration-events

| 지표 | 값 | 측정 방법 |
|------|-----|-----------|
| 소스 줄 수 (.lnpl, 공백 제외) | 80 (orders.lnpl 59 + notifier.lnpl 21) | `grep -cve '^\s*$' src/orders-lite/orders.lnpl src/notifier/notifier.lnpl` |
| 파일 수 | 2 `.lnpl` + 1 `.py`(스텁, lnpl 밖) + 2 payload json | `find src -name '*.lnpl'` 등 |
| authoring 라운드 (편집→재실행 사이클 총계) | 15 | evidence/01-authoring.md `grep -c '^round'` |
| 실행한 CLI 명령 수 | ~55 (lnpl compile/run/serve/relay/spec/openapi 합계 ~35, curl ~6, sqlite3 조회 ~10, 스텁 self-test 1스크립트=7모드) | evidence/00~09 전수 근사 |
| 첫 컴파일 성공까지 라운드 | orders-lite: 5 (round 1-5) / notifier: 3 (round 11-13, notifier 전용 카운트) | evidence/01-authoring.md |
| 첫 spec 전건 통과까지 라운드 | N/A(의도적으로 미달성 유지 — spec 3은 R4의 실제 결함을 문서화하기 위해 계속 레드로 둠) | evidence/04-spec.md |
| spec 시나리오 수 / 단언 수 | 3 시나리오 / 9 단언(시나리오당 completed+effects complete+result 3개) | evidence/04-spec.md |
| 요구사항 충족 / 부분 / 불가 / 우회 (개수) | 충족 3(R2,R6,R7) / 부분 1(R10) / 불가 2(R4,R9) / 우회(의미손실) 4(R1,R3,R5,R8) | FINDINGS.md 커버리지 표 집계 |
| 결함 탐지: spec이 잡은 것 / 사람이 실행 출력을 보고 잡은 것 / 못 잡고 지나간 것 | spec 1건(R4, evidence/04-spec.md spec 3 FAIL) / 사람 10건(F-1,F-2,F-3,F-4,F-6,F-7,F-8,F-9,F-10,F-11 — 전부 실행 출력·IR·로그를 직접 읽어 확정) / 못 잡고 지나간 것 0건(발견한 것은 전부 F-항목화) | FINDINGS.md Frictions |
| 읽은 문서 (파일 목록과 대략 줄 수) | evidence/00-env.md 표 19행(전체 정독 12개 + 부분열람 5개 + grep-only 2개) | evidence/00-env.md |
| 변경 요청(R-change) 반영: 바뀐 줄 수 / 라운드 / 기존 spec 중 깨진 것 | N/A(S2에는 변경요청 태스크가 없음 — s1/s3 등 다른 케이스의 몫) | — |
| 벽시계 시간 (시작~FINDINGS 완성) | 34분 (launch 16:33Z → impl_done 17:07Z) | 코디네이터 status 타임스탬프(plan_ready/impl_done) — N1 리뷰 피드백 반영, 세션 타임스탬프 추정치 대신 실측값으로 교체 |
| 토큰 | (코디네이터가 기입) | token-report.sh |
| B-시나리오 판정 개수 | 충족 2(B4,B6) / 부분 3(B1,B2,B7) / 불가 2(B3,B5) | evidence/07·09 요약표 |

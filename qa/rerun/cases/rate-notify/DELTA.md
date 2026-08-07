# DELTA — rate-notify: 원 실측(713a4cba) → 재측정(6d84bd6)

## F-1~F-12 전건 판정

| F-id | 원 심각도 | 재측정 관찰 (증적) | 판정 | 근거 |
|------|-----------|--------------------|------|------|
| F-1 notify/send 동사 부재 | minor | verbs.md 29행 여전히 "`send`, `notify` … 이 표에 **없다**" (evidence/01-authoring.md) | **잔존** | 어휘 불변 — create+emit 근사 우회도 원과 동일 |
| F-2 미선언 이벤트 런타임 잠복 | major | 심은-참조 probe가 **compile rc=2** 거부 + "declared: event.notification.sent" 후보 제시 (evidence/02-compile.md) | **해소** | 원: compile 0 error→런타임 rc=1·가드 스킵 시 잠복. 참조 해석이 컴파일 타임으로 이동 |
| F-3 --field 이름 불일치 무경고 무시 | major | bare 이름 **rc=2** 거부 + "valid: measurement.acknowledged, measurement.value, priorNotification" 목록 (evidence/05-modeB.md) | **해소** | 원: 무경고 exit=0, 전 필드 기본값 평가. help 정책 문구도 rejected로 개정 |
| F-4 spec 블록 무음 병합 | major | 3블록 → "**3 case(s)**", given/expect 블록별 분리 (evidence/08-spec.md 시도 1) | **해소** | 원: "1 case(s)" 모순 병합. spec.md에 "블록마다 독립 케이스" 문서화 |
| F-5 given id 미적용으로 케이스 실행 불가 | major | given `id 3f2504e0-…` 적용되어 케이스 1이 4스텝 완주, 8/8 PASS (evidence/08-spec.md 시도 2) | **해소** | 원: steps=1 validate 실패(id 유실). 기본 payload 위 필드 덮어쓰기 문서화(issue #46)와 실동작 일치 |
| F-6 given `no <field>` 스코프 미문서화 | minor | `no priorNotification` 원과 동일 문구로 거부, references/spec.md에 스코프 규정 여전히 없음 (evidence/08-spec.md 시도 1) | **잔존** | 우회 동일(라인 제거). 재측정 spec 재시도 1의 원인 |
| F-7 `==`/`!=` grammar 부재 | info | grammar.md 31행 "`<=` `>=` `==` `!=` `<` `>`" + `==` probe compile rc=0 (evidence/01-authoring.md, 02-compile.md) | **해소** | RFC-0015 정본화가 생성 참조·실동작 양쪽에 반영 |
| F-8 examples/guarded.lnpl 부재 | info | 존재 — presence·comparison 양방향 실행 커맨드와 until 미수록 사유까지 헤더에 정본화 (evidence/01-authoring.md) | **해소** | 원: checkout 1줄이 유일한 가드 예제 |
| F-9 0라운드 until 무표지 | info | R1 skipped에 `{guard: wf.report.guard.3, mode: until, rounds: 0}` 구조화 레코드 + `guard-skipped-steps` stderr 진단이 when/until 대칭 (evidence/04-modeA.md) | **해소** | 원: skipped=[] 무표지 비대칭 |
| F-10 run --json에 rows 신호 부재 | info | result 키에 rows 여전히 없음(키는 증가: correlation_id, failure_reason 등). 단 spec 러너 rows 단언이 실작동(rows=1/rows=0 검증 통과) (evidence/04-modeA.md, 08-spec.md) | **부분** | 직접 신호 부재 지속, 원 우회로(F-5로 불가였던 spec rows)는 복구 |
| F-11 진단에 파일:라인 부재 | info | 경고 여전히 노드 id(`[perf.rate.notify]`)만. F-2 에러는 `workflow Report:` 구성명 맥락 추가되었으나 파일:라인은 없음 (evidence/02-compile.md) | **잔존** | 경미 개선(구성명), 원 기대(소스 위치)에는 미달. 소스가 짧아 실영향 없음 — 원 판정 유지 |
| F-12 spec 실패 사유 미출력 | minor | 단언 불일치는 `(steps=4 want=5)` 인라인, 런타임 실패는 `reason: step='find measurement' — repository read found no row` 직접 출력 (evidence/08-spec.md probe 2건) | **해소** | 원: FAIL 줄뿐, 별도 run probe 필요했음 |

**집계: 해소 8 (major 4/4 전건 포함) · 부분 1 · 잔존 3 (전부 minor/info).**

관련 오픈 버그: **#51** (until의 mode B 차등 발산) — r7 diff **DIVERGENT 재현**
(evidence/06-differential.md). 실행 순서 검사는 양모드 20스텝 동일 PASS, 발산은
관측 맵의 스텝 이름 중복 처리 비대칭(A 마지막 1개 vs B 16개 누적) — 원 F-목록
밖의 신규 추적 이슈로, "잔존(#51 추적 중)"으로 기록.

## 재시도 비교 (단계별, 원 → 재측정)

| 단계 | 원 | 재측정 | 원인 소멸 |
|------|-----|--------|-----------|
| authoring | 3 (emit 이름 1 + spec 재구성 2) | **0** | F-2가 컴파일 거부로 이동, F-4·F-5 해소로 spec 재구성 불요 |
| modeA | 1 (F-2로 6/7 실패 후 재실행) | **0** | 매달린 참조가 실행에 도달 불가 |
| modeB | 1 (F-3로 전 런 오평가 후 dotted 재실행) | **0** | bare 이름 즉시 거부(오평가 자체가 불가능) |
| spec | 3 (상한 도달 — FAIL) | **1** (F-6 잔존으로 경계 given 1줄 축소) | F-4·F-5·F-12 해소 |
| 합계 | **8** | **1** | — |

## 신규 마찰

- **N-1** (info): `--strict`가 진단 종류를 구분하지 않아 perf 경고 상존 소스에선
  전 런 rc=2 — 가드 스킵 감지를 exit code로만 할 수 없음(JSON skipped 레코드
  사용으로 우회). 상세: FINDINGS.md N-1.

## 케이스 판정

원: "가드 런타임 자체는 프로덕션 사용 가능 수준이나, spec 검증 경로가 사실상
사용 불가(F-4·F-5)이고 무경고 함정이 축적돼 있어 플랫폼 전체로는 아직 프로덕션
부적합 — spec 러너 수리와 참조 해석의 컴파일 타임 이동이 선결 조건이다."

재측정: **가드 런타임 양호 유지(3가드 × 양모드 전건 분기) + 선결 조건 2건 모두
충족**(spec 원형 3시나리오 8/8 PASS, 참조 해석 컴파일 거부) + 무경고 함정
4종(F-2·3·4·5) 제거. 잔존은 minor/info 3건과 관측기 층의 #51뿐 — **이 케이스
범위에서는 "spec 사실상 불가·플랫폼 부적합" 판정이 뒤집혔다.** 재시도 총량
8→1 (-87.5%). 케이스 횡단 종합은 r5 소관.

## DoD 자기 대조

| DoD 항목 | 증적 |
|----------|------|
| rate-notify.lnpl 원형 표현 + 가드 양방향 증적 + 전 단계 증적 | rate-notify.lnpl(워크플로 8스텝 동형 — 01-authoring.md), 04-modeA.md·05-modeB.md 양방향 대조표, evidence/00~08 전 단계 |
| spec 3시나리오 원형 실행 결과 (원 FAIL 대비 판정) | 08-spec.md — 8/8 PASS rc=0, "원 유일 FAIL 반전" 명기 |
| DELTA.md 12건 전부 판정 + 재시도 비교 + 신규 마찰 + 케이스 판정 | 이 파일 — 12행 표 + 재시도 표 + N-1 + 케이스 판정 절 |
| FINDINGS.md 원 포맷 | FINDINGS.md — Scorecard 9행/Frictions/총평/측정 순도 캐비앗 |
| qa/rerun/cases/rate-notify/ 밖 무변경 | evidence/09-no-change-proof.txt — -uall 게이트 양방향 검증 |

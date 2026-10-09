# FINDINGS — s3-batch-report

환경: 커밋 264e3442d653e5534d827687ebac5ede956e801a, lnpl 0.8.0, python 3.13.1, 드라이버 sqlite(내장, `--backend sqlite:<path>`), dev_doctor rc=1 (evidence/00-env.md — venv 부재 시점 측정값 + LLVM/mode B 갭; 이 케이스는 mode A만 씀)
조건: 블랙박스(requirements/README.md §2), impl/ 열람 0회(비의도적 노출 1건 — F-6 참조), impl/ 수정 0건 (evidence/11-purity.md)
블랙보드 게시: t3 플랫폼 관측 4건(16:50Z, `.orchestration/notes/decisions.md`) — 케이스-내부
관찰을 잘못 게시했다(선언된 인터페이스 변경·태스크 간 하중 있는 결정 전용 채널을
README §2 블랙박스 격리 위반으로 사용). 코디네이터 NOTICE로 정정, 재발 없음. 다른 케이스
오염 가능성은 t6가 정산. F-1/F-3 자체의 실행 증거(evidence/02-compile.md·03-run.md)는
이 케이스 안에서 독립 재현했으므로 그대로 유효 — 정정 대상은 게시 채널이지 발견의
신빙성이 아니다.

세션 타임라인: launch 16:30Z, round-1 impl_done 16:50Z(≈21분), 코디네이터 리뷰 rework
지시, round-2 시작 16:55Z, round-2 완료 18:0x Z대(evidence 각 파일 타임스탬프; N1 참조) —
round 1은 4시간 예산을 wall clock이 아니라 "집중 작업 시간"으로 오독해 조기 종료했다.

## Scorecard

| 단계 | 결과 | 증적 경로 | 재시도 수 |
|------|------|-----------|-----------|
| authoring | PASS | evidence/01-authoring.md | round 1: 4 라운드+6 probe+1 seed포맷; round 2: 8 라운드+6 probe+1 harness버그 |
| compile(--strict=warning) | PASS | evidence/02-compile.md | 0 (최종본 clean; 정보성 diagnostic 1개는 의도됨) |
| modeA run | PASS | evidence/03-run.md, evidence/08-rerun-oracle.md | C1/C2/C3 소규모 + 10k 전체 50가맹점 |
| spec | PASS(부분) | evidence/04-spec.md | C1/C2/C3-analog 4블록 24/24 통과; rerun 블록은 spec-runtime 버그로 7/9 FAIL(의도된 재현, F-10) |
| openapi | PASS(마찰 1건) | evidence/05-openapi.md | 최종본 clean; create-as+respond 조합은 크래시(F-6) |
| serve(실 HTTP) | FAIL(부분) | evidence/06-serve.md | GET 목록 성공, POST totals는 플랫폼 버그로 실패(F-7) |
| schedule-trigger | PASS | evidence/07-schedule-trigger.md, evidence/08-rerun-oracle.md | 소규모 + 10k 50가맹점 전량 |
| rerun-oracle | PASS | evidence/08-rerun-oracle.md | 10k 50가맹점 7필드 3반올림규칙, 0 불일치 |
| perf | PASS | evidence/09-perf.md | 1k/10k 3회, 100k 1회(600s 여유), pushdown 스위치 부재 확인 |
| backfill | FAIL(부분) | evidence/10-backfill.md | 백업/복원 성공, `lnpl migrate` 자체는 무동작 버그(F-8) |

## 요구사항 커버리지

| R | 요구 | 판정 | 근거(evidence 경로 + 실행 출력 인용) |
|---|------|------|--------------------------------------|
| R1 | 시드 10k/50가맹점/3개월/90-5-5 | 충족 | evidence/00-env.md — settled 9008/refunded 510/pending 482(±50 이내), 두 `--dump` sha256 동일 |
| R2 | daily_rollup, on schedule + lnpl trigger + schedules 스니펫 | 충족 | evidence/07-schedule-trigger.md(메커니즘, 소규모) + evidence/08-rerun-oracle.md(10k 50가맹점, 2026-07-15, 0 불일치) |
| R3 | 월간 정산 gross/fees/net/tx_count/avg/max/min, refunded·pending 제외 | 우회(의미 손실: net = gross − fees가 lnpl 밖 계산 — Money는 `set`을 전면 거부, 집계식만 예외) | evidence/03-run.md, evidence/08-rerun-oracle.md — 10k 50가맹점 7필드 0불일치(net·tier-fee 포함, glue.py 계산 후) |
| R4 | tx_count>1000이면 fees=1.5%×gross, Money 산술 | 우회(의미 손실: 등급 수수료 재계산 전체가 lnpl 밖 — Money 곱셈은 `set`에서 컴파일 거부, R3와 같은 사유) | evidence/03-run.md — C3 raw fee(sum) in-language, tier-adjusted fee(half-to-even)는 glue.py; evidence/08 — 10k 전량 동일 규칙 0불일치 |
| R5 | 멱등 재실행, 가맹점당 1행 | 충족 (메커니즘: find→delete→recreate — F-2) | evidence/08-rerun-oracle.md — 10k 50가맹점 재실행 후 6필드 0불일치 |
| R6 | 독립 파이썬 대조, 전 가맹점 전 필드, 불일치 0 | 충족 | evidence/08-rerun-oracle.md — 10k 50가맹점×7필드×3반올림규칙, half-even 매칭, 0불일치 |
| R7 | 1k/10k 성능, 선형성, 100k 시도, pushdown on/off | 충족(pushdown on/off는 스위치 부재로 비교 불가 — 근거만 기록) | evidence/09-perf.md — 1k/10k 3회 중앙값(0.074s/0.077s, 거의 flat), 100k 1회 0.14s(600s 이내 여유), 스위치 부재 확인 |
| R8 | GET /settlements/{month} 리포트 API | 불가(구조적: 두 원시 중 어느 것도 "필터+정렬desc+헤더합계"를 못 내고, 조합 시도는 플랫폼 버그 2건에 막힘) | evidence/06-serve.md, evidence/05-openapi.md — GET 목록(오름차순만, Money 정렬 불가)은 실측 성공; POST totals는 F-6/F-7로 실패 |
| R9 | currency 백필(migrate), 재개 가능성 | 우회(의미 손실: `lnpl migrate`가 다개체 모듈에서 무동작 버그로 실패 — 백업/복원은 정본대로 성공, 백필 자체는 직접 SQL로 대체 시연, no-op·중단재개는 도구가 안 되므로 의미 없음) | evidence/10-backfill.md — F-8 |
| R10 | R3·R4·R5를 소규모 시드로 spec에 표현 | 부분 | evidence/04-spec.md — C1/C2/C3-analog 24/24 통과(값 단언 포함); C3의 1001행 원본은 `stored[i]`로 실용상 불가, tier 규칙 자체는 glue.py에 있어 spec 사정권 밖; rerun 블록은 `.lnpl`상 올바르나 `lnpl spec`의 `delete` 무동작 버그(F-10)로 FAIL — 실제 `lnpl run` 동작은 evidence/08에서 이미 0불일치로 증명됨 |

**우회 비율**: 커버리지 10행 중 2행(R3, R4)이 우회(같은 근본 원인, Money 산술 제한) + 1행
(R9)이 별도 근본 원인(migrate 버그)의 우회. 6행이 충족(R1/R2/R5/R6/R7 전량, 이번 라운드에서
10k 규모로 승격), 1행이 부분(R10 — 메커니즘 충족이나 두 개의 별개 한계에 부딪힘: C3
실규모의 실용적 불가능 + spec 자체의 delete 버그), 1행이 불가(R8, 구조적+버그 이중 차단).

## Frictions

### F-1: Money 필드는 `set`이 어떤 형태로도 거부한다 — 집계식만 유일한 쓰기 경로
- 단계: authoring | 심각도: major | 축: expr
- 재현: `set report.net to report.gross - report.fees`와 `set report.net to input.net`
  둘 다 동일 메시지로 컴파일 거부. `evidence/02-compile.md` 전문 인용.
- 기대 vs 실제: s3.md R3/R4는 "Money 산술로"라고 명시. RFC-0044 §Reference-level
  Specification/1은 이를 명시적으로 좁혀 두었다 — 실측으로 산술 유무와 무관하게
  타입 자체로 거부됨을 추가 확인.
- 재시도: 2(probe) | 우회: 성공 — src/glue.py가 sqlite payload를 직접 갱신. 10k 전량
  적용 후 오라클 0불일치로 정합성 확인(evidence/08).
- 보완 제안: Money 필드를 대상으로 하는 연산자 없는 순수 복사 `set`만이라도 허용.

### F-2: 멱등 재실행에 in-language "upsert"가 없다 — find→delete→recreate를 호출자가 조립해야 한다
- 단계: rerun-oracle | 심각도: minor | 축: expr
- 재현: 동일 payload로 두 번째 호출 시 `create` 단계가 `repository create conflicts`로
  실패(F-1과 같은 근본 원인 — Money 필드는 `update`로 갱신 불가).
- 재시도: 0 | 우회: 성공, 의미 손실 없음 — 10k 50가맹점 재실행에서도 동일 패턴으로
  0불일치 확인(evidence/08).
- 보완 제안: 명시적 upsert 동사, 또는 Money 필드 한정 "재집계로 덮어쓰기" 문법.

### F-3: `input.<field>`는 그 이름을 선언한 엔티티가 모듈 안에 하나라도 있어야 한다 — 문서에 없다
- 단계: authoring | 심각도: minor | 축: doc
- 재현: `list Payment where merchant == input.merchantId` 거부; **가드**(`when
  input.bumpAmount > 0`)에서도 동일 거부 — 전역 규칙 확인.
- 재시도: 2(probe) | 우회: 성공, 의미 손실 없음(필드명을 선언된 이름에 맞춤; `monthKey`/
  `dayKey` 신설).
- 보완 제안: `references/grammar.md` "입력 네임스페이스" 절에 이 규칙 한 줄 추가.

### F-4: FINDINGS-SCHEMA의 판정 어휘 4종에 "도구 버그로 무의미해진 하위 항목"을 담을 자리가 없다
- 단계: backfill(R9) | 심각도: minor | 축: llm
- 재현: R9의 "no-op rerun"·"interrupted rerun" 하위 요구는 `lnpl migrate` 자체가 깨져
  있어 시험이 무의미하다(F-8). "불가"는 "우회도 못 함"을 뜻하고 "우회"는 R9 전체에는
  맞지만 이 두 하위 항목엔 "시험 대상 도구가 없다"는 세 번째 사실이 필요하다.
- 재시도: 0 | 우회: 성공 — 해당 하위 항목만 evidence/10-backfill.md에 "불가(도구 버그로
  시험 무의미)"로 별도 표기.
- 보완 제안: FINDINGS-SCHEMA.md 판정 어휘에 다섯 번째 값 추가(라운드 1 제안 유지).

### F-5: `expose list <Entity> by <field>`는 Money를 정렬 필드로 거부하고 `desc` 수식어가 없다
- 단계: openapi | 심각도: major | 축: expr
- 재현: `list Settlement by net` → "sort field must be Integer or DateTime ... but
  Settlement.net is base 'Money'"; `list Settlement by net desc` → "expose list needs
  list <Entity> by <field>"(desc 자체가 문법에 없음). `evidence/06-serve.md` 전문.
- 기대 vs 실제: R8은 "정렬 net 내림차순"을 요구하지만, auto-list 경로는 Money 정렬도
  desc도 둘 다 못 낸다 — 이 경로로는 R8의 핵심 요구를 원천적으로 충족 못 함.
- 재시도: 2(probe) | 우회: 실패 — Integer 필드(`txCount`)로 바꿔 메커니즘만 시연,
  요구된 정렬 자체는 우회 없이 불가로 남김.
- 보완 제안: 최소한 `desc` 수식어를 열거나, Money를 order-by 허용 타입에 추가.

### F-6: `respond`가 `create ... as` 바인딩을 참조하면 `lnpl openapi`(및 `lnpl serve`)가 크래시한다 — RFC-0030과 모순
- 단계: openapi/serve | 심각도: blocker | 축: rt
- 재현(최소): `create foo as newFoo; set newFoo.n to input.n; respond newFoo.n` →
  `lnpl openapi` → `KeyError: 'newFoo'`(`_response_schema`의 `by_binding` 조회 실패).
  `find`-바인딩(`find foo; respond foo.n`)은 동일 조건에서 정상 생성됨. `evidence/06-serve.md`
  전문. 근인(비의도적 열람 — 크래시 스택에 노출된 impl/lnpl/openapi.py:475; 의도적 Read 없음).
- 기대 vs 실제: RFC-0030 §2는 `create <명사> as <이름>`을 `find` 바인딩과 동등하게
  `set`/`format`/`respond`의 대상으로 명시한다 — 실제로는 `respond`에서 크래시하므로
  이 RFC의 문서화된 계약과 정면 모순(문서 오류가 아니라 구현 회귀).
- 재시도: 1(probe로 즉시 확정) | 우회: 성공, 의미 손실 없음 — `find`-바인딩으로 재설계.
- 보완 제안: `_response_schema`의 `by_binding` 맵에 `create ... as` 바인딩도 등록.

### F-7: `find`로 읽은 행에 `set`을 두 번 이상 쓰면 두 번째부터 "write conflict"로 실패한다 — 같은 요청 안에서 자기 자신과 충돌
- 단계: serve | 심각도: blocker | 축: rt
- 재현(최소): `find counter; set counter.a to counter.a + 1; set counter.b to counter.b + 1`
  — 첫 `set`은 성공(`counter.a=1`), 두 번째는 `write conflict: row changed since read`로
  실패. Money·집계와 무관하게 재현(정수 필드, 단일 요청). `evidence/06-serve.md` 전문.
- 기대 vs 실제: `docs/backends.md` §3의 `_version` 낙관적 동시성은 **요청 간** 충돌을
  막기 위한 설계인데, 실제로는 **같은 요청 안의 두 번째 쓰기**가 그 자신의 첫 번째
  쓰기와 충돌한다 — 바인딩의 `_version`이 in-workflow 쓰기 후 갱신되지 않는 것으로 보인다.
- 재시도: 1(probe로 즉시 확정) | 우회: 실패 — `create ... as`+집계 `set`(수차례 검증 완료,
  충돌 없음)으로 대체 가능한 경우에만 회피되고, `find`-바인딩에 여러 필드를 써야 하는
  일반적인 "레코드 일부 필드 갱신" 패턴 자체는 회피 불가.
- 보완 제안: 워크플로 실행 중 같은 바인딩에 성공적으로 `set`한 뒤에는 그 바인딩의
  in-memory `_version`을 갱신해 다음 `set`의 낙관적 잠금 검사에 반영한다.

### F-8: `lnpl migrate`가 다개체(multi-entity) 모듈에서 조용히 무동작한다 — rc=0, "성공"을 보고하지만 아무것도 쓰지 않는다
- 단계: backfill | 심각도: blocker | 축: rt
- 재현: 동일 저장소·동일 행에 대해 (a) Transaction 엔티티 하나만 선언한 파일로 마이그레이션
  → 정상 동작(`updated: 1`, 필드 기록됨); (b) `Merchant`/`DailyTotal`/`SettlementSummary`/
  `Settlement`도 함께 선언한 `src/domain.lnpl`로 마이그레이션 → `updated: 0, skipped: 10000`
  (또는 1행 재현에서도 `updated: 0`)을 rc=0으로 보고하지만 실제 payload에는 필드가
  기록되지 않는다(파일 mtime도 불변). `--dry-run`과 실행이 서로 다른 판정을 내놓는 경우도
  관측됨(마지막 재현에서는 둘 다 "이미 있음"으로 일치). `evidence/10-backfill.md` 전문.
- 기대 vs 실제: docs/migration.md는 "타입이 안 맞거나 필드·엔티티가 미선언이면 아무것도
  쓰지 않고 **거부(rc 2)**"라고만 말한다 — 조용히 rc=0으로 "이미 채워짐"을 보고하며
  아무것도 쓰지 않는 세 번째 경로는 문서에 없다. 이것이 R9의 "재개 가능성" 자체보다
  훨씬 심각한 문제다: 배포 담당자가 이 출력을 믿으면 실제로는 백필이 전혀 안 됐는데도
  마이그레이션이 끝났다고 판단한다 — 전형적인 "초록≠충족".
- 재시도: 3(단일 엔티티 격리, 실제 스키마 격리, 전체 파일 재현) | 우회: 성공(직접 SQL
  갱신, 10000/10000 검증) — 그러나 `lnpl migrate` 자체의 정합성은 회복되지 않음.
- 근인: impl/ 미열람(고의) — `cmd_migrate`를 읽으면 즉시 확정 가능하겠지만 블랙박스
  경계를 지켜 시도하지 않았다. 재현 자체가 결정적이라 판단에 지장 없음.
- 보완 제안: `lnpl migrate`의 필드-존재 검사가 다개체 스키마 컨텍스트에서 왜 달라지는지
  최우선 조사 대상.

### F-9: `set`/`respond` 대상 바인딩 이름은 camelCase — `find`의 객체(소문자-연결형)와 다른 표기
- 단계: authoring | 심각도: minor | 축: doc
- 재현: `find reportsummary`(소문자-연결형, 성공) 다음 `set reportsummary.total ...` →
  "not a declared entity"; `set reportSummary.total ...`(camelCase)로 바꾸면 성공.
  단어가 하나뿐인 엔티티(`Bookmark`, `Order`)는 두 표기가 우연히 같아 이 케이스 이전
  모든 예제에서 드러나지 않았다. `evidence/05-openapi.md` 전문.
- 재시도: 2 | 우회: 성공, 의미 손실 없음.
- 보완 제안: `naming.md`에 "바인딩을 나중에 참조할 때는 camelCase" 규칙을 명시.

### F-10: `lnpl spec`에서 `delete`가 실효과 없다 — 실행은 성공으로 보고되지만 행이 그대로 남는다
- 단계: spec | 심각도: major | 축: rt
- 재현(최소): `find thing; delete thing`을 `stored thing n 1`으로 시딩한 뒤 `expect
  completed, effects complete, rows Thing 0`를 걸면 앞의 둘은 PASS, `rows Thing 0`은
  `Thing rows=1 want=0`으로 FAIL. `evidence/04-spec.md` 전문(3회 시도로 격리).
- 기대 vs 실제: 같은 `find→delete→create` 시퀀스가 **실제** `lnpl run`에서는 100%
  정상 동작한다(evidence/08-rerun-oracle.md, 1건 + 10k 50가맹점 전량 재확인) — `lnpl
  spec`의 시뮬레이션 실행기와 `lnpl run`의 실제 인터프리터가 `delete`에 대해 서로 다른
  결과를 낸다는 뜻이다. `spec`이 "제작자가 신뢰할 계약"이라는 존재 이유(README §4 "초록
  ≠충족")에 정면으로 걸리는 사례 — 이번엔 spec 쪽이 거짓 RED를 낸다(반대 방향의 같은
  결함 계열).
- 재시도: 3(중복 필드 제거, 최소 격리) | 우회: 실패 — spec 안에서는 우회할 방법이 없다;
  대신 실제 `lnpl run` 증거로 R5/R10의 실질 판정을 대체함(evidence/08).
- 보완 제안: `lnpl spec`의 fixture 실행기가 `delete`를 실제 저장소 드라이버와 같은
  코드경로로 처리하도록 정합화.

## 케이스 판정

**Block** — driven by F-8. `lnpl migrate`가 이 도메인의 실제 스키마(다개체 모듈)에서
조용히 무동작하며 rc=0으로 성공을 보고한다: 통화 백필처럼 흔하고 되돌릴 수 없는(운영
중 데이터에 영구히 반영되는) 운영을 맡기면, 담당자는 "끝났다"는 도구의 말을 믿고 실제로는
전혀 안 된 상태로 넘어간다. qa/rerun/REPORT.md의 규칙("수용자 없는 known-issue는
Block")대로 판단하면: 이 사고 시나리오를 "받아들이겠다"고 서명할 수 있는 정산 시스템
오너는 없다 — 그래서 known-issue가 아니라 Block이다. F-6(생성 직후 응답이 서빙 계층
자체를 죽임)·F-7(레코드의 두 번째 필드 갱신이 자기 자신과 충돌)도 같은 이유로 이 판정을
지지한다: 셋 다 "Python으로 우회"가 통하지 않는 **플랫폼 자체의 결함**이고, 셋 다 이번
라운드에서 처음으로, 최소 재현으로 확정됐다(evidence/06-serve.md, evidence/10-backfill.md).
심각도는 라운드 1/2에서 매긴 값(F-6/F-7/F-8 모두 blocker) 그대로 유지한다.

이 Block 판정과 **별개로, 좁게 스코프한 사실 하나는 명확히 뒤집힌다**: 이전 10차 감사가
Block으로 판정한 "배치·집계"의 **집계 연산 자체**(`sum`/`count`/`avg`/`min`/`max`,
`list where`, `on schedule`+`lnpl trigger`, find→delete→recreate 멱등 재실행)는 이번
라운드에서 10k/50가맹점 전량, 7필드, 3반올림규칙 기준 0불일치로 증명됐다(R1/R2/R5/R6/R7,
evidence/08-rerun-oracle.md) — 소규모가 아니라 전량 근거다. t6는 이 사실을 "s3 케이스
판정 = Block"과 혼동하지 말고, "집계 프리미티브는 살아있다; 이 도메인을 막는 것은 그
위에 얹히는 파생 계산·서빙·마이그레이션의 결함이다"로 따로 기록해야 한다.

known-issue가 아니라 Block이므로 "수용 조건"은 없다 — 대신 이 판정을 뒤집기 위한 조건을
남긴다: (1) F-6/F-7/F-8 세 버그가 수리될 것. (2) Money 파생 계산(net, tier fee)은 계속
Python 파이프라인으로 유지하는 것으로 합의(이건 언어의 명시적 설계 선택이지 버그가
아니므로 F-8과 달리 "수용 가능"). (2b) glue.py 실행 전 구간에는 어떤 클라이언트도
`/settlement-service/settlement*`를 읽지 않는다는 운영 규율 — 플랫폼이 이를 강제·신호할
방법이 없다(raw-run-to-glue 노출 창, evidence/06-serve.md). (3) 재실행 로직은 "conflict
→ replace" 관용구로 표준화. (4) R8(리포트 API)은 구조적 한계(F-5, Money 정렬·desc·헤더
합계 부재)까지 겹쳐 있어 F-6/F-7 수리만으로는 완성되지 않는다 — 별도 설계가 필요하다.

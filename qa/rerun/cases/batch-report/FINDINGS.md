# FINDINGS — batch-report (재측정, #43~#50 이후)

케이스: 일별 주문 집계 리포트(집계 sum/count → DailyReport, 자정 배치 트리거,
집계 조회 엔드포인트)를 LLM-only 개발자 페르소나로 `.lnpl` 재표현 시도. 원 실측
(qa/cases/batch-report/, HEAD=713a4cb)과 동일 스펙·동일 규율, 플랫폼 무수정.
환경: HEAD=6d84bd6, python3.13 자체 venv, LLVM+SDK env(evidence/00-env-doctor.log
rc=0). 대조군(examples/shorten.lnpl) compile·run 모두 rc=0
(evidence/01-control-*.log) — 아래 실패·제약은 전부 케이스 귀속.

## Scorecard

| 단계 | 결과 | 증적 경로 | 재시도 수 (원) |
|------|------|-----------|----------------|
| authoring | PASS (부분집합 — 요구 3개 중 (c) 온전, (a)·(b) **부분**: 원 "(a) 잔여부, (b) 표현 불가"에서 개선) | evidence/03-vocab-survey-diff.md, evidence/hypothesis-log.md, batch-report.lnpl | **2** (probe-a2 수정 2회) (원 9) |
| parse | PASS | evidence/06-pipeline-compile.log | 0 (원 0) |
| lower | PASS (IR 24노드, 선언 전건 내용 일치 — evidence/06-pipeline-ir-count.log) | evidence/artifacts/final/batch-report.lir.json | 0 (원 0) |
| validate | PASS | evidence/06-pipeline-validate.log | 0 (원 0) |
| modeA | PASS (BuildReport·GetReport 각 completed; orderCount **실제 계산됨** 1→2) | evidence/06-pipeline-modeA-build.log, 06-pipeline-modeA-get.log | **0** (원 1 — F-7 해소로 소멸) |
| modeB | PASS (set/Assignment 스텝 포함 네이티브 완주) | evidence/06-pipeline-modeB.log | 0 (원 0) |
| differential | PASS (두 워크플로 모두 4/4 EQUIVALENT — Assignment 하강 등가 실측) | evidence/06-pipeline-diff.log, 06-pipeline-diff-get.log | 0 (원 0) |
| openapi | PASS (+`x-lnpl-schedules` 신규 관측) | evidence/06-pipeline-openapi.log, evidence/artifacts/final/batch-report.openapi.json | 0 (원 0) |
| spec | PASS (7 passed, 0 failed — 정상 1·에러 1·경계 1, 블록 3=케이스 3 독립 실행) | evidence/07-spec-validate.log, evidence/artifacts/final/batch-report.spec.json | **1** (stored 시드 누락 — 문서에 규칙 있어 1회 수렴) (원 2) |

판정 규칙: 원과 동일 — PASS/FAIL은 대조군 비교, 요구 수준의 표현 가능성은
Frictions가 정본. Scorecard의 PASS는 "표현 가능한 부분집합이 파이프라인을
통과했다"는 뜻이지 요구 충족이 아니다. 원 F-n 번호를 유지하고 재측정 판정
(해소/부분/잔존)을 병기한다. 원 대비 델타 전건 판정은 DELTA.md가 정본.

## Frictions — 원 8건 재검

### F-1: 집계 — **부분** (파생값 절반은 열림, 행 집합 집계는 잔존)
- 단계: authoring · 원 심각도: **blocker** → 재측정: **major(부분)**
- 잔존 실측(HEAD=6d84bd6, 워크트리 루트, `.venv` 준비 후):
  1. `grep -ci "\bsum\b\|\bcount\b\|\baggregate\b" plugins/lnpl/skills/lnpl-authoring/references/{verbs,grammar,declarations}.md` → 전부 0 (03-vocab-survey-diff.md)
  2. 원 probe-a1 그대로 compile → rc=0 + `unknown-verb` 2건(sum·count) — 원과 동일 (04-probe-a1-compile.log)
  3. repeat+set 누적(probe-a3) → read order 3회 전부 같은 시드 행, N행 합산 불가 (04-probe-a3-modeA.log)
- 해소 실측(파생값 기록 — RFC-0015 `set`):
  4. `set report.orderCount to report.orderCount + 1` → IR `Assignment`(target/expression 내용 일치), mode A에서 orderCount 1→**2** 실제 계산 (04-probe-a2-ir.log, 04-probe-a2-modeA.log)
- 경계: **Money 산술 불가** — `set report.totalAmount to report.totalAmount + order.amount`가 rc=2, "declared type Money is neither Integer nor DateTime — RFC-0016 computes over whole numbers and instants only". 제품 요구(금액 합산)는 Integer 강등(스펙 이탈) 없이는 파생값으로도 불가 (04-probe-a2-compile.log 시도 2). 최종본 totalAmount는 시드 `"0"` 고정 (06-pipeline-modeA-build.log).
- 로드맵: RFC-0015 §Alternatives에 "넣지 않는 이유+후속 이슈 제안" 기록 존재(rfcs/0015-value-semantics.md:322). 단 authoring 문서 라우팅(references 5종+SKILL+kb)에서 그리로 가는 포인터 **0건**(우연 일치 1건뿐) — LLM-only 개발자는 발견 불가 (03-vocab-survey-diff.md §D12).
- 우회: Integer 필드 한정 파생값만. 행 집합 집계는 여전히 언어 밖.

### F-2: 배치 트리거 — **부분** (선언·메타데이터 도달, 실행기 부재)
- 단계: authoring · 원 심각도: **blocker** → 재측정: **major(부분)**
- 해소 실측: `event DailyRollup on schedule daily at 00:00 UTC`(grammar.md:80-84 신규)가
  1. parse: rc=0 + `declared-not-enforced [event.daily.rollup]` 경고 (05-probe-b1-compile.log)
  2. IR: `{"kind":"Event","source":{"every":"daily","at":"00:00","zone":"UTC"}}` 내용 일치 (05-probe-b1-ir.log)
  3. OpenAPI: `x-lnpl-schedules: [{event, every, at, zone, "enforcement":"unenforced"}]` (05-probe-b1-openapi.log)
- 잔존: 실행기 없음 — "no scheduler runs it ... issue #26 (the serving layer) owns the executor"(declarations.md:34). UNENFORCED가 진단·문서·산출물 3채널에 정직하게 명시되나, **스케줄 실행은 여전히 외부 시스템 몫**. 중복실행 방지(overlap/singleton/once)·재실행 멱등(idempotent 선언) 어휘 0 hits 불변 (03-vocab-survey-diff.md).
- 원 b2 재현: `unknown policy 'schedule' (allowed: retry, rollback, timeout, parallel)` rc=2 — 불변 (05-probe-b2-compile.log).

### F-3: 조용한 무동작 실패 — **해소** (--strict 게이트 신설, 양방향 검증)
- 단계: parse/modeA · 원 심각도: **major** → 재측정: **해소**
- 실측: probe-a1(unknown-verb 2건) 기본 compile rc=0(원과 동일) / `--strict` **rc=2** / `run --json --strict` **rc=2** (08-strict-off/on/run.log). 오탐 방향: 진단 0인 probe-clean.lnpl `--strict` **rc=0** (08-strict-clean.log) — 게이트가 clean/warned를 실제 구분.
- 남는 그늘: 기본값은 여전히 rc=0+stderr(원 함정 그대로) — 게이트는 opt-in이며, N-4(진단 등급 부재)로 신기능과 충돌. F-8·N-4 참조.

### F-4: 다단어 엔티티 참조 — **해소**
- 단계: parse(authoring) · 원 심각도: **major** → 재측정: **해소**
- 실측: `entity DailyReport` + `create DailyReport` → rc=0, IR RepositoryCall `entity: "entity.daily.report"` 내용 일치 (08-probe-c1-compile.log). 원 rc=2+오도 에러 소멸. 재시도 0회(원 4회).

### F-5: spec 복수 케이스 병합 — **해소** (독립 실행 + 원 재현 시끄러운 거부)
- 단계: spec · 원 심각도: **major** → 재측정: **해소**
- 실측: ① 지원 경로 — 워크플로당 spec 블록 여러 개 = 블록마다 독립 케이스(references/spec.md, issue #46). 최종본 블록 3개 → manifest 케이스 3개, `--run` 7 passed 0 failed (07-spec-validate.log). 원 우회(경계 전용 CheckOrder 워크플로) 제거됨. ② 원 재현(한 블록 2 triplet, probe-d1) → **rc=2** "a second `given` inside one spec block — open a new `spec` block per scenario" — 무경고 병합이 파싱 거부+교정 지시로 (07-probe-d1-compile.log).

### F-6: 복수형 객체 명사 — **해소**
- 단계: parse(authoring) · 원 심각도: minor → 재측정: **해소**
- 실측: `load orders`(entity Order) → rc=0, IR `entity: "entity.order"` (08-probe-c2-compile.log).

### F-7: --workflow id 미문서·후보 없음 — **해소**
- 단계: modeA · 원 심각도: minor → 재측정: **해소**
- 실측: `run --workflow GetReport` → rc=2, `--workflow 'GetReport' is not a workflow of ... (valid: wf.build.report, wf.get.report)` — 경계 검증+전 후보 제시. IR grep 불요 (06-pipeline-wfname.log). 재시도 0회(원 1회).

### F-8: 진단 게이트 채널 부재 — **부분** (exit 채널 신설, 등급 부재)
- 단계: parse · 원 심각도: info → 재측정: **부분**
- 해소 실측: `--strict` = "exit 2 if any diagnostic is reported"(compile·run --help) — 경고가 종료 코드 채널을 얻음 (08-diag-channel.log).
- 잔존: ① 공식 예제는 여전히 경고 설계(shorten이 declared-not-enforced 등 방출 — 08-strict-clean.log 상단) — "경고 0" 게이트는 여전히 프로젝트 규약 문제. ② 구조화(JSON) 진단 스트림 없음 — stderr 텍스트뿐. ③ 진단 등급 부재 → N-4.

## Frictions — 신규 (N-n)

### N-1: repeat 아래 들여쓴 다중 스텝이 무진단으로 쪼개진다
- 단계: parse/lower · 심각도: **major**
- 재현: probe-a3 — `repeat 3` 아래 스텝 2개(read order, set 누적) 들여쓰기 → rc=0 무진단, IR에서 repeat Guard의 children이 **첫 스텝뿐**, set은 워크플로 직속 형제로 이동 (04-probe-a3-ir.log). mode A: read 3회·set 1회 (04-probe-a3-modeA.log).
- 기대: 블록 전체 반복 또는 "두 번째 스텝은 반복 밖" 진단. 실제: 조용히 분리 — 저자는 누적 루프를 썼다고 믿는다. 가드 스코프 규칙("바로 다음 항목 하나", grammar.md)이 repeat에도 적용되는 것으로 보이나 문서는 가드 절만 언급, repeat 들여쓰기 함정은 미기술.
- silent 함정 계보(원 F-3/F-5)와 동형: 파싱 성공 + 의도 증발.

### N-2: `set`의 대상 바인딩 규칙이 미문서 + 진단이 오도
- 단계: authoring · 심각도: minor
- 재현: `create report` 후 `set report.orderCount to ...` → rc=2, "guard condition 'set report.orderCount to ...' reads entity.report, but this workflow never **reads** it" (04-probe-a2-compile.log 시도 1).
- 마찰 2겹: ① set 대상은 read/load 계열 바인딩만 — create 바인딩 불가 규칙이 references(verbs/grammar/declarations) 어디에도 없음. ② 진단이 set 스텝을 "guard condition"이라 지칭 — set은 가드가 아니며, 원 F-4의 "에러 지시가 오도" 유형의 잔재. 거부 자체는 시끄러움(rc=2)이라 minor.

### N-3: workflow 본문의 `policy` 절이 이후 스텝까지 통째로 무음 증발
- 단계: parse · 심각도: **major**
- 재현(최소화 완료): workflow 본문에 `policy` + `retry 2`(허용 이름) + `read report` → rc=0 **무진단**, IR의 Workflow가 children 없이 텅 빔 — policy 블록과 **이후 read report 스텝까지** 소실 (05-probe-b2b-compile.log). 미허용 이름(schedule) 여부와 무관(허용 이름으로 재현됨).
- 대조: 같은 policy를 service 블록에 두면 미허용 이름이 rc=2로 시끄럽게 거부됨(F-2 재검의 b2). 위치 위반은 거부가 아니라 증발 — 빈 워크플로가 초록으로 완주한다.

### N-4: `--strict`에 진단 등급이 없어 신기능(스케줄 선언)과 상호 배타
- 단계: parse/CI · 심각도: **major**
- 재현: 정당한 `on schedule` 선언(probe-b1)이 declared-not-enforced 경고를 내므로 `--strict` **rc=2** (08-diag-channel.log 말미). 최종본 batch-report.lnpl도 동일(의도 경고 2건).
- 결과: #49의 스케줄 선언을 쓰는 파일은 #43의 --strict 게이트를 켤 수 없다 — 오타 no-op(unknown-verb)과 의도된 문서화 선언(unenforced)을 게이트가 구분 못함. F-3 해소의 실효를 절반으로 줄이는 설계 공백.

## 총평

원 8마찰 중 **5건 해소(F-3·F-4·F-5·F-6·F-7), 2건 부분(F-1·F-2), 1건 부분(F-8)** —
authoring 재시도가 9회→2회로, silent 함정 2종(동사 no-op 탐지 불가·spec 병합)이
게이트·파싱 거부로 닫혔다. 케이스의 본론이던 두 blocker는 정직하게 절반만 열렸다:
(a) 집계는 `set`+이항 산술로 "파생값 기록"이 실제 계산되나(orderCount 1→2 실측)
**Integer·DateTime 한정**이라 제품 요구인 금액(Money) 합산은 스펙 이탈 없이 불가하고,
행 집합 집계(sum/count)는 어휘·실행 모형 양쪽에서 잔존 — 로드맵은 RFC에 있으나
authoring 라우팅에서 발견 불가. (b) 스케줄은 선언→IR→OpenAPI까지 도달하고
UNENFORCED가 3채널에 명시되나 실행기는 없다(issue #26) — "매일 자정 실행"은 여전히
외부 시스템 몫. 신규 마찰 4건 중 major 3건이 전부 silent 계보(N-1 repeat 분리,
N-3 policy 증발)거나 게이트 실효 공백(N-4 등급 부재)이라, 원 총평의 "실패의 형태"
문제는 종류를 바꿔 살아 있다. **프로덕션 판정: 배치·집계 워크로드는 여전히 사용
불가(부분 개선 — 파생값·선언 메타데이터까지); 요청-응답 서비스 한정 조건부 사용의
조건은 개선됨** — CI 게이트가 stderr grep에서 `--strict`로 승격됐고 엔티티명
단일 단어 규약이 불필요해졌으나, 스케줄 선언을 쓰는 순간 `--strict`를 잃는다(N-4).
자동화 후보 갭: 진단 등급(오타성 vs 의도 선언) 도입 후 `--strict`의 선택적 통과,
repeat 블록 들여쓰기 진단, workflow 내 policy 위치 오류의 명시 거부, authoring
references에서 RFC 로드맵으로의 포인터.

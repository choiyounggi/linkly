# FINDINGS — batch-report

케이스: 일별 주문 집계 리포트(집계 sum/count → DailyReport, 자정 배치 트리거,
집계 조회 엔드포인트)를 LLM-only 개발자 페르소나로 `.lnpl` 표현 시도.
환경: HEAD=713a4cb, python3.13 자체 venv, LLVM+SDK env. 대조군(examples/shorten.lnpl)
전 단계 PASS(evidence/02-control-pipeline.md) — 아래 실패·제약은 전부 케이스 귀속.

## Scorecard

| 단계 | 결과 | 증적 경로 | 재시도 수 |
|------|------|-----------|-----------|
| authoring | PASS (부분집합 — 요구 3개 중 (c)만 온전, (a) 잔여부, (b) 표현 불가) | evidence/03-vocab-survey.md, evidence/hypothesis-log.md, batch-report.lnpl | 9 (프로브 a 공통 4 + a3 3 + spec 2) |
| parse | PASS | evidence/06-pipeline-compile.log | 0 (최종본 기준) |
| lower | PASS (compile이 parse+lower 일체 수행, IR 생성) | evidence/06-pipeline-compile.log, evidence/artifacts/final/batch-report.lir.json | 0 |
| validate | PASS | evidence/06-pipeline-validate.log | 0 |
| modeA | PASS (BuildReport·GetReport 각 completed) | evidence/06-pipeline-modeA-build.log, 06-pipeline-modeA-get.log | 1 (워크플로 id 표기 — F-7) |
| modeB | PASS | evidence/06-pipeline-modeB.log | 0 |
| differential | PASS (두 워크플로 모두 4/4 EQUIVALENT) | evidence/06-pipeline-diff.log, 06-pipeline-diff-get.log | 0 |
| openapi | PASS | evidence/06-pipeline-openapi.log, evidence/artifacts/final/batch-report.openapi.json | 0 |
| spec | PASS (7 passed, 0 failed — 정상 1·에러 1·경계 1) | evidence/07-spec-validate.log, evidence/artifacts/final/batch-report.spec.json | 2 (복수 케이스 병합 — F-5) |

판정 규칙: PASS/FAIL은 대조군 비교(evidence/02-control-pipeline.md), N/A(env) 해당
없음. 요구 수준의 표현 가능성은 Frictions가 정본이다 — Scorecard의 PASS는 "표현
가능한 부분집합이 파이프라인을 통과했다"는 뜻이지 요구 충족이 아니다.

## Frictions

### F-1: 집계(sum/count → 파생값)가 어휘·문법 양쪽에서 표현 불가
- 단계: authoring · 심각도: **blocker**
- 재현(HEAD=713a4cb, 워크트리 루트, `.venv` 준비 후):
  1. `grep -ci "\bsum\b\|\bcount\b\|\baggregate\b" plugins/lnpl/skills/lnpl-authoring/references/{verbs,grammar,declarations}.md` → 전부 0
  2. `.venv/bin/lnpl compile qa/cases/batch-report/probes/probe-a1.lnpl -o /dev/null` → `unknown-verb` 2건, exit 0
  3. `.venv/bin/lnpl run qa/cases/batch-report/probes/probe-a2.lnpl --json` → Report 행 생성되나 orderCount/totalAmount가 types.md 예시값(1, "0") 그대로
- 기대: 주문 3건(100/250/50)에서 count=3·sum=400인 DailyReport (케이스 요구 (a))
- 실제: 집계 동사 부재(VERB_LEXICON 16개 전부 I/O 계열), 산술·대입·파생값 문법 부재
  (grammar.md 리터럴: 비교 연산자 4개와 기간 단위뿐), repeat 3회도 같은 시드값만 기록.
  공식 예제 checkout.lnpl조차 total 필드를 "서술(계산 안 됨)"로 자인.
- 재시도: 프로브 3종·7회 시도로 수렴(H-a1~a3 전부 confirmed, evidence/hypothesis-log.md)
- 우회: 없음(.lnpl 안에서 불가). 부분집합(읽기+행 생성)만 표현 — batch-report.lnpl 주석 참조.

### F-2: 배치 트리거(스케줄·중복실행·멱등)가 표현 불가
- 단계: authoring · 심각도: **blocker**
- 재현:
  1. `grep -ci "\bschedule\b\|\bcron\b\|\bdaily\b" plugins/lnpl/skills/lnpl-authoring/references/{verbs,grammar,declarations}.md` → 전부 0
  2. `.venv/bin/lnpl compile qa/cases/batch-report/probes/probe-b1.lnpl -o /dev/null` → `unknown-verb [schedule]`, exit 0; mode A에서 해당 스텝 `"effects": []`
  3. `.venv/bin/lnpl compile qa/cases/batch-report/probes/probe-b2.lnpl -o /dev/null` → `unknown policy 'schedule' (allowed: retry, rollback, timeout, parallel)`, exit 2
- 기대: "매일 자정 실행" 상당의 트리거 선언 (케이스 요구 (b))
- 실제: 시간 트리거 어휘가 동사·선언·제어 어휘 어디에도 없음. `event`는 엔티티
  생명주기 훅뿐. 중복실행 방지(b2)·재실행 멱등(b3)도 어휘 0 hits로 연쇄 N/A(blocked).
  `performance batch`는 이름만 존재하고 unenforced(집행 매트릭스 명시, H-b3).
- 재시도: 프로브 3종 각 1회로 판정(H-b1~b3 confirmed)
- 우회: 없음(.lnpl 안에서 불가). 스케줄링은 외부 시스템 몫이 됨 — 언어 경계 밖.

### F-3: "파싱 성공 + 런타임 무동작" 실패 모드가 조용하다 (exit 0 + stderr 전용 진단)
- 단계: parse/modeA · 심각도: **major**
- 재현:
  1. `.venv/bin/lnpl compile qa/cases/batch-report/probes/probe-a1.lnpl -o /dev/null; echo $?` → stderr에 `unknown-verb` 2건, **exit 0**
  2. `.venv/bin/lnpl run qa/cases/batch-report/probes/probe-a1.lnpl --json` → `sum`/`count` 스텝 `"effects": []`인 채 status=completed
- 기대: 의도가 증발한 실행이 실패로 표면화되거나 최소한 종료 코드로 구분 가능
- 실제: 워크플로는 "성공한 척" 완주. 진단은 stderr 전용이라 안 읽으면 사라짐.
  단, 진단 메시지 자체는 상급(코드·위치·기제 서술: "derives no Effect and runs as a
  descriptive no-op")이고 스킬 문서가 함정을 반복 경고 — 문서 라우팅을 따르는 한 탐지
  가능, 따르지 않으면 무방비. F-1·F-2의 위험 증폭기.
- 재시도: 해당 없음(관찰 소견) · 우회: CI에서 stderr의 진단 코드 grep(플랫폼 밖 우회)

### F-4: 다단어 엔티티명은 스텝 객체로 참조 불가 + 에러 지시가 오도함
- 단계: parse(authoring) · 심각도: **major**
- 재현:
  1. probe-a1.lnpl의 엔티티를 `DailyReport`로, 스텝을 `create dailyReport`로 작성 → `does not say which entity it means ... Name the entity as the step's object`, exit 2
  2. 에러 지시대로 `create DailyReport`(정확 표기)로 수정 → **같은 에러 반복**
  3. 엔티티를 `Report`(단일 단어)로 리네임 → 통과 (evidence/04-probe-a1-compile.log 이력)
- 기대: 정확한 엔티티명 참조는 해석되거나, 안 되는 이유·규칙이 문서/에러에 명시
- 실제: 다단어/camelCase 엔티티는 객체로 해석 불가. references 5종·examples 어디에도
  참조 규칙 없음(공식 예제는 전부 단일 단어 엔티티). 에러 지시를 따라도 실패.
- 재시도: 4회(공통 authoring 재시도의 주 원인) · 우회: 엔티티명 단일 단어 강제(성공)

### F-5: spec 블록의 복수 케이스가 한 케이스로 조용히 병합됨
- 단계: spec · 심각도: **major**
- 재현:
  1. 한 spec 블록에 given/when/expect 2벌(정상+경계) 작성 → 컴파일 무경고
  2. `.venv/bin/lnpl spec <파일> --run` → 정상 케이스 4 FAIL(steps=1 want=4 등)
  3. `.venv/bin/lnpl spec <파일> -o out.json` → manifest에 케이스 1개: given[valid order, no amount], expect[completed,…,failed] — 자기모순 병합 실측
- 기대: 케이스 2개로 각각 실행되거나, 미지원이면 파싱 단계에서 거부
- 실제: 무경고 병합 → `no amount`가 정상 케이스에도 적용돼 1스텝에서 실패.
  silent 함정 3호(동사 no-op, batch unenforced에 이어).
- 재시도: 2회 · 우회: 워크플로당 1케이스 + 경계 전용 워크플로(CheckOrder) 추가(성공)

### F-6: 복수형 객체 명사가 엔티티로 해석되지 않음
- 단계: parse(authoring) · 심각도: minor
- 재현: `load orders`(entity Order) → `does not say which entity it means`, exit 2
- 기대: 복수형 해석 또는 "did you mean order" 힌트 / 실제: 단수형 강제, 힌트 없음
- 재시도: 1회 · 우회: 단수형 표기(성공)

### F-7: `--workflow`가 미문서 IR 노드 id를 요구하고 에러에 후보 목록이 없음
- 단계: modeA · 심각도: minor
- 재현: `.venv/bin/lnpl run <파일> --workflow GetReport` → `runtime error: no such workflow: 'GetReport'`, exit 3
- 기대: 워크플로 이름 해석 또는 에러에 사용 가능 id 목록 / 실제: IR JSON을 grep해야
  `wf.get.report`(camelCase→점 표기 소문자 변환, 미문서) 발견
- 재시도: 1회 · 우회: IR에서 id 추출(성공)

### F-8: 진단 게이트 부재 — 경고를 기계적으로 잡을 종료 코드 채널이 없음
- 단계: parse · 심각도: info
- 내용: 커밋된 공식 예제 셋 다 경고를 내는 설계(lnpl-verify SKILL 명시)라 "경고 0"을
  게이트로 쓸 수 없고, exit 0이라 종료 코드 게이트도 불가 — CI는 stderr의 진단 코드
  목록(`unknown-verb` 등 4종)을 직접 파싱해야 함. F-3의 시스템적 배경.

## 총평

요청-응답 워크로드((c) 조회)는 공식 예제 동형으로 파이프라인 9단계를 전부 통과했지만,
이 케이스의 본론인 집계(F-1)와 배치 트리거(F-2)는 어휘·문법 수준에서 표현 불가였고
언어 안에 우회가 없다 — lnpl 0.2.0의 표현 범위는 사실상 "검증·CRUD·캐시·이벤트 발행을
갖춘 요청-응답 서비스"로 닫혀 있다. 더 위험한 것은 실패의 형태로, 선언부는 허용 목록을
제시하며 시끄럽게 거부하는 반면 스텝 동사와 spec 케이스는 그럴듯한 표기가 조용히
무동작·병합으로 증발해(F-3, F-5, 진단은 stderr+exit 0) 문서 라우팅을 건너뛴 LLM-only
개발자는 초록 파이프라인을 보고 배치 리포트가 돌아간다고 믿게 된다. 진단 메시지 품질
자체는 상급이고 문서가 함정을 정직하게 공개하는 점은 강점이나, 에러 지시가 오도하는
지점(F-4)과 미문서 규칙(엔티티 참조·워크플로 id)이 authoring 재시도를 9회로 불렸다.
**프로덕션 판정: 배치·집계 워크로드에는 사용 불가(blocker 2건); 요청-응답 서비스
한정으로는 조건부 사용 가능 — CI에 stderr 진단 코드 게이트를 붙이고 엔티티명 단일 단어
규약을 지킨다는 조건에서.** 자동화 후보 갭: 진단 코드의 exit/JSON 노출(`--strict` 상당),
spec 복수 케이스 거부 회귀 테스트, 다단어 엔티티 참조 규칙의 문서화 또는 지원.

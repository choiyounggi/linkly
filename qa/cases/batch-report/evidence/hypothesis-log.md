# 가설 로그 — batch-report 프로브

규율(D3, wiki: debugging-methodology-hypothesis-testing): 가설은 "구문 X가 요구 Y를
커버한다 — 근거: references 행"으로 명문화, 예측은 반증 가능하게, 실험당 변수 1개
(프로브 파일당 구문 1개 변주), 결과는 confirmed/falsified/inconclusive.
판별 절차(D4): compile stderr 진단 → IR grep → mode A 관찰 결과 순.

## (a) 집계 — sum/count → DailyReport

### H-a1 — 그럴듯한 집계 동사는 no-op이다
- 가설: `sum orders` / `count orders` 류 스텝은 VERB_LEXICON(verbs.md 표) 밖이므로
  파싱은 성공하고 Effect 없는 no-op으로 실행된다.
- 근거: verbs.md "아래 표에 없는 동사는 에러가 아니라 효과 없는 no-op" + 조사 0 hits.
- 예측(반증 가능): `lnpl compile` exit 0 + stderr에 `unknown-verb` 2건, IR의 해당
  스텝에 Effect 노드 없음, mode A는 status=completed로 "성공한 척" 완주.
- 프로브: probes/probe-a1.lnpl
- 결과: **confirmed** (예측 그대로). compile exit 0 + `unknown-verb` 2건
  ("derives no Effect and runs as a descriptive no-op"), mode A에서 `sum order.amount`·
  `count order` 스텝의 `"effects": []`, status=completed로 완주 — 집계는 전혀 일어나지
  않는데 성공으로 보고됨. 증적: 04-probe-a1-compile.log, 04-probe-a1-modeA.log.
  authoring 재시도 4회(아래 공통 마찰 참조).

### H-a2 — 어휘 내 동사만으로는 엔티티 생성까지만 되고 파생값 계산은 안 된다
- 가설: `load orders` + `create dailyReport`는 전부 표 안 동사라 클린 컴파일되지만,
  DailyReport의 totalAmount/orderCount 필드에 주문 합산값(400/3)이 채워질 방법이 없다.
- 근거: verbs.md의 16개 동사 전부 Effect가 I/O 계열(계산 Effect 부재) +
  checkout.lnpl 헤더가 total 필드를 "서술"로 자인.
- 예측: 컴파일 클린(진단 0~경고만), mode A --json 결과에서 DailyReport 행은
  생성되나 필드 값이 주문 합산(sum=400, count=3)과 무관.
- 프로브: probes/probe-a2.lnpl
- 결과: **confirmed**. 컴파일 클린(경고 0), Report 행은 생성되나 필드 값이 전부
  types.md의 타입 예시값 시드 그대로: id=UUID 예시(3f2504e0-…), orderCount=Integer
  예시(1), totalAmount=Money 예시(amount "0"), reportDate=DateTime 예시
  (2026-07-31T09:00:00Z). 주문 데이터에서 파생된 값이 아님 — 파생값을 채울 문법 부재.
  부기: bindings가 단일 네임스페이스로 Order·Report 필드를 한 레코드에 병합(놀람).
  증적: 04-probe-a2-compile.log, 04-probe-a2-modeA.log.

### H-a3 — repeat/until 제어 어휘로도 누적 계산은 표현되지 않는다
- 가설: `repeat`/`until`(grammar.md 제어 어휘)로 주문 순회를 흉내 내도 누적
  변수/산술 표현이 문법에 없어 합산이 표현되지 않는다.
- 근거: grammar.md 리터럴 절 — 비교 연산자 4개(<= >= < >)와 기간 단위만 존재,
  산술 연산자·대입·변수 선언 부재(해당 절에 0 언급).
- 예측: `repeat` 블록은 파싱되더라도 합산 의미가 IR에 없거나, 형태에 따라 파스 에러.
- 프로브: probes/probe-a3.lnpl
- 결과: **confirmed** (3회 시도로 수렴). 시도1: `repeat`는 count 필수("repeat needs a
  count" — until만으로는 안 됨). 시도2: until 가드는 워크플로가 read한 엔티티 바인딩만
  참조 가능("no binding can ever exist, so the guard would be false forever" — 정적
  데이터플로 검사, 메시지 상급). 시도3: `repeat 3` + `update report`는 컴파일·실행되나
  update 3회가 같은 시드값을 반복 기록 — 반복은 표현되고 누적은 표현 불가(산술·대입
  어휘 부재, grammar.md 리터럴 절에 비교 연산자 4개와 기간 단위만).
  증적: 04-probe-a3-compile.log(각 시도), 04-probe-a3-modeA.log.

## (b) 배치 트리거 — b1 스케줄 / b2 중복실행 / b3 멱등

### H-b1 — 그럴듯한 스케줄 스텝은 no-op이다
- 가설: `schedule daily report` 스텝은 VERB_LEXICON 밖 → unknown-verb no-op.
- 근거: 03-vocab-survey (schedule/daily/cron … 0 hits).
- 예측: compile exit 0 + `unknown-verb [schedule]`, IR에 Effect 없음, mode A 완주.
- 프로브: probes/probe-b1.lnpl
- 결과: **confirmed** (1회). compile exit 0 + `unknown-verb [line 16] schedule`
  ("descriptive no-op"), mode A에서 해당 스텝 `"effects": []`, status=completed.
  "매일 자정 실행"이라는 의도가 통째로 증발하는데 파이프라인은 초록.
  증적: 05-probe-b1-compile.log, 05-probe-b1-modeA.log.

### H-b2 — policy 절의 미허용 이름은 (no-op이 아니라) 명시적으로 거부된다
- 가설: `policy schedule daily` 같은 미허용 절 이름은 닫힌 목록(retry/rollback/
  timeout/parallel) 위반으로 컴파일 단계에서 거부된다 — 동사와 달리 선언은 시끄럽게
  실패하는지 측정.
- 근거: declarations.md "절별 허용 이름" — policy 4개 닫힌 목록.
- 예측: compile이 에러(exit≠0 또는 error 진단)를 낸다. 만약 조용히 통과하면
  선언부에도 silent 함정이 있다는 뜻 — 어느 쪽이든 측정 가치.
- 프로브: probes/probe-b2.lnpl
- 결과: **confirmed** (1회). `compile error: line 16: unknown policy 'schedule'
  (allowed: retry, rollback, timeout, parallel)` exit 2 — 선언부는 허용 목록까지
  제시하며 시끄럽게 거부. 동사부(no-op)와 선언부(명시 거부)의 실패 모드 비대칭이
  실측으로 확정됨. 증적: 05-probe-b2-compile.log.

### H-b3 — `performance batch`는 파싱되고 무시되며, 진단이 그 사실을 알려주는가
- 가설: `performance batch`는 허용 이름이라 파싱되지만 unenforced로 무시된다.
  진단(`declared-not-enforced`)이 그 사실을 stderr에 노출하는지가 측정 핵심 —
  노출되면 "문서화된 함정", 안 되면 "무경고 함정".
- 근거: declarations.md:33 "performance batch | unenforced | parsed, but the
  execution plan never reads it".
- 예측: compile exit 0, stderr에 batch 관련 declared-not-enforced 진단 1건.
- 프로브: probes/probe-b3.lnpl
- 결과: **confirmed** (1회). compile exit 0 + `declared-not-enforced [perf.report]
  performance batch — declared but unenforced: parsed, but the execution plan never
  reads it`. 이름이 존재하는 "batch"는 파싱되고 무시되지만, 진단이 그 사실을 기제까지
  설명하며 공개 — "문서화된 함정"으로 판정(무경고 함정 아님). 단 stderr+exit 0이라
  진단을 안 읽으면(F-후보 #1) 함정이 복원됨. 증적: 05-probe-b3-compile.log,
  05-probe-b3-modeA.log.

### b2(중복실행)·b3(멱등) 어휘 판정 — 확정
- b1 결과: 스케줄 표현 불가(H-b1 no-op + H-b2 정책 거부로 이중 확인). 따라서: overlap/singleton/once 0 hits,
  idempotent/unique/upsert 0 hits(03-vocab-survey)를 근거로 **N/A(blocked,
  어휘 부재)** — 프로브 없이 종결(wiki: testing-quality-checks-that-cannot-pass,
  부재의 연쇄를 FAIL 다건으로 부풀리지 않음). **적용 완료** — b2/b3는 N/A(blocked).

## (c) 조회 — 사전 판정: 표현 가능
- 근거: verbs.md의 load/find/read(RepositoryCall read) + 공식 예제 동형 패턴.
- Task 05에서 batch-report.lnpl 조립으로 실측.

## (a) 공통 — 예정 밖 발견 (authoring 마찰, F-후보)

- **F-후보 #2 (major)**: 스텝 객체 해석이 다단어/camelCase 엔티티명을 못 푼다.
  `create dailyReport`(retry2) → 실패, 에러 지시대로 정확 표기 `create DailyReport`
  (retry3) → **같은 에러 반복**("does not say which entity it means ... Name the
  entity as the step's object" — 지시를 따라도 실패하는 오도성 메시지). 단일 단어
  엔티티(Report)로 리네임(retry4)해야 통과. 문서(references 5종·examples)에 엔티티
  참조 규칙 무설명. 우회: 엔티티명을 단일 단어로 강제.
- **F-후보 #3 (minor)**: 복수형 객체(`load orders`)가 `Order`로 해석되지 않음
  (retry1→2). "did you mean" 부재. 에러 메시지는 위치·원인 제시 — 품질 자체는 양호.
- 진단 품질 총평(compile 에러): 위치(line)·원인·수정 방향을 모두 서술 — 상급.
  단 F-후보 #2의 경우 수정 방향이 실제로는 작동하지 않는 오도성.

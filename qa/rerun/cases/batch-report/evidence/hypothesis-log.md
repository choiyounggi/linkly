# hypothesis-log — r3-batch-report 재측정 세션 로그

형식(D1, wiki: qa-exploratory-exploratory-sessions): 차터 → 가설 H-r* → 시도·rc·판정.
재시도 정의: 같은 목표의 `.lnpl` 수정-재컴파일 1회 = 재시도 1회(원 케이스와 동일 집계 규칙).

## 차터 1 (Task 03): 집계 표현
`Explore 집계 표현을 with 갱신된 어휘 표(set·이항 산술·Assignment effect) to discover
F-1이 어디까지 부분 해소됐는지와 그 경계`

### H-ra1: sum/count 동사는 여전히 unknown-verb no-op인가 → **confirmed (잔존)**
- 시도 1: 원 probe-a1 그대로 복사·컴파일 → rc=0, `unknown-verb` 2건(sum, count) —
  원 실측과 동일. (04-probe-a1-compile.log)

### H-ra2: `set`+이항 산술로 파생값 기록이 표현되는가 → **부분 confirmed**
- 시도 1: `create report` 후 `set report.orderCount to ...` → **rc=2**:
  "guard condition 'set ...' reads entity.report, but this workflow never reads it".
  발견 2건: ① `set` 대상 바인딩은 read/load 계열만 — `create` 바인딩 불가(문서
  references에 이 규칙 명시 없음), ② 진단이 set 스텝을 "guard condition"이라 부름
  (오도 — set은 가드가 아님). → 신규 마찰 후보 N-2. (04-probe-a2-compile.log 시도 1)
- 시도 2: `read report`로 변경 → **rc=2**: "report.totalAmount, whose declared type
  Money is neither Integer nor DateTime — RFC-0016 computes over whole numbers and
  instants only". **Money 산술 자체가 불가** — 제품 스펙(금액 합산)은 파생값으로도
  막힘. 진단 품질은 상급(타입·근거 RFC·경계 서술). → F-1 부분 판정의 경계 증거.
  (04-probe-a2-compile.log 시도 2)
- 시도 3: amount/totalAmount를 Integer로 강등(스펙 이탈 우회) → **rc=0**,
  IR Assignment 2건 내용 일치(04-probe-a2-ir.log), mode A에서
  orderCount 1→2, totalAmount 1+1→2 — **식이 실제 계산됨**(원 실측은 시드값
  1/"0" 고정). 파생값 기록의 절반이 실제로 열림. (04-probe-a2-modeA.log)

### H-ra3: repeat+set으로 N행 집계가 표현되는가 → **refuted (여전히 불가)**
- 시도 1: repeat 3 아래 read order + set 누적(들여쓴 2스텝) → rc=0이나 IR에서
  repeat Guard가 **첫 스텝(read order)만 소유** — set은 무진단으로 블록 밖 형제가 됨
  (04-probe-a3-ir.log). mode A: read order 3회 전부 같은 시드 행(id 동일), set 1회,
  totalAmount=2. 두 겹으로 불가: ① 반복이 다른 행을 바인딩하지 않음(행 집합 없음 —
  RFC-0015 §Alternatives의 결정과 일치), ② 들여쓴 다중 스텝 블록이 조용히 쪼개짐
  → 신규 마찰 후보 N-1. (04-probe-a3-modeA.log)

집계 판정(실측): sum/count **잔존**(target missing 불변). `set` 파생값은 **Integer
한정으로 열림** — Money는 산술 불가로 금액 합산은 우회로도 스펙 이탈(Integer 강등)
필요. N행 집계는 문법·실행 모형 양쪽에서 불가 유지.

## 차터 2 (Task 04): 스케줄 선언
`Explore 스케줄 표현을 with grammar.md:80-84의 신규 on schedule 문법 to discover
F-2가 선언→IR→OpenAPI 어디까지 도달하고 무엇이 남는지`

### H-rb1: `on schedule daily at 00:00 UTC`가 IR·OpenAPI까지 가는가 → **confirmed (부분 해소)**
- 시도 1: probe-b1 compile → rc=0 + `declared-not-enforced [event.daily.rollup]` 경고
  (05-probe-b1-compile.log). IR: `{"kind":"Event","source":{"every":"daily","at":"00:00",
  "zone":"UTC"}}` 내용 일치 PASS (05-probe-b1-ir.log). OpenAPI:
  `x-lnpl-schedules: [{event, every, at, zone, "enforcement":"unenforced"}]`
  (05-probe-b1-openapi.log). UNENFORCED가 진단·문서(grammar.md:84,
  declarations.md:34 "issue #26 ... owns the executor")·산출물 3채널 모두에 명시 —
  선언은 열렸고 실행기는 없음이 정직하게 공개됨.

### H-rb2: policy 절 미허용 이름은 여전히 시끄러운 거부인가 → **confirmed (불변)**
- 시도 1: 원 probe-b2 그대로(service 안 policy schedule) → rc=2,
  `unknown policy 'schedule' (allowed: retry, rollback, timeout, parallel)` —
  원 실측과 동일 (05-probe-b2-compile.log).

### H-rb2b(파생): workflow 안 policy 절은? → **신규 마찰 N-3 발견**
- 시도 1: workflow 본문에 policy schedule daily + read report → rc=0 **무진단**,
  IR의 Workflow가 children 없이 텅 빔 — policy 블록과 **이후 스텝(read report)까지**
  통째로 증발 (05-probe-b2b-compile.log 상단).
- 최소화: 미허용 이름 탓인지 분리 — **허용 이름 `retry 2`로도 동일 재현**(rc=0,
  빈 워크플로). 위치 규칙(policy는 service 전용)이 원인이며, 위반 시 거부가 아니라
  무음 증발. silent 함정 계보(F-3/F-5)의 신규 표본 (05-probe-b2b-compile.log 하단).

## 차터 3 (Task 05): silent-failure 재검
`Explore 진단·참조 규칙의 변화를 with --strict와 원 F-3/F-4/F-6/F-8 재현 절차 to
discover 조용한 실패 모드가 어디까지 닫혔는지`

### H-rc0: unknown-verb가 --strict에서 rc≠0인가 (F-3) → **confirmed (해소 방향)**
- compile 기본: rc=0(원과 동일 — 08-strict-off.log) / `--strict`: **rc=2**
  (08-strict-on.log) / `run --json --strict`: **rc=2** (08-strict-run.log).
- 오탐 없음 방향: 공식 예제 shorten은 경고 설계(declared-not-enforced 등 — F-8 원
  관찰 유지)라 clean 재료 부적합 → probe-clean.lnpl 신규 작성, `--strict` **rc=0**
  (08-strict-clean.log). 게이트가 clean/warned를 실제로 구분 — 양방향 검증 완료(D6).

### H-rc1: 다단어 엔티티 참조 (F-4) → **confirmed (해소)**
- `entity DailyReport` + `create DailyReport` → rc=0, IR RepositoryCall의
  entity=`entity.daily.report` 내용 일치 (08-probe-c1-compile.log). 원 rc=2+오도
  에러가 사라짐. 재시도 0회.

### H-rc2: 복수형 객체 명사 (F-6) → **confirmed (해소)**
- `load orders`(entity Order) → rc=0, IR entity=`entity.order` (08-probe-c2-compile.log).

### H-rc3: 진단 게이트 채널 (F-8) → **부분 해소 + 신규 마찰 N-4**
- exit 채널 신설: `--strict` = "exit 2 if any diagnostic is reported"(--help 원문,
  08-diag-channel.log). JSON 구조화 진단 스트림은 여전히 없음(stderr 텍스트뿐).
- **N-4 발견**: 정당한 `on schedule` 선언(probe-b1)도 declared-not-enforced 경고
  때문에 `--strict` rc=2 — 진단에 등급이 없어 의도 선언(unenforced 문서화 설계)과
  오타 no-op(unknown-verb)을 게이트가 구분 못함. #49의 신규 기능을 쓰면 #43의 신규
  게이트를 켤 수 없는 상호 배타 (08-diag-channel.log 말미).

## 차터 4 (Task 06): 최종 파이프라인 조립
`Explore 표현 가능 부분집합의 전 단계 통과를 with 프로브 실증 결과(차터 1~3) to
discover F-5/F-7의 변화와 신규 마찰`

### 조립 재시도 집계 (원: authoring 9회 / modeA 1회 / spec 2회)
- authoring: 프로브 단계 재시도 — a2 2회(시도 3회: create-set 거부→read로 1,
  Money 산술 거부→Integer 강등 1), 그 외 프로브 0회. 최종본 조립 자체는 0회.
- spec: **1회** (spec 1 given에 stored Report 시드 누락 → references/spec.md의
  "given이 알아듣는 형식"에 규칙이 문서화돼 있어 1회로 수렴. 원 2회 대비 감소,
  원인도 미문서 병합이 아니라 시드 누락으로 질이 다름).
- modeA: 0회 — F-7 해소로 원 1회(워크플로 id 표기)가 사라짐. `--workflow GetReport`
  → rc=2 + "valid: wf.build.report, wf.get.report" 후보 목록 (06-pipeline-wfname.log).

### H-rd1: 한 블록 복수 triplet(원 F-5 재현) → **confirmed (해소 — 시끄러운 거부)**
- probe-d1 → rc=2, "a second \`given\` inside one spec block — open a new \`spec\`
  block per scenario" — 원 무경고 병합이 파싱 거부+교정 지시로 바뀜
  (07-probe-d1-compile.log). 지원 경로: 블록 3개 → 독립 케이스 3개, spec --run
  7 passed 0 failed (07-spec-validate.log).

### 전 단계 결과 (Scorecard 상세는 FINDINGS.md)
compile rc=0(의도 경고 2) / validate PASS / modeA build·get rc=0(orderCount 실제
계산) / modeB build rc=0 / diff 두 워크플로 4/4 EQUIVALENT(set 스텝 포함 등가 —
Assignment가 모드 B에도 하강함을 관측) / openapi rc=0(x-lnpl-schedules 포함) /
spec 7 passed 0 failed.

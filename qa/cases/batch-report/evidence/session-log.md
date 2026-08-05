# 탐색 세션 로그 — batch-report

**Charter** (D1, wiki: qa-exploratory-exploratory-sessions):
Explore .lnpl vocabulary with lnpl-authoring references + the full pipeline
to discover where batch/aggregation workloads stop being expressible.

시뮬레이션 페르소나: 플랫폼 내부 지식 없는 LLM-only 개발자. 정보원은
AGENTS.md 라우팅, plugins/lnpl/skills/**, examples/** 만.

환경: HEAD=713a4cb, python3.13 자체 venv(상대경로), LLVM+SDK env 설정.

---

## Task 01 — 환경 + 명령 발견 + 대조군 (21:1x–21:2x)

- AGENTS.md → lnpl-dev-env 라우팅은 명확. dev_doctor rc=0 1회에 통과.
- 명령 발견: lnpl-authoring SKILL(컴파일), lnpl-verify SKILL(spec/diff), 나머지는
  `lnpl --help`가 8개 서브커맨드를 한 화면에 보여줌. **발견 마찰 낮음.**
  예외: IR 단일 문서 검증 명령은 스킬 문서에 없음 — `validate_ir.py`를 인자 없이
  실행해야 사용법이 나옴 (F-후보 아님 수준의 미세 마찰, info).
- 대조군 shorten.lnpl: 7단계 전부 exit 0. **N/A(env) 단계 없음 확정.**
- [surprise] 진단이 stderr+exit0 설계라는 걸 스킬 문서가 두 번 반복 경고 —
  문서가 함정을 정직하게 공개하고 있음. LLM-only 개발자가 SKILL을 안 읽고
  `--help`만 봤다면 이 사실을 몰랐을 것 (문서 라우팅을 따르는 한 안전).
- [F-후보 #1, info] `lnpl compile`의 진단 exit 코드가 0이라 CI에서 경고를
  게이트하려면 stderr 파싱이 필요 — unknown-verb를 기계적으로 잡을 수단이
  종료 코드에 없음.

## Task 02 — 어휘 조사 (21:2x–21:3x)

- references 5종 총 198줄 — 전량 읽기 부담 낮음. 표가 닫힌 목록임을 명시하고
  집행 매트릭스까지 제공: **문서 정직성 높음.**
- 집계 동사 계열 8낱말·스케줄 계열 7낱말·멱등 계열 5낱말 전부 0 hits (03-vocab-survey).
- [surprise] `performance batch` — "batch"라는 이름이 존재하는데 unenforced.
  이름만 보고 쓰면 파싱되고 무시되는, 브리프가 경고한 함정의 정확한 실물.
- [surprise] checkout.lnpl 공식 예제가 total 필드를 스스로 "서술(계산 안 됨)"로
  분류 — 파생값 계산 부재를 공식 예제가 자인.
- 가설 6건 초안(hypothesis-log.md): a1~a3, b1~b3.

## Task 03 — 집계 프로브 (21:3x–21:4x)

- H-a1/a2/a3 전부 confirmed — 집계는 (i) 동사 부재(no-op), (ii) 파생값 문법 부재,
  (iii) 산술·대입 부재의 3중으로 표현 불가. 시도 횟수: 공통 authoring 4회 + a3 개별 3회.
- [F-후보 #2, major] 다단어 엔티티명(DailyReport)은 스텝 객체로 참조 불가 —
  에러 지시("Name the entity")를 따라 정확 표기해도 같은 에러. 오도성 메시지.
- [F-후보 #3, minor] 복수형 객체 미해석("load orders"), did-you-mean 없음.
- [surprise] mode A bindings가 Order·Report 필드를 단일 레코드로 병합 — 시드값이
  types.md 예시값 그대로라 "계산된 것처럼 보이는" 위험(orderCount=1이 우연히 그럴듯).

## Task 04 — 배치 트리거 프로브 (21:4x)

- H-b1/b2/b3 전부 confirmed, 각 1회. 스케줄 어휘 없음: 스텝은 no-op, policy는 명시
  거부(허용 목록 제시 — 진단 상급), performance batch는 "문서화된 함정"(진단이 공개).
- 실패 모드 비대칭 확정: 동사부=조용한 no-op(위험), 선언부=시끄러운 거부(안전).
- b2(중복실행)·b3(멱등)은 어휘 부재로 N/A(blocked) — 03-vocab-survey 0 hits 인용.

## Task 05 — 부분집합 조립 + 전 파이프라인 (21:4x–21:5x)

- batch-report.lnpl: Order/Report + BuildReport(집계 잔여부) + GetReport(조회) +
  event ReportBuilt. 컴파일 1회에 통과(학습된 규칙 반영: 단일 단어 엔티티·단수 객체).
- 7단계 전부 PASS. differential 두 워크플로 모두 4/4 EQUIVALENT.
- [F-후보 #4, minor] `lnpl run --workflow GetReport` 실패 — 이름이 아닌 IR 노드 id
  (wf.get.report)를 요구. camelCase→점 표기 변환 규칙 미문서화, 에러에 후보 목록
  없음. IR JSON grep으로 우회(재시도 1).

## Task 06 — spec 블록 (21:5x–22:0x)

- lnpl-spec 스킬의 도출 규칙 준수: 정상(completed+steps+slo)+rows, 에러는 policy
  retry 2 추가로 도출(failed+attempts 3, empty repository), 경계는 no amount.
- 시도1 실패: 한 spec 블록에 given/when/expect 2벌 → 파싱은 되지만 **한 케이스로
  조용히 병합**(manifest 실측: given[valid order, no amount] + expect[completed,…,
  failed] 자기모순). 4 FAIL. [F-후보 #5, major] silent 함정 3호 — spec 복수 케이스.
- 시도2: 워크플로당 1케이스 재구조 + 경계 전용 CheckOrder 워크플로 우회 →
  spec: 7 passed, 0 failed. 파이프라인 전 단계 최종본 재실행 전부 exit 0.
- 진단 품질: spec FAIL 라인은 기대/실측을 나란히 출력(steps=1 want=4) — 상급.
  단 복수 triplet 병합은 무경고.

## Task 07 — 마감: lnpl-verify 게이트 + FINDINGS + 순수성 (22:0x–22:1x)

lnpl-verify 3항목 (실행 출력 기준):
1. compile 진단: 최종본 경고 1건 — `declared-measured-only [perf.report]
   performance response`. **의도됨**: SLO를 서술로 남기는 공식 예제(shorten)와 같은
   패턴이고, spec의 `slo met` 단언이 이 선언에서 도출된다. (06-pipeline-compile.log)
2. spec 실행: `spec: 7 passed, 0 failed` (07-spec-validate.log)
3. mode A/B 동치: 툴체인 있음 — 두 워크플로 모두 `differential: EQUIVALENT`
   (06-pipeline-diff.log, 06-pipeline-diff-get.log). 건너뛴 단계 없음.

- 독립 감사: test-quality-auditor VERDICT: PASS (5개 기준 전부 충족).
- git 순수성: `git status --porcelain` → `?? qa/` 단 1건, tracked diff 없음
  (09-git-purity.log). .venv/.claude/tmp는 gitignore로 미표시.
- 세션 산출물 3종 마감: 세션 노트(본 파일) / F-기록 8건(FINDINGS.md) /
  자동화 후보 갭 3건(FINDINGS 총평).

# DELTA — batch-report: 원 실측(713a4cb) → 재측정(6d84bd6, #43~#50 이후)

대조 기준: `qa/cases/batch-report/FINDINGS.md`(F-1~F-8). 재측정 정본:
`qa/rerun/cases/batch-report/FINDINGS.md`. 판정 어휘(D11): **해소**(원 재현 절차가
더 이상 마찰을 내지 않음) / **부분**(일부 경로만 열림) / **잔존**(원 재현 그대로).
모든 판정은 재측정 실측 rc·산출물 인용 — 사전조사·구현 커밋 메시지는 근거로 쓰지
않았다.

## ① 원 8마찰 전건 판정

| F | 내용 | 원 심각도 | 판정 | 근거 증적 |
|---|------|-----------|------|-----------|
| F-1 | 집계(sum/count→파생값) 표현 불가 | blocker | **부분** — `set`+이항 산술로 파생값 실제 계산(orderCount 1→2); 단 Integer·DateTime 한정(Money 산술 rc=2 거부), N행 집계·sum/count 어휘 잔존(unknown-verb 재현 동일), 로드맵은 RFC-0015 §Alternatives에 있으나 authoring 라우팅에서 포인터 0건 | evidence/04-probe-a2-{compile,ir,modeA}.log, 04-probe-a1-compile.log, 04-probe-a3-{ir,modeA}.log, 03-vocab-survey-diff.md §D12 |
| F-2 | 배치 트리거(스케줄) 표현 불가 | blocker | **부분** — `on schedule daily at 00:00 UTC` 선언이 parse(경고 declared-not-enforced)→IR(내용 일치)→OpenAPI `x-lnpl-schedules`(enforcement:"unenforced")까지 도달; 실행기 부재(issue #26 소관)·중복실행/멱등 어휘 0 hits 잔존 | evidence/05-probe-b1-{compile,ir,openapi}.log, 03-vocab-survey-diff.md |
| F-3 | 무동작 실패가 조용함(exit 0) | major | **해소** — `--strict`: unknown-verb rc=2(compile·run 양쪽), clean 파일 rc=0(오탐 없음, 양방향 검증). 기본값은 여전히 rc=0(opt-in 게이트) | evidence/08-strict-{off,on,run,clean}.log |
| F-4 | 다단어 엔티티 참조 불가+오도 에러 | major | **해소** — `create DailyReport` rc=0, IR entity=`entity.daily.report` 내용 일치. 재시도 4→0회 | evidence/08-probe-c1-compile.log |
| F-5 | spec 복수 케이스 무경고 병합 | major | **해소** — 블록 3개→독립 케이스 3개, `--run` 7 passed 0 failed; 원 재현(한 블록 2 triplet)은 rc=2 + 교정 지시("open a new `spec` block per scenario")로 시끄럽게 거부. 원 우회(CheckOrder 분리 워크플로) 제거됨 | evidence/07-spec-validate.log, 07-probe-d1-compile.log |
| F-6 | 복수형 객체 명사 해석 불가 | minor | **해소** — `load orders` rc=0, IR entity=`entity.order` | evidence/08-probe-c2-compile.log |
| F-7 | --workflow id 미문서·후보 없음 | minor | **해소** — 선언명 입력 시 경계에서 rc=2 + 전 후보 목록("valid: wf.build.report, wf.get.report"). IR grep 불요, 재시도 1→0회 | evidence/06-pipeline-wfname.log |
| F-8 | 진단의 기계 채널 부재 | info | **부분** — `--strict`로 exit 채널 신설; 공식 예제 경고 설계·JSON 진단 스트림 부재·진단 등급 부재(→N-4) 잔존 | evidence/08-diag-channel.log, 08-strict-clean.log |

집계: **해소 5 / 부분 3 / 잔존 0** (단 부분 3건의 잔존 절반은 전부 케이스 본론 —
집계·스케줄 실행 — 에 걸려 있다. 아래 ④).

## ② 재시도 비교

| 단계 | 원 | 재측정 | 원인 델타 |
|------|-----|--------|-----------|
| authoring | 9회 (프로브 a 공통 4 + a3 3 + spec 진입 2) | **2회** (probe-a2: create-set 거부→read 1회, Money 산술 거부→Integer 강등 1회) | 원 재시도의 주 원인이던 F-4(다단어 엔티티, 4회)가 해소로 소멸. 신규 재시도 2회는 신기능 `set`의 미문서 규칙(N-2)과 타입 경계(Money) — 거부가 시끄러워(rc=2) 수렴은 빠름 |
| modeA | 1회 (F-7 워크플로 id) | **0회** | F-7 해소 |
| spec | 2회 (F-5 병합 우회 탐색) | **1회** (stored 시드 누락) | 원인 질이 다름: 원은 미문서 무경고 병합의 시행착오, 재측정은 문서화된 `given` 형식(references/spec.md)의 누락 — 문서만 읽으면 0회 가능 |
| 합계 | **12회** | **3회** | 75% 감소. 남은 3회 중 2회가 신기능 경계(N-2 미문서·Money 타입)에서 발생 — 신규 마찰이 신규 재시도의 전부 |

## ③ 신규 마찰 (상세: FINDINGS.md §Frictions — 신규)

| N | 내용 | 심각도 | 성격 |
|---|------|--------|------|
| N-1 | `repeat` 아래 들여쓴 다중 스텝이 무진단 분리 — 첫 스텝만 반복, 나머지는 블록 밖으로 | **major** | silent (F-3/F-5 계보) |
| N-2 | `set` 대상 바인딩 규칙(read 계열 전용, create 불가) 미문서 + 진단이 set을 "guard condition"으로 오칭 | minor | 오도 (F-4 계보) |
| N-3 | workflow 본문의 `policy` 절이 이후 스텝까지 통째 무음 증발(허용 이름으로도 재현, rc=0 빈 워크플로) | **major** | silent |
| N-4 | `--strict`에 진단 등급 없음 — 의도 선언(unenforced)과 오타 no-op을 구분 못해 스케줄 선언(#49)과 strict 게이트(#43)가 상호 배타 | **major** | 게이트 실효 공백 |

## ④ 케이스 판정

원 판정(원 FINDINGS 총평): "**배치·집계 워크로드에는 사용 불가(blocker 2건);
요청-응답 서비스 한정으로는 조건부 사용 가능 — CI에 stderr 진단 코드 게이트를
붙이고 엔티티명 단일 단어 규약을 지킨다는 조건에서.**"

갱신 판정: **배치·집계 워크로드는 여전히 사용 불가 — 단 blocker 2건이 각각 절반
열렸다(부분 개선).** (a) 집계는 파생값 기록(`set`, Integer 한정)이 실제 계산되나
행 집합 sum/count와 Money 산술이 잔존해 제품 요구(금액 합산 리포트)는 스펙 이탈
없이 표현 불가. (b) 스케줄은 선언·IR·OpenAPI 메타데이터까지 열렸으나 실행기가
없어(unenforced 3채널 명시) "매일 자정 실행"은 외부 시스템 몫 그대로. **요청-응답
한정 조건부 사용의 조건은 실질 개선**: stderr grep 우회가 `--strict` 정식 게이트로
승격됐고(F-3), 엔티티명 단일 단어·spec 1케이스·워크플로 id grep 규약이 전부
불필요해졌다(F-4·F-5·F-7). 단 새 조건이 하나 생겼다 — 스케줄 선언을 쓰는 파일은
`--strict`를 켤 수 없다(N-4). silent 실패의 형태 문제는 종류를 바꿔 살아 있다
(N-1·N-3).

자동화 후보 갭(D1 세션 출력 3): ① 진단 등급 도입 + `--strict`의 등급 선택 통과
(N-4), ② repeat 들여쓰기 블록 진단(N-1), ③ workflow 내 policy 위치 오류의 명시
거부(N-3), ④ set 바인딩 규칙 문서화+진단 문구 교정(N-2), ⑤ authoring references에서
RFC 로드맵 포인터(F-1 발견 가능성), ⑥ 원 F-1 재현 커맨드의 회귀 테스트화.

## 플랫폼 무수정 증명

`git status --porcelain -uall` 전량이 `qa/rerun/cases/batch-report/` 아래
(+gitignored `.venv/`·`.claude/tmp/`) — allowlist 밖 위반 0건. 게이트 자체의 양방향
검증(PASS 방향+FAIL 방향)은 evidence/00-baseline.md, 최종 실행은
evidence/09-git-purity.log.

## Definition of Done 체크

- [x] batch-report.lnpl(표현 가능 부분집합 — 스케줄 선언 포함) + 전 단계 증적 → `batch-report.lnpl`, `evidence/06-pipeline-*.log`, `evidence/07-spec-validate.log`, `evidence/artifacts/final/*`
- [x] 어휘 표 재조사 diff → `evidence/03-vocab-survey-diff.md` (+`evidence/03-genref-check.log` rc=0)
- [x] DELTA.md 8건 전부 판정 + 재시도 비교 + 신규 마찰 + 케이스 판정 → 본 문서 ①~④
- [x] FINDINGS.md 원 포맷 → `FINDINGS.md` (원 구조: 헤더/Scorecard/판정 규칙/Frictions/총평)
- [x] qa/rerun/cases/batch-report/ 밖 무변경 → `evidence/09-git-purity.log`

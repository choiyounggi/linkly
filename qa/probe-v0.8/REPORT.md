# probe-v0.8 — lnpl 0.8.0 엔터프라이즈 준비도 종합 보고서 (11차 감사)

다섯 시나리오(S1~S5, 블랙박스 개발자 페르소나)의 실측 결과를 종합한다. 이
보고서는 새 측정을 하지 않으며, 모든 판정 문장은 케이스 FINDINGS.md의
F-번호·evidence 경로·METRICS 행만 인용한다. 판정 어휘는 Ship /
Ship-with-known-issues / Block 셋뿐이다. 세부 데이터는
report-appendix/{friction-matrix,coverage-matrix,metrics-comparison}.md가
정본이다.

## §1 Executive Summary

**종합 판정: Block**(s1/s2/s3 FINDINGS.md 케이스 판정 — 도메인별 근거는 아래 세 불릿과 §3).

- 네 도메인(s1~s4) 중 세 도메인(s1 다중팀 CRUD·결제, s2 외부 연동·이벤트, s3 배치·집계)이 Block이고 한 도메인(s4 운영 배포)만 Ship-with-known-issues여서, worst-domain 규칙(§3)에 따라 종합 판정은 Block이다(s1 FINDINGS.md 케이스 판정; s2 FINDINGS.md 케이스 판정; s3 FINDINGS.md 케이스 판정).
- Money/Decimal이 `set`·가드·재실행 경로 전반에서 산술·갱신 대상이 못 되는 제약(C1)과 `create ... as` 바인딩이 OpenAPI/serve 응답 스키마 해석기에 없어 생기는 크래시(C2)가 세 Block 도메인에 걸쳐 반복돼, 개별 케이스의 우연이 아니라 플랫폼 표면의 반복 결함임을 보여준다(s1 F-1, s2 F-1, s3 F-1 — C1; s1 F-12, s3 F-6 — C2; report-appendix/friction-matrix.md §3).
- 운영(s4)만 유일하게 Ship-with-known-issues에 도달했고 그마저 성능 blocker(postgres 지속 부하 붕괴)를 소유자가 수용해야 하는 조건부라는 점에서, v0.8.0은 "엔터프라이즈급 개발"의 네 핵심 도메인 중 셋을 막고 있다(s4 FINDINGS.md 케이스 판정 조건 1; s4 F-6).

## §2 다섯 질문에 대한 답

### (1) 엔터프라이즈급 개발이 가능한가

엔터프라이즈 개발 가능성은 도메인별로 갈린다: s1(CRUD·결제)·s2(연동·이벤트)·s3(배치·집계) 세 도메인은 각각 Block이고 s4(운영배포)만 Ship-with-known-issues다(s1/s2/s3/s4 FINDINGS.md 케이스 판정; report-appendix/coverage-matrix.md §2).

커버리지 집계로 보면 s1은 10건 중 충족 3·부분 6·불가 1, s2는 충족 3·부분 1·불가 2·우회 4, s3은 충족 5·부분 1·불가 1·우회 3으로 세 도메인 모두 절반 이상이 완전 충족에 못 미친다(report-appendix/coverage-matrix.md §2).

집계 규칙(전 보고서 공통, r1 F1 대응): 심각도가 비표준 표기 "blocker 후보"인 항목(s1 F-6)은 blocker로 계수하고, 축을 2개 표기한 항목은 friction-matrix.md §1 각주대로 첫 번째 축으로 계수한다 — `grep -cE '심각도: \*{0,2}blocker' qa/probe-v0.8/cases/*/FINDINGS.md`로 케이스별 재확인: s1=5(F-1·F-3·F-6·F-12·F-13), s2=5, s3=3, s4=1, s5=0, 합계 14. 14건의 blocker F-항목 중 13건(s1 5 + s2 5 + s3 3)이 s1~s3에 집중돼 있고, 그중 Money/Decimal 산술 제한(C1)과 create-as 바인딩 미등록(C2)은 각각 3개·2개 도메인에 걸쳐 반복된다(report-appendix/friction-matrix.md §2, §3).

결론적으로 오늘의 v0.8.0으로 "여러 팀이 나눠 만드는 CRUD·결제·연동·집계 서비스"를 완결하려면 표현력·서빙 레이어의 blocker 다수를 플랫폼이 먼저 고쳐야 한다(s1/s2/s3 FINDINGS.md 케이스 판정 driver 문단).

### (2) 성능은 어떤가

성능은 s3·s4 두 케이스에서만 측정됐다: s3의 집계 파이프라인은 1k/10k 중앙값이
0.074s/0.077s(비율 1.04)로, 테이블 전체 스캔이라면 나올 ~10배의 선형 확장보다
훨씬 낮아 pushdown/색인에 부합하는 평평한(flat) 패턴을 보이며(스위치 부재로
on/off 대조까지는 증명하지 못해 "일관됨" 수준으로만 기록), 100k도 0.14s(600초
상한 대비 여유)로 이 평평한 패턴이 유지된다(s3 evidence/09-perf.md). s4의 postgres 백엔드는 100rps 지속
부하에서 0–40초는 평균 10ms대로 안정적이나 40–50초 평균 95.9ms(최대
3968ms), 50–60초 평균 1161.9ms(최대 5876ms)로 시간에 비례해 tail latency가
폭증한다(s4 evidence/05-load.md, F-6). 같은 케이스의 드레인 시험은
grace-period 1초·10초 어느 쪽에서도 6000건 중 정확히 1건이 손실돼 "손실 0"
요구를 충족하지 못한다(s4 evidence/06-drain.md, F-7). 종합하면 짧은 배치·집계
워크로드의 처리 성능은 준수하지만, 지속적 고부하 서빙 성능은 v0.8.0의 안전
상한이 미확정인 채 blocker로 남아 있다(s4 FINDINGS.md F-6).

### (3) 유지보수는 어떤가

변경 요청 반영은 s1(gift_wrap 옵션)이 12줄·4라운드(자체 버그 1건 포함)·기존
spec 0건 손상으로 완료됐고, s5(FastAPI 대조군)는 동일 성격의 변경을 3파일
+18/-4줄·1라운드·기존 테스트 0건 손상으로 완료했다 — 절대 노력은 s5가 더
적으나 s1도 회귀 없이 끝냈다는 점에서 유지보수성 자체가 막혀 있지는
않다(s1 METRICS.md 변경 요청 행; s5 METRICS.md 변경 요청 행). s5는 비즈니스
규칙 1개당 평균 ~29줄이 흩어져 있고 상태 전이표만 한 곳(`orders/state.py`)에
모여 있다고 스스로 기록했는데(report-appendix/metrics-comparison.md Table
C), 이는 lnpl의 선언적 워크플로 구조(요구사항이 `when`/`set`/`respond` 등으로
한 파일에 순서대로 나열됨)와 대조된다(s1 FINDINGS.md R10). friction-matrix의
`maint` 축에는 이번 라운드 F-항목이 0건이라(report-appendix/friction-matrix.md
§2), 유지보수 마찰 자체는 이번 측정에서 F-항목으로 직접 포착되지 않았다 —
변경 요청 지표 1쌍 이상의 일반화는 미측정이다. 결론: 변경 반영 능력 자체는
두 스택 모두 입증됐고, 어느 쪽이 더 유지보수하기 쉬운지는 표본 1쌍으로는
말할 수 없다(s1 METRICS.md, s5 METRICS.md).

### (4) LLM 특화 관점에서는 어떤가

표본 1쌍(n=1, 방향성만)의 t1 대 t5 대조에서 lnpl 쪽이 authoring 라운드(42 대
24, 비율 1.75)·소스 대비 읽은 문서량(~2,655줄 대 ~252줄, 비율 ~10.5)·출력
토큰(722,792 대 234,410, 비율 3.08) 모두에서 더 많이
든다(report-appendix/metrics-comparison.md Table A). friction-matrix 축
집계로 보면 `doc`(문서·예제 오류/누락) 축이 12건으로 전체 47건 중 가장 큰
단일 축이고, 그중 9건이 minor(우회는 가능하나 문서만 봐서는 못
씀)다(report-appendix/friction-matrix.md §2). `llm` 축 3건(s1 F-15 pipeline
암묵 종결, s3 F-4 판정 어휘 갭, s5 F-5 자체검수 한계)과 `diag` 축 1건(s2
F-10 관측 신호 부족)은 닫힌 어휘·문서 의존이 LLM 저작 비용에 직접 영향을
준다는 근거다(report-appendix/friction-matrix.md §1). 종합하면 lnpl은 표현력
탐색 비용(닫힌 어휘 + 문서 갭)이 LLM 저작자에게 FastAPI보다 구조적으로 더
크다는 방향성은 뚜렷하나, 표본 1쌍이라 배율(1.75~10.5배)의 정확한 크기는
주장할 수 없다(report-appendix/metrics-comparison.md 헤더 n=1 caveat).

### (5) 상품성 — 테스트/QA는 충분한가

`rt`축 blocker는 6건(s1 F-12·F-13, s2 F-4, s3 F-6·F-7·F-8)이며, 그중 s3
F-8(`lnpl migrate`가 rc=0으로 성공을 보고하지만 실제로는 아무것도 쓰지
않음)은 정의상 "조용히 틀린 결과"의 전형이다(report-appendix/friction-matrix.md
§1, s3 F-8). spec/pytest가 실제로 결함을 잡은 사례는 s1의 D3
flip-red-restore-green 실증(s1 evidence/04-spec.md)과 s5의 round12
ambiguous-column 실패(s5 evidence/03-pytest.md) 둘 다 있어 "초록≠충족" 원칙이
두 스택 모두에서 최소 1회는 실제로 작동했다. 반대로 s3의 spec은 `delete`의
시뮬레이션 실행기 버그로 실제 `lnpl run`은 정상인데도 거짓 RED를 냈다(s3
FINDINGS.md F-10) — spec 자체의 신뢰성이 false green과 false red 양방향에서
흔들린 사례다. spec/pytest 커버리지는 s1 R9=충족(9블록/33단언), s2
R10=부분, s3 R10=부분, s5 R9=충족(26노드/83assert)로 갈려 s2/s3에서는 spec
표현력 자체가 요구를 다 못 담는다(report-appendix/coverage-matrix.md §1). impl
열람으로 근인이 실측 확정된 F-항목은 4건(s1 F-3·F-12·F-13, s3 F-6)뿐이라,
이번 라운드 결함 대부분(43/47)은 블랙박스 실행 증거만으로 확정된 것이며
상품성 QA는 "증상은 재현 가능하나 근인은 대개 미확인"인 상태다(s1
FINDINGS.md F-3/F-12/F-13; s3 FINDINGS.md F-6).

## §3 도메인별 판정표

| 도메인 | 판정 | 근거 | known-issue 조건(번호) |
|---|---|---|---|
| s1 다중팀 CRUD·결제 | **Block** | (s1 FINDINGS.md 케이스 판정 — driver F-12, 보조 사유 F-6) | Block 반전 조건 (1) F-12/F-13 수리, (2) F-3 수리로 R2 원자성 복구, (3) 그 뒤 소유자 별도 수용 대상: F-1, F-4, F-11, F-8(코드는 있으나 F-번호 결측 — §7), F-14 |
| s2 외부 연동·이벤트 | **Block** | (s2 FINDINGS.md 케이스 판정 — F-4/F-5/F-6 우회 불가 확정, F-1/F-2도 blocker 유지) | 수용 가능한 known-issue 없음 — F-4(재시도 무발동)·F-5(응답 검증 시 크래시)·F-6(emit 페이로드 매핑 불가) 셋 다 "아무도 수용 못 하는" 성격 |
| s3 배치·집계 | **Block** | (s3 FINDINGS.md 케이스 판정 — driver F-8, F-6/F-7도 동일 사유로 지지) | Block 반전 조건 (1) F-6/F-7/F-8 수리, (2) Money 파생 계산은 Python 파이프라인 유지로 합의(설계 선택, 수용 가능), (2b) glue.py 실행 전 raw 구간 비열람 운영 규율, (3) 재실행 로직 "conflict→replace" 표준화, (4) R8(리포트 API)은 F-5 구조적 한계까지 겹쳐 별도 설계 필요 |
| s4 운영 배포 | **Ship-with-known-issues** | (s4 FINDINGS.md 케이스 판정) | (1) postgres 지속 고부하(≥100rps·≥40s) 비운영 또는 `--rate-limit` 보수적 설정(F-6, blocker), (2) 캐시 hit-rate 검증 불가 인지(F-2, major), (3) gunicorn 선택 시 경화 옵션 절반 상실 인지(F-5, major) |
| s5 대조군(FastAPI) | Ship-with-known-issues — **대조군, 플랫폼 판정에 불포함** | (s5 FINDINGS.md 케이스 판정) | (1) import-linter 간접-import 기본 설정 필요(F-1), (2) httpx/TestClient 버전 경고(F-4), (3) 자체 검수만으로는 커버리지 갭 3건을 놓쳤을 것(F-5) — lnpl 대비 비교 참고용 |

## §4 이전 감사 계보 대비 변화

1차(`qa/REPORT.md`, 커밋 713a4cb) → 3차(`qa/rerun/REPORT.md`, 커밋 6d84bd6) →
이번(4차, probe-v0.8) 순으로, 같은 개념의 도메인을 고정 매핑해 대조한다.
측정되지 않은 도메인은 3차 판정을 그대로 이월하고 "(미재측정 — 3차 유지)"로
표기하며, §1의 종합 판정에는 포함하지 않는다.

| 도메인 | 1차 판정 | 3차 판정 | 이번(4차) 판정 | 근거 F/evidence |
|---|---|---|---|---|
| 요청-응답 CRUD·값 규칙(s1 R2–R4) | 조건부 가능(qa/REPORT.md L184) | Ship-with-known-issues(r1 "프로덕션 사용 가능(상태 전이 자동화 제외)", qa/rerun/REPORT.md §1) | **Ship-with-known-issues**(부분 셀 3건, 불가 0건 — D6 유도 규칙) | s1 R2/R3/R4 coverage cells(report-appendix/coverage-matrix.md); F-6(R2 지지 — §7에 심각도 표기 불일치 기록), F-5(R3, 수용 불필요), F-4(R4) |
| 결제·민감정보(s1 R5–R7) | 불가(qa/REPORT.md L186) | Ship-with-known-issues(r2 "사용 가능(조건부)" 조건 2건, qa/rerun/REPORT.md §1) | **Ship-with-known-issues**(부분 셀 3건, 불가 0건 — D6 유도 규칙) | s1 R5/R6/R7 coverage cells; F-11·F-14(R7) — R5/R6이 인용하는 F-8/F-9는 s1 FINDINGS.md에 해당 헤딩이 없어 §7에 결측으로 기록, 여기서는 재인용하지 않음 |
| 가드+spec 검증(s1 R9 + s2 R10 + s3 R10) | 불가(C7 가드 조건 표현력 한계, blocker, 3/4 관측 — qa/REPORT.md L143) | Ship-with-known-issues(r4 "판정 반전 — spec 원형 3시나리오 PASS", qa/rerun/REPORT.md §1) | **Ship-with-known-issues**(s1 R9 충족, s2 R10 부분, s3 R10 부분 — 불가 0건, D6 유도 규칙) | s1 R9(9블록/33단언 그린), s2 R10(부분 — 대리신호), s3 R10(부분 — 스케일·spec delete 버그 F-10) |
| 시간창 정책 | 불가(qa/REPORT.md L188) | Ship-with-known-issues(r2 F-5 해소, qa/rerun/REPORT.md §1) | (미재측정 — 3차 유지) Ship-with-known-issues | (s-none: 이번 라운드에 시간창 정책을 다루는 케이스가 없음) — §1 종합 판정에 미포함, qa/rerun/REPORT.md §1 판정을 그대로 이월 |
| 배치·집계(s3) | 불가(qa/REPORT.md L187) | Block 유지("배치·집계 워크로드는 여전히 사용 불가 — 단 blocker 2건이 각각 절반 열렸다", qa/rerun/REPORT.md §1) | **Block**(driver 교체: F-1/F-2(3차)→F-6/F-7/F-8(4차)) | s3 FINDINGS.md 케이스 판정 — 단, 집계 연산 자체(sum/count/avg/list where/schedule/멱등재실행)는 10k/50가맹점 전량 0불일치로 증명돼 3차 대비 개선(R1/R2/R5/R6/R7, evidence/08-rerun-oracle.md) |
| 외부 연동·이벤트(s2, 신규) | 해당 없음(1차 도메인 없음) | 해당 없음(3차 도메인 없음) | **Block** | s2 FINDINGS.md 케이스 판정 |
| 운영 배포(s4, 신규) | 해당 없음(1차 도메인 없음) | 해당 없음(3차 도메인 없음) | **Ship-with-known-issues** | s4 FINDINGS.md 케이스 판정 |

## §5 보완 로드맵(P0~P2)

한 행 = 교차 클러스터(C1~C4) 또는 클러스터에 속하지 않는 blocker/major
F-항목 1건(D8). 우선순위: P0 = blocker 또는 조용히 틀린 결과, P1 = major가
≥2케이스에 반복되거나 R 하나 전체를 불가로 만드는 마찰, P2 = 나머지. 중복
확인 셀은 `ls rfcs | grep -i <keyword>`와 `grep -n -i <keyword>
docs/ROADMAP.md`의 실제 실행 결과를 인용한다.

| # | 증상(F refs) | 근인 | 플랫폼 변경안 | 기대 효과(열리는 R/A) | 기존 RFC/이슈 중복 여부 | 우선순위 |
|---|---|---|---|---|---|---|
| C1 | s1 F-1, s2 F-1·F-2, s3 F-1·F-2(blocker×3, major×1, minor×1 — 3개 케이스) | RFC-0016/0028/0044가 산술 evaluator를 Integer/DateTime(+ 집계 컨텍스트의 Money)로만 좁혀 `set`·가드·재실행(upsert) 경로 전부에서 Money/Decimal을 배제 | Money/Decimal 전용 산술 evaluator(최소 곱셈 1건)를 열거나, 최소한 연산자 없는 순수 복사 `set` 허용 | s1 R2/R3, s2 R1, s3 R3/R4/R9의 우회(총 6건) 소멸 — 화폐 계산을 언어 안에서 직접 표현 | `ls rfcs \| grep -i money` → `0044-money-arithmetic.md`(기존 RFC, 이번 요청은 그 범위의 확장이지 신규 주제 아님); `grep -n -i money docs/ROADMAP.md` → 0줄 | **P0** |
| C2 | s1 F-12, s3 F-6(blocker×2, 2개 케이스) | `_response_schema`의 `by_binding`이 `find` 바인딩만 알고 `create ... as` 별칭 바인딩을 모름(RFC-0030 §2와 모순) | `by_binding` 맵에 `create ... as` 바인딩도 등록 | s1 R8, s3 R8(OpenAPI 생성 + `lnpl serve` 기동) 자체가 복구 — RFC-0030 골든 예제가 다시 동작 | `ls rfcs \| grep -i create-as` → 0줄; `grep -n -i openapi docs/ROADMAP.md` → **7줄**(125·160·165·174·181·193·207 — Phase 2 "자동 생성물 1종" 계획, RFC-0001 validation rule 반영, R18 제네릭/컬렉션 타입 부재가 OpenAPI 스키마에 미치는 영향; 7건 모두 `create ... as` 바인딩 크래시와 무관 — 이 회귀는 여전히 없음) | **P0** |
| C3 | s1 F-13, s3 F-7(blocker×2, 2개 케이스) | in-workflow 쓰기(생성/수정) 직후 바인딩 내부 상태(사전 시딩 스킵 여부, 낙관적 잠금 `_version`)가 갱신되지 않아 같은 실행의 다음 연산이 자기 자신과 충돌 | in-workflow 쓰기 직후 해당 바인딩의 내부 상태를 즉시 갱신 | s1 R8 계열 워크플로, s3의 일반적인 "레코드 일부 필드 갱신" 패턴 복구 | `ls rfcs \| grep -i version` → 0줄(무관 주제); `grep -n -i conflict docs/ROADMAP.md` → 0줄 | **P0** |
| C4 | s1 F-4, s2 F-7(major×2, 2개 케이스) | 가드 거부는 설계상 HTTP 200/`skipped`로만 신호되고 NetworkCall은 예외를 던지지 않음 — "이 결과를 실패로 승격"하는 명시적 동사가 없음 | `when`에 "게이트 실패 시 4xx" 선언 옵션 또는 NetworkCall 결과를 RunError로 escalate하는 동사 | s1 R4/R5/R6의 4xx 정합, s2 R8 "3회 연속 실패" 조건 표현 가능 | `ls rfcs \| grep -i escalate` / `-i failure` → 0줄; `grep -n -i escalate docs/ROADMAP.md` → 0줄 | **P1** |
| U1 | s1 F-3(blocker) | `impl/lnpl/repo_policy.py::row_key`가 어떤 엔티티든 `payload["id"]` 하나만 사용 | `find`/`create`에 조회 키 필드를 지정하는 표기(`find product by input.productId`) | s1 R2 원자성 우회(F-6) 자체가 불필요해짐 | `ls rfcs \| grep -i row-key`/`-i lookup` → 0줄; `grep -n -i 'row.key\|lookup\|find.*by\|natural key' docs/ROADMAP.md` → 0줄 | **P0** |
| U2 | s1 F-6(blocker, F-3의 연쇄) | U1과 동일(F-3) | U1 해결에 종속 — 별도 변경 불필요 | s1 R2 on_hand 실차감 복구, 과다판매 방지 | U1과 동일 이슈 트랙 | **P0** |
| U3 | s2 F-4(blocker) | `HttpNetworkDriver`가 회복성 코어(`_call_with_resilience`)를 실제로 호출하지 않는 것으로 추정 | retry/backoff 실행 경로 회귀 테스트 추가 및 수리 | s2 R3 재시도 신뢰 회복 | `ls rfcs \| grep -i resilience` → `0037-http-resilience.md`(기존 RFC의 구현 결함, 신규 설계 아님) | **P0** |
| U4 | s2 F-5(blocker) | 응답 형식 검증(비수치 값 거부) predicate 부재 — 가드 비교가 예외를 던져 워크플로 전체가 죽음 | **RFC-0028 개정**으로 안전한 `is-numeric`류 alternative-guard predicate 추가(신규 RFC 아님 — 아래 중복확인 참고) | s2 R4 완전 충족(외부 API 응답 방어 검증) | `ls rfcs \| grep -i guard` → **6줄**(0008-guard-conditions, 0009-guard-condition-open-question, 0014-guard-skip-observability, 0017-guarded-example-correction, 0023-guard-scope-diagnostic, 0028-arithmetic-and-alternative-guards); `rfcs/0028-arithmetic-and-alternative-guards.md:202`가 "비수치 값의 비교 → `RunError` — cannot compare non-numeric"를 **이미 의도된 설계로 명시** — F-5는 이 RunError 계약 자체가 아니라 "안전하게 회피할 predicate가 없다"는 갭이므로, **기존 항목 보강**(RFC-0028 개정) 대상이지 신규 주제가 아니다; ROADMAP grep 없음 | **P0** |
| U5 | s2 F-6(blocker) | `emit`이 IR의 `EventEmit.payloadMap`을 저작 문법에 노출하지 않음 | `emit <event> with <ref>...` 페이로드 매핑 절 | s2 R5 완전 충족(이벤트 기반 통합의 핵심 요구) | `ls rfcs \| grep -i payload` → `0030-create-result-binding-and-payload-seed.md`(create 바인딩용, emit과 무관 — 실질 중복 없음) | **P0** |
| U6 | s3 F-8(blocker, 조용히 틀린 결과) | 다개체 스키마에서 필드-존재 검사 로직이 달라지는 것으로 추정(impl 미열람, 고의) | `lnpl migrate`의 필드-존재 검사를 다개체 컨텍스트에서 최우선 조사·수리 | s3 R9 완전 충족 — 되돌릴 수 없는 백필 운영의 신뢰 회복 | `ls rfcs \| grep -i migrate` → 0줄; `grep -n -i migrate docs/ROADMAP.md` → 0줄 | **P0** |
| U7 | s4 F-6(blocker) | `lnpl serve`↔`lnpl-postgres` 드라이버 경로의 커넥션 재사용 정책 vs dev 서버 스레드 모델 불일치로 추정(impl 미열람) | postgres 백엔드 지속 부하 상한 공식 측정·문서화 + 근인 조사 | s4 R7 완전 충족 — 프로덕션 배치 가이드 확정 | `ls rfcs \| grep -i postgres` → 0줄(외부 드라이버 레포 소관); `grep -n -i postgres docs/ROADMAP.md` → **1줄**(line 69: "capability(`postgres`·`redis`·`jwt`)는 인메모리 fake로 대체한다" — 테스트 목킹 목록일 뿐, 지속 부하 상한과 무관 — 중복 없음) | **P0** |
| M1 | s1 F-11(major) | 환불 "3회 상한"이 누적 금액 캡과 별개로 집행되지 않음 | F-10 기법(자기-set 필드 참조)으로 count 캡 추가(미검증 방향) | s1 R7 완전 충족 | 케이스 국한 — RFC/ROADMAP grep 생략(신규 언어 기능 아님, 저작 패턴) | **P2** |
| M2 | s2 F-3(major) | `references/verbs.md`가 `format` 문법을 보여주지 않음(진단 메시지가 유일한 출처) | `verbs.md`의 `format` 행에 정확한 문법 한 줄 추가 | 저작 라운드 절감(R 변화 없음, 이미 성공) | 문서 전용 — RFC 불필요 | **P2** |
| M3 | s3 F-5(major) | `expose list by`가 Integer/DateTime만 정렬 허용, `desc` 수식어 부재 | `desc` 수식어 개방 또는 Money를 order-by 허용 타입에 추가 | s3 R8(리포트 API) 불가 해소에 기여(F-6/F-7과 함께 해결돼야 완성) | `ls rfcs \| grep -i sort` / `-i desc` → 0줄(0038은 list-where predicate, order-by 아님); `grep -n -i desc docs/ROADMAP.md` → 1줄이나 kb.\* 응답 얘기로 무관 | **P1** |
| M4 | s4 F-2(major) | CacheAccess `get`을 만드는 표면 동사가 없음(`cache`는 set, `invalidate`만 존재) | `check`/`peek` 표면 동사 또는 `find ... via cache` 구문 | s4 R2 완전 충족(read-through 캐시 워크플로 표현 가능) | `ls rfcs \| grep -i cache` → 0줄; `grep -n -i cache docs/ROADMAP.md` → **4줄**(99·112·208·298 — 전부 Phase 1 골든 IR의 `CacheAccess`(set) 표면 표기·TTL 소유·Performance metric 직렬화 논의뿐, `get` 표면 동사 갭은 언급 없음) | **P2** |
| M5 | s5 F-1(major, 대조군) | 해당 없음 — lnpl 무관(서드파티 import-linter의 기본 의미론) | 해당 없음 — s1이 이미 `internal` 선언(1급 문법)으로 이 문제 자체가 없음을 확인(비교 근거로만 기록) | 없음(액션 아이템 아님) | 해당 없음 | **P2** |
| M6 | s3 F-10(major) | `lnpl spec`의 fixture 실행기가 `delete`를 실제 저장소 드라이버와 다른 코드경로로 처리 | fixture 실행기를 실제 드라이버 코드경로로 정합화 | s3 R10 완전 충족 — spec의 양방향 신뢰성(false green도 false red도 없음) 회복 | `ls rfcs \| grep -i delete` → 0줄; ROADMAP grep 없음 | **P2** |
| M7 | s1 F-14(major) | `lnpl token`에 `--role` 플래그가 없음 | `lnpl token --role <r>` 최소 플래그 추가 | s1 R7 admin 승인 경로를 내장 CLI만으로 왕복 검증 가능 | `ls rfcs \| grep -i jwt` → 0줄; `grep -n -i jwt docs/ROADMAP.md` → 2줄, capability 목록 언급뿐(role 클레임 이슈 없음) | **P2** |
| M8 | s2 F-8(major) | outbox·CloudEvents 봉투·서빙 로그 세 지점 모두 correlation 컬럼/필드가 없음(4개 무관 식별자로 쪼개짐) | 세 지점에 originating `correlation_id` 컬럼/필드 추가 | s2 R9(불가 → 충족 가능) | `ls rfcs \| grep -i correlation` → 0줄; `grep -n -i correlation docs/ROADMAP.md` → 1줄, RFC-0006 agent-protocol `_meta.correlation_id`(별도 프로토콜 — event/outbox 스키마와 범위가 다름, 실질 중복 아님) | **P1** |
| M9 | s4 F-5(major) | `build_app()`의 env-var 표면이 `serve` CLI보다 좁음(gunicorn 경로에서 rate-limit/metrics/cache/jwt-issuer 미지원) | `build_app()` env-var 표면을 `serve`와 동등 확장 또는 nginx 대체 설정 문서화 | s4 R4 경화 옵션이 gunicorn 경로에서도 완전 충족 | `ls rfcs \| grep -i gunicorn` → 0줄; `grep -n -i gunicorn docs/ROADMAP.md` → 0줄 | **P2** |
| M10 | s5 F-5(major, 대조군) | 해당 없음 — 방법론 관찰(자체검수 vs 독립검수) | 플랫폼 변경 아님 — s1의 spec 블록이 구현 상수를 import 못 하게 강제하는 언어 차원 방어가 있는지는 향후 비교 과제 | 없음(교육적 데이터) | 해당 없음 | **P2** |
| M11 | s1 F-18(major) | round 1 증거가 응답 JSON만으로 작성되고 sqlite 직접 조회(read-back)를 안 함 | 해당 없음 — 이 케이스 자신의 증거 절차 결함, 플랫폼 문제 아님(FINDINGS 자체 명시) | 없음(플랫폼 R에 영향 없음) | 해당 없음 | **P2** |

## §6 이슈 후보 표

§5의 행 1개당 이슈 후보 1개(라벨은 저장소 기존 라벨 집합 {bug, documentation,
enhancement, production-readiness, tech-debt, question}에서만 선택).

| # | 제목 | 근거 F | 라벨 후보 |
|---|---|---|---|
| C1 | Money/Decimal 산술·갱신을 `set`/가드/재실행 경로로 열기 | s1 F-1, s2 F-1, s2 F-2, s3 F-1, s3 F-2 | enhancement |
| C2 | `create ... as` 바인딩을 `by_binding`(openapi/serve 응답 스키마)에 등록 | s1 F-12, s3 F-6 | bug |
| C3 | in-workflow 쓰기 직후 바인딩 내부 상태(사전시딩/`_version`) 갱신 | s1 F-13, s3 F-7 | bug |
| C4 | 업무/네트워크 실패를 호출자 가시 실패 신호로 승격하는 동사 추가 | s1 F-4, s2 F-7 | enhancement |
| U1 | `find`/`create`에 조회 키 필드 지정 표기 추가 | s1 F-3 | enhancement |
| U2 | (U1과 동일 수정으로 해소) Stock.onHand 갱신 불가 | s1 F-6 | bug |
| U3 | `capability http retry`가 실행에서 no-op인 회귀 수리 | s2 F-4 | bug |
| U4 | **기존 항목 보강**(RFC-0028 개정) — alternative-guard에 `is-numeric`류 방어 predicate 추가 | s2 F-5 | enhancement |
| U5 | `emit ... with ...` 페이로드 매핑 절 추가 | s2 F-6 | enhancement |
| U6 | `lnpl migrate` 다개체 스키마 무동작 버그 수리 | s3 F-8 | bug, production-readiness |
| U7 | postgres 백엔드 지속 부하 상한 측정·문서화 | s4 F-6 | production-readiness |
| M1 | 환불 등 카운트 기반 캡을 표현하는 패턴/동사 검토 | s1 F-11 | enhancement |
| M2 | `verbs.md`의 `format` 문법 문서화 | s2 F-3 | documentation |
| M3 | `expose list by`에 `desc` 및 Money order-by 허용 | s3 F-5 | enhancement |
| M4 | CacheAccess `get` 표면 동사(`check`/`peek`) 추가 | s4 F-2 | enhancement |
| M5 | (대조군 관찰, 액션 없음) lnpl `internal`이 import-linter 문제를 회피함 기록 | s5 F-1 | question |
| M6 | `lnpl spec`의 `delete` fixture 실행기 정합화 | s3 F-10 | bug |
| M7 | `lnpl token --role` 플래그 추가 | s1 F-14 | enhancement |
| M8 | outbox/CloudEvents/서빙 로그에 correlation_id 필드 통일 | s2 F-8 | enhancement |
| M9 | `build_app()` env-var 표면을 `serve`와 동등화 | s4 F-5 | enhancement, production-readiness |
| M10 | (교육적 관찰, 액션 없음) spec의 구현-상수 자기참조 방지 가능성 비교 과제 | s5 F-5 | question |
| M11 | (이 케이스 자신의 절차 개선, 플랫폼 아님) 모든 create/update 주장은 read-back으로 맺기 | s1 F-18 | question |

## §7 이번 측정의 한계

1. **표본 크기 n=1.** 다섯 시나리오 각각 1회씩만 측정했다 — 시나리오당 반복
   측정이나 여러 저자에 의한 재현은 하지 않았다(coordinator 지시, 전 케이스
   공통).
2. **Sonnet 티어 워커, 케이스당 4시간 상한.** t1~t5 전부 Sonnet 5(high
   effort)로 작업했고(report-appendix/token-usage.md 주1), 4시간 예산 안에서
   측정했다 — 더 긴 시간이나 다른 모델 등급에서는 다른 라운드 수·판정이 나올
   수 있다.
3. **블랙박스 조건(플러그인 문서 + CLI만).** 다섯 케이스 모두
   `requirements/README.md §2`의 블랙박스 규약(impl/ 열람 원칙적 0회, 열람 시
   각 F-항목에 명기)을 따랐다 — impl 열람으로 근인이 실측 확정된 F-항목은
   4건(s1 F-3·F-12·F-13, s3 F-6)뿐이고 나머지는 증상만 확정, 근인은 추정이다.
4. **t1/t5 단일 쌍.** LLM 특화 비교(§2-4)는 같은 요구사항·같은 모델·같은
   상한 아래 lnpl 대 FastAPI 딱 1쌍만 있다 — 배율의 방향성은 뚜렷하나 크기는
   통계적으로 주장할 수 없다(report-appendix/metrics-comparison.md 헤더).
5. **재측정 없음.** 이 보고서는 다섯 케이스의 기존 증거만 종합했고, 어떤
   명령도 다시 실행하지 않았다 — 증거가 없는 값은 전부 "미측정"으로 남겼다
   (예: §4의 시간창 정책 행).

**블랙보드 오염 평가(r1 F3 대응).** 2026-09-05 16:50Z, s3(t3)가 케이스-내부
플랫폼 관측 4건(Money 산술 제한 포함)을 `.orchestration/notes/decisions.md`에
잘못 게시했고 코디네이터가 즉시 격리·정정 NOTICE를 냈다(s3 FINDINGS.md 환경
헤더: "블랙보드 게시: t3 플랫폼 관측 4건(16:50Z, ...) — 케이스-내부 관찰을
잘못 게시했다... 재발 없음"). 이 4건 중 다른 케이스의 F-항목과 겹치는 사실은
"Money/Decimal은 `set`/가드 산술 대상이 될 수 없다"(s1 F-1, s2 F-1) 하나뿐이다
— s1 evidence/01-authoring.md는 s1이 이 사실을 round 3a-3g(round1 세션
16:22Z~17:26Z의 초반, round 4의 Integer 전환 **이전**)에 컴파일러 진단과
`rfcs/0044-money-arithmetic.md`로 직접 확정했음을 보여준다(같은 세션이 round
1~40을 담고 있어 round 3~4는 세션 시작 후 10분 이내로 추정 — 약 16:27~16:28Z,
16:50Z보다 20분 이상 앞선다). s2 evidence/01-authoring.md도 s2가 round
4/15(세션 16:33Z~17:07Z, 34분)에서 같은 사실을 `rfcs/0028-arithmetic-and-
alternative-guards.md`와 컴파일러 진단으로 독립 확정했음을 보여준다(round
4/15 ≈ 세션 시작 후 9분 — 약 16:42Z, 16:50Z보다 8분 앞선다). 즉 s1·s2 모두
16:50Z 이전에 자기 증거로 이미 이 사실을 발견했으므로, C1 클러스터(§3
friction-matrix.md)의 "3개 케이스 반복" 주장은 블랙보드 오염이 아니라 독립
재발견에 근거한다. s1/s2/s4/s5 FINDINGS.md 환경 헤더 어디에도 코디네이터
NOTICE가 요청한 "블랙보드 t3 항목 열람: 예" 자기신고 줄이 없어(`grep -n
'블랙보드' qa/probe-v0.8/cases/{s1-order-platform,s2-integration-events,
s4-ops-deploy,s5-baseline-fastapi}/FINDINGS.md` → 0줄), 추가 열람도 자기신고
되지 않았다 — 이 보고서는 s3의 오게시가 §1 불릿 2의 "반복 결함" 논지를
약화시키지 않는다고 평가한다.

**읽은 파일(D1, 필요할 때만 evidence를 연 목록)**: `.claude/tmp/t6-read-list.txt`
— FINDINGS-SCHEMA.md, 다섯 FINDINGS.md, 다섯 METRICS.md,
report-appendix/token-usage.md, qa/rerun/report-appendix/friction-matrix.md
(형식 선례). 이번 종합에 인용된 evidence 파일은 모두 케이스 FINDINGS.md가
이미 인용한 값을 재확인 없이 그대로 전재했다(D1 — 새로 열 필요가 없었다).

**케이스 기록 정정 필요** (cases/**는 수정하지 않았다 — 아래는 기록용):

1. `qa/probe-v0.8/cases/s1-order-platform/FINDINGS.md:27` — R5 커버리지 셀이
   `F-8`을 인용하나 이 파일에 `### F-8` 헤딩이 없다(같은 파일 line 164에서도
   재인용). PAN 미추출 friction 자체는 실재하나(R5 서술과 정합), 라운드
   재구성 중 번호가 빠진 것으로 보인다.
2. `qa/probe-v0.8/cases/s1-order-platform/FINDINGS.md:28` — R6 커버리지 셀이
   `F-9`를 인용하나 이 파일에 `### F-9` 헤딩이 없다(같은 행에 인용된 `F-18`은
   실재).
3. `qa/probe-v0.8/cases/s1-order-platform/FINDINGS.md:51` — F-6의 심각도가
   `blocker 후보`로, FINDINGS-SCHEMA §1의 3종(blocker/major/minor) 밖의
   비표준 표기다. friction-matrix.md는 blocker로 집계하고 주1로 남겼다.
4. `qa/probe-v0.8/cases/s1-order-platform/FINDINGS.md:72` — F-10의 심각도가
   "(발견 자체, 심각도 표기 대상 아님)"으로 비표준이고, 축도 `doc, llm` 2개로
   FINDINGS-SCHEMA §2가 요구하는 "정확히 1개"를 벗어난다.
5. `qa/probe-v0.8/cases/s1-order-platform/FINDINGS.md:93,128` — F-18/F-16의
   축이 각각 "(해당 없음 — 검증 관행)", "(해당 없음 — 자기 절차 위반)"으로
   스키마의 축 태그 8종 밖이다(둘 다 이 케이스 자신의 절차에 대한 메모라는
   점은 본문에 명시돼 있다).
6. `qa/probe-v0.8/cases/s2-integration-events/FINDINGS.md:80,107,175` —
   F-3(`expr, doc`)·F-5(`expr, rt`)·F-10(`diag, ops`)이 각각 축 2개를 표기해
   FINDINGS-SCHEMA §2의 "정확히 1개" 규칙을 벗어난다. friction-matrix.md는
   첫 번째 태그를 집계에 썼다.
7. `qa/probe-v0.8/cases/s4-ops-deploy/METRICS.md:12` — "충족 7 / 부분 2 /
   불가 0 / 우회 0"(합계 9)로 적혀 있으나, 같은 케이스 FINDINGS.md의
   요구사항 커버리지 표는 R1~R10 전건에 8충족·2부분(합계 10)을 기록한다(r1
   N2 대응). report-appendix/coverage-matrix.md §2는 FINDINGS.md 원문(8/2/0/0)을
   따랐다 — METRICS.md 쪽이 정정 대상이다.

**인용 무결성 검사 결과** (D7):

```
$ sh .claude/tmp/t6-integrity-check.sh
== F-number tokens (sN F-k proximity) ==
== evidence/ paths (sN evidence/... proximity) ==
== friction-matrix row count vs source F-heading count ==
source=47 matrix_rows=47
done
```

검사(`.claude/tmp/t6-integrity-check.sh`, 저장소에 커밋되지 않는 스캐치)는
REPORT.md·report-appendix/*.md에서 `sN F-k` 및 `sN evidence/...` 근접 토큰을
전부 뽑아 해당 케이스 `cases/sN.../FINDINGS.md`에 `### F-k` 헤딩이, 또는
`cases/sN.../evidence/...`에 파일이 실재하는지 확인하고, friction-matrix.md의
행 수가 다섯 FINDINGS.md의 `### F-` 전건 수(47)와 같은지 확인한다. 결과:
**0 missing**, 47=47(모두 REPORT.md·report-appendix/**에 한정된 검사이며,
cases/** 자체의 결측 2건(F-8/F-9 dangling)은 위 "케이스 기록 정정 필요"에
별도 기록했고 본 REPORT/부록에는 재인용하지 않았다).

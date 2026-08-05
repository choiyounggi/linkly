# Appendix — 46건 마찰 인벤토리·클러스터 배정·매트릭스 원자료

Wave 1 4개 FINDINGS.md의 F-기록 전건(46건)을 정규화한 표다. 심각도는 원 기록
그대로 전사했고(관찰자가 정한 사실 축 — 재협상·인상 없음), 주 클러스터는
`.orchestration/plans/t5-report.md`의 확정 배정 맵을 따른다. F 1건당 주 클러스터
1개이며 교차 참조는 비고에 적는다. 증적 경로는 각 케이스 워크트리의
`qa/cases/<case>/` 기준 상대 경로로, 원문 F-절에 인쇄된 표기를 보존한다.

소스(읽기 전용):
- t1 = `.worktrees/qa-t1-inventory-order/qa/cases/inventory-order/FINDINGS.md` (F-1~F-12)
- t2 = `.worktrees/qa-t2-payment-refund/qa/cases/payment-refund/FINDINGS.md` (F-1~F-14)
- t3 = `.worktrees/qa-t3-batch-report/qa/cases/batch-report/FINDINGS.md` (F-1~F-8)
- t4 = `.worktrees/qa-t4-rate-notify/qa/cases/rate-notify/FINDINGS.md` (F-1~F-12)

## 1. 마찰 인벤토리 (46건)

| 케이스 | F | 단계 | 심각도 | 한 줄 요약 | 주 클러스터 | 증적(원문 표기) |
|--------|---|------|--------|------------|-------------|------------------|
| t1 | F-1 | authoring | blocker | 가드 우변에 필드 참조 불가 — 수량 인지 재고 검사 표현 불가, S2 과판매가 completed | C7 | evidence/04 (S2 귀결) |
| t1 | F-2 | authoring | blocker | 산술·할당 문법 부재 — 재고 차감 표현 불가 | C6 | 원문 재현 절(grammar.md·verbs.md 전수 + IR 확인) |
| t1 | F-3 | authoring | major | 상태 전이 규칙 표현 불가 — enum 타입 선언까지만 | C6 | evidence/01 |
| t1 | F-4 | authoring | minor | 가드는 바로 다음 1스텝만 감쌈 — 스코프 규칙 미문서 | C10 | evidence/01 (시도 2) |
| t1 | F-5 | modeA | major | 거부 의미론 부재 — 가드 스킵이어도 completed·rc=0 | C2 | evidence/04 S3, evidence/05 |
| t1 | F-6 | modeA | major | refinement facet 런타임 미집행 — qty=0 주문 통과, openapi 400 서술과 불일치 | C5 | evidence/04 S4, evidence/07 |
| t1 | F-7 | spec | major | spec은 워크플로당 1케이스 — 복수 블록 침묵 병합 | C1 | evidence/08 (manifest 원문) |
| t1 | F-8 | spec | minor | `stored` 엔티티명 소문자만 + 진단 시점 불일치 | C9 | 원문 재현 절(spec --run 진단) |
| t1 | F-9 | modeB | minor | `--field` 오키 침묵 무시 — 기본값 0으로 가드 평가 | C4 | evidence/05 |
| t1 | F-10 | modeA | info | payload가 엔티티 네임스페이스 없이 평평하게 병합 | 단독 | evidence/04 상단 |
| t1 | F-11 | modeA | info | 결정론적 검증 실패에도 retry 3회 발동 | 단독 | evidence/04 프로브 |
| t1 | F-12 | authoring | minor | 파이프라인 명령·플래그 라우팅 갭 — CLI 전모는 소스 열람 필요 | C10 | evidence/01 관찰 |
| t2 | F-1 | parse | major | 가드가 read된 저장 행만 참조 가능 — 입력값 검증 표현 불가 | C7 | evidence/raw/compile-a3.err |
| t2 | F-2 | lower | major | 연쇄 `when` 가드 첫 번째가 무진단 IR 탈락 — 0원·음수 결제 승인 | C3 | evidence/02-compile.md, evidence/04 (T05) |
| t2 | F-3 | authoring | major | 조건 결합(AND)·등가(==) 부재 — 범위·전액 환불 검증 불가 | C7 | 원문 재현 절(grammar.md 연산자 목록) |
| t2 | F-4 | modeA | major | Money 필드 가드 — 컴파일 통과 후 런타임 raw traceback 크래시 | C7 | evidence/raw/run-approval-default.err |
| t2 | F-5 | authoring·modeA | major | 기간 정책(30일 이내) 표현 불가 — DateTime 산술·비교 불가 | C8 | 원문 재현 절 ①~③ (비고: 산술 측면은 C6 교차) |
| t2 | F-6 | modeA | major | 가드 false = 조용한 skip — completed·rc=0 | C2 | evidence/raw/run-approval-amt1000001.out |
| t2 | F-7 | modeA | **blocker** | 마스킹 부분 집행 — trace는 `***`, result.bindings는 카드번호 원문 노출, 우회 없음 | C5 | evidence/04-modeA-masking.md |
| t2 | F-8 | openapi | major | OpenAPI `writeOnly` 계약과 런타임 동작 모순 | C5 | evidence/07-openapi.md |
| t2 | F-9 | differential | minor | diff 마스킹 검사가 누수 채널을 비교 표면에 미포함 | C5 | evidence/06-differential.md |
| t2 | F-10 | spec | major | spec 블록 간 given 병합 — 워크플로당 시나리오 1개만 | C1 | evidence/08-spec.md 시도 2·3 |
| t2 | F-11 | spec | major | given이 payload 통째 대체 + Money 표기 부재 — 경계 spec 불가 | C9 | evidence/08-spec.md 시도 4·5 |
| t2 | F-12 | spec | minor | `stored` given 오도적 진단 — 선언된 엔티티를 "not declared"로 보고 | C9 | evidence/08-spec.md 시도 1 |
| t2 | F-13 | modeA | minor | run payload 전체 필드 강제 — 경계 프로브에도 카드번호 제출 | 단독 | evidence/04 |
| t2 | F-14 | authoring | info | KB 보안 커버리지 공백 — 마스킹 질의가 네이밍 문서로 오라우팅 | C10 | evidence/01 |
| t3 | F-1 | authoring | **blocker** | 집계(sum/count → 파생값)가 어휘·문법 양쪽에서 표현 불가 | C6 | evidence/03-vocab-survey.md, evidence/hypothesis-log.md |
| t3 | F-2 | authoring | **blocker** | 배치 트리거(스케줄·중복실행·멱등) 표현 불가 | C8 | 원문 재현 절(probe-b1~b3) |
| t3 | F-3 | parse/modeA | major | 파싱 성공+런타임 무동작이 조용함 — exit 0, 진단은 stderr 전용 | C3 | 원문 재현 절(probe-a1) |
| t3 | F-4 | parse | major | 다단어 엔티티명 스텝 객체 참조 불가 + 에러 지시가 오도 | C10 | evidence/04-probe-a1-compile.log 이력 |
| t3 | F-5 | spec | major | spec 블록의 복수 케이스가 한 케이스로 조용히 병합 | C1 | 원문 재현 절(manifest 실측) |
| t3 | F-6 | parse | minor | 복수형 객체 명사가 엔티티로 해석되지 않음 | C10 | 원문 재현 절 |
| t3 | F-7 | modeA | minor | `--workflow`가 미문서 IR 노드 id 요구, 에러에 후보 목록 없음 | C10 | 원문 재현 절 |
| t3 | F-8 | parse | info | 진단 게이트 부재 — 경고를 기계적으로 잡을 종료 코드 채널 없음 | C3 | 원문(lnpl-verify SKILL 명시) |
| t4 | F-1 | authoring | minor | 동사 어휘에 notify/send 부재 — 발송을 기록+이벤트로 근사 | C6 | evidence/01-authoring.md |
| t4 | F-2 | authoring/modeA | major | 미선언 이벤트 참조가 compile·validate 통과, 런타임에만 실패 — 가드 스킵 시 잠복 | C3 | evidence/02-compile.md, 03-ir-validate.md, 04-modeA.md |
| t4 | F-3 | modeB | major | `--field` 불일치 이름 무경고 무시 — 전 필드 기본값 0 평가 | C4 | evidence/05-modeB.md |
| t4 | F-4 | spec | major | 워크플로당 spec 블록 다중 선언 무음 병합 | C1 | evidence/08-spec.md, raw/spec-run-1.txt |
| t4 | F-5 | spec | major | spec 러너가 given의 id를 payload에 적용 못함 — 케이스 실행 불가 | C9 | evidence/08-spec.md, raw/spec-run-2.txt, spec-run-3.txt |
| t4 | F-6 | spec | minor | given `no <field>` 필드 스코프 미문서 | C9 | evidence/08-spec.md, raw/spec-run-1.txt |
| t4 | F-7 | authoring | info | RFC-0008의 `==`/`!=`가 생성된 grammar.md에 없음 | C7 | evidence/01-authoring.md (비고: 문서 불일치 측면은 C10 교차) |
| t4 | F-8 | authoring | info | RFC-0008 §5.2가 약속한 examples/guarded.lnpl 부재 | C10 | evidence/01-authoring.md |
| t4 | F-9 | modeA | info | 0라운드 until이 skipped 목록에 미표기 — when 스킵과 비대칭 | C2 | evidence/04-modeA.md |
| t4 | F-10 | modeA | info | `run --json` 결과에 저장소 행 수(rows) 신호 없음 | 단독 | evidence/04-modeA.md |
| t4 | F-11 | parse | info | 컴파일 진단에 파일:라인 위치 정보 없음 | C10 | evidence/02-compile.md |
| t4 | F-12 | spec | minor | spec 러너가 실패 사유를 출력하지 않음 | C9 | evidence/08-spec.md |

검산: t1 12건 + t2 14건 + t3 8건 + t4 12건 = 46건.
클러스터 배정 42건 + 단독 4건(t1 F-10·F-11, t2 F-13, t4 F-10) = 46건.

## 2. 클러스터 확정표 (C1~C10)

무음 실패 계열 — 파싱·컴파일은 초록인데 의미가 조용히 증발:

| id | 이름(플랫폼 결함 명명) | 심각도(구성원 max) | 관측 케이스 | 구성원 |
|----|----------------------|--------------------|-------------|--------|
| C1 | spec 블록 무음 병합 — 워크플로당 1케이스 강제 | major (4/4 관측으로 우선순위 최상위) | 4/4 | t1 F-7, t2 F-10, t3 F-5, t4 F-4 |
| C2 | 가드 skip = completed·rc=0 — 거부 의미론 부재 | major | 3/4 | t1 F-5, t2 F-6, t4 F-9 |
| C3 | 선언·참조의 무음 증발/지연 실패 — 컴파일 초록, 런타임 무동작·잠복 | major | 3/4 | t2 F-2, t3 F-3, t3 F-8, t4 F-2 |
| C4 | `--field` 이름 불일치 무경고 무시 — 기본값 0 평가 | major | 2/4 | t1 F-9, t4 F-3 |
| C5 | 출력 채널 간 집행 불일치 — 마스킹 누수·계약 과대 광고·검사 표면 누락 | **blocker** | 2/4 | t2 F-7, t2 F-8, t2 F-9, t1 F-6 |

표현력 공백 계열 — 언어 안에 우회가 없는 표현 불가:

| id | 이름 | 심각도(구성원 max) | 관측 케이스 | 구성원 |
|----|------|--------------------|-------------|--------|
| C6 | 값 의미론 부재 — 산술·할당·집계·파생값·상태 전이·동사 어휘 폐쇄 | **blocker** | 4/4 (t2는 F-5의 산술 측면 교차 관측) | t1 F-2, t1 F-3, t3 F-1, t4 F-1 |
| C7 | 가드 조건 표현력 한계 — 우변 리터럴 한정·단일 비교·AND/== 부재·입력값 검증 불가 | **blocker** | 3/4 | t1 F-1, t2 F-1, t2 F-3, t2 F-4, t4 F-7 |
| C8 | 시간·기간·스케줄 정책 공백 — DateTime 산술·시간창·배치 트리거 불가 | **blocker** | 2/4 | t2 F-5, t3 F-2 |
| C9 | spec given 의미론 결함 — payload 통째 대체·id 유실·표기 제약·스코프 미문서 | major | 3/4 | t1 F-8, t2 F-11, t2 F-12, t4 F-5, t4 F-6, t4 F-12 |

문서·진단 계열:

| id | 이름 | 심각도(구성원 max) | 관측 케이스 | 구성원 |
|----|------|--------------------|-------------|--------|
| C10 | 미문서 규칙·문서-구현 불일치 — 엔티티 참조 규칙·워크플로 id·`==`/`!=`·예제 부재·CLI 커버리지·KB 오라우팅 | major | 4/4 | t1 F-4, t1 F-12, t2 F-14, t3 F-4, t3 F-6, t3 F-7, t4 F-8, t4 F-11 |

## 3. 스코어카드 매트릭스 원자료 (9단계 × 4케이스)

각 셀은 원문 Scorecard의 결과·재시도 수를 문자 그대로 전사한 것이다(한정어 보존).

| 단계 | t1 inventory-order | t2 payment-refund | t3 batch-report | t4 rate-notify |
|------|--------------------|--------------------|------------------|-----------------|
| authoring | PASS / 5 (.lnpl 수정→재실행 총계; 내역: 컴파일 3 + spec 2) | PASS / 편집 9회 (가드 3·엔티티 2·spec 4) | PASS (부분집합 — 요구 3개 중 (c)만 온전, (a) 잔여부, (b) 표현 불가) / 9 (프로브 a 공통 4 + a3 3 + spec 2) | PASS / 3 (emit 이름 1 + spec 재구성 2) |
| parse | PASS / 0 | PASS / 8 (에러 3·성공 5) | PASS / 0 (최종본 기준) | PASS / 0 (첫 컴파일 rc=0, 의도된 경고 1) |
| lower | PASS / 0 | PASS (24 nodes) / 8 (parse와 동일 명령) | PASS (compile이 parse+lower 일체 수행, IR 생성) / 0 | PASS / 0 |
| validate | PASS / 0 | PASS / 4 (재컴파일마다 재검증, 전부 PASS) | PASS / 0 | PASS / 0 |
| modeA | PASS / 0 (변형 6회 전부 구동; 의미 갭은 F-1·F-5·F-6) | PASS / 워크플로당 2 (+경계 프로브 6실행) | PASS (BuildReport·GetReport 각 completed) / 1 (워크플로 id 표기 — F-7) | PASS / 1 (F-2로 1차 6/7 실패 → 수정 후 7/7 rc=0) |
| modeB | PASS / 1 (`--field` 키 형식 규명) | PASS / 1 | PASS / 0 | PASS / 1 (F-3로 1차 전 런 오평가 → dotted 재실행) |
| differential | PASS / 0 (EQUIVALENT 4/4) | PASS (EQUIVALENT 4/4 ×2 워크플로) / 1 | PASS (두 워크플로 모두 4/4 EQUIVALENT) / 0 | PASS / 0 (r1·r2 모두 EQUIVALENT 4/4) |
| openapi | PASS / 0 | PASS / 1 | PASS / 0 | PASS / 0 |
| spec | PASS / 2 (3케이스→1케이스 축소 — F-7) | PASS (4 passed, 0 failed) / 6 | PASS (7 passed, 0 failed — 정상 1·에러 1·경계 1) / 2 (복수 케이스 병합 — F-5) | **FAIL** / 3 (상한 도달 — F-4·F-5·F-7) |

**재시도 계수 각주**: 계수 규칙이 케이스별로 다르다 — t1은 ".lnpl 수정→재실행
총계", t2는 "편집 횟수·명령 재실행", t3은 "프로브 시도", t4는 "attempt 수" 기준.
따라서 재시도 수의 **케이스 간 합산·비교는 무효**이며, 이 표의 수치는 각 케이스
안에서의 방향성 신호로만 읽어야 한다.

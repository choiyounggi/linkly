# FINDINGS — rate-notify

케이스: 임계값 기반 조건부 알림 (when/until 가드 런타임 평가 실측).
환경: commit 713a4cba, python3.13.1, lnpl 0.2.0, LLVM(homebrew)+SDK 설정,
dev_doctor rc=0 (evidence/00-env.md). 실행: 2026-08-05 21:07~21:35 KST.

## Scorecard

| 단계 | 결과 | 증적 경로 | 재시도 수 |
|------|------|-----------|-----------|
| authoring | PASS | evidence/01-authoring.md | 3 (emit 이름 1 + spec 재구성 2) |
| parse | PASS | evidence/02-compile.md, raw/compile-attempt-*.txt | 0 (첫 컴파일 rc=0, 의도된 경고 1) |
| lower | PASS | evidence/03-ir-validate.md, raw/lower-stderr.txt | 0 |
| validate | PASS | evidence/03-ir-validate.md, raw/validate.txt | 0 |
| modeA | PASS | evidence/04-modeA.md, raw/modeA-r*.json | 1 (F-2로 1차 6/7 실패 → 수정 후 7/7 rc=0) |
| modeB | PASS | evidence/05-modeB.md, raw/modeB-b*.txt | 1 (F-3로 1차 전 런 오평가 → dotted 재실행) |
| differential | PASS | evidence/06-differential.md, raw/diff-r*.txt | 0 (r1·r2 모두 EQUIVALENT 4/4) |
| openapi | PASS | evidence/07-openapi.md | 0 |
| spec | **FAIL** | evidence/08-spec.md, raw/spec-run-*.txt | 3 (상한 도달 — F-4·F-5·F-7) |

**핵심 측정 결과 (케이스의 존재 이유): 가드 3형태(when 비교식·when presence·until)
모두 mode A/B 양쪽에서 실제로 평가되며, 참/거짓 페어의 관찰 신호가 전부 갈렸다 —
무음 통과(항상 참) 없음.** 경계 실측: `>`는 배제 경계(값=임계값 100 → 스킵),
0·음수 정상 비교. until은 16라운드 상한(`reason="round_cap"` WARN) 확인.
differential은 발화·스킵 경로 모두 EQUIVALENT.

## Frictions

### F-1: 동사 어휘에 notify/send 부재 — 알림 발송을 직접 표현 불가
- 단계: authoring | 심각도: **minor** | 재시도: 0 | 우회: 있음
- 재현: (1) plugins/lnpl/skills/lnpl-authoring/references/verbs.md 열람 (2) 표 16개 동사 확인.
- 기대 vs 실제: 알림 도메인이면 발송 동사를 기대 vs "`return`, `log`, `send`, `notify` … 이 표에 **없다**"(verbs.md 원문). `create notification`(RepositoryCall)+`emit`(EventEmit)으로 대체 — 의미는 "발송"이 아니라 "기록+이벤트".
- 증적: evidence/01-authoring.md.

### F-2: 미선언 이벤트 참조가 compile·validate를 통과하고 런타임에만 실패 — 가드 스킵 시 잠복
- 단계: authoring/modeA | 심각도: **major** | 재시도: 1 | 우회: 있음(이벤트 이름 camelCase)
- 재현: (1) `emit notification` 스텝 작성(이벤트 선언명은 NotificationSent) (2) `lnpl compile` → rc=0, 0 error (3) `validate_ir.py` → PASS (4) `lnpl run --payload payloads/r1.json` → rc=1.
- 기대 vs 실제: 미해석 참조는 컴파일 또는 IR 검증에서 거부 vs `EventEmit references undeclared event 'event.notification'` **런타임 에러**. 더 나쁜 것: presence 가드가 emit을 스킵한 r6은 **rc=0으로 통과** — 가드가 자주 스킵되는 경로면 프로덕션까지 잠복한다. emit 목적어→이벤트 id 합성 규칙(`notificationSent`→`event.notification.sent`)은 어느 문서에도 없다.
- 증적: evidence/02-compile.md, 03-ir-validate.md, 04-modeA.md.

### F-3: mode B `--field`가 정규화된 dotted 이름을 요구하며, 불일치 이름은 무경고 무시
- 단계: modeB | 심각도: **major** | 재시도: 1 | 우회: 있음(dotted 이름)
- 재현: (1) `lnpl build --run --field value=150 --field acknowledged=1` (2) 출력 관찰.
- 기대 vs 실제: 이름 불일치 시 경고/에러 vs **무경고 exit=0으로 전 필드 기본값 0 평가** — create 스킵·until 16라운드, 5개 런이 사실상 동일 거동. help의 "Fields the workflow does not compare on are ignored"가 오타·이름 불일치까지 삼킨다. `lnpl diff`는 payload에서 스스로 배선해 이 함정이 없다(사람이 직접 넘길 때만 위험).
- 증적: evidence/05-modeB.md.

### F-4: 워크플로당 spec 블록 다중 선언이 무음 병합됨
- 단계: spec | 심각도: **major** | 재시도: 1 | 우회: 부분(1블록으로 축소)
- 재현: (1) spec 블록 3개(정상/에러/경계) 선언 (2) `lnpl spec -o` → `1 case(s)`.
- 기대 vs 실제: 블록당 1케이스 또는 명시 거부 vs 3블록의 given/expect가 한 케이스로 이어붙어 `completed`와 `failed`가 공존하는 모순 케이스 생성, 경고 없음. 정상+에러+경계를 spec으로 표현할 방법이 사실상 없다.
- 증적: evidence/08-spec.md, raw/spec-run-1.txt.

### F-5: spec 러너가 given의 `id` 값을 payload에 적용하지 못해 케이스 실행 불가
- 단계: spec | 심각도: **major** | 재시도: 2 | 우회: 없음(F-기록 대체)
- 재현: (1) given에 `id 3f2504e0-…`, `value 150`, `acknowledged 1` (2) `lnpl spec --run` → steps=1에서 failed (3) 동일 필드 값의 `payloads/r1.json`으로 `lnpl run --payload` → **completed**.
- 기대 vs 실제: run이 실행하는 payload는 spec도 실행 vs 매니페스트에 `id …`가 실렸는데도 러너는 validate에서 실패(probe로 확인한 사유: `missing required field 'id'`). 러너는 기본값을 채우지 않으며 given의 UUID 적용이 유실된다.
- 증적: evidence/08-spec.md, raw/spec-run-2.txt, spec-run-3.txt, modeA-norow.json.

### F-6: given `no <field>`의 필드 스코프가 미문서화 — 타 엔티티 선언 필드 거부
- 단계: spec | 심각도: **minor** | 재시도: 0 | 우회: 있음(라인 제거)
- 재현: (1) Notification에 `priorNotification UUID` 선언 (2) given `no priorNotification` (3) `spec --run`.
- 기대 vs 실제: 에러 문구가 "`no <field>` naming a declared field"라 하므로 수용 vs `compile error: unsupported given: 'no priorNotification'` — 스코프가 워크플로 입력 엔티티로 한정되는 듯하나 references/spec.md에 규정 없음.
- 증적: evidence/08-spec.md, raw/spec-run-1.txt.

### F-7: RFC-0008의 comparator `==`/`!=`가 생성된 grammar.md에 없음
- 단계: authoring | 심각도: **info** | 재시도: 0 | 우회: 있음(`> 0`로 회피)
- 재현: rfcs/0008 §1 "Comparator 집합 … `==`, `!=`" vs references/grammar.md "비교 연산자: `<=` `>=` `<` `>`".
- 기대 vs 실제: RFC와 생성 참조 일치 vs 불일치 — 어느 쪽이 구현 정본인지 소스만으론 알 수 없어 회피 설계함(실동작 미검증).
- 증적: evidence/01-authoring.md.

### F-8: RFC-0008 §5.2가 약속한 examples/guarded.lnpl이 레포에 없음
- 단계: authoring | 심각도: **info** | 재시도: 0 | 우회: 있음(checkout 1줄 준거)
- 재현: `ls examples/` → checkout/login/shorten만 존재.
- 기대 vs 실제: RFC가 "새 시나리오 `examples/guarded.lnpl`"을 명시 vs 부재. 가드 사용 공식 예제는 checkout의 `when product.stock > 0` 한 줄뿐 — until·presence 예제 0건.
- 증적: evidence/01-authoring.md.

### F-9: 0라운드 until이 skipped 목록에 표기되지 않음 (when 스킵과 비대칭)
- 단계: modeA | 심각도: **info** | 재시도: 0 | 우회: 해당 없음
- 재현: R1(ack=1) 실행 → until 피가드 `read` 0회, `skipped=[]`.
- 기대 vs 실제: when 스킵은 `skipped=['wf.report.guard.1']`로 기록되므로 until 0라운드도 관측 표지를 기대 vs 무표지 — "실행 안 됨"의 두 경로가 트레이스에서 구별되지 않는다.
- 증적: evidence/04-modeA.md.

### F-10: `run --json` 결과에 저장소 행 수(rows) 신호가 없음
- 단계: modeA | 심각도: **info** | 재시도: 0 | 우회: 부분(spec 러너의 rows 단언 — 단 F-5로 사용 불가)
- 재현: raw/modeA-r1.json의 result keys = bindings/steps/skipped/… (rows 없음).
- 기대 vs 실제: create 효과를 행 수로 확인 가능 기대 vs steps/effects로만 간접 확인.
- 증적: evidence/04-modeA.md.

### F-11: 컴파일 진단에 파일:라인 위치 정보가 없음
- 단계: parse | 심각도: **info** | 재시도: 0 | 우회: 해당 없음(소스가 짧아 무영향)
- 재현: `lnpl compile` → `warning: declared-measured-only [perf.rate.notify] …`.
- 기대 vs 실제: 소스 위치 포함 기대 vs 노드 id로만 지칭. 코드·설명 품질 자체는 양호.
- 증적: evidence/02-compile.md.

### F-12: spec 러너가 실패 사유를 출력하지 않음
- 단계: spec | 심각도: **minor** | 재시도: 0 | 우회: 있음(`lnpl run`으로 별도 probe)
- 재현: `spec --run` 실패 시 출력 = `FAIL … completed (status=failed)` 뿐.
- 기대 vs 실제: failed_step/failure_reason 노출 기대 vs 무엇이 왜 실패했는지 부재 — F-5 진단에 별도 probe 실행이 필요했다.
- 증적: evidence/08-spec.md.

## 총평

이 케이스의 핵심 질문 — when/until 가드가 실제로 평가되는가 — 의 답은 **긍정적**이다:
비교식·presence·until 세 형태 모두 mode A/B에서 payload 값에 따라 분기가 갈렸고
(무음 통과 없음), 경계값(임계값 동일·0·음수)은 배제 경계로 일관되며, differential은
발화·스킵 경로 모두 EQUIVALENT였다. 그러나 도구 체인의 **무음 실패 모드 4건(major)**
— 런타임까지 잠복하는 미선언 이벤트 참조(F-2), 무경고로 반대 분기를 실행하는
`--field` 이름 불일치(F-3), spec 블록 무음 병합(F-4), run이 실행하는 payload를
실행하지 못하는 spec 러너(F-5) — 가 "조용히 틀리는" 경로를 여럿 남긴다. 재알림
억제는 presence 가드로 표현 가능했으나 `notify` 동사 부재(F-1)로 "발송"의 의미는
기록+이벤트로 근사된다. **판정: 가드 런타임 자체는 프로덕션 사용 가능 수준이나,
spec 검증 경로가 사실상 사용 불가(F-4·F-5)이고 무경고 함정이 축적돼 있어 플랫폼
전체로는 아직 프로덕션 부적합 — spec 러너 수리와 참조 해석의 컴파일 타임 이동이
선결 조건이다.**

자동화 후보 (wiki/testing 백로그): (a) until 라운드 수를 포함한 differential
(r7 경로 — 이번엔 r1·r2만 diff), (b) presence 가드 다중 선언 시 `--skip` 개별
제어 검증, (c) `==`/`!=` 실동작 확인(F-7 해소), (d) deadline 중단(`reason="deadline"`)
도달 케이스.

### 측정 순도 캐비앗

계획 단계에서 허용 문서(AGENTS.md, plugins/lnpl/skills/**, examples/) 외에
`impl/lnpl/cli.py`(run/build/diff 플래그), `impl/lnpl/repo_policy.py`(시드 행 =
payload 복사본), `impl/lnpl/interp.py`(가드 평가 경로), `examples/*.lir.json`·
`*.spec.json`을 열람했다. 해당 항목의 "발견 난이도" 측정은 오염(선확인)이며,
실행 중 probe 1건(F-5 진단)도 내부 지식 없이 재현 가능한 `lnpl run` 실험으로
수행했다. 어휘·문법 마찰과 실행 결과 측정은 유효하다. 또한 브리프가 인용한
"RFC-0008 G8" 식별자는 RFC-0008에 존재하지 않아 §2(가드 런타임 의미론)·
§3.1(payload 전달)로 매핑해 측정했다.

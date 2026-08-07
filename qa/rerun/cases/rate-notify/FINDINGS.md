# FINDINGS — rate-notify (재측정 run)

케이스: 임계값 기반 조건부 알림 (when/until 가드 런타임 재실측 + spec 검증 경로 재검).
환경: commit 6d84bd6 (#43~#50 구현 후 main), python3.13, lnpl 0.2.0,
LLVM(homebrew)+SDK 설정, dev_doctor rc=0 (evidence/00-env.md).
실행: 2026-08-07 14:1x~14:3x KST. 대조 기준: qa/cases/rate-notify/FINDINGS.md
(원 실측 2026-08-05, commit 713a4cba). 원 F-1~F-12 전건 판정은 DELTA.md.

## Scorecard

| 단계 | 결과 | 증적 경로 | 재시도 수 (원) |
|------|------|-----------|----------------|
| authoring | PASS | evidence/01-authoring.md | 0 (3) |
| parse | PASS | evidence/02-compile.md | 0 (0) |
| lower | PASS | evidence/03-ir-validate.md | 0 (0) |
| validate | PASS | evidence/03-ir-validate.md | 0 (0) |
| modeA | PASS | evidence/04-modeA.md | 0 (1) |
| modeB | PASS | evidence/05-modeB.md | 0 (1) |
| differential | PASS(r1·r2) / r7 DIVERGENT=#51 재현 | evidence/06-differential.md | 0 (0) |
| openapi | PASS | evidence/07-openapi.md | 0 (0) |
| spec | **PASS** | evidence/08-spec.md | 1 (3, 상한 도달 FAIL) |

**핵심 측정 결과: 원 유일 단계 FAIL이던 spec이 원형 3시나리오(정상/에러/경계)로
8/8 단언 통과(rc=0)했다 — 반전 확정.** 가드 3형태(when 비교식·when presence·until)는
mode A/B 양쪽에서 여전히 전부 실제 평가되며 참/거짓 신호가 갈렸다(무음 통과 없음).
경계 실측(임계값 동일=배제 경계, 0·음수 정상 비교, until 16라운드 round_cap)도
원과 동일. 원 4대 무음 실패 모드(F-2 미선언 이벤트 잠복, F-3 --field 무경고 무시,
F-4 spec 블록 병합, F-5 given id 유실)는 **전부 컴파일/CLI 타임 거부 또는 정상
동작으로 해소**됐다. until의 mode B 차등 관측은 r7에서 DIVERGENT — 오픈 버그
#51 재현(실행 순서는 양모드 동일, 관측기 층 비대칭), 잔존으로 추적 중.

## Frictions (재측정에서 새로 만난 것)

### N-1: `--strict`가 진단 종류를 구분하지 않아 상존 경고가 있는 소스에서는 스킵 감지 신호로 쓸 수 없음
- 단계: modeA | 심각도: **info** | 재시도: 0 | 우회: 있음(JSON skipped 레코드 사용)
- 재현: (1) performance 선언이 있는 소스(본 케이스 — declared-measured-only 경고 상존)
  (2) `lnpl run --payload payloads/r1.json --strict` (스킵 없는 정상 런) (3) rc 관찰.
- 기대 vs 실제: 가드 스킵이 있을 때만 rc=2를 기대할 수 있으나, 실제는 모든 진단이
  rc=2를 유발하므로 perf 경고가 상존하는 소스에선 전 런 rc=2 — 스킵 유무를 exit
  code로 구분 불가. help 문구("exit 2 if any diagnostic is reported")대로의 동작이라
  결함은 아니고, 용도 한계의 기록.
- 증적: evidence/04-modeA.md (raw/modeA-r{2,7}-strict.*).

## 총평

이 재측정의 핵심 질문 — #43~#50 구현이 원 12마찰을 실제로 해소했는가 — 의 답은
**대부분 긍정**이다: major 4건(F-2·F-3·F-4·F-5) 전건 해소, info 3건(F-7·F-8·F-9)
해소, F-12(minor) 해소 — 합계 **해소 8**. 부분 1(F-10 — run --json엔 rows가 여전히
없으나 spec 러너 우회로가 실작동), 잔존 3(F-1 동사 어휘, F-6 given 스코프 미문서화,
F-11 진단 위치 정보) + until mode B 차등 발산(#51, 관측기 층)이 남았다. 잔존은
전부 minor/info로, 원 총평의 선결 조건 두 가지("spec 러너 수리와 참조 해석의
컴파일 타임 이동")가 **둘 다 충족**됐다. **판정: 가드 런타임 양호 유지 + spec
검증 경로 사용 가능 + 무경고 함정 4종 제거 — 이 케이스 기준으로 원 "플랫폼
부적합" 판정을 뒤집을 근거가 확보됐다** (케이스 횡단 판정은 r5 소관).

### 측정 순도 캐비앗

이번 재측정에서 `impl/`은 열람하지 않았다. 지식 소스는 AGENTS.md,
plugins/lnpl/skills/** (lnpl-authoring references, lnpl-spec), examples/guarded.lnpl,
CLI `--help`(run/build — 증적에 원문 보존), 그리고 원 실측 기록
qa/cases/rate-notify/**(대조 기준, 읽기 전용)뿐이다. 원 실측이 오염으로 표기한
항목(발견 난이도 측정)은 이번 판정 대상이 아니며, 전 판정은 실행 결과 증적
기반이다. 재측정 소스·payload는 원형과 동형(워크플로 8스텝 diff 무출력,
payload 7종 cmp 동일 — evidence/01-authoring.md).

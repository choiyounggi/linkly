# RFC-0022: mode B의 관측 표면

## Status

- Status: **Accepted** (RFC-0022, 2026-08-08)
- Updates: **RFC-0014 §2.5·§2.6** — 스킵 진단의 방출 지점을 mode B까지 넓히고, 그
  진단의 그레인(스텝 단위)과 `where`(워크플로 id)를 규정한다. §2.4의 레코드 정의와
  §2.6의 복원 규칙 자체는 바꾸지 않는다.
- Updates: **RFC-0021 §코드 → 등급 (정본)** — 코드 하나를 추가한다:
  `validation-sample-derived` = `info`. 사다리와 `--strict` 문턱의 의미는 그대로다.

Supersedes는 없다. 두 상류 RFC의 계약을 **넓히기만** 한다 — 기존 문장을 무효로
만드는 조항이 없으므로 둘의 Status는 Accepted로 유지된다(RFC-0007 §2.2).

번호가 0022인 이유: 0021까지 점유됐다. RFC-0007 §3은 번호 재사용을 금지한다.

언어 워킹네임은 **LNPL**(소스 확장자 `.lnpl`)이다.

## Motivation

2026-08-07 재측정(`qa/rerun/REPORT.md` §6.2)이 mode B의 관측 표면에서 세 가지를
보고했다. 셋 다 이 워크트리에서 재현했다.

| 근거 | 심각도 | 관측 |
|------|--------|------|
| r1 N-2 / r1 F-5 | minor / 부분 | `build --run`이 거짓 가드로 실행되지 않은 스텝을 **아무 방식으로도** 말하지 않는다 — 같은 입력의 `run`은 진단·첫 줄 표기·스킵 레코드로 세 번 말한다 |
| r1 N-3 | minor | `--field`가 검증 경로에 도달하지 않는데, 그 사실이 출력에 없어 "refinement 미집행"으로 읽힌다 |
| r2 N-1 | minor | 합집합 payload의 동명 필드에 모드 간 비대칭 값을 `run` 채널로 주입할 수 없다 |

핵심은 계약의 **부재가 아니라 표면의 부재**였다. RFC-0014 §2.6은 이미 "모드 B는
'계획에 있으나 출력에 없는 스텝'으로 같은 항목을 복원한다"고 규정하고 있고,
`differential.observe_mode_b`는 그 복원을 수행하고 있었다. 복원을 부르지 않는 것은
`lnpl build`였다 — 즉 `skipped[]` 계약이 mode A 전용이었던 것이 아니라, **관측기를
거치지 않는 사용자에게 도달할 경로가 없었다.**

세 번째 항목은 두 번째와 같은 뿌리를 갖는다. r2 N-1의 정식 우회 경로는 mode B
`--field`이고(그것만이 `input.X`와 `entity.X`를 독립 주입한다), 그 우회의 결과가
바로 첫 번째 결함이 삼키던 **이름 없는 부재**였다. 초과 환불의 거부가
`status completed` / `exit=0`으로 나왔다. 하나를 표면화하면 나머지 하나가 스스로를
설명한다.

부수적으로 같은 계열의 드리프트를 하나 더 발견해 고쳤다:
`docs/ENFORCEMENT-MATRIX.md` §C가 진단 코드 다섯 개를 전부 `warning`이라고 적고
있었다(RFC-0021 이후 셋은 `info`다). 그 표를 지키던 검사가 문서의 주장을 그대로
단정하고 있어서, 코드와 어긋난 상태로 초록이었다.

## Guide-level Explanation

mode B의 스킵 관측은 **바이너리가 말하는 것이 아니라 관측기가 복원하는 것**이다.

`scf.if`는 가드가 거짓일 때 `lnpl_step`을 호출하지 않는다. 그래서 바이너리의
stdout에는 그 스텝의 줄이 아예 없고, 부재는 그것이 빠진 목록 없이는 아무 뜻도
아니다. 그 목록이 컴파일된 **스텝 계획**이고, 복원은 "계획에 있고 출력에 없는
피가드 스텝"을 고르는 일이다.

이 판정을 하는 함수는 하나다 — `backend.restore_skips()`. 두 곳이 그것을 부른다:
차동 검사(`differential.observe_mode_b`)와 CLI(`cli.cmd_build`). 같은 사실을 두 번
유도하지 않는 것이 규범이다. 바이너리 stdout에 스킵 라인을 새로 찍는 방안을 기각한
이유도 여기에 있다(§Alternatives).

`--field`에 대해서는 반대 방향의 정직함이 필요하다. 그 플래그는 비교 가드의 i64
파라미터를 몬다. refinement 검증은 mode B에서 **빌드 시점에** 결정되고, 그 입력은
파생 sample payload이므로 어떤 `--field` 값도 refinement를 실패시킬 수 없다. 그래서
`build`는 Validation effect를 가진 워크플로를 빌드할 때마다 그 사실을 `info` 진단으로
말한다 — 값이 연결돼 있지 않은 레버를 조용히 두면, 균일한 출력이 "집행되지 않음"으로
읽힌다.

합집합 payload의 동명 필드는 **표현 불가**를 계약으로 적는다. `run`의 payload는 하나의
평면 네임스페이스이고 시드된 행은 그 payload의 복사본이므로, `input.X ≠ entity.X`인
실행은 그 채널에 존재하지 않는다. 그것을 강제하는 채널은 mode B `--field`뿐이며,
그 채널에서의 거부는 위의 복원 경로로만 읽힌다.

## Reference-level Specification

### 표 1 — 관측 신호별 모드 대조

각 신호가 두 모드에서 무엇으로 존재하는지, 그리고 RFC-0004의 4분류 비교 대상인지.

| 신호 | mode A | mode B | 비교 대상인가 |
|------|--------|--------|---------------|
| `스킵 레코드` | 있음 — 가드 단위, `guard` 포함 | **복원**(계획 − 출력) — 스텝 단위 | 예 — 실행 순서 분류(1/4) 안, `guard` 제외한 4키 투영 |
| `스킵 진단` | `guard-skipped-steps` — 가드당 1건 | `guard-skipped-steps` — 스텝당 1건 | 아니오 — 진단 채널은 4분류에 없다 |
| `진단 기계 판독` | `run --json`의 `diagnostics[]` | 없음 | 아니오 — 잔여(표 3) |
| `Validation 결과를 구동하는 입력` | `run --payload` | 빌드 시점 파생 sample payload | 아니오 — 값 차원의 허용된 비대칭 |
| `동명 필드 독립 주입` | 없음 — 평면 합집합 payload | `--field <qualified.name>` | 아니오 — 표현 가능성의 차이 |

두 모드의 `스킵 레코드`는 `{mode, condition, step, rounds}` 네 필드에서 **같아야
한다**. `guard`(IR 노드 id)는 mode B가 원리적으로 생산할 수 없으므로 비교에서
제외한다(RFC-0014 §2.4). mode A는 레코드 하나를 그 `steps` 수만큼 펴고, mode B는
복원으로 같은 항목을 만든다.

`스킵 진단`의 그레인 차이는 **의도된 것이다.** mode A는 어떤 가드가 어떤 스텝들을
소유하는지 알고 있어 가드당 한 건을 낸다. mode B의 관측 표면에는 가드가 없고 계획된
스텝만 있으므로, 가드 단위로 묶으면 갖고 있지 않은 정보를 발명하게 된다. 같은
이유로 mode B 진단의 `where`는 가드 노드 id가 아니라 **워크플로 id**다 — 그것이 mode
B가 정직하게 지목할 수 있는 가장 세밀한 노드 id다.

### 표 2 — 상태 모델 diff

두 모드가 모형하는 상태가 다르므로, 기본 입력에서의 `EQUIVALENT`는 "모형되지 않은
상태가 결과를 결정하지 않는 입력에서 두 모드가 일치한다"만 뜻한다. 각 차원을
결정하게 만드는 입력은 따로 읽어야 한다.

| 상태 차원 | mode A | mode B | 이 차원을 결정하게 만드는 입력 |
|-----------|--------|--------|-------------------------------|
| `저장소 행` | 모형함 — `FakeRepository`/드라이버 | 미모형 — 시드 규칙에서 정적 파생 | `--no-row`, 또는 같은 키를 두 번 create |
| `캐시` | 모형함 — TTL을 집행한다 | 미모형 — 예산 유무만 정적 판정 | 캐시-TTL 예산 없는 `CacheAccess set` |
| `시계` | 모형함 — 주입 클럭 | 미모형 — 조건 필드를 i64로 인코딩 | 창 경계를 넘는 instant |
| `세션·인증` | 선언만 — UNENFORCED | 선언만 — 동일 | `serve --jwt-secret-env` (mode B 대상 아님) |
| `가드 노드 id` | 있음 — IR 노드 id | 없음 — `step <index> <name>`뿐 | 없음 — 비교에서 제외한다 |

`저장소 행`이 미모형인 것의 따름정리가 동명 필드 문제다. `run`의 payload는 평면
합집합이고 시드된 행은 계약상 그 payload의 복사본이므로
(`repo_policy.default_rows`, 그리고 `differential._check_rows_are_reproducible`가
다른 값을 가진 행을 아예 거부한다), `input.X ≠ entity.X`인 실행은 `run` 채널에서
**표현 불가**하다. 그 차원을 강제하는 정식 채널은 mode B의
`--field <qualified.name>` 하나이며, 그 실행에서의 거부는 표 1의 `스킵 레코드`
복원 경로로만 관측된다. 표현할 수 없는 입력을 "일치"로 세지 않는다 — 미검증이다.

### 표 3 — 남는 공백

이 개정이 **닫지 않는** 것들. 정직하게 적는 것까지가 이 RFC의 범위다.

| 잔여 | 무엇이 남는가 | 왜 지금 닫지 않는가 |
|------|---------------|---------------------|
| `bare-binary` | `lnpl`을 거치지 않고 바이너리만 실행하면 스킵은 여전히 침묵한다 | 복원은 컴파일된 계획을 손에 든 관측기만 할 수 있다. 바이너리에 계획을 실어 찍게 하는 것은 §Alternatives에서 기각한 두 번째 채널이다 |
| `build --json 없음` | mode B 스킵·진단의 기계 판독 채널이 없어 CI가 등급별로 게이트를 걸 수 없다 | 이슈 #55의 완료 기준 밖이고, 채널 shape은 `run --json`과 맞춰야 한다. 후속에서 둘을 함께 정한다 |
| `build --strict 없음` | 스킵이 있어도 rc는 0이며 승격 경로가 없다 | 같다 — `--strict` 문턱(RFC-0021)을 `build`로 넓히는 것은 별도 결정이다 |
| `가드 단위 그룹핑 없음` | mode B는 어떤 가드가 여러 스텝을 함께 건너뛰었는지 묶어 말하지 못한다 | 관측 표면에 가드가 없다(표 2 마지막 행). 묶으려면 없는 정보를 발명해야 한다 |

## Examples

RFC-0007 §6대로 골든 "Login"을 **유지한 채**, 골든이 다루지 않는 가드에 대해서만 골든
인접 예제 `examples/guarded.lnpl`(RFC-0008 §5.2의 가드 시나리오)를 추가로 제시한다.
골든 자체는 확장하지 않는다.

### 골든 "Login" — 가드 없는 워크플로에서의 이 계약

Login에는 가드가 없고 `validate input`이 있다. 그래서 이 개정의 두 표면 중 하나만
나타난다 — 스킵은 0건이고, `--field` 도달 범위 진단은 나온다. 정본 정의는
`plans/rfc-suite/plan.md` §골든 시나리오 "Login"이며 여기서 재정의하지 않는다.

```
$ lnpl build examples/login.lnpl --run
```

stdout — 여섯 스텝 전부 실행되고 스킵 줄이 없다:

```
native binary: .../module
step 1 validate input
effect validate input Validation
step 2 authenticate
effect authenticate RepositoryCall
step 3 cache user
effect cache user CacheAccess
step 4 generate token
step 5 audit login
step 6 return token
status completed
exit=0
```

stderr — 빌드 사실 한 건만:

```
info: validation-sample-derived [wf.login] validate input — mode B decides the
Validation outcome at build time from a derived sample payload, which is valid by
construction — so no --field value can make a refinement fail here. --field drives
comparison guards only; use `lnpl run --payload` (mode A) to exercise refinement
enforcement
1 info, 0 warning(s), 0 error(s)
```

이것이 표 1의 `Validation 결과를 구동하는 입력` 행이 Login에서 갖는 모습이다. 가드가
없는 워크플로는 `스킵 레코드` 행에 대해 아무것도 관측하지 않는다 — 그 부재가
정상이라는 것이 아래 두 예제의 대조군이다.

### r1 N-2 — 거짓 가드의 before / after

```
$ lnpl build examples/guarded.lnpl --run --field token.retryBudget=0
```

**두 스트림을 나눠 적는다.** 합쳐 적으면 버퍼링에 따라 순서가 달라지는 전사가 되고,
그 전사는 코드가 아니라 실행 환경을 기술하게 된다.

before — stdout에 `step 4 call token`이 없고, 그 사실을 말하는 것도 없다. stderr는
비어 있었다:

```
native binary: .../module
step 1 validate token
effect validate token Validation
step 2 find token
effect find token RepositoryCall
step 3 cache token
effect cache token CacheAccess
status completed
exit=0
```

after — stdout에서 같은 부재가 이름을 갖는다:

```
native binary: .../module
step 1 validate token
effect validate token Validation
step 2 find token
effect find token RepositoryCall
step 3 cache token
effect cache token CacheAccess
status completed
  (1 step(s) skipped by guard, restored from the compiled plan)
  skipped by `when token.retryBudget > 0`: call token
exit=0
```

그리고 stderr에 진단 **두 건**이 나간다 — 이 워크플로의 `validate token`이
Validation effect를 갖기 때문에 §Guide-level의 `--field` 진단도 함께 나온다:

```
info: validation-sample-derived [wf.retrieve.with.cache] validate token — mode B
decides the Validation outcome at build time from a derived sample payload, which is
valid by construction — so no --field value can make a refinement fail here. --field
drives comparison guards only; use `lnpl run --payload` (mode A) to exercise
refinement enforcement
1 info, 0 warning(s), 0 error(s)
warning: guard-skipped-steps [wf.retrieve.with.cache] token.retryBudget > 0 — the
`when` guard did not run call token; mode B's binary prints nothing for a step it
skips, so this record is restored from the compiled step plan (RFC-0014 §2.6)
0 info, 1 warning(s), 0 error(s)
```

`validation-sample-derived`는 빌드 사실이므로 빌드 직전에, `guard-skipped-steps`는
실행 사실이므로 실행 뒤에 나온다. 두 진단이 각자 자기 요약 줄(`N info, ...`)을 갖는
것은 `_emit_diagnostics`를 두 번 부르기 때문이고, 그것이 두 사실을 구분해 읽게 한다.

가드가 참인 실행(`--field token.retryBudget=1`)은 스킵 줄도 `guard-skipped-steps`도
내지 않는다(`validation-sample-derived`는 그대로 나온다 — 그것은 가드와 무관한 빌드
사실이다). 두 실행의 최상위 신호가 다르다는 것이 이슈 #44가 mode A에 세운 기준이고,
이제 mode B도 그것을 만족한다.

### r1 N-3 — `--field`의 도달 범위

`examples/shorten.lnpl`의 `validate input`은 세 refinement facet을 집행한다. 그
워크플로에는 비교 가드가 없으므로 유효한 `--field` 이름이 하나도 없다:

```
$ lnpl build examples/shorten.lnpl --run --field slug=1     # 종료 코드 2
```

stderr(둘 다 stderr이므로 이 순서는 결정적이다). stdout은 비어 있다 — 거부가 빌드보다
먼저 오므로 `native binary:` 줄에 닿지 않는다:

```
info: validation-sample-derived [wf.shorten] validate input — mode B decides the
Validation outcome at build time from a derived sample payload, which is valid by
construction — so no --field value can make a refinement fail here. --field drives
comparison guards only; use `lnpl run --payload` (mode A) to exercise refinement
enforcement
1 info, 0 warning(s), 0 error(s)
error: --field name(s) slug do not match any comparison-guard field of workflow
wf.shorten (valid: (none))
```

before는 `error:` 줄만 있었다. 그 줄은 참이지만 **왜**를 말하지 않고, 그래서 읽는
쪽이 "refinement가 집행되지 않는다"로 옮겼다. 진단이 rc 2보다 먼저 나오는 것은
의도다 — 오독이 일어난 경로가 바로 이 거부 경로다.

### r2 N-1 — 동명 필드의 독립 주입과 그 거부

`qa/rerun/cases/payment-refund`의 `wf.refund.request`는
`when input.requestedAt - payment.createdAt <= 30d and input.amountCents <= payment.amountCents`
를 갖고, `amountCents`가 Payment·Refund 양쪽에 선언돼 있다. `run` 채널에서는 두 값이
항상 같다(표 2). mode B에서만 갈라진다:

초과 환불(`input.amountCents=9` > `payment.amountCents=5`), stdout:

```
native binary: .../module
step 1 read payment
effect read payment RepositoryCall
status completed
  (1 step(s) skipped by guard, restored from the compiled plan)
  skipped by `when input.requestedAt - payment.createdAt <= 30d and input.amountCents <= payment.amountCents`: create refund
exit=0
```

부분 환불(`input.amountCents=3`), stdout — `create refund`가 실행되고 스킵은 0건이다:

```
native binary: .../module
step 1 read payment
effect read payment RepositoryCall
step 2 create refund
effect create refund RepositoryCall
status completed
exit=0
```

이 워크플로에는 Validation effect가 없으므로 `validation-sample-derived`는 나오지
않고, 초과 환불 실행의 stderr에는 `guard-skipped-steps` 한 건만 있다. before에는 두
실행 모두 `status completed` / `exit=0`이었고 차이는 `step 2` 줄의 유무뿐이었다 —
거부가 관측되지 않았다.

## Alternatives

### 바이너리 stdout에 스킵 라인을 방출하는 안 (기각)

`runtime.c`에 실행된 인덱스를 기록하고 종료 시 컴파일된 계획과 대조해
`skip <index> <name>`을 찍게 하면, `lnpl`을 거치지 않는 사용자도 스킵을 본다
(표 3의 `bare-binary`가 닫힌다). 세 가지 이유로 기각한다.

첫째, **RFC-0014가 이미 같은 형태를 기각했다** — §Alternatives "진단 대신 새 출력
채널을 만드는 안". 스킵은 "플랫폼이 이 프로그램이 말한 것을 하지 않고 있다"는
클래스의 사실이고, 그것을 위한 채널은 이미 있다. 두 번째 채널은 그 채널이 해결한
문제(같은 사실의 두 가지 표현)를 한 단계 위에서 재생산한다.

둘째, **진실 소유자가 둘이 된다.** 지금은 `backend.restore_skips()` 하나가 판정하고
차동 검사와 CLI가 그것을 읽는다. 바이너리가 자기 판정을 찍기 시작하면, 그 판정과
관측기의 판정이 어긋날 수 있는 면이 새로 생긴다 — 그리고 어긋남은 차동 검사가
잡아야 할 결함을 차동 검사 자신의 입력에 심는 것이 된다.

셋째, **비용이 골든에 닿는다.** `scf.if`의 else 분기로 마커 op를 내는 변형은 컴파일된
모듈을 바꾸므로 `impl/tests/golden/*.std.mlir`가 깨진다. 그 픽스처는 변경 이전
스냅샷이고 재생성하지 않는다(이슈 #44). `runtime.c`만 고치는 변형은 골든을 건드리지
않지만 첫째·둘째 이유가 그대로 남는다.

### 복원을 mode A 쪽으로 접는 안 (기각)

mode B의 스킵을 아예 비교에서 빼고 mode A의 레코드만 신뢰하는 안. 그러면 가드
불일치와 하강 불일치를 구별할 수 없다 — 스킵된 스텝과 애초에 없던 스텝이 둘 다
짧아진 `order`로 나타나기 때문이다(RFC-0008 §5가 스킵 집합을 실행 순서 분류에 넣은
이유가 이것이다).

### `rejected`를 제3의 terminal status로 두는 안 (재기각)

RFC-0014 §Alternatives가 반례와 함께 기각했고 이 개정은 그 판단을 바꾸지 않는다.
어떤 가드가 정책 게이트이고 어떤 가드가 최적화인지 **선언**할 문법이 없는 동안,
런타임이 대신 판정하는 것은 추측이다.

## Open Questions

1. **`build`의 기계 판독·게이트 채널.** 표 3의 `build --json 없음`과
   `build --strict 없음`은 함께 결정되어야 한다 — `run --json`의 `diagnostics[]`
   shape과 RFC-0021의 `--strict=<level>` 문턱을 mode B로 넓히는 하나의 개정이다.
   그때까지 CI에서 mode B의 스킵을 게이트하는 방법은 없다.

2. **`bare-binary` 공백의 소유자.** 컴파일된 산출물을 `lnpl` 없이 배포하는 사용법을
   지원할 것인지 자체가 미결이다. 지원한다면 계획을 산출물에 함께 실어야 하고, 그것은
   위에서 기각한 두 번째 채널과 같은 문제를 다시 연다.

3. **가드의 의도 선언.** RFC-0014 Open Question 1을 그대로 계승한다. 어떤 스킵이
   비즈니스적 거부인지는 여전히 읽는 쪽이 판정하며, 가드를 정책 게이트로 선언하는
   문법이 도착하면 표 1의 `스킵 레코드`가 그 판정의 입력이 된다.

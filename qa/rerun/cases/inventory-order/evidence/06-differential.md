# evidence/06-differential — mode A vs mode B 동치 검사 (재측정 Task 04)

재시도 수: 0

D9(differential 인용 규율): 양측이 모델링하는 상태를 diff하면 비대칭 차원은
② 저장소 시드, ⑤ 검증 payload 두 개다(mode B는 --field로 가드 값만 받고
저장소·payload는 하네스 시드에 의존). 아래에 기본 입력 판정과 차원별 강제 입력
판정을 **별도 줄로** 기록한다.

## 기본 입력

```
$ lnpl diff <src> --workdir .claude/tmp/qa-r1/diff
# rc=0
PASS 1/4 execution order — 5 step(s): validate order -> find product -> create order
       -> set product.stock to product.stock - input.quantity -> update product | 0 skip(s)
PASS 2/4 policy outcome — status=completed
PASS 3/4 observability signals — 5 effect(s) per step match
PASS 4/4 masking — no secret marker in either mode's output
differential: EQUIVALENT
```

기본 입력 판정: **EQUIVALENT (4/4)** — 가드 참 경로 5스텝(Assignment 포함)에서
양 모드 일치. (이 판정의 문자 그대로의 범위: 비대칭 상태가 결과를 결정하지 않는
입력에서의 합의.)

## 강제 입력 1 — 가드 거짓 경로 (`--payload pS2.json`, stock=1 qty=2)

```
PASS 1/4 execution order — 2 step(s): validate order -> find product | 3 skip(s)
PASS 2/4 policy outcome — status=completed
differential: EQUIVALENT
```

강제 입력 판정(가드 거짓): **EQUIVALENT** — 스킵 3건이 diff 관측에 계수됨
(`| 3 skip(s)` — 원 실측 diff에는 skip 계수 자체가 없었다).

## 강제 입력 2 — refinement 경계 (`--payload pS4.json`, qty=0)

```
PASS 1/4 execution order — 1 step(s): validate order | 0 skip(s)
PASS 2/4 policy outcome — status=failed
differential: EQUIVALENT
```

강제 입력 판정(검증 실패): **EQUIVALENT — 양 모드 모두 failed.** refinement
min=1이 **mode B에서도 집행**됨을 이 입력이 증명(evidence/05 S4의 --field 관측과
상보 — 채널이 다르면 도달 경로가 다르다). 동일 실패의 원인 일치는 1/4 실행
순서(validate에서 정지)로 확인.

## 강제 입력 3 — 빈 저장소 (`--no-row`)

```
PASS 1/4 execution order — 2 step(s): validate order -> find product | 0 skip(s)
PASS 2/4 policy outcome — status=failed
differential: EQUIVALENT
```

강제 입력 판정(저장소 차원): **EQUIVALENT — 양 모드 모두 find에서 failed.**

판정: PASS — 기본 1 + 강제 3 전부 EQUIVALENT. 원 실측(기본 입력 4/4만)보다
증거 범위가 넓다: 가드 거짓·검증 실패·빈 시드 차원 각각에서 두 모드가 같은
지점에 정지한다. 미검 차원: 없음(이 케이스의 상태 차원 두 개 모두 강제됨).

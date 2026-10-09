# FINDINGS — s5-baseline-fastapi

환경: 커밋 264e3442d653e5534d827687ebac5ede956e801a(linkly worktree 참고용, 이 케이스는 그 내용을 쓰지 않음), lnpl 미사용(대조군), python 3.13.1, 드라이버 none(fastapi/pydantic/sqlite3/pytest/httpx/import-linter — evidence/00-env.md), dev_doctor 해당 없음(범위 밖)
조건: 블랙박스(requirements/README.md §2, s5.md), impl/ 열람 0회, impl/ 수정 0건, linkly 문서(README/AGENTS/docs/rfcs/skills) 열람 0회 — requirements/{README,FINDINGS-SCHEMA,s1,s5}.md만 읽음

## Scorecard

| 단계 | 결과 | 증적 경로 | 재시도 수 |
|------|------|-----------|-----------|
| authoring | PASS | evidence/01-authoring.md | 24라운드 중 재시도(실패→재실행) 6건: round2(cwd 설정 미발견) round6~8(import-linter 간접 임포트, 3회) round12(테스트 SQL ambiguous-column, 1회) round23(독립 리뷰가 지적한 테스트 커버리지 갭 수정, 1회) |
| lint·type (import-linter) | PASS | evidence/02-lint-type.md | 3(설정 경로 1 + 아키텍처 수정 2 — 상세는 F-1) |
| pytest | PASS | evidence/03-pytest.md | 2(round12 ambiguous-column, round23 독립 리뷰 지적 커버리지 갭 — 상세는 F-5) |
| openapi | PASS | evidence/04-openapi.md | 0 |
| serve(실 HTTP) | PASS | evidence/05-serve.md | 0 |

## 요구사항 커버리지

| R | 요구 | 판정 | 근거(evidence 경로 + 실행 출력 인용) |
|---|------|------|--------------------------------------|
| R1 | 코드베이스 구조(팀별 분리 + Stock 비가시성) | 충족 | evidence/02-lint-type.md: 위반 삽입 시 `BROKEN`(rc=1), 제거 시 `KEPT`(rc=0) |
| R2 | 주문 생성(재고 검증·예약·전체 거부) | 충족 | evidence/03-pytest.md A1(on_hand 5→3, reservation 1행), A3(재고부족 시 reservation 0행, on_hand 5 유지) |
| R3 | 금액 계산(subtotal/discount/tax/total, 반올림) | 충족 | A1(3998/0/320/4318), A2(5997/600/432/5829) — evidence/05-serve.md curl 결과와 pytest 동일 |
| R4 | 상태 전이(합법/불법) | 충족 | `test_illegal_transitions` 15개 파라미터 케이스 + A6(shipped 후 cancel 409, 상태 유지) |
| R5 | 결제(금액 일치, PAN 미노출, 실패 시 무기록) | 충족 | A4(DB dump·응답·로그 3채널에서 PAN 부재 + last4 존재 대조), A5(0 payment 행, pending 유지), `test_simulate_failure` |
| R6 | 취소 원자성(환불+예약해제 all-or-nothing) | 충족 | A7(정상: 환불 1행 + on_hand 복원), `test_cancel_atomic_injected_failure`(주입 시 환불 0행 + on_hand 미복원 + 상태 paid 유지 — `X-Test-Fail-After: refund` + `ORDERHUB_TEST_HOOKS=1`) |
| R7 | 환불(부분·누적 한도·3회 제한·admin) | 충족 | A8(누적 5000>4318 거부, 2행), `test_refund_limit_boundary`(4번째 1센트 거부), 비관리자 첫 시도부터 403 |
| R8 | OpenAPI 3.1 + 실서버 curl | 충족 | evidence/04-openapi.md(`"openapi":"3.1.0"`, 경로 7개), evidence/05-serve.md(A1~A8 전부 curl) |
| R9 | A1~A8을 spec(pytest)으로, 저장소 단언 포함 | 충족 | tests/test_a1_a8.py 전 테스트가 sqlite3 직접 SELECT로 단언(SELECT 28회/테스트정의 16개, 파라미터화 포함 26 노드, 독립 리뷰 후 최종본) |
| R10 | 변경 요청(gift_wrap) | 충족 | evidence/06-change-request.md: 3파일 +18/-4줄, 1라운드, 기존 spec 0건 손상 |

## Frictions

### F-1: import-linter의 `forbidden` contract 기본값이 간접(transitive) import까지 검사해 정당한 조립 경로를 위반으로 잡음
- 단계: lint·type | 심각도: major | 축: doc
- 재현: `.importlinter`에 `orderhub.app`을 source_modules로 넣고 `orderhub.db`가 (스키마 초기화를 위해) `orderhub.orders.inventory`의 상수를 import하게 했더니, `PYTHONPATH=src .venv-s5/bin/lint-imports --config .importlinter`가 `orderhub.app -> orders.router -> orderhub.db -> orders.inventory` 경로를 위반으로 보고(rc=1). `db.py`에서 그 import를 없애도 `app -> orders.router -> orders.service -> orders.inventory`(같은 팀 내부의 정당한 라우터 조립)가 다시 걸림.
- 기대 vs 실제: R1의 의도("Stock을 orders 팀 **밖에서** 직접 참조하면 거부")를 direct-import 금지로 읽고 `.importlinter` forbidden contract를 그대로 썼는데, 실제로는 `allow_indirect_imports`(기본값 False)가 간접 경로까지 잡아 app의 정상적인 라우터 조립 자체가 불가능해짐.
- 재시도: 3(round 6~8) | 우회: 성공 — `.importlinter`에 `allow_indirect_imports = True` 추가(source: `.venv-s5/lib/python3.13/site-packages/importlinter/contracts/forbidden.py` docstring). 의미 손실 없음(직접 import 위반은 여전히 잡힘, evidence/02 재확인).
- 보완 제안: 이 축의 플랫폼(lnpl)이 팀 간 가시성 경계를 1급 문법으로 제공한다면(예: `internal` 선언 + 컴파일러가 "직접 참조"만 거부) 이런 서드파티 lint 도구의 기본 의미론을 역설계할 필요가 없다 — S1과의 직접 비교 포인트.

### F-2: `lint-imports`가 cwd 기준으로 설정 파일을 찾아 케이스 루트가 아닌 다른 디렉터리에서 실행하면 조용히 실패
- 단계: lint·type | 심각도: minor | 축: doc
- 재현: `cd src && ../.venv-s5/bin/lint-imports` → "Could not read any configuration"(rc=1, 계약 위반이 아니라 설정 파싱 실패).
- 기대 vs 실제: `lint-imports`가 `PYTHONPATH`처럼 프로젝트 루트를 자동 인식할 것으로 기대했으나, 실제로는 `--config` 명시가 필요.
- 재시도: 1 | 우회: 성공 — 케이스 루트에서 `--config .importlinter`로 실행. 의미 손실 없음.
- 보완 제안: 해당 없음(파이썬 생태계 도구의 일반적 관례이며 lnpl 플랫폼과 무관).

### F-3: 테스트 SQL의 ambiguous column name — 두 테이블이 같은 컬럼명(`amount`)을 가질 때 JOIN에서 미명시하면 sqlite3가 조용히 거부
- 단계: pytest | 심각도: minor | 축: rt
- 재현: `SELECT amount FROM refund r JOIN payment p ON r.payment_id = p.id` → `sqlite3.OperationalError: ambiguous column name: amount`(round 12).
- 기대 vs 실제: 테스트 작성 시 `refund.amount`만 있다고 가정했으나 `payment.amount`와 충돌.
- 재시도: 1 | 우회: 성공 — `r.amount AS amount`로 별칭 부여. 의미 손실 없음.
- 보완 제안: 정적 스키마 인지(컬럼 충돌을 컴파일 타임에 알려주는) SQL 계층이 있다면 이런 런타임 에러가 사라진다 — S1과의 직접 비교 포인트(트랜잭션 DSL이 컬럼명 충돌을 미리 검사하는지).

### F-4: FastAPI 번들 `TestClient`가 설치된 `httpx` 버전과 충돌 경고(향후 실패 가능성)
- 단계: pytest | 심각도: minor | 축: doc
- 재현: 모든 pytest 실행에서 `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead` 경고 출력(테스트 자체는 통과).
- 기대 vs 실제: `pip install fastapi pytest httpx`로 설치한 최신 조합이 서로 경고 없이 맞물릴 것으로 기대했으나, `httpx2`라는 별도 패키지가 필요하다는 안내가 나옴 — 지금은 경고뿐이지만 버전 정책이 바뀌면 깨질 잠재 결함.
- 재시도: 0(우회 안 함, 경고 수용) | 우회: 실패(시도 안 함 — 3회 상한 이전에 "지금은 영향 없음"으로 판단하고 다음으로 감)
- 보완 제안: 해당 없음(파이썬 생태계 패키지 간 버전 정합성 문제이며 lnpl과 무관 — 다만 이런 "설치 조합이 서로를 경고하는" 마찰 자체가 S1과 비교할 만한 데이터).

### F-5: 자체 검수로는 3건의 테스트 커버리지 갭을 발견하지 못함 — 독립 리뷰(test-quality-auditor)가 뮤테이션 테스트로 잡음
- 단계: pytest | 심각도: major | 축: llm
- 재현: 작성자 본인은 `pytest -q tests`가 23 passed(0 failed)라는 초록 신호만으로 R4/R5 커버리지가 충분하다고 판단했다. 별도 세션(test-quality-auditor)이 실제 뮤테이션(구현 코드를 의도적으로 망가뜨리는 것)으로 검증한 결과: (1) `payments/service.py`의 pending 가드를 제거해도 스위트가 그대로 초록 유지될 뻔한 경로(15개 illegal-transition 파라미터 중 "→paid" 3개를 엔드포인트가 없다고 착각해 스킵) (2) `ILLEGAL_PAIRS`를 구현체 자신의 `TRANSITIONS` dict에서 파생시켜, `orders/state.py`의 상태표를 느슨하게 고쳐도 파라미터화 자체가 조용히 줄어들며 초록을 유지하는 구조적 결함 (3) R5 "결제 실패 시 예약은 유지"에 대한 저장소 단언이 아예 없어 재고를 잘못 해제해도 잡히지 않는 경로.
- 기대 vs 실제: 작성자는 "초록 = 충분한 커버리지"로 여겼으나, 실제로는 테스트가 구현 세부사항을 자기참조하거나(2번) 엔드포인트 존재 여부를 스스로 오판해 스킵하는(1번) 구조적 약점이 있었다. 스펙(s1.md R4/R5) 자체를 다시 읽고 하드코딩했어야 할 곳을 구현 파일에서 편의상 가져다 쓴 것이 원인.
- 재시도: 1(round 23에서 4개 항목 모두 일괄 수정) | 우회: 성공 — `ILLEGAL_PAIRS`를 스펙에서 하드코딩, "→paid" 케이스를 실제 `/pay` 호출로 전환, R5 예약유지 단언 추가, 느슨한 상태코드 범위를 정확한 422로 교체. 의미 손실 없음(오히려 커버리지 확대: 26 passed/4 skipped, 남은 4개 skip은 진짜로 API에 없는 "pending 복귀" 뿐).
- 보완 제안: 이 발견 자체가 dev-loop의 "구현/평가 분리" 원칙("만드는 AI와 평가하는 AI를 반드시 분리 — 자기가 만든 것을 자기가 평가하면 항상 잘했다고 한다")이 실제로 유효함을 보여주는 정량 데이터다. S1이 lnpl의 spec 블록으로 같은 종류의 자기참조/스킵 결함을 구조적으로 막을 수 있는지(예: spec이 구현 상수를 import하지 못하게 하는 언어 차원 강제)가 S1 대비 비교 포인트.

## 케이스 판정

**Ship-with-known-issues** — R1~R10 전부 충족, pytest 26개 노드(26 passed, 4 skipped—모두 API에 없는 "pending 복귀"라 정상) 전부 통과(독립 리뷰가 지적한 커버리지 갭 수정 후 최종본), OpenAPI 3.1 실서버 curl로 A1~A8 확인, R10 변경 요청은 3파일 +18/-4줄·1라운드·기존 테스트 무손상으로 반영됨. known-issue로 남기는 조건:
1. F-1(import-linter 간접-import 기본 검사)은 이 케이스에 한정된 도구 설정 문제로 해소됐으나, 유사한 "팀 경계" 요구를 처음 구현하는 개발자라면 같은 3회 재시도를 반복할 수 있다(`allow_indirect_imports=True`를 표준 스캐폴드에 포함할 것을 권고).
2. F-4(httpx/TestClient 경고)는 현재 기능에 영향 없으나 의존성 버전을 고정하지 않으면(F-1 참고 `src/requirements.txt`로 고정함) 향후 깨질 수 있다.
3. F-5(자체 검수 대비 독립 리뷰가 3건의 테스트 커버리지 갭을 추가로 잡음)는 이번엔 즉시 수정됐지만, 이 세션 혼자였다면(독립 리뷰 없이) "23 passed, 0 failed"를 근거로 그대로 Ship 판정했을 것 — 소유자는 이 대조군 결과를 "자체 테스트의 초록만으로 커버리지를 신뢰하지 말 것"의 실측 근거로 참고.

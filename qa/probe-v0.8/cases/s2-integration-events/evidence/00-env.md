# 00-env — 환경 기준선

## 명령·결과

```
$ python3.13 -m venv .venv && .venv/bin/python --version
Python 3.13.1

$ git rev-parse HEAD
264e3442d653e5534d827687ebac5ede956e801a

$ .venv/bin/pip install -e .
rc=0 (46개 패키지 설치, lnpl==0.8.0 editable 빌드 성공)

$ .venv/bin/lnpl --version
lnpl 0.8.0
rc=0

$ bash scripts/dev_doctor.sh
rc=1
linkly 기여자 환경 진단
------------------------
python3.13  : Python 3.13.1
venv        : Python 3.13.1
jsonschema  : 설치됨
lnpl 스크립트: lnpl 0.8.0
MLIR/LLVM   : 없음 — mlir-opt mlir-translate
  → brew install llvm ...
sysroot 정합: .../MacOSX26.2.sdk
SDK 경로    : CPATH/LIBRARY_PATH 미설정
```

`dev_doctor.sh` rc=1은 MLIR/LLVM(mode B 네이티브 빌드) 미설치 때문 — 이 케이스는
계획상 mode A(`lnpl run`/`serve`/`relay`)만 쓰므로 blocker 아님. 참고:
`AGENTS.md`가 이 실패를 알려진 환경 문제(회귀 아님)로 명시.

## 읽은 문서 (D1 지식 진입점 — AGENTS.md 라우팅)

전건 목록, 파일 : 총 줄 수(전체/부분) : 읽은 범위:

| 파일 | 총 줄 수 | 읽은 범위 |
|------|---------|-----------|
| AGENTS.md | 71 | 전체(세션 초기 컨텍스트에 이미 로드됨) |
| plugins/lnpl/skills/lnpl-authoring/SKILL.md | 77 | 전체 |
| plugins/lnpl/skills/lnpl-authoring/references/verbs.md | 35 | 전체 |
| plugins/lnpl/skills/lnpl-authoring/references/declarations.md | 59 | 전체 |
| plugins/lnpl/skills/lnpl-authoring/references/grammar.md | 143 | 전체 |
| plugins/lnpl/skills/lnpl-authoring/references/types.md | 65 | 전체 |
| plugins/lnpl/skills/lnpl-authoring/references/spec.md | 93 | 전체 |
| plugins/lnpl/skills/lnpl-authoring/references/naming.md | 70 | 전체 |
| plugins/lnpl/skills/lnpl-authoring/references/patterns.md | 13 | 전체 |
| plugins/lnpl/skills/lnpl-authoring/cli-surface.md | 491 | 전체 |
| rfcs/0037-http-resilience.md | 284 | 전체 — `capability http` retry/backoff/jitter/breaker/path 정본 |
| rfcs/0040-event-consumption-contract.md | 408 | 전체 — `consume by`, CloudEvents 인입, 멱등/오류분류(3갈래), `lnpl relay` 정본 |
| rfcs/0027-network-driver-and-result-binding.md | ~600 | 부분(L340-380) — `--network` 예산 접합(remaining-deadline → timeout_ms), 네트워크 결과 바인딩 규칙 |
| rfcs/0036-policy-rollback-declaration-effect.md | ~150 | 부분(L30-70) — `policy retry`/`timeout`이 `con["retry"]`/`con["timeout_ms"]`를 직접 구동한다는 대조 서술 |
| docs/backends.md | 1011 | 부분(L1-45 세 계약, L164-230 아웃박스 스키마+drain/ack CLI) |
| docs/backends.md (§10 SPI 헤더만) | — | grep으로 절 제목만 확인, 본문 미독(§10 외부 드라이버 SPI — 이 케이스는 내장 http/sqlite만 씀) |
| plugins/lnpl/skills/lnpl-authoring/cli-surface.md 내 `outbox`/`relay` 서브커맨드 절 | (위 491줄에 포함) | 전체 |
| examples/linkhub.lnpl | 111 | 부분(L1-80) — pipeline/spec/refine 실사용 형태 확인 |
| docs/serving.md | 789 | grep만(미독) — `correlation_id`/`--log-format json` 존재 확인용, 본문 서술은 아직 안 읽음(task 04/05에서 필요시 정독) |
| qa/probe-v0.8/requirements/README.md | 85 | 전체(계약) |
| qa/probe-v0.8/requirements/s2.md | 41 | 전체(계약) |
| qa/probe-v0.8/requirements/FINDINGS-SCHEMA.md | 87 | 전체(계약) |

## 핵심 발견 (authoring 전 메모)

- `capability http`는 `method`(get/post/put/patch/delete)·`auth`·`retry N backoff <dur> [jitter]`·
  `breaker after N within <dur>`·`path "<template>"` 절을 받는다(RFC-0037). URL은 여기 없다 —
  `--endpoint NAME=URL`(CLI) 또는 `LNPL_ENDPOINT_<NAME>`로 런타임에 준다(#101 "URL은 환경, 계약은 선언").
  `capability http`에 `endpoint`/`base_url` 같은 절은 없다 — 자연스러워 보이지만 어휘 밖.
- 소켓 타임아웃(연결 실패·DNS·응답 지연)은 `NetworkDriver.call`이 `DriverError`로 던진다 — 5xx/4xx
  응답은 정상 반환(status로 관측). `retry`가 재시도하는 것은 접속 실패·408·429·5xx(501 제외)뿐이고,
  `timeout_ms`는 `policy timeout`이 선언되면 워크플로 잔여 데드라인, 없으면 기본 30_000ms.
  → B4(3초 지연, 1초 내 끊김)를 내려면 서비스에 `policy timeout 1s`를 선언해야 할 가능성이 큼 —
  다만 `policy timeout` 초과는 "워크플로 데드라인 초과 → 실행 실패"로 문서화돼 있어(declarations.md),
  타임아웃이 "실행 실패"로 가는지 "그 스텝만 실패 → fallback 분기로 이어지는지"는 task 03에서
  실측해야 하는 미해결 지점(R3의 핵심 마찰 후보).
- `event <Name> consume by <Workflow>`(RFC-0040)가 notifier 소비의 정본. 인입 라우트는
  `POST /-/events/<slug>`, CloudEvents v1.0 구조화 JSON만, `id`가 멱등키. 응답 3갈래:
  200(성공)/503+Retry-After(일시적, 재시도)/422(영구, dead-letter). `lnpl relay <src> --backend
  sqlite:<path> --target <base-url> [--once]`가 outbox→인입을 잇는 레퍼런스 구현.
- outbox 스키마(`lnpl_outbox`: seq/emission_id/event/payload/created_at/delivered_at)와
  `lnpl outbox drain`/`ack` CLI 확인. `emission_id`는 프로세스-로컬이라 재현 가능 — 행 정체성은
  `seq`. R5(outbox 발행이 주문 저장과 함께 커밋)는 `policy rollback` 절이 다루는 롤백 경계와
  맞닿아 있다(docs/backends.md ENFORCEMENT-MATRIX: `policy rollback`은 저장소 쓰기만 되돌리고
  NetworkCall은 되돌리지 않음 — `rollback-escapes-network` 경고).

## 워크플로 라운드 카운트

읽기 전용 단계 — authoring 라운드 0 (task 02부터 집계).

## Purity

```
$ git status --porcelain -uall | grep -v '^?? qa/probe-v0.8/cases/s2-integration-events/'
(no output)
```

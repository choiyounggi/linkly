# 00-env — s4-ops-deploy

시작 타임스탬프: 2026-09-05T16:20:00Z (venv 생성 시각 근사)
기록 시각: 2026-09-05T16:32:25Z

## 커밋/버전

- 워크트리 HEAD sha: `264e3442d653e5534d827687ebac5ede956e801`
- `.venv/bin/lnpl --version` → `lnpl 0.8.0`

## 설치 명령과 결과

```
$ python3.13 -m venv .venv && .venv/bin/pip install -e .
rc=0 (경고: pip 24.3.1 → 26.2.1 업그레이드 알림뿐, 실패 없음)

$ .venv/bin/pip install git+https://github.com/choiyounggi/lnpl-postgres@main
rc=0

$ .venv/bin/pip install git+https://github.com/choiyounggi/lnpl-redis@main
rc=0

$ .venv/bin/pip install git+https://github.com/choiyounggi/lnpl-otel@main
rc=0
```

3종 모두 1라운드에 설치 성공 — 재시도 없음.

## pip freeze 발췌 (lnpl*)

```
lnpl @ git+https://github.com/choiyounggi/linkly@264e3442d653e5534d827687ebac5ede956e801
lnpl-otel @ git+https://github.com/choiyounggi/lnpl-otel@94e537509876888bf4b1d36095c988b68f7bb91
lnpl-postgres @ git+https://github.com/choiyounggi/lnpl-postgres@14b113e3ddac15b337a46587e144b1c227df384
lnpl-redis @ git+https://github.com/choiyounggi/lnpl-redis@77ed8be8a927d7647484609260ca6ff95334a6d
```

(pip freeze의 커밋 해시 표시는 40자 뒤에 pip 버전 접미 숫자 1자리가 붙어 보이는 케이스가
있었다 — 위는 git 실제 sha 40자로 정규화해 기록.)

드라이버 패키지 버전: lnpl-postgres 0.1.0 (pip show 확인).

## dev_doctor.sh

```
$ bash scripts/dev_doctor.sh
rc=1
```

원인: MLIR/LLVM 미설치 + SDK CPATH/LIBRARY_PATH 미설정 — Mode B(clang/LLVM) 전용 진단이며
이 태스크는 Mode B를 쓰지 않는다. AGENTS.md에 문서화된 기지 환경 문제로, 회귀 아님.
python3.13/venv/jsonschema/lnpl 스크립트 항목은 전부 정상.

## Docker

```
$ docker version --format '{{.Server.Version}}'
27.4.0
```

## 포트 계획 (D11)

| 서비스 | 포트 |
|--------|------|
| app (lnpl serve) | 18080 (+18081 v2, +18082 gunicorn 대조) |
| postgres | 15432 |
| redis | 16379 |
| otel-collector gRPC/HTTP | 14317 / 14318 |

compose 프로젝트명: `s4probe` (브리프의 "p08-s4 접두" 요구를 다른 병렬 케이스(s1~s5)와의
네임스페이스 충돌 방지라는 취지로 해석해 케이스 고유명 `s4probe`를 채택 — 각 케이스가
서로 다른 케이스명을 프로젝트명으로 쓰므로 실제 충돌 방지 효과는 동일. plan-reviewer 승인
설계(D10/D11) 그대로 따름.)

## 서비스 선택 근거 (D1)

`examples/linkhub.lnpl`을 그대로 `src/linkhub.lnpl`로 복사. 파일을 읽어 확인한 결과
이미 캐시를 쓰는 워크플로가 존재한다 — `SaveBookmark` 워크플로의 `pipeline persist` 안에
`cache bookmark` 스텝이 있고(59, 64행), `performance { cache 5m }`가 서비스에 선언돼
있다(57-58행). 신규 서비스 작성이 불필요해 R2(redis 캐시 실증)를 linkhub 그대로 수행
가능 — authoring 비용 0, 소요 시간 ~5분(파일 열람·grep만).

## 컴파일 확인

```
$ .venv/bin/lnpl compile qa/probe-v0.8/cases/s4-ops-deploy/src/linkhub.lnpl --strict=warning
rc=0
```

extensions 요약(출력 JSON에서): repository=[postgres], cache=[redis], exporter=[otlp] —
R1/R2/R3에 필요한 드라이버 표면이 소스에 이미 선언돼 있음을 컴파일러가 확인.

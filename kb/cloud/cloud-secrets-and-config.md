---
id: cloud-secrets-and-config
category: Cloud
triggers:
  - 시크릿을 파일로 주입할 때
  - 시크릿 원천(환경변수·파일·프로바이더)
  - 시크릿 교체
  - lnpl.toml 프로필
  - secrets
  - LNPL_JWT_SECRET_FILE
  - vault
  - rotation
  - lnpl.toml
  - profile
version: 0.1.0
status: draft
sources:
  - docs/backends.md
  - docs/serving.md
  - impl/lnpl/config.py
---
# secrets and config

JWT 서명 시크릿은 설정에 **값**이 아니라 그 값을 가리키는 포인터만 남긴다 —
환경변수 이름, 파일의 절대경로, 또는 외부 프로바이더의 키 이름이다(근거:
docs/serving.md "시크릿 원천 — 환경변수·파일·프로바이더 (이슈 #192)").

이렇게 한다:

## 시크릿은 값이 아니라 이름과 경로로

- `--secret-env`/`--jwt-secret-env`는 환경변수 **이름**을 받는다. 값은
  명령줄로 받지 않는다 — 셸 히스토리와 `ps`에 남기 때문이다. 변수가 없거나
  32바이트 미만이면 서버가 소켓을 열기 전에 rc 2로 죽고, 메시지는 변수
  이름만 싣는다(근거: docs/backends.md "시크릿").

## 시크릿 원천

- JWT 서명 시크릿은 환경변수, 파일, 프로바이더 세 원천 중 하나에서 온다 —
  `lnpl serve --jwt-secret-env NAME` / `--jwt-secret-file PATH`,
  `build_app()`의 `LNPL_JWT_SECRET_ENV`/`LNPL_JWT_SECRET_FILE`,
  `lnpl.toml`의 `jwt = "NAME"` / `{ file = "..." }` / `{ provider = "...",
  key = "..." }`다(근거: docs/serving.md "시크릿 원천 — 환경변수·파일·프로바이더
  (이슈 #192)").
- 파일 원천은 절대경로여야 하고 끝 개행 하나만 벗긴다. 일반 파일만 열고
  디렉터리·FIFO·소켓·장치는 거부한다. 65536바이트를 넘으면 거부하고,
  HMAC 시크릿은 32바이트 이상이어야 한다. 파일은 기동 시 한 번만
  읽는다(근거: docs/serving.md "시크릿 원천 — 환경변수·파일·프로바이더
  (이슈 #192)").
- 오류 메시지는 역할 이름만 싣는다 — 경로도 파일 내용도 싣지 않는다
  (근거: docs/serving.md "시크릿 원천 — 환경변수·파일·프로바이더 (이슈
  #192)"). 파일 원천은 설정 쪽 표현으로 `SecretFileRef`에 담긴다(근거:
  impl/lnpl/config.py).

## 교체와 재조회

- 프로바이더 원천의 JWT 검증자는 현재 키 또는 이전 키와 맞으면 통과한다 —
  서명은 현재 키로만 한다. 기동 시 한 번 읽고, 이후 60초
  (`SECRET_REFRESH_S`)가 지난 뒤 처음 오는 검증·발급 요청이 다시 읽는다
  (single-flight)(근거: docs/backends.md "교체와 재조회").
- `/-/readyz` 검사 ⑤(`secret-provider`)도 프로바이더를 다시 읽는다 — 단
  마지막 읽기가 5초(`READYZ_REFRESH_FLOOR_S`)보다 최근이면 그 결과를
  재사용한다. 실패하면 503에 `secret-provider`를 싣고 마지막 정상 키를
  그대로 쓴다(근거: docs/serving.md "`/-/readyz` — readiness").
- 운영 절차: 프로바이더에서 새 값을 현재로, 직전 값을 이전으로 바꾼 뒤
  최소 60초를 기다려야 발급자가 새 키로 서명한다(근거: docs/backends.md
  "교체와 재조회").
- 이전 키는 발급자가 새 키로 바꾼 시점부터 가장 긴 토큰 수명이 지난 뒤에
  프로바이더에서 지운다 — 기본 수명 `DEFAULT_TTL_MS`(15분)에 검증의
  `LEEWAY_S`(60초)를 더해 기본값이면 16분 뒤다. 지운 뒤에도 워커가 다시
  읽기까지(최대 60초) 이전 키는 살아 있다 — 유출된 키를 끊으려면 기다리지
  않고 지금 지운다(근거: docs/backends.md "교체와 재조회").

## 외부 프로바이더 SPI

- Vault·클라우드 시크릿 매니저 같은 외부 저장소는 `lnpl.secrets`
  entry-points 그룹에 등록한다 — 시크릿 원천은 신뢰 경계라서 같은 이름의
  등록을 조용히 무시하지 않고 거부한다(근거: docs/backends.md "16. SPI:
  외부 시크릿 프로바이더 등록 (issue #192)").
- `SecretProvider`의 계약은 셋이다: `get(key) -> bytes`, `get_previous(key)
  -> bytes 또는 None`, `close()`. 값은 `bytes`만이고, 실패는 전부
  `DriverError`다(근거: docs/backends.md "계약").
- `env`와 `file`은 코어가 직접 읽는 원천이지 프로바이더가 아니다 — 같은
  이름으로 등록된 entry-point가 있으면 로드하지 않고 거부한다(근거:
  docs/backends.md "내장 이름은 절대 가려지지 않는다").

## lnpl.toml 프로필과 우선순위

- `lnpl.toml`은 `[default]`와 `[<profile>]`(`--profile`/`LNPL_PROFILE`로
  선택)을 키 단위로 오버레이한다(근거: docs/serving.md "설정 파일 —
  `lnpl.toml` (이슈 #114)"). `[*.secrets]`는 값이 아니라 환경변수 이름,
  파일 절대경로, 또는 등록된 프로바이더 키 이름만 받는다(근거:
  docs/serving.md "시크릿 원천 — 환경변수·파일·프로바이더 (이슈 #192)").
- 값 하나를 결정하는 순위는 CLI 플래그 > 환경변수(`LNPL_ENDPOINT_<NAME>`)
  > `lnpl.toml [<profile>]` > `lnpl.toml [default]` > 내장 기본값이다(근거:
  docs/serving.md "우선순위 (정본)").
- `${VAR}`는 순수 환경변수 참조로만 치환된다 — 기본값 문법은 지원하지
  않는다. `[*.secrets]` 값 안에서는 치환이 전혀 없다(근거: docs/serving.md
  "`${VAR}` 치환").
- `lnpl config check`는 소켓을 바인드하기 전에 endpoint 매핑, 시크릿
  환경변수·파일 존재, JWT 매핑 여부를 미리 판정한다 — 전부 통과하면 rc 0,
  아니면 발견한 문제 전부를 나열하고 rc 2다(근거: docs/serving.md
  "`lnpl config check` — 기동 전 완결성 판정").

## 배포 생성기가 시크릿을 넘기는 법

- `compose` 생성기는 시크릿 변수(`LNPL_JWT_SECRET`, `POSTGRES_PASSWORD` 등)를
  값 없이 `"${VAR:?set VAR before docker compose up}"` 참조로만 낸다 —
  호스트 환경에 없으면 compose가 시작을 거부한다(근거: docs/backends.md
  "`compose` — 내장 배포 생성기 (이슈 #189)").
- `k8s` 생성기는 ConfigMap, Deployment, Service를 쓴다 — Secret 오브젝트는
  만들지 않는다. `--from-literal`로 직접 만든 Secret을 Deployment의
  `secretKeyRef`로 참조한다(근거: docs/backends.md "`k8s` — 내장 배포
  생성기 (이슈 #189)").

## 집행 등급

- 미구현 — 실제 Vault나 클라우드 시크릿 매니저 드라이버. SPI와 TCK만
  제공된다. 위 권고는 설계 방향의 서술이지 지금 집행되는 제약이 아니다
  (근거: docs/backends.md "16. SPI: 외부 시크릿 프로바이더 등록 (issue
  #192)").
- 구현됨 — 환경변수·파일 원천(근거: docs/serving.md "시크릿 원천 —
  환경변수·파일·프로바이더 (이슈 #192)").
- 구현됨 — `lnpl.secrets` 외부 프로바이더 SPI(근거: docs/backends.md "16.
  SPI: 외부 시크릿 프로바이더 등록 (issue #192)").
- 구현됨 — 현재·이전 키 재조회를 통한 무중단 교체(근거: docs/backends.md
  "교체와 재조회").

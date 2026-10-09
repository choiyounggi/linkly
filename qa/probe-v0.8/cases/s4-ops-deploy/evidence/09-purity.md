# 09-purity — 순수성 확인 (D12)

## impl/ 등 out-of-scope 디렉터리 수정 0건

```
$ git status --porcelain -- impl/ scripts/ plugins/ docs/ rfcs/ examples/ README.md qa/probe-v0.8/requirements/
(출력 없음 — 변경 0건)

$ git status --porcelain
?? qa/probe-v0.8/cases/
(케이스 디렉터리 하나만 untracked로 신규 — 그 외 워킹트리 변경 없음)
```

## impl/ 열람 횟수

**0회.** 이 케이스 전 구간에서 `impl/`·`scripts/` 아래 어떤 파일도 Read/Grep으로
연 적 없다. D14의 `impl/tests/test_unknown_entity_corpus_sweep.py` 실행은
소스 열람이 아니라 계획이 명시적으로 지시한 회귀 게이트 실행이다(플랜 Task 06
step 6, 브리프 constraints). F-6(postgres 부하 붕괴)의 근인을 `impl/`을 보지
않고 postgres 컨테이너 자체의 로그·리소스(정상)만으로 배제해 "postgres 서버가
아니라 클라이언트-서버 상호작용 어딘가"까지만 좁히고 더 깊이 들어가지
않았다 — 블랙박스 조건(§2) 유지.

## 오토닌트 테스트-오염 메모

Task 06 evidence(07-migration.md)에 기록한 손상 행 1건(`{"visits":0,
"_schema_gen":...}`)은 이 세션 자신의 이전 실험(hardening 검증 중 1회성
`lnpl migrate --set visits=0` 호출)의 부작용으로 추정되며, `lnpl`/드라이버의
결함으로 단정하지 않았다(근인 미확정, F-항목화하지 않음 — 재현 절차를 특정하지
못해 축 태그를 붙일 근거가 부족).

## test-quality-auditor (loop-implement step 6.5)

auditor N/A — measurement task without test artifacts. 이 태스크는 spec 블록이나
pytest 파일을 새로 작성하지 않았다 — `src/linkhub.lnpl`의 spec 4블록은
`examples/linkhub.lnpl`에서 그대로 가져온 것(원본 예제, 이 세션이 저작하지
않음)이고 `src/linkhub.v2.lnpl`도 그 spec을 그대로 상속한다. `src/load.py`·
`src/burst.py`는 assertion을 갖는 테스트 스위트가 아니라 부하 생성·측정
도구다. D14 회귀 게이트(`impl/tests/test_unknown_entity_corpus_sweep.py`)는
기존 파일을 실행만 했을 뿐 저작하지 않았다.

## Docker 리소스 정리 확인

```
$ docker compose -p s4probe -f src/compose.yaml down -v
... postgres/redis/otel-collector/app 4개 컨테이너 + 네트워크 Removed
$ docker rmi s4probe-app:latest
Untagged / Deleted
$ docker compose -p s4probe ps -a   -> (없음)
$ docker volume ls | grep s4probe   -> (없음)
$ docker image ls | grep s4probe    -> (없음)
```

## 워크트리 임시 파일

`.claude/tmp/`(s4.env, lnpl-cachetest.toml, serve*.log, dev_doctor.log, rss/,
bookmark*.json) — 프로젝트 임시 디렉터리만 사용, `/tmp` 미사용
(`docker exec ... pg_dump -f /tmp/...`는 postgres **컨테이너 내부**
파일시스템이며 호스트 `/tmp`가 아님 — `docker cp`로 evidence/backups/에
즉시 옮김).

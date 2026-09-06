# 07-migration — R9 무중단 스키마 변경 (D8/D9)

절차: (1) 시드 → (2) 백업(`docs/backends.md` §14) → (3) v2 소스(필드 1개 추가)
→ (4) `lnpl migrate` 백필 → (5) v2 배포하며 v1 병행 응답 확인 → (6) 백업 복원.

## 1) 시드

```
$ # 100건 curl 루프 (100 rps 부하 흔적으로 rate-limit 50 걸려 83건만 1차 성공)
$ # 20건 추가(50ms 간격)로 채움
$ docker exec s4probe-postgres-1 psql -U s4user -d s4db -t -c "SELECT count(*) FROM lnpl_rows;"
108
```

(108건 — 목표 100+α. 1차 100건 루프 중 17건이 `--rate-limit 50`에 걸려 429,
2차로 20건을 50ms 간격으로 채워 108건 확보. "재시도"라기보다 자기 자신이 이미
켜 둔 rate-limit과의 상호작용 — 재시도 카운트에 넣지 않음, F-항목 아님.)

## 2) 백업 (`docs/backends.md` §14 "postgres 드라이버 — pg_dump/PITR에 위임")

```
$ docker exec s4probe-postgres-1 pg_dump -U s4user -d s4db -Fc -f /tmp/s4db_backup.dump
$ docker cp s4probe-postgres-1:/tmp/s4db_backup.dump evidence/backups/s4db_backup.dump
elapsed=0.17s, size=11771 bytes, rows=108
```

## 3) v2 소스 — 필드 1개 추가

`src/linkhub.v2.lnpl`: `Bookmark`에 `priority Priority`(신규 refine, min 0) 추가.
어떤 워크플로도 `priority`를 아직 참조하지 않음(expand 단계,
`docs/migration.md` §2 "새 필드를 참조하는 validate/set을 아직 워크플로에
넣지 않는다").

```
$ lnpl compile src/linkhub.v2.lnpl --strict=warning   # rc=0
$ lnpl db check --backend postgres:... src/linkhub.v2.lnpl
113개 mismatch: priority 108건(신규 필드, 예상대로 전 행 missing) +
                기존에 있던 손상 행 1건(payload가 `{"visits":0,"_schema_gen":...}`뿐 —
                이 세션의 사전 테스트(ad-hoc migrate 실험) 잔재로 추정, 근인 미확정)
```

**메모(F 아님, 투명성 기록):** 108개 정상 행 외에 1개 손상 행(필수 필드
`id`/`url`/`title`/`owner`/`savedAt` 전부 missing)이 `db check`에서 발견됐다.
이 세션 초반 hardening 옵션 검증 중 실행한 1회성 `lnpl migrate --set
visits=0` 실험(당시 5행 상태)의 부작용으로 추정되나 재현·근인을 확정하지
못했다(4h 예산상 별도 추적 안 함) — 이후 migrate/restore 카운트에는 포함해
그대로 다뤘다(정상 행과 동일하게 `priority`가 backfill됨, 아래).

## 4) `lnpl migrate` 백필

```
$ lnpl migrate --entity Bookmark --set priority=1 --backend "postgres:...:5432/s4db" src/linkhub.v2.lnpl
{"scanned": 108, "updated": 108, "skipped": 0}
elapsed=0.40s
```

**독립 확인(psql, lnpl 출력과 별개 채널):**

```
$ psql -c "SELECT count(*) FROM lnpl_rows;"                                 -> 108  (행 수 불변)
$ psql -c "SELECT count(*) FROM lnpl_rows WHERE payload ? 'priority';"      -> 108  (전 행 backfill)
$ psql -c "SELECT payload->'priority', count(*) FROM lnpl_rows GROUP BY 1;" -> 1 | 108
```

행 손실 0, 단일 트랜잭션, 0.4초. **판정: 충족.**

## 5) v2 배포하며 v1 병행 확인 (expand-contract)

```
$ lnpl serve --host 127.0.0.1 --port 18081 --backend postgres:... src/linkhub.v2.lnpl &
$ curl -s -o /dev/null -w "v1 healthz=%{http_code}\n" http://127.0.0.1:18080/-/healthz
v1 healthz=200
$ curl -X POST http://127.0.0.1:18080/link-hub-service/save-bookmark -d '{...no priority...}'
{"status":"completed", ...} status=200   # v1(구스키마)이 계속 정상 응답
```

**양방향으로 확인(계획보다 한 걸음 더):**

- v2(18081)가 마이그레이션 이전 행(`priority` 있음, migrate가 채웠으므로)을
  정상 조회: `GetBookmark` → 200, `bindings.bookmark.priority: 1`.
- v2(18081)가 **v1이 migrate 이후에 새로 쓴, priority 없는 행**을 조회해도
  **깨지지 않음** — 200 응답, `bindings.bookmark`에 `priority` 키가 아예
  없이(기본값을 억지로 채우지 않고) 조용히 생략된 채 반환됨. 읽기 경로가
  구스키마 행에 관대하다는 뜻 — 무중단 배포에 유리한 성질(긍정적 관찰).

v1 종료(`docker compose -p s4probe stop app`) 후 v2/postgres 계속 동작 확인.
**판정: 충족.**

## 6) 백업 복원

```
$ docker compose -p s4probe stop app   # v1/v2 프로세스 정지 후 복원
$ docker exec s4probe-postgres-1 pg_restore -U s4user -d s4db --clean --if-exists /tmp/s4db_backup.dump
elapsed=0.12s
$ psql -c "SELECT count(*) FROM lnpl_rows;"                            -> 108   (백업 시점과 동일 — 백업 이후 추가된 1건 사라짐, 예상대로)
$ psql -c "SELECT count(*) FROM lnpl_rows WHERE payload ? 'priority';" -> 0     (migrate 이전 상태로 정확히 복원)
$ psql -c "SELECT payload FROM lnpl_rows WHERE payload->>'id'='1111...1111';"
{"id": "1111...1111", "url": "https://example.com/a", ..., "visits": 0, "_schema_gen": "bbd0ae751547"}
```

원본 값과 정확히 일치(임의 행 재확인), `priority` 필드 없음(백업이 migrate
**이전**에 떠졌으므로 정상) — **복원 절차가 실제로 작동함을 실증. 판정: 충족.**

## 5단계 요약 표

| 단계 | 행 수 전 | 행 수 후 | 소요 시간 |
|------|---------|---------|-----------|
| 시드 | 0 | 108 | — |
| 백업 | 108 | 108(스냅샷) | 0.17s |
| v2 소스 작성 | — | — | 컴파일 rc=0 |
| migrate 백필 | 108(priority 0건) | 108(priority 108건) | 0.40s |
| v1/v2 병행 → v1 종료 | 108(+1 v1 신규) = 109 | 109 | — |
| 복원 | 109 | 108(백업 시점 상태로) | 0.12s |

## 정리

```
$ docker compose -p s4probe down -v
... 4개 컨테이너 Removed, 네트워크 Removed
$ docker rmi s4probe-app:latest
Untagged / Deleted
$ docker compose -p s4probe ps -a   ->  (없음)
$ docker volume ls | grep s4probe   ->  (없음)
$ docker image ls | grep s4probe    ->  (없음)
```

## 회귀 게이트 (D14)

```
$ .venv/bin/python -m unittest impl.tests.test_unknown_entity_corpus_sweep -v
Ran 5 tests in 0.023s — OK
```

(이 venv에 pytest가 없어 `python -m pytest` 대신 표준 `unittest` 러너로 같은
파일을 실행 — 결과는 동일 스위트, 5/5 통과, rc 0.)

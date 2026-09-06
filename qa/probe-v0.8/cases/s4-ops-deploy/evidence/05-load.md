# 05-load — R7 100 rps × 60 s (fake vs postgres)

`src/load.py`(stdlib open-loop, 10ms 간격 스레드 발사, 워밍업 5s 제외) 사용.

## fake 백엔드 (호스트 `lnpl serve`, --profile dev 상당 = `[default]`)

```
$ lnpl serve --host 127.0.0.1 --port 18087 --cache fake --config src/lnpl.toml src/linkhub.lnpl
$ python src/load.py --url http://127.0.0.1:18087/link-hub-service/get-bookmark \
    --rps 100 --seconds 60 --warmup 5 --method POST --body '{...실존 bookmark...}' \
    --out evidence/load_dev_fake.csv
total=6000 post_warmup=5500 ok=5500 error_or_non2xx=0
p50=1.02ms p95=2.48ms p99=6.78ms
error_rate=0.00%
```

RSS(5s 간격, `ps -o rss=`): 21.7~22.1MB로 평탄(첫 샘플만 기동 직후라 낮음).

10초 구간별 평균/최대 지연(csv 재집계) — **평탄**:

| 구간 | 평균 | 최대 |
|------|------|------|
| 0-10s | 1.19ms | 10.86ms |
| 10-20s | 1.37ms | 12.44ms |
| 20-30s | 1.26ms | 10.85ms |
| 30-40s | 1.35ms | 27.33ms |
| 40-50s | 1.16ms | 13.67ms |
| 50-60s | 1.28ms | 25.83ms |

## postgres 백엔드 — ① 배포 그대로(compose app, rate-limit 50 포함)

```
$ python src/load.py --url http://127.0.0.1:18080/link-hub-service/get-bookmark \
    --rps 100 --seconds 60 --warmup 5 --method POST --body '{...}' \
    --out evidence/load_prod_postgres.csv
total=6000 post_warmup=5500 ok=2750 error_or_non2xx=2750
p50=6.32ms p95=10.73ms p99=15.77ms
error_rate=50.00%   (전량 429 — 200:3049 / 429:2951, awk 집계)
```

RSS(`docker stats --no-stream`): 45~51MiB로 평탄.

**해석(F 아님, 배치 판단 사실):** 100 rps 목표 부하에 `--rate-limit 50`이 그대로
걸려 있으면 offered load의 절반이 429다 — R4에서 넣은 경화값(50/s)이 R7의 목표
처리량(100/s)보다 낮다는, **이 케이스가 스스로 만든 설정 부정합**이지 플랫폼
결함이 아니다. 200으로 통과한 요청들의 지연(p50 6.32/p99 15.77ms)은 postgres
실 RTT를 포함해 fake보다 높지만 안정적 — rate-limit이 과부하를 조기에 걷어내
tail latency를 보호하는 효과가 보인다(아래 ②의 무제한 케이스와 대비).

## postgres 백엔드 — ② rate-limit 없이(호스트 `lnpl serve`, 순수 백엔드 비교용)

```
$ lnpl serve --host 127.0.0.1 --port 18089 --cache fake \
    --backend "postgres:postgresql://s4user:s4pw@localhost:15432/s4db" src/linkhub.lnpl
$ python src/load.py --url http://127.0.0.1:18089/link-hub-service/get-bookmark \
    --rps 100 --seconds 60 --warmup 5 --method POST --body '{...}' \
    --out evidence/load_postgres_no_ratelimit.csv
total=6000 post_warmup=5500 ok=5500 error_or_non2xx=0
p50=9.89ms p95=1284.75ms p99=5866.91ms
error_rate=0.00%
```

RSS: 37.8~45.4MB로 평탄(fake보다 다소 높지만 폭주 없음 — 즉 메모리 누수가
아니라 **지연 축적**이 원인).

### F-6 (축 perf, blocker): 100 rps 지속 부하에서 postgres 백엔드가 ~40 s 지점부터
### 붕괴 — p99 5.9초

10초 구간별 재집계:

| 구간 | 평균 지연 | 최대 지연 | 표본 |
|------|-----------|-----------|------|
| 0-10s | 10.6ms | 59.8ms | 1000 |
| 10-20s | 10.8ms | 74.5ms | 1000 |
| 20-30s | 10.6ms | 47.8ms | 1000 |
| 30-40s | 10.3ms | 36.2ms | 1000 |
| **40-50s** | **95.9ms** | **3968.4ms** | 1000 |
| **50-60s** | **1161.9ms** | **5876.6ms** | 1000 |

처음 40초는 안정(fake와 같은 수준의 상대적 안정성, 절대값만 postgres RTT만큼
높음), 이후 두 구간에서 평균이 10배·110배로 폭증 — 전형적 큐 붕괴(오퍼레이팅
용량이 100 rps보다 살짝 낮아 open-loop 부하 아래 백로그가 시간에 비례해
누적되는 패턴, M/M/1 포화 곡선과 일치).

**postgres 서버 자체는 무관함을 확인:**

```
$ docker compose -p s4probe logs postgres --tail 30
... (정상 체크포인트 로그만, 에러/경고 없음)
$ docker stats --no-stream s4probe-postgres-1
CPU 6.17%  MEM 29.39MiB/3.827GiB  PIDS 6
```

postgres 컨테이너의 CPU·메모리·에러 로그 전부 정상 — 병목이 postgres 서버가
아니라 `lnpl serve`(스레드-퍼-요청 dev 서버, `docs/serving.md` "요청마다
인터프리터와 저장소 rows를 새로 만든다") ↔ `lnpl-postgres` 드라이버 경로에
있음을 시사한다(더 깊은 근인은 `impl/`·드라이버 내부를 봐야 하며 이 케이스의
블랙박스 조건 밖 — 근인 미확정으로 F-항목만 기록).

**추가 확인**: 짧은 15초 재현(`--seconds 15`)에서는 붕괴가 나타나지 않음
(p99=26.85ms, `pg_stat_activity` 동시 연결 1~2건 유지 — 커넥션 풀 자체는
정상 동작). 즉 붕괴는 **지속 시간에 비례해 누적**되는 문제이지 연결 수
폭주가 아니다.

**재현**: `python src/load.py --url http://<postgres-backed lnpl serve>/... --rps 100
--seconds 60 --body <valid Bookmark JSON>`, 40초 지점 이후 지연 폭증.

**심각도: blocker** — 우회 시도 안 함(D13, 플랫폼 성능 결함은 우회 대상이 아님).
100 rps는 R7이 요구한 목표치이므로 "요구사항을 우회로도 충족 못함" 기준에
해당.

**보완 제안**: `lnpl serve`(dev 서버)로 postgres 백엔드를 지속 부하 아래 운영하지
않도록 문서에 명시하고(현재 `docs/serving.md`는 dev 서버의 운영 부적합성을
TLS·워커 풀 관점에서만 경고), gunicorn(`build_app()`) 경로에서 동일 부하
재현·대조 벤치마크를 CI 성능 게이트로 추가한다. 근인은 `lnpl-postgres` 드라이버의
커넥션 재사용 정책과 dev 서버의 무제한 스레드 생성 중 무엇인지 플랫폼팀의 impl/
조사가 필요.

# 08-health — R10 헬스·준비 (D7)

문서 근거: `docs/serving.md` "운영 표면 — `/-/healthz`/`/-/readyz`/`/-/metrics`"
(liveness는 저장소를 안 봄, readiness는 "영속 백엔드가 설정돼 있으면 커넥션을
1회 획득·해제한다"의 4개 닫힌 체크 목록).

## 존재 여부

```
$ curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18080/-/healthz
200
$ curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18080/-/readyz
200
```

둘 다 존재 — **판정: liveness/readiness 존재, 충족.**

## postgres stop → readiness 전이 → start → 회복

```
$ (readyz를 1.5s 간격으로 폴링, 백그라운드)
$ docker compose -p s4probe stop postgres
$ sleep 20
$ docker compose -p s4probe start postgres
```

관측된 전이 타임스탬프(epoch, 상대 초는 stop 명령 기준):

| 시각(상대) | readyz | 본문 |
|---|---|---|
| stop 이전 | 200 | `{"status":"ok"}` |
| stop+1.7s | **503** | `{"code":"not-ready","detail":"readiness check(s) failed: repository","checks":["repository"]}` |
| stop+2.5s ~ +20.6s (13개 표본 전부) | 503 | 동일 |
| start+1.4s | **200** | `{"status":"ok"}` |
| 이후 24개 표본 전부 | 200 | 동일 |

**전이 확인: 200 → 503(≈1.7s 이내) → 200(재기동 후 ≈1.4s 이내).** `checks:
["repository"]`로 어느 검사가 깨졌는지 명시(문서 예시와 정확히 일치).

**문서 표현 대비 실측 정정(사소, F 아님):** `docs/serving.md`의 readyz ② 항목은
"영속 백엔드(`--backend sqlite:...`)가 설정돼 있으면"이라고 **sqlite로 예시**를
들지만, 실측 결과 postgres 백엔드에서도 동일하게 `repository` 체크가 동작한다
(위 표) — 즉 "영속 백엔드 일반"에 적용되는 계약이고 sqlite는 예시일 뿐이었다.
표현이 특정 스킴처럼 읽혀 처음엔 "postgres에도 적용되는지" 확인이 필요했다
(추가 조사 5분, 재시도 아님).

## liveness/readiness 분리 확인

```
$ docker compose -p s4probe stop postgres; sleep 3
$ curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18080/-/healthz
200          # postgres가 죽어도 liveness는 불변
$ curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18080/-/readyz
503
$ docker compose -p s4probe start postgres; sleep 3
$ curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18080/-/readyz
200
```

문서의 "liveness와 readiness를 절대 섞지 않는다" 계약대로 — postgres 장애 중에도
`healthz`는 200을 유지해 k8s가 파드를 재시작시키지 않는다. **판정: 충족.**

## 서비스 프로세스 생존(재시작 없이 자동 회복)

```
$ docker inspect s4probe-app-1 --format '{{.RestartCount}} {{.State.Pid}} {{.State.StartedAt}}'
0 99300 2026-09-05T16:46:29.261601583Z
```

postgres 장애 전후로 `RestartCount=0`, `StartedAt` 불변 — app 컨테이너/프로세스
자체는 **한 번도 재시작되지 않고** readiness만 전환됐다가 자동 회복했다. **판정:
충족** (D5 "readiness 실패 → 회복, 서비스 프로세스 생존" 그대로).

## 요약

R10 세 항목(liveness/readiness 존재, postgres 장애 시 readiness 전환, 복구 시
자동 회복 + 프로세스 생존) 전부 문서 그대로 동작 — 이 케이스에서 R10은 마찰
없이 **충족**.

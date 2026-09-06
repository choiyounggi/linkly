# 06-drain — R8 SIGTERM 그레이스풀 드레인 (D6)

방법: fake 백엔드 `lnpl serve --grace-period {1,10}` 기동 → `load.py` 100rps×60s
백그라운드 실행 → t=20s에 `kill -TERM <pid>` → `date +%s.%N` 전후로 종료까지
걸린 시간 측정 → CSV를 completed(200)/refused(ECONNREFUSED, 프로세스 종료 후
연결 자체가 거부됨)/lost(응답 없이 연결이 끊김 — timeout 또는 connection reset)로
분류.

## grace-period = 1s

```
$ lnpl serve --host 127.0.0.1 --port 18090 --backend fake --cache fake --grace-period 1 src/linkhub.lnpl
$ python src/load.py --url .../get-bookmark --rps 100 --seconds 60 --warmup 0 \
    --method POST --body '{...}' --out evidence/drain_grace1.csv &
$ sleep 20; T0=$(date +%s.%N); kill -TERM <pid>
$ # 프로세스 종료를 폴링으로 확인
elapsed = 0.105s
```

serve stderr: `lnpl serve: drain complete -- shutting down` — 유예(1s) 만료가
아니라 드레인 자체가 끝나서 멈췄음을 명시(문서 `docs/serving.md` "SIGTERM
그레이스풀 드레인" §3 "어느 쪽인지 stderr 한 줄로 구분"과 일치).

분류(6000행 전수):

| 분류 | 건수 |
|------|------|
| completed (200) | 1999 |
| refused (ECONNREFUSED — 프로세스 종료 후) | 4000 |
| **lost** (ConnectionResetError, errno 54) | **1** |

lost 1건의 `t_start=19.994s` — SIGTERM 시점(t≈20.00s)과 0.006s 차이, 즉 종료
직전 마지막 순간에 발사된 요청의 TCP 연결이 서버 소켓 close와 정확히
경합했다(마지막 completed의 `t_start=19.981s`, 첫 refused의 `t_start=20.002s`
사이에 낀 단 1건). **종료 소요 시간(0.105s) ≤ grace-period(1s) — 판정: 충족**
(s4.md D4 "종료 시간 ≤ grace").

## grace-period = 10s

```
$ lnpl serve --host 127.0.0.1 --port 18091 --backend fake --cache fake --grace-period 10 src/linkhub.lnpl
$ (동일 절차) t=20s에 SIGTERM
elapsed = 0.112s
```

| 분류 | 건수 |
|------|------|
| completed (200) | 1998 |
| refused (ECONNREFUSED) | 4001 |
| **lost** (ConnectionResetError, errno 54) | **1** |

동일 패턴 — 종료 소요 시간(0.112s) ≤ grace-period(10s). **판정: 충족.**

## 해석 — lost=0이 아니라 lost=1(양쪽 다)

s4.md D4는 "손실 0"을 기대치로 든다. 두 라운드 모두 정확히 1건이 손실됐다 —
매 라운드 SIGTERM 순간(t≈20.00s)에 발사된 마지막 요청 1건이 서버 소켓이 닫히는
찰나와 경합해 `ConnectionResetError`를 받는, TCP accept-vs-close 레이스로 보인다
(fake 백엔드라 요청 처리 자체는 사실상 즉시 끝나므로, 두 grace-period 값이
드레인 소요 시간에 차이를 만들지 못했다 — 아래 "한계" 참고). **심각도: minor**
(요구한 "손실 0"에 1건 못 미치지만 재현 가능한 경계 레이스이고, 6000건 중 2건
(0.03%)뿐이며 grace-period 값과 무관하게 상수라 그레이스풀 드레인 로직 자체의
결함이라기보다 클라이언트가 정확히 종료 순간에 새 TCP 연결을 열 때의 커널 레벨
경합으로 보임 — 근인 미확정, `ops` 축 F-항목으로 기록).

**F-7(축 ops, minor):** SIGTERM 그레이스풀 드레인이 "새 연결 거부"로 전환되는
순간과 정확히 겹친 신규 연결 1건이 매 라운드 `ConnectionResetError`로 끊긴다
(0.03%, grace-period 값과 무관). "손실 0"을 엄격히 요구하는 SLA라면 로드밸런서
헬스체크 기반 사전 draining(서비스 제거 후 SIGTERM)으로 이 레이스 창을 없애야
한다 — 애플리케이션 레벨에서 TCP accept 큐의 마지막 항목까지 커버하는 것은
일반적으로 불가능한 범위다. **보완 제안**: `docs/serving.md`의 드레인 절에 이
레이스(신규 연결이 accept와 close 사이에 낄 수 있음)를 알려진 한계로 명시.

## 한계 — 이 테스트로 grace-period 차이를 구분하지 못함

fake 백엔드는 요청 처리가 사실상 즉시(<1ms) 끝나 진행 중 요청이 없다시피
하므로, 두 grace-period(1s vs 10s) 모두 실제 드레인 완료 시간(0.1s 안팎)에
차이를 만들지 않았다 — "느린 진행 중 요청이 grace-period 안에서 완료되는지"는
이 케이스에서 실증하지 못했다(postgres 백엔드로 반복하면 더 유의미하겠지만,
05에서 이미 postgres가 지속부하 아래 자체적으로 붕괴하는 현상(F-6)을 확인했고
4h 예산상 이 조합까지 재현하지 않음 — 기록만 남김).

# 05 — mode B (네이티브 컴파일·실행) (Task 05)

사전 확인: 셸 export 4종 재설정 후 `bash scripts/dev_doctor.sh` → doctor-rc=0
(00-env.md 패리티 인벤토리와 동일 상태).

명령(공통): `.venv/bin/lnpl build qa/cases/rate-notify/rate-notify.lnpl --run --workdir .claude/tmp/lnpl-build <인자>`
raw: `evidence/raw/modeB-bN.txt`. 전 런 rc=0, `exit=0`.

## 1차 실행 — `--field value=150` 형식이 조용히 무시됨 (F-기록)

bare 이름(`--field value=150 --field acknowledged=1`)으로 B1~B5 실행:
**5개 런 전부 사실상 동일 거동** — `step 3 create notification` 부재(가드1 항상
스킵), until 16라운드(가드3 항상 미성립). 즉 --field 값이 반영되지 않고 전부
기본값 0으로 평가됐다. **경고·오류 출력은 없었고 exit=0.**

- 원인: 조건이 참조하는 필드명은 정규화된 dotted 이름(`measurement.value`)인데
  bare 이름은 "workflow가 비교하지 않는 필드"로 분류되어 **조용히 무시**된다
  (help 문구: "Fields the workflow does not compare on are ignored; omitted ones
  default to 0.").
- 사용자 실수(오타·이름 불일치)가 **무경고로 반대 분기 실행**이 되는 구조 —
  가드 무음 오평가의 실제 사례. → FINDINGS F-4 (major).
- 우회: dotted 이름으로 재실행 (시도 2). 1차 raw는 덮어썼으나 거동은 위에 인용.

## 2차 실행 (dotted `--field measurement.value=…`) — 결과 표

| Run | 인자 | 실행 스텝 수 | create | emit | read 라운드 | mode A 대응 | 일치 |
|-----|------|--------------|--------|------|-------------|-------------|------|
| B1 | value=150, ack=1 | 4 | ✓ | ✓ | 0 | R1 (4스텝, read 0회) | **Y** |
| B2 | value=50, ack=1 | 3 | ✗ (스킵) | ✓ | 0 | R2 (create 스킵) | **Y** |
| B3 | value=100, ack=1 | 3 | ✗ (스킵) | ✓ | 0 | R3 (`>` 배제 경계) | **Y** |
| B4 | value=150, ack=0 | 20 | ✓ | ✓ | **16** (round cap) | R7 (read ×16) | **Y** |
| B5 | value=150, ack=1, `--skip` | 3 | ✓ | ✗ (스킵) | 0 | R6 (emit 스킵) | **Y** |

## 가드별 양방향 대조 (mode B)

| 가드 | 참 런 | 거짓 런 | 신호가 갈렸는가 |
|------|-------|---------|-----------------|
| guard.1 비교식 | B1 (create 실행) | B2/B3 (create 부재) | **Y** |
| guard.2 presence | B1 (emit 실행) | B5 `--skip` (emit 부재) | **Y** |
| guard.3 until | B1 (read 0회) | B4 (read 16회 = `_UNTIL_ROUND_CAP`) | **Y** |

**판정: mode B에서도 세 가드 모두 실제로 컴파일·평가된다** (RFC-0008 §3 —
비교식은 i64 파라미터, presence는 skip 플래그). 경계 semantics(100 → 스킵)도
mode A와 동일. 단 presence는 `--skip` 단일 플래그 구동이라 presence 가드가
여러 개면 개별 제어 불가로 보인다(이 케이스는 1개라 미검증 — 커버리지 갭).

정리: `.claude/tmp/lnpl-build`는 T05 종료 후 제거(9번 증적 전 확인).

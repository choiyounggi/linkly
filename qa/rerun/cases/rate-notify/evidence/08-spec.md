# 08 — spec 매니페스트와 실행 (T7) — 최우선 측정점

raw: `evidence/raw/spec-manifest*.txt`, `spec-run-{1,2}.txt`, `spec-f12*-probe.txt`.
시도 2회 (원: 3회 상한 도달 FAIL).

## 시도 1 — 3블록 매니페스트 독립 케이스화 확인, `no priorNotification`만 거부

```
$ .venv/bin/lnpl spec … -o …   → wrote … (3 case(s))       # 3블록 = 3케이스
 - ['valid measurement','id 3f2504e0-…','value 150','acknowledged 1'] -> ['completed','steps 4','slo met','rows Notification 1']
 - ['empty repository'] -> ['failed','attempts 4']
 - ['id 3f2504e0-…','value 100','acknowledged 1','no priorNotification'] -> ['completed','rows Notification 0']
$ … spec --run   → rc=2
compile error: unsupported given: 'no priorNotification' (use `valid <...>`, `empty repository`, `<field> <value>`, `no <field>` naming a declared field, or `stored <entity> <field> <value>`)
```

- **F-4 반전**: 원 "3블록인데 1 case(s)" 무음 병합 → 재측정 **"3 case(s)"**,
  given/expect가 블록별로 정확히 분리(위 인용). references/spec.md도 "블록마다
  독립 케이스 하나"로 문서화됨.
- **F-6 잔존**: `no priorNotification`(Notification 엔티티에 선언된 필드)이 원과
  동일 문구로 거부. 진단은 "`no <field>` naming a declared field"라 말하지만
  스코프가 워크플로 입력 엔티티(Measurement)로 한정된 것으로 보이고, 그 규정은
  references/spec.md에 여전히 없음.
- 대응(계획 선결정 분기): 그 1줄만 제거하고 재시도 1로 집계.

## 시도 2 — 3케이스 원형 실행 **전부 통과**

```
$ … spec --run   → rc=0
PASS Report spec 1 — completed (status=completed)
PASS Report spec 1 — steps 4 (steps=4 want=4)
PASS Report spec 1 — slo met (slo_met=True)
PASS Report spec 1 — rows Notification 1 (Notification rows=1 want=1)
PASS Report spec 2 — failed (status=failed)
PASS Report spec 2 — attempts 4 (max attempts=4 want=4)
PASS Report spec 3 — completed (status=completed)
PASS Report spec 3 — rows Notification 0 (Notification rows=0 want=0)
spec: 8 passed, 0 failed
```

- **F-5 반전**: given의 `id 3f2504e0-…`가 payload에 적용되어 케이스 1이
  validate를 통과하고 4스텝 완주(원: steps=1에서 failed, id 유실). 케이스 3
  (given에 id+value 100)도 completed — given→payload 경로가 run과 일치.
  references/spec.md의 "기본 payload(샘플 값) 위에 필드 단위로 덮어쓰며" 문서화
  (issue #46)와 실동작 일치.
- 정상+에러+경계 3시나리오가 **spec만으로** 표현·실행·판정된다 — 원의
  "정상+에러+경계를 spec으로 표현할 방법이 사실상 없다"의 반전.
- rows 단언(케이스 1: rows=1, 케이스 3: rows=0)도 spec 러너로 검증 가능 —
  F-10(run --json의 rows 부재)의 우회로가 이제 실제로 작동.

## F-12 재검: 실패 사유 출력 — probe 2건 (probes/f12-fail.lnpl, f12b-runtime-fail.lnpl)

- 단언 불일치: `FAIL Report spec 1 — steps 5 (steps=4 want=5)` — **관측값 vs
  기대값 인라인 출력** (raw/spec-f12-probe.txt, rc=1).
- 런타임 실패: 기대를 completed로 바꾼 probe에서
  `FAIL Report spec 2 — completed (status=failed)` 바로 아래
  `reason: step='find measurement' — repository read found no row for entity.measurement`
  — **failed_step과 실패 사유가 spec 출력에 직접 노출** (raw/spec-f12b-probe.txt).
  원: FAIL 줄뿐이라 별도 `lnpl run` probe가 필요했다. **반전**.

## 판정

**스코어카드 spec 행 = PASS** (rc=0, 8/8 단언, 재시도 1 — F-6 잔존으로 인한
경계 given 1줄 축소만). 원 유일 단계 FAIL의 반전이 확정됐다.

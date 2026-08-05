# 08 — spec 매니페스트와 실행 (Task 07)

raw: `evidence/raw/spec-manifest-stderr.txt`, `spec-run-1..3.txt`, `modeA-norow.json`.
시도 3회 (상한 도달 — effort_level max 3 retries 준수).

## 시도 1 — spec 블록 3개(정상/에러/경계)가 무음 병합

```
$ .venv/bin/lnpl spec … -o …   → wrote … (1 case(s))     # 3블록인데 1케이스
given:  ['valid measurement','value 150','acknowledged 1','no priorNotification','empty repository','value 100','acknowledged 1','no priorNotification']
expect: ['completed','steps 5','slo met','rows Notification 1','failed','attempts 4','completed','rows Notification 0']
$ … spec --run   → run-rc=2
compile error: unsupported given: 'no priorNotification' (use `valid <...>`, `empty repository`, `<field> <value>`, `no <field>` naming a declared field, or `stored <entity> <field> <value>`)
```

- **거부 없이 3블록이 1케이스로 이어붙어** `completed`와 `failed`가 공존하는
  모순 케이스가 됐다 (경고 없음) → F-5.
- `no priorNotification` 거부: 에러 문구는 "`no <field>` naming a declared
  field"를 지원한다는데 priorNotification은 Notification 엔티티에 **선언돼
  있다**. given 필드 스코프가 워크플로 입력 엔티티(Measurement)로 한정되는
  것으로 보이나 문서(references/spec.md)엔 스코프 규정이 없다 → F-6.
- 진단 문구 자체는 대안 목록을 제시 — 품질 양호(측정 규율 2).

## 시도 2 — 정상 케이스 1블록만 (폴백 2·5 발동)

```
FAIL Report spec — completed (status=failed)
FAIL Report spec — steps 5 (steps=1 want=5)
…
spec: 0 passed, 4 failed        # run-rc=1
```

- steps=1 = validate에서 실패. **실패 사유가 spec 출력에 없다**(진단성 부족).
- probe(`lnpl run` + `{"value":150,"acknowledged":1}`)로 재현:
  `reason= missing required field 'id'` — **spec 러너는 given이 설정한 필드만으로
  payload를 구성**하며 나머지 required 필드를 채우지 않는다.

## 시도 3 — given에 `id <uuid>` 추가 + steps 관측값(4)으로 정정

```
given: ['valid measurement', 'id 3f2504e0-4f89-41d3-9a0c-0305e82c3301', 'value 150', 'acknowledged 1']
FAIL Report spec — completed (status=failed)
FAIL Report spec — steps 4 (steps=1 want=4)
spec: 0 passed, 4 failed        # run-rc=1
```

- `id …` given이 **매니페스트에는 실렸으나** 러너는 여전히 1스텝에서 실패.
- 동일 필드 값의 `payloads/r1.json`은 `lnpl run --payload`로 **completed**
  (04-modeA.md R1). 즉 **run이 실행하는 payload를 spec 러너는 실행하지 못한다**
  — given→payload 적용 경로가 run과 다르며 id 값이 유실/미적용 → F-7 (major).
- steps 의미론은 시도 2에서 관측 확정: **실행된 스텝 수**(steps=1). `steps 4`
  정정은 그 관측에 근거(검증 약화 아님 — 폴백 3 단서).

## DoD spec 항목의 대체 커버리지 (브리프: "표현 불가하면 F-기록으로 대체 가능")

| 케이스 | spec 표현 | 대체 증적 |
|--------|-----------|-----------|
| 정상 (value 150 → 알림 1건) | 블록은 존재하나 러너 실패 (F-7) | 04-modeA.md R1: completed, create+emit 실행 |
| 에러 (빈 저장소 → 재시도 소진) | 블록 병합 문제로 제거 (F-5) | `run --no-row`: `status=failed, failed_step=find measurement, reason=repository read found no row`, **attempts=4** = retry 3+1 (lnpl-spec 도출표와 일치). raw: modeA-norow.json |
| 경계 (value 100 → 억제) | 블록 병합 문제로 제거 (F-5) | 04-modeA.md R3: guard.1 스킵, `>` 배제 경계 실측 |

스코어카드 spec 행 = **FAIL** (러너 기준), 단 3케이스 전부 실행 증적으로 커버됨.

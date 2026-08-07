# 01 — 원형 재구성과 정적 마찰 재검 (T2)

## 열람 문서 (순서)

| # | 문서 | 목적 |
|---|------|------|
| 1 | AGENTS.md | 라우팅(".lnpl 한 줄 쓰기 전 lnpl-authoring") — 원과 동일하게 1회 도달 |
| 2 | qa/cases/rate-notify/rate-notify.lnpl | 동형의 원본(읽기 전용) — capability~workflow 부 verbatim 이식 |
| 3 | qa/cases/rate-notify/evidence/08-spec.md | 원 시도 1의 3블록 given/expect 원형 |
| 4 | plugins/lnpl/skills/lnpl-authoring/references/verbs.md | F-1 재검 |
| 5 | plugins/lnpl/skills/lnpl-authoring/references/grammar.md | F-7 재검 |
| 6 | plugins/lnpl/skills/lnpl-authoring/references/spec.md | 다중 블록 정책("블록마다 독립 케이스") 확인 |
| 7 | examples/guarded.lnpl | F-8 재검 |

측정 순도: `impl/` 미열람. 지식 소스는 위 표 + CLI `--help`(이후 태스크)뿐.

## 소스 구성 (D1·D2)

- `rate-notify.lnpl` — 원본과 워크플로 8스텝·엔티티·이벤트·서비스 동형.
  가드 3형태 유지: `when measurement.value > 100` / `when priorNotification missing` /
  `until measurement.acknowledged > 0`. `==` 전환 안 함(비교 가능성 우선).
- spec은 원 시도 1의 의도(정상/에러/경계 3블록)를 복원하되:
  - steps는 5가 아닌 **4** — 원 시도 3에서 관측 확정된 의미론(실행 스텝 수) 반영.
  - `no priorNotification`은 **경계 블록에만** 실어 F-6 스코프 재검용으로 격리.
  - 정상 블록 given에 `id 3f2504e0-…` 포함 — F-5(given id 적용) 판정 지점.
- 3블록 각각 관측 가능한 단언 보유(minimum-case-set): 정상=steps 4+rows 1,
  에러=failed+attempts 4, 경계=completed+rows 0.
- `payloads/r1~r7.json` — 원본에서 바이트 동일 복사(`cmp` 전건 통과).

## F-1 재검: notify/send 동사 부재

- 현행 verbs.md 29행: "`return`, `log`, `send`, `notify`, `verify` 같은 낱말은
  이 표에 **없다**. 자연스러워 보여도 아무 효과가 없다."
- 원 관찰과 동일 — 어휘는 그대로이나, 부재가 명시 경고로 문서화되어 있어
  저작 시 우회(`create notification`+`emit`)를 처음부터 선택하게 됨(재시도 0 예상).
- 판정 후보: **잔존**(어휘 자체) / 문서 경고는 원 실측 때도 있었음 — T8에서 확정.

## F-7 재검: comparator `==`/`!=` 정본화

- 현행 grammar.md 31행: "비교 연산자: `<=` `>=` `==` `!=` `<` `>`" —
  원 실측("`<=` `>=` `<` `>`"뿐)과 달리 **`==`/`!=`가 생성 참조에 등재됨**.
- examples/guarded.lnpl 헤더도 "Comparison, RFC-0015가 `==`를 정본화"로 교차 확인.
- 실동작: `probes/f7-eq.lnpl`(본 소스에서 guard 1줄만 `==`로 교체) — T3에서 compile rc 기록.

## F-8 재검: examples/guarded.lnpl 존재

- `ls examples/guarded.lnpl` → 존재. 헤더 주석이 presence(`exists`)·comparison
  두 형태의 양방향 실행 커맨드까지 명시 — 원 "가드 공식 예제는 checkout 1줄뿐"
  대비 반전. until 미수록 사유(차등 관측기 비대칭, 이슈 #50 실측)도 주석에 정본화.
- 판정 후보: **해소** — T8에서 확정.

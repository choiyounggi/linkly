# 06 — differential (mode A vs B) (재측정)

커맨드: `lnpl diff payment-refund.lnpl --workflow <id> --payload <카드번호 심은 payload>`
— payload에 `4111111111111111`이 실려 있으므로 마스킹 차원이 결과를 결정하는
**강제 입력**이다(D6).

## 판정이 비교하는 표면 (인용 전 기록 — wiki: testing-quality-differential-run-agreement)

diff 출력이 스스로 밝히는 4클래스: ① execution order(+skips) ② policy outcome(status)
③ observability signals(effects) ④ masking("no secret marker in either mode's output").
플랫폼 문서(kb `security-sensitive-field-masking`, raw/kb-load-masking.out)가 스코프를
명시: **"PASS masking은 두 모드의 출력에 표지가 없다는 뜻이지, 모든 채널을 봤다는
뜻이 아니다."** — 원 F-9가 지적한 '초록의 의미' 모호성이 문서로 닫힘. mode A
result.bindings 채널은 이 판정과 별개로 evidence/04 §6에서 독립 sweep(0히트, 컨트롤
평문)으로 확인했다.

## 결과 (기본 입력 아님 — 카드번호 심은 강제 입력)

| 워크플로 | 판정 | raw |
|----------|------|-----|
| wf.approval (amt500000) | **EQUIVALENT 4/4** — 1 step, 0 skip, masking PASS | diff-wf.approval.out |
| wf.refund.request (day5) | **EQUIVALENT 4/4** — read→create, 0 skip, masking PASS | diff-wf.refund.request.out |

- 재시도: 0. 원 실측(EQUIVALENT 4/4 ×2, 단 F-7 누수 공존)과 표면상 동일하나, 이번엔
  같은 실행의 bindings 채널 독립 검증이 클린이라 초록의 의미가 다르다.
- 스코프 한정 인용(D6): 이 EQUIVALENT는 "두 모드가 같은 스텝 집합·status·effects를
  내고, 두 모드 출력에 비밀 표지가 없다"는 주장이다. 저장 값 차원(mode B는 저장소
  비모형)은 이 판정 밖 — RFC-0015 §5가 명시한 허용 차이.
- 메모리 기록(2026-08-06, RFC-0016 도입기)의 "differential이 DateTime을 mode B에서
  0으로 강제" 이슈: 본 실행에서 DIVERGENT 미발생 — day5 payload의 DateTime 값이 diff
  경로에서 정상 처리됨(스텝 집합 일치). 별도 마찰로 기록하지 않음.

F-9 예비 판정: **부분** — 검사의 비교 표면 자체는 여전히 전 채널이 아니며 문서가
그 한계를 정직하게 명시(+ #43 채널 통일로 원 공존 누수는 소멸, 독립 sweep 병행 시
실질 위험 없음). '모든 채널을 본다'는 원 기대 자체는 미충족.

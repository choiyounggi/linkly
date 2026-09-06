# METRICS — s1-order-platform

| 지표 | 값 | 측정 방법 |
|------|-----|-----------|
| 소스 줄 수 (.lnpl, 공백·주석 제외) | 218 | `find src -name '*.lnpl' \| xargs wc -l` (round 2: spec 블록 9개 추가로 163→218) |
| 파일 수 | 4 | `find src -name '*.lnpl' \| wc -l` |
| authoring 라운드 (편집→재실행 사이클 총계) | 42 | evidence/01-authoring.md `## Rounds (D4 format)` 절, `- round N:` 그레프 가능(round 1의 서술형 "~40" 대체 — F-16 해소) |
| 실행한 CLI 명령 수 | ~110 | evidence/00–09 전수 (compile ~32, run ~50, spec ~5, openapi 3, serve+curl ~17, token 7) |
| 첫 컴파일 성공까지 라운드 | 2 | evidence/01 round 1→2 (필드명 camelCase 수정) |
| 첫 spec 전건 통과까지 라운드 | 2 | evidence/04-spec.md — round 1(bare `stored` 실패) → round 2(`stored Entity[0]` 인덱스 폼으로 즉시 통과, F-17) |
| spec 시나리오 수 / 단언 수 | 9 / 33 | evidence/04-spec.md — A1/A2/A3(CreateOrder×3) + A6/A7(CancelOrder×2) + A4/A5(Pay×2) + A8×2(Refund, within-cap/exceeds-cap) = A1–A8 전건, `spec: 33 passed, 0 failed` |
| 요구사항 충족 / 부분 / 불가 / 우회 (개수) | 충족 3 / 부분 6 / 불가 1 (부분 6건 중 우회로 절반 충족: F-1·F-3·F-5·F-8) | FINDINGS.md 커버리지 표 집계(R1,R9,R10=충족; R2–R7=부분; R8=불가 — round 3에서 판정이 Block으로 바뀌며 R8도 "부분"에서 "불가"로 정정됐다) |
| 결함 탐지: spec이 잡은 것 / 사람이 실행 출력을 보고 잡은 것 / 못 잡고 지나간 것 | 1(D3 자체 검증) / 16(실제 `### F-` 헤딩 개수 — F-1,3,4,5,6,8,9,10,11,12,13,14,15,16,17,18; F-2/F-7 번호는 결번) / 알 수 없음 | `grep -c '^### F-' FINDINGS.md` → 16. F-18은 플랫폼 결함이 아니라 이 케이스 자신의 증거 절차 결함(round 1의 read-back 누락)이지만, 여전히 "사람이 실행 출력을 보고 잡은 것" 열에 속한다 — round 1의 응답-JSON-만 확인 관행 자체가 read-back으로 잡힌 결함이기 때문. spec이 실제로 초록/빨강을 가른 것은 D3 자기증명 1건뿐(reviewer F1이 지적한 "spec이 잡은 결함 0"은 이제 최소 1로 해소) |
| 읽은 문서 (파일 목록과 대략 줄 수) | 17개 파일, ~2,655줄 | evidence/00 §Docs read, evidence/01 목록 — round 2에서 RFC-0038(370줄, 재확인)·RFC-0028(§1, F-5 근거) 추가 |
| 변경 요청(R-change) 반영: 바뀐 줄 수 / 라운드 / 기존 spec 중 깨진 것 | 12줄 / 4라운드(1회 자체 버그) / spec 0건 깨짐(R10 당시 spec 자체가 없었음 — round 2에서 신설된 spec은 R10 이후 상태를 기준으로 작성돼 회귀 확인 대상이 아님, evidence/07 그대로) | evidence/07-change-request.md |
| 벽시계 시간 (시작~FINDINGS 완성) | round 1: 16:22Z→17:26Z(64분); round 2: 2026-09-06T12:37:29Z(rework 지시)→12:58:28Z+ (~21분); round 3: 2026-09-06T13:01:57Z(rework 지시)→13:03:35Z+ (~2+분, t1-r2.md 회신 작성 시점 기준) | `date -u`, status/t1.json (t1-r1 N2, t1-r2 N1 회신) |
| 토큰 | (코디네이터 기입) | token-report.sh |

## Round 2 변경 요약 (reviewer t1-r1 대응)

- F1 해소: spec 9블록/33단언 A1–A8 전건 그린 + D3 flip-red-restore-green 실증(evidence/04)
- F2 해소(다른 결론으로): `lnpl serve`가 openapi.generate()를 기동 시점에 직접 호출해 F-12와 동일한 크래시로 **아예 기동 실패** — A1–A8 실 서버 curl은 "시간 상한"이 아니라 "불가"로 재분류(evidence/06). 격리된 동치 픽스처로 F-4의 200/500 상태코드 자체는 실 HTTP로 검증
- F3 해소: F-11 경계(1센트 환불 4회)를 실행으로 확인 — count-cap 부재가 코드 리뷰 추정이 아니라 관찰된 결함으로 승격; D4 라운드 로그 형식 준수(evidence/01)
- F4 해소: R2 커버리지 셀에 미충족 절반(on_hand 차감 불가) 명시; R6/A7 재검증에서 round 1 증거의 read-back 누락을 발견 — 원본 DB엔 Refund 행이 없었고, 격리 재현에서는 있음(evidence/03에 두 사실 모두 기록, 재현 쪽을 정본으로 채택)

## 대조군 주석 (t5 — FastAPI 기준)

이 케이스(t1, lnpl)는 다음 세 축에서 t5(FastAPI+SQLite)와 대조될 값을 남긴다:

- **표현력 우회 횟수**: F-1(Money)·F-3(단일 id)·F-8(substring 없음) — FastAPI는
  이 셋 다 원어(Python)로 직접 표현 가능해야 정상이며, 대조군 판정의 핵심
  차이점이 될 것으로 예상.
- **툴체인 자체 결함 발견 수**: F-12/F-13(둘 다 blocker, 상호 유발, round 2에서
  "openapi만"이 아니라 "serve 자체가 기동 불가"로 격상) — lnpl 0.8.0의 OpenAPI
  생성 경로가 자기 문서(RFC-0030)의 골든 예제조차 못 돌리고, 그 경로를
  `lnpl serve`가 기동 시점에 그대로 재사용한다. FastAPI의 OpenAPI 생성
  (Pydantic 기반)에는 구조적으로 대응하는 실패 모드가 없을 가능성이 높음 —
  t5와의 직접 비교 시 이 항이 가장 클 것으로 예상.
- **라운드 수 42**: 상당 부분(F-2/F-3/F-10/F-17 발견)이 "어떻게 표현하는가"를
  찾는 탐색이었지 "요구사항이 뭔가 몰라서"가 아니다 — LLM 특화 축(llm 태그)
  관점에서, 닫힌 어휘 언어의 탐색 비용이 이 케이스의 지배적 비용이었다.

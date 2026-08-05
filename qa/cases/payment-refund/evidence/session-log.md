# session-log — payment-refund (append-only)

**Charter (D1):** Explore payment-refund .lnpl authoring and the full pipeline
with the closed vocabulary (skills/references only, no impl knowledge) to
discover masking/policy/boundary expressiveness gaps and diagnostic quality.

베이스라인: 713a4cb, 2026-08-05 21:20 KST. 계수 규칙: 시도 = 편집→단계 명령 재실행 1회(최초 실행이 1).

---

- 21:20 [T01] venv 생성+install 1회 성공. dev_doctor 첫 실행 rc=1은 내 캡처 경로(.claude/tmp 부재) 탓 — 재실행 rc=0. F-후보 아님(플랫폼 무관).
- 21:22 [T02] AGENTS.md→스킬 문서 2홉 도달, 마찰 없음. KB: 네이밍 문서가 camelCase 강제·워크플로 동작명사 규칙을 사전에 잡아줌(+). 반면 "마스킹" 질의가 네이밍 문서로 오라우팅(F-후보: KB security 커버리지 공백), "환불 기간 정책"·"amount limit"은 no match.
- 21:25 [T03] compile 4시도. F-후보 확정 3건: (1) 필드 간 산술·비교 미지원(RFC-0008 형식 제한), (2) 기간 단위에 day 없음(30일=43200m 수동 환산), (3) 가드는 read된 행만 참조(RFC-0012) — "입력값 검증" 표현 불가, Approval을 find→update로 재해석하는 우회. 진단 메시지 품질은 3건 모두 높음(행 번호·지원 형식·RFC 근거·귀결 설명). 잔여 경고 2건은 의도 프로브.
- 21:29 [T05] F-후보 대량: (4) Money 가드 런타임 TypeError 크래시(raw traceback 누출), (5) 연쇄 when 첫 가드 무진단 탈락 → 0·-1 금액 승인 런타임 증명, (6) 가드 false = skip인데 status=completed·rc=0 (한도 초과가 성공으로 보임), (7) 마스킹 부분 집행: trace는 "***", result.bindings는 원문 노출(s3cret-value·4111… 각 1히트), (8) DateTime<=Duration 컴파일 통과 후 런타임 거부, (9) payload 전체 필드 강제(프로브에도 카드번호 제출). 경계 1000000/1000001은 <= 포함으로 정확.
- 21:38 [T06] mode B build·diff 전부 1시도 PASS, EQUIVALENT — 예고된 환경 실패 미재현. diff 4/4가 마스킹 검사인데 bindings 누수 채널은 비교 표면 밖(F-후보: present vs verified).
- 21:40 [T07] openapi 1시도 PASS. cardNumber={string,password,writeOnly:true}, 예시 누출 0 — 문서 표면 우수. 단 writeOnly 계약 vs 런타임 bindings 원문 반환 모순(F-후보).
- 21:45 [T08] spec 6시도 끝에 4P/0F. F-후보: (10) spec 블록 간 given 병합 — 워크플로당 1시나리오, 정상+에러+경계 공존 불가, (11) given은 payload 통째 대체 + Money 값 표현 불가 → 경계 시나리오 spec 표현 불가(F-대체), (12) stored 대문자 엔티티명에 오도적 진단.
- 21:50 [T09] F-기록 14건 확정(blocker 1: 마스킹 bindings 누수 / major 9 / minor 3 / info 1). Scorecard 9행 전부 PASS — 단 "우회 누적 후의 초록"임을 총평에 명시. 스코프 밖 무변경 git 증명 완료. 세션 산출물 3종(노트=session-log, 버그=FINDINGS Frictions, 자동화 후보=spec 2케이스+mode A 프로브 매트릭스) 마감.

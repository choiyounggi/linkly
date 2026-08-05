# 01 — authoring (문서 발견·어휘 근거) (Task 02)

## 읽기 경로와 발견 난이도

| 순서 | 문서 | 무엇을 얻었나 |
|------|------|----------------|
| 1 | AGENTS.md | ".lnpl 한 줄 쓰기 전 lnpl-authoring" 라우팅 — 명확, 1회에 도달 |
| 2 | plugins/lnpl/skills/lnpl-authoring/SKILL.md | 함정 3개(사전 밖 동사=no-op, 선언≠집행, if/for/while/switch 예약어), references 라우팅 표 |
| 3 | references/verbs.md | 닫힌 동사 16개. **`notify`/`send` 없음** → 알림 발송 모델링 불가, `create notification`으로 대체 (F-후보) |
| 4 | references/grammar.md | 제어 어휘 `when repeat parallel until pipeline merge`; 비교 연산자 **`<= >= < >`만 등재** |
| 5 | references/types.md | 필드 타입 폐집합 — UUID/Integer/DateTime 사용 |
| 6 | references/declarations.md | 집행 매트릭스 — retry·timeout enforced, response measured-only(의도적으로 사용) |
| 7 | references/spec.md | expect 키 12개, given 4형식 (`no <field>` 존재) |
| 8 | rfcs/0008-guard-conditions.md | 조건 2형태(Presence=bare CamelName / Comparison), until 이중 경계(_UNTIL_ROUND_CAP=16 + timeout deadline), mode B payload i64 전달 |
| 9 | examples/checkout.lnpl | 유일한 가드 사용 예 `when product.stock > 0` — dotted 필드 준거 |

발견 난이도 평가: 라우팅 자체는 AGENTS.md → SKILL.md → references 경로가 1회에
닿았다(마찰 없음). 단, **가드를 실제로 쓰는 공식 예제는 checkout의 1줄뿐**이고,
RFC-0008이 약속한 `examples/guarded.lnpl`(§5.2)은 레포에 **존재하지 않는다**
(F-후보: 문서가 가리키는 예제 부재).

## 구성요소별 어휘 근거 (계획 D7~D11 재검증 — references와 어긋남 없음)

| 소스 구성요소 | 근거 |
|---------------|------|
| `create notification` (알림 발송 대체) | verbs.md: notify/send 부재, create→RepositoryCall create |
| `when measurement.value > 100` | RFC-0008 §1 Comparison + checkout dotted 준거; `>` 는 grammar.md 등재 연산자 |
| `when priorNotification missing` | RFC-0008 §1 Presence ::= CamelName ('exists'\|'missing') |
| `until measurement.acknowledged > 0` | RFC-0008 §2.2; `==`/`!=`는 grammar.md에 없어 회피 (F-후보: RFC와 생성 참조 불일치) |
| `policy retry 3` / `timeout 3s` | declarations.md enforced 행 2개 |
| `performance response < 50ms` | declarations.md measured — **의도적 사용**(slo 관측 목적), 경고 예상 |
| spec 3블록 (정상/에러/경계) | spec.md given/expect 어휘 내에서만 구성 |

## 시도 집계

- 소스 작성: 1회 (계획의 확정 소스 그대로, 수정 없음)
- 컴파일: 1회 rc=0 (상세 → 02-compile.md)
- 폴백 사다리 발동: 0건

## 측정 순도 주석

파이프라인 명령 플래그(run --payload / build --field / diff)와 "시드 행 = payload
복사본" 사실은 **계획 단계에서 impl/ 내부 코드로 선확인**되었다 — 해당 항목의
발견 난이도 측정은 오염(FINDINGS 캐비앗 참조). 이 파일의 어휘·문법 마찰 기록은
허용 문서만으로 재검증했으므로 유효하다.

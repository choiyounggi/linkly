# evidence/01 — 어휘·명령 발견 (T02)

읽은 경로(순서): AGENTS.md 라우팅 표 → plugins/lnpl/skills/lnpl-authoring/SKILL.md →
references/{verbs,declarations,types,grammar,spec}.md → lnpl-kb/SKILL.md →
lnpl-spec/SKILL.md → lnpl-verify/SKILL.md → plugins/lnpl-dev/skills/lnpl-dev-env/SKILL.md →
examples/checkout.lnpl. 총 2홉(AGENTS.md → 스킬/references)으로 전 문서 도달 — 라우팅 마찰 없음.

## D16 구문 요소 → 출처 인용 표

| 구성요소 | 결정 | 출처 인용 |
|----------|------|-----------|
| 엔티티/필드 문법 | `entity X` / `field` 절 / `이름 타입` 행 | examples/checkout.lnpl (entity Product 블록); grammar.md 최상위 선언·절 목록 |
| 필드 네이밍 | **camelCase 필수** → `cardNumber`, `createdAt`, `paymentId`, `requestedAt` | KB `naming-entity-field-conventions`: "필드는 camelCase. `createdAt`. 문법이 `CamelName`을 요구한다" |
| 엔티티 네이밍 | 단수 명사 `Payment`, `Refund` | 같은 KB 문서: "entity는 단수 명사" |
| 워크플로 네이밍 | 동작 명사 `Approval`, `RefundRequest` (동사구 금지 → 계획의 ApprovePayment/RequestRefund를 교정) | 같은 KB 문서: "workflow는 동작 명사. Login·Checkout. 동사구(DoLogin)는 … 아니다" |
| 마스킹 타입 | `cardNumber Password` — 마스킹은 타입 주도가 유일 기제. 전용 PAN/CardNumber 타입 없음(F-후보) | declarations.md 집행 매트릭스: "`security encrypt` unenforced … (Password masking is a separate, type-driven behaviour)"; types.md 의미 타입 표(18종에 카드번호 타입 부재) |
| 금액 타입 | `amount Money` — 단 Money는 refinement facet 불가(`Money | —`)라 한도를 타입으로 표현 불가(F-후보). 한도는 가드로 | types.md Refinement 표 |
| 가드 | `when <field expr> <op> <literal>` ; 연산자는 `<= >= < >` 뿐 — **`==` 없음** → 전액 환불 등가 경계 가드 표현 불가(F-후보) | grammar.md 리터럴 절; checkout.lnpl `when product.stock > 0` |
| 분기/반복 | `if/for/while/switch` 예약어 — 렉서 거부. `when`/`repeat`/`until`만 | grammar.md 예약어 절 |
| policy | `retry`(enforced) `timeout`(enforced) `rollback`(unenforced) `parallel`(unenforced) | declarations.md 절별 허용 이름 + 집행 매트릭스 |
| security | `jwt`(무인자) `role`/`encrypt`(인자 필요) — 셋 다 unenforced | declarations.md: "인자를 받는 security 기제: `role` `encrypt`" |
| 동사 | validate/find/create/update/emit 등 16개만. `log`/`return`/`send`/`verify`는 no-op | verbs.md 표 전체 |
| event | `event RefundIssued on Refund create` | checkout.lnpl `event OrderPlaced on Order create`; grammar.md `event` |
| spec | `given`(`valid <명사>`/`empty repository`/`<field> <value>`/`no <field>`/`stored <entity> <field> <value>`), `expect` 키 12종 | references/spec.md |
| spec 도출 | 정상=항상(completed+steps); `policy retry N`→failed+attempts=N+1; 표 밖 기대 금지 | lnpl-spec SKILL.md 도출 표 |
| 기간 단위 | `ms` `s` `m` — **일(day) 단위 없음** → `timeout 3s`는 되지만 30일 기간을 duration으로 표현 불가(F-후보) | grammar.md 리터럴 절 |

## lnpl kb 조회 (D10, 4건)

| 질의 | 결과 |
|------|------|
| "결제 카드번호 필드 마스킹" | → `naming-entity-field-conventions` (네이밍 문서로 오라우팅 — security 카테고리 매칭 실패, F-후보: KB에 마스킹 항목 부재) |
| "환불 기간 제한 정책" | `(no match — the KB has nothing for that)` |
| "entity field naming payment refund" | → `naming-entity-field-conventions` (로드함, 위 표에 반영) |
| "amount limit validation" | `(no match)` |

KB에 근거가 없는 결정(기간 정책·금액 한도·마스킹 방식)은 그 사실을 밝히고 진행(lnpl-kb 규칙).

## 단계 → 명령 표 (`--help` 실측)

| Scorecard 행 | 명령 |
|--------------|------|
| authoring | (수작업 — 이 표+references가 근거) |
| parse·lower | `.venv/bin/lnpl compile -o qa/cases/payment-refund/payment-refund.lir.json qa/cases/payment-refund/payment-refund.lnpl` (진단 stderr·exit 0) |
| validate | `.venv/bin/python scripts/validate_ir.py qa/cases/payment-refund/payment-refund.lir.json` (스크립트 docstring 실측) |
| modeA | `.venv/bin/lnpl run --workflow <id> --payload <json> --json <src>` — **payload 주입 지원** → 경계값 프로브 가능 |
| modeB | `.venv/bin/lnpl build --workflow <id> --workdir .claude/tmp/t2-build <src>` (workdir을 tmp로 — 빌드 디렉터리 잔존 금지, AGENTS.md) |
| differential | `.venv/bin/lnpl diff --workflow <id> --workdir .claude/tmp/t2-diff [--payload <json>] <src>` |
| openapi | `.venv/bin/lnpl openapi -o qa/cases/payment-refund/payment-refund.openapi.json <src>` |
| spec | `.venv/bin/lnpl spec <src> --run` |

워크플로 지정 인자는 "workflow node id (default: the first one)" — id 도출 규칙(KB 문서: 이름→id)이 있으므로 실행 시 실측해 기록한다.

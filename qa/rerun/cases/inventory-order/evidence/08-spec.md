# evidence/08-spec — spec 매니페스트 실행 (재측정 Task 05)

재시도 수: **2** (.lnpl 수정→재실행 2회 — 아래 타임라인. 원 실측도 spec 2회였으나
원인은 다르다: 원=블록 병합 우회, 이번=given 필드 해석 갭 우회)

## F-7 재검 — 3블록이 3케이스로 분리된다

```
$ .venv/bin/lnpl spec <src> -o .claude/tmp/qa-r1/manifest.json
# rc=0
wrote .claude/tmp/qa-r1/manifest.json (3 case(s))
```

원 증상("3블록 → `1 case(s)` 침묵 병합, given 연결·when 3회 반복·completed와
failed 동시 expect") **소멸** — 매니페스트에 케이스 3개가 각자의 given/when/
expect로 분리. F-8 재검: `stored Product stock 5`(대문자 선언명)가 **그대로
수용**(원: 소문자만 + spec --run에서야 거부).

## 타임라인 (수정→재실행 각 1회)

| 시도 | 명령 | rc | 출력 원문(핵심) | 조치 |
|------|------|----|-----------------|------|
| 1 (given `quantity 2`) | `lnpl spec <src> --run` | 2 | `compile error: unsupported given: 'quantity 2' (use … `<field> <value>`, `no <field>` naming a declared field, …)` — quantity는 선언된 필드인데 거부 | 점 표기로 재시도 |
| 2 (given `order.quantity 2`) | 동일 | 2 | 동일 에러 | 특성화 프로브(스크래치 사본 5종, 케이스 파일 무수정)로 원인 규명 → given 재설계 |
| 3 (stock 제어 3케이스) | 동일 | **0** | `spec: 9 passed, 0 failed` | 성공 |

## 특성화 프로브 결과 (스크래치 사본 — N-4의 근거)

| given | 필드 소속 | 결과 |
|-------|----------|------|
| `stock 5` | Product(읽힘 — find) | **수용** |
| `name widget` | Product | **수용** |
| `quantity 2` | Order(생성 대상) | 거부 |
| `quantity 2` (타입을 Integer로 바꿔도) | Order | 거부 — refinement 여부와 무관 |
| `placedAt …` / `no quantity` | Order | 거부 |

→ `<field> <value>`/`no <field>` given은 **워크플로가 읽는 엔티티(Product)의
필드만** 해석한다. 검증(validate) 대상인 입력 엔티티(Order)의 필드 — 경계 spec에
가장 필요한 필드 — 는 설정 불가. 진단은 "naming a declared field"라고만 말해
원인(읽힘 엔티티 한정)을 가리키지 않는다. **신규 마찰 N-4.**

## 최종 실행 (시도 3 — stock 제어로 정상+경계+에러 3케이스)

```
$ .venv/bin/lnpl spec <src> --run        # rc=0  (--strict도 rc=0)
PASS PlaceOrder spec 1 — completed / steps 5 / rows Order 1 / effects 5 / effects complete
PASS PlaceOrder spec 2 — completed / rows Order 1
PASS PlaceOrder spec 3 — steps 2 / rows Order 0
spec: 9 passed, 0 failed
```

| 케이스 | given | 종류 | 판별력(단언이 실패할 수 있는 조건) |
|--------|-------|------|-----------------------------------|
| spec 1 | stored Product stock 5 (기본 qty=1) | 정상 | 가드·차감·생성 어느 하나만 깨져도 steps/rows/effects 단언 실패 |
| spec 2 | stored Product stock 1 (qty=1 — **정확 한계**) | 경계 | 가드가 `>=`가 아니라 `>`면 rows Order 0으로 실패 — S5 경계를 언어 안에서 검증 |
| spec 3 | stored Product stock 0 | 에러(재고 부족 거부) | 가드가 상시 참이면 steps 5·rows 1로 실패 — S3 동형 |

판정: PASS — **정상+에러+경계 3시나리오가 spec 언어 안에서 원형 작성·통과**
(원: 1케이스 축소 우회). 잔존 제약: qty=0 경계(S4)는 N-4로 인해 spec에 실을 수
없어 런타임 실측(evidence/04 S4, rc=1)으로 검증 — CASE-SPEC의 S4 관측 지점
조항(payload 구동) 충족.

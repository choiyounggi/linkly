# evidence/05-modeB — MLIR→네이티브 컴파일·실행 (재측정 Task 04)

재시도 수: 0 (전 런 1회 통과 — 원 실측의 1회는 `--field` 키 형식 규명이었는데,
이번엔 오키가 즉시 거부되어 규명 자체가 불필요했다)
환경: export 4줄 적용(evidence/00), dev_doctor rc=0. AGENTS.md의 "모드 B 대량
실패(7f/62e)"는 이 케이스에서 재현되지 않음 — 빌드·실행 전부 성공.

## F-9 재검 — 오키는 이제 거부된다

```
$ lnpl build <src> --run --workdir .claude/tmp/qa-r1/build --field stock=5
# rc=2
error: --field name(s) stock do not match any comparison-guard field of
workflow wf.place.order (valid: input.quantity, product.stock)
```

원 증상(침묵 무시 + 기본값 0 평가) 소멸 — 유효 키 목록까지 제시.

## 컨트롤 페어 (D7 — 매트릭스 전 레버 연결 증명)

| 런 | --field | rc | 실행된 스텝 |
|----|---------|----|------------|
| true | `product.stock=5 input.quantity=2` | 0 | **5스텝**(validate·find·create·**set**·update) |
| false | `product.stock=1 input.quantity=2` | 0 | **2스텝**(validate·find) |

관측 플립 확인 — 이후 매트릭스 유효. mode B가 Assignment(set) 스텝을
실행한다(원 실측엔 없던 스텝).

## S1~S5 매트릭스 (`--field product.stock=<s> input.quantity=<q>`)

| 시나리오 | field | rc | 스텝 수 | 판정 |
|----------|-------|----|--------|------|
| S1 | 5,2 | 0 | 5 | ✅ mode A와 일치 |
| S2 | 1,2 | 0 | 2 | ✅ 가드 스킵 일치 |
| S3 | 0,1 | 0 | 2 | ✅ 일치 |
| S4 | 5,0 | 0 | **5** | ⚠️ mode A(rc=1 failed)와 다름 — 아래 해석 |
| S5 | 5,5 | 0 | 5 | ✅ 일치 |

S4 해석(diff --payload로 판별, evidence/06): `--field`는 문서대로 **비교 가드
필드 전용**이라 검증(payload) 경로에 도달하지 않는다 — 가드는 5>=0 참, validate는
기본 샘플 payload(quantity=1)를 검사했다. 같은 qty=0을 **payload로** 주면 양
모드 모두 failed(EQUIVALENT). 즉 refinement 미집행이 아니라 주입 채널의 스코프
차이다(신규 마찰 N-3: --field와 검증 경로의 상호작용이 문서에 없어 오독 유도).

## 기타 관측

- `build`에 `--strict` 플래그 없음: `lnpl: error: unrecognized arguments:
  --strict` (rc=2, argparse 거부) — 거부 rc 게이트는 mode A(run)·spec에만 존재.
- mode B 출력에는 mode A의 `skipped by …` 레코드·`guard-skipped-steps` 진단이
  없다(2스텝 + completed만) — 거부 관측성의 모드 간 비대칭(신규 마찰 N-2).

판정: PASS(빌드·실행·가드 의미론 mode A 일치). 원 F-9 증상 소멸.

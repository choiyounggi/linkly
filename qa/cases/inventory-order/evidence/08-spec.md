# evidence/08-spec — spec 매니페스트 실행 (Task 06)

재시도 수: 2 (.lnpl 시도 4·5 — 아래 타임라인)

## 타임라인

| .lnpl 시도 | 명령 | rc | 출력 원문(핵심) |
|-----------|------|----|-----------------|
| 3 (spec 3블록) | `lnpl spec <src> --run` | 2 | `compile error: given 'stored Product stock 0' names 'Product', which is not a declared entity` |
| 4 (소문자 `stored product`) | 동일 | 2 | ``compile error: `empty repository` and `stored ...` contradict each other: there is no row to store into an empty store. Drop one.`` |
| 4 (manifest 추출 `-o`) | `lnpl spec <src> -o manifest.json` | 0 | `wrote … (1 case(s))` — **3개 spec 블록이 케이스 1개로 침묵 병합**: given 3줄 연결, when 3회 반복, expect에 `completed`와 `failed` 동시 포함 |
| 5 (spec 1블록으로 축소) | `lnpl spec <src> --run` | 0 | 아래 |

## 최종 실행 (시도 5)

```
$ .venv/bin/lnpl spec qa/cases/inventory-order/inventory-order.lnpl --run
# rc=0
PASS PlaceOrder spec — completed (status=completed)
PASS PlaceOrder spec — steps 4 (steps=4 want=4)
PASS PlaceOrder spec — rows Order 1 (Order rows=1 want=1)
PASS PlaceOrder spec — effects 4 (effects=4 want=4)
PASS PlaceOrder spec — effects complete (every step performed an effect)
spec: 5 passed, 0 failed
```

판정: PASS(정상 케이스 1개, 단언 5건). 단 DoD의 "정상+에러+경계 3시나리오"는
**spec으로 표현 불가**(워크플로당 케이스 1개 — FINDINGS F-7) → 에러(retry
attempts=4)·경계(stock 0/qty 0/qty=stock)는 evidence/04·05의 런타임 실측으로 대체.
`stored`의 엔티티명은 소문자만 인식(F-8), 병합은 파싱 시 무진단(F-7).

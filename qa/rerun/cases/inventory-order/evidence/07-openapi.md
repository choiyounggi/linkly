# evidence/07-openapi — OpenAPI 3.1 생성 (재측정 Task 05)

재시도 수: 0 (최종 소스 기준 재생성 1회 포함 총 2회 실행, 모두 rc=0)

```
$ .venv/bin/lnpl openapi qa/rerun/cases/inventory-order/inventory-order.lnpl \
    -o qa/rerun/cases/inventory-order/inventory-order.openapi.json
# rc=0
wrote qa/rerun/cases/inventory-order/inventory-order.openapi.json (1 path(s))
$ .venv/bin/python -m json.tool <산출물>   # rc=0 (유효 JSON)
```

생성 내용: `openapi: 3.1.0`, 경로 1개 `POST /order-service/place-order`,
응답 200/400/504. description에 **5스텝**(set 스텝 포함) 순서 명시:

> Steps: validate order -> find product -> create order -> set product.stock
> to product.stock - input.quantity -> update product

`quantity`는 `$ref: PositiveInteger` 스키마로 문서화.

판정: PASS. 원 실측의 주의점("400 서술은 문서뿐 — refinement 런타임 미집행이라
문서와 거동이 어긋남")이 **소멸**: qty=0이 실제로 validate 단계에서 거부되므로
(evidence/04 S4, rc=1) 400 서술과 런타임 거동이 이제 일치한다.

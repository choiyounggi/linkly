# evidence/07-openapi — OpenAPI 3.1 생성 (Task 06)

재시도 수: 0 (최종 소스 기준 재생성 1회 포함 총 2회 실행, 모두 rc=0)

```
$ .venv/bin/lnpl openapi qa/cases/inventory-order/inventory-order.lnpl \
    -o qa/cases/inventory-order/inventory-order.openapi.json
# rc=0
wrote qa/cases/inventory-order/inventory-order.openapi.json (1 path(s))
$ .venv/bin/python -m json.tool qa/cases/inventory-order/inventory-order.openapi.json
# rc=0 (유효 JSON)
```

생성 내용 확인: `openapi: 3.1.0`, 경로 1개 `POST /order-service/place-order`,
응답 200(completed)/400(validation failed)/504(deadline exceeded),
description에 스텝 4개 순서 명시.

판정: PASS. 주: 400 응답은 의미 타입 검증(UUID 등)까지만 실제 동작을 반영 —
refinement facet(min=1)은 런타임 미집행이므로(evidence/04) 문서와 실제 거동이
어긋날 수 있는 지점이다.

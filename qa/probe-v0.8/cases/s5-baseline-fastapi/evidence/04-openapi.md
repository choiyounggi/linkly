# 04 — OpenAPI 3.1 (live server)

`FastAPI(title="OrderHub", openapi_version="3.1.0")`로 명시 설정(`src/orderhub/app.py`).

명령: `uvicorn orderhub.app:app --port 8765` (background) 후
`curl -s localhost:8765/openapi.json` → `evidence/openapi.json`에 저장.

```
$ python -c "import json; d=json.load(open('evidence/openapi.json')); print(d['openapi'])"
3.1.0
```

경로 목록 (7개):

```
/orders                          [post]
/orders/{order_id}               [get]
/orders/{order_id}/cancel        [post]
/orders/{order_id}/deliver       [post]
/orders/{order_id}/pay           [post]
/orders/{order_id}/ship          [post]
/payments/{payment_id}/refund    [post]
```

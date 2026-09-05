# 06 — R10 변경 요청: gift_wrap

요구: "주문 라인에 `gift_wrap` 옵션 추가, 라인당 $2.00 가산, `digital` 상품엔 불가(거부)."

스냅샷: `cp -R src .claude/tmp/src-pre-r10` (커밋 없이 순수 파일 비교로 diff 측정).

## 반영한 파일 (3개, 규칙을 찾기 위해 연 파일 수와 동일)

1. `src/orderhub/db.py` — `order_line` 테이블에 `gift_wrap` 컬럼 추가 (스키마를 먼저 확인)
2. `src/orderhub/orders/router.py` — `OrderLineIn` 요청 모델에 `gift_wrap: bool = False` 추가 (요청 파싱 지점)
3. `src/orderhub/orders/service.py` — `place_order`의 라인별 계산(line_total)에 `GIFT_WRAP_CENTS`
   가산 + `kind == "digital"`이면 `BusinessRule("gift_wrap_not_allowed")`로 전체 롤백 +
   `get_order`의 응답 직렬화에 `gift_wrap` 필드 추가 (비즈니스 규칙이 있는 지점)

## diff 크기

`diff -ru --exclude=__pycache__ <pre-r10> <post-r10>` (전문):

```diff
diff -ru --exclude=__pycache__ src-pre-r10/orderhub/db.py .../db.py
--- src-pre-r10/orderhub/db.py
+++ .../db.py
@@ -48,7 +48,8 @@
             product_sku TEXT NOT NULL REFERENCES product(sku),
             qty INTEGER NOT NULL,
             unit_price INTEGER NOT NULL,
-            line_total INTEGER NOT NULL
+            line_total INTEGER NOT NULL,
+            gift_wrap INTEGER NOT NULL DEFAULT 0
         );

diff -ru --exclude=__pycache__ src-pre-r10/orderhub/orders/router.py .../router.py
--- src-pre-r10/orderhub/orders/router.py
+++ .../router.py
@@ -26,6 +26,7 @@
 class OrderLineIn(BaseModel):
     product_id: str
     qty: int = Field(ge=1)
+    gift_wrap: bool = False

diff -ru --exclude=__pycache__ src-pre-r10/orderhub/orders/service.py .../service.py
--- src-pre-r10/orderhub/orders/service.py
+++ .../service.py
@@ -29,6 +29,9 @@
+GIFT_WRAP_CENTS = 200
+
+
 def place_order(...):
@@ -50,9 +53,15 @@
             if product is None:
                 raise NotFound("product_not_found", line["product_id"])
+            gift_wrap = bool(line.get("gift_wrap", False))
+            if gift_wrap and product["kind"] == "digital":
+                raise BusinessRule(
+                    "gift_wrap_not_allowed",
+                    f"{product['sku']} is digital, cannot be gift-wrapped",
+                )
             qty = line["qty"]
             unit_price = product["price"]
-            line_total = qty * unit_price
+            line_total = qty * unit_price + (GIFT_WRAP_CENTS if gift_wrap else 0)
             subtotal += line_total
             line_rows.append({..., "gift_wrap": gift_wrap})
@@ -79,14 +89,15 @@
             conn.execute(
                 """INSERT INTO order_line
-                   (order_id, product_sku, qty, unit_price, line_total)
-                   VALUES (?, ?, ?, ?, ?)""",
+                   (order_id, product_sku, qty, unit_price, line_total, gift_wrap)
+                   VALUES (?, ?, ?, ?, ?, ?)""",
                 (..., int(row["gift_wrap"])),
             )
@@ -158,6 +169,7 @@
                 "line_total": ln["line_total"],
+                "gift_wrap": bool(ln["gift_wrap"]),
             }
```

**소스 diff 통계**: 파일 3개, +18줄 / -4줄(파일 헤더 제외한 순수 변경분).
테스트는 별도로 `tests/test_a1_a8.py`에 3개 함수 추가(gift_wrap 정상/거부/경계 qty=1).

## 라운드

R10 자체에 든 라운드: 코드 3파일 수정 후 pytest 1회 실행 → 즉시 green(재시도 0회).
자세한 라운드 로그는 `evidence/01-authoring.md` round 21 참고.

## 기존 spec 중 깨진 것

**0건.** `gift_wrap` 필드가 기본값 `False`이므로 A1~A8 기존 8개 시나리오의 값(subtotal/
discount/tax/total 등)은 전혀 바뀌지 않음 — 기존 20개 통과 테스트 그대로 유지, 신규 3개
추가로 총 23 passed(+7 skipped, 변동 없음).

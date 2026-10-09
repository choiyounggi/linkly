import sqlite3
from datetime import datetime, timezone

from orderhub.errors import BusinessRule, IllegalTransition, InjectedFailure, NotFound
from orderhub.money import pct
from orderhub.orders import inventory, state


def seed_stock(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO stock (product_sku, on_hand) VALUES (?, ?)", ("P1", 5)
    )
    conn.execute(
        "INSERT OR IGNORE INTO stock (product_sku, on_hand) VALUES (?, ?)", ("P2", 999)
    )
    conn.execute(
        "INSERT OR IGNORE INTO stock (product_sku, on_hand) VALUES (?, ?)", ("P3", 0)
    )


def seed_customers(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO customer (id, tier, email) VALUES (?, ?, ?)",
        ("C1", "standard", "c1@example.com"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO customer (id, tier, email) VALUES (?, ?, ?)",
        ("C2", "vip", "c2@example.com"),
    )


GIFT_WRAP_CENTS = 200


def place_order(conn: sqlite3.Connection, customer_id: str, lines: list[dict]) -> dict:
    if not lines:
        raise BusinessRule("empty_order", "order must have at least one line")

    conn.execute("BEGIN IMMEDIATE")
    try:
        customer = conn.execute(
            "SELECT id, tier FROM customer WHERE id = ?", (customer_id,)
        ).fetchone()
        if customer is None:
            raise NotFound("customer_not_found", customer_id)

        subtotal = 0
        line_rows = []
        for line in lines:
            product = conn.execute(
                "SELECT sku, price, kind FROM product WHERE sku = ?",
                (line["product_id"],),
            ).fetchone()
            if product is None:
                raise NotFound("product_not_found", line["product_id"])
            gift_wrap = bool(line.get("gift_wrap", False))
            if gift_wrap and product["kind"] == "digital":
                raise BusinessRule(
                    "gift_wrap_not_allowed",
                    f"{product['sku']} is digital, cannot be gift-wrapped",
                )
            qty = line["qty"]
            unit_price = product["price"]
            line_total = qty * unit_price + (GIFT_WRAP_CENTS if gift_wrap else 0)
            subtotal += line_total
            line_rows.append(
                {
                    "product_sku": product["sku"],
                    "qty": qty,
                    "unit_price": unit_price,
                    "line_total": line_total,
                    "gift_wrap": gift_wrap,
                }
            )

        discount = pct(subtotal, 1000) if customer["tier"] == "vip" else 0
        tax = pct(subtotal - discount, 800)
        total = subtotal - discount + tax
        created_at = datetime.now(timezone.utc).isoformat()

        cur = conn.execute(
            """INSERT INTO "order"
               (customer_id, status, subtotal, discount, tax, total, created_at)
               VALUES (?, 'pending', ?, ?, ?, ?, ?)""",
            (customer_id, subtotal, discount, tax, total, created_at),
        )
        order_id = cur.lastrowid

        for row in line_rows:
            conn.execute(
                """INSERT INTO order_line
                   (order_id, product_sku, qty, unit_price, line_total, gift_wrap)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    order_id,
                    row["product_sku"],
                    row["qty"],
                    row["unit_price"],
                    row["line_total"],
                    int(row["gift_wrap"]),
                ),
            )
            # insufficient stock rolls the whole transaction back — no partial reservation
            inventory.reserve(conn, row["product_sku"], order_id, row["qty"])

        conn.execute("COMMIT")
    except inventory.InsufficientStock as exc:
        conn.execute("ROLLBACK")
        raise BusinessRule("insufficient_stock", str(exc)) from exc
    except (BusinessRule, NotFound):
        conn.execute("ROLLBACK")
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return get_order(conn, order_id)


def cancel_order(conn: sqlite3.Connection, order_id: int, fail_after: str | None = None) -> dict:
    conn.execute("BEGIN IMMEDIATE")
    try:
        state.transition(conn, order_id, "cancelled")

        payment = conn.execute(
            "SELECT id, amount FROM payment WHERE order_id = ? AND status = 'captured'",
            (order_id,),
        ).fetchone()
        if payment is not None:
            conn.execute(
                "INSERT INTO refund (payment_id, amount, reason) VALUES (?, ?, 'cancel')",
                (payment["id"], payment["amount"]),
            )

        if fail_after == "refund":
            raise InjectedFailure("injected_failure", "fault injected after refund insert")

        inventory.release(conn, order_id)
        conn.execute("COMMIT")
    except (IllegalTransition, InjectedFailure):
        conn.execute("ROLLBACK")
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return get_order(conn, order_id)


def get_order(conn: sqlite3.Connection, order_id: int) -> dict:
    order = conn.execute('SELECT * FROM "order" WHERE id = ?', (order_id,)).fetchone()
    if order is None:
        raise NotFound("order_not_found", str(order_id))
    lines = conn.execute(
        "SELECT * FROM order_line WHERE order_id = ?", (order_id,)
    ).fetchall()
    return {
        "id": order["id"],
        "customer_id": order["customer_id"],
        "status": order["status"],
        "subtotal": order["subtotal"],
        "discount": order["discount"],
        "tax": order["tax"],
        "total": order["total"],
        "created_at": order["created_at"],
        "lines": [
            {
                "product_id": ln["product_sku"],
                "qty": ln["qty"],
                "unit_price": ln["unit_price"],
                "line_total": ln["line_total"],
                "gift_wrap": bool(ln["gift_wrap"]),
            }
            for ln in lines
        ],
    }

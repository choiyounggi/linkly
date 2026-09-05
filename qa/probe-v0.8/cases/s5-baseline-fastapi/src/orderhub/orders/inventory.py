import sqlite3


class InsufficientStock(Exception):
    pass


def reserve(conn: sqlite3.Connection, product_sku: str, order_id: int, qty: int) -> None:
    row = conn.execute(
        "SELECT on_hand FROM stock WHERE product_sku = ?", (product_sku,)
    ).fetchone()
    if row is None or row["on_hand"] < qty:
        raise InsufficientStock(product_sku)
    conn.execute(
        "UPDATE stock SET on_hand = on_hand - ? WHERE product_sku = ?",
        (qty, product_sku),
    )
    conn.execute(
        "INSERT INTO stock_reservation (product_sku, order_id, qty) VALUES (?, ?, ?)",
        (product_sku, order_id, qty),
    )


def release(conn: sqlite3.Connection, order_id: int) -> None:
    rows = conn.execute(
        "SELECT id, product_sku, qty FROM stock_reservation WHERE order_id = ?",
        (order_id,),
    ).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE stock SET on_hand = on_hand + ? WHERE product_sku = ?",
            (row["qty"], row["product_sku"]),
        )
        conn.execute("DELETE FROM stock_reservation WHERE id = ?", (row["id"],))

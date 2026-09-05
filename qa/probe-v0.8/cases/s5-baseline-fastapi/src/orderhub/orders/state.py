import sqlite3

from orderhub.errors import IllegalTransition

TRANSITIONS = {
    "pending": {"paid", "cancelled"},
    "paid": {"shipped", "cancelled"},
    "shipped": {"delivered"},
    "delivered": set(),
    "cancelled": set(),
}


def transition(conn: sqlite3.Connection, order_id: int, to: str) -> None:
    row = conn.execute('SELECT status FROM "order" WHERE id = ?', (order_id,)).fetchone()
    if row is None:
        raise IllegalTransition("illegal_transition", f"order {order_id} not found")
    current = row["status"]
    if to not in TRANSITIONS.get(current, set()):
        raise IllegalTransition(
            "illegal_transition", f"cannot transition from {current} to {to}"
        )
    conn.execute('UPDATE "order" SET status = ? WHERE id = ?', (to, order_id))

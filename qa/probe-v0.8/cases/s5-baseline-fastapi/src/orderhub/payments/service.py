import logging
import sqlite3

from orderhub.errors import BusinessRule, IllegalTransition, NotFound
from orderhub.orders import state

REFUND_LIMIT = 3

logger = logging.getLogger(__name__)


def pay(
    conn: sqlite3.Connection,
    order_id: int,
    amount: int,
    card_number: str,
    simulate_failure: bool = False,
) -> dict:
    conn.execute("BEGIN IMMEDIATE")
    try:
        order = conn.execute(
            'SELECT status, total FROM "order" WHERE id = ?', (order_id,)
        ).fetchone()
        if order is None or order["status"] != "pending":
            raise IllegalTransition(
                "illegal_transition", "order must be pending to accept payment"
            )
        if amount != order["total"]:
            raise BusinessRule("amount_mismatch", f"amount {amount} != total {order['total']}")
        if simulate_failure:
            raise BusinessRule("payment_declined", "payment simulated failure")

        card_last4 = card_number[-4:]
        cur = conn.execute(
            "INSERT INTO payment (order_id, amount, card_last4, status) VALUES (?, ?, ?, 'captured')",
            (order_id, amount, card_last4),
        )
        payment_id = cur.lastrowid
        state.transition(conn, order_id, "paid")
        conn.execute("COMMIT")
    except (BusinessRule, IllegalTransition):
        conn.execute("ROLLBACK")
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise

    logger.info("payment captured order=%s last4=%s", order_id, card_last4)
    return get_payment(conn, payment_id)


def refund(conn: sqlite3.Connection, payment_id: int, amount: int, reason: str) -> dict:
    conn.execute("BEGIN IMMEDIATE")
    try:
        payment = conn.execute(
            "SELECT id, amount FROM payment WHERE id = ?", (payment_id,)
        ).fetchone()
        if payment is None:
            raise NotFound("payment_not_found", str(payment_id))

        existing = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(amount), 0) AS total FROM refund WHERE payment_id = ?",
            (payment_id,),
        ).fetchone()
        if existing["n"] >= REFUND_LIMIT:
            raise BusinessRule("refund_limit", "no more than 3 refunds per payment")
        if existing["total"] + amount > payment["amount"]:
            raise BusinessRule(
                "refund_exceeds_payment",
                f"cumulative refund {existing['total'] + amount} exceeds payment {payment['amount']}",
            )

        conn.execute(
            "INSERT INTO refund (payment_id, amount, reason) VALUES (?, ?, ?)",
            (payment_id, amount, reason),
        )
        conn.execute("COMMIT")
    except (BusinessRule, NotFound):
        conn.execute("ROLLBACK")
        raise
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return get_refund_summary(conn, payment_id)


def get_refund_summary(conn: sqlite3.Connection, payment_id: int) -> dict:
    rows = conn.execute(
        "SELECT id, amount, reason FROM refund WHERE payment_id = ?", (payment_id,)
    ).fetchall()
    total = sum(r["amount"] for r in rows)
    return {
        "payment_id": payment_id,
        "refunds": [{"id": r["id"], "amount": r["amount"], "reason": r["reason"]} for r in rows],
        "cumulative_refunded": total,
    }


def get_payment(conn: sqlite3.Connection, payment_id: int) -> dict:
    row = conn.execute("SELECT * FROM payment WHERE id = ?", (payment_id,)).fetchone()
    return {
        "id": row["id"],
        "order_id": row["order_id"],
        "amount": row["amount"],
        "card_last4": row["card_last4"],
        "status": row["status"],
    }

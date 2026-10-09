import os
import sqlite3

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field

from orderhub.orders import service, state

router = APIRouter()


def get_db_path() -> str:
    return os.environ.get("ORDERHUB_DB", "orderhub.db")


def get_conn():
    from orderhub.db import connect

    conn = connect(get_db_path())
    try:
        yield conn
    finally:
        conn.close()


class OrderLineIn(BaseModel):
    product_id: str
    qty: int = Field(ge=1)
    gift_wrap: bool = False


class OrderIn(BaseModel):
    customer_id: str
    lines: list[OrderLineIn] = Field(min_length=1)


@router.post("/orders", status_code=201)
def create_order(body: OrderIn, conn: sqlite3.Connection = Depends(get_conn)):
    lines = [line.model_dump() for line in body.lines]
    return service.place_order(conn, body.customer_id, lines)


@router.get("/orders/{order_id}")
def read_order(order_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    return service.get_order(conn, order_id)


@router.post("/orders/{order_id}/ship")
def ship_order(order_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    conn.execute("BEGIN IMMEDIATE")
    try:
        state.transition(conn, order_id, "shipped")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return service.get_order(conn, order_id)


@router.post("/orders/{order_id}/deliver")
def deliver_order(order_id: int, conn: sqlite3.Connection = Depends(get_conn)):
    conn.execute("BEGIN IMMEDIATE")
    try:
        state.transition(conn, order_id, "delivered")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return service.get_order(conn, order_id)


@router.post("/orders/{order_id}/cancel")
def cancel_order(
    order_id: int,
    conn: sqlite3.Connection = Depends(get_conn),
    x_test_fail_after: str | None = Header(default=None),
):
    fail_after = x_test_fail_after if os.environ.get("ORDERHUB_TEST_HOOKS") == "1" else None
    return service.cancel_order(conn, order_id, fail_after)

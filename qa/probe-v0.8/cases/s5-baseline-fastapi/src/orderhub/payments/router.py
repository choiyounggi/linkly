import sqlite3

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field

from orderhub.errors import Forbidden
from orderhub.orders.router import get_conn
from orderhub.payments import service

router = APIRouter()


def require_admin(x_role: str = Header(default="")) -> None:
    if x_role != "admin":
        raise Forbidden("forbidden", "admin role required")


class PayIn(BaseModel):
    amount: int
    card_number: str = Field(min_length=12, max_length=19, pattern=r"^\d+$")
    simulate_failure: bool = False


class RefundIn(BaseModel):
    amount: int = Field(gt=0)
    reason: str


@router.post("/orders/{order_id}/pay", status_code=201)
def pay_order(order_id: int, body: PayIn, conn: sqlite3.Connection = Depends(get_conn)):
    return service.pay(
        conn, order_id, body.amount, body.card_number, body.simulate_failure
    )


@router.post(
    "/payments/{payment_id}/refund", status_code=201, dependencies=[Depends(require_admin)]
)
def refund_payment(
    payment_id: int, body: RefundIn, conn: sqlite3.Connection = Depends(get_conn)
):
    return service.refund(conn, payment_id, body.amount, body.reason)

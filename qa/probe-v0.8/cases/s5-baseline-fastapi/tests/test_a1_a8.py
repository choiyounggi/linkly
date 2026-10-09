import itertools
import logging

import pytest

# Hardcoded from s1.md R4 — deliberately NOT imported from orderhub.orders.state,
# so a broken/over-permissive TRANSITIONS dict in the implementation cannot silently
# shrink or pass this parametrization (it must diverge from the spec's own truth).
ALL_STATUSES = ["pending", "paid", "shipped", "delivered", "cancelled"]
LEGAL_PAIRS = {
    ("pending", "paid"),
    ("pending", "cancelled"),
    ("paid", "shipped"),
    ("paid", "cancelled"),
    ("shipped", "delivered"),
}
ILLEGAL_PAIRS = [
    (a, b)
    for a, b in itertools.product(ALL_STATUSES, ALL_STATUSES)
    if a != b and (a, b) not in LEGAL_PAIRS
]


def _place_a1_order(c):
    resp = c.post("/orders", json={"customer_id": "C1", "lines": [{"product_id": "P1", "qty": 2}]})
    assert resp.status_code == 201
    return resp.json()


def test_a1_standard_order(client):
    c, db_path = client
    resp = c.post("/orders", json={"customer_id": "C1", "lines": [{"product_id": "P1", "qty": 2}]})
    assert resp.status_code == 201
    body = resp.json()
    assert body["subtotal"] == 3998
    assert body["discount"] == 0
    assert body["tax"] == 320
    assert body["total"] == 4318

    from orderhub.db import connect

    conn = connect(db_path)
    on_hand = conn.execute("SELECT on_hand FROM stock WHERE product_sku='P1'").fetchone()["on_hand"]
    assert on_hand == 3
    res_count = conn.execute(
        "SELECT COUNT(*) AS n FROM stock_reservation WHERE order_id=?", (body["id"],)
    ).fetchone()["n"]
    assert res_count == 1
    conn.close()


def test_a2_vip_discount(client):
    c, db_path = client
    resp = c.post("/orders", json={"customer_id": "C2", "lines": [{"product_id": "P1", "qty": 3}]})
    assert resp.status_code == 201
    body = resp.json()
    assert body["subtotal"] == 5997
    assert body["discount"] == 600
    assert body["tax"] == 432
    assert body["total"] == 5829

    from orderhub.db import connect

    conn = connect(db_path)
    row = conn.execute('SELECT total FROM "order" WHERE id=?', (body["id"],)).fetchone()
    assert row["total"] == 5829
    conn.close()


def test_a3_insufficient_stock(client):
    c, db_path = client
    resp = c.post(
        "/orders",
        json={
            "customer_id": "C1",
            "lines": [
                {"product_id": "P1", "qty": 2},
                {"product_id": "P3", "qty": 1},
            ],
        },
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "insufficient_stock"

    from orderhub.db import connect

    conn = connect(db_path)
    res_count = conn.execute("SELECT COUNT(*) AS n FROM stock_reservation").fetchone()["n"]
    assert res_count == 0
    on_hand = conn.execute("SELECT on_hand FROM stock WHERE product_sku='P1'").fetchone()["on_hand"]
    assert on_hand == 5
    conn.close()


def test_a4_payment_success(client):
    c, db_path = client
    order = _place_a1_order(c)
    resp = c.post(
        f"/orders/{order['id']}/pay",
        json={"amount": 4318, "card_number": "4242424242424242"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["card_last4"] == "4242"
    assert "4242424242424242" not in resp.text

    from orderhub.db import connect

    conn = connect(db_path)
    payment = conn.execute(
        "SELECT status, card_last4 FROM payment WHERE order_id=?", (order["id"],)
    ).fetchone()
    assert payment["status"] == "captured"
    assert payment["card_last4"] == "4242"
    dump = "\n".join(conn.iterdump())
    assert "4242424242424242" not in dump
    assert "4242" in dump  # negative control: masked value is present
    order_row = conn.execute('SELECT status FROM "order" WHERE id=?', (order["id"],)).fetchone()
    assert order_row["status"] == "paid"
    conn.close()


def test_a4_pan_not_in_logs(client, caplog):
    c, db_path = client
    order = _place_a1_order(c)
    with caplog.at_level(logging.INFO, logger="orderhub.payments.service"):
        resp = c.post(
            f"/orders/{order['id']}/pay",
            json={"amount": 4318, "card_number": "4242424242424242"},
        )
    assert resp.status_code == 201
    assert "4242424242424242" not in caplog.text
    assert "4242" in caplog.text  # negative control


def test_a5_amount_mismatch(client):
    c, db_path = client
    order = _place_a1_order(c)
    resp = c.post(
        f"/orders/{order['id']}/pay",
        json={"amount": 100, "card_number": "4242424242424242"},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "amount_mismatch"

    from orderhub.db import connect

    conn = connect(db_path)
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM payment WHERE order_id=?", (order["id"],)
    ).fetchone()["n"]
    assert count == 0
    status = conn.execute('SELECT status FROM "order" WHERE id=?', (order["id"],)).fetchone()["status"]
    assert status == "pending"
    conn.close()


def test_simulate_failure(client):
    c, db_path = client
    order = _place_a1_order(c)
    resp = c.post(
        f"/orders/{order['id']}/pay",
        json={"amount": 4318, "card_number": "4242424242424242", "simulate_failure": True},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "payment_declined"

    from orderhub.db import connect

    conn = connect(db_path)
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM payment WHERE order_id=?", (order["id"],)
    ).fetchone()["n"]
    assert count == 0
    status = conn.execute('SELECT status FROM "order" WHERE id=?', (order["id"],)).fetchone()["status"]
    assert status == "pending"
    # R5: "예약은 유지" — a declined payment must not release the stock reservation
    on_hand = conn.execute("SELECT on_hand FROM stock WHERE product_sku='P1'").fetchone()["on_hand"]
    assert on_hand == 3
    res_count = conn.execute(
        "SELECT COUNT(*) AS n FROM stock_reservation WHERE order_id=?", (order["id"],)
    ).fetchone()["n"]
    assert res_count == 1
    conn.close()


@pytest.mark.parametrize("from_status,to_status", ILLEGAL_PAIRS)
def test_illegal_transitions(client, from_status, to_status):
    c, db_path = client
    order = _place_a1_order(c)

    from orderhub.db import connect

    conn = connect(db_path)
    conn.execute('UPDATE "order" SET status=? WHERE id=?', (from_status, order["id"]))
    conn.close()

    if to_status == "paid":
        endpoint = f"/orders/{order['id']}/pay"
        resp = c.post(endpoint, json={"amount": order["total"], "card_number": "4242424242424242"})
    elif to_status == "pending":
        pytest.skip("no endpoint reverts an order to pending — not part of the API surface")
    else:
        endpoint = {
            "shipped": f"/orders/{order['id']}/ship",
            "delivered": f"/orders/{order['id']}/deliver",
            "cancelled": f"/orders/{order['id']}/cancel",
        }[to_status]
        resp = c.post(endpoint)

    assert resp.status_code == 409
    assert resp.json()["code"] == "illegal_transition"

    conn = connect(db_path)
    status = conn.execute('SELECT status FROM "order" WHERE id=?', (order["id"],)).fetchone()["status"]
    assert status == from_status
    if to_status == "paid":
        payment_count = conn.execute("SELECT COUNT(*) AS n FROM payment").fetchone()["n"]
        assert payment_count == 0
    conn.close()


def _pay_a1_order(c, order):
    resp = c.post(
        f"/orders/{order['id']}/pay",
        json={"amount": order["total"], "card_number": "4242424242424242"},
    )
    assert resp.status_code == 201
    return resp.json()


def test_a6_illegal_cancel_after_ship(client):
    c, db_path = client
    order = _place_a1_order(c)
    _pay_a1_order(c, order)
    ship_resp = c.post(f"/orders/{order['id']}/ship")
    assert ship_resp.status_code == 200

    resp = c.post(f"/orders/{order['id']}/cancel")
    assert resp.status_code == 409
    assert resp.json()["code"] == "illegal_transition"

    from orderhub.db import connect

    conn = connect(db_path)
    status = conn.execute('SELECT status FROM "order" WHERE id=?', (order["id"],)).fetchone()["status"]
    assert status == "shipped"
    conn.close()


def test_a7_cancel_atomicity_refund_and_release(client):
    c, db_path = client
    order = _place_a1_order(c)
    _pay_a1_order(c, order)

    resp = c.post(f"/orders/{order['id']}/cancel")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cancelled"

    from orderhub.db import connect

    conn = connect(db_path)
    refund_row = conn.execute(
        "SELECT r.amount AS amount FROM refund r JOIN payment p ON r.payment_id = p.id WHERE p.order_id=?",
        (order["id"],),
    ).fetchone()
    assert refund_row["amount"] == 4318
    on_hand = conn.execute("SELECT on_hand FROM stock WHERE product_sku='P1'").fetchone()["on_hand"]
    assert on_hand == 5
    res_count = conn.execute(
        "SELECT COUNT(*) AS n FROM stock_reservation WHERE order_id=?", (order["id"],)
    ).fetchone()["n"]
    assert res_count == 0
    conn.close()


def test_cancel_atomic_injected_failure(client, monkeypatch):
    monkeypatch.setenv("ORDERHUB_TEST_HOOKS", "1")
    c, db_path = client
    order = _place_a1_order(c)
    _pay_a1_order(c, order)

    resp = c.post(f"/orders/{order['id']}/cancel", headers={"X-Test-Fail-After": "refund"})
    assert resp.status_code == 500
    assert resp.json()["code"] == "injected_failure"

    from orderhub.db import connect

    conn = connect(db_path)
    refund_count = conn.execute("SELECT COUNT(*) AS n FROM refund").fetchone()["n"]
    assert refund_count == 0  # rolled back with the rest of the transaction
    on_hand = conn.execute("SELECT on_hand FROM stock WHERE product_sku='P1'").fetchone()["on_hand"]
    assert on_hand == 3  # still reserved — release never committed
    status = conn.execute('SELECT status FROM "order" WHERE id=?', (order["id"],)).fetchone()["status"]
    assert status == "paid"
    conn.close()


def test_a8_refund_limit_and_admin_gate(client):
    c, db_path = client
    order = _place_a1_order(c)
    payment = _pay_a1_order(c, order)
    payment_id = payment["id"]

    non_admin_resp = c.post(f"/payments/{payment_id}/refund", json={"amount": 100, "reason": "x"})
    assert non_admin_resp.status_code == 403

    from orderhub.db import connect

    conn = connect(db_path)
    assert conn.execute("SELECT COUNT(*) AS n FROM refund").fetchone()["n"] == 0
    conn.close()

    admin_headers = {"X-Role": "admin"}
    r1 = c.post(
        f"/payments/{payment_id}/refund",
        json={"amount": 2000, "reason": "partial"},
        headers=admin_headers,
    )
    assert r1.status_code == 201
    r2 = c.post(
        f"/payments/{payment_id}/refund",
        json={"amount": 2000, "reason": "partial"},
        headers=admin_headers,
    )
    assert r2.status_code == 201
    r3 = c.post(
        f"/payments/{payment_id}/refund",
        json={"amount": 1000, "reason": "over"},
        headers=admin_headers,
    )
    assert r3.status_code == 422
    assert r3.json()["code"] == "refund_exceeds_payment"

    conn = connect(db_path)
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM refund r JOIN payment p ON r.payment_id=p.id WHERE p.id=?",
        (payment_id,),
    ).fetchone()["n"]
    assert count == 2
    conn.close()


def test_refund_limit_boundary(client):
    c, db_path = client
    order = _place_a1_order(c)
    payment = _pay_a1_order(c, order)
    payment_id = payment["id"]
    admin_headers = {"X-Role": "admin"}

    for _ in range(3):
        resp = c.post(
            f"/payments/{payment_id}/refund",
            json={"amount": 1, "reason": "cent"},
            headers=admin_headers,
        )
        assert resp.status_code == 201

    fourth = c.post(
        f"/payments/{payment_id}/refund",
        json={"amount": 1, "reason": "cent"},
        headers=admin_headers,
    )
    assert fourth.status_code == 422
    assert fourth.json()["code"] == "refund_limit"

    from orderhub.db import connect

    conn = connect(db_path)
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM refund r JOIN payment p ON r.payment_id=p.id WHERE p.id=?",
        (payment_id,),
    ).fetchone()["n"]
    assert count == 3
    conn.close()


def test_r10_gift_wrap_physical(client):
    c, db_path = client
    resp = c.post(
        "/orders",
        json={"customer_id": "C1", "lines": [{"product_id": "P1", "qty": 2, "gift_wrap": True}]},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["lines"][0]["line_total"] == 4198
    assert body["subtotal"] == 4198
    assert body["tax"] == 336
    assert body["total"] == 4534

    from orderhub.db import connect

    conn = connect(db_path)
    row = conn.execute(
        "SELECT gift_wrap, line_total FROM order_line WHERE order_id=?", (body["id"],)
    ).fetchone()
    assert row["gift_wrap"] == 1
    assert row["line_total"] == 4198
    conn.close()


def test_r10_gift_wrap_digital_rejected(client):
    c, db_path = client
    resp = c.post(
        "/orders",
        json={"customer_id": "C1", "lines": [{"product_id": "P2", "qty": 1, "gift_wrap": True}]},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "gift_wrap_not_allowed"

    from orderhub.db import connect

    conn = connect(db_path)
    count = conn.execute('SELECT COUNT(*) AS n FROM "order"').fetchone()["n"]
    assert count == 0  # whole order rejected, nothing committed
    conn.close()


def test_r10_gift_wrap_boundary_qty1(client):
    c, db_path = client
    resp = c.post(
        "/orders",
        json={"customer_id": "C1", "lines": [{"product_id": "P1", "qty": 1, "gift_wrap": True}]},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["lines"][0]["line_total"] == 2199
    assert body["total"] == 2375

    from orderhub.db import connect

    conn = connect(db_path)
    row = conn.execute(
        "SELECT gift_wrap FROM order_line WHERE order_id=?", (body["id"],)
    ).fetchone()
    assert row["gift_wrap"] == 1
    conn.close()

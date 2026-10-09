import sqlite3


def seed(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO product (sku, name, price, kind, active) VALUES (?, ?, ?, ?, 1)",
        ("P1", "P1", 1999, "physical"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO product (sku, name, price, kind, active) VALUES (?, ?, ?, ?, 1)",
        ("P2", "P2", 999, "digital"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO product (sku, name, price, kind, active) VALUES (?, ?, ?, ?, 1)",
        ("P3", "P3", 500, "physical"),
    )

import sqlite3


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS category (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS product (
            sku TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('physical', 'digital')),
            active INTEGER NOT NULL DEFAULT 1,
            category_id TEXT REFERENCES category(id)
        );

        CREATE TABLE IF NOT EXISTS customer (
            id TEXT PRIMARY KEY,
            tier TEXT NOT NULL CHECK (tier IN ('standard', 'vip')),
            email TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS "order" (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id TEXT NOT NULL REFERENCES customer(id),
            status TEXT NOT NULL,
            subtotal INTEGER NOT NULL,
            discount INTEGER NOT NULL,
            tax INTEGER NOT NULL,
            total INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS order_line (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL REFERENCES "order"(id),
            product_sku TEXT NOT NULL REFERENCES product(sku),
            qty INTEGER NOT NULL,
            unit_price INTEGER NOT NULL,
            line_total INTEGER NOT NULL,
            gift_wrap INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS payment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL REFERENCES "order"(id),
            amount INTEGER NOT NULL,
            card_last4 TEXT NOT NULL,
            status TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS refund (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_id INTEGER NOT NULL REFERENCES payment(id),
            amount INTEGER NOT NULL,
            reason TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS stock (
            product_sku TEXT PRIMARY KEY REFERENCES product(sku),
            on_hand INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS stock_reservation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_sku TEXT NOT NULL REFERENCES product(sku),
            order_id INTEGER NOT NULL REFERENCES "order"(id),
            qty INTEGER NOT NULL
        );
        """
    )

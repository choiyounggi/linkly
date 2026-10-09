#!/usr/bin/env python3
"""Deterministic seed generator for s3-batch-report (D2).

Writes directly into the sqlite `lnpl_rows` table (docs/backends.md §3 schema),
which is D3's rung-1 store-write path. Money fields are stored as
{"amount": "<minor units>", "currency": "USD"} per RFC-0044 §1.
"""
import argparse
import hashlib
import json
import random
import sqlite3
import sys
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS lnpl_rows (
    entity_id TEXT NOT NULL,
    row_key   TEXT NOT NULL,
    payload   TEXT NOT NULL,
    _version  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (entity_id, row_key)
)
"""

MONTHS = ["2026-05", "2026-06", "2026-07"]
MONTH_DAYS = {"2026-05": 31, "2026-06": 30, "2026-07": 31}


def money(cents: int) -> dict:
    # Money.amount is a decimal STRING with exactly `exponent` decimal places
    # for the currency (RFC-0044 §3) -- NOT a bare minor-unit integer string.
    # Discovered via `money-encode-precision` RunError (evidence/02-compile.md).
    return {"amount": f"{cents // 100}.{cents % 100:02d}", "currency": "USD"}


def merchant_row(mid: str, name: str, tier: str) -> dict:
    return {"id": mid, "name": name, "tier": tier}


def tx_row(tid: str, merchant: str, amount_cents: int, fee_cents: int, status: str, occurred_at: str) -> dict:
    month_key = occurred_at[:7]
    day_key = occurred_at[:10]
    return {
        "id": tid,
        "merchant": merchant,
        "amount": money(amount_cents),
        "fee": money(fee_cents),
        "status": status,
        "occurredAt": occurred_at,
        "monthKey": month_key,
        "dayKey": day_key,
    }


def gen_small():
    """C1-C3 fixture: M1 (3 settled + 1 refunded), M2 (none), M3 (1001 settled)."""
    merchants = [
        merchant_row("M1", "Merchant One", "small"),
        merchant_row("M2", "Merchant Two", "small"),
        merchant_row("M3", "Merchant Three", "large"),
    ]
    txs = []
    n = 0

    def add(merchant, amount, fee, status, day):
        nonlocal n
        n += 1
        txs.append(tx_row(f"c1-tx-{n:05d}", merchant, amount, fee, status, f"2026-07-{day:02d}T10:00:00Z"))

    # C1: M1 settled 1000/2000/3000 (fee 30/60/90) + refunded 9999
    add("M1", 1000, 30, "settled", 1)
    add("M1", 2000, 60, "settled", 2)
    add("M1", 3000, 90, "settled", 3)
    add("M1", 9999, 0, "refunded", 4)
    # C2: M2 has zero transactions — no rows added
    # C3: M3 settled 1001 tx x 100 amount, fee 3 each
    for i in range(1001):
        add("M3", 100, 3, "settled", (i % 28) + 1)
    return merchants, txs


def gen_full(total: int, seed: int = 42):
    """R1 fixture: `total` Transaction rows across 50 merchants / 3 months, 90/5/5 status split."""
    rng = random.Random(seed)
    merchants = []
    for i in range(1, 51):
        mid = f"M{i:02d}"
        tier = "large" if i <= 10 else "small"
        merchants.append(merchant_row(mid, f"Merchant {i:02d}", tier))
    merchant_ids = [m["id"] for m in merchants]

    txs = []
    for i in range(total):
        merchant = rng.choice(merchant_ids)
        month = rng.choice(MONTHS)
        day = rng.randint(1, MONTH_DAYS[month])
        hour = rng.randint(0, 23)
        minute = rng.randint(0, 59)
        second = rng.randint(0, 59)
        occurred_at = f"{month}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}Z"
        draw = rng.random()
        status = "settled" if draw < 0.90 else ("refunded" if draw < 0.95 else "pending")
        amount = rng.randint(100, 50000)
        fee = amount * 3 // 100
        txs.append(tx_row(f"tx-{i:07d}", merchant, amount, fee, status, occurred_at))
    return merchants, txs


def write_store(path: str, merchants, txs):
    conn = sqlite3.connect(path)
    conn.execute(SCHEMA)
    conn.executemany(
        "INSERT OR IGNORE INTO lnpl_rows (entity_id, row_key, payload) VALUES (?, ?, ?)",
        [("entity.merchant", m["id"], json.dumps(m)) for m in merchants],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO lnpl_rows (entity_id, row_key, payload) VALUES (?, ?, ?)",
        [("entity.transaction", t["id"], json.dumps(t)) for t in txs],
    )
    conn.commit()
    conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--small", action="store_true", help="C1-C3 fixture")
    ap.add_argument("--size", type=int, default=10000, help="Transaction row count for the full fixture")
    ap.add_argument("--store", default=None, help="sqlite path to write into")
    ap.add_argument("--dump", action="store_true", help="print sorted JSON lines instead of writing a store")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    merchants, txs = gen_small() if args.small else gen_full(args.size, args.seed)

    if args.dump:
        rows = sorted(merchants + txs, key=lambda r: r["id"])
        for r in rows:
            print(json.dumps(r, sort_keys=True))
        return

    if not args.store:
        print("error: --store <path> required unless --dump", file=sys.stderr)
        sys.exit(2)
    Path(args.store).parent.mkdir(parents=True, exist_ok=True)
    write_store(args.store, merchants, txs)
    print(f"wrote {len(merchants)} merchants, {len(txs)} transactions -> {args.store}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Drives ComputeDailyRollup once per merchant via `lnpl trigger` (R2/C5 @ 10k).
Same external-loop shape as run_settlement.py, same reason (no in-language
per-group loop)."""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

WORKTREE = Path(__file__).resolve().parents[5]
LNPL = str(WORKTREE / ".venv" / "bin" / "lnpl")
HERE = Path(__file__).resolve().parent


def merchants(store: str):
    import sqlite3

    conn = sqlite3.connect(store)
    ids = [
        row[0]
        for row in conn.execute(
            "select row_key from lnpl_rows where entity_id='entity.merchant' order by row_key"
        )
    ]
    conn.close()
    return ids


def trigger_one(store: str, merchant: str, day_key: str) -> tuple:
    payload = {"id": f"dailytotal-{merchant}-{day_key}", "merchant": merchant, "status": "settled", "dayKey": day_key}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, dir=str(WORKTREE / ".claude" / "tmp" / "s3")) as f:
        json.dump(payload, f)
        payload_path = f.name
    proc = subprocess.run(
        [
            LNPL, "trigger",
            str(HERE / "domain.lnpl"), str(HERE / "settlement.lnpl"),
            "--schedule", "event.daily.rollup",
            "--backend", f"sqlite:{store}",
            "--payload", payload_path,
        ],
        capture_output=True, text=True,
    )
    Path(payload_path).unlink(missing_ok=True)
    return merchant, proc.returncode, proc.stdout[-300:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--day-key", default="2026-07-15")
    args = ap.parse_args()
    results = [trigger_one(args.store, m, args.day_key) for m in merchants(args.store)]
    ok = sum(1 for _, rc, _ in results if rc == 0)
    failed = [(m, out) for m, rc, out in results if rc != 0]
    print(f"{ok}/{len(results)} completed", file=sys.stderr)
    # rc!=0 for a merchant with 0 settled tx that day is expected (no-op source
    # RowSet -> count/sum still fine, but if 0 rows overall repository create
    # with 0 gross is legal -- only avg/min/max would fail on an *empty* source,
    # which this workflow does not compute, so failures here are unexpected.
    for m, out in failed:
        print(f"FAILED {m}: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()

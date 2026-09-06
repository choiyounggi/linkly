#!/usr/bin/env python3
"""우회(의미 손실: lnpl 밖 계산 — tier 수수료 재계산(R4)과 net = gross - fees(R3)).

Money 필드는 lnpl의 `set`에서 산술도, 심지어 값 복사도 거부된다
(RFC-0044 §Reference-level Specification/1 — "Money는 가드 조건이나 평범한
`set ... to <산술>`의 피연산자로 여전히 쓸 수 없다"; 실측: evidence/02-compile.md
round 3 — `set x.net to x.gross - x.fees`와 `set x.net to input.net` 둘 다
동일한 컴파일 거부). lnpl이 낸 gross/fees(raw)/txCount로 이 스크립트가
tier-adjusted fees와 net을 계산하고, sqlite의 `lnpl_rows` payload를 직접 갱신한다
(다시 lnpl을 거치지 않는다 — 거칠 방법이 없다).
"""
import argparse
import json
import sqlite3
from decimal import ROUND_HALF_EVEN, Decimal


def apply_tier_and_net(store_path: str, settlement_id: str) -> dict:
    conn = sqlite3.connect(store_path)
    row_key = f"entity.settlement#{settlement_id}"
    cur = conn.execute(
        "select payload from lnpl_rows where entity_id='entity.settlement' and row_key=?",
        (row_key,),
    )
    row = cur.fetchone()
    if row is None:
        raise SystemExit(f"no settlement row for {settlement_id}")
    payload = json.loads(row[0])

    gross = Decimal(payload["gross"]["amount"])
    fees_raw = Decimal(payload["fees"]["amount"])
    tx_count = payload["txCount"]

    if tx_count > 1000:
        # R4: fees = 1.5% of gross, half-to-even to the cent (RFC-0044 §4's
        # avg_round policy applied here too — this whole computation is the
        # 우회, so it picks its own rounding rule and records it).
        fees = (gross * Decimal("0.015")).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    else:
        fees = fees_raw

    net = (gross - fees).quantize(Decimal("0.01"))

    payload["fees"] = {"amount": str(fees), "currency": payload["gross"]["currency"]}
    payload["net"] = {"amount": str(net), "currency": payload["gross"]["currency"]}

    conn.execute(
        "update lnpl_rows set payload=? where entity_id='entity.settlement' and row_key=?",
        (json.dumps(payload), row_key),
    )
    conn.commit()
    conn.close()
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--settlement-id", required=True)
    args = ap.parse_args()
    result = apply_tier_and_net(args.store, args.settlement_id)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

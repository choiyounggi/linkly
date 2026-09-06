"""stdlib-only open-loop load generator (D5): fires a request every 1/rps
seconds on its own thread regardless of prior completion, records per-request
result rows to a CSV, and prints p50/p95/p99 + error rate (warmup excluded).
"""
import argparse
import csv
import http.client
import threading
import time
import urllib.parse


def fire(url, method, body, t_start, rows, lock):
    parsed = urllib.parse.urlsplit(url)
    status = None
    error = ""
    t0 = time.monotonic()
    try:
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=10)
        headers = {"Content-Type": "application/json"} if body else {}
        conn.request(method, parsed.path or "/", body=body, headers=headers)
        resp = conn.getresponse()
        status = resp.status
        resp.read()
        conn.close()
    except Exception as exc:
        error = type(exc).__name__ + ":" + str(exc)
    latency_ms = (time.monotonic() - t0) * 1000
    with lock:
        rows.append((t_start, status, round(latency_ms, 3), error))


def percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--rps", type=float, default=100)
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--warmup", type=float, default=5)
    ap.add_argument("--method", default="GET")
    ap.add_argument("--body", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    body = args.body.encode() if args.body else None
    interval = 1.0 / args.rps
    rows = []
    lock = threading.Lock()
    threads = []

    t_run_start = time.monotonic()
    next_fire = t_run_start
    end_at = t_run_start + args.seconds
    while True:
        now = time.monotonic()
        if now >= end_at:
            break
        t_start = now - t_run_start
        th = threading.Thread(target=fire, args=(args.url, args.method, body, t_start, rows, lock))
        th.start()
        threads.append(th)
        next_fire += interval
        sleep_for = next_fire - time.monotonic()
        if sleep_for > 0:
            time.sleep(sleep_for)
    for th in threads:
        th.join(timeout=15)

    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_start", "status", "latency_ms", "error"])
        for r in sorted(rows, key=lambda r: r[0]):
            w.writerow(r)

    post_warmup = [r for r in rows if r[0] >= args.warmup]
    ok = [r for r in post_warmup if isinstance(r[1], int) and 200 <= r[1] < 300]
    errored = [r for r in post_warmup if r[1] is None or not (isinstance(r[1], int) and 200 <= r[1] < 300)]
    lat = sorted(r[2] for r in post_warmup)
    print(f"total={len(rows)} post_warmup={len(post_warmup)} ok={len(ok)} error_or_non2xx={len(errored)}")
    if lat:
        print(f"p50={percentile(lat, 0.50):.2f}ms p95={percentile(lat, 0.95):.2f}ms p99={percentile(lat, 0.99):.2f}ms")
    if post_warmup:
        print(f"error_rate={len(errored)/len(post_warmup)*100:.2f}%")


if __name__ == "__main__":
    main()

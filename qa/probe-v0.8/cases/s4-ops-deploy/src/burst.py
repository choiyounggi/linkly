"""stdlib-only burst client: fire N requests with C concurrent threads, tally status codes."""
import argparse
import http.client
import threading
import urllib.parse


def one_request(url, results, lock, method="GET", body=None):
    parsed = urllib.parse.urlsplit(url)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    try:
        headers = {"Content-Type": "application/json"} if body else {}
        conn.request(method, parsed.path or "/", body=body, headers=headers)
        resp = conn.getresponse()
        status = resp.status
        first_body = resp.read()[:200] if status == 429 else None
    except Exception as exc:
        status = f"error:{exc}"
        first_body = None
    finally:
        conn.close()
    with lock:
        results.append(status)
        if first_body:
            results.append(("429-body", first_body))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--requests", type=int, default=200)
    ap.add_argument("--concurrency", type=int, default=20)
    ap.add_argument("--method", default="GET")
    ap.add_argument("--body", default=None)
    args = ap.parse_args()

    body = args.body.encode() if args.body else None
    results = []
    lock = threading.Lock()
    threads = []
    for i in range(args.requests):
        t = threading.Thread(target=one_request, args=(args.url, results, lock, args.method, body))
        threads.append(t)
        t.start()
        if len(threads) >= args.concurrency:
            for t in threads:
                t.join()
            threads = []
    for t in threads:
        t.join()

    statuses = [r for r in results if not (isinstance(r, tuple) and r[0] == "429-body")]
    bodies = [r for r in results if isinstance(r, tuple) and r[0] == "429-body"]
    counts = {}
    for s in statuses:
        counts[s] = counts.get(s, 0) + 1
    print(f"total={len(statuses)}")
    for status, n in sorted(counts.items(), key=lambda kv: str(kv[0])):
        print(f"  {status}: {n}")
    if bodies:
        print("sample 429 body:", bodies[0][1])


if __name__ == "__main__":
    main()

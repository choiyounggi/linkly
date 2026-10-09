# PostgreSQL Backend — Sustained Load Ceiling (issue #180)

How much sustained load a postgres-backed `lnpl serve` holds, measured on one
machine on 2026-10-01, and what was learned about the cause of the collapse
reported in issue #180. Every number below comes from a run made for this
document. Numbers from the earlier audit are labelled "prior audit".

## Machine and versions

| Item | Value |
|------|-------|
| Host | Apple M4 Pro, 12 cores, 24 GB, macOS (Darwin 25.1.0, arm64) |
| Docker | 27.4.0 |
| PostgreSQL | 16.15 (`postgres:16` container, host port 15480) |
| Python | 3.13.1 |
| `lnpl` | 0.8.0, commit `34ba5b835928a4528e6a50db971b48948047b711` |
| `lnpl-postgres` | 0.1.0, commit `14b113e` |
| psycopg | 3.3.6 (binary) |

The load generator, `lnpl serve` and the postgres container all ran on this
one host. The generator talks to the server over loopback.

## Reproduction commands

Postgres, and the driver installed next to the working tree's `lnpl`:

```
docker run -d --name i180-pg -e POSTGRES_USER=i180 -e POSTGRES_PASSWORD=i180pw \
  -e POSTGRES_DB=i180db -p 15480:5432 postgres:16
.venv/bin/pip install --no-deps <lnpl-postgres checkout>
.venv/bin/pip install 'psycopg[binary]'
```

Workload. The service is the `linkhub.lnpl` used by the prior audit
(`qa/probe-v0.8/cases/s4-ops-deploy/src/linkhub.lnpl` on branch
`probe/v0.8-enterprise`), started without `--config`. Every request is
`POST /link-hub-service/get-bookmark` with this body, which names one row
that is saved once per server before the load starts:

```
{"id":"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee","url":"https://example.com/postgres-load-probe","title":"postgres load probe fixture","owner":"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee","savedAt":"2026-01-01T00:00:00Z","visits":0}
```

Control (fake backend):

```
lnpl serve --host 127.0.0.1 --port 18180 --cache fake linkhub.lnpl
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  http://127.0.0.1:18180/link-hub-service/save-bookmark -d '<body>'        # 200
python scripts/load_probe.py --url http://127.0.0.1:18180/link-hub-service/get-bookmark \
  --rps 100 --seconds 60 --warmup 5 --method POST --body '<body>' --out load_control.csv
```

Reproduction (postgres backend):

```
lnpl serve --host 127.0.0.1 --port 18181 --cache fake \
  --backend "postgres:postgresql://i180:i180pw@localhost:15480/i180db" linkhub.lnpl
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  http://127.0.0.1:18181/link-hub-service/save-bookmark -d '<body>'        # 200
python scripts/load_probe.py --url http://127.0.0.1:18181/link-hub-service/get-bookmark \
  --rps 100 --seconds 60 --warmup 5 --method POST --body '<body>' --out load_repro.csv
```

Proof that the route reaches postgres, taken after the seed and before the
load:

```
$ psql -t -c "SELECT count(*) FROM lnpl_rows WHERE entity_id='entity.bookmark';"
1
$ psql -t -c "SELECT seq_scan+idx_scan FROM pg_stat_user_tables WHERE relname='lnpl_rows';"
4
$ # five get-bookmark calls, all 200
$ psql -t -c "SELECT seq_scan+idx_scan FROM pg_stat_user_tables WHERE relname='lnpl_rows';"
14
```

One row exists, and five requests moved the scan counter by 10.

Ceiling sweep: the reproduction command with `--seconds 90` and `--rps` set to
25, 50, 75, 100 and 150, one fresh `lnpl serve` per rate (ports 18182-18186),
the same database, and the seed call repeated for each server.

`scripts/load_probe.py` is open-loop: it sends a request every 1/rps seconds
on its own thread whether or not earlier requests have returned. The first
5 seconds are left out. A bucket's mean and max use 2xx responses only.

A run is **STABLE** when its error rate is 0 and every 10-second bucket mean
is at most 2 times the 0-10 s bucket mean. Otherwise it is **UNSTABLE**.

## Control result (fake backend)

100 rps for 60 s: 5500 requests after warm-up, 5500 answered 200, error rate
0.00 %. p50 1.37 ms, p95 1.91 ms, p99 2.81 ms.

| Bucket | Mean | Max | Samples |
|--------|------|-----|---------|
| 0-10 s | 1.68 ms | 61.34 ms | 1000 |
| 10-20 s | 1.39 ms | 6.20 ms | 1000 |
| 20-30 s | 1.38 ms | 3.81 ms | 1000 |
| 30-40 s | 1.40 ms | 7.36 ms | 1000 |
| 40-50 s | 1.35 ms | 9.85 ms | 1000 |
| 50-60 s | 1.31 ms | 5.96 ms | 500 |

Verdict: STABLE. The largest bucket mean is 1.00 times the first. The harness
and the machine hold 100 rps flat.

## Reproduction result (postgres backend)

100 rps for 60 s: 5500 requests after warm-up, 5500 answered 200, error rate
0.00 %. p50 11.42 ms, p95 13.89 ms, p99 21.09 ms.

| Bucket | Mean | Max | Samples |
|--------|------|-----|---------|
| 0-10 s | 11.25 ms | 26.61 ms | 1000 |
| 10-20 s | 11.33 ms | 28.42 ms | 1000 |
| 20-30 s | 14.37 ms | 170.16 ms | 1000 |
| 30-40 s | 11.23 ms | 16.59 ms | 1000 |
| 40-50 s | 11.63 ms | 63.85 ms | 1000 |
| 50-60 s | 11.39 ms | 30.73 ms | 500 |

Verdict: not reproduced. No bucket mean is more than 2 times the first; the
largest is 1.28 times. The run is STABLE.

For comparison, the prior audit saw the same 100 rps load hold about 10 ms for
40 s and then climb to a 95.9 ms mean (40-50 s) and a 1161.9 ms mean
(50-60 s), with p99 5866.91 ms. That run was on a different setup: postgres
came from a compose stack on another port and the service was started from
the audit's own directory.

Each postgres request costs about 10 ms more than a fake-backend request
(11.25 ms against 1.68 ms in the first bucket).

## Ceiling sweep

90 s per rate, warm-up 5 s, postgres backend.

| Rate (rps) | Verdict | 0-10 s mean | Last-bucket mean | Worst bucket mean | Error rate | p99 |
|------------|---------|-------------|------------------|-------------------|------------|-----|
| 25 | STABLE | 18.99 ms | 18.90 ms | 19.23 ms (1.01x) | 0.00 % | 31.39 ms |
| 50 | STABLE | 16.60 ms | 16.02 ms | 16.93 ms (1.02x) | 0.00 % | 30.41 ms |
| 75 | STABLE | 13.38 ms | 8.12 ms | 15.19 ms (1.14x) | 0.00 % | 23.19 ms |
| 100 | STABLE | 9.19 ms | 7.70 ms | 15.44 ms (1.68x) | 0.00 % | 52.23 ms |
| 150 | UNSTABLE | 7.04 ms | 6.87 ms | 386.14 ms (54.87x) | 0.16 % | 2028.38 ms |

Ceiling: 100 rps. It is the highest rate tested that stayed STABLE; no rate
between 100 and 150 was tested.

The 150 rps run, bucket by bucket:

| Bucket | Mean | Max | 2xx samples |
|--------|------|-----|-------------|
| 0-10 s | 7.04 ms | 15.01 ms | 1500 |
| 10-20 s | 7.73 ms | 33.20 ms | 1500 |
| 20-30 s | 386.14 ms | 5868.58 ms | 1497 |
| 30-40 s | 55.06 ms | 1130.26 ms | 1483 |
| 40-50 s | 6.66 ms | 15.17 ms | 1500 |
| 50-60 s | 6.68 ms | 13.65 ms | 1500 |
| 60-70 s | 10.59 ms | 181.28 ms | 1500 |
| 70-80 s | 7.08 ms | 18.91 ms | 1500 |
| 80-90 s | 6.87 ms | 13.01 ms | 750 |

At 150 rps the server ran flat for about 25 s, stalled for about 15 s, and
then recovered by itself. During the stall 20 requests (sent at 35-36 s into
the run) came back 500. The server log gives the reason for each of them:

```
psycopg.OperationalError: connection failed: connection to server at "127.0.0.1",
  port 15480 failed: FATAL:  sorry, too many clients already
```

So during the stall more requests were in flight than postgres has
connection slots (`max_connections` is 100 in the stock image), and every
one of them was opening its own connection.

Mean latency falls as the rate rises (18.99 ms at 25 rps, 7.04 ms at
150 rps). This sweep does not explain that; the same pattern is not in the
fake-backend control, which was run at one rate only.

## Refinement in a Linux container (issue #195)

Issue #195 asked for the gap between 100 and 150 rps to be measured at 10 rps
resolution. The sections above were measured on the macOS host and are left as
they were. This refinement ran on 2026-10-08 inside a Docker Linux container
(Docker Desktop VM on an Apple M4 Pro, 8 CPUs, 4 GB; Debian 12, kernel
6.10.14-linuxkit), because the macOS host loopback path stalls after about 8000
to 10000 short connections for any client and server
(`benchmarks/load/i195/diagnosis/README.md`). Versions: PostgreSQL 16.15,
lnpl-postgres 0.1.0 at 14b113e and psycopg 3.3.6 (as above), Python 3.13.16,
lnpl commit 5e81fd01b04ef4278b68f2b753648f5b147e799c. Full machine table and
reproduction commands: `docs/gunicorn-load-measurement.md`.

Method is #180's: a fresh `lnpl serve --cache fake --backend postgres:<dsn>` per
rate (postgres in a second container on the same Docker network), 90 s per rate,
5 s warm-up, the same workload, one run per rate. The STABLE rule is printed by
`scripts/load_probe.py` as its `verdict=` line. Control: `lnpl serve --cache fake`
(fake backend) at 140 rps for 90 s was `verdict=STABLE worst_bucket_ratio=1.111x`
(`serve-fake-control.log`); the session controls were STABLE as well
(`session.log`).

| Rate (rps) | Verdict | 0-10 s mean | Last-bucket mean | Worst bucket mean | Error rate | p99 | Log |
|------------|---------|-------------|------------------|-------------------|------------|-----|-----|
| 100 | STABLE | 5.66 ms | 4.63 ms | 6.03 ms (1.065x) | 0.00 % | 7.53 ms | `serve-postgres-100.log` |
| 110 | UNSTABLE | 4.50 ms | 5.73 ms | 143.01 ms (31.767x) | 0.00 % | 204.09 ms | `serve-postgres-110.log` |
| 120 | UNSTABLE | 5.47 ms | 4.52 ms | 52.66 ms (9.621x) | 0.00 % | 113.95 ms | `serve-postgres-120.log` |
| 130 | STABLE | 4.78 ms | 4.15 ms | 4.78 ms (1.000x) | 0.00 % | 5.98 ms | `serve-postgres-130.log` |
| 140 | STABLE | 4.38 ms | 4.16 ms | 4.50 ms (1.026x) | 0.00 % | 6.29 ms | `serve-postgres-140.log` |
| 150 | STABLE | 4.58 ms | 4.31 ms | 5.11 ms (1.117x) | 0.00 % | 8.54 ms | `serve-postgres-150.log` |

Ceiling in the container: 100 rps. It is the highest rate that stayed STABLE with
every lower rate also STABLE, at 10 rps resolution. The 110 and 120 rps runs each
had one short stall (a single 10 s bucket, longest request 5155.77 ms and
2060.78 ms) and then recovered with no errors; 130, 140 and 150 rps were STABLE
in their single runs. One run per rate does not show whether the stalls at 110
and 120 would repeat, so the table does not support a ceiling above 100.

These numbers are not directly comparable with the host numbers above: the
container has a different kernel and network stack, and 150 rps, which stalled
in all three #180 host runs, was STABLE here. #180's host numbers may also have
been affected by the host loopback stall described in
`benchmarks/load/i195/diagnosis/README.md`; they are not rewritten. The
recommendation below stays at `--rate-limit 100`: it is the highest rate STABLE
with every lower rate STABLE in both environments, and each refinement rate ran
once.

## Hypothesis table

The 100 rps run did not collapse, so every experiment below uses the lowest
rate that did: 150 rps for 90 s, warm-up 5 s, same workload.

| Hypothesis | Command | Result | Verdict |
|------------|---------|--------|---------|
| H3 | The control run above (fake backend, 100 rps x 60 s, same generator, same host). | STABLE, largest bucket mean 1.00x the first, 0 errors. The generator and the host do not produce the stall by themselves. | REFUTED |
| H2 | `grep -n "= factory()" impl/lnpl/wsgi.py` and `grep -n "psycopg.connect" lnpl_postgres/driver.py`, then one unpatched 150 rps run with `pg_stat_activity` sampled every 5 s. | 5 `factory()` call sites, 1 `psycopg.connect` inside `__init__`: every request builds its own driver and its own connection, so there is no single connection to contend on. Sampled backends: 1-2 in 17 samples, 82 in the sample taken during the stall — 82 separate connections. | REFUTED |
| H2' | The same run and samples as H2, plus the server log of the 150 rps sweep run. | In-flight requests each hold their own connection and their number is unbounded: 82 backends at the stall, and in two other unpatched runs 20 and 23 requests were refused with `too many clients already` at `max_connections` 100. | CONFIRMED |
| H1 | Temporary patch (reverted, never committed) to the one `factory = ...` line in `impl/lnpl/cli.py`: 24 driver instances opened once at start, each lent to one request at a time. 3 patched runs and 3 unpatched runs at 150 rps x 90 s; smoke check 10 rps x 15 s on the first patched server before its run (100 of 100 OK). | Unpatched: all 3 runs stalled (worst bucket mean 386-422 ms). Patched: 0 errors in all 3 runs, worst bucket mean 4.08-4.73 ms, under the 14.60 ms band. The stall disappears when requests stop building a driver each. | CONFIRMED |
| H1a | `h1_split_probe.py`: 90 threads at once each open a connection and then run the driver's two `CREATE TABLE IF NOT EXISTS` statements; time each phase. | Connection setup took 93.6 % of the combined time (207.718 ms against 14.140 ms). Two more runs: 75.5 % and 83.3 %. | CONFIRMED |
| H1b | Same script, the DDL phase. | The two DDL statements took 6.4 % of the combined time (24.5 % and 16.7 % in the two other runs). Below the 50 % share in every run. | REFUTED |

The six runs behind H1:

| Run | Driver per request | Errors | p99 | 0-10 s mean | Worst bucket mean | Worst / first |
|-----|--------------------|--------|-----|-------------|-------------------|---------------|
| Unpatched 1 (the sweep run) | yes | 20 | 2028.38 ms | 7.04 ms | 386.14 ms | 54.87x |
| Unpatched 2 (the H2 sampling run) | yes | 0 | 2026.83 ms | 7.30 ms | 422.18 ms | 57.87x |
| Unpatched 3 | yes | 23 | 2020.37 ms | 8.48 ms | 412.89 ms | 48.71x |
| Patched 1 | no, pool of 24 | 0 | 10.05 ms | 2.31 ms | 4.73 ms | 2.05x |
| Patched 2 | no, pool of 24 | 0 | 9.45 ms | 2.67 ms | 4.32 ms | 1.62x |
| Patched 3 | no, pool of 24 | 0 | 8.93 ms | 2.98 ms | 4.08 ms | 1.37x |

How H1 was judged. The planned rule was to call a patched run healthy when
its worst bucket mean stayed within 2 times its own first bucket. That ratio
rule was replaced by a band rule, because the patch lowered the baseline
latency itself (7 ms to 2-3 ms), which makes a ratio against the run's own
first bucket misleading: a 2.4 ms wobble reads as "2.05x". The band rule:
H1 is confirmed when every patched run has 0 errors and no bucket mean above
2 times the median 0-10 s mean of the unpatched runs. That median is 7.30 ms,
so the band is 14.60 ms. The literal ratio is in the last column.

How H2 and H2' were judged. The planned thresholds were "H2 confirmed if any
sample shows 10 or more postgres backends" and "H2' confirmed if the OS-level
connection count is at least 3 times the backend count". Both were
mis-specified. A backend count measures separate connections, so a high count
speaks against one shared connection, not for it. And
`lsof -iTCP:15480 -sTCP:ESTABLISHED` counts each connection about twice on
this host (the patched server held 25 backends and showed 48 lines in every
sample), so the 3-times ratio could never be met. The two verdicts rest on
the evidence in the table instead: 82 backends at the stall, and the
`too many clients already` errors at `max_connections` 100.

Samples from the unpatched H2 run, one every 5 s (postgres backends / `lsof`
lines): 17 samples between 1 / 0 and 2 / 3, and one sample of 82 / 90 at the
stall. The stall in that run was in the 70-80 s bucket (mean 422.18 ms, max
3967.09 ms).

`h1_split_probe.py`, first run, verbatim:

```
connect-sequential  mean=4.327ms p95=5.916ms
ddl-sequential      mean=0.599ms p95=1.017ms
connect-concurrent(M=90) mean=207.718ms max=388.488ms
ddl-concurrent(M=90)     mean=14.140ms max=62.029ms
connect share=93.6% ddl share=6.4%
```

One connection alone takes about 4 ms. Ninety opened at the same moment take
150-208 ms each.

## Root cause

Side: lnpl-postgres

Location: lnpl_postgres/driver.py:109 (`psycopg.connect(dsn)` inside `PostgresRepositoryDriver.__init__`). `lnpl serve` builds a new driver for every request (`impl/lnpl/cli.py:855` hands `lambda: open_repository(backend)` to the server, and `impl/lnpl/wsgi.py:1555,1611,1763,1798,2015` call it once per request and close the result in `finally`). The two `CREATE TABLE IF NOT EXISTS` calls at driver.py:111-112 run on every construction too, but they are the smaller cost: `connect share=93.6% ddl share=6.4%` at 90 concurrent constructions (75.5 % and 83.3 % in two more runs).

Mechanism: `lnpl serve` starts one thread per request with no upper bound (`impl/lnpl/serve.py`, `ThreadingMixIn`), and by design each request opens its own backend connection (`docs/serving.md:334`; `docs/backends.md` leaves pooling to the driver and names `psycopg_pool.ConnectionPool`). With this driver that means one new postgres connection per request, about 4 ms when it is the only one. The cost is not constant: 90 connections opened at the same moment took 150-208 ms each. So when requests overlap for any reason, each new one makes connection setup slower for all of them, more requests arrive before the earlier ones finish, and the number of open connections runs away. At 150 rps this showed as a stall after tens of seconds of flat latency: 82 postgres backends at once in the sampled run, bucket means of 386-422 ms, single requests up to 5.9 s, and in two of three runs requests refused with `too many clients already` at `max_connections` 100. The stall then cleared by itself. With 24 drivers opened once and lent to one request at a time (the H1 patch) the same load ran three times with no stall and no error, worst bucket mean 4.08-4.73 ms. What first makes requests overlap was not identified, and postgres CPU was not measured in these runs.

Proposed fix: `PostgresRepositoryDriver` should stop opening a connection per construction. It should hold a `psycopg_pool.ConnectionPool` opened once (`min_size`/`max_size` near cores x 2 of the database host, tuned by measurement) and borrow a connection through `pool.connection()` for each request's `begin()` .. `commit()`/`rollback()` span, giving it back in `close()`. This needs no change to the per-request `repository_factory()` call shape in `impl/lnpl/wsgi.py`, as long as the pool outlives the request. The implementation in `lnpl-postgres` has to choose between a module-level pool keyed by DSN inside the driver, which needs no linkly change, and one driver-held pool cached where `lnpl serve` builds its factory (`impl/lnpl/cli.py:855`), which needs a linkly change as well. The pool must block or fail fast when it is empty, so the number of connections stays bounded however many request threads exist. The two DDL statements were the minor cost here (H1b refuted), so moving them out of `__init__` is optional; with a pool they would at least run once per pooled connection instead of once per request.

## Deployment guidance

Set `--rate-limit 100` for a postgres-backed `lnpl serve` until the
`lnpl-postgres` driver ships connection pooling (proposed above; not
scheduled). `--rate-limit` answers `429` with `Retry-After` when the rate is
exceeded, so overload fails fast instead of queueing (issue #148).

This number is per `lnpl serve` process. With K instances or gunicorn
workers each running `--rate-limit 100`, the combined admitted rate is
up to 100 x K, not 100 (`docs/serving.md` "Rate limit" -- the bucket is
process-local). Put the combined cap at the gateway instead
(`examples/deploy/nginx.conf`'s `limit_req_zone`/`limit_req`, issue
#194; directive docs:
https://nginx.org/en/docs/http/ngx_http_limit_req_module.html).

100 rps is the measured ceiling on the machine above: it was STABLE in both
runs made at that rate (60 s and 90 s), and 150 rps stalled in all three
unpatched runs. The issue #195 refinement
("Refinement in a Linux container" above) then measured 100 to 150 rps at
10 rps steps, once each, in a container: ceiling 100 rps, 110 and 120 rps
UNSTABLE, 130 to 150 rps STABLE. One repetition per rate, so read 100 as the
figure to plan with, not the 130 to 150 results as headroom.

This differs from the prior audit, which saw 100 rps collapse after about
40 s on its own setup. The ceiling depends on how fast the host opens
postgres connections, so treat 100 as this machine's number: repeat the sweep
on the deployment host (`scripts/load_probe.py`, commands above) and set the
limit to the highest rate that stays STABLE there. A lower value such as the
audit's `--rate-limit 50` is the safe choice until that is done.

Low CPU on the postgres side does not mean the service is healthy under this
load. Requests queue while CPU is idle, because each request thread is blocked
in connection setup, which is waiting and not computing. The prior audit
measured 6 % CPU on the postgres container during its collapse.

# gunicorn Path — Sustained Load Table (issue #195)

This document measures the production path `gunicorn "lnpl.wsgi:build_app()"`
for three backends (fake, sqlite, postgres), three worker counts (1, 2, 4) and
two worker classes (sync, gthread): 18 cells. It was measured on one machine,
inside a Docker Linux container, on 2026-10-08. The raw logs are in
`benchmarks/load/i195/linux/`; every number in the tables below is copied from
a line of those logs.

## Why not on the macOS host

The first plan ran the same session directly on the macOS host. It could not
be completed: the fake-backend control collapsed in three sessions in a row
(`benchmarks/load/i195/invalid-1/`, `invalid-2/`, `invalid-3/`), at host 1-minute
load averages of 3.15, 2.04 and 1.90 (`session.log` of each), with no errors before the stall and
then multi-second requests and error rates of 31.14% and 32.70% (`invalid-1/` and
`invalid-2/` `session.log`). `benchmarks/load/i195/diagnosis/README.md` shows
the stall in most runs starting after about 8000 to 10000 short connections (one
400 rps run stalled from the first bucket, and an ApacheBench run stopped after
75 requests), and that ApacheBench (a different client), `lnpl serve` and gunicorn all hit it.
The host loopback path is therefore not usable for a sustained connection-per-
request measurement, and no number from those directories is used below. The
measurement was moved into a Linux container (Docker Desktop VM), where the
same pre-check passed (`benchmarks/load/i195/linux/precheck/precheck-400.log`:
two 55 s runs at 400 rps, both `verdict=STABLE`, longest request 21.50 ms and
34.10 ms).

## Machine and versions

| Item | Value |
|------|-------|
| Environment | Docker Engine 27.4.0 in the Docker Desktop Linux VM on an Apple M4 Pro host, 8 CPUs, 4 GB RAM (`host docker:` line; `session.log` prints it as "Docker Desktop 27.4.0", but 27.4.0 is the engine version) |
| Kernel / OS | 6.10.14-linuxkit, Debian GNU/Linux 12 (bookworm), `nproc 8`, `MemTotal: 4013416 kB` |
| Network sysctls | `net.core.somaxconn = 4096`, `net.ipv4.ip_local_port_range = 32768	60999`, `net.ipv4.tcp_fin_timeout = 60` |
| PostgreSQL | PostgreSQL 16.15 (Debian 16.15-1.pgdg13+2), container `t195-pg`, no host port |
| Python | Python 3.13.16 |
| gunicorn | gunicorn (version 26.2.0) |
| psycopg | 3.3.6 |
| lnpl-postgres | 0.1.0 at commit 14b113e |
| lnpl | commit 5e81fd01b04ef4278b68f2b753648f5b147e799c |
| Host load at start / end | `10:45  up 14 days, 14:52, 14 users, load averages: 5.09 4.58 3.85` / `12:03  up 14 days, 16:09, 14 users, load averages: 5.12 4.57 4.28` |

The container ran on a developer laptop that was also in use; the host load
averages above are the macOS side. The container's own load average at the first
control was 1.34 (`uptime` line in `session.log`).

## Reproduction

Images used: `python:3.13-slim-bookworm` and `postgres:16`; the load container is
built from the first with curl and procps added (`t195-load`). From the
repository root of a worktree:

```
bash benchmarks/load/i195/run_linux.sh up
bash benchmarks/load/i195/run_linux.sh precheck 400
bash benchmarks/load/i195/run_linux.sh session "50 100 200 400" 400 "100 110 120 130 140 150"
bash benchmarks/load/i195/run_linux.sh down
```

`up` creates the network `t195-net`, the postgres container
(`docker run -d --name t195-pg --network t195-net -e POSTGRES_USER=t195 -e POSTGRES_PASSWORD=t195pw -e POSTGRES_DB=t195db postgres:16`)
and `t195-load` with the worktree mounted read-only at `/src`, the
lnpl-postgres checkout read-only at `/lnpl-postgres` (host path from `T195_PGSRC`, default the author's `/Users/choeyeong-gi/Desktop/workspace/lnpl-postgres`; set it to your own checkout), and
`benchmarks/load/i195/linux` as the only writable mount (`/out`). Inside, it runs
`pip install /work gunicorn==26.2.0 'psycopg[binary]==3.3.6'` and
`pip install --no-deps /work-pg` (a copy of lnpl-postgres at 14b113e) into a
venv. Client and servers run in `t195-load` on 127.0.0.1; the postgres DSN host
is `t195-pg:5432`. `session` runs `benchmarks/load/i195/run_matrix.sh`; `down`
removes the two containers, the network, their volumes and the `t195-load` image.

Per cell the runner starts, with the cell's values:

```
LNPL_SOURCE=examples/linkhub.lnpl LNPL_BACKEND=<fake | sqlite:<db> | postgres:<dsn>> \
  gunicorn "lnpl.wsgi:build_app()" --bind 127.0.0.1:18195 --workers <1|2|4> \
  --worker-class <sync|gthread> --threads <1|4> --no-control-socket
```

## Method

- Workload: `examples/linkhub.lnpl`, every request `POST /link-hub-service/get-bookmark`
  with the body of issue #180 (`scripts/load_probe.py` is the generator). One row is
  saved once per server (the seed answers 200 or 409), then a get must answer 200.
- Ladder, the same for all 18 cells: 50, 100, 200, 400 rps, ascending; a cell stops at
  its first point that is not STABLE. Each point runs 55 s with the first 5 s left out
  (five 10 s buckets), 1 repetition, 2 s between points, a fresh gunicorn per cell.
  The sync class uses the default 1 thread; gthread uses `--threads 4` (the example of
  the gunicorn design page, https://gunicorn.org/design/). Every other setting is the
  default (`--timeout 30`, `--backlog 2048`); `--no-control-socket` keeps gunicorn from
  creating a socket outside the container.
- STABLE: the error rate is 0 and every bucket mean is at most 2 times the first
  bucket's mean. `scripts/load_probe.py` prints the result as its last line
  (`verdict=STABLE worst_bucket_ratio=1.155x`).
- Cell ceiling: the highest rate whose block reads `verdict=STABLE`, taken from the
  start of the ladder up to the first non-STABLE block. `400 (ladder top)` means all
  four points were STABLE. p50/p95/p99 and the worst ratio are copied from the ceiling
  point's block.
- Ladder top: 400 rps, because the generator keeps one thread per in-flight request with
  a 10 s timeout. The pre-check in the container passed at 400 rps (above).
- Postgres tables were created once before the first postgres cell (concurrent first
  opens race; see Follow-ups found).
- Time box: the plan's budget was about 90 minutes. To fit it, each point runs 55 s
  instead of #180's 90 s and once; no axis was dropped. The session ran from
  `session start 2026-10-08T01:45:45Z` to `session end 2026-10-08T03:03:06Z`, 77 minutes.

## Controls

A session whose control is not STABLE is INVALID and no number is taken from it. The
control is the fake backend with gunicorn gthread, 4 workers x 4 threads, at 400 rps.

| Control | Verdict | Worst ratio | p99 | Error rate | Log |
|---------|---------|-------------|-----|------------|-----|
| control start | STABLE | 1.155x | 3.30ms | 0.00% | `session.log` (`control start`) |
| control end | STABLE | 1.037x | 2.35ms | 0.00% | `session.log` (`control end`) |
| refinement control (`lnpl serve --cache fake`, 140 rps, 90 s) | STABLE | 1.111x | 4.03ms | 0.00% | `serve-fake-control.log` |

Three earlier sessions on the macOS host were INVALID and are kept unused in
`benchmarks/load/i195/invalid-1/`, `invalid-2/` and `invalid-3/`.

## Results

Ceiling is the highest STABLE rate (rps). "Next point" is the first rate that was not
STABLE, with its worst ratio.

| Backend | Workers | Class | Ceiling (rps) | p50 | p95 | p99 | Worst ratio | Log | Next point |
|---------|---------|-------|---------------|-----|-----|-----|-------------|-----|------------|
| fake | 1 | sync | 400 (ladder top) | 0.91ms | 1.91ms | 3.72ms | 1.014x | `gunicorn-fake-w1-sync.log` | – |
| fake | 1 | gthread | 400 (ladder top) | 0.89ms | 1.83ms | 4.26ms | 1.374x | `gunicorn-fake-w1-gthread.log` | – |
| fake | 2 | sync | 400 (ladder top) | 0.94ms | 1.86ms | 2.77ms | 1.043x | `gunicorn-fake-w2-sync.log` | – |
| fake | 2 | gthread | 400 (ladder top) | 0.88ms | 1.73ms | 2.56ms | 1.023x | `gunicorn-fake-w2-gthread.log` | – |
| fake | 4 | sync | 400 (ladder top) | 0.93ms | 1.88ms | 3.07ms | 1.086x | `gunicorn-fake-w4-sync.log` | – |
| fake | 4 | gthread | 400 (ladder top) | 0.90ms | 1.67ms | 2.39ms | 1.089x | `gunicorn-fake-w4-gthread.log` | – |
| sqlite | 1 | sync | 400 (ladder top) | 1.10ms | 1.87ms | 2.75ms | 1.000x | `gunicorn-sqlite-w1-sync.log` | – |
| sqlite | 1 | gthread | 400 (ladder top) | 1.04ms | 2.39ms | 43.96ms | 1.000x | `gunicorn-sqlite-w1-gthread.log` | – |
| sqlite | 2 | sync | 400 (ladder top) | 1.17ms | 2.24ms | 3.33ms | 1.034x | `gunicorn-sqlite-w2-sync.log` | – |
| sqlite | 2 | gthread | 400 (ladder top) | 1.06ms | 2.01ms | 3.12ms | 1.000x | `gunicorn-sqlite-w2-gthread.log` | – |
| sqlite | 4 | sync | 400 (ladder top) | 1.09ms | 2.10ms | 3.44ms | 1.000x | `gunicorn-sqlite-w4-sync.log` | – |
| sqlite | 4 | gthread | 400 (ladder top) | 1.03ms | 1.82ms | 2.33ms | 1.000x | `gunicorn-sqlite-w4-gthread.log` | – |
| postgres | 1 | sync | 100 | 4.36ms | 5.73ms | 6.74ms | 1.005x | `gunicorn-postgres-w1-sync.log` | 200 UNSTABLE (147.217x) |
| postgres | 1 | gthread | 50 | 5.62ms | 6.83ms | 7.54ms | 1.000x | `gunicorn-postgres-w1-gthread.log` | 100 UNSTABLE (3.730x) |
| postgres | 2 | sync | 400 (ladder top) | 4.87ms | 1493.78ms | 1566.89ms | 1.000x | `gunicorn-postgres-w2-sync.log` | – |
| postgres | 2 | gthread | 400 (ladder top) | 4.63ms | 6.92ms | 10.98ms | 1.000x | `gunicorn-postgres-w2-gthread.log` | – |
| postgres | 4 | sync | 100 | 4.61ms | 12.50ms | 22.28ms | 1.000x | `gunicorn-postgres-w4-sync.log` | 200 UNSTABLE (3.382x) |
| postgres | 4 | gthread | 400 (ladder top) | 4.90ms | 27.64ms | 60.12ms | 1.000x | `gunicorn-postgres-w4-gthread.log` | – |

## Reading the table

- Every fake and sqlite cell, sync and gthread, was STABLE up to the ladder top of 400
  rps with a p99 of 43.96 ms or less (the 43.96 ms is sqlite, 1 worker, gthread).
- Postgres is the only backend with ceilings below 400: 1 worker sync stopped at 100
  (200 was UNSTABLE, 147.217x), 1 worker gthread at 50 (100 was UNSTABLE, 3.730x), and
  4 workers sync at 100 (200 was UNSTABLE, 3.382x).
- Postgres with 2 workers (sync and gthread) and with 4 workers gthread reached 400 rps,
  but the rows are not equal: the 2-worker sync row has a p95 of 1493.78 ms and a p99 of
  1566.89 ms at 400 rps, because its first bucket was already slow (buckets 1108.04,
  91.20, 11.29, 6.05 and 8.53 ms), so the rule compared later buckets with a slow first one.
- Three more STABLE cells have a first bucket above the later ones, which the ratio
  column (1.000x) does not show: postgres 4 workers gthread at 400 (buckets 17.10, 6.57,
  5.43, 5.35, 4.87 ms; max 185.97 ms), sqlite 1 worker gthread at 400 (buckets 6.60,
  1.08, 1.06, 1.08, 1.05 ms; max 124.07 ms, the source of its 43.96 ms p99), and
  postgres 4 workers sync at 100 (buckets 9.13, 4.80, 4.61, 4.59, 4.61 ms; max 45.88 ms).
  Read their p99 as a start-up spike, not as steady state.
- The ceilings do not rise steadily with workers (4 workers sync stopped at 100, 2 workers
  sync reached 400); one repetition per point cannot separate a worker-count effect from
  run-to-run noise on a shared laptop.
- Of the two classes at postgres 4 workers, gthread reached 400 and sync stopped at 100.

## Limits

- One host (a Docker Desktop VM on a laptop in use during the run), one repetition per
  point, 50 s measured windows. A late stall like #180's 70-80 s one can be missed.
- The ladder doubles, so a ceiling of R says only "R held, 2R did not or was not tested".
- The macOS host's load averages at the start and end of the session are in the
  Machine table; the container's own load average was 1.34 at the first control.
- Virtualised networking and CPU: the numbers describe this VM, not bare metal.
- `stability_verdict` compares every bucket with the first one only (see Follow-ups found),
  so slow-from-the-start points can read STABLE.

## Follow-ups found

1. `scripts/load_probe.py` `stability_verdict` compares every bucket only to the first
   bucket, so a run that is slow from the start reads STABLE (the postgres 2 workers sync
   row at 400 rps above; the 200 rps runs in `benchmarks/load/i195/diagnosis/`).
2. The macOS host loopback path stalls after about 8000 to 10000 short connections for any
   client and server (`benchmarks/load/i195/diagnosis/README.md`); the cause below that
   level is unknown.
3. lnpl-postgres: concurrent first opens on a fresh database race on
   `CREATE TABLE IF NOT EXISTS` (`duplicate key value violates unique constraint
   "pg_type_typname_nsp_index"`), so `--workers 2` or more on a fresh database can fail to
   boot.
4. linkly: `build_app()` reports that boot-time driver error as
   `LNPL_BACKEND is not a recognized selector`, which hides the cause.
5. `scripts/load_probe.py` cannot drive rates whose in-flight requests exceed the
   per-process thread limit.

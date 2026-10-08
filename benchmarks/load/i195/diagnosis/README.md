# Why 400 rps is not measurable here (issue #195, ruling 2, Step A)

Server for every run: `gunicorn "lnpl.wsgi:build_app()"`, fake backend, `--worker-class gthread --workers 4 --threads 4`,
fresh per run. Client: `scripts/load_probe.py --seconds 55 --warmup 5`. Sampler: every 2 s, epoch, TIME_WAIT count,
ESTABLISHED count, thread count of the load_probe process (`diag-<rate>.samples.log`). Host 1-minute load average at the start of these runs: 3.57 (300 rps), 4.50 (400 rps), 3.41 and 3.42 (200 rps a, b) and 6.22
(`diag-200.log`, a first 200 rps run: STABLE 1.333x, listed here for completeness) (desktop apps); the earlier sessions at 400 rps
(`../invalid-1/`, `../invalid-2/`) ran at 3.15 and 2.04 and collapsed the same way. This directory is a diagnosis, not a result: no number here goes into the results table.

| run | file | verdict | buckets (0-10 s ... 40-50 s mean) |
|-----|------|---------|-----------------------------------|
| 300 rps | `diag-300.log` | UNSTABLE 2029.271x | 1.34, 1.09, 1.39, 2032.70, 2717.09 ms |
| 400 rps | `diag-400.log` | UNSTABLE 1.595x | 1881.21, 501.96, 1647.22, 2107.54, 3000.48 ms |
| 200 rps | `diag-200-a.log` | STABLE 1.249x | 556.29, 660.97, 236.84, 306.53, 694.76 ms |
| 200 rps | `diag-200-b.log` | STABLE 1.221x | 1022.58, 406.52, 584.08, 1064.25, 1248.44 ms |

## Cause

The onset is not at a fixed time: 300 rps was flat for 20-30 s and stalled in the 30-40 s bucket (about 8000-9000
requests sent), the two 400 rps sessions were flat for 20 s and stalled at about 8000 requests (`../invalid-1/session.log`,
`../invalid-2/session.log`), and this directory's 400 rps run stalled from the first bucket. That fits a count-based
resource better than a clock: every request opens its own TCP connection (the generator sends no keep-alive), TIME_WAIT sat
between 0 and 1556 sockets (300 rps) and 0 and 2176 (400 rps) and ESTABLISHED between 59 and 106 in the samples, and once the
stall began the generator's in-flight threads rose from 2-3 to at most 2335 (300 rps) and 3051 (400 rps)
(`diag-300.samples.log`, `diag-400.samples.log`); requests of 3.9-7.8 s look like connect retries. The samples do not name
the exhausted resource (the host's ephemeral range is 32768-65535, `host-tcp-counters.log`; TIME_WAIT never came close to
its 32768 ports), so the
claim is only this: after about 8000-10000 connections the harness-plus-host path stops accepting connections at a steady rate, and
the point is not measurable with this harness.

Also visible in the 200 rps runs: they are STABLE by the rule, but their maxima are 3.9-5.9 s with bucket means of
0.2-1.2 s on a fake backend, which is the same connect-retry effect at a lower level. Treat 200 rps cells as "held
under the STABLE rule", not as "fast".

## Client or server (ruling 3, 200 rps, fake backend)

Question: is the stall made by the client (`load_probe`: one thread and one new TCP connection per request) or by the
server/host side? Three runs, same half hour, host load average 3.1-4.1.

| run | client | server | result |
|-----|--------|--------|--------|
| `ab-1.log` | ApacheBench, `-n 11000 -c 8`, no `-k` | gunicorn fake, gthread 4x4 | 9879 requests completed, then `apr_socket_recv: Operation timed out (60)`; `ab` aborted without printing its percentile table, so there is no longest-request figure |
| `ab-2.log` | the same, started 5 s after `ab-1` | fresh gunicorn | `apr_socket_recv: Operation timed out (60)` after 75 requests |
| `serve-200.log` | `load_probe` 200 rps, 55 s | `lnpl serve --backend fake --cache fake` (the #180 server) | `p99=2014.80ms`, longest request in the 40-50 s bucket `max=3937.93ms`, buckets 1.39 / 1.26 / 1.22 / 1.06 / 245.57 ms, `verdict=UNSTABLE worst_bucket_ratio=177.091x` |
| `gunicorn-ref-200.log` | `load_probe` 200 rps, 55 s | gunicorn fake, gthread 4x4 | `p99=3937.11ms`, `max=4006.71ms`, buckets 64.68 / 468.14 / 518.40 / 9.35 / 524.49 ms, `verdict=UNSTABLE worst_bucket_ratio=8.109x` |

Reading, by the ruling's rule: `ab` did not stay under 1 s and did not run far above 200 rps; a different C client with
a closed loop (8 connections at a time, so no thread pile-up) hit the same wall after about 9900 connections and, a few
seconds later, after 75. Both servers (`lnpl serve`, one thread per request, and gunicorn) show requests of about 2 s and
4 s (p99 2014.80 ms and 3937.11 ms) on a fake backend. So the stall is not made by `load_probe`'s threads: it follows the
number of connections opened against a loopback listener on this host, whichever client and server are used.

Not the listen queue: `netstat -s -p tcp`, read after all these runs (totals since boot, `host-tcp-counters.log`), reports `0 listen queue overflow` and
`0 embryonic connection dropped`. The 2 s and 4 s steps fit connect retries, but this was not traced further (no packet
capture, time box). Open sysctls: `net.inet.tcp.msl` 1000, `net.inet.ip.portrange.first` 32768, `last` 65535,
`kern.ipc.somaxconn` 128.

Verdict: SERVER/HOST side (the host's loopback connection path), not a `load_probe` artifact; cause below that level
is UNCLEAR.

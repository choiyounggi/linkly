# evidence/06 — `lnpl serve` (real HTTP)

**Revision (round 2, per reviewer F2):** round 1 curled A1–A3 against a
version of the source that still carried the F-12-avoidance workaround
(`find` before `respond`) and got false 409s (F-13) — evidence, but not
the question F2 asked. On rework, restarting `lnpl serve` against the
**corrected** source (no workaround, matches what mode A actually
verifies) produced a new, more fundamental result:

## `lnpl serve` cannot start at all against the corrected source

```
$ LNPL_JWT_SECRET=... lnpl serve src/ --port 8793 --backend sqlite:.claude/tmp/serve2.db \
    --jwt-secret-env LNPL_JWT_SECRET
Traceback (most recent call last):
  File "impl/lnpl/cli.py", line 857, in cmd_serve
  File "impl/lnpl/serve.py", line 140, in serve
  File "impl/lnpl/wsgi.py", line 553, in build_routes
    contract = set(generate(document)["paths"])
  File "impl/lnpl/openapi.py", line 277, in generate
  File "impl/lnpl/openapi.py", line 510, in _operation
    response_schema = _response_schema(steps, nodes, entities, refined)
  File "impl/lnpl/openapi.py", line 475, in _response_schema
    entity = by_binding[binding]
KeyError: 'newOrder'
$ echo $?
1
```

**This upgrades F-12's severity.** `wsgi.py::build_routes` calls the exact
same `openapi.generate()` that crashes for `lnpl openapi` (evidence/05) —
`lnpl serve` is not a separate code path that merely shares the bug, it is
a **caller** of the same crashing function, at startup, unconditionally.
The round-1 server that *did* start only worked because the source still
carried the create-as-then-find workaround (F-13) at that point; a source
that is runtime-correct (no F-13) is a source `lnpl serve` refuses to
boot at all. **R8's "실 서버로 A1–A8을 curl"는 시간 상한이 아니라 불가** —
there is no `lnpl serve` session to curl against for this case's actual
workflows, full stop, given the F-12/F-13 double-bind already established.

## What was still verified — F-4's status-code claims, via an isolated equivalent fixture

Since the case's own workflows can't be served, the specific mechanism
question F2 raised (does a guard-skip really return 200, does a forced
`RunError` really return something else) was verified against a **minimal
fixture with the identical two mechanisms** (`find`+`when`+`set`+`respond`,
no `create ... as`, so it doesn't trip F-12) — same platform, same
`docs/serving.md` mapping table, isolated from F-12/F-13's interference:

```
$ lnpl serve .claude/tmp/http_probe/probe.lnpl --port 8794 \
    --backend sqlite:.claude/tmp/http_probe/probe.db --jwt-secret-env LNPL_JWT_SECRET
serving ... (mode A, backend=sqlite, jwt=verified)

$ curl -X POST .../thing-service/seed-thing -d '{"id":"1111…8888","flag":1}'
HTTP 200

$ curl -X POST .../thing-service/do-thing -d '{"id":"1111…8888"}'   # guard true, flag 1->2
HTTP 200
{"status":"completed", ..., "response":{"thing":{"id":"1111…8888","flag":2}}}

$ curl -X POST .../thing-service/do-thing -d '{"id":"1111…8888"}'   # guard now false (flag==2)
HTTP 200
{"status":"completed", "skipped":[{"guard":"wf.do.thing.guard.1","condition":"thing.flag == 1",
 "evaluations":[{"ref":"thing.flag","value":2,"op":"==","expected":1,"holds":false}]}], ...}

$ curl -X POST .../thing-service/force-fail -d '{"id":"1111…8888"}'  # list-where matches 0 rows
HTTP 500
{"title":"workflow execution failed","status":500,"code":"workflow-failed",
 "detail":"aggregate 'max other.val': min-max-of-empty-rowset — `max val` needs at least one row",
 "failed_step":"set thing.flag to max other.val"}
```

**Confirmed with real transport-level evidence, not mode-A inference:** a
guard-skip is genuinely HTTP 200 with `skipped[]` (F-4's core claim), and
this case's `list where`-forced-RunError rejection technique (used
throughout R2/R5/R7, evidence/03) genuinely maps to HTTP 500
(`workflow-failed`), not a 4xx — both exactly as `docs/serving.md`'s M9/M8
rows state, now with an observed status line rather than a read of the
spec.

## PAN grep — not exercisable

F-8 already recorded that this implementation never receives a full card
number to begin with (client sends `cardLast4` pre-extracted). With `Pay`
itself unable to be served (F-12), there is no live request/log to grep
for a PAN either way — recorded as 불가, not silently skipped.

## Seeding / tokens (round 1, still valid — the corrected source's
entities/fields are unchanged, only three `respond` lines changed)

`lnpl serve` boot-time fail-fast on missing `--jwt-secret-env` when
`security role` is declared, `lnpl token`'s lack of a `--role` flag
(F-14), and the `secret_export` guardrail note are unchanged from round 1
and not re-quoted here.

# evidence/09 — Purity

```
$ git status --porcelain -uall | grep -v '^?? qa/probe-v0.8/cases/s1-order-platform/'
(empty)
```

All changes (tracked and untracked) are confined to
`qa/probe-v0.8/cases/s1-order-platform/`. No `impl/`, `scripts/`, `docs/`,
`rfcs/`, `plugins/`, `examples/`, or `README.md` path appears in git status.

```
$ git status --porcelain -uall | grep -E '^\s*[AM]\s+(impl|scripts)/'
(empty)
```

`impl/` was read twice, both times to name the root cause of an already
empirically-observed friction (README §2's exception), never to fix
anything:

- `impl/lnpl/repo_policy.py` (`row_key`, `binding_name`) — root cause of
  F-3 (every entity touched in one execution shares one payload `id`).
- `impl/lnpl/openapi.py` (`_response_schema`) and `impl/lnpl/interp.py`
  (default-row seeding around `RepositoryCall`/`create`) — root cause of
  F-12/F-13 (OpenAPI crash on `create ... as` + `respond`, and the
  false-conflict bug in the one workaround that avoids it).

Both are named with `근인(impl 열람)` in their FINDINGS.md entries. `impl/`
was never modified (confirmed above) and `scripts/` was never opened
(only executed: `bash scripts/dev_doctor.sh`, per README §2's explicit
allowance).

## Scratch

```
$ ls .claude/tmp | wc -l
```

`.claude/tmp/` holds this task's sqlite backends (`s1*.db`, `serve.db`),
seed/scenario payload JSON, ~30 `roundN.stderr`/`.lir.json` compile
transcripts, and `find_probe/`/`r1-probe-tree/`/`spec_probe/`/`http_probe/`
(the isolated fixtures behind F-2/F-3/F-4/F-12/F-13/F-17/R1's probe,
evidence/01/04/05/06/09). Nothing under `/tmp` was used (one accidental
`lnpl openapi -o /tmp/...` invocation during round-2 re-verification
errored out before writing anything — confirmed no file was created, no
cleanup was needed beyond a no-op `rm -f`). Left in place as the session's
own record — not copied into `evidence/` verbatim, but every command+output
pasted into evidence/00–09 was run from exactly these files.

## Round 2 addendum

No new `impl/` file was opened this round — the `lnpl serve` startup
crash (F-12's severity upgrade, evidence/06) was confirmed from the CLI's
own traceback output (file paths and line numbers it printed), not from
reading `impl/lnpl/wsgi.py`/`serve.py` directly. The impl/-read count in
FINDINGS.md's header (2) is unchanged from round 1.

```
$ git status --porcelain -uall | grep -v '^?? qa/probe-v0.8/cases/s1-order-platform/'
(empty)   # re-confirmed after all round-2 edits
```

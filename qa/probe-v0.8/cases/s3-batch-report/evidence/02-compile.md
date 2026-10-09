# 02-compile — compile rounds (--strict=warning)

Round tally and probe list: see `01-authoring.md`. This file has the actual compiler
output for the case's real sources.

## Final compile, both files together
```
$ .venv/bin/lnpl compile --strict=warning src/domain.lnpl src/settlement.lnpl
```
rc=0. One diagnostic on stderr:
```
info: declared-not-enforced [event.daily.rollup] (line 33) event schedule — declared but
unenforced: by default nothing calls it; `lnpl trigger --schedule NAME` and
`POST /-/schedules/<slug>` (`lnpl serve`) run the linked workflow on demand, but only when
an external scheduler (cron/systemd — see `lnpl schedules`) is configured to call one of
them (issue #81)
1 info, 0 warning(s), 0 error(s)
```
This is expected and intentional (R2 explicitly tests the `on schedule` + `lnpl trigger`
split, not automatic cron execution) — matches `docs/ENFORCEMENT-MATRIX.md` line 83 exactly.

## Sweep safety (D12)
`src/*.lnpl` = exactly `domain.lnpl` + `settlement.lnpl`, both already compiled together
above with 0 `unknown-entity`/`unknown-verb` diagnostics. No `src/probes/` files exist —
every experiment that needed a throwaway file used `.claude/tmp/probe/` (deleted after
each answer, listed in `01-authoring.md`), never `src/`.

## Money type restriction — confirmed by direct compiler error text (feeds FINDINGS F-item)
```
$ lnpl compile --strict=warning <probe>
compile error: workflow ComputeNet: 'set report.net to report.gross - report.fees' uses
report.net, whose declared type Money is neither Integer nor DateTime — RFC-0016 computes
over whole numbers and instants only (Money and the composite types have no evaluator in
either mode)
rc=2
```
Repeated with a **plain copy**, no arithmetic operator (`set report.net to input.net`,
`report.net` still Money) — same rejection, same message. So the restriction fires on the
**target field's declared type**, not on the presence of an operator: a Money field cannot
be written by `set` at all except through an aggregate expression (`sum`/`avg`/`min`/`max`
over a `list`-bound RowSet). Aggregate writes to a Money field compile and run cleanly (see
`03-run.md`).

## Undocumented `input.<field>` global-name rule — confirmed by direct compiler error text
```
compile error: ... 'list Payment where merchant == input.merchantId' names input field
'merchantId', which no entity declares (declared fields: amount, id, merchant, total)
```
and, in a **guard** context unrelated to `list where`:
```
compile error: ... 'input.bumpAmount > 0' names input field 'bumpAmount', which no entity
declares (declared fields: id, qty)
```
Every `input.<field>` reference anywhere in a module must spell a field name some entity in
that module declares — this is not scoped to the entity being read/listed. Not stated in
`lnpl-authoring/SKILL.md`, `references/grammar.md`, or the RFC-0038 guide text I read
(RFC-0038 §Guide-level Explanation instead says an unrecognized-shape `input.<field>` on the
list-where RHS defers typing to runtime — that is a *different, narrower* claim than "the
name itself must exist somewhere", and reading only that RFC section would predict this
compiles). Cost: 2 of the 6 discovery-probe rounds in `01-authoring.md`.

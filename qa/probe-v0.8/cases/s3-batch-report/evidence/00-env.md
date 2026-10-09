# 00-env — environment setup

## Commit / versions
- HEAD sha: `264e3442d653e5534d827687ebac5ede956e801a`
- `.venv/bin/lnpl --version` → `lnpl 0.8.0`
- `.venv/bin/python --version` → `Python 3.13.1` (python3.13 via `/opt/homebrew/bin/python3.13`, per AGENTS.md — python3 default is 3.14 and breaks this repo)
- venv: created fresh in this worktree at `.venv` (`python3.13 -m venv .venv && .venv/bin/pip install -e .`), pip rc=0

## dev_doctor.sh
```
$ bash scripts/dev_doctor.sh
rc=1
linkly 기여자 환경 진단
------------------------
python3.13  : Python 3.13.1
venv        : 없음
MLIR/LLVM   : 없음 — mlir-opt mlir-translate
sysroot 정합: .../MacOSX26.2.sdk
SDK 경로    : CPATH/LIBRARY_PATH 미설정
```
rc=1 caused by (a) venv not yet created at run time (fixed immediately after, see above) and (b)
missing MLIR/LLVM toolchain for mode B (`lnpl build`). Per s3.md R7 this case measures **mode A**
(`lnpl run`/`lnpl trigger`), not mode B, so the LLVM gap is out of scope for this case — recorded
per AGENTS.md as an environment condition, not a code regression. Not fixed (no venv mutation
outside `.claude/tmp/`/case dir needed beyond `.venv` itself, no LLVM install attempted).

## lnpl CLI surface (mode A relevant subcommands, `lnpl --help`)
compile, run, trigger, schedules, spec, openapi, generate, serve, token, outbox, relay, db,
migrate, build (mode B, unused), diff, config, vocab, grammar, cost, capabilities, kb, agents.

## Knowledge entry (README §2 allowed sources read so far, file:approx-lines)
- AGENTS.md (routing only, top-level) — 63
- plugins/lnpl/skills/lnpl-authoring/SKILL.md — 78
- plugins/lnpl/skills/lnpl-authoring/references/declarations.md (enforcement matrix, grep only so far) — partial
- plugins/lnpl/skills/lnpl-authoring/references/grammar.md (grep: repeat/until/group) — partial
- plugins/lnpl/skills/lnpl-authoring/references/patterns.md — 1-13 (RowSet/group-by pointer)
- plugins/lnpl/skills/lnpl-authoring/references/rfcs.md — RFC index (RFC-0025/0038/0044/0045/0048 rows)
- docs/ENFORCEMENT-MATRIX.md (schedule row) — partial
- docs/serving.md (schedule/trigger sections, lines ~214-320) — partial
- rfcs/0025-row-sets-and-aggregation.md (Status + Guide-level Explanation) — ~90 lines
- rfcs/0038-list-where-predicate.md (Status only so far)
- rfcs/0044-money-arithmetic.md (Status only so far)
- rfcs/0045-rowset-aggregation-extension.md (Status + avg/min/max semantics, empty-RowSet errors) — ~170 lines
- rfcs/0048-collections-non-goal-and-rowset-group-by.md (Status + Guide-level + Reference-level §2) — ~135 lines
- rfcs/0002-syntax.md (RepeatGuard production, grep only)

## Preliminary platform finding — feeds F-item in FINDINGS.md (task 06)
`group by` (RFC-0048) is **Status: Draft**, not Accepted — it does not appear in the generated
`plugins/lnpl/skills/lnpl-authoring/references/grammar.md` (which is machine-generated from the
compiler's own tables via `scripts/gen_plugin_references.py`, so its absence reflects the actual
parser, not a stale doc). RFC-0048 §2(g) says explicitly: "설계를 확정 ... 파서·lower·런타임의
실제 구현은 이 RFC의 범위 밖" (design frozen; parser/lower/runtime implementation deferred to a
follow-up issue). By contrast RFC-0025 (RowSet + sum/count), RFC-0038 (`list where`/order
by/limit), RFC-0044 (Money arithmetic), RFC-0045 (avg/min/max) are all **Accepted**.

Separately, `repeat` is `repeat <Integer>` — a **fixed-count** repeat guard (RFC-0002 §syntax,
`RepeatGuard ::= 'repeat' Integer EOL`), not a for-each-row-in-RowSet loop; `if/for/while/switch`
are lexically forbidden (lnpl-authoring SKILL.md 함정 3). `list <Entity>` binds the entity's
**entire** row set into an aggregate-only binding (RFC-0025 Guide-level Explanation) — there is no
in-language construct that runs a block of steps once per row of a RowSet.

Net effect for R3 (per-merchant monthly settlement over 50 merchants in one pass): the language as
shipped in 0.8.0 has no in-language way to (a) group Transaction rows by merchant, or (b) iterate a
workflow body once per merchant. `list Transaction where merchant == <literal>` + the 5 aggregate
functions can compute one merchant's numbers per workflow invocation, but producing all 50 rows
requires driving 50 invocations from outside lnpl (external loop) — this is an orchestration gap,
not (by itself) a computation gap: the actual gross/fees/net/avg/max/min arithmetic per merchant
*is* expressible in-language via `list where` + `sum`/`avg`/`min`/`max`/`count` (Accepted RFCs).
Task 02 will attempt the per-merchant-invocation shape first before falling back to a Python
loop-driver; whichever shape is used will be labelled precisely in FINDINGS per D10 (우회 표기).

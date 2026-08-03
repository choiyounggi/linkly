# Task 05: give the new gates mutation coverage

## Objective

`impl/tests/mutation_check.py` carries one entry per branch this work added, each
verified RED, and its baseline is still GREEN.

## Wiki pages (read these first, only these)

- `wiki/testing/quality/tests-that-cannot-fail.md` — the reason this task exists.
  A relaxed gate that only ever says yes is indistinguishable from a deleted gate,
  and the suite alone cannot tell you which one you shipped.

## Inputs

- From tasks 02-04: `protocol.reference_only_edit`, `protocol.attachments`,
  `protocol.moves`, the relaxed rights loop in `_m_ir_propose`, the relaxed stages
  1/3/4 in `Reviewer._assess`, and `agents.RefactoringAgent`.
- `impl/tests/mutation_check.py`, measured: `MUTATIONS` is a list of
  `(label, relpath, original, mutated)` where `relpath` is relative to `impl/`.
  56 entries, **baseline GREEN, 0 STALE** (repaired in the previous PR — do not
  re-break it). `apply_and_run(label, relpath, original, mutated)` returns
  `(verdict, note)`; verdict `RED` means the suite caught the mutation, `GREEN`
  means nothing did, `STALE` means the anchor text was not found.
- Decisions that bind you: **D18** (one entry per new branch).

## Steps

1. Add **eight** entries to `MUTATIONS` — one per decision branch tasks 02-04
   introduced, not a sample. Anchor each on text that exists **after** those tasks,
   and copy the anchor strings out of the files rather than retyping them: a
   mistyped anchor reports `STALE`, which `main()` does **not** treat as a failure,
   so it is a silent pass.

   | Label | File | Removes |
   |---|---|---|
   | `Intent: accept any out-of-rights edit as an attachment` | `lnpl/protocol.py` | condition (c) of `reference_only_edit` — the non-reference-field comparison |
   | `Intent: compare references as sets, ignoring order and field` | `lnpl/protocol.py` | condition (d)'s per-field order-preserving comparison, replaced by a set comparison. **The single most important entry** — a set comparison is what let an audit reverse a workflow's execution order and migrate a `Policy` out of `constraints` |
   | `Intent: let a proposal attach a node it did not author` | `lnpl/protocol.py` | the D7 containment check |
   | `Intent: attach a child its parent may not own` | `lnpl/protocol.py` | the `CHILDREN_ALLOWED` check |
   | `Intent: accept an out-of-rights edit with no agent origin` | `lnpl/protocol.py` | the `meta.origin` requirement |
   | `Intent: treat every dropped reference as a declared move` | `lnpl/agents.py` | the `unexplained` filter in `_assess` stage 4 |
   | `Intent: accept a move whose destination takes it in another field` | `lnpl/agents.py` | the same-field requirement in `_assess` step 5 |
   | `Refactoring: split without moving the extra access` | `lnpl/agents.py` | `RefactoringAgent._split`'s removal of the extra call ids from the original step |

   Place them next to the existing agent/protocol entries rather than at the end,
   so related mutations stay adjacent.

   **Also confirm task 03 re-anchored the entry it invalidated.**
   `Reviewer: allow a replacement to drop references (removal by edit)` is anchored
   on `            if dropped:\n                return False,`, which task 03 step 4
   renames to `if unexplained:`. Task 03 owns the fix; this task's `STALE` check is
   what catches it if it was missed.

2. Add a short comment above the block noting that these eight cover every branch
   RFC-0010 introduced, that the last is the agent rather than a gate — it proves
   the split is a *move* and not a duplication, which `_structure_fault` would
   otherwise catch as contested ownership — and that the set-comparison entry is
   the one guarding against the two attacks that got through the design's first
   draft.

3. Run every new entry and require `RED`. Then run the whole harness and require
   the baseline `GREEN` with `0 STALE`.

## Deliverables

- `impl/tests/mutation_check.py` (modified — eight entries plus a comment)

## Verify

```bash
cd ~/Desktop/workspace/ai && mkdir -p .claude/tmp
PYTHONPATH=impl .venv/bin/python -c "
import sys, os; sys.path.insert(0, 'impl/tests')
import mutation_check as mc
stale = [l for l, rel, old, _ in mc.MUTATIONS
         if old not in open(os.path.join('impl', rel), encoding='utf-8').read()]
print('total', len(mc.MUTATIONS), '| STALE', len(stale))
for s in stale: print('  STALE:', s)
"
```

Success = `total 64 | STALE 0` (56 existing + 8 new). A `STALE` line means that anchor does not match
the shipped code — fix the anchor, never the code.

Then each new entry must be caught:

```bash
PYTHONPATH=impl .venv/bin/python -c "
import sys; sys.path.insert(0, 'impl/tests')
import mutation_check as mc
new = ('Intent:', 'Refactoring:')
for label, rel, old, mut in mc.MUTATIONS:
    if label.startswith(new):
        print('%-58s %s' % (label, mc.apply_and_run(label, rel, old, mut)[0]))
"
```

Success = **all eight print `RED`**. A `GREEN` means the branch is untested — go add
the missing assertion in the owning task's test class rather than deleting the
mutation.

Then the baseline, which must not have regressed:

```bash
PYTHONPATH=impl .venv/bin/python -c "
import sys, os, tempfile; sys.path.insert(0, 'impl/tests')
import mutation_check as mc
with tempfile.TemporaryDirectory(dir=mc._scratch()) as t:
    r = os.path.join(t, 'repo'); mc.make_tree(r)
    print('baseline:', mc.run_suite(r))
"
```

Success = `baseline: GREEN`.

## Out of scope

- Adding mutations for pre-existing behaviour. Eight new branches, eight entries.
- The stale-anchor class of problem generally — the harness is healthy as of the
  previous PR; keep it that way.

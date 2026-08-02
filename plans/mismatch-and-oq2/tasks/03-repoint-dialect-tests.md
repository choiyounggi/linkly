# Task 03: point the dialect tests at the shared fixture

## Objective

`impl/tests/test_lnpl_dialect.py` no longer carries its own copy of `GUARDED`.
Its emission and verification tests still pass unchanged.

## Wiki pages (read these first, only these)

- `wiki/testing/data/test-data-and-isolation.md` — D2: two verbatim copies of the
  same fixture drift the moment one is edited, which is exactly what task 01 just
  did to the other copy.

## Inputs

- From task 01: `impl/tests/fixtures.py` exporting `GUARDED` and
  `guarded_source(guard)`.
- `impl/tests/test_lnpl_dialect.py` currently defines its own `GUARDED` constant
  and a local `guarded_doc(guard)` helper that does
  `GUARDED.replace("when token missing", guard)` then `lower(parse(src), "t")`.
- **Two call sites use `GUARDED` directly and cannot go through
  `guarded_source(guard)`** — they replace a *two-line* block, not the guard line:
  - `test_interleaved_unroll_rounds_are_numbered_per_node_id` substitutes
    `"    when token missing\n    cache user"` with a `repeat 2` + `pipeline`
    block.
  - `TestStringEscaping.workflow_named` deletes that same two-line block and then
    rewrites the `load user` line.

  Both must keep working, so `GUARDED` stays imported. Leaving it out of the
  import raises `NameError` in three tests — measured.
- Decisions that bind you: **D2** (one home for the source).

## Steps

1. Delete the module-level `GUARDED` in `test_lnpl_dialect.py` and add
   `from tests.fixtures import GUARDED, guarded_source`. **Both names** — see
   Inputs for the two sites that need `GUARDED` itself.

2. Rewrite the local helper to delegate, keeping its name and signature so no
   call site changes:

   ```python
   def guarded_doc(guard):
       """The shared GUARDED workflow with its guard line replaced."""
       return lower(parse(guarded_source(guard)), "t").to_document()
   ```

   Note the substitution now goes through `guarded_source`, which replaces the
   **indented** line. The old local version replaced the bare phrase, so callers
   passed `"until counter >= 10"` and got correct indentation by luck; with
   `guarded_source` that is explicit.

3. Change nothing else. The tests in this file do text emission, dialect
   verification, byte-comparison and build gating — none run the differential, so
   the cache budget task 01 added is inert here. It does add a `Capability` and a
   `Performance` node to the document, which is why step 4 checks the counts.

4. Re-check the assertions that count things, since the fixture grew nodes:
   `test_unrolled_until_rounds_share_one_node_id`,
   `test_unrolled_repeat_rounds_share_one_node_id` and
   `test_every_op_carries_a_node_id_and_a_location` count **steps and effects**,
   which the new capability/performance clauses do not create. If any count
   assertion moves, do not adjust the number to fit — find out why first, because
   the fixture change was supposed to be step-neutral.

## Deliverables

- `impl/tests/test_lnpl_dialect.py` (modified)

## Verify

```bash
cd ~/Desktop/workspace/ai && mkdir -p .claude/tmp
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl
```

Success = `OK`, no failures.

Then confirm the duplicate is really gone and both files now read one source:

```bash
git grep -c "^GUARDED = " -- impl/tests
```

Success = only `impl/tests/fixtures.py` is listed.

## Out of scope

- `test_backend.py` — task 02 owns it.
- Changing any assertion's expected value. If one breaks, that is a finding, not
  a number to update.

# Task 01: give the test sources one home, and give GUARDED a cache TTL

## Objective

`impl/tests/fixtures.py` exists and exports the two workflow sources the
divergence tests need: `GUARDED` (whose differential baseline is now EQUIVALENT)
and `UNTIL_COUNTER`. Nothing imports it yet, so the suite is untouched at 336.

## Wiki pages (read these first, only these)

- `wiki/testing/data/test-data-and-isolation.md` — governs D2 and D3: why the
  source strings are shared (immutable) while the payloads stay in the test
  bodies (the reader must see why a test passes).

## Inputs

- `impl/tests/test_backend.py` currently defines `GUARDED` as a module constant.
  `impl/tests/test_lnpl_dialect.py` defines a **verbatim duplicate**. Both stay
  as they are in this task; tasks 02 and 03 repoint them.
- `impl/tests/test_until_mode_equivalence.py` defines `SRC`, an
  `until counter >= 10` workflow already proven EQUIVALENT at `counter` 0/9/10/100.
- Decisions that bind you: **D1** (add redis + a cache budget), **D2** (one
  module), **D3** (no payloads in the fixture module), **D4** (the `until` source
  moves here).

## Steps

1. Create `impl/tests/fixtures.py`. Module docstring must say why `GUARDED`
   carries a cache budget — a `CacheAccess set` with no TTL makes mode A raise
   `RunError` while mode B returns 0, so the differential is divergent before any
   test does anything, which is what made three mismatch cases vacuous.

2. Export `GUARDED` exactly as below. The `capability redis`, the `token Text`
   field and the `performance / cache 5m` clause are all load-bearing and were
   measured together — do not trim any of them.

   **The block below is indented for this document.** In `fixtures.py` the string
   contents start at column 0: `capability postgres` has no leading space, and the
   nested lines carry exactly 4 or 8. The language is indentation-sensitive, so a
   copied-in indent produces a `ParseError` — loud, but wasted time.

   ```python
   GUARDED = """
   capability postgres
   capability redis
   entity User
       field
           id UUID
           email Email
           token Text
   service S
       performance
           cache 5m
   workflow W
       load user
       when token missing
       cache user
   """
   ```

3. Export `guarded_source(guard)`, which substitutes the whole indented guard
   line so callers never manage indentation:

   ```python
   def guarded_source(guard):
       """GUARDED with its guard line replaced — e.g. guarded_source("repeat 3")."""
       return GUARDED.replace("    when token missing", "    " + guard)
   ```

4. Export `UNTIL_COUNTER`, copied **verbatim** from
   `test_until_mode_equivalence.py`'s `SRC` — including the `doneAt DateTime`
   field.

5. Then **repoint that file at it** (D16): delete its module-level `SRC` and add
   `from tests.fixtures import UNTIL_COUNTER as SRC`. Keeping both would leave two
   verbatim copies of the `until` source — the drift this module exists to
   prevent, committed in the name of preventing it. Its six tests must still pass
   unchanged; the string is identical, so nothing about them should move.

6. Export nothing else. In particular **no payload dicts and no `PAYLOAD`
   constant** — each test supplies the payload whose values explain its outcome
   (D3). `test_backend.py`'s existing `PAYLOAD` stays where it is.

## Deliverables

- `impl/tests/fixtures.py` (new)
- `impl/tests/test_until_mode_equivalence.py` (modified — `SRC` now imported)

## Verify

```bash
cd ~/Desktop/workspace/ai && mkdir -p .claude/tmp
PYTHONPATH=impl .venv/bin/python -m unittest discover -s impl/tests -t impl
```

Success = `OK`, still **336** tests. Nothing imports the new module yet, so a
change in the count means you edited something you should not have.

Then confirm the new `GUARDED` is actually equivalent — this is the whole point
of the task, and it is not covered by any test until task 02:

```bash
PYTHONPATH=impl .venv/bin/python -c "
import os, shutil, tempfile
from lnpl import differential
from lnpl.lower import lower
from lnpl.parser import parse
from tests.fixtures import GUARDED
d = tempfile.mkdtemp(prefix='t01-', dir='.claude/tmp')
doc = lower(parse(GUARDED), 't').to_document()
rows = {'entity.user': {'id': '3f2504e0-4f89-41d3-9a0c-0305e82c3301', 'email': 'u@e.com'}}
ok, rep = differential.verify(doc, 'wf.w', {'id': '3f2504e0-4f89-41d3-9a0c-0305e82c3301', 'email': 'u@e.com'}, rows, d)
print('EQUIVALENT' if ok else 'STILL DIVERGENT: ' + str([l for l in rep if 'FAIL' in l]))
shutil.rmtree(d, ignore_errors=True)"
```

Must print `EQUIVALENT`. If it prints `STILL DIVERGENT`, the fixture is wrong —
fix it here rather than letting task 02 inherit the problem.

## Out of scope

- Editing `test_backend.py` (task 02), `test_lnpl_dialect.py` (task 03), or
  `test_until_mode_equivalence.py` (not in this plan at all).
- Adding tests. This task ships data, not assertions.

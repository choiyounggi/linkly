# Task 01: OQ① canonical LLVM version-pin file + reader

## Objective
`mlir/llvm.pin` exists as the single machine-read source of the pinned LLVM/MLIR
version; `backend.py` exposes `LLVM_PIN_PATH` and `pinned_llvm_version()` that
read it by anchored path; a test in `test_backend.py` proves the pin parses and
(when the toolchain is present) matches the installed `mlir-opt`.

## Wiki pages (read these first, only these)
- wiki/platforms/toolchains/version-management.md — use for: why one committed
  pin file is the source of truth and must not be duplicated in prose/code.
- wiki/platforms/environment/path-resolution.md — use for: locating the pin file
  by a path anchored on `__file__`, never cwd (D6).
- wiki/testing/quality/tests-that-cannot-fail.md — use for: making the pin test
  able to actually go red on drift, and skip (not vacuously pass) when the
  toolchain is absent.

## Inputs
- `impl/lnpl/backend.py` — has `REPO_ROOT` (three dirnames up from `__file__`),
  `LNPL_IRDL_PATH` (the pattern to mirror), `tool()`, `toolchain_available()`,
  `_run(...)`. Read lines ~40–130.
- Measured: `brew list --versions llvm` → `llvm 22.1.8`; `mlir-opt --version`
  prints a line containing `22.1.8` (`Homebrew LLVM version 22.1.8`).
- Decisions that bind you: D4 (pin format `llvm 22.1.8`), D5 (reader + test, no
  hard gate), D6 (anchored path `LLVM_PIN_PATH`).

## Steps
1. Create `mlir/llvm.pin` with exactly one line and a trailing newline:
   ```
   llvm 22.1.8
   ```
   No comments, no second line — a second declaration is what D4 forbids.
2. In `backend.py`, next to `LNPL_IRDL_PATH`, add:
   ```python
   LLVM_PIN_PATH = os.path.join(REPO_ROOT, "mlir", "llvm.pin")
   ```
3. Add a reader near `tool()`:
   ```python
   def pinned_llvm_version():
       """The single pinned LLVM/MLIR version, read from mlir/llvm.pin (OQ①).

       The pin file is the one machine-read declaration of the version; nothing
       else in the tree restates it. Format: one `llvm <version>` line.
       """
       with open(LLVM_PIN_PATH, encoding="utf-8") as fh:
           line = fh.readline().strip()
       parts = line.split()
       if len(parts) != 2 or parts[0] != "llvm":
           raise BackendError(
               "mlir/llvm.pin must be one line `llvm <version>`, got %r" % line)
       return parts[1]
   ```
4. In `impl/tests/test_backend.py`, add a `TestVersionPin` class with three
   cases (normal / boundary / integration), each asserting:
   - normal: `pinned_llvm_version()` returns a non-empty dotted version
     (`re.match(r"\d+\.\d+\.\d+$", v)`).
   - boundary/error: a `pinned_llvm_version` call against a temp pin file whose
     content is malformed (e.g. `"clang 1.2.3"` or `"22.1.8"`) raises
     `BackendError`. Point the reader at the temp file by monkeypatching
     `backend.LLVM_PIN_PATH` inside the test and restoring it (or by
     temporarily writing the bad content — use `.claude/tmp/`, never `/tmp`).
   - integration: `if backend.toolchain_available():` assert
     `pinned_llvm_version()` appears as a substring of the `mlir-opt --version`
     output (call `backend._run([backend.tool("mlir-opt"), "--version"], "pin")`
     or `subprocess`); else `self.skipTest("toolchain absent")`.

## Deliverables
- `mlir/llvm.pin` (new)
- `impl/lnpl/backend.py` (add `LLVM_PIN_PATH`, `pinned_llvm_version()`)
- `impl/tests/test_backend.py` (add `TestVersionPin`)

## Verify
- `mkdir -p .claude/tmp && PYTHONPATH=impl .venv/bin/python -m unittest
  impl.tests.test_backend.TestVersionPin -v` → OK (integration case may show
  `skipped` if the toolchain is absent; it must NOT be reported as passed
  vacuously — the skip is the honest outcome).
- `PYTHONPATH=impl .venv/bin/python -c "from lnpl import backend;
  print(backend.pinned_llvm_version())"` → prints `22.1.8`.

## Out of scope
- Enforcing the version as a hard build/`build()` gate (D5: test-only).
- Editing `rfcs/0004-compiler.md` to mark OQ① resolved — that is task 05.
- Any CI workflow (there is none; D5/M5).

# lnpl-mcp

The LNPL compiler as **MCP tools** rather than a shell command.

## Why this exists

`lnpl compile` writes its diagnostics to **stderr and exits 0**. A caller that
branches on the exit code therefore misses every warning — and in LNPL a warning
is not cosmetic: `unknown-verb` means that step derives no effect and **does
nothing at runtime** (issue #36).

Calling it through a shell puts three failure points between the compiler and the
model:

| Shelling out | With these tools |
|--------------|------------------|
| Get the redirection order right (`2>&1 >/dev/null`) or capture the IR instead of the diagnostics | No streams involved |
| Re-parse prose that was written for a human and is not a stable interface | A `diagnostics` array with `code` / `severity` / `where` / `subject` |
| Find the CLI on `PATH` — which an agent process often does not have | The compiler is imported in-process |

## Tools

| Tool | Use it when |
|------|-------------|
| `lnpl_compile` | Before and after writing any `.lnpl`. Takes `text` (check a draft without saving it) **or** `path`. Returns every diagnostic as a record plus an `unknown_verbs` count. |
| `lnpl_kb_route` | **Before** making an architecture, naming, performance, security, testing, concurrency, database, or cloud decision. Returns the knowledge-base documents that govern it (RFC-0005). |
| `lnpl_spec` | After writing `spec` blocks, to check them without shelling out to `lnpl spec --run`. Takes `text` **or** `path`. Returns each case's `pass`/`fail` status with expected-vs-actual detail for failures; a source with no `spec` block reports `spec_present: false`, not an error. |

Tool names arrive prefixed: `mcp__plugin_lnpl-mcp_lnpl__lnpl_compile`.

## Install

```
/plugin marketplace add choiyounggi/linkly
/plugin install lnpl-mcp@linkly
```

Pair it with `lnpl@linkly`, which carries the closed-vocabulary references and
the write-time diagnostics hook. This plugin answers "what does the compiler say";
that one answers "what words exist".

## Finding the compiler

The server needs the `lnpl` package. It resolves it in this order and fails loudly
if none works:

1. `$LNPL_IMPL` — the `impl/` directory of a linkly checkout
2. `import lnpl` — installed with `pip install .`
3. Walking up from the working directory for `impl/lnpl/` — this is what makes it
   work inside a linkly checkout with no install at all

Set `LNPL_IMPL` if you run Claude Code from outside the repo and have not
installed the package.

## What it does not do

No `run`, `diff`, `serve`, or `build`. Those execute programs, start servers,
and shell out to the MLIR/LLVM toolchain — a different risk surface that
belongs behind an explicit command, not an always-available tool.

`lnpl_spec` is not in that list even though it runs a workflow: `spec` cases
execute against the interpreter's deterministic fake backend — no real I/O, no
network, no process spawned, no side effects outside the call — the same
backend `lnpl spec --run` uses. That puts it on the same footing as
`lnpl_compile` and `lnpl_kb_route`: all three answer a question **before**
anything runs for real, which is what a model needs while it writes.

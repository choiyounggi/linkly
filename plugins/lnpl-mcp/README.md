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
| `lnpl_vocabulary` | When no plugin reference is loaded: the closed vocabulary (verbs, keywords, types, diagnostic codes) as one manifest. |
| `lnpl_capabilities` | Before choosing a `--backend`/`--cache`/`--network` value: every extension slot with its built-in and registered names, and whether each loads. |
| `lnpl_run` | To run a workflow without shelling out to `lnpl run`. Takes `text` **or** `path`, optional `workflow`, `payload`, `no_row`. Runs only on the fake backend and virtual clock and returns `{result, trace, diagnostics}`; `diagnostics` is always a list. |
| `lnpl_openapi` | To get the OpenAPI 3.1 document as text — the same bytes `lnpl openapi` prints. |
| `lnpl_generate` | To get `compose` or `k8s` deployment files as text (`{generator, files, warnings}`), with `options` as the `--set` keys. Nothing is written. |

Tool names arrive prefixed: `mcp__plugin_lnpl-mcp_lnpl__lnpl_compile`.

## Install

```
/plugin marketplace add choiyounggi/linkly
/plugin install lnpl-mcp@linkly
```

Pair it with `lnpl@linkly`, which carries the closed-vocabulary references and
the write-time diagnostics hook. This plugin answers "what does the compiler say";
that one answers "what words exist".

## Transports

The plugin starts the stdio server. The same tools are also served over MCP
Streamable HTTP at `/mcp`, for clients that cannot spawn a process.

### stdio (what the plugin ships)

```json
{
  "mcpServers": {
    "lnpl": {
      "command": "python3",
      "args": ["-E", "${CLAUDE_PLUGIN_ROOT}/server.py"]
    }
  }
}
```

### Streamable HTTP

```bash
export LNPL_MCP_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 -m lnpl.mcp_http --port 8765
```

The server refuses to start unless `LNPL_MCP_TOKEN` holds at least 32
visible-ASCII bytes, binds 127.0.0.1 unless `--host` says otherwise, and prints
`lnpl-mcp: http listening on 127.0.0.1:8765`. Point a client at it from your
own user or project `.mcp.json`:

```json
{
  "mcpServers": {
    "lnpl-http": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp",
      "headers": {"Authorization": "Bearer ${LNPL_MCP_TOKEN}"}
    }
  }
}
```

This entry belongs in your own `.mcp.json`, not the plugin's: the plugin's
servers connect at every session start, and an HTTP entry would fail whenever
no server is running. Authentication is a static Bearer token, a deliberate
subset of MCP's optional OAuth authorization.

### Limits of the HTTP transport

- `path` and `root` arguments are refused — send sources as `text`.
- Each tool call runs in a separate child process that is stopped after 10 s
  or above 512 MiB of memory; its response is capped at 4 MiB, and at most 4
  run at once (more get a "server busy" tool error).
- Measured: a runaway call grows about 0.3-0.4 GB/s and is stopped near
  530 MiB. A call that finishes just under the cap can briefly reach the cap
  plus one copy of its result (about 750 MiB) while it is serialized, so the
  worst case is about 3 GiB across 4 concurrent calls.
- Request bodies are capped at 1 MiB and must be `application/json` with a
  `Content-Length` (no chunked encoding).
- Browsers are unsupported — no CORS, and any `Origin` other than
  `http://localhost`, `http://127.0.0.1` or `http://[::1]` (any port) gets 403.
- `lnpl_compile` and `lnpl_capabilities` results include `package_path`, the
  server's install directory.
- At most 64 sessions are kept; the oldest is dropped.
- A request rejected before its body is read is answered and the connection
  closed, so a client still sending a large body may see a connection reset
  instead of the status.
- The 30 s timeout applies per read, so a client that trickles bytes can hold
  a connection, and the server has no connection cap — put TLS, rate limiting
  and connection limits in a reverse proxy before exposing it beyond this
  machine.

## Finding the compiler

The server needs the `lnpl` package. It resolves it in this order:

1. `$LNPL_IMPL_PATH` — an absolute path to the `impl/` directory of a linkly
   checkout, set by you. A relative path, or a path with no `lnpl/__init__.py`
   in it, is ignored (not fatal — the server moves on to the next step and
   notes why on stderr).
2. `import lnpl` — installed with `pip install .`

It never derives a path from the working directory, `CLAUDE_PROJECT_DIR`, or
the file you have open — any of those let a project plant its own `impl/lnpl`
and have it run inside this server process. For the same reason the server
runs as `python3 -E`, which ignores an inherited `PYTHONPATH` (for example one
set by a project's direnv or venv), so step 2 finds only an installed package.

If neither resolves, the server still starts: the handshake succeeds, and
every tool call returns a structured error explaining how to install `lnpl`
or set `LNPL_IMPL_PATH`, instead of the connection just failing silently.

Set `LNPL_IMPL_PATH` if you run Claude Code from outside the repo and have not
installed the package.

## What it does not do

No `diff`, `serve`, `build`, or `relay`. Those start servers, write files,
reach real backends, or shell out to the MLIR/LLVM toolchain — a different risk
surface that belongs behind an explicit command, not an always-available tool.

`lnpl_run` and `lnpl_spec` do execute workflows, but only on the interpreter's
deterministic fake backend and virtual clock — no real I/O, no network, no
process spawned by the tool, nothing written — the same backend
`lnpl spec --run` uses. `lnpl_openapi` and `lnpl_generate` return text and
write nothing.

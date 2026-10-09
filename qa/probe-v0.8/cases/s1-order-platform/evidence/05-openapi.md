# evidence/05 — OpenAPI generation

```
$ lnpl openapi src/ -o src/openapi.json
wrote src/openapi.json (23 path(s))
```

23 paths (5 workflow `POST` routes we authored + 3 seed-only `POST` routes +
15 auto-exposed `GET /<service>/<entity>/{id}` routes, issue #99). Full
listing in `src/openapi.json`.

## F-12 (blocker) — `lnpl openapi` crashes on `create ... as <alias>` + `respond <alias>.field`

This is RFC-0030's own headline pattern (§Guide-level Explanation's first
example: `create order as newOrder` / `respond newOrder.id
newOrder.total`) — and it crashes `openapi.py` with an unhandled
`KeyError`, not a graceful diagnostic:

```
Traceback (most recent call last):
  ...
  File "impl/lnpl/openapi.py", line 277, in generate
    paths[path] = {"post": _operation(child, service, con, nodes, entities, refined)}
  File "impl/lnpl/openapi.py", line 510, in _operation
    response_schema = _response_schema(steps, nodes, entities, refined)
  File "impl/lnpl/openapi.py", line 475, in _response_schema
    entity = by_binding[binding]
KeyError: 'newOrder'
```

Reproduced on a **minimal** two-line fixture with nothing else in it
(`.claude/tmp/find_probe/probeoa2.lnpl`) — not something our workflow's
complexity introduced. 근인(impl 열람): `impl/lnpl/openapi.py:475` —
`_response_schema`'s `by_binding` lookup is keyed by an entity's own
`repo_policy.binding_name` (the `find`/`read` binding name), never by an
author-chosen `create ... as <name>` alias; RFC-0030 added the alias-binding
form to the interpreter (`interp.py`) without updating `openapi.py`'s
response-schema inference to know about it.

**Workaround attempted and rejected:** re-`find <entity>` (using the same
binding's own id) right before `respond`, then `respond <entity>.field`
instead of `respond <alias>.field` — this **does** dodge the openapi crash
(verified, `.claude/tmp/find_probe/probeoa3.lnpl` → 2 paths, no crash), but
it triggers a **worse**, independent bug: **F-13 (blocker)** — a `find
<entity>` step anywhere in a workflow that also `create`s that same entity
(via `as`) makes the *`create` itself* fail with a false "already exists"
conflict, even against a brand-new empty database with a payload id never
used before:

```
$ cat probe11.lnpl
workflow PlaceOrder
    create order as newOrder
    set newOrder.qty to input.qty
    find order
    respond order.id order.qty
$ lnpl run probe11.lnpl --backend sqlite:probe11.db --payload '{"id":"99999999-...-1","qty":5}' --json
status: failed
failure_reason: repository create conflicts: entity.order already exists
```

근인(impl 열람): `impl/lnpl/interp.py` — the interpreter's default-row
seeding for entities a workflow "reads" (RFC-0030-era `default_rows`/
`repo_policy` machinery, meant to bootstrap a sample row for a `find`
precondition) does not distinguish "reads X as an independent
precondition" from "re-reads X after this same execution already created
X" — it pre-seeds a skeleton row for `order` because the workflow contains
a `find order` step *anywhere in its source*, and that pre-seed collides
with the workflow's own later (chronologically first, source-order-wise
also first here) `create order as newOrder`.

**Net effect: no workaround exists that keeps both `lnpl openapi` working
and the workflow's own runtime correct at the same time**, for any
workflow shaped like RFC-0030's own golden example. This implementation
keeps the **correct runtime behavior** (`respond <alias>.field`, no
extra `find`) and accepts that `lnpl openapi` cannot generate a document
for `CreateOrder`/`Pay`/`CancelOrder`'s response schemas as a result —
R8's "OpenAPI 3.1 문서를 생성" is **부분** (충족 for the paths and request
schemas, 불가 for those three workflows' response body schema, since the
generator crashes the moment they are present in the compiled unit).

**Actual state of `src/openapi.json` in this repo:** generated from the
source **before** F-13 was discovered (i.e., while it still had the
`find`-before-`respond` workaround in three workflows) — regenerating it
after the revert reproduces the `KeyError` crash above. The checked-in
`src/openapi.json` is therefore evidence of the crash's shape (23 paths,
all workflows' response schemas present) and not the buildable state of
the final source; task 06's purity/evidence pass notes this explicitly
rather than silently shipping a file the current source cannot regenerate.

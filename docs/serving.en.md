# Serving — `lnpl serve` / WSGI (issues #26, #80)

**English** | [한국어](serving.md)

> This is the English edition of [`docs/serving.md`](serving.md), translated in
> full. The Korean text is normative: where the two disagree, the Korean text
> wins. Identifiers, flags, environment variable names, paths and every code
> block are identical in both editions.

`lnpl serve` binds a compiled module's workflows to the routes OpenAPI defines,
and runs the interpreter (mode A) once per request: request body → payload validation
(the workflow's own `validate` step, the #48 contract) → execution → a status code per
the mapping table below.

This request-processing core lives in `impl/lnpl/wsgi.py` as a standard WSGI
callable (PEP 3333, `environ`/`start_response`) (issue #80). `lnpl serve` is a dev
server that wraps that callable with `wsgiref.simple_server` + `ThreadingMixIn`, and
a production deployment hands the SAME callable to a real WSGI host (gunicorn) — since
only one piece of code runs on both paths, they cannot drift apart (see the "Shared
contract" section below). TLS termination, graceful shutdown and worker management are
the responsibility of that host (+ a reverse proxy such as nginx), not this module —
since issue #110, `lnpl serve` (`serve.serve()`) has a single SIGTERM handler (see the
"Operational surface" section below), but all that handler does is flip `/-/readyz` to
503 — connection draining and actual shutdown are still not this module's
responsibility — the `build_app()`/gunicorn path has no such handler and is unchanged.

```
lnpl serve <src>.lnpl [--host 127.0.0.1] [--port 8080]
```

Each workflow is bound to `POST /<service-slug>/<workflow-slug>` — this is checked
against the routes `lnpl openapi` generates at startup, and the server refuses to
start if they disagree (rc 2).

Issue #99: the read surface is checked the same way. `GET /<service-slug>/<entity-slug>/{id}`
is automatically attached for every entity a workflow touches (no declaration needed,
D1), and a `GET /<service-slug>/<entity-slug>?after=<cursor>&limit=N` list is attached
only for an entity whose `service ... expose / list <Entity> by <field>` clause is
written (opt-in, D2). The cursor is an opaque token encoding the sort key + row_key
(D3), and a list's 200 body is `{"items": [...], "next": <다음 커서 또는 null>}`
(`<다음 커서 또는 null>` is the next cursor, or `null`).
Authorization reuses exactly the same verdict as the workflow path (M3/M3a, D5) —
there is no new 401 verdict specific to reads.

Issue #103: the realtime surface is also derived from an opt-in declaration — instead
of adding ws syntax to the language, the single word `subscribe` on an event
declaration (an AppSync-style explicit opt-in) opens
`GET /<service-slug>/events/<event-slug>` (`Accept: text/event-stream`). This route is
attached only to the service that owns the workflow actually `emit`ting that event
(the same structural rule by which get-single derives entity ownership — derived from
the IR graph with no new declaration; an event with no `subscribe` has no surface and
is a 404). The server tail-polls `lnpl_outbox` (#102) filtered to that event, and
writes an `id: <seq>`/`data: <마스킹된 payload>` SSE frame for every new row
(`<마스킹된 payload>` is the masked payload). `id:` is
t102's `seq` (a monotonic storage cursor), not `emission_id` — `emission_id` is the
trace identifier of one execution and can be reused across re-executions, so it cannot
be used as a reconnection cursor. Reconnection uses the `Last-Event-ID` header (the SSE
standard retransmission mechanism) to pick up only what is past that seq, with no loss.
Authorization reuses exactly the same M3/M3a as the workflow/read paths. The payload is
already a masked value as of `EventEmit` (the #43 contract), so the subscription path
does not mask it separately.

```bash
lnpl serve examples/shorten.lnpl &
curl -s http://127.0.0.1:8080/shorten-service/shorten \
  -H "Authorization: Bearer any" \
  -d '{"id":"3f2504e0-4f89-41d3-9a0c-0305e82c3301","slug":"abc-123",
       "target":"https://example.com/a",
       "owner":"3f2504e0-4f89-41d3-9a0c-0305e82c3302",
       "clicks":0,"createdAt":"2026-07-31T09:00:00Z"}'
```

## Status code mapping table (canonical)

In judgment order. `impl/tests/test_serve.py` pins at least one case per row.

| # | Observed condition | HTTP | error `code` |
|---|-----------|------|--------------|
| M1 | Route not in the routing table | 404 | `not-found` |
| M2 | Route exists but method ≠ POST | 405 + `Allow: POST` | `method-not-allowed` |
| M3 | Service declares `security jwt` ∧ `Authorization` header absent | 401 | `auth-missing` |
| M3a | Token provider configured (`--jwt-secret-env`) ∧ token verification fails | 401 | `auth-invalid` |
| M3b | Token verification succeeds (passes M3a) ∧ service declares `security role <r>` ∧ the verified role mismatches (or is absent) `<r>` | 403 | `forbidden` |
| M4 | `Content-Length` > 1 MiB | 413 | `body-too-large` |
| M5 | Body fails JSON parsing, or is not an object | 400 | `body-unreadable` |
| M6 | Execution fails ∧ `failure_reason` starts with `deadline` | 504 | `deadline-exceeded` |
| M7 | Execution fails ∧ the failed step's effects include `Validation` | 400 | `validation-failed` |
| M8a | Execution fails ∧ a repository create collides with an existing key (`failure_kind == "conflict"`, issue #113) | 409 | `conflict` |
| M8b | Execution fails ∧ a read verb finds no row on a persistent backend (issue #197), or `update`/`delete` affects 0 rows on any backend (issue #215, RFC-0064) — `failure_kind == "not-found"` | 404 | `not-found` |
| M8c | Execution fails ∧ an optimistic version write conflict (`failure_kind == "write-conflict"`, issues #92/#201) — may clear on a re-read and retry | 409 | `write-conflict` |
| M8d | Execution fails ∧ `create`'s payload has no `id` and the target entity's `id` is not `derived generated` either (`failure_kind == "id-required"`, RFC-0055) — rejected before the write | 400 | `id-required` |
| M8e | Execution fails ∧ ends with `fail <code>` (an author-declared business rejection, `failure_kind == "rejected"`, issue #206/RFC-0056) | 422 | the author-declared code (e.g. `out-of-stock`) |
| M8 | Execution fails (everything else) | 500 | `workflow-failed` |
| M9 | `status == completed` — including a guard rejection | 200 | — |
| M10 | GET single: route exists but there is no row (absent, or backend not configured) | 404 | `not-found` |
| M11 | GET list: an entity with no `expose` (the 2-segment route is not in the routing table) | 404 | `not-found` |
| M12 | GET list: the `after` cursor cannot be decoded, or does not match this field's type (forged) | 400 | `cursor-invalid` |
| M13 | GET list: `limit` is not an integer, or is outside `[1, 200]` | 400 | `limit-invalid` |
| M14 | GET (single or list) repository driver error | 500 | `read-failed` |
| M15 | SSE subscription: an event with no `subscribe` (the route is not in the routing table) | 404 | `not-found` |
| M16 | SSE subscription: `Last-Event-ID` is not a non-negative integer (forged) | 400 | `cursor-invalid` |

- **A guard rejection is 200.** RFC-0014 defines `skipped` as a signal orthogonal to
  status — an execution where a guard did its job is rc 0 on the CLI, and if HTTP alone
  gave 4xx the same execution would get a different verdict on its two surfaces. The
  observability contract is carried by the 200 body's `skipped[]`. Each skip record
  carries `guard`/`mode`/`condition`/`steps`/`rounds` plus `evaluations[]` (issue #83 —
  the values the condition actually compared, after masking any sensitive field).
- An empty body runs with payload `{}` (no special case). A workflow with a
  `validate` step gets a 400 via M7, and a workflow without one just runs.
- M6 comes before M7: an execution whose deadline runs out right before the validate
  step is a timeout, not a payload rejection.
- M8a/M8b/M8c/M8d come before M8: all of them split a repository failure by
  `failure_kind` (issues #113/#197/#201, RFC-0055) — only every other failure falls
  through to M8 (500). The verdict comes from the exception type, not from reading the
  message text: if an external driver raises `lnpl.drivers.WriteConflictError` for a
  version conflict it is M8c, and a plain `DriverError` is M8 (500) even with the same
  wording. A 409 still splits by `code` into `conflict` (a create collision — resending
  the same request collides again) and `write-conflict` (resending it may succeed). No
  `Retry-After` header is carried.
- **M8e is a declared rejection, not a guard rejection** (RFC-0056). Only a
  `fail <code>` step reached because its guard was true becomes 422; a `fail` skipped
  because its guard was false is M9 (200). The status is 422 regardless of the code,
  and the verdict is made by `failure_kind`. `code` is the author's code, and `detail`
  is that same code. An author's code cannot collide with one of the server's reserved
  `code`s (a compile error), so `title` is the common phrase
  `the workflow rejected the request`.

The error body has a single shape across every endpoint (RFC 9457 problem+json,
`Content-Type: application/problem+json`): `title`/`status`/`code`/`detail`, plus
`correlation_id`/`failed_step`/`skipped` when an execution took place. A client
branches on `code` (the stable contract), not on `detail` (for humans). The 200 body is
the same dict as `lnpl run --json`'s `result` — `bindings` are masked values (the #43
contract), and a Password-family value's raw text never rides in any response.

### Authorization — trust model and gate scope (issue #119)

Even after passing token verification (M3/M3a), if the verified role differs from
`security role <r>` it is 403 `forbidden` (mapping table M3b, Task 04) — 401 means
"I don't know who you are" and 403 means "I know who you are but you may not", two
different verdicts, so the order is also fixed right after M3a. The 403 body does not
carry which role was required — that information goes out only via server stderr
alongside the correlation id (the same judgment call M3a already makes).

**Trust model (updated by t119b).** The role `security role <r>` enforces is read
from the `role` claim (or a single-element `roles` claim) of the token this server
verified. That trust basis now depends on what the verifier is built from:

- **With only the built-in `hmac` provider (`--token-provider` unset, the default)**
  it is still **self-asserted** — `lnpl token` both issues and verifies on the same
  service. `--jwt-issuer` can change the expected `iss` away from the hardcoded
  `"lnpl"` (t119b, D3), but the signature verification itself is still symmetric-key
  HS256, and whoever holds that key is the issuer — **an SPI being open is not the
  same as an external IdP actually being attached.** With only the built-in provider,
  the question "who may trust this role claim, and why" still has no third-party
  answer. `lnpl token --role <r>` can carry a role claim along with it — this value is
  also self-asserted (issue #202).
- **Selecting a provider registered via the `lnpl.tokens` SPI with
  `--token-provider <name>`** (for example, an external package that verifies
  Keycloak/Auth0/an in-house IdP's RS256/ES256 signature) moves the identity basis
  outside — only a token signed with a private key only that IdP knows passes, and
  linkly only verifies with the public key. RS256/ES256 itself is not in the core
  (t119b, D1) — it is delegated to a `cryptography`-based external package to avoid
  the risk of hand-implementing constant-time comparison and padding. What the core
  owns is only the contract (`TokenProvider`) and the `TokenProviderTCK` that verifies
  that contract (`docs/backends.md`).

To actually cross the self-asserted trust boundary in production you need an
`lnpl.tokens` SPI implementation (an external package) — t119b ships only that SPI
boundary and its TCK.

**Gate scope — action versus object.** `security role <r>` is an **action gate**: it
asks only "may a caller with this role run this route". An **object
(ownership/tenancy) gate** such as "does order #42 belong to this caller" **does not
exist** in linkly — passing the action gate does not mean passing an object gate too
(neither implies the other). A workflow that needs ownership (for example, "cancel
only your own order") is not safe with only this service-level role gate — the
workflow itself must check that condition with a guard.

The canonical reference for the adapter contract, backend selection and the jwt
verification checklist is `docs/backends.md`.

## Idempotency — `Idempotency-Key` (issue #113)

If a `POST /<service-slug>/<workflow-slug>` request carries an `Idempotency-Key`
header, `(workflow_id, key)` makes that execution run only once. **Whether it
succeeds or fails**, the first execution's status code + body are stored as-is, and a
repeat request with the same key replays that stored response — it does not run the
workflow again (the same contract as Stripe: "saving the resulting status code and
body of the first request ... regardless of whether it succeeds or fails"). A client
that wants a real retry uses a new key — the same key being blocked is the contract,
not a bug.

**`Idempotency-Key` is not an RFC.** This header's IETF draft expired and never
became a standard — it is only an industry practice Stripe and several payment APIs
settled on, and linkly follows no normative document for it.

**Key length ceiling — 255 bytes (issue #258).** The key goes directly into the
`(workflow_id, key)` index. Postgres's btree index has a limit on a single entry's
size, so an uncompressed key of about 4000 characters made `idempotency_begin` fail
with a `DriverError`, producing an unhandled 500 (sqlite has no length limit, so the
result differed by backend). So, regardless of backend, a value over 255 bytes is
rejected with 400 `idempotency-key-too-long` (M23) before the repository driver is
even opened — it neither claims the key nor runs the workflow. The length is the
header's raw byte count (PEP 3333 — WSGI passes one header byte as one character). An
ASCII key (a UUID, etc.) equals 255 characters, and a non-ASCII UTF-8 character counts
as 2-4 bytes. 255 matches Stripe's ceiling ("Idempotency keys are up to 255 characters
long"); the header draft sets no length. An empty value is still a valid key.
The generated OpenAPI also declares `maxLength: 255` on this header (issue #261) — JSON
Schema's `maxLength` counts characters, so it only equals the byte ceiling for an ASCII
key.

| # | Observed condition | HTTP | error `code` |
|---|-----------|------|--------------|
| M17 | Already running under the same key (another request has not finished) | 409 | `idempotency-in-progress` |
| M22 | An `Idempotency-Key` header is present, and the configured repository driver's (`RepositoryDriver`) `supports_idempotency()` is False — it does not implement the three claim methods (`idempotency_begin`/`idempotency_finish`/`idempotency_release`) (currently `lnpl-postgres`). Neither claims the key nor runs the workflow | 501 | `idempotency-unsupported` |
| M23 | The `Idempotency-Key` header value exceeds 255 bytes — rejected before the repository driver is opened, so it neither claims the key nor runs the workflow. The same on every backend, including `fake` | 400 | `idempotency-key-too-long` |

A replay is not a new verdict row — it only returns the stored first execution's
status code and body as-is (200 stays 200, a 409 `conflict` stays 409 `conflict`,
unchanged).

**Design (r1 — fixes a flaw in the original plan)**: issue #113's body required both
"write the record inside the workflow transaction" and "replay failures too" together,
and the two are not compatible — `run_workflow` (`interp.py`) **unconditionally** calls
`self.repo.rollback()` on failure (regardless of whether `policy rollback` is declared
— that declaration only turns on one log line, see below), and if the final record sat
inside that transaction, the rollback would undo it too and leave the key **permanently**
stuck at `in-progress`. So it is split into three steps:

1. When the request arrives, INSERT `(workflow_id, key)` as `in-progress` and
   **commit immediately** — a concurrent request with the same key sees this and
   gives a 409.
2. `run_workflow` commits/rolls back in **its own transaction**. The idempotency
   row sits outside that boundary and is unaffected.
3. After `run_workflow` returns, the final status code + body are upserted in a
   **separate statement**.

**Remaining gap**: if the process dies between step 1 and step 3, that key is left
at `in-progress`, and even a retry is blocked for that whole window (it keeps getting
409). The only recovery is `--idempotency-ttl` (default 24h) — once the TTL passes,
that key is treated as a fresh miss. This window is not pretended away: it is short
but real.

**Per-backend rules (issue #228).** Whether `Idempotency-Key` can be honored is
declared by the repository driver's `RepositoryDriver.supports_idempotency()`
(`docs/backends.md` §8 — True only when all three claim methods
`idempotency_begin`/`idempotency_finish`/`idempotency_release` are implemented).
Instead of silently ignoring a key it cannot honor and running the same request
twice, it fails explicitly:

| Backend | When an `Idempotency-Key` arrives | At-startup stderr |
|--------|--------------------------|----------------|
| `fake` (`--backend fake`) | Disabled — a fresh empty store is reseeded for every request, so there is nowhere to leave a claim; the header is ignored and every request just runs. A value over 255 bytes is still rejected with M23 (400) | One line, `lnpl serve: Idempotency-Key support is disabled ...` (D11) |
| `sqlite:<path>` (`supports_idempotency()` True) | Exactly the contract above — claim, replay, M17 | None |
| A driver that does not implement the three claim methods (`supports_idempotency()` False — currently `lnpl-postgres`, until lnpl-postgres#8) | Rejected — 501 `idempotency-unsupported` (M22). Neither claims the key nor runs the workflow. A request with no header still runs | One line, `lnpl serve: repository driver <module.qualname> -- idempotency: unsupported ...` (see Operational surface below) |

501 carries exactly the meaning of RFC 9110 §15.6.2 — the server does not support a
feature needed to fulfill this request. The Idempotency-Key draft does not specify the
response of a server with nowhere to store the key. The 501 body's `detail` names the
driver as `<module>.<qualname>` and states what the operator should do (install or
upgrade a driver that implements it, or resend without the header). The event
consumption route (`POST /-/events/<slug>`) follows the same rule — since that route's
CloudEvents `id` is itself the key, every request on such a driver is E8 (501).

## `ETag` / `If-Match` (issue #113)

A `GET /<service-slug>/<entity-slug>/{id}` response carries a `_version`-based
**weak** validator (`W/"<n>"`) as its `ETag` — it is weak because this server does not
guarantee that the masked JSON body is byte-identical on every code path (RFC 9110
§8.8.1, an honest choice).

When a state-changing workflow (`POST`) carries `If-Match`, it is compared against
the stored version of the entity **that workflow `read`s first** — a workflow endpoint
has no single target resource the way REST's PUT/PATCH does, so the row that produced
the prior GET's ETag is used as the baseline. If that read uses `by <ref>` (RFC-0052),
the key is also resolved to the value that read actually uses — it is not pinned to
the payload's `id`. A mismatch → 412 (M19). If the lookup key itself cannot be
evaluated ahead of time from this request alone (the reference points at a binding or a
network result, or that value is absent from this request), the workflow is not run and
it is rejected with 400 (M20) — a condition that cannot be evaluated is never let
through silently. If the key was evaluated but no row exists for that key, it answers
412 (M21) — a request that expects "a row of this version" finding no row at all is a
false condition. There are exactly two cases where the check is skipped: a workflow
with no read step at all, and a driver that does not emit `observed_version` (the
`fake` backend is one, an opt-in like D12).

| # | Observed condition | HTTP | error `code` |
|---|-----------|------|--------------|
| M18 | `If-Match` value is not this server's ETag format (malformed) | 400 | `precondition-invalid` |
| M19 | `If-Match` present and a row to condition on exists, but it mismatches the stored version | 412 | `precondition-failed` |
| M20 | `If-Match` present and the first read's lookup key cannot be evaluated ahead of time from this request alone (the reference points at a binding or a network result, or that value is absent from this request) | 400 | `precondition-unsupported` |
| M21 | `If-Match` present and the lookup key was evaluated, but no row exists for that key | 412 | `precondition-failed` |

Evaluation order: authentication (M3/M3a/M3b, already finished before `_respond`) →
M23 (key length, right after M4/M5 and before opening the driver) → M22 (idempotency
unsupported, only when `Idempotency-Key` is present) → the idempotency claim
(M17/replay) → M18 (format) → M20 (lookup key not evaluated) → M21 (no row) → M19
(version mismatch) → the workflow runs. M21 comes before the 404 (M8b) the same
request without `If-Match` would get.

With no `If-Match`, nothing changes from today (no regression). `If-None-Match`/304
is out of scope — the issue does not require it.

## Schedule triggers (issue #81)

`event ... on schedule` reaches only the IR and the OpenAPI `x-lnpl-schedules` and
has no executor (RFC-0016). A built-in cron was rejected by design — instead, three
trigger surfaces are exposed for an external scheduler (cron/systemd) to call
directly:

- **The trigger route** — `POST /-/schedules/<event-slug>`. It does not ride on the
  OpenAPI contract (a schedule is `x-lnpl-schedules` metadata, not an operation) — it
  instead runs through **exactly the same code path** as the workflow routes
  `build_routes` builds: the same M1-M9 mapping, the same `_check_auth` (M3/M3a exactly
  as-is if the service that event belongs to declares `security jwt`), the same
  `skipped[]` observability, the same JSON access log (#78) — it creates not a single
  new verdict.
- **`lnpl trigger <src>... --schedule <event-id>`** — a one-shot CLI path that opens
  no socket. It is the same mode A execution as `lnpl run`, differing only in that the
  workflow is chosen by the schedule event's link instead of `--workflow`. Success is
  rc 0, a failed execution is rc ≠ 0 — cron can use this directly as the verdict.
- **`lnpl schedules <src>... --format crontab|systemd`** — builds a single crontab
  line, or a systemd `.timer`+`.service` pair, from the `x-lnpl-schedules` metadata.
  The output is generated, not meant for hand edits (stated in its header).

**Trigger token (issue #236).** `lnpl token <src> --path /-/schedules/<event-slug> --subject <누구> --secret-env LNPL_JWT_SECRET [--role <역할>] [--ttl 5m]`
issues a token for this route. The audience (aud) is `-` — every path under `/-/`
shares that same value, so this token also works on another `/-/schedules/`·`/-/events/`
route with a matching role, and does not work on a `/<service>/<workflow>` route. The
CronJob from `lnpl generate k8s` makes a 5-minute token with this command on every run
(`docs/backends.md` section 12).

**Event→workflow linking.** A schedule event belongs to no workflow in the IR
(`lower.py`'s `owner_of` is workflow-only). The trigger surface applies exactly the same
rule a workflow already uses — "the nearest preceding `service` declaration" (RFC-0002
A.2 R2) — over the compiled document's `line` field, and picks that service's one
workflow child as the target. **If it is not exactly one** (no preceding service, or
that service has 0 or 2+ workflows), it is rejected with `ServeError` **at startup** —
it never guesses. `lnpl serve` validates every schedule event in the document at once,
and `lnpl trigger` validates only the one it was asked for.

## Event consumption (`consume by`, issue #118)

The publish side (`emit`/`publish` → `lnpl_outbox`, issue #102) existed, but the
consume side — the path by which an event actually wakes a workflow — did not.
`event <E> subscribe` (issue #103) only **emits** SSE to an HTTP client; it runs no
workflow. `event <E> consume by <Workflow>` is the opposite side: on arrival, it runs
`<Workflow>`. Both clauses can sit side by side on the same `event` declaration and are
not mutually exclusive — the comparison table below.

| Clause | Meaning | Route | Auth |
|----|----|--------|------|
| `subscribe` | **Emits** SSE to an HTTP client | `GET /<svc>/events/<slug>` | The service of the workflow that `emit`s the event |
| `consume by <W>` | **Runs** `<W>` on arrival | `POST /-/events/<slug>` | The service that owns `<W>` |

**Route** — `POST /-/events/<event-slug>`. It shares the same reserved namespace and
the same merge order as `/-/schedules/<slug>` (issue #81) — joining **after**
`build_routes`'s OpenAPI contract check, since CloudEvents ingestion is this server's
own contract, not an operation — but its execution path differs from the schedule
trigger: instead of riding the workflow POST's M1-M9 mapping, it uses its own 3-way
mapping below (D7) — because what a relay must mechanically decide, retry or
dead-letter, is not "what did this caller do wrong" but "may this envelope be pushed
again".

**Envelope (D5)** — accepts only structured-mode CloudEvents v1.0. `specversion`
(fixed `"1.0"`), `id`, `source` and `type` must be non-empty strings. `type` is
**not** checked against the event name — the slug is already the routing key, and
that check being the relay's job is a deliberate simplification. When
`datacontenttype` is present, only `application/json` is accepted (any parameter
after `;` is ignored); any other value, or `data_base64` (binary mode), is rejected.
`data` defaults to `{}` and becomes this workflow's input payload (D6).
`id` is the idempotency key and goes directly into the `lnpl_idempotency
(workflow_id, key)` index, so it has the same 255-byte ceiling as M23 (E9) — the length
is the byte count of the JSON string value encoded as UTF-8. The CloudEvents spec sets
no maximum length for `id`, so this ceiling is a consumer-side policy.

| # | Observed condition | HTTP | error `code` |
|---|-----------|------|--------------|
| E1 | Any of `specversion`/`id`/`source`/`type` is not a non-empty string, or `specversion != "1.0"`, or `id` is a string that cannot be encoded as UTF-8 (an unpaired surrogate escape such as `\ud800`, issue #261) | 400 | `cloudevents-invalid` |
| E2 | `datacontenttype` is present but is not `application/json`, or `data_base64` is present (binary mode) | 400 | `cloudevents-invalid` |
| E3 | `data` is present but is not a JSON object | 400 | `cloudevents-invalid` |
| E4 | Already running under the same `id` (the same conflict signal as #113) | 409 | `idempotency-in-progress` |
| E5 | Execution completed | 200 | — |
| E6 | Execution fails — a deadline is exceeded, or the failed step's effect is `RepositoryCall`/`NetworkCall` (a `DriverError` family), or an optimistic version write conflict (`failure_kind == "write-conflict"`, issue #201 — this applies even when the failed step is `set` and its effect is `Assignment`) — transient, the relay should retry | 503 + `Retry-After: 1` | `event-retry-later` |
| E7 | Execution fails — everything else (a `Validation` rejection, an explicit business/guard `RunError` — an author-declared `fail <code>`, `failure_kind == "rejected"`, RFC-0056 —, a create collision, `not-found` — a read miss on a persistent backend (issue #197) or a 0-row `update`/`delete` (issue #215), a create with no `id`, `id-required` (RFC-0055)) — permanent, replaying the same payload gives the same result | 422 | `event-rejected` |
| E8 | The repository driver's (`RepositoryDriver`) `supports_idempotency()` is False — since the CloudEvents `id` is itself the idempotency key, this applies to every request on this route. Judged right after the envelope check (E1-E3) and before E4; neither claims the key nor runs the workflow | 501 | `idempotency-unsupported` |
| E9 | The CloudEvents `id` exceeds 255 bytes (UTF-8 encoded) (issue #261) — rejected right after the envelope check (E1-E3), before E8 and E4, and before the repository driver is opened, so it neither claims the key nor runs the workflow. The same on every backend, including `fake` | 400 | `cloudevents-id-too-long` |

**Idempotency (D6)** — the CloudEvents `id` is the idempotency key. It reuses
`lnpl_idempotency` (issue #113) **as-is** — no second store is built. Since 200 and 422
are deterministic outcomes, they are finalized with `idempotency_finish`, so a
redelivery of the same `id` replays the first response instead of running the
workflow again. 503 is **deliberately not finalized** — finalizing it would make #113
replay 503 forever for that key, so the relay could retry forever and the workflow
would never run again (that squarely breaks the intent of D7). Instead, on a 503
(whether on the normal branch or a path where an exception `run_workflow` did not
catch escaped), the claim is cleared with `idempotency_release`, so the next
redelivery of the same `id` runs fresh right away (D6 r2). On the exception path the
workflow transaction may still be open, so it is closed with `rollback()` first and
only then released (issue #258) — this way the release runs on the driver's own
connection, and the failed execution's partial write is never committed together with
the release. If even that `rollback()` fails, the claim is not released — since that is
better than committing a partial write, that `id` gets E4 (409) until the TTL ends.
Even if `idempotency_release` itself fails with a `DriverError` (issue #261), the
response is still the same 503 `event-retry-later`, and the claim stays unreleased, so
that `id` gets E4 (409) until the TTL ends — stderr carries the original failure's
traceback and one release-failure line under the same `correlation_id`.
The `fake` backend (no idempotency store) runs independently every time (same existing
rule as D9/D11). On a driver that does not implement the three claim methods
(`supports_idempotency()` False), it is rejected right after the envelope check with
E8 (501 `idempotency-unsupported`) and not run (issue #228). The reference relay
`lnpl relay` treats 501 as an unexpected state and resends it on the next drain without
acking.

**Reference relay — `lnpl relay`.** A minimal implementation connecting
`lnpl outbox drain` (publish) and this route (consume). `--target http(s)://...`
exercises the contract between two instances with no broker dependency (byte-identical).
When `--target` is a different scheme, it publishes through a registered
`lnpl.publishers` driver (issue #191, RFC-0061, `docs/backends.md` §15) — this section
(the consume-side contract) does not change. For the detailed ack discipline, see
`lnpl relay --help` and issue #118 D8.

## Contract limits (what this server is not)

- **The capability backend defaults to fake.** Started with no flag, storage is an
  in-memory `FakeRepository` reseeded per request, and no state survives between
  requests — exactly as #26 shipped it. Given `--backend sqlite:<path>`, it becomes a
  real persistent store that opens and closes its own connection per request, and
  **state survives between requests**. The contract is in `docs/backends.md`.
- **What 401 means depends on whether a provider is configured.** Started with
  neither `--jwt-secret-env` nor `--token-provider`, it is only a **presence check**
  of the `Authorization` header (presence-checked, not verified) — any value passes.
  Given one, M3a comes alive and fully verifies the signature, `exp`/`nbf` (60-second
  leeway), and `iss`/`aud`/`typ`, and a failure is 401 `auth-invalid`. Which check
  broke is not carried in the response — that is exactly the feedback someone polishing
  a forgery would want, so it goes out only via server stderr alongside the correlation
  id. A token for the built-in `hmac` provider is issued by `lnpl token` (`--jwt-issuer`
  can change the expected `iss`, issue #119b); a token for an external SPI provider
  chosen with `--token-provider` is issued by the real IdP that provider verifies —
  `lnpl token` still only issues for the built-in `hmac`.
- **There is no built-in scheduler (a cron loop)** — this server runs no timer of
  its own. Actually honoring the time/period declared by `event ... on schedule` is
  still the job of an external scheduler (cron/systemd) the operator attaches — see the
  "Schedule triggers" section below, issue #81. There is also no mode B (native)
  serving.
- **WebSocket is explicitly deferred in this issue (#103).** SSE is a one-way HTTP
  stream, so it can be implemented with the stdlib alone (a WSGI iterator — `wsgiref`
  for the dev server, any WSGI host such as gunicorn in production), but WebSocket needs
  an external dependency for its protocol upgrade and framing, which conflicts with the
  stdlib-only principle.
  If client→server two-way demand is ever filed as a real issue, an external gateway
  pattern (AWS-Step-Functions-style: delegate to API Gateway WebSocket + a task token
  callback) is examined first, before adding ws syntax to the language.
- The request's `Content-Type` header is not checked — the verdict comes from
  whether body parsing succeeds.

## Operational properties

- Concurrency (dev server): thread-per-request (`wsgiref.simple_server` +
  `ThreadingMixIn`, mirroring the same combination as
  `http.server.ThreadingHTTPServer` exactly, with `WSGIServer` in place of
  `HTTPServer`). Each request builds a fresh interpreter and repository rows, so
  isolation needs no lock. The only shared state is the compiled document, the
  routing table, and the token provider, and all of it is read-only — this property is
  byte-identical to before issue #80 (a reorganization, not a redesign).
- With a real backend: each request opens **its own connection** (a `sqlite3`
  connection is bound to the thread that created it) and closes it in a `finally` —
  the close happens **after** writing the response, so the server may still be
  cleaning up at the moment the client receives the response.
- The postgres backend's sustained-load ceiling has been measured and root-caused —
  this property of opening a new connection per request can lead to accumulating
  latency (queue collapse) under high load:
  [docs/postgres-load-ceiling.md](postgres-load-ceiling.md).
- Shutdown (dev server): SIGINT (Ctrl-C) → closes the socket and exits rc 0. **TLS
  termination and worker pool management are still not the dev server's
  responsibility** — the WSGI host + nginx in the "Production deployment" section below
  own that. SIGTERM is different (issue #148, D2 overturns issue #110's D4 in this one
  respect): in addition to immediately flipping `/-/readyz` to 503 (issue #110, see the
  "Operational surface" section below), this module itself performs a graceful drain
  and then exits — see the "SIGTERM graceful drain" section below.
- An SSE subscription (#103) is especially heavy under the thread-per-request/worker
  model — it keeps holding that worker for as long as the connection stays open. It
  polls `lnpl_outbox` on `wsgi.SSE_POLL_INTERVAL_S` (default 0.2s), and if no new row
  appears for `wsgi.SSE_IDLE_TIMEOUT_S` (default 30s), the WSGI iterator ends itself
  (`StopIteration`) — a ceiling so a slow or dead subscriber cannot pin a worker down
  forever. (`lnpl.serve` re-exports the same names, but the module global the loop
  actually reads is `lnpl.wsgi`'s — to shrink the value in a test you must patch
  `wsgi.SSE_POLL_INTERVAL_S`.)
- Per-request diagnostics (guard skips, etc.) go out via stderr, the same channel as
  the CLI.

## Operational surface — `/-/healthz` / `/-/readyz` / `/-/metrics` (issue #110)

Issue #87 built even the container (`examples/deploy/Dockerfile`), but there was no
k8s probe to attach — during a rolling update, traffic went to a pod that was not yet
ready. All three routes are built by `build_ops_routes`/`build_metrics_route` in
`impl/lnpl/wsgi.py`, and `make_wsgi_app` merges them in with `routes.update(...)`
**after** `build_routes`'s set-equality check (the same kind of contract as D1 in the
"Status code mapping table" section above, `set(routes) == contract`) — at exactly the
place and in exactly the way `/-/schedules/...` (issue #81) already established.
**`/-/` paths are excluded from that check** (pinned by a test,
`impl/tests/test_ops_surface.py`) — they were never part of the route set OpenAPI
defines, so it should not be read as the check "missing" them; it means this check was
never looking at them in the first place.

**All three are exempt from authentication** — reachable with no token even if some
service declares `security jwt`/`security role`. kubelet's liveness/readiness probes do
not carry an `Authorization` header, so landing a 401/403 here would leave the pod that
service lives on permanently unready.

### `/-/healthz` — liveness

Checks only that the process is alive and this document loaded. **It touches
neither storage nor the network** — the check ends with 100 itself, and
`repository_factory` is never called even once (`impl/tests/test_ops_surface.py`
asserts a call count of 0 with a recording driver). The reason no backend check goes
into liveness is a failure mode reference material warns about repeatedly: if the DB
dies for 30 seconds, liveness dies right along with it and k8s restarts that pod — but
a restart cannot fix the DB and only adds one more outage. Backend availability is
readyz's job below.

`/-/healthz` is **unaffected** even on SIGTERM — if liveness restarted a pod that is
shutting down, a rolling update/drain would break.

### `/-/readyz` — readiness

Looks only at a closed list of five (never grown arbitrarily):

1. Whether the routing↔OpenAPI check passed — `build_routes` already judged this at
   startup (had it failed, `ServeError` would have kept it from starting in the first
   place, so this app's very existence is proof it passed).
2. If a persistent backend (`--backend sqlite:...`) is configured, it acquires and
   releases a connection once. On that same connection it also reads the driver's
   `supports_idempotency()` and carries it in the 200 body's `capabilities` (issue
   #228) — this is data, not a check item. It is still 200 even when False.
3. If `--jwt-secret-env` is specified, whether that environment variable is **still**
   set — separate from the startup verification (`cli.cmd_serve`), it is read again on
   every probe (so the rare drift of that variable disappearing while the process is up
   is also caught by the next probe). It runs exactly the same way on the
   `build_app()` (gunicorn) path — it checks when a name is given via
   `LNPL_JWT_SECRET_ENV` (or the `jwt_secret_env` argument), and passes with nothing
   to check when none is given (issue #187).
4. If `--network http` is used, whether every logical-name endpoint mapping is
   resolved — for the same reason as (1), this exposes a fact already judged at
   startup.
5. `secret-provider` — runs only when the JWT secret's source is an `lnpl.secrets`
   provider (issue #192). The probe re-reads the current key + the previous key from
   the provider — exactly the read verification relies on. But if the last read
   (whether it succeeded or failed) is more recent than 5 seconds
   (`READYZ_REFRESH_FLOOR_S`), the provider is not called and that read's result is
   reported as-is — since readyz has no authentication and is also exempt from
   `--rate-limit`, this is a floor that limits reads to once per 5 seconds per worker
   even if probes are sent repeatedly (half of kubelet's default 10-second probe
   period, so a real probe reads every time). On failure it carries
   `secret-provider` in a 503 and keeps using the last key that was good, and once the
   floor has passed, the next probe that reads successfully installs the new key and
   returns to 200. The body carries only the check's name.

SIGTERM is checked **before** these five — the instant it is received, it is 503
with no further checks. If all pass, 200
`{"status": "ok", "capabilities": {"idempotency": <bool>}}`; if even one breaks, 503 +
`application/problem+json` (`code: "not-ready"`) carrying the **names of the broken
checks** as `checks`. This is the opposite judgment from 401/403 (M3/M3a/M3b above) —
since readyz is for operators, not an attack surface, which check broke is never
hidden.

```jsonc
// 예: 백엔드 커넥션 획득 실패 + jwt-secret-env 미설정, 둘 다
{"title": "the server is not ready to receive traffic", "status": 503,
 "code": "not-ready",
 "detail": "readiness check(s) failed: repository, jwt-secret-env",
 "checks": ["repository", "jwt-secret-env"]}
```

**Capability exposure and the startup line (issue #228).** `capabilities.idempotency`
is `true` only when the repository driver's `supports_idempotency()` is True — with no
persistent backend (`fake`), it is `false`. Lacking the capability is a static fact
that waiting or restarting cannot change, so it is not a readiness failure: 200 stays
200, the closed list of five does not grow (`capabilities` is not a `checks` name), and
the 503 body does not change either. The same fact is also announced once at startup —
`make_wsgi_app` (both `lnpl serve` and `build_app()` go through it) opens one
repository, reads the capability, closes it, and if the capability is absent prints one
line to stderr:

```text
lnpl serve: repository driver <module.qualname> -- idempotency: unsupported (it does not implement idempotency_begin, idempotency_finish and idempotency_release); requests carrying Idempotency-Key are refused with 501 idempotency-unsupported
```

`fake` has no such line (the D11 warning above already covers it). If gunicorn calls
`build_app()` per worker with no `--preload`, one line is printed per worker.

**Never mix liveness and readiness.** A failure whose answer is a restart (the
process is broken) goes to healthz, and a failure that only needs traffic cut off
(backend/config drift) goes to readyz — merging the two into one either fires a
restart when cutting traffic would have been enough, or keeps letting traffic flow in
when a restart is what is actually needed.

### `/-/metrics` — RED signals (`--metrics`, default off)

Started with no `--metrics`, `/-/metrics` is not in the routing table at all — **it
is 404, not a "disabled" body**. Turned on, it emits the metrics below in the
Prometheus text exposition format (including `# HELP`/`# TYPE`):

| Metric | Kind | Labels |
|---|---|---|
| `lnpl_workflow_runs_total` | counter | `service`, `workflow`, `status` |
| `lnpl_workflow_duration_seconds` | histogram | `service`, `workflow` |
| `lnpl_step_failures_total` | counter | `service`, `workflow`, `step`, `kind` |
| `lnpl_http_requests_total` | counter | `route`, `method`, `status` |
| `lnpl_http_request_duration_seconds` | histogram | `route` |
| `lnpl_cache_ops_total` | counter | `op`(`get`/`set`/`invalidate`), `result`(`hit`/`miss`/`ok`/`error`) |
| `lnpl_idempotency_claims_total` | counter | `status`(`started`/`in-progress`/`done`/`unsupported`/`other`) |
| `lnpl_outbox_undelivered` | gauge | None — only when the driver implements `outbox_undelivered_count()` (the built-in sqlite does) |
| `lnpl_driver_<name>` | gauge | None — one per entry of the dict the driver's optional `metrics()` hook returns |

**The cardinality contract (D8, revising D7 in issue #237).** Issue #110's D7 was
"no new label axis". As a result, not one response that ends outside a workflow
(401/403/404/409/412/429) was ever counted, and a per-route SLO dashboard or alert
could not be built. The revised rule is this: **a new label axis is allowed only when
every one of its values is a closed set the server itself decides.** `route` is a
declared route key (the single-GET template is `/<svc>/<entity>/{id}`), and any path
that matches no route is folded into one fixed value, `unmatched`. `method` is one of
RFC 9110's nine methods or `other`, `status` is a status code this server emits, and
`op`/`result` and the idempotency `status` are fixed words. So the number of label
combinations is proportional only to the number of declared routes, and incoming
requests cannot grow it. **A raw path, an entity id, `correlation_id`, or a payload
value still cannot become a label** — unbounded cardinality would bring down Prometheus
itself. `interp.Trace.metric`'s label allowlist (`{module, service, workflow, step,
kind}`, RFC-0003) is unchanged, and a label outside it is still a `RunError`.
`lnpl_driver_<name>` emits only the entries whose full name matches the Prometheus name
grammar `[a-zA-Z_:][a-zA-Z0-9_:]*`, and skips only that entry for a value that is not
numeric (including a boolean) or not finite. If a hook or
`outbox_undelivered_count()` raises, only that metric is dropped and the scrape is
still 200. The stderr line (`serve: metrics: <source> failed (...)`) prints at most
once per UTC day for the same content.

**Where it accumulates (D9).** `interp.Trace.metrics` (a fresh array per request,
the `--trace-exporter`/issue #78 contract) is left untouched. Alongside it, the
already-computed result is read when the request ends and added to a
**process-level** store (`wsgi.MetricsRegistry`, which survives between requests) —
the two channels are independent, so turning one off does not change the other.
Workflow metrics are still added in `LnplWsgiApp._respond`. HTTP metrics are recorded
exactly once per response, in `LnplWsgiApp._finalize_response` — this includes a
429/503 that ends before dispatch, an exception during processing (counted as 500), and
SSE (when the stream ends or closes). `/-/healthz`·`/-/readyz`·`/-/metrics` requests
are counted too, but a scrape does not carry its own request (it is recorded after the
body is built). The two gauges each open one repository, read, and close it on every
scrape. Every update is protected by a single `threading.Lock` (D10) — since the dev
server is thread-per-request, a lock-free `+=` would lose updates under concurrent
requests.

This is the PromQL for the error rate and p95 latency — the full dashboard example
is `examples/deploy/grafana-red-dashboard.json`.

```promql
sum by (route) (rate(lnpl_http_requests_total{status=~"5.."}[5m]))
  / sum by (route) (rate(lnpl_http_requests_total[5m]))
histogram_quantile(0.95, sum by (le, route) (rate(lnpl_http_request_duration_seconds_bucket[5m])))
```

**This can also be turned on via the `build_app()` path (issue #187).**
`--metrics`, `--trust-incoming-trace`, and readyz check ③ (re-confirming
`--jwt-secret-env` is alive) existed only on the `lnpl serve` path — now
`build_app()` (production deployment, gunicorn) accepts the same things:
`LNPL_METRICS`, `LNPL_TRUST_INCOMING_TRACE`, and check ③ when `LNPL_JWT_SECRET_ENV`
is given (the environment variable table in the "Production deployment" section
below). `impl/tests/test_build_app_serve_parity.py` enforces that every `serve`
option either has a `build_app()` counterpart or states why it has none — adding a
new `serve` flag with no counterpart fails that test. `/-/healthz`/`/-/readyz`
themselves come up the same way on the `build_app()` path too — both are built by
`build_ops_routes`, which unconditionally joins in inside `make_wsgi_app()` (above).

## Rate limit — `--rate-limit` (issue #148)

`--rate-limit N` (default: unset = unlimited, the behavior before issue #148) — one
process-global token bucket, `rate == capacity == N` (N per second, bursts up to N too).
With K instances (or gunicorn workers), the real allowance loosens to N × K, and there
is no per-client limit at all — **linkly provides only a single-instance line of
defense**, and that is this project's official position (issue #194). Both a global
limit and a per-client limit are the gateway's job — nginx `limit_req` (official docs:
https://nginx.org/en/docs/http/ngx_http_limit_req_module.html, a reference config is at
`examples/deploy/nginx.conf`), a cloud API gateway, etc. A shared-store-based
distributed limit (#143, using the redis cache driver as a counter) was examined but
not adopted — this in-process bucket is only a minimal line of defense for a
single-instance deployment with no gateway in front.

**Every `/-/` path is exempt** — a k8s probe must never get a 429 (the same reason
as the "Operational surface" section above).

On exceeding it: `429` + `Retry-After: <N>` (integer seconds,
`ceil(부족 토큰 / rate)` — the ceiling of tokens short divided by rate) +
`application/problem+json` (`code: "rate-limited"`).
`429` + `Retry-After` follows RFC 6585 §4's recommendation (RFC 6585, *Additional HTTP
Status Codes*, https://datatracker.ietf.org/doc/html/rfc6585 — "MAY include a
Retry-After header indicating how long to wait before making a new request").

```jsonc
{"title": "rate limit exceeded", "status": 429, "code": "rate-limited",
 "detail": "rate limit exceeded, retry after 1s"}
```

## SIGTERM graceful drain — `--grace-period` (issue #148)

Issue #110 (D11, D4) treated SIGTERM only as a flag for `/-/readyz` 503, leaving the
actual drain and shutdown as "not the dev server's job". Issue #148 narrows that
boundary in exactly one respect, the drain — `lnpl serve` itself now:

1. Immediately on SIGTERM: `/-/readyz` 503 (issue #110, unchanged).
2. A new request other than `/-/` touches none of routing, auth, or workflow
   execution and is immediately rejected with `503` + `Retry-After: 1` +
   `application/problem+json` (`code: "shutting-down"`) — the same pattern as k8s
   apiserver's `shutdown-send-retry-after` option (reject the request during the drain
   window and give `Retry-After`, kubernetes/kubernetes#101257,
   https://github.com/kubernetes/kubernetes/pull/101257), but a different status code —
   apiserver uses `429`, while here it is `503`. That is because the accurate meaning
   is not "this one request comes too often" (what 429 means) but "this server instance
   itself is not taking traffic" — the same judgment as the `event-retry-later` 503
   precedent in issue #118 (the "Event consumption" section above).
3. A request already in flight (WSGI entry through exit) keeps being processed. The
   server actually stops (`server.shutdown()`) at whichever condition comes first —
   that count reaching 0, or `--grace-period` seconds passing (default 30 — matched to
   gunicorn's default below) — and leaves one stderr line distinguishing which one it
   was, the drain finishing or the grace period running out.

```jsonc
{"title": "the server is draining connections before shutdown", "status": 503,
 "code": "shutting-down",
 "detail": "the server is shutting down; retry against another instance"}
```

**A gunicorn deployment needs no code change** — `graceful_timeout` (default **30
seconds**, from gunicorn's official docs at
https://gunicorn.org/reference/settings/: "Generally, the default of thirty seconds
should suffice") already gives a worker time to finish an in-flight request after
SIGTERM. `--grace-period`'s default of 30 is matched to this so the gunicorn path and
the dev-server path do not answer the same-named question — how long to wait after
SIGTERM — with two different, unrelated numbers.

## Observability — `--log-format` / `TraceExporter` (issue #78)

With only human-oriented stderr text, a collector cannot pull out `correlation_id`
as a field (the text diagnostics `format_lines` produces are for grepping, not
parsing). This section opens that channel — while leaving the default `text` output's
bytes untouched.

### Access log — `--log-format`

- `text` (default): no access log. Byte-identical to before issue #78 — per-request
  diagnostics such as a guard skip still go out via stderr through `format_lines` (the
  "Operational properties" section above, unchanged).
- `json`: one JSON line to stderr per request (`json.dumps(..., ensure_ascii=False)`).
  Fields:

  | Field | Meaning |
  |------|-----|
  | `correlation_id` | For a request where a workflow ran, **the same** id as the response body (not re-minted separately); for a pre-execution rejection (404/405/401/413/400), an id minted just for this request |
  | `method` / `path` | `REQUEST_METHOD` / `PATH_INFO` |
  | `workflow` | The workflow node id for a POST workflow request, else `null` (GET single/list/SSE/rejection) |
  | `status` | The HTTP status that went out as the response — the same value as the mapping table above (M1-M16) |
  | `duration_ms` | Total time spent processing the request (rounded to 3 digits) |
  | `skipped` | `result["skipped"]` as-is (`[]` for a non-workflow request) |
  | `diagnostics` | `diagnostics.to_records(interp.diagnostics)` (reuses the existing diagnostic record — no new serialization is invented; `[]` for a non-workflow request) |
  | `trace_id` / `span_id` | The value `_resolve_trace_context` decides from the inbound `traceparent` (adopted only when `--trust-incoming-trace` is on; freshly minted otherwise) (issue #123) |

  Since an SSE subscription is a stream and `duration_ms` must point at the whole
  time the connection stayed open, the one line goes out not at connection time but
  **when the stream ends** (a normal exhaustion, an idle timeout, or a `GeneratorExit`
  from the client closing the connection).

  **Trace propagation scope (issue #123, D1/D3/D6).** `trace_id`/`span_id` are carried
  on the canonical line for all four served paths (workflow POST, GET single, GET list,
  SSE subscription) — but **only when `--log-format json`**: `text` mode has no
  canonical line at all, so it is out of scope (a workflow POST still resolves its own
  trace for `Trace`, but that value simply has nowhere to go in the log). GET/SSE build
  no `Trace` object — the id is carried only on this log line and never appears in
  `--trace-exporter` output (option 2 was not chosen). `_resolve_trace_context` is
  called exactly once per request — a workflow POST receives the JSON log path's
  (`_call_with_json_log`) single resolution as an argument into `_respond`, and only in
  `text` mode does `_respond` fall back to resolving it itself.
- Every channel where a payload/field value could end up on a log line receives only
  values that have already passed the existing `mask_payload` checkpoint — no second
  masking rule is invented (the items above are themselves non-sensitive metadata like
  correlation_id/status/time, and `skipped[].evaluations` carries only values
  `interp.py` has already masked).

### `TraceExporter` — exporting completed requests' traces

`--trace-exporter` is **independent** of `--log-format` — Trace alone can be
exported without turning on the access log. Every time a workflow completes (whether
it succeeds or fails), `interp.Trace.to_dict()` (`{"correlation_id", "span",
"metrics", "logs"}`, the step span tree already existed) is handed to exactly one
hook:

```python
class TraceExporter:
    def export(self, trace_dict):
        raise NotImplementedError
```

There is one built-in implementation, `stderr-json` — it `json.dumps`es exactly
what `export()` received and writes one line to stderr. A GET single/list/SSE request
never builds an `Interpreter`/`Trace` at all, so the exporter only reacts to workflow
requests.

#### Registration

A name outside the built-ins is looked up in the `lnpl.exporters` entry-points
group — the same shape as `lnpl.drivers` (issue #75, `docs/backends.md` §8):

```toml
# lnpl-otel 자신의 pyproject.toml
[project.entry-points."lnpl.exporters"]
otlp = "lnpl_otel:make_exporter"
```

`make_exporter` must be a factory called with no arguments (if it is a class, its
constructor takes no arguments), and its return value must subclass `TraceExporter`
and implement `export(trace_dict)`.

A real example of this shape is [`lnpl-otel`](https://github.com/choiyounggi/lnpl-otel)
(issue #144) — a `TraceExporter` registered as `otlp = "lnpl_otel:make_exporter"`
that refuses to start with `ExporterError` if `OTEL_SERVICE_NAME` is absent, sends
completed workflow traces over OTLP, and whose own Testcontainers CI verifies grpc and
http ingestion separately against a real otel-collector (the canonical span↔OTel
semconv mapping is that repo's `docs/semconv-mapping.md`).

#### The built-in scheme is never shadowed

`stderr-json` is matched by a string comparison before any entry-points lookup —
even if an external package registers the same name, it is never run (the same order
`open_repository` uses to protect `fake`/`sqlite`).

#### Diagnostics for an unregistered name

If `--trace-exporter jaeger` is given but no package has registered that name, a
`ValueError` goes out carrying the value received and the full list of
built-in/registered names, and the CLI path translates it to rc 2
(`cli._open_trace_exporter`).

#### entry-point load failure

If it is registered but `entry_point.load()` fails (a missing module, an import
error, etc.), it is translated into a single `lnpl.wsgi.ExporterError` — the causing
exception is attached as `__cause__` (the same "errors go out as one kind" principle as
the driver path's `DriverError`).

### Audit trail — `--audit-sink` (issue #241)

Given `--audit-sink` (environment variable `LNPL_AUDIT_SINK`), an audit record is
left one line at a time, **separate** from the access log. It is independent of
`--log-format` (it is still left even in text mode).

**What gets left.** Only these two things:
- Every POST to a `workflow`·`event-consume` route — regardless of the outcome
  (200, 400, 401, 403, 404, 409, 412, 413, 422, 429, 500, 501, 503, 504, including an
  idempotency replay)
- Any other request that ends in 401 or 403

A successful read (GET 200, SSE), an unmatched path (404), 405, and
`/-/healthz`·`/-/readyz`·`/-/metrics` are not left. The judgment is made by route kind,
not by path prefix.

**Fields.** The canonical reference is `schemas/audit-record.schema.json` (draft
2020-12, `additionalProperties: false`, every key required — an unknown value is
`null`).

```json
{"record_type": "lnpl.audit", "schema_version": 1,
 "timestamp": "2026-01-02T03:04:05.006Z",
 "correlation_id": "req-000000000001", "trace_id": null, "span_id": null,
 "actor": {"subject": "alice", "role": "clerk"},
 "action": {"method": "POST", "route": "/order-service/approve-order",
            "kind": "workflow", "workflow": "wf.approve.order"},
 "resource": [],
 "outcome": {"status": 403, "code": "forbidden", "failed_step": null, "replay": false},
 "duration_ms": 1.234}
```

- `timestamp` — wall-clock UTC (`time.time()`), milliseconds. Not a virtual clock.
- `correlation_id` — that execution's id if there was one, else the response body's
  id, else the JSON access log line's id, and `null` if none of the three exist.
- `actor` — the verified token's `sub`/`role` (`caller_view`). Carried on a 403
  too. `null` on a 401, on a route with no authentication, or in a deployment with no
  token verifier. The token string and the `Authorization` header are never carried.
- `action` — the method, the route template (not the concrete URL), the route
  kind, and the workflow node id.
- `resource` — `{entity, op, key}` in the order the execution actually made its
  repository calls. `op` is `read`/`create`/`update`/`delete`/`query`/`persist`, and
  `query`'s `key` is `null`. A read the cache answered is still left as `read`. A
  failed call is left too (the outcome speaks to the result). If the key's source
  field is in the `Password` family, the key is masked as `<entity>#***` (the same
  masking rule; the request body is never carried).
- `outcome` — the status code the client received, `code: "ok"` for 200,
  otherwise the problem body's `code`; `failed_step`; `replay: true` for an idempotency
  replay (in which case `resource` is `[]`).

**Sinks.** Exactly two.
- `stderr-json` — one stderr line per record. stderr is shared with the access
  log, the Trace exporter, and diagnostics, and is not serialized with their
  `print()` calls, so use `file:` when integrity matters. Distinguished by
  `record_type: "lnpl.audit"`.
- `file:<path>` — opened once at startup with `O_APPEND`, mode `0600`. One record
  is one `write()`. When multiple gunicorn workers append to the same file, lines do
  not interleave, but no order is guaranteed across workers. A short write can
  truncate the last line, so a reader should skip a line that fails `json.loads`.

The `lnpl.exporters` entry-point is not used as an audit sink — that group's
`export()` is a contract that receives a Trace dict. A dedicated audit-sink SPI is a
follow-up issue.

**Failure modes.** Startup is fail-closed: for an unknown value, a `file:` with no
path, or a file that cannot be opened, `lnpl serve` stops before opening the port with
`error: ...` and rc 2, and `build_app()` raises `WsgiConfigError`. During request
processing it is fail-open: even if the sink fails, the response (status, headers,
body) does not change, and one line,
`serve: audit sink failed (correlation_id=...): ...`, is left on stderr (if even that
print fails, it is silently skipped).

**Retention, rotation, tamper-resistance.** These are the operator's job. `file:`
does not rotate — use logrotate `copytruncate` or a collector. A hash chain is
**deferred** this time: (a) with N gunicorn workers appending to one file, a single
chain does not hold, (b) a collector can reorder or drop `stderr-json` lines, and (c)
integrity and retention are functions of log management infrastructure (OWASP Logging
Cheat Sheet, NIST SP 800-92). It can be added as an optional field in a later schema
version.

```bash
lnpl serve app.lnpl --audit-sink file:/var/log/lnpl/audit.jsonl
```

### Environment variables (via `build_app()`)

There are two more rows in the table in the "Production deployment" section below:
`LNPL_LOG_FORMAT`, `LNPL_TRACE_EXPORTER`.

## Config file — `lnpl.toml` (issue #114)

`lnpl serve` adds one file to a configuration channel that used to be only CLI
flags and individual environment variables (`LNPL_ENDPOINT_<NAME>`) — a secret
**value** is never carried (exactly the issue #101 discipline): `[*.secrets]` accepts
only the **name** of the environment variable holding that value, or the absolute path
of a file holding that value (`{ file = "..." }`, issue #192).

```toml
# lnpl.toml — 기본 위치는 cwd, --config로 재지정
[default]
backend = "sqlite:./app.db"
log_format = "json"
trace_exporter = "stderr-json"

[default.endpoints]
payments = "https://api.example.com/pay"

[default.secrets]
jwt = "LNPL_JWT_SECRET"          # 값이 아니라 환경변수 이름
# jwt = { file = "/run/secrets/jwt" }   # 또는 파일 원천(이슈 #192)
# jwt = { provider = "vault", key = "kv/app/jwt" }   # 또는 등록된 프로바이더(이슈 #192)

[staging]                        # [default] 위에 얕게(1단) 오버레이
backend = "sqlite:./staging.db"

[staging.endpoints]
payments = "https://staging.example.com/pay"   # payments만 덮는다
```

With no `--profile staging` (or `LNPL_PROFILE=staging`), `[default]` alone applies.
`[<profile>]` is overlaid on `[default]` only **key by key** — only the individual
keys of `endpoints`/`secrets` are overridden, not the whole section, so a key the
profile does not touch still comes down from `[default]` unchanged. There is no
include, inheritance, or conditional.

The `build_app()` (gunicorn) path can also use this file (issue #187): given the
`LNPL_CONFIG`/`LNPL_PROFILE` environment variables (or the `config`/`profile`
arguments), `backend`/`jwt_secret_env`/`endpoints` are overlaid in **exactly the same
way** as `lnpl serve`. There are three differences. First, since this path has no
CLI flags, the table below's first priority is instead `build_app()`'s explicit
arguments and environment variables such as `LNPL_BACKEND`/`LNPL_JWT_SECRET_ENV`.
Second, `lnpl serve` reads `./lnpl.toml` from cwd when `--config` is absent, but
`build_app()` **never reads `lnpl.toml` from cwd on its own** — it reads it only when
`LNPL_CONFIG`/`config` is given explicitly. Third, the file's
`log_format`/`trace_exporter` are not applied on this path — those values are given
via `LNPL_LOG_FORMAT`/`LNPL_TRACE_EXPORTER` (or the `log_format`/`trace_exporter`
arguments). If the file sets either one, `build_app()` announces, in one stderr line
at startup (`lnpl build_app: LNPL_CONFIG sets ...`), the name of the key not applied
and the environment variable to use instead — it never carries the value. Giving only
`LNPL_PROFILE` with no `LNPL_CONFIG` has no effect.

### Precedence (canonical)

When deciding a single value, whichever is present earliest in this list wins:

| Rank | Source | Notes |
|------|------|------|
| 1 | CLI flag (`--backend`/`--jwt-secret-env`/`--jwt-secret-file`/`--log-format`/`--trace-exporter`/`--endpoint`) | |
| 2 | Environment variable (`LNPL_ENDPOINT_<NAME>`) | Today this exists only for the endpoint mapping (the issue #101 contract) |
| 3 | `lnpl.toml` `[<profile>]` | Selected by `--profile`/`LNPL_PROFILE` |
| 4 | `lnpl.toml` `[default]` | |
| 5 | Built-in default | `backend=fake`, `log_format=text`, `trace_exporter`/secret=unset |

When `lnpl.toml` is absent (the default path `./lnpl.toml` does not exist), all
five values resolve byte-identically to before this file existed — the introduction
itself is not a regression. On the other hand, a path named explicitly with `--config`
that does not exist is treated as an operator mistake, rc 2.

Giving both `--jwt-secret-env` and `--jwt-secret-file` (build_app:
`LNPL_JWT_SECRET_ENV`/`LNPL_JWT_SECRET_FILE`, including the arguments) is rejected
with rc 2/`WsgiConfigError`. Giving just one wins over `lnpl.toml`'s
`[*.secrets].jwt` (regardless of its shape). `LNPL_JWT_SECRET_ENV=""` (an empty
string) also counts as "given" — switching to the file side means unsetting that
variable entirely, not emptying it.

### `${VAR}` substitution

Inside a scalar or an `endpoints` string value, `${VAR}` is substituted only as a
pure environment variable reference — an undefined `VAR` is rc 2 along with its key
path. Default-value syntax such as `${VAR:-default}` is not supported (to avoid
opening a hole for writing a secret into the file as a bypass). There is no
substitution at all inside a `[*.secrets]` value — that value must always be the
**name** of an environment variable, and if it does not match the name regex
(`^[A-Za-z_][A-Za-z0-9_]*$`, 64 characters or fewer) (containing a URL, whitespace,
etc.), it is rejected at load time with rc 2.

### `lnpl config check` — pre-startup completeness verdict

```
lnpl config check <src>.lnpl... [--profile staging] [--config lnpl.toml]
```

Pre-judges three conditions that would make `lnpl serve` fail, before it binds the
socket: (a) does every `NetworkCall` logical name in the source have an endpoint
mapping, (b) is the environment variable `lnpl.toml`'s `[*.secrets]` points at
actually set, (c) if `security jwt` is declared, is there a `[*.secrets].jwt`
mapping. If all pass, rc 0; otherwise it lists **every** problem found on stderr and
rc 2 — it accepts no `--endpoint`/`--jwt-secret-env` (it diagnoses only the already
standing lnpl.toml + environment-variable surface, not an on-the-spot override). For
(b), a `{ file = "..." }` entry is checked for whether the file exists, is a regular
file and is readable, is non-empty, and is 65536 bytes or fewer, and for the `jwt` key
it also checks that it is at least 32 bytes (issue #192) — the message carries only
the role name `lnpl.toml secrets.<key>.file`, never the path or the content. A
`{ provider = "...", key = "..." }` entry opens the provider the same way startup
does, reads the current key + the previous key, then closes it — it reports
unregistered/load failure/read failure/a value that is not `bytes`, and for the `jwt`
key it also checks that both values are at least 32 bytes. The message uses the same
wording as at startup and never carries the value.

### Secret sources — environment variable, file, provider (issue #192)

The JWT signing secret comes from three sources. Whichever one, what is written in
the config is a **pointer**, never the value.

| Source | `lnpl serve` | `build_app()` | `lnpl.toml` |
|------|--------------|---------------|-------------|
| Environment variable | `--jwt-secret-env NAME` | `jwt_secret_env` / `LNPL_JWT_SECRET_ENV` | `jwt = "NAME"` |
| File | `--jwt-secret-file PATH` | `jwt_secret_file` / `LNPL_JWT_SECRET_FILE` | `jwt = { file = "<절대경로>" }` |
| Provider | (none — config file only) | (none — config file only) | `jwt = { provider = "<이름>", key = "<키>" }` |

(`<절대경로>` is the absolute path; `<이름>`/`<키>` are the provider name and key.)

The file source reads a Kubernetes/Docker-mounted secret file as-is:

- The path must be an **absolute path** after expanding `~`. A relative path is
  rejected — since cwd is decided by the host (gunicorn, the container), the same
  config could point at a different file. `--jwt-secret-file ""` is also rejected
  since it is not an absolute path (in `build_app()`, `""` is the same as unset).
- Only **one** trailing newline is stripped: one `\r\n`, or one `\n`. Any other
  byte (whitespace, a lone leftover `\r`, a second `\n`) is part of the key. This
  prevents verification from quietly failing because of the trailing newline
  `kubectl create secret --from-file` or `echo ... > file` appends.
- Opens only a **regular file**. A symlink is followed, so a link pointing at a
  regular file (the shape Kubernetes mounts) is read as-is. A directory, FIFO,
  socket, or device (including `/dev/zero`, `/dev/null`) is rejected before opening —
  because `open()`ing a FIFO with no writer would hang startup forever.
- It is an error if 0 bytes remain after stripping the newline. Over 65536 bytes,
  reading stops right there and it is rejected. An HMAC secret must still be at least
  32 bytes, the existing rule.
- The file is read **once at startup**. Changing the key means restarting the
  process. So readyz check ③ (confirming the environment variable survives) does not
  apply to the file source.
- The file is not read if `--token-provider` is not `hmac` (the same rule as the
  environment-variable source — an external provider's key is managed by that
  provider).

The error message carries only a **role name** — one of `--jwt-secret-file`,
`LNPL_JWT_SECRET_FILE`, `lnpl.toml secrets.jwt.file`. It never carries the path or the
file's content (so that even a secret mistakenly pasted into the path slot never ends
up in the output). The server path is one `error: ...` line and rc 2;
`build_app()` is `WsgiConfigError`:

| Situation | Message (`<role>` = the role name) |
|------|------------------------------|
| A relative path | `<role> must be an absolute path` |
| No file | `<role> names a file that does not exist` |
| Not a regular file (directory/FIFO/socket/device), no permission, a NUL byte in the path, etc. | `<role> names a file that cannot be read` |
| Over 65536 bytes | `<role> names a file larger than 65536 bytes` |
| Empty after stripping the newline | `<role> names an empty file` |
| Under 32 bytes | `the JWT signing secret must be at least 32 bytes, got <n> (from <role>)` |
| Both an environment variable name and a file given | `--jwt-secret-env and --jwt-secret-file both name the JWT signing secret — give exactly one` (build_app: `LNPL_JWT_SECRET_ENV and LNPL_JWT_SECRET_FILE ...`) |

If `lnpl.toml`'s `[*.secrets]` value is not shaped like an environment variable
name, it is rejected at load time, and the value received is never carried in the
message — since the value that landed there could be the secret itself. If the table
shape is neither `{ file = "..." }` nor `{ provider = "...", key = "..." }` (another
key, an empty table, a mixed key), it announces only the key name received and the
shapes allowed.

#### Provider sources and key rotation

`jwt = { provider = "<이름>", key = "<키>" }` (`<이름>` the provider name, `<키>` the
key) reads a key from an external
provider registered via `lnpl.secrets` (Vault, a cloud secrets manager, etc. —
registration and the contract are in `docs/backends.md` §16). There is no CLI flag or
environment variable — this is config-file only. Precedence is exactly the table
above: giving `--jwt-secret-env`/`--jwt-secret-file` (or their `build_app()`
counterparts) wins, and the provider is never even opened. The provider is also not
opened when `--token-provider` is not `hmac`.

- **Rotation (zero-downtime).** Verification accepts **both the provider's current
  key and its previous key**, and signing (`issue`) uses only the current key. Only
  one previous key is kept.
- **Re-fetch rule.** It is read once at startup, and then the first
  verification/issuance request to arrive after 60 seconds (`SECRET_REFRESH_S`) have
  passed reads it again (only one thread reads at a time; the rest keep using the
  existing key). Separately, the `/-/readyz` probe also re-reads it (check ⑤, reusing
  the result if the last read is more recent than 5 seconds). If a re-fetch fails, the
  last good key keeps being used, and readyz fails 503 with `secret-provider`. There is
  no timer thread — traffic is what triggers a re-fetch, so workers never expire all at
  once.
- **Operating procedure.** Change the key in the provider (the new value becomes
  current, the just-previous value becomes previous). Then wait **at least 60
  seconds** before letting the issuer sign with the new key — before that, a worker
  that has not yet read the new key could reject the new token.
- **Shutdown.** `lnpl serve` calls `close()` on the provider at shutdown. The
  `build_app()` path has no shutdown hook, so the provider lives as long as the
  process does.

A provider failure blocks startup (the server path: one `error: ...` line + rc 2;
`build_app()`: `WsgiConfigError` with no cause chain). A driver exception's wording is
never carried over — a driver message could contain a URL or a value:

| Situation | Message |
|------|--------|
| Unregistered name | `lnpl.toml secrets.jwt: unknown secret provider '<이름>' (built-in: env, file; registered entry-points: ...)` |
| A registration that shadows a built-in name (`env`, `file`) | `lnpl.toml secrets.jwt: entry-point '<이름>' (registered via '...') attempts to shadow the built-in secret source '<이름>'; ...` |
| A built-in name (`env`, `file`) given as a provider | `lnpl.toml secrets.jwt: secret provider '<이름>' is a built-in source, not a registered provider — ...` |
| entry-point load failure | `lnpl.toml secrets.jwt: secret provider '<이름>' registered via entry-point '...' failed to load (<예외 타입>)` |
| Factory failure | `lnpl.toml secrets.jwt: secret provider '<이름>' failed to start (<예외 타입>)` |
| Read failure | `the secret provider failed to return the secret (from lnpl.toml secrets.jwt provider '<이름>')` |
| A value that is not `bytes` | `the secret provider returned a value that is not bytes (from lnpl.toml secrets.jwt provider '<이름>')` |
| Under 32 bytes | `the JWT signing secret must be at least 32 bytes, got <n> (from lnpl.toml secrets.jwt provider '<이름>')` (for the previous key: `the previous JWT signing secret ...`) |

(`<이름>` is the provider name; `<예외 타입>` is the exception type.)

## Production deployment — WSGI host (gunicorn) (issue #80)

The `lnpl serve` dev server has neither TLS nor a multi-process worker pool (D4 —
deliberately not built; the "Operational properties" section above). Graceful
shutdown is an exception from issue #148 — the dev server itself performs the SIGTERM
graceful drain (the section above). In production, the `build_app()` factory in
`impl/lnpl/wsgi.py`, which exposes the request-processing core, is handed to a
standard WSGI host — here gunicorn, a tool outside the stdlib, is used as the example
(it is not added as a project dependency; the stdlib-only principle is about
`impl/lnpl` itself, not about a separate process that hosts it). TLS termination has a
reference at `examples/deploy/nginx.conf` (issue #148) — the "TLS termination" section
of `examples/deploy/README.md`.

```bash
pip install gunicorn   # 이 저장소의 의존성이 아니다 — 배치 환경에서 설치

LNPL_SOURCE=examples/shorten.lnpl \
  gunicorn "lnpl.wsgi:build_app()" --bind 0.0.0.0:8000
```

Since `build_app()` is called as a factory that takes no arguments (that is how
gunicorn calls a factory string), every setting comes through environment variables —
the env-var counterpart of each CLI flag:

| Environment variable | CLI counterpart | Default |
|-----------|----------|--------|
| `LNPL_SOURCE` | `lnpl serve <src>` | (required) — files (`os.pathsep`-separated) or one directory, consumed exactly as t77's `load_sources` does |
| `LNPL_BACKEND` | `--backend` | `fake` |
| `LNPL_JWT_SECRET_ENV` | `--jwt-secret-env` | (unset — presence-checked, not verified) |
| `LNPL_JWT_SECRET_FILE` | `--jwt-secret-file` | (unset) — the absolute path of a secret file (issue #192). Rejected if given together with `LNPL_JWT_SECRET_ENV` |
| `LNPL_CLOCK` | (none — `serve` has no `--clock` flag. `serve`'s built-in dev server always runs on a virtual clock, and `LNPL_CLOCK` is a convenience only for gunicorn workers) | `virtual` |
| `LNPL_ENDPOINT_<NAME>` | `--endpoint NAME=URL` | (reuses the issue #101 contract exactly as-is — `build_app()` invents nothing new) |
| `LNPL_LOG_FORMAT` | `--log-format` | `text` (issue #78) |
| `LNPL_TRACE_EXPORTER` | `--trace-exporter` | (unset — exports nothing, issue #78) |
| `LNPL_IDEMPOTENCY_TTL_S` | `--idempotency-ttl` | `86400` (24 hours, integer seconds — issue #113) |
| `LNPL_METRICS` | `--metrics` | (unset = off) — boolean: `1`/`true`/`yes`/`on` or `0`/`false`/`no`/`off`, case-insensitive |
| `LNPL_CAPTURE_ON_FAILURE` | `--capture-on-failure` | (unset = off) — the same boolean notation |
| `LNPL_TRUST_INCOMING_TRACE` | `--trust-incoming-trace` | (unset = off) — the same boolean notation |
| `LNPL_RATE_LIMIT` | `--rate-limit` | (unset = unlimited) — a finite number greater than 0 |
| `LNPL_CONFIG` | `--config` | (unset — `lnpl.toml` is not read. `./lnpl.toml` in cwd is also not read automatically) — the `lnpl.toml` file path |
| `LNPL_PROFILE` | `--profile` | `default` — the profile name inside the loaded `lnpl.toml`. Has no effect without `LNPL_CONFIG` |
| `LNPL_CACHE` | `--cache` | (unset = the built-in `fake` cache) — `<scheme>[:<arg>]`, an `lnpl.caches` entry-point |
| `LNPL_NETWORK` | `--network` | (unset = exactly the existing resolution: checks an endpoint mapping for every logical-name target) — `fake`, `http`, or an `lnpl.networks` entry-point `<scheme>[:<arg>]` |
| `LNPL_TOKEN_PROVIDER` | `--token-provider` | `hmac` — or an `lnpl.tokens` entry-point name. The secret is read only when it is `hmac` |
| `LNPL_JWT_ISSUER` | `--jwt-issuer` | `lnpl` — the expected `iss` claim, any non-empty string |
| `LNPL_AUDIT_SINK` | `--audit-sink` | (unset = no audit record) — `stderr-json` or `file:<path>` (issue #241) |

The variables in the table's last column (from `LNPL_METRICS` through
`LNPL_AUDIT_SINK`) treat an empty string as unset — the variables above them keep
their previous behavior. A boolean notation outside the closed list, or an
`LNPL_RATE_LIMIT` that is not numeric or is ≤ 0/`nan`/`inf`, fails startup with a
`WsgiConfigError` carrying that variable's name. A bad value for any of the six
variables added by issue #187 also fails startup, and the message carries only the
variable name — **never the value** (so a DSN password or path never ends up in a
log): an unknown selector is `LNPL_CACHE is not a recognized selector`/`LNPL_NETWORK
is not a recognized selector`, an unknown token provider is `LNPL_TOKEN_PROVIDER is
not a recognized token provider`, a file that is absent, unreadable, or malformed is
`LNPL_CONFIG is not a valid configuration file`, and a profile not in the file is
`LNPL_PROFILE is not a recognized profile`. `LNPL_JWT_ISSUER` alone has no such thing
as a bad value — an issuer is a free string and is accepted as-is. `LNPL_PROFILE` has
no effect unless `LNPL_CONFIG` is also set. An empty `LNPL_JWT_ISSUER` is treated as
unset and the default issuer (`lnpl`) applies — unlike the CLI's `--jwt-issuer ""`,
which is rejected as an operator error. The two messages for when the secret
`LNPL_JWT_SECRET_ENV` points at is missing or short are unchanged from before (they
carry only the variable name and byte count, never the secret value). When
`build_app()` is called directly with arguments, an explicit argument (a value other
than `None`) wins over the environment variable — `metrics=False` turns off
`LNPL_METRICS=1` (issue #187).

When gunicorn starts multiple worker processes (`--workers K`, default 1), since
each worker is a separate OS process, `LNPL_RATE_LIMIT`'s token bucket is also built
separately per worker — the same N × instance-count arithmetic from the "Rate limit"
section above applies even within one host: with `--workers K` and
`LNPL_RATE_LIMIT=N`, that one host can let through a combined maximum of N × K per
second. The global limit is still the gateway's job here too (the "Rate limit"
section above).

It is not only the rate-limit bucket. Every process-local state that survives
between requests is one per worker: the metrics registry (`wsgi.MetricsRegistry`) and
the token bucket (`wsgi.TokenBucket`). So with `--workers K`, `/-/metrics` returns only
the accumulated value of the one worker that received that scrape — not the whole
host's total. Measured (issue #195,
`benchmarks/load/i195/linux/per-worker-state.log`): after seeding 2 workers and
sending 100 get-bookmark requests, scraping ten times gave a `GetBookmark` execution
count of 53 or 48 (summing to 101 = 100 requests + the seed's 1 get); sending
`LNPL_RATE_LIMIT=20` at 100 rps for 10 seconds across 2 workers gave 434 200s and 566
429s (with one worker it would be 20 × 10 seconds + a burst of 20 = about 220). If a
host-level metric is needed, sum the per-worker values on the collection side, or keep
to 1 worker.

The resolution order is source compilation → `LNPL_CONFIG`/`LNPL_PROFILE` (file
load) → `LNPL_BACKEND` → `LNPL_JWT_SECRET_ENV`/`LNPL_JWT_SECRET_FILE` →
`LNPL_TOKEN_PROVIDER`/`LNPL_JWT_ISSUER` → `LNPL_CLOCK` → `LNPL_CACHE` → `LNPL_NETWORK`
→ everything else. A cache opened via `LNPL_CACHE` is closed before startup fails, if
a later step fails.

### Worker count and worker class (issue #195)

The numbers below come from `docs/gunicorn-load-measurement.md` (one Docker Linux
container, one measurement per point), so read them as a shape, not as a value for
your deployment host. For each combination the rps ladder 50·100·200·400 was climbed,
and the ceiling recorded is the point right before the first one that was not STABLE.

| Backend | Workers | Class | Ceiling (rps) | p99 |
|--------|---------|--------|-----------|-----|
| postgres | 1 | sync | 100 | 6.74ms |
| postgres | 1 | gthread | 50 | 7.54ms |
| postgres | 2 | sync | 400 (ladder's top) | 1566.89ms |
| postgres | 2 | gthread | 400 (ladder's top) | 10.98ms |
| postgres | 4 | sync | 100 | 22.28ms |
| postgres | 4 | gthread | 400 (ladder's top) | 60.12ms |

Pick the combination with the fewest workers whose ceiling is at or above your
target throughput, then re-measure on the deployment host with
`scripts/load_probe.py`. The combination this table backs for 100 rps is postgres,
1 worker, sync (ceiling 100, p99 6.74ms). For a target above 100 rps, 2 workers,
gthread (ceiling 400, p99 10.98ms) is the smallest clean row. 2 workers sync also
reached 400, but it was slow from the very first interval (p95 1493.78ms), and the
STABLE rule did not catch that. The ceiling does not rise monotonically with worker
count (4 workers sync is 100, 2 workers sync is 400) — with one measurement per
point, this table alone cannot separate the effect of worker count from per-run noise.
Among the table's p99 values, 4 workers gthread (60.12ms) and 4 workers sync
(22.28ms) come from their first 10-second interval being higher than the ones after it
(17.10ms and 9.13ms versus 6.57ms or less and 4.80ms or less), so they are read as a
startup-time spike, not a steady-state value.

The ceiling on how many connections to postgres are open at once is K for sync,
and K × thread count for gthread (4K with `--threads 4`). Since each request opens
its own connection (`docs/postgres-load-ceiling.md` Root cause), keep K × thread
count well below postgres's default `max_connections` of 100. The gunicorn docs'
`(2 × 코어 수) + 1` (2 × core count + 1) (https://gunicorn.org/design/ — "workers = (2 × CPU cores) +
1") and the `--workers` settings doc's "generally in the 2-4 x $(NUM_CORES) range"
(https://gunicorn.org/reference/settings/) are only a starting point, and measurement
replaces them. The difference per worker class is also in the design doc. The fake
and sqlite backends were STABLE all the way to the ladder's top of 400 rps across 1,
2, and 4 workers and both sync and gthread (p99 at most 43.96ms, sqlite 1 worker
gthread) and never became a bottleneck.

Starting with `--workers 2` or more for the first time against a fresh postgres DB
can fail startup with `LNPL_BACKEND is not a recognized selector`. This happens
because every worker's startup check runs the driver's `CREATE TABLE IF NOT EXISTS`
at the same moment and they collide with each other (`duplicate key value violates
unique constraint "pg_type_typname_nsp_index"`). Create the table once first (start
one worker, or run
`python -c "from lnpl.drivers import open_repository; open_repository('postgres:<dsn>').close()"`)
and then start K workers. This is an lnpl-postgres follow-up task (found during the
issue #195 measurement).

### Changes to an existing deployment — exactly two (issue #187)

Issue #187 (the work that made `build_app()` accept every `serve` option) changes
exactly these two behaviors in an existing gunicorn deployment that sets none of the
variables above:

1. readyz check ③ now also runs on the `build_app()` path — stated in check ③ of
   the list in the "Operational surface" section above.
2. The startup-failure message for an unrecognized `LNPL_BACKEND` value no longer
   carries the value: `LNPL_BACKEND is not a recognized selector` (it used to carry
   the value and the internal error sentence as-is, via `"LNPL_BACKEND %r: %s"`).

A resolution failure (a source that does not exist, an unrecognized
backend/clock/cache/network selector or token provider, an unreadable config file, an
unset JWT secret, an unmapped network target) raises `lnpl.wsgi.WsgiConfigError` and
**fails startup, not a request** — the same principle `cli.cmd_serve` already
established on the CLI path (it never starts, instead of being discovered only on the
first request).

This machine may not have gunicorn installed — for that case, D5 requires
alternate evidence via `wsgiref.validate`: `test_boundary_wsgiref_validate_accepts_the_built_callable`
in `impl/tests/test_wsgi.py` runs the callable `build_app()` produces through the PEP
3333 validation wrapper (`wsgiref.validate.validator`) and confirms it on every suite
run. Below is an actual startup/request/SIGTERM-shutdown log measured by installing
gunicorn locally while verifying this repository (to reproduce: `pip install
gunicorn`, then the command above, with curl from another terminal):

```
$ LNPL_SOURCE=examples/shorten.lnpl gunicorn "lnpl.wsgi:build_app()" --bind 127.0.0.1:8099 --workers 1
[INFO] Starting gunicorn 26.1.0
[INFO] Listening at: http://127.0.0.1:8099 (13187)
[INFO] Using worker: sync
[INFO] Booting worker with pid: 13189

$ curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8099/shorten-service/shorten \
    -H "Authorization: Bearer any" -d '{"id":"3f2504e0-...","slug":"abc-123", ...}'
200

$ curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8099/no/such/path
404

$ kill -TERM 13187   # gunicorn's own graceful shutdown, not this project's code
[INFO] Handling signal: term
[INFO] Worker exiting (pid: 13189)
[INFO] Shutting down: Master
```

The two status codes (200/404) are the same as M9/M1 in the mapping table above —
even under gunicorn, this is exactly the verdict `impl/tests/test_wsgi_contract.py`'s
shared contract test has already pinned for both the socket path (the built-in `lnpl
serve`) and a directly driven WSGI callable. When nginx sits in front, TLS termination
and static header policy belong to nginx, and gunicorn's only role is serving this
WSGI callable — both are deployment concerns outside this repository.

A reference Dockerfile that runs this exact procedure in a container, and measured
build/startup logs, are in
[examples/deploy/README.md](../examples/deploy/README.md) (issue #87).

## Shared contract

The built-in dev server (the socket) and the WSGI callable `build_app()`/
`make_wsgi_app()` builds run **the same code** (`LnplWsgiApp` in `impl/lnpl/wsgi.py`) —
`lnpl.serve` is only a thin wrapper putting `wsgiref.simple_server` on top of it, not a
second implementation. `impl/tests/test_wsgi_contract.py` proves this by running it,
not by reading the code: it runs a completed POST workflow, GET single/list, 401
(missing authorization), and 404 (an unregistered route) identically on both the
socket path and a direct call to the WSGI callable, and asserts the responses are
byte-identical (except for fields that are random per request, like
`correlation_id`). SSE is separate — since the real-time arrival, reconnection, and
idle shutdown over the socket are already pinned by `test_serve_sse.py`,
`test_wsgi_contract.py` checks only the one thing that was not covered there: that SSE
works as a **pure WSGI iterator** with no socket at all — receiving frames by calling
`next()` repeatedly, and the iterator ending itself (`StopIteration`) on the idle
timeout.

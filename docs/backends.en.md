# Capability adapters and real backends (issue #25)

**English** | [한국어](backends.md)

> This is the English edition of [`docs/backends.md`](backends.md), translated in
> full. The Korean text is normative: where the two disagree, the Korean text
> wins. Identifiers, flags, environment variable names, paths and every code
> block are identical in both editions.

**The code is canonical.** The contract is the three classes in `impl/lnpl/drivers.py`
and their docstrings; this document translates that into human-readable form while
recording **why it was decided that way** and **what it does not do**. When the two
disagree, the code is right.

`capability postgres` / `capability redis` / `security jwt` stopped at declaration
before this issue — the interpreter hardwired `FakeRepository`/`FakeCache`, and jwt
was only recorded. The adapter is **where that declaration gets bound**.

## 1. The three contracts

```python
class RepositoryDriver:      # capability postgres
    def seed(self, rows)                    # {entity_id: {row_key: row}} — 없을 때만 삽입
    def execute(self, entity_id, operation, key)
    def persist(self, entity_id, key, row)  # 바인딩을 통해 갱신된 행을 flush
    def close(self)

class CacheDriver:           # capability redis
    def get(self, key); def set(self, key, value, ttl_ms)
    def invalidate(self, key); def close(self)
    # `set`의 ttl_ms는 클록 비교(FakeCache가 하는 것)와 스토어 네이티브 만료
    # (예: Redis SETEX) 위임 둘 중 어느 쪽으로 판정해도 계약을 만족한다 —
    # 드라이버가 고른다. RFC-0003 §Execution Model/Clock(RFC-0029), 이슈 #100

class TokenProvider:         # security jwt
    def issue(self, subject, audience, ttl_ms=None)   # -> compact JWS
    def verify(self, token, audience)                 # -> claims, 실패 시 TokenError
```

The reference implementation is `interp.FakeRepository`/`interp.FakeCache`. Both are
**bona fide drivers** that satisfy the contract, not "test fakes" — they are in-memory
implementations. The same contract suite (`impl/tests/test_driver_contract.py`) passes
fake and sqlite with **the same assertions**.

The `cached` clause on a read verb (RFC-0062, issue #188) is the first surface that actually calls `CacheDriver.get`. On a hit it does not read the store; on a miss it reads the row from the store and `set`s it under the same key (TTL = the `performance cache` budget). If the same document writes that entity with `update`/`delete`/`set`, it `invalidate`s that key, and if the execution rolls back, it `invalidate`s the keys that execution recorded. The driver gains no new method to implement — the `get`/`set`/`invalidate` behavior that read-through caching expects is already checked by `CacheDriverTCK` (all 7 of its test methods observe the result via `get`).

### Failures all exit one way

Every driver failure exits as `DriverError` (tokens as its subtype `TokenError`),
and the interpreter translates it to `RunError` at **three call sites** (preserving the
cause chain). That is why a storage outage becomes **an ordinary failed execution**, not
a traceback — `status: failed`, CLI rc 1, HTTP 500. This is why `--backend` is a
replacement, not a rewrite.

## 2. Selection surface

```bash
lnpl run   <src>.lnpl --backend sqlite:./store.db
lnpl serve <src>.lnpl --backend sqlite:./store.db --jwt-secret-env LNPL_JWT_SECRET
lnpl token <src>.lnpl --path /shop/checkout --subject alice \
                      --secret-env LNPL_JWT_SECRET [--ttl 15m] [--role <r>]
```

| Value | Meaning |
|----|-----|
| `--backend fake` | **Default.** In-memory, fresh on every run. Behaves byte-identically to before this issue |
| `--backend sqlite:<path>` | Real storage that persists to a file |
| `--backend <scheme>:<arg>` (if registered) | External driver registered via `lnpl.drivers` entry-points — §8 SPI |
| Any other value (unregistered) | rc 2. Prints the token it received together with **the allowed set of built-in + registered entry-points** — it never guesses |

`fake` being the default is the non-destructive principle. Tightening an already
shipped surface is a breaking change; new features turn on **only when opted into**.

### Path values

`sqlite:<path>` accepts a relative path (it is an argument a person types at a shell,
so the CWD is the intent). But **at open time** it does `~` expansion then one absolute-path
resolve and keeps that form, and dies with rc 2 if the parent directory is missing or
unwritable. The message carries **the text exactly as received** — a resolved path the
operator never typed is one more thing to debug.

### Secrets

`--secret-env`/`--jwt-secret-env` take **an environment variable name**. The value
itself is never taken on the command line — it would stay in shell history and `ps`. If
the variable is missing or under 32 bytes, it dies with rc 2 **before the server opens a
socket**, and the message carries **only the variable name**.

`lnpl serve --jwt-secret-file PATH` (issue #192) reads a mounted secret file
(Kubernetes/Docker secret). The path must be absolute, and only one trailing newline is
stripped. If the file is missing, unreadable, empty, or under 32 bytes, it dies with rc 2
under the same rule, and the message carries only the flag name (`--jwt-secret-file`) —
never the path or the contents. Giving it together with `--jwt-secret-env` is rejected.
The full shape, precedence, and error text are in the "Secret sources" section of
`docs/serving.md`.

`lnpl.toml`'s `jwt = { provider = "<이름>", key = "<키>" }` (issue #192, config-file
only) reads the key from an external provider registered via `lnpl.secrets`, and
verifies against the current key plus the previous key to support zero-downtime
rotation — the registration, contract, and re-fetch rules are in §16.

```bash
export LNPL_JWT_SECRET="…여기에 32바이트 이상의 무작위 값. 이 문자열이 아니라…"
```

## 3. sqlite storage

### Schema — not one table per entity

```sql
CREATE TABLE IF NOT EXISTS lnpl_rows (
    entity_id TEXT NOT NULL,
    row_key   TEXT NOT NULL,
    payload   TEXT NOT NULL,
    _version  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (entity_id, row_key)
)
```

`entity_id` is **a bound column value**, not a table name. Making one table per
entity would put a name that came from the document into the SQL **statement text**
itself — exactly the shape injection needs. Here every statement is a constant and every
varying value is a bind parameter.

`_version` is an internal column used only by the "Write conflicts" section below.
No `.lnpl` document, payload, or response ever knows this name — the closed vocabulary
gains not a single word (issue #92). If an existing DB lacks this column, run this once
at deploy time:

```sql
ALTER TABLE lnpl_rows ADD COLUMN _version INTEGER NOT NULL DEFAULT 0;
```

A freshly created file already gets this column from `CREATE TABLE IF NOT EXISTS`,
so this ALTER is unnecessary — it applies once, only to files created before this issue.

### Concurrency

WAL handles reads against reads, and `_version` handles writes against writes — two
different problems.

- **Once, when the file is created**: `journal_mode=WAL`, `synchronous=NORMAL`
  (persisted to the file)
- **Every connection**: `busy_timeout=5000` — waits instead of erroring immediately on a
  lock
- **A new connection per request (= per Interpreter)**, closed in `finally`. Opening a
  connection costs ~0.05ms so a pool buys nothing, and the connection never crossing a
  thread is why it is safe without a lock under `ThreadingHTTPServer`.

#### Write conflicts — `_version`

A concurrent read-modify-write (for example `read x` followed by `set x.n to x.n +
1`) is not solved by WAL alone: two executions read the same value, each computes, and
whichever writes later overwrites the earlier write without a trace — measured at 12 of
31 concurrent increments vanishing this way.

The row `SqliteRepositoryDriver._read` returns remembers the `_version` at that
moment too (it never appears in the payload — it is just an internal attribute of the
returned dict). `persist()` conditions the UPDATE statement on that value:

```sql
UPDATE lnpl_rows
   SET payload = ?, _version = _version + 1
 WHERE entity_id = ? AND row_key = ? AND _version = ?
```

Zero rows affected means someone wrote first, after the read — instead of silently
overwriting, it raises `WriteConflictError("write conflict: row changed since read
...")`, which takes the same path as any other driver error to become `RunError`, an
ordinary failed execution (`status: failed`, `failure_kind: "write-conflict"`, issue
#201). `WriteConflictError` is a subtype of `DriverError` and a sibling of the create
conflict's `ConflictError` (neither is a subtype of the other). An external driver opts
in by importing this type from `lnpl.drivers` and raising it — a driver that raises a
plain `DriverError`, even with the same message text, remains an unclassified failure as
before. The fake driver is single-process in-memory, so this conflict cannot occur and
`persist()` is simply a no-op.

When `update` succeeds (one or more rows affected), the driver carries that same
`_version` increment from the UPDATE forward into the row this execution has already
read and bound under the same key — as a result, a `set; update; set` sequence within
one execution no longer conflicts with itself (issue #182). If another connection
(another execution) genuinely wrote in between, it still conflicts exactly as before —
this carry-forward advances only by 1 from a value this execution already knows, so it
never outruns a concurrent write it does not know about.

**Who retries when it conflicts.** Since one `WorkflowStep` is one line of source
(`_step` in `lower.py`), `read` and the `set` after it are always different steps.
Retrying only the failed `set` step writes the same (never re-read) binding again, so it
never recovers — what recovers is **a new call that invokes the whole workflow again**,
which reads from scratch. Because `policy retry` already declares these effects
idempotent (RFC-0003 §Policy Enforcement), calling it again is safe — nothing was
committed, so it is not a duplicate, and how many retries the declared budget allows is
already decided. This is not a new concept, just reusing the existing contract. The
serving surface answers this failure with 409 `write-conflict` (`docs/serving.md` M8c;
the event-consumption path answers with 503 in E6) — the retry is the client calling the
whole workflow again. **`policy retry` alone does not recover from this conflict**: the
declared budget only retries the failed `set` step with the same stale read (with
`retry 3`, all 4 writes conflict), so a single `run_workflow` call exhausts its budget
and fails — `impl/tests/test_driver_concurrency.py`'s
`test_a_declared_retry_budget_does_not_by_itself_rerun_the_whole_workflow` pins this
down.

### Seeding and flush

`seed()` **inserts only when absent** (`INSERT OR IGNORE`) — meaning the caller never
overwrites a row an earlier execution wrote.

**Who calls `seed()` (issue #197).** `Interpreter.__init__` calls `seed()` with the
request payload only when `self.repo` is a `FakeRepository` instance — targeting the
`fake` backend and the spec/diff runners (both use `FakeRepository` internally). For a
persistent driver, whether `sqlite:` or one registered via `lnpl.drivers`, the
`Interpreter` no longer calls `seed()` at all: if a read verb (`find`/`load`/`read`/
`authenticate`, bare or `by <ref>`) finds no row in persistent storage, that step fails
with the typed `failure_kind` `not-found`, and the request payload never gets stored as
a ghost row. To pre-load data into a persistent driver — for tests or for production —
call `seed()` directly or use a `create` workflow.

**A zero-row write (issue #215, RFC-0064).** If `update`/`delete` (bare or `by
<ref>`) affects zero rows (`execute` returns `{"affected": 0}`), that step also fails
with the same `failure_kind` `not-found` — the same for `fake`, `sqlite:`, and external
drivers alike. The default seed still populates only the entity that is `read` first, so
on `fake`, a workflow that first touches an entity via `update`/`delete` fails with
`not-found` even on the default seed.

`persist()` flushes to disk the value RFC-0015's `set` **wrote into the bound row**.
For fake this is a no-op since the bound dict is already the stored row, but without
this flush on a real store, an update would be visible only during the execution and
then disappear.

### The outbox — `lnpl_outbox` (issue #102)

This makes `emit`, which used to stop at observation, real. The core owns only the
table schema and the drain/ack semantics — the relay (the side that actually publishes
to a broker) is out of process (the #88 principle).

```sql
CREATE TABLE IF NOT EXISTS lnpl_outbox (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    emission_id  TEXT NOT NULL,
    event        TEXT NOT NULL,
    payload      TEXT NOT NULL,
    created_at   INTEGER NOT NULL,
    delivered_at INTEGER
)
```

An `EventEmit` effect run with `--backend sqlite:...` lands as one row in this table
the moment it registers (RFC-0003 — the synchronous section ends at "register the
publish"). This is **status marking**, not deletion — `delivered_at` being `NULL` means
undelivered, a value means delivered, and the row itself is never removed.

**A row's identity is `seq`, not `emission_id` — a decision that departs from issue
#102's original text (PK on `emission_id`) on measured grounds.** `emission_id` is
`"%s#%d" % (effect_id, len(outbox)+1)` (`interp.py`), **a counter local to one
`Interpreter` instance**. Running the same document with `lnpl run` against the same
store twice, separately, reproduces exactly the same `emission_id` for the first emit of
each run — because the CLI creates a fresh `Interpreter` per run and never passes
`correlation_id`, which then pins to its default (`cid-0001`). `emission_id` was
originally the PK, but **the second `lnpl run` invocation failing on a PK collision** was
measured directly (2026-08-24, during this task's implementation). This is not a
retransmission — at-least-once dedupe targets **the same delivery** arriving again —
these are **two distinct emissions** made by two distinct runs, so the right behavior is
for the second row to be stored successfully. So the delivery identity moves to the
storage-owned surrogate key `seq` (sqlite `AUTOINCREMENT`), and `emission_id` remains an
ordinary column pointing at the trace that created that emission — the
`emission_id`/`correlation_id` generation in `interp.py` itself was left untouched (it is
part of the deterministic trace contract that golden output and mode A/B differential
checks read, so its blast radius is larger than this task).

CLI contract (details in `plugins/lnpl/skills/lnpl-authoring/cli-surface.md`):

- `lnpl outbox drain --backend sqlite:<path> [--limit N]` — emits undelivered rows to
  stdout as JSON Lines in `seq` ascending order (insertion order). One line is
  `{"seq", "emission_id", "event", "payload", "created_at"}`. Since `seq` equals
  insertion order, it can be used directly as a cursor — this is exactly the value an
  SSE subscription (t103) would resume from, Last-Event-ID style.
- `lnpl outbox ack --backend sqlite:<path> <seq> [<seq>...]` — marks the given `seq`s
  as delivered. **Re-acking the same `seq` is idempotent** (succeeds, state unchanged) —
  `UPDATE ... WHERE seq = ? AND delivered_at IS NULL` touches zero rows on an
  already-marked row and succeeds quietly. If a batch contains **even one unknown
  `seq`, nothing is written**, and that `seq` is rejected by name with rc≠0 — the rest
  are never silently acked in a way that leaves the caller unable to tell "only some
  succeeded" from the message alone.

`drain_outbox`/`ack_outbox` are **optional** methods of `RepositoryDriver`. Whether an
external driver has both is reported by `supports_outbox_drain()`; the per-feature
mapping is in the "Optional methods and capability predicates" table in §8.

**What the external relay owns.** This implementation only reads via drain and
clears via ack — the polling publisher that actually publishes to Kafka, SQS, etc. is
owned by an out-of-process scheduler such as cron, a systemd timer, or a k8s `CronJob`,
and its loop is `drain → (각 행을 브로커에 퍼블리시) → 성공한 seq만 ack`
(drain → publish each row to the broker → ack only the seq's that
succeeded). `ack` must only be called after the actual publish is confirmed — acking
ahead of time leaves no way to see that emission again if the publish fails (breaking
at-least-once).

**This extension (issue #191, RFC-0061).** When the "external relay" in the paragraph
above is `lnpl relay` itself, it is no longer entirely out of process — if `--target` has
a scheme other than `http(s)://`, the core-owned `lnpl.publishers` registry selects the
registered `EventPublisher` driver, and acks only after that driver's `publish` confirms
(§15 below). The actual broker binding (Kafka client code, etc.) is still the job of the
external package implementing that driver — what changed is only that the core now owns
"the point that picks which driver to use."

**Batch transactions and delivery guarantees (issue #257).** `lnpl relay` wraps one
batch — `drain_outbox` → publish (or POST) each row → `ack_outbox` — in a single driver
transaction. `begin()` before the batch, `commit()` when the batch ends, and
`rollback()` if an exception escapes the batch (an ack failure, an unexpected publisher
exception, an interrupt). The commit finishes before the `--once` summary output and the
next poll wait, so no transaction is left open while waiting. Per-row handling stays the
same — a row whose publish fails (`DriverError`, 503, no response) is not acked, the
batch is committed anyway, so it reappears on the next drain, and acks already succeeded
are kept.

- **Condition.** The exactly-once-per-batch guarantee below holds only for a driver
  whose `drain_outbox` takes a row lock inside `begin()`. Right now that driver is
  `lnpl-postgres` (`SELECT ... FOR UPDATE SKIP LOCKED` — PR choiyounggi/lnpl-postgres#9,
  `drain_outbox` on main `a1bef53`). A driver that keeps the base class's no-op
  `begin()`, or has no row locking, leaves delivery between relays at-least-once.
- **An unwrapped drain.** `drain_outbox` called outside a transaction (e.g. `lnpl
  outbox drain`) releases its lock at statement end even on `lnpl-postgres`. If two
  relays read the same outbox this way, both can publish the same row before either
  acks — at-least-once between relays.
- **A wrapped batch — exactly-once per batch (row-locking drivers only).** While
  `lnpl relay`'s batch transaction is open, the lock on a drained row is held until
  commit, and a second relay's drain skips that row. So within one batch, each row goes
  to at most one relay.
- **Batch size ceiling (issue #262).** A relay drains at most 100 rows
  (`RELAY_BATCH_LIMIT`) per batch. If the driver's `drain_outbox` accepts a `limit`
  argument (determined from its signature), it is called as `drain_outbox(limit=100)`;
  if not, it is called without `limit` as before, running one unbounded batch. Each batch
  is one transaction, and if the batch is full (100 rows) and at least one row was acked,
  the next batch is drained immediately. If the batch is short or zero rows were acked,
  that pass ends — `--once` exits, and the default mode sleeps for the poll interval
  before the next pass. So on a row-locking driver, a second relay skips the rows the
  first relay locked and receives the rows after them. The worst-case time a batch holds
  its locks is 100 rows × a 10-second HTTP timeout (about 17 minutes against a
  non-responding target). A row whose publish fails (`DriverError`, 503, no response, an
  unexpected status) is not acked, so it reappears at the front of the next batch in the
  same pass. If 100 such rows pile up, one batch ends with 0 acks and the pass stops, and
  the rows after them are not drained until the rows ahead of them are acked or
  dead-lettered (422). An emission newly recorded while `--once` is running can also be
  drained within the same pass.
- **When redelivery happens.** End to end, this is still at-least-once. If the relay
  dies after publishing but before acking, that row is redelivered regardless of driver.
  If the commit fails after ack, or it is interrupted before the commit, on
  `lnpl-postgres` the ack rolls back with the transaction and is redelivered, but on
  sqlite it is not redelivered because `ack_outbox` committed on its own. If the rollback
  itself fails, the `error:` line prints the rollback error instead of the original one.
  Consumers must dedupe on the stable CloudEvents `id` (`outbox-<seq>`).
- **sqlite.** sqlite has no row locking (`drain_outbox` is a plain SELECT, `ack_outbox`
  commits on its own). So this wrapping does not change the delivery guarantee on
  sqlite, and only one relay should run against one sqlite store.

**What this does not do.** HTTP drain (`GET /_outbox`) and webhook push are scope the
issue marked as a follow-up, so `serve.py` is untouched. Broker binding (Kafka, etc.) is
the relay implementation's job. The interaction with `#79`'s workflow-level transaction
boundary (does a row emitted by a failed execution stay) is explicitly deferred — that
interaction rule does not exist yet.

## 4. jwt

| Item | Value |
|------|-----|
| Algorithm | **Fixed at HS256.** The issuer and the verifier are the same service, so a symmetric key is the right shape |
| Key | ≥32 bytes (256 bits). Read from an environment variable, a file, or an `lnpl.secrets` provider. A provider source verifies against the current key + the previous key (issue #192) |
| Verification order | 3 segments → **alg allowlist** → signature (`hmac.compare_digest`) → `typ` → `iss` → `aud` → `nbf`/`exp` |
| leeway | 60 seconds (RFC 7519's approved ceiling is "a few minutes") |
| Claims | `iss`/`aud`/`sub`/`jti`/`iat`/`nbf`/`exp`, and `role` if `--role` is given (issue #202, self-asserted). The payload is base64, not ciphertext, so no PII goes in it |
| Lifetime | 15 minutes by default |

`alg` is decided by a **server-side allowlist**. Letting the token pick its own
algorithm is exactly where `alg: none` and alg-confusion live. Signature verification
always computes with HS256.

`aud` is derived from **the service slug of the request path** (`/shop/checkout` →
`shop`). Issuing (`lnpl token`) and verifying (`serve`) read the same function
(`audience_for_path`), so drift is impossible, and a token issued for a neighboring
service never works here.

No library was added. HS256 is HMAC-SHA256, and its primitive comes from the stdlib
`hmac`/`hashlib` — what is written here is the encoding and the verification checklist,
not a cryptographic algorithm implementation.

**Extended by issue #119b.** `iss` is no longer hardcoded — `--jwt-issuer` can
specify the expected issuer, and when unspecified, the existing `"lnpl"` stays exactly,
byte for byte. An algorithm this table itself does not cover, such as RS256/ES256, does
not enter the core — the §9 `lnpl.tokens` SPI is that boundary.

## 5. What this implementation does not do

Not writing down what remains makes it read as though it was done.

| What it does not do | Why |
|--------------|-----|
| **A real `redis` binding** | The clock cause is resolved (RFC-0003 §Execution Model/Clock, RFC-0029, issue #100) — delegating the `ttl_ms` that `CacheDriver.set` receives to the store's native expiry (e.g. Redis `SETEX`) means the cross-process clock-reset problem never arises in the first place (the clock-comparison path is still available via `--clock real`, but delegation is the recommended path). The `CacheDriver` contract is defined and `FakeCache` is its implementation — the SPI surface (`lnpl.caches` entry-points, `open_cache`) was opened by issue #131 (§10). The external package that ships a real driver is now filled in: `lnpl-redis` (§10) is the real implementation of the recommended delegation path (a single atomic `SET key value PX ttl_ms`) — the boundary design itself, that the core does not ship it, stands unchanged |
| **Refresh tokens, rotation, a revocation list** | All three require a server-side session store. A refresh without a store is just an access token with a longer lifetime under a different name. Revocation gap = access-token lifetime (signing-key rotation is §16) |
| **A postgres / redis server binding** | The fact that the core does not ship it stands unchanged — that is §8's boundary design. The postgres side has its outside-the-boundary half filled in: the external repo [`lnpl-postgres`](https://github.com/choiyounggi/lnpl-postgres) ships a `RepositoryDriver` (psycopg 3) registered in `lnpl.drivers` as `postgres = "lnpl_postgres:make_driver"`, and passes this repo's TCK against a real postgres server in its own Testcontainers CI (issue #121, following issue #115's in-repo half = TCK hardening, completed 2026-08-30). The redis side is also filled in: the external repo [`lnpl-redis`](https://github.com/choiyounggi/lnpl-redis) ships a `CacheDriver` (redis-py 8) registered in `lnpl.caches` as `redis = "lnpl_redis:make_cache"`, and passes this repo's `CacheDriverTCK` against a real redis server in its own Testcontainers CI (issue #143, completed 2026-09-02) |
| **Compensation for a `NetworkCall` outside the transaction boundary** | `policy rollback` only reverts storage writes (RFC-0032 §Open Questions ②) — a `call`/`request` has already gone out and does not roll back. The compiler only **reports** this per workflow, as `rollback-escapes-network` (warning, issue #112). The compensation approach was decided by RFC-0034 (Draft); the implementation is a follow-up (Batch B) |
| **Side effects in mode B (native)** | The contract that mode B is structural-trace-only stands unchanged. The adapter does nothing to mode B |
| **Outbox HTTP drain (`GET /_outbox`) and webhook push** | Scope issue #102 marked as a follow-up. `serve.py` is untouched — this task reaches as far as the CLI (`lnpl outbox drain`/`ack`) |
| **A real outbox-to-broker binding (Kafka, etc.)** | The core owns only the table schema and the drain/ack semantics (the #88 principle). The polling publisher that actually publishes is the relay implementation's job (cron/systemd/k8s `CronJob`) — when `lnpl relay` itself plays that publisher role, it goes through a driver registered in `lnpl.publishers` (§15, issue #191); the real driver implementation itself is still a separate package's job |
| **A real broker-to-`consume by`-ingestion binding (a Kafka consumer, etc.)** | The #88 principle applied symmetrically to the consuming side (issue #118). The core owns only the subscription declaration (`consume by`), the ingestion endpoint (`POST /-/events/<slug>`), and the idempotency/error-classification semantics — reading from the broker and hitting that endpoint is the job of `lnpl relay` (the reference, urllib only) or an external relay implementation. Real Kafka consumer-group and offset management is outside this repo |
| **`security encrypt <field>`** | Removed — see RFC-0035 §D3 (issue #127). Dropped from the closed vocabulary because having zero external drivers to actually enforce it was never "driver-dependent" but always an empty set. `Password` masking (#43, the observation-channel rule that hides a value in responses/traces when a field's type is in the `Password` family) stays unchanged regardless of this decision |
| **A real `NetworkDriver` with a connection pool** | `HttpNetworkDriver` opens and closes a connection per call — what RFC-0037 (issue #109) added was only retry/backoff/jitter/circuit-breaker/path templates. The `lnpl.networks` entry-points SPI surface itself was opened by issue #132 (§10) — an external package that registers a real driver with a keep-alive pool (`urllib3`/`httpx`-based) on that surface is still outside this repo |
| **A dedicated object-storage (S3/GCS/Blob) capability** | Judged against real scenarios how far a `capability http` workaround reaches (issue #193) — [docs/object-storage-http-assessment.md](object-storage-http-assessment.md) |

**A symmetric boundary on the consuming side (issue #118).** The boundary already
set on the publishing side — the #88 principle that the core owns only the contract
(table schema, drain/ack semantics) and the real broker binding is the relay's job — is
applied the same way to the consuming side. The core owns only the subscription
declaration (`consume by`) + the ingestion endpoint (`POST /-/events/<slug>`) + the
idempotency/error-classification semantics (RFC-0040). A reference relay (`lnpl relay`)
that exercises this contract exists, but actually reading from brokers (Kafka, etc.) and
hitting that endpoint is still outside the core — as with the driver SPI (#75/#132), the
real binding is a decision a separate package owns, not this plan reversed.

`FakeRepository`'s `rollback` is left out of the table above: as of issue #120 it is
no longer a no-op — it actually reverts. `begin()` takes a snapshot of `self.rows`,
`rollback()` restores from that snapshot, and `commit()` discards it — so even on
`--backend fake` (the backend most of the suite and local development use), RFC-0032's
"one workflow execution = one transaction" policy is genuinely upheld.

## 6. Relationship to differential verification

`EQUIVALENT` on the fake backend still holds. But exactly what that verdict says
must be stated precisely — since mode B does not model storage state:

- **Default inputs**: the two modes agree on **inputs where storage state does not
  determine the result**.
- **Forcing inputs** (`--no-row`, creating the same key twice): a verdict on inputs
  where the storage dimension determines the result must be read **separately**.
- **The sqlite path is not a differential-verification target.** Since mode B does not
  model storage, it cannot render any verdict on that dimension — this is not
  "agreement" but **unverified**.
- **`--clock real` is also not a differential-verification target** — it is
  non-deterministic, so it cannot produce a repeatable comparison. The `diff`/`spec`
  subcommands have no `--clock` selector at all (RFC-0003 §Execution Model/Clock,
  RFC-0029, issue #100).
- **A `list where` predicate is also an unverified dimension** (issue #116, D9). A
  predicate filters a RowSet by the row **values** accumulated in storage, and as RFC-0025
  §10 already states, a RowSet value is none of mode B's four observation classes
  (execution order + skips, policy outcome, observation signals, masking) — the same
  reason `sum`/`count` results were never a comparison target to begin with.
  `differential.compare_observations` therefore keeps emitting `EQUIVALENT` when the four
  classes genuinely agree (that verdict itself is true) — but it adds one more line when
  the report passes a `list` with a predicate: `note: N \`list
  where\` step(s) — filtered RowSet content is not compared (unverified
  dimension, docs/backends.md §6)`. The point of this line is to keep "agreement" from
  being read as "the filtered content matches too."
- **Real concurrency in a `parallel` block is also an unverified dimension** (issue
  #108, D8). Mode A now genuinely runs the steps of a `parallel` block concurrently
  (RFC-0041), but mode B still runs them sequentially — exactly the open question
  RFC-0004 §5 (#7) already carried, this issue changed only mode A and left mode B
  untouched. Because "execution order," one of the four observation classes, is reported
  by **declaration order**, not completion order (D6), the two modes' order reports
  happen to come out the same shape for a failure-free execution — but that does not
  verify "whether mode A actually ran in parallel." Evidence of real concurrency, such as
  wall-clock overlap, never belonged to any of the four classes to begin with.
  `differential.compare_observations` therefore adds one more line when the report
  passes a workflow with a `parallel` block: `note: N \`parallel\`
  block(s) — mode B runs them sequentially (unverified dimension,
  docs/backends.md §6)`.

## 7. mode B's observation surface (issue #55)

The canonical source is `rfcs/0022-mode-b-observation-surface.md`. Here only the two
things someone who just read §6 immediately needs are written down.

**A skip is not stated by the binary — the observer reconstructs it.** If the guard
is false, `scf.if` never calls `lnpl_step`, so that step's line is simply absent from
stdout. An absence means nothing without a list of what is missing, and that list is the
compiled step plan. One function, `backend.restore_skips()`, does that comparison, and
differential checking and `lnpl build --run` read it. So `build --run` says this:

```
status completed
  (1 step(s) skipped by guard, restored from the compiled plan)
  skipped by `when token.retryBudget > 0`: call token
```

The diagnostic `guard-skipped-steps` (warning) goes to stderr, and unlike mode A it
is **one per step**, with `where` being the workflow id — mode B's observation surface
has no guard-node id.

**`--field` is comparison-guard only.** In mode B, refinement verification is
decided at build time and its input is a derived sample payload, so no `--field` value
can ever fail a refinement. `build` states this fact as `validation-sample-derived`
(info) for every workflow that has a Validation effect. To measure refinement
enforcement for real, use `lnpl run --payload` (mode A).

What remains **unclosed** here (RFC-0022 table 3): running the binary alone without
`lnpl` leaves a skip silent as ever, and `build` has neither `--json` nor `--strict`, so
there is no way to machine-read or gate a mode B skip in CI.

## 8. SPI: external driver registration (issue #75)

As §5 already said, the core does not own the real postgres/redis driver — only the
contract and the TCK live in the core, and an external package verifies the real binding
**against a real server in its own CI** ("no binding without an integration test"). This
section writes down how that boundary shows up in code: the core keeps the
`lnpl.drivers` entry-points group open, and when `open_repository` fails on the two
built-in schemes (`fake`/`sqlite`), it looks the scheme name up in that group.

### Registration

An external package's `pyproject.toml`:

```toml
[project.entry-points."lnpl.drivers"]
postgres = "my_lnpl_postgres:make_driver"
```

`my_lnpl_postgres.make_driver` is a callable that takes one `<arg>` (the text after
the colon, exactly as written) and returns a `RepositoryDriver`. When the package is
installed, `--backend postgres:<dsn>` finds and calls that factory — the core side has
not a single `if` statement for this scheme.

A real example of this shape is
[`lnpl-postgres`](https://github.com/choiyounggi/lnpl-postgres) (issue #121) — a
`RepositoryDriver` (psycopg 3) that registers as `postgres = "lnpl_postgres:make_driver"`,
whose own Testcontainers CI runs this repo's TCK against a real postgres server (the
first fulfillment of "no binding without an integration test").

### A built-in scheme can never be shadowed

`open_repository` checks `fake`/`sqlite` **before** the entry-points lookup. Even if
some package registers under the name `sqlite` or `fake` in `lnpl.drivers`, that
registration is never looked up — there is no path at all by which a built-in gets
shadowed (`test_driver_spi.py::BuiltinShadowingTest`).

### Diagnostic for an unregistered scheme

A scheme that is in neither the built-ins nor the registered entry-points is
rejected with rc 2, and the message carries **the value received**, **the built-in
list**, and **the entry-points actually registered at that moment** (or "none" if there
are none) together — so a typo and "the package was never installed" can be told apart
from the same message.

### entry-point load failure

When something is registered but its value (`module:attr`) cannot be imported — for
example when the package was removed but its registration metadata survived —
`open_repository` does not let the `ImportError` escape as-is; it translates it to
`DriverError` (preserving the cause chain). This means this module's "ONE ERROR TYPE
OUT" rule applies to the entry-points path exactly the same way.

### Optional methods and capability predicates (issues #228/#229)

`lnpl run` works even with only `RepositoryDriver`'s required methods implemented.
But some features of serve and the CLI require an extra bundle of **optional methods**,
and whether a driver has that bundle is reported by two **capability predicates** on the
base class. The base class defines none of the five optional methods. A predicate's
default implementation checks directly whether every method in the bundle is callable on
this driver instance, so an external driver that implements the methods is reported
True even without overriding the predicate. If even one method of the bundle is missing,
it is False — a half implementation is not support.

| Feature | Required optional method | Reporting predicate | When the predicate is False |
|---|---|---|---|
| The `Idempotency-Key` header — the workflow request path and the `POST /-/events/<slug>` consumption path | `idempotency_begin` / `idempotency_finish` / `idempotency_release` | `supports_idempotency()` | serve rejects the request without executing it, with 501 `idempotency-unsupported` (problem+json) (issue #228) |
| `lnpl outbox drain` / `lnpl outbox ack` | `drain_outbox` / `ack_outbox` | `supports_outbox_drain()` | The CLI ends with a one-line error and rc 2 (issue #229) |
| `lnpl relay` | `drain_outbox` / `ack_outbox` | `supports_outbox_drain()` | The CLI ends with a one-line error and rc 2 (issue #229) |
| An SSE subscription `GET /<svc>/events/<slug>` | `read_outbox` | None — `read_outbox` is a required base method | Not applicable |

Do not override the predicates. The TCK cross-checks a predicate's answer against the
methods that actually exist, so a driver that returns True without the methods, or False
while having the methods, fails the TCK ("Verifying with the TCK" below).

Current drivers (as of 2026-10-11): the built-in `sqlite` is True for both predicates.
[`lnpl-postgres`](https://github.com/choiyounggi/lnpl-postgres) lacks all five optional
methods, so both are False, and the implementation is lnpl-postgres#8's job. `fake` has
no persistent storage driver, so it never asks the predicate and keeps its existing
behavior unchanged — it makes no idempotency claim, and `lnpl outbox`/`lnpl relay`
reject it with rc 2 as before.

### Verifying with the TCK

An external driver subclasses `lnpl.testing.RepositoryDriverTCK` and runs it in its
own CI:

```python
import unittest
from lnpl.testing import RepositoryDriverTCK

class MyPostgresDriverTCKTest(RepositoryDriverTCK, unittest.TestCase):
    def make_driver(self):
        return MyPostgresDriver(dsn=TEST_DSN)
```

`RepositoryDriverTCK` is a pure mixin that does not subclass `unittest.TestCase` —
the concrete class must multiply-inherit with `unittest.TestCase`. What it verifies:
read, write, delete, `affected` 0 for updating and deleting an absent row (issues #183,
#215), `None` returned for an absent row, `DriverError` on a duplicate create, and —
only for a driver whose read row carries an `observed_version` attribute — whether a
stale write conflicts (issue #92) and whether that conflict is of type
`WriteConflictError` (issue #201); both cases are skipped if this attribute is absent.
An external driver that exposes `observed_version` but used to raise a plain
`DriverError` on conflict fails this second case, so it must be changed to raise
`lnpl.drivers`'s `WriteConflictError`. As of issue #182, for a driver with
`observed_version` it also verifies that a `set; update; set; update` sequence within one
execution all succeed, and that it still conflicts if another connection's real write
lands before or after that `update` (both orders).

**`begin`/`commit`/`rollback` (issue #79, RFC-0032) — breaking-changed by issue
#115.** It used to check only that the three were callable in order without raising, and
never asserted that `rollback` actually reverts, on the grounds that the base contract
allows a no-op. Once RFC-0032 raised `policy rollback` to enforced, that leniency was a
hole that let contract violations through — now the TCK asserts that `rollback` actually
reverts the row writes and outbox registrations made inside the transaction, and that a
second `begin` on an already-open transaction is rejected with `DriverError`. **A driver
that used to answer `rollback` with a no-op no longer passes this TCK.** The example of
`SqliteRepositoryDriver` verified with this TCK is
`impl/tests/test_driver_contract.py::SqliteDriverTCKTest`.

**Optional methods (issues #228/#229) — declared-unsupported, not a skip.** The TCK
holds 3 idempotency cases (re-claiming an open claim gives `in-progress`; a claim after
`idempotency_finish` replays the stored result; a claim after `idempotency_release`
starts fresh as `started`) and 3 drain/ack cases (undelivered rows are listed in `seq`
ascending order; an acked row is never drained again; re-acking the same `seq` succeeds
idempotently). Each case first asks the relevant predicate. If True, it asserts the
behavior; if False, it asserts that the predicate is genuinely `bool` False and that
not one method of that bundle exists, then passes. Neither path is a `skipTest`, so a
driver that returns True without the methods, or implements only part of the bundle,
cannot hide behind a skip and fails. A driver missing all five methods (`lnpl-postgres`
as of 2026-10-11) passes all six cases as declared-unsupported.

## 9. SPI: external token provider registration (issue #119b)

What issue #119 pointed out: if the role claim enforcing `security role <r>` only
ever comes from a token self-issued by the built-in `hmac` provider, that is
self-asserted, not grounds for identity. This section writes down how it opens that
boundary in code — the same shape as `lnpl.drivers` in §8: the core keeps the
`lnpl.tokens` entry-points group open, and when `open_token_provider` sees a name other
than the built-in (`hmac`), it looks it up by name in that group.

### Registration

An external package's `pyproject.toml`:

```toml
[project.entry-points."lnpl.tokens"]
oidc = "my_lnpl_oidc:make_provider"
```

`my_lnpl_oidc.make_provider` is a callable invoked **with no arguments** that returns
a `TokenProvider` — unlike `lnpl.drivers`'s `factory(<arg>)` (which takes the text after
the colon): settings such as the signature-verification key, the JWKS endpoint, and key
rotation are the package's own job, not a string this CLI parses and hands over (see D4
below). When the package is installed, `--token-provider oidc` finds that factory and
calls it with no arguments.

### A built-in name is rejected if shadowed

`lnpl.drivers`'s `BuiltinShadowingTest` (§8) has the built-in win **silently** — the
entry-points lookup never even happens. `open_token_provider` behaves differently: when
`--token-provider hmac` is called and `lnpl.tokens` has an entry-point registered under
the name `hmac`, it **rejects with `TokenError`**, carrying the conflicting name and the
module that entry-point points to in the message (`test_token_spi.py`
`BuiltinShadowingTest`). Since token identity is the trust basis `security role`
enforcement stands on, a package registering the same name **either silently winning or
silently losing is equally unacceptable here** — so it fails loudly instead.

### Diagnostic for an unregistered name

A name that is in neither the built-ins nor the registered entry-points is rejected
with `ValueError`, and the message carries **the value received**, **the built-in list**
(`hmac`), and **the entry-points actually registered at that moment** (or "none" if
there are none) together.

### entry-point load failure

When something is registered but its value (`module:attr`) cannot be imported,
`open_token_provider` translates the `ImportError` to `DriverError` (preserving the
cause chain) — the same "ONE ERROR TYPE OUT" rule as §8.

### Verifying with the TCK

An external provider subclasses `lnpl.testing.TokenProviderTCK` and runs it
in its own CI:

```python
import unittest
from lnpl.testing import TokenProviderTCK

class MyOidcProviderTCKTest(TokenProviderTCK, unittest.TestCase):
    def make_provider(self):
        return MyOidcProvider(...)

    def make_foreign_issuer_provider(self):
        return MyOidcProvider(..., issuer="somebody-else")
```

`TokenProviderTCK` is a pure mixin like `RepositoryDriverTCK`. It asserts D6 (a
closed list of 7 items): ① a valid token passes, ② a forged signature is rejected, ③
`alg: none` is rejected, ④ an `iss` other than expected is rejected, ⑤ an `aud` mismatch
is rejected, ⑥ expiry is rejected, ⑦ an alg outside the allowlist is rejected. ③ and ⑦
are the crux — letting a token pick its own algorithm is exactly where `alg: none` and
the confusion attack that uses an RS256 public key as an HMAC secret take aim (the
`ACCEPTED_ALGS` comment in `drivers.py`). The example of the built-in
`HmacTokenProvider` verified with this TCK is
`impl/tests/test_token_contract.py::HmacTokenProviderTCKTest`.

The lesson of issue #115 applies unchanged: a reference implementation alone cannot
prove that the TCK itself has discriminating power — that is, that it actually fails a
wrong implementation. `impl/tests/test_token_contract.py`'s `_NoSignatureCheckProvider`
(a provider that skips signature verification) is that negative control: running the
TCK's signature-forgery case alone **fails** on this provider and **passes** on
`HmacTokenProvider` — both results carry `testsRun == 1`, guaranteeing the case was not
silently skipped (`TokenTCKDiscriminatesTest`).

### Why there is no `--jwks-url` (D4)

For a real RS256/ES256 implementation to talk to a real IdP, it usually must fetch
public keys from a JWKS (JSON Web Key Set) endpoint, pick one of several keys by the
`kid` (key id) claim, cache the result, and re-fetch on expiry/rotation. These four —
fetching, `kid` selection, caching, rotation — form a small subsystem of their own, and
if the core took it on it would break two things at once: the stdlib-only principle (an
HTTP fetch and a cache policy need a separate dependency) and the boundary D1 drew (for
the same reason the core chose not to implement RS256 signature verification itself,
JWKS fetching and caching are also a real-implementation detail). So the `--jwks-url`
flag is out of scope this time — an external package registering via the `lnpl.tokens`
SPI owns those four with its own configuration. That `open_token_provider`'s factory
takes no arguments (the "Registration" section above) is a result of the same decision:
the core parses no JWKS configuration string of any shape.

## 10. SPI: external cache and network driver registration (issues #131 + #132)

This opens the same shape as §8/§9 for two capabilities: cache (`redis`) and network
(`NetworkCall`). Both boundaries use the same discipline as `lnpl.drivers` in §8 — a
built-in scheme is checked **before** the entry-points lookup so it can never be
shadowed (winning silently like `sqlite`/`fake` in §8, not failing loudly like `hmac` in
§9); the message for an unregistered scheme carries the value received, the built-in
list, and the registered entry-points list together; and an entry-point load failure
translates the `ImportError` into `DriverError` instead of letting it escape as-is
("ONE ERROR TYPE OUT").

### Registration

An external package's `pyproject.toml`:

```toml
[project.entry-points."lnpl.caches"]
redis = "my_lnpl_redis:make_cache"

[project.entry-points."lnpl.networks"]
pooled-http = "my_lnpl_pool:make_network"
```

`my_lnpl_redis.make_cache`/`my_lnpl_pool.make_network` are callables that each take
one `<arg>` (the text after the colon, exactly as written) and return a
`CacheDriver`/`NetworkDriver` respectively — the same shape as `lnpl.drivers`'s
`factory(<arg>)`, unlike `lnpl.tokens`'s argument-less factory (§9). When the package is
installed, `--cache redis:<dsn>` or `--network pooled-http:<config>` finds and calls
that factory — the core side has not a single `if` statement for this scheme.

A real example of this shape is
[`lnpl-redis`](https://github.com/choiyounggi/lnpl-redis) (issue #143) — a `CacheDriver`
(redis-py 8) that registers as `redis = "lnpl_redis:make_cache"`, whose own
Testcontainers CI runs this repo's `CacheDriverTCK` against a real redis server (the
first fulfillment on the cache side of "no binding without an integration test"). It is
also the first real use of RFC-0043's `cache_scope: "shared"` self-report — the
difference from the process-local `FakeCache` shows up in the diagnostic.

`run`/`trigger`/`serve` all genuinely use a driver opened this way. `run`/`trigger`
pass the result of `open_cache`/`open_network` straight into `Interpreter(...)`'s
`cache=`/`network=` arguments. `serve` uses a different shape than `repository` —
`repository` has per-request transaction state, so it is opened fresh per request via
`repository_factory` (§8), but `cache`/`network` have no per-request state, so, as
`network` already has (issue #101), one instance opened once when the server starts is
shared by every request's Interpreter (`serve()` → `make_wsgi_app()` → `LnplWsgiApp` →
the `Interpreter(...)` created fresh per request — the same `self.cache`/`self.network`
flows through to both).

### A built-in scheme can never be shadowed

`open_cache` checks `fake`, and `open_network` checks `fake`/`http`, **before** the
entry-points lookup. Even if some package registers under the name `fake` in
`lnpl.caches`, or under `fake`/`http` in `lnpl.networks`, that registration is never
looked up — the same reason and the same guarantee as `sqlite`/`fake` in §8
(`test_cache_spi.py::BuiltinShadowingTest`,
`test_network_spi.py::BuiltinShadowingTest`).

`--network` has, since before this SPI existed, taken the two values `fake`/`http`
with no argument (no colon) — that bare form stays byte-for-byte unchanged.
`<scheme>:<arg>` is the form this SPI newly opens, and writing a scheme that already
overlaps a built-in name with a colon, such as `http:<arg>`, is rejected as unregistered
(unless an entry-point is actually registered under that name) — only bare `http` is
intercepted by the built-in, not `http:...`.

### Diagnostic for an unregistered scheme

A scheme that is in neither the built-ins nor the registered entry-points is
rejected with `ValueError`, and the message carries **the value received**, **the
built-in list** (`fake` for `open_cache`, `fake, http` for `open_network`), and **the
entry-points actually registered at that moment** (or "none" if there are none)
together.

### entry-point load failure

When something is registered but its value (`module:attr`) cannot be imported, both
`open_cache` and `open_network` translate the `ImportError` to `DriverError`
(preserving the cause chain) — the same rule as §8/§9.

### The driver owns the connection pool (issue #148)

The `NetworkDriver`/`RepositoryDriver` SPI does not specify pooling — the
`call(target, payload, timeout_ms, ...)`/`execute(...)` signature was not changed by
this issue (the three contracts of §1 stand unchanged), and whether to open a fresh
connection per call or reuse one is entirely **the driver implementation's own
responsibility**. The core only hands over one shared instance (the "Registration"
section just above — `network`/`cache` are opened once when the server starts and
shared by every request's Interpreter) and never looks inside that instance to see how
it manages pooling.

The built-in `HttpNetworkDriver` (`impl/lnpl/drivers.py`) is that reference
implementation — one keep-alive connection per `(scheme, host, port)` cached in
`threading.local` (`http.client` is not thread-safe, so it cannot be widened beyond
thread-local), one reconnect-and-retry if reuse finds it stale, and eviction from the
cache if that also fails — a pattern this file established, not a contract the SPI
requires. An external driver bringing its own pool is equally valid — for example, if the
postgres backend (§3, the postgres driver section of §14) needs a real connection pool,
it can keep a driver-native pool such as `psycopg_pool.ConnectionPool` inside its own
implementation. What `close()` cleans up is likewise the driver's own call —
`HttpNetworkDriver.close()` closes **only the connection the calling thread cached**
(a connection another thread opened must be closed by that thread's own `close()` — a
fundamental limitation of a thread-local pool, not a bug).

The ceiling the postgres backend shows under high load, when it has not brought a
real connection pool, has already been measured and root-caused:
[docs/postgres-load-ceiling.md](postgres-load-ceiling.md).

### Verifying with the TCK

An external cache driver subclasses `lnpl.testing.CacheDriverTCK` and runs
it in its own CI:

```python
import unittest
from lnpl.testing import CacheDriverTCK

class MyRedisDriverTCKTest(CacheDriverTCK, unittest.TestCase):
    def make_cache(self):
        return MyRedisDriver(...)

    def advance(self, ms):
        time.sleep(ms / 1000)   # 또는 스토어 네이티브 만료를 그냥 기다린다
```

What it verifies: a get/set round trip, `None` instead of an exception for an absent
key, TTL expiry (`None` after calling `advance`), `ttl_ms=0` expiring immediately, an
empty value (`""`) round-tripping, overwriting the same key, and `invalidate` clearing a
key. A `CacheDriver`'s TTL can be satisfied either by clock comparison or by the store's
native expiry (e.g. Redis `SETEX`) (the `CacheDriver` docstring) — `advance(ms)` is the
hook that makes the driver itself answer "time has passed," whichever of the two it
uses.

An external network driver subclasses the existing `lnpl.testing.NetworkDriverTCK`
(issue #109, which predates this section) unchanged — this task only strengthened two
cases: whether all three of `status`/`body`/`headers` are bound even on a non-2xx
response (the existing case checked headers only on 200), and whether an empty response
body (`{}`) round-trips as itself instead of being replaced with `None`. The
retry/circuit-breaker/timeout/header-lowercasing cases are unchanged since issue #109.

Both `CacheDriverTCK` and `NetworkDriverTCK` are pure mixins that do not subclass
`unittest.TestCase` — the concrete class must multiply-inherit with `unittest.TestCase`
(the same reason as `RepositoryDriverTCK` in §8: if the mixin itself were collected, it
would run standalone with its hooks raising `NotImplementedError`).

## 11. SPI: extension diagnostics registration (issue #138, RFC-0042)

The contract RFC-0042 settled: let an extension emit its own failure mode as a
diagnostic without touching the closed `CODES` in `impl/lnpl/diagnostics.py`. The same
shape as §8/§9 — the core keeps the `lnpl.diagnostics` entry-points group open, and right
after `compile` (and `--json`) builds the IR, it runs every registered extension's
`check` against that IR.

### Registration

An external package's `pyproject.toml`:

```toml
[project.entry-points."lnpl.diagnostics"]
kafka = "my_lnpl_kafka:register"
```

`my_lnpl_kafka.register` is a callable invoked **with no arguments** that returns a
dict of this shape:

```python
def register():
    return {
        "codes": {
            "at-least-once": {"severity": "info",
                              "description": "outbox relay is at-least-once only"},
        },
        "check": lambda document, config: [
            {"code": "at-least-once", "where": "emit userCreated",
             "subject": "emit userCreated",
             "message": "...", "line": 12},
        ],
    }
```

The entry-point's name itself is the **prefix** — it is never declared separately.
The `code` in the dict `check` returns is bare (e.g. `"at-least-once"`), and the core
normalizes it to `<prefix>/<code>` (e.g. `"kafka/at-least-once"`). `config` is a reserved
argument that is always `{}` for now (a configuration channel is out of scope this time).
`check` receives only the compiled IR document — the source text or a file path is never
passed (so as to not force a second parser implementation).

### Load-time validation

`load_extensions()` rejects all of the following at load time (each violation raises
`ExtensionDiagnosticsError`, with a message in the same style as §8/§9 — carrying **the
value received**, **the rule violated**, and **the list registered up to that moment**
together):

- the prefix does not satisfy `^[a-z][a-z0-9-]{1,15}$`;
- the prefix is `lnpl`/`core` (reserved words);
- another extension loads under an already-registered prefix (one prefix, one owner);
- any code declares `severity` as `error` — an extension may only use `info`/`warning`.

### Runtime filter — an unregistered code

If `check` emits a code not in its own `codes`, only that one diagnostic is dropped
from the result and one warning line goes to stderr — it neither kills the whole
extension nor swallows it silently. This is a runtime filter, not load-time validation,
so it is not an exception.

### Opting out of `--strict`

A `<prefix>/<code>` diagnostic **never** enters `--strict`'s threshold comparison,
regardless of severity — merely installing an extension never changes the exit code of a
build that was already clean. This RFC does not even provide an opt-in to join that
comparison (§Guide-level Explanation, "What this does not do").

### Visibility — all three compile paths: CLI, wsgi, MCP

This pass exists as a single function, `extension_diagnostic_records(document)` in
`diagnostics.py` (issue #140), and all three paths that produce a compiled IR document
call it:

- `compile`/`--json` in `cli.py` — appended after the core diagnostics, carried in
  both the stderr report and the `--json` array (see "Record shape and order" above).
- The `lnpl_compile` tool in `mcp_server.py` — appended after
  `to_records(module.diagnostics)`, carried in the same order in the response's
  `diagnostics` array. If the registry load violates RFC-0042, `ExtensionDiagnosticsError`
  propagates, and `tools/call`'s existing compile-failure handling (the same path as any
  other compile failure) translates it into an `isError` response.
- `build_app` in `wsgi.py` — since this function never exports the compiled
  `module.diagnostics` anywhere (no log, no endpoint, no app state), extension records
  are printed to stderr one line at a time right after compilation — the same
  `format_lines_from_records` rendering as `lnpl compile`'s stderr report. A registry
  load failure becomes `WsgiConfigError` through the same path as an existing compile
  failure such as `LowerError`, blocking the app from starting at all (not a
  request-time crash).

All three paths see the same record (the same registration, the same filtering, the
same 6-key shape); only the packaging — where it is exported to — differs by path.

### TCK

Unlike §8/§9, extension diagnostics has no `lnpl.testing` TCK yet — what there is to
verify is much shallower than "one diagnostic comes out" (only the registration contract
and the runtime filter), so it will be added later if needed once real consumers exist.

## 12. SPI: external generator registration (issue #139)

`README.md` declares the Semantic IR a hub, but if every consumer that draws output
from that hub — the OpenAPI document, and further out, GraphQL, gRPC, a frontend SDK, k8s
manifests, everything CHARTER §Auto Generation promises — were all hardwired into the
core, that claim would never have been put to the test. The principle §5 already stated
for a real broker binding — "the core owns only the contract; the real implementation
differs by organization" — applies the same way to generated output. What this section
opens is a slot: the core ships the deployment generators `compose`/`k8s` built in
(issue #189, the two sections below), and GraphQL/gRPC generators are not built by the
core but filled in by external packages (the same principle as "no binding without an
integration test," issue #115).

The contract is exactly the [protoc plugin model](https://protobuf.dev/reference/cpp/api-docs/google.protobuf.compiler.plugin/):
a generator returns `generate(document, options) -> {relative_path: bytes}`, and
**writing that map out as real files is the core's job**. Not giving the generator
filesystem permission lets the core own the overwrite policy and the path-escape check
in exactly one place (`generators.run_generator`) — the same reason protoc's
`CodeGeneratorResponse` never writes files directly.

### Registration

An external package's `pyproject.toml`:

```toml
[project.entry-points."lnpl.generators"]
graphql = "my_lnpl_graphql:generate"
```

`my_lnpl_graphql.generate` **is itself** the callable that takes `(document,
options)` and returns `{relative_path: bytes}` — unlike §8's driver factory
(`module:factory` is a two-step shape where a function takes an argument and builds a
driver), the protoc plugin model has no per-generation state to build fresh, so it is one
step. `document` receives exactly the dict that is byte-identical to `.lir.json`
(including provenance, RFC-0042) — the source text or a file path is never passed (so as
to not force a second parser implementation, the same reason as §11). `options` is the
`{KEY: VALUE}` string dict that `lnpl generate ... --set KEY=VALUE` populates (issue
#189; `--set` can repeat, and it ends with rc 2 if there is no `=`, the KEY is empty, or
the same KEY appears twice). The meaning and validation of keys belong to each generator
separately — `compose`/`k8s` reject a key outside their closed key set and an empty
value, while `openapi` ignores options.

When the package is installed:

```
lnpl generate graphql <src.lnpl> --out ./generated
```

finds and calls that factory — the core side has not a single `if` statement for this
name. `--out` is required (to prevent littering the cwd, for explicitness).

### A built-in name can never be shadowed

`resolve_generator` checks `openapi` **before** the entry-points lookup. Even if some
package registers under the name `openapi` in `lnpl.generators`, that registration is
never looked up — there is no path at all by which a built-in gets shadowed
(`test_generator_spi.py::BuiltinShadowingTest`).

### Diagnostic for an unregistered name

A name that is in neither the built-ins nor the registered entry-points is rejected
with rc 2, and the message carries **the value received**, **the built-in list**, and
**the entry-points actually registered at that moment** (or "none" if there are none)
together — the same "triple miss" discipline as §8.

### entry-point load failure, and the generator's own exception

When something is registered but its value cannot be imported, or the loaded
`generate()` itself raises an exception, it is translated to `GeneratorError`
(preserving the cause chain) — §8's "ONE ERROR TYPE OUT" rule applies the same way here.
`lnpl generate`'s exit code is rc 2, the same as other compile-family failures such as
`lnpl openapi`.

### The core writer rejects a path escape

Each key the generator returns is validated before being written under `--out`: an
absolute path, a path that points outside `--out` via `..`, and a path that points
outside via a symlink are all rejected (rc 2, saying which key and why) — validation
finishes entirely before anything is written, so one key escaping never leaves the rest
partially written. An empty `{}` is a valid return — 0 files, rc 0.

### `openapi` — a built-in generator and the first dogfooding case

`generate_files(document, options)` in `openapi.py` is the built-in generator
registered with this SPI: it reuses the existing `generate(document, version=...)` (the
function `cli.py`/`wsgi.py`/several tests import by name) as-is, takes the spec it
produces, serializes it with the same formatting as `cli.py`'s `_dump` (2-space JSON,
`ensure_ascii=False`, LF-terminated) into bytes, and returns `{"openapi.json": <bytes>}`
— the adapter is named `generate_files`, not `generate`, to avoid a name collision. The
existing `generate()` and the `lnpl openapi` subcommand have had their behavior changed
not at all: `<dir>/openapi.json`, which `lnpl generate openapi <src> --out <dir>`
writes, is byte-identical to what `lnpl openapi <src>` emits to stdout
(`test_generator_spi.py`'s differential test).

### `compose` — a built-in deployment generator (issue #189)

`lnpl generate compose <src.lnpl> --out <dir>` writes exactly one file,
`<dir>/compose.yaml`. The same input and options give the same bytes (no timestamps, no
host paths, ASCII, LF). Since no YAML library is used (the core's only runtime
dependency is jsonschema), every place a value is interpolated is escaped as a
double-quoted YAML string. A value the generator cannot know (an image tag, a source
path) is left as a placeholder with a `# PLACEHOLDER:` comment, filled in via options.

| Option | Default | Meaning |
|------|--------|-----|
| `image` | `ghcr.io/OWNER/linkly:VERSION` (placeholder) | The app image. Official tags are `vX.Y.Z`/`X.Y` and `latest` is never published, so the default is deliberately an unusable value |
| `port` | `8000` | The host port (1-65535). Published only as `127.0.0.1:<port>:8000` (the container port 8000 comes from `EXPOSE` in `docker/Dockerfile`) |
| `source` | `./app.lnpl` (placeholder) | The host path of the `.lnpl` file. A relative path is resolved against the compose file's location ([Compose spec](https://github.com/compose-spec/compose-spec/blob/main/05-services.md)). Bind-mounted read-only to `/srv/lnpl/app.lnpl` in the container |
| `postgres_image` | `postgres:16` | The image when the `postgres` capability is present (the version `docs/postgres-load-ceiling.md` measured) |
| `redis_image` | `redis:7` | The image when the `redis` capability is present |

**Environment variables.** Only names found in `docs/serving.md`'s table are used.
Always `LNPL_SOURCE`. If `jwt` is declared, `LNPL_JWT_SECRET_ENV=LNPL_JWT_SECRET`. For
every NetworkCall target called by logical name, `LNPL_ENDPOINT_<대상 대문자>`
(`<target uppercased>`) (the
value is `http://endpoint-placeholder.invalid`, using the reserved `.invalid` domain, so
forgetting to set it fails at DNS, not against someone else's host; if the target name
does not fit the environment-variable name rule `[A-Za-z_][A-Za-z0-9_]*` — e.g.
`foo:bar` — the compiler accepts it but the generator rejects it, naming that target).
Even when `postgres`/`redis` are declared, `LNPL_BACKEND`/`LNPL_CACHE` appear **only as
comments**: the official image bundles only the `fake`/`sqlite` backend, so these are
uncommented when using a derived image (`docs/RELEASING.md`) that has `lnpl-postgres`,
etc., installed. Variables the generator does not export (add by hand if needed):
`LNPL_JWT_SECRET_FILE`, `LNPL_CLOCK`, `LNPL_LOG_FORMAT`, `LNPL_TRACE_EXPORTER`,
`LNPL_IDEMPOTENCY_TTL_S`, `LNPL_METRICS`, `LNPL_CAPTURE_ON_FAILURE`,
`LNPL_TRUST_INCOMING_TRACE`, `LNPL_RATE_LIMIT`, `LNPL_CONFIG`, `LNPL_PROFILE`,
`LNPL_NETWORK`, `LNPL_TOKEN_PROVIDER`, `LNPL_JWT_ISSUER`.

**Secrets by name only.** The secret variables the document names by name
(`LNPL_JWT_SECRET`, the `capability http` `auth ... from <ENV>` variable) and the
`postgres` service's `POSTGRES_PASSWORD` appear with no value, only as the reference
`"${VAR:?set VAR before docker compose up}"`. If it is absent from the host environment,
compose refuses to start — both `up` and `down` interpolate, so both must be preceded by
an `export`.

**capability → service.** `postgres` → the `postgres` service (named volume
`postgres-data`, `pg_isready` healthcheck), `redis` → the `redis` service (`redis-cli
ping` healthcheck); the app attaches `depends_on: condition: service_healthy` to each
service that gets created. Service order is app, postgres, redis, regardless of
declaration order. `jwt` and `capability http <이름>` (`<name>`) only create environment variables.
With zero capabilities, only the app service appears. A name not in the mapping above is
skipped with one line to stderr:
`lnpl generate compose: capability 'foo' has no deployment mapping; skipped (mapped: postgres, redis, jwt, http <name>)`.

**The healthcheck is `/-/readyz`.** Compose never restarts an unhealthy container, so
a compose healthcheck is not a liveness probe. It is used in exactly two places —
`depends_on: condition: service_healthy` and `docker compose up --wait` — and both ask
"can it serve right now," which is readiness. `/-/readyz` checks storage and the jwt
secret variable too, while `/-/healthz` answers healthy even with a broken backend. The
probe is `python -c "import urllib.request;
urllib.request.urlopen('http://127.0.0.1:8000/-/readyz', timeout=3)"` because the image
has no curl/wget, and on a 503 `urlopen` raises, ending with a non-zero code
([healthcheck / depends_on](https://github.com/compose-spec/compose-spec/blob/main/05-services.md)).

**`$` becomes `$$`.** Since Compose interpolates `$VAR`/`${VAR}` inside a value, a
`$` in an option value is doubled to `$$` to make it literal ([interpolation
rules](https://github.com/compose-spec/compose-spec/blob/main/12-interpolation.md)).
`docker compose config` prints this value back in the same `$$` form.

### `k8s` — a built-in deployment generator (issue #189)

`lnpl generate k8s <src.lnpl> --out <dir>` writes exactly one file, `<dir>/k8s.yaml`:
a ConfigMap, a Deployment, a Service, then one CronJob per `on schedule` event, then an
Ingress/HorizontalPodAutoscaler/PodDisruptionBudget/NetworkPolicy (app) turned on by
option, and finally one trigger NetworkPolicy per CronJob — in that order, separated by
`---`, in one file (issue #236). A Secret object is still never created.

| Option | Default | Meaning |
|------|--------|-----|
| `image` | `ghcr.io/OWNER/linkly:VERSION` (placeholder) | Same as `compose` |
| `name` | The module name (the source file's name) | The name of the Deployment/Service and the `app.kubernetes.io/name` label value. Must be a DNS-1035 label (starts with a lowercase letter, lowercase/digits/`-`, ends alphanumeric, ≤63 chars). Required because it is the Service name — on violation it is rejected, never rewritten (set with `--set name=<label>`) |
| `replicas` | `1` (placeholder) | An integer ≥ 1. The generator does not know the replica count |
| `cpu_request`, `cpu_limit`, `memory` | None | A Kubernetes quantity (`100m`, `0.5`, `256Mi`). If none are given, no `resources:` appears, only a BestEffort comment. `memory` goes into both requests and limits |
| `ingress_host` | None | Creates a `networking.k8s.io/v1` Ingress. Rejected unless it is a DNS-1123 subdomain (lowercase/digits/`-`/`.`, each label starts and ends alphanumeric, ≤253 chars). The path is one `Prefix` per served service segment (`/<service>`) — the `/` and `/-/` paths are never carried |
| `hpa_min`, `hpa_max`, `hpa_cpu` | None | Give all three together. An `autoscaling/v2` HPA (CPU `averageUtilization`). `hpa_min` ≥ 1, `hpa_max` ≥ `hpa_min`, `hpa_cpu` 1-100. Requires `cpu_request` and cannot be given together with `replicas`. When given, the Deployment's `replicas:` line is omitted |
| `pdb` | `false` | If `true`, a `policy/v1` PodDisruptionBudget (`minAvailable: 1`). Any value other than `true`/`false` is rejected |
| `network_policy` | `false` | If `true`, a default-deny NetworkPolicy for the app pod and a trigger NetworkPolicy per CronJob. Any value other than `true`/`false` is rejected |
| `egress_cidrs` | None | A comma-separated CIDR list (`203.0.113.0/24,2001:db8::/32`). Every entry requires a prefix length, forbids host bits, and forbids whitespace. Rejected if given without `network_policy=true` |

**Probes and termination.** `livenessProbe` is `/-/healthz`, `readinessProbe` is
`/-/readyz` (both on the named container port `http`=8000; the timing fields are
Kubernetes defaults — the generator has no measured value). `terminationGracePeriodSeconds:
30` matches `lnpl serve --grace-period`'s default (30.0) and gunicorn's
`graceful_timeout` (30); `deploy_gen.GRACE_PERIOD_S` holds this value and a test checks
the two agree (`docs/serving.md` "SIGTERM graceful drain").
References: [Pod lifecycle](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/),
[liveness/readiness/startup probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/).

**Objects you must create yourself.** The generated manifest refers to them only by
name.

```bash
kubectl create configmap <name>-source --from-file=app.lnpl=<path>
kubectl create secret generic <name>-secrets --from-literal=<KEY>=<value>
```

`--from-literal` is one per `secretKeyRef` key (`postgres` → `LNPL_BACKEND`, `redis`
→ `LNPL_CACHE`, `jwt` → `LNPL_JWT_SECRET`, the `capability http` `auth` variable).
References: [ConfigMap](https://kubernetes.io/docs/concepts/configuration/configmap/),
[Secret](https://kubernetes.io/docs/concepts/configuration/secret/). The environment
variables (`LNPL_SOURCE`, `LNPL_JWT_SECRET_ENV`, `LNPL_ENDPOINT_*`) are injected by the
ConfigMap `<name>-config` via `envFrom`. Backing services (DB, cache) are the operator's
choice, so none are created. An unknown capability is skipped with the same one-line
stderr as `compose` (`lnpl generate k8s: ...`).

**The schedule-trigger CronJob (issue #236).** One `batch/v1` CronJob is created per
`on schedule` event. Its name is `<name>-<event-slug>` and must be a DNS-1035 label of
≤52 characters (the CronJob controller appends 11 characters to the Job name). On
violation it is rejected, never rewritten. `schedule`/`timeZone` come from the
declaration (`daily at 06:30 UTC` → `"30 6 * * *"`, `"UTC"`). `concurrencyPolicy:
Forbid`, `backoffLimit: 0` (a POST that ended in a timeout may already have run the
workflow, so it is never auto-retried), `startingDeadlineSeconds: 300`,
`activeDeadlineSeconds: 600`. The container runs the app image via `python -B -c` to
POST `{}` to `http://<name>:8000/-/schedules/<event-slug>` (the Service, not the
Ingress). If the owning service declares `security jwt`, each run mints a 5-minute token
(aud `-`, `sub` = the CronJob name, role = the role the service requires) via `lnpl
token --path /-/schedules/<slug>`, reading `LNPL_JWT_SECRET` from `<name>-secrets` via
`secretKeyRef`. This is the only Secret key this pod ever receives (it never gets
`LNPL_BACKEND`, `LNPL_CACHE`, or the http `auth` variable). Hardening:
`automountServiceAccountToken: false`, `runAsNonRoot: true` with `runAsUser: 1000`
(`docker/Dockerfile`'s `USER linkly` is a name, so kubelet rejects `runAsNonRoot` without
a numeric uid), `seccompProfile: RuntimeDefault`, `allowPrivilegeEscalation: false`,
`readOnlyRootFilesystem: true`, `capabilities.drop: ["ALL"]`. The script prints only the
path and the HTTP status and never prints the token or the key through any channel. The
image must be a lnpl release after 0.9.0 or later (including support for `lnpl token
--path /-/schedules/...`) — an older image ends every run with rc 2 `is not served`. If
the server uses an issuer, put `LNPL_JWT_ISSUER` in the ConfigMap `<name>-config`, not
the Deployment's `env` (both pods read it via `envFrom`) — otherwise every run gets 401.
If `LNPL_TOKEN_PROVIDER` is not `hmac`, the generated trigger cannot mint a token — it
would turn the CronJob into an IdP client.

**What privilege the trigger pod holds (the security model).** (a) Since this pod
holds the server's one and only HS256 signing key, a process inside it can mint a token
of any audience, role, subject, or lifetime — neither `lnpl token` nor the verifying
side has an upper bound on lifetime (measured: `--ttl 365d` → 31536000 seconds). That is,
it can fully impersonate every caller of every `security jwt` route until the key is
rotated. (b) If it is the trigger token, not the key, that leaks: because aud is `-`, it
is accepted by every auth-required `/-/schedules/<slug>`/`/-/events/<slug>` route whose
role matches, it is not accepted by `/<service>/<workflow>` routes, and it lasts at most
5 minutes. (c) Why this is accepted: anyone who can create a Pod/Deployment/CronJob in
the namespace can already read that Secret (the Kubernetes Secret docs), the app pod
holds the same key too, and the trigger pod listens on nothing and has no API token.
Mitigations: one Secret key, no service account token, a restricted pod, and with
`network_policy=true`, no inbound connections and outbound limited to kube-dns and the
app pod's port 8000. A DNS query is still a path out, and none of this helps if the image
or the app is compromised. (d) Rotation: change the `LNPL_JWT_SECRET` value in
`<name>-secrets` and restart the Deployment (env is read at pod start, and the env path
carries only one key — current+previous key rotation is only possible via an
`lnpl.secrets` provider). The next Job pod reads the new value on its own. (e)
Follow-ups (not in this release): a verify-side trigger-only key that works only for
audience `-`, a per-route trigger audience.

**Ingress.** The path is one `Prefix` per served service segment. The `/-/` routes
(schedule/event triggers, `/-/healthz`, `/-/readyz`, `/-/metrics`) are never carried —
because a schedule/event trigger has no auth unless the service declares `security jwt`,
and an ops route is never authenticated. `ingressClassName` and `tls` are absent — add
them with a patch.

**PodDisruptionBudget.** With 1 replica, `minAvailable: 1` permits zero voluntary
evictions, so a node drain never finishes (the generated comment also says so). Keep at
least 2 replicas.

**NetworkPolicy's limits.** Since a peer is only a pod, a namespace, or an IP block,
a `capability http` endpoint hostname cannot be expressed — write an external backend
with `egress_cidrs` instead (`ipBlock` is for addresses outside the cluster). DNS egress
assumes a pod labeled `k8s-app: kube-dns` in `kube-system` and a CNI that enforces
NetworkPolicy. If NodeLocal DNSCache (169.254.20.10) is used, the kube-dns rule does not
match — add a policy yourself, on both the app and trigger labels, allowing UDP/TCP 53
to `169.254.20.10/32`. A backend inside the cluster needs a policy you add yourself
(policies are additive; an example is below). The app policy accepts TCP 8000 from any
pod in the cluster, so any pod can call the unauthenticated
`/-/schedules/<slug>`/`/-/events/<slug>` and ops routes — declare `security jwt` on the
owning service, or narrow `from` in a policy you write yourself (the generator knows
neither the namespace nor the ingress controller).

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: "app-to-postgres"
spec:
  podSelector:
    matchLabels:
      "app.kubernetes.io/name": "app"
  policyTypes:
    - "Egress"
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              "kubernetes.io/metadata.name": "db"
          podSelector:
            matchLabels:
              "app.kubernetes.io/name": "postgres"
      ports:
        - protocol: "TCP"
          port: 5432
```

The same for redis, on port 6379. Replace `app` with `<name>` and `db` with the
backend's namespace.

**Checking.** In this environment, `kubectl apply --dry-run=client -f k8s.yaml`
never finishes without an API server: rc 1 `failed to download openapi: Get
"http://localhost:8080/openapi/v2?timeout=32s"`, and even with `--validate=false`, rc 1
`couldn't get current server API group list` (measured, kubectl v1.30.5). The closest
check usable without a cluster is kubeconform (it fetches its schema from the network):

```bash
docker run --rm -i ghcr.io/yannh/kubeconform:v0.6.7@sha256:0925177fb05b44ce18574076141b5c3d83235e1904d3f952182ac99ddc45762c -strict -summary -kubernetes-version 1.30.0 - < k8s.yaml
```

`tests.test_deploy_generators`'s `KubeconformTest` checks every generated object (32
objects) with this command, and also verifies that a deliberately broken document comes
back `Invalid: 1`. If docker is absent, this test is skipped; with
`LNPL_REQUIRE_KUBECONFORM=1` it fails instead.

kubeconform does not check object names (measured: it passes `Pg_Redis`). Names are
blocked by the generator's own DNS-1035 rule.

**Regenerating goldens.** The golden files
(`impl/tests/golden/deploy/<fixture>/`) are regenerated only via the CLI — from the repo
root, with no `--set`,
`PYTHONPATH=impl .venv/bin/python -m lnpl generate compose impl/tests/golden/deploy/<fixture>.lnpl --out impl/tests/golden/deploy/<fixture>`
(the same for `k8s`), then read `git diff impl/tests/golden/deploy` and commit it. There
is no automatic-regeneration switch.

### Verifying with the TCK

An external generator subclasses `lnpl.testing.GeneratorTCK` and runs it in its own CI:

```python
import unittest
from lnpl.testing import GeneratorTCK

class MyGraphQLGeneratorTCKTest(GeneratorTCK, unittest.TestCase):
    def make_generator(self):
        return my_lnpl_graphql.generate
    def make_out_dir(self):
        ...  # a fresh, empty, writable directory; clean it up yourself
```

What it verifies: determinism (the same document twice → the same map), and three
things the core writer guarantees in common — rejecting a path-escaping key, allowing an
empty return, and translating the generator's own exception into a single
`GeneratorError`. The latter three hold for free for any generator, as long as it passes
through the same writer `lnpl generate` uses, so `GeneratorTCK` proves those three
directly with a fixed fixture generator (unlike the §8/§9 TCKs, it does not re-verify the
target driver/generator itself every time).

## 13. SPI: driver conformance reporting (issues #138/#140, RFC-0043)

What §8/§9/§10 open is only "which driver gets loaded" — there was no way for the
core to know **how** that driver behaves (delivery guarantee, isolation level, cache
scope, claim composition). What RFC-0043 opens is not a new entry-points group but one
self-report attribute **optionally** attached to the same factory §8/§9/§10 already
register — the registration itself is unchanged.

### How to report

Attach a class/static attribute `lnpl_enforcement: dict` to the object `ep.load()`
returns (the factory callable itself, or, when the callable is a class, that class):

```python
class KafkaOutboxRepository(RepositoryDriver):
    lnpl_enforcement = {"delivery": "at-least-once"}

    def __init__(self, arg):
        ...

def make_driver(arg):
    return KafkaOutboxRepository(arg)
```

The only way to read it is `getattr(loaded, "lnpl_enforcement", None)` — no
instantiation, no connection (the same layer as §8 stopping at `ep.load()` in
`_registered_entries`). **Check exactly what `loaded` points to**: if, as in the example
above, `pyproject.toml` registers `kafka = "my_pkg:make_driver"`, `ep.load()` returns
`make_driver` — `lnpl_enforcement` must be attached to that function object to be read.
If a class is registered directly as the entry-point's value (`kafka =
"my_pkg:KafkaOutboxRepository"` — a class is also a valid callable, invoked as
`Class(arg)`), attach it as the class's own attribute instead. Whatever is registered,
the one rule is that the attribute must be on the exact object `ep.load()` actually
returns.

If it is absent (`None`), that means "no report" and no diagnostic is emitted —
not declaring an enforcement and saying nothing about whether it is enforced are
different states. The built-in drivers (`fake`/`sqlite`/`hmac`, etc.) do not have this
attribute.

### The report vocabulary (a closed table, owned by the core)

| axis (dict key) | Value shape | Value vocabulary |
|------------------|---------|---------|
| `delivery` | scalar | `at-most-once` \| `at-least-once` \| `exactly-once` |
| `isolation` | scalar | `read-uncommitted` \| `read-committed` \| `repeatable-read` \| `serializable` |
| `cache_scope` | scalar | `process-local` \| `shared` |
| `token_claims` | `list[str]` | A claim name (a free string) |

An unknown key, and a value outside a known key's vocabulary, are silently ignored
(no warning) — a driver reporting a new axis ahead of the core never leads to a load
failure. If `token_claims` is not a `list[str]`, it is likewise ignored.

### How the core composes the diagnostic

No driver ever has to register its own `lnpl.diagnostics` extension (§11) — fill in
one report, and the core assembles the code, severity, and wording. Declaring
`capability postgres`/`redis`/`jwt`/`http <Name>` activates the storage/cache/token/network
slot respectively (the same vocabulary as `CAPABILITY_SLOT`, `SLOTS` in
`impl/lnpl/capabilities.py`), and once a slot is active, it cross-checks **every
installed driver** in that slot's entry-point group — it never guesses which driver
`--backend` would actually pick for that run. The diagnostic code is
`<entry-point 이름>/<axis-code>` (`<entry-point name>/<axis-code>`)
(a scalar axis is `<axis>-<값>` (`<axis>-<value>`), `token_claims` is the fixed code
`token-claims`), all at `info`, and never participates in `--strict` (the same
non-participation rule as §11, already applying to every code containing `/`).

```
$ lnpl compile app.lnpl
info: kafka/delivery-at-least-once [line 12] emit userCreated — the
installed kafka driver guarantees at-least-once delivery only; userCreated
may be delivered more than once
0 info, 0 warning(s), 0 error(s)
```

This pass is `enforcement_diagnostic_records(document)` in `capabilities.py`, called
at the end of the same shared layer as §11 (`diagnostics.extension_diagnostic_records`),
so all three paths — `lnpl compile`, `build_app` in `wsgi.py`, and the MCP
`lnpl_compile` — receive the same record (the same wiring as §11's "Visibility"
section).

### Seeing it in the catalog

Each item in `slots.<slot>.registered` of `lnpl capabilities --json` attaches an
`enforcement` key only when a report exists — `{axis: value}`; with no report, the key
itself is absent (not an empty `dict`). For the measured table-rendering contract, see
`docs/ENFORCEMENT-MATRIX.md` §B.

## 14. Backup and restore (issue #147)

### sqlite — copying the file is invalid; `.backup`/`VACUUM INTO` is canonical

As the Concurrency section of §3 established, this driver turns on
`journal_mode=WAL` once, when the file is created. In WAL mode, some of the latest data
lives not in the main `.db` file but in a separate `-wal` file, merged into the main file
later by a checkpoint — the official SQLite documentation describes exactly this file
structure ([Write-Ahead Logging](https://sqlite.org/wal.html)). So copying only the main
file, as in `cp store.db store.db.bak`, either misses a recent commit that lives only in
`-wal`, or, if caught mid-checkpoint, yields an outright inconsistent snapshot — this
risk is recorded with a measured case on the official SQLite forum too ([Hot backup
database in WAL mode by coping](https://sqlite.org/forum/forumpost/2ea989bbe9)).

The canonical approach is one of two:

- **`sqlite3 store.db ".backup backup.db"`** (or the language binding's online
  backup API, `sqlite3_backup_init`/`_step`/`_finish`) — produces a transactionally
  consistent snapshot without blocking writes
  ([SQLite Backup API](https://sqlite.org/backup.html)).
- **`VACUUM INTO 'backup.db'`** — leaves the original untouched and creates a new,
  vacuumed (defragmented) file. An alternative to the backup API; the resulting file is
  minimal size, so it may do less filesystem I/O
  ([`VACUUM` — SQLite Query Language](https://sqlite.org/lang_vacuum.html)).

Run both as a connection/process separate from the one this driver opens. The
command that wraps the former (the online backup API) is `lnpl db backup` below.

### sqlite — `lnpl db backup` (issue #238)

`lnpl db backup --backend sqlite:<path> --out <path>` opens a connection separate
from the original, using the SQLite online backup API, to produce a consistent copy. It
is safe even while `serve` is writing — a committed row goes into the copy even if it
lives only in `-wal`, and a row from a not-yet-committed transaction does not. The copy
is always a new file: an existing `--out` is never overwritten. No `-wal`/`-shm` file is
left beside the copy. It never cross-checks rows against a declaration, so it takes no
`.lnpl` source argument. Since the original is only read, it needs no write permission on
the original's directory (a backup sidecar with the data volume mounted `:ro`). But
SQLite needs the `-shm` file to exist or be creatable to read a WAL store, so if every
writing process has exited, leaving no `-shm`, and the store sits in a read-only
directory, it is rejected with `cannot read ... as a sqlite database` (rc 2).

Measured: 2026-10-29, `git rev-parse --short HEAD` = cc54829 + the t6 working tree,
Python 3.13.1 / SQLite 3.53.4, run via `python -m lnpl` (= the `lnpl` console script).

Backup (a `store.db` with 3 rows):

```bash
lnpl db backup --backend sqlite:store.db --out backup.db
```

stdout:

```
{
  "out": "backup.db",
  "rows": 3
}
```

stderr is empty and rc 0.

The same command again — `--out` already exists:

```bash
lnpl db backup --backend sqlite:store.db --out backup.db
```

stderr:

```
error: db backup: --out already exists, refusing to overwrite: 'backup.db'
```

stdout is empty and rc 2.

A non-sqlite backend:

```bash
lnpl db backup --backend fake --out backup2.db
```

stderr:

```
error: db backup: backend 'fake' does not support online backup; for postgres use pg_dump (see docs/backends.md §14)
```

stdout is empty and rc 2.

postgres — the message names only the scheme and never carries the DSN (including the password):

```bash
lnpl db backup --backend postgres:postgresql://app:example-password@db.invalid/app --out backup2.db
```

stderr:

```
error: db backup: backend 'postgres' does not support online backup; for postgres use pg_dump (see docs/backends.md §14)
```

stdout is empty and rc 2.

| rc | Meaning |
|----|-----|
| 0 | Backup complete — a `{"out", "rows"}` JSON on stdout (`rows` is the row count of `lnpl_rows` in the copy) |
| 1 | A sqlite error during copying — the partial file this run created is deleted |
| 2 | An operator error — a non-sqlite `--backend` (postgres is pointed to `pg_dump`), an empty `--out`, an `--out` or its `-wal`/`-shm`/`-journal` that already exists, a missing parent directory, a missing original, a non-sqlite file, a file with no `lnpl_rows`, or a closed WAL store with no `-shm` in a read-only directory |

### Verifying a restore

1. Stop every writing process (`serve`, etc.).
2. Delete `store.db`, `store.db-wal`, `store.db-shm`.
3. Copy the backup file to `store.db` (`cp backup.db store.db`).
4. Cross-check against the declaration — expect `[]` and rc 0 (the first command
   below).
5. Check the row count — the second command's `rows` must equal the `rows` from backup
   time. The runtime image has no `sqlite3` CLI, and `db check` only prints mismatches,
   so count with this command instead. Delete `verify.db` after checking.

```bash
lnpl db check app.lnpl --backend sqlite:store.db
```

stdout (stderr is empty, rc 0):

```
[]
```

```bash
lnpl db backup --backend sqlite:store.db --out verify.db
```

stdout (stderr is empty, rc 0):

```
{
  "out": "verify.db",
  "rows": 3
}
```

This procedure is run by `RestoreRehearsalTest` in
`impl/tests/test_cli_db_backup.py` every time in CI.

### Continuous replication and PITR — Litestream

When continuous disaster recovery is needed, not a single snapshot, use
[Litestream](https://litestream.io/how-it-works/). It intercepts the WAL checkpoint
itself and incrementally streams new WAL pages to object storage (S3/R2/B2, etc.),
while also periodically keeping full snapshots — a restore downloads the nearest
snapshot and replays the changes recorded after it. Since it runs as a background
process beside this sqlite file, there is no code change on the `lnpl` side.

A runnable example is `examples/deploy/litestream-compose.yml` and
`examples/deploy/litestream.yml`; the restore and verification commands are in the
"Backup and restore (issue #238)" section of `examples/deploy/README.md`.

### The postgres driver — delegated to `pg_dump`/PITR

A deployment that uses postgres by registering an external driver (e.g.
`lnpl-postgres`, issue #121) in the `capability postgres` slot also leaves backup to
postgres's own tools: a logical backup is `pg_dump`/`pg_dumpall`, while continuous
archiving and PITR are a separate procedure based on WAL archiving — that
`pg_dump`/`pg_dumpall` itself is not a filesystem-level backup, and so cannot be used as
part of continuous archiving, is an explicit warning in the official PostgreSQL
documentation ([Continuous Archiving and Point-in-Time Recovery
(PITR)](https://www.postgresql.org/docs/current/continuous-archiving.html)). This repo
does not implement that driver — it is the responsibility of whoever implements the
`RepositoryDriver` SPI (§8).

`lnpl db backup` rejects the postgres backend with the rc 2 message above. An
example of periodic dumping is `examples/deploy/pg-dump-cronjob.yaml` (a Kubernetes
CronJob, `pg_dump -Fc`, `concurrencyPolicy: Forbid`).

## 15. SPI: external event publisher registration (issue #191, RFC-0061)

This opens the boundary for sending an emission `outbox` accumulated to a real
broker — the same discipline as §8/§10: a built-in scheme (`http`/`https`) is checked
before the entry-points lookup so it can never be shadowed, the message for an
unregistered scheme carries the scheme received, the built-in list, and the registered
entry-points list together, but **never the full target URL** (since it could carry
credentials in the userinfo) — an entry-point load failure translates the `ImportError`
into `DriverError` instead of letting it escape as-is ("ONE ERROR TYPE OUT").

### Registration

An external package's `pyproject.toml`:

```toml
[project.entry-points."lnpl.publishers"]
kafka = "my_lnpl_kafka:make_publisher"
```

`my_lnpl_kafka.make_publisher` is a callable that takes one `target` (the full URL
string given to `--target` — exactly as written, including the scheme, not just the text
after the colon) and returns an `EventPublisher`. `lnpl relay --target
kafka://broker:9092/topic` finds and calls that factory — the core side has not a single
`if` statement for this scheme.

`EventPublisher` is three methods: `publish(envelope)`, `publish_batch(envelopes)`,
`close()`. If `publish` returns without raising, it is acked; if it raises
`PublishRejected` (a permanent rejection), it is acked and a dead-letter warning is
issued; for any other `DriverError`, it is not acked and the next drain retries it.

### A built-in scheme can never be shadowed

`open_publisher` checks `http`/`https` **before** the entry-points lookup. Even if
some package registers under those two names in `lnpl.publishers`, that registration is
never looked up — the same reason and the same guarantee as `sqlite`/`fake`/`http` in
§8/§10.

### Diagnostic for an unregistered scheme

A scheme that is in neither the built-ins nor the registered entry-points is
rejected with `ValueError`, and the message carries **the scheme received** (not the
full target), **the built-in list** (`http`, `https`), and **the registered
entry-points list** (or "none" if there are none) together.

### entry-point load failure

When something is registered but its value (`module:attr`) cannot be imported,
`open_publisher` translates the `ImportError` to `DriverError` (preserving the cause
chain) — the same rule as §8/§9/§10.

### Verifying with the TCK

An external publisher driver subclasses `lnpl.testing.EventPublisherTCK` and runs it
in its own CI:

```python
import unittest
from lnpl.testing import EventPublisherTCK

class MyKafkaPublisherTCKTest(EventPublisherTCK, unittest.TestCase):
    def make_publisher(self, fail_ids=frozenset()):
        return MyKafkaPublisher(..., fail_ids=fail_ids)
```

What it verifies: acking only after a publish is confirmed, leaving a failed
publish unacked (the next drain retries it), republishing an unacked row after a
restart, and preserving outbox `seq` order. The evidence that the TCK actually catches
this is a discriminating test that runs the same case against both a driver that "acks
before publishing" and a driver that "swallows the error and acks," confirming both fail
(`EventPublisherTCKDiscriminatesTest` in `impl/tests/test_publisher_spi.py`, the same
approach as `RollbackTCKDiscriminatesTest` in §8). The object `make_publisher(fail_ids)`
returns must raise `DriverError` from `publish` for an `id` in `fail_ids`, and must
expose a `published` list holding the confirmed envelope `id`s in publish order — a real
broker driver provides this via a test-only wrapper.

## 16. SPI: external secret provider registration (issue #192)

This opens the boundary for reading a secret such as the JWT signing key from an
external store — Vault, a cloud secret manager, etc. — rather than an environment
variable or `lnpl.toml`. The discipline is the same as §10/§15, except handling a
built-in name follows `lnpl.tokens` (§9): because a secret source is a trust boundary,
registering the same name is not silently ignored — it is **rejected**. No error message
ever carries the driver exception's original text — a module or factory could put a URL
or a secret value into its message.

### Registration

An external package's `pyproject.toml`:

```toml
[project.entry-points."lnpl.secrets"]
vault = "lnpl_vault:make_provider"
```

`lnpl_vault.make_provider` is a callable invoked **with no arguments** that returns a
`SecretProvider` (the same shape as `lnpl.tokens`). Connection settings such as the
store address and authentication are the driver package's own configuration, and the
`key` to read is passed on each call.

### Contract

`SecretProvider` (`lnpl.drivers`) has three methods:

- `get(key) -> bytes` — the current value
- `get_previous(key) -> bytes 또는 None` (`-> bytes or None`) — the value right before the last rotation, or
  `None` if there is none
- `close()` — releases resources, safe to call more than once

The value is `bytes` only (returning `str` is a contract violation). Every failure
(a missing key, a store outage, permissions) is `DriverError`, and its message must
never carry the secret bytes.

### A built-in name can never be shadowed

`env` and `file` are sources the core reads directly, not providers
(`BUILTIN_SECRET_SOURCES`). If an entry-point is registered under those names in
`lnpl.secrets`, `open_secret_provider` never loads it and rejects with `DriverError`:

```text
entry-point 'file' (registered via 'my_pkg:make') attempts to shadow the built-in secret source 'file'; built-in names are reserved (lnpl.secrets SPI, docs/backends.md)
```

Requesting a built-in name as a provider when no such registration exists is a
`ValueError` pointing to the inline form instead:

```text
secret provider 'file' is a built-in source, not a registered provider — write jwt = "ENV_NAME" or jwt = { file = "/absolute/path" } instead
```

### Diagnostic for an unregistered name

A name that is in neither the built-ins nor the registered entry-points is rejected
with `ValueError`, carrying the name received, the built-in list, and the registered
entry-points list (or "none" if there are none) together:

```text
unknown secret provider 'nope' (built-in: env, file; registered entry-points: vault)
```

### entry-point load failure

When something is registered but its value (`module:attr`) cannot be imported, or
the factory raises, it is translated to `DriverError`. Both carry **only the exception
type name** and never carry the driver's own message — a factory failure even severs the
cause chain (`from None`), so it never shows up in a formatted traceback either:

```text
secret provider 'vault' registered via entry-point 'lnpl_vault:make_provider' failed to load (ModuleNotFoundError)
secret provider 'vault' failed to start (RuntimeError)
```

### Rotation and re-fetching

For a provider source (`[*.secrets] jwt = { provider, key }`), the JWT verifier is
`RotatingHmacTokenProvider` (`lnpl.drivers`):

- Verification passes if it matches **either the current key or the previous key**
  (it always computes both MACs and compares with `hmac.compare_digest`). Signing uses
  only the current key. The previous key must also be ≥32 bytes. The two keys change
  atomically as one tuple, so a verification running concurrently sees either the old
  pair or the new pair, never a mix.
- At startup it reads `get` + `get_previous` once. After that, the first `verify`/`issue`
  to arrive once `SECRET_REFRESH_S` (60 seconds) has elapsed re-reads — only one thread
  reads at a time (single-flight), and on failure it quietly keeps the last good key and
  retries 60 seconds later. It does not re-read every time a bad token arrives (so a
  garbage token cannot trigger unbounded provider calls).
- The `/-/readyz` probe also re-reads (check ⑤ `secret-provider`, details in
  `docs/serving.md`). But if the last read (success or failure) is more recent than
  `READYZ_REFRESH_FLOOR_S` (5 seconds), it reuses that result — so repeated unauthenticated
  readyz calls cannot trigger unbounded provider calls. A failure is 503; recovering is
  200, and the new key is installed.
- Operating procedure: in the provider, move the new value to current and the prior value
  to previous, then wait **at least 60 seconds** before letting the issuer sign with the
  new key. Delete the previous key from the provider only after the longest token
  lifetime has passed since the issuer switched to the new key — the default lifetime is
  `DEFAULT_TTL_MS` (15 minutes, the `lnpl token --ttl` default `15m`) and verification
  looks past expiry by `LEEWAY_S` (60 seconds), so with defaults that is 16 minutes
  later. Even after deleting it, the previous key stays alive until a worker re-reads (up
  to 60 seconds) — to cut off a leaked old key, delete it now instead of waiting.
- `lnpl serve` calls `close()` on the provider at shutdown. The `build_app()` path has no
  shutdown hook.

### Verifying with the TCK

An external secret driver subclasses `lnpl.testing.SecretProviderTCK` and runs it in
its own CI. There are three hooks — `make_provider(initial)` provides a fresh provider
whose current value for `TCK_KEY` is `initial` with no previous value; `rotate` provides
a test-only operation that makes a new value current and the old current value previous;
`break_provider` provides a test-only operation that makes subsequent `get`/`get_previous`
calls raise `DriverError`:

```python
import unittest
from lnpl.testing import SecretProviderTCK

class MyVaultTCKTest(SecretProviderTCK, unittest.TestCase):
    def make_provider(self, initial):
        return MyVaultProvider(...)   # TCK_KEY에 initial을 써 둔 저장소

    def rotate(self, provider, new_value):
        ...                           # 새 버전 쓰기

    def break_provider(self, provider):
        ...                           # 이후 읽기가 실패하게
```

What it verifies (7 items): the bytes set are returned unchanged (≥32 bytes),
`get_previous` is `None` before any rotation, rotating moves the current value to
previous, rotating twice still leaves only one previous value, a missing key raises
`DriverError` from both methods, a broken provider also raises `DriverError` from both
methods, and `close()` is safe to call twice. The evidence that the TCK actually catches
this is a discriminating test that runs the same case against both a provider that
"returns the previous value as current" and a provider that "lets a `KeyError` escape
for a missing key," confirming both fail (`SecretProviderTCKDiscriminatesTest` in
`impl/tests/test_secret_spi.py`).

## References

- The migration (expand-contract) procedure and `lnpl migrate`: `docs/migration.md`
- The serving layer's status-code mapping and 401 verdicts: `docs/serving.md`
- The declaration ↔ enforcement matrix: `docs/ENFORCEMENT-MATRIX.md`
- The mode B observation contract (skip reconstruction, `--field` reach, what remains):
  `rfcs/0022-mode-b-observation-surface.md`
- The full CLI surface: `plugins/lnpl/skills/lnpl-authoring/cli-surface.md`


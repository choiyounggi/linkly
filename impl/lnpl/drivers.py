"""Capability adapters — the seam between a declaration and a real backend (#25).

Until this module existed, `capability postgres` and `capability redis` reached
`FakeRepository`/`FakeCache` and stopped there, and `security jwt` was recorded
and never acted on. The three contracts below are what a capability declaration
now binds to, and `SqliteRepositoryDriver` is the first implementation that
outlives the process that wrote it.

Three rules hold this module in place:

  ONE DIRECTION. Nothing here reads the interpreter, the native backend, or the
  CLI. `interp` imports *this*; the reverse would be a cycle that breaks the
  build — the same rule `repo_policy` states for itself, for the same reason.

  ONE ERROR TYPE OUT. Every failure leaves as `DriverError`, cause attached.
  The interpreter translates it to `RunError` at its two call sites, so a
  driver fault becomes an ordinary failed run (`status: failed`, rc 1) rather
  than a traceback out of the CLI.

  STATEMENT TEXT IS CONSTANT. Every SQL string below is a literal; every value
  that varies — including the entity id — is a bound parameter. That is why
  there is one `lnpl_rows` table keyed by `entity_id` rather than one table per
  entity: a per-entity table would put a document-supplied name into the
  statement text, which is the shape SQL injection needs.
"""

import base64
import binascii
import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from importlib import metadata as importlib_metadata
from pathlib import Path

from .repo_policy import READ_OPS

# The operations a RepositoryCall can carry, as a closed set. A miss is a
# diagnostic that names the accepted values, never a plausible no-op.
WRITE_OPS = ("create", "update", "delete")
ACCEPTED_OPS = tuple(READ_OPS) + WRITE_OPS

# The closed table of backend selectors `--backend` accepts.
BACKENDS = ("fake", "sqlite")

# issue #75: the entry-points group an external package registers a
# RepositoryDriver factory under (`[project.entry-points."lnpl.drivers"]`
# in its own pyproject.toml — `docs/backends.md` §8 has the example). Built-in
# schemes (`BACKENDS`, above) are matched before this group is ever consulted,
# so a registered entry-point can never shadow `fake`/`sqlite`.
DRIVERS_ENTRY_POINT_GROUP = "lnpl.drivers"

# The closed table of network selectors `--network` accepts (RFC-0027 §1).
NETWORKS = ("fake", "http")

# Every connection waits this long for a lock instead of raising at once.
BUSY_TIMEOUT_MS = 5000

# --- token constants ------------------------------------------------------
# One service both issues and verifies here, so a symmetric algorithm is the
# right shape: HS256 with a key only this service holds. The list is a
# server-side allowlist, never a value read out of the token — letting the
# token pick its own algorithm is what `alg: none` and the RS256-public-key-as-
# HMAC-secret confusion both exploit.
ACCEPTED_ALGS = ("HS256",)
ISSUER = "lnpl"
# Bounded clock skew. RFC 7519 sanctions "a few minutes" at most; 60s is enough
# for hosts that agree to within a minute and short enough that an expired
# token does not keep working.
LEEWAY_S = 60
# 256 bits of key material, matching the digest HS256 signs with.
MIN_SECRET_BYTES = 32
# Access tokens are short-lived because the revocation gap equals their
# lifetime: there is no session store here to check a denylist against, so
# expiry is the only thing that ends a token's life.
DEFAULT_TTL_MS = 15 * 60 * 1000


class DriverError(Exception):
    """A capability adapter could not carry out the operation.

    `interp` wraps this into `RunError` at the call site, preserving the
    message and the cause chain.
    """


class TokenError(DriverError):
    """A token could not be issued, or failed verification."""


class ConflictError(DriverError):
    """A write collided with existing state. Not retryable: retrying the same
    non-idempotent effect only reproduces the same conflict."""


# --------------------------------------------------------------------------
# The contracts
# --------------------------------------------------------------------------

class RepositoryDriver:
    """The `postgres` capability's adapter contract.

    Reference implementation: `interp.FakeRepository` (in-memory, per run).
    """

    def seed(self, rows):
        """Populate `{entity_id: {row_key: row}}`, INSERTING ONLY WHERE ABSENT.

        Insert-if-absent is what lets the seed rule (`repo_policy`) stay true
        for a persistent store: run N re-seeds the entities the workflow reads,
        and a row run N-1 wrote is left exactly as it was found.
        """
        raise NotImplementedError

    def execute(self, entity_id, operation, key):
        """Carry out one RepositoryCall.

        read / query    -> the stored row as a dict, or None when absent
        create          -> {"affected": 1}; DriverError when (entity, key) exists
        update / delete -> {"affected": n}
        """
        raise NotImplementedError

    def query(self, entity_id):
        """Every row for `entity_id`, ordered by row_key ascending.

        Empty list when the entity has no rows — never `None`, and never an
        error (RFC-0025 §5: an empty RowSet is a valid binding, not an absent
        one). Row-key order is part of the contract, not an implementation
        detail: `SqliteRepositoryDriver` orders by `ORDER BY row_key`, and any
        other implementation must agree with that order for a document to
        mean the same thing under either `--backend` (RFC-0025 §7).
        """
        raise NotImplementedError

    def persist(self, entity_id, key, row):
        """Write back a row mutated through an execution-scope binding.

        RFC-0015's `set` writes into the dict a read bound. For the Fake that
        dict IS the stored row, so this is a no-op; for a real store the bound
        dict is detached and the write has to be flushed or it never happened.
        """
        raise NotImplementedError

    def record_emission(self, emission):
        """Persist one `EventEmit` registration for durable at-least-once
        delivery (issue #102). `emission` is `{"emission_id", "event",
        "payload"}` — the same dict the interpreter's in-memory `outbox`
        already holds.

        Reference implementation: `interp.FakeRepository`, a no-op — it has
        no store that outlives the run, so there is nothing here to persist
        (the same asymmetry `persist`'s own docstring states for the Fake).
        """
        raise NotImplementedError

    def begin(self):
        """Open a transaction boundary spanning one workflow execution
        (issue #79, RFC-0032). `interp.Interpreter.run_workflow` calls this
        once, before its first step, and always closes it with exactly one
        of `commit`/`rollback` before returning.

        Default: no-op. A driver with no transactional notion of its own —
        `interp.FakeRepository`, and any external SPI written before this
        contract existed — satisfies it by doing nothing in all three of
        `begin`/`commit`/`rollback`: the run still completes, its writes
        just are not grouped into anything a failure could undo.
        """
        return None

    def commit(self):
        """Close the boundary `begin` opened, keeping every write made
        since. Default: no-op (see `begin`)."""
        return None

    def rollback(self):
        """Close the boundary `begin` opened, discarding every write made
        since. Default: no-op (see `begin`)."""
        return None

    def query_sorted(self, entity_id, field):
        """Every row for `entity_id`, ordered by `field` ascending, `row_key`
        (`repo_policy.row_key`) the tiebreaker for equal values (issue #99,
        D3/D7 — the `expose list` GET surface).

        Same empty-list-never-None contract as `query`. `field` names a
        top-level key of the JSON `payload` — never SQL text: the statement
        text stays constant, `field` rides in as a bound `json_extract` path
        parameter (STATEMENT TEXT IS CONSTANT, this module's docstring).
        """
        raise NotImplementedError

    def read_outbox(self, event, after_seq=0):
        """Every `event` emission with `seq > after_seq`, ascending (issue
        #103): the SSE subscribe surface's tail read. Independent of
        `delivered_at` — a live SSE subscriber and the drain/ack consumer
        (issue #102) read this same table for two unrelated purposes, and
        neither's cursor moves the other's. Same empty-list-never-None
        contract as `query`/`drain_outbox`.

        Reference implementation: `interp.FakeRepository`, a no-op — it has
        no store that outlives the run, so there is nothing here to tail (the
        same asymmetry `record_emission`'s docstring states for the Fake).
        """
        raise NotImplementedError

    def close(self):
        """Release resources. Safe to call more than once."""
        raise NotImplementedError


class CacheDriver:
    """The `redis` capability's adapter contract.

    Reference implementation: `interp.FakeCache`. No persistent implementation
    ships here — that remains #75's job (external SPI). `docs/backends.md` §5
    records the still-open gap (no shipped server/library on this machine).

    **TTL may be store-delegated.** `set`'s `ttl_ms` is a deadline, not a
    mandate on how it is judged (RFC-0003 §Execution Model/Clock, RFC-0029,
    issue #100). A driver may satisfy the contract either way:

      - Compare `ttl_ms` against a clock reading, the way `FakeCache` compares
        against whichever `Clock`/`RealClock` it was constructed with.
      - **Delegate to the store's own native expiry** (e.g. Redis `SETEX`/
        `EXPIRE`, handed `ttl_ms` untouched) and never read a clock at all.
        This is the recommended path for a persistent driver: the store's own
        clock survives process restarts that an injected one does not, and it
        is one fewer clock to keep synchronized with the store's.

    Either way `get`/`invalidate` need no clock — expiry already happened (or
    didn't) by the time they run.
    """

    def get(self, key):
        raise NotImplementedError

    def set(self, key, value, ttl_ms):
        raise NotImplementedError

    def invalidate(self, key):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError


class TokenProvider:
    """The `security jwt` capability's adapter contract."""

    def issue(self, subject, audience, ttl_ms=None):
        """-> a compact JWS string."""
        raise NotImplementedError

    def verify(self, token, audience):
        """-> the claims dict. Raises TokenError on any checklist failure."""
        raise NotImplementedError


class NetworkDriver:
    """The `NetworkCall` effect's adapter contract (RFC-0027 §1, issue #64).

    Reference implementation: `FakeNetworkDriver` (deterministic, no I/O).

    issue #107, D11: `call` takes an optional `trace_headers` — a
    `{header-name: value}` mapping the runtime builds (W3C `traceparent`,
    verbatim `tracestate`). It defaults to `None`, so every pre-existing
    caller is unaffected. As of this extension there are zero external
    `NetworkDriver` implementations in the wild (issue #115), so widening
    the contract now is safe. D8: these are observation headers, a runtime
    output, never author-declared — a driver applies them AFTER any
    capability-declared headers, so the runtime value always wins.
    """

    def call(self, target, payload, timeout_ms, trace_headers=None):
        """Call `target` once.

        -> (status: int, body: dict). A response was received for every
        status this returns, 5xx included — that is a value, not a fault
        (RFC-0027 §3). Raise `DriverError` only when no response arrived at
        all (connection refused, DNS failure, timeout). `timeout_ms` is this
        one call's budget; a driver must never wait past it, and must never
        treat "unset" as "wait forever" (RFC-0003 §Execution Model).
        """
        raise NotImplementedError

    def close(self):
        """Release resources. Safe to call more than once."""
        raise NotImplementedError


# --------------------------------------------------------------------------
# sqlite
# --------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS lnpl_rows (
    entity_id TEXT NOT NULL,
    row_key   TEXT NOT NULL,
    payload   TEXT NOT NULL,
    _version  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (entity_id, row_key)
)
"""
_SELECT_ROW = ("SELECT payload, _version FROM lnpl_rows "
              "WHERE entity_id = ? AND row_key = ?")
_SELECT_ALL_ROWS = ("SELECT payload FROM lnpl_rows WHERE entity_id = ? "
                    "ORDER BY row_key")
# issue #99, D7: the sort field name never touches the statement text — it
# rides as `json_extract`'s second argument, a bound parameter like every
# other varying value here (STATEMENT TEXT IS CONSTANT, module docstring).
# `payload` carries no per-field column (D7: the existing schema is
# unchanged), so the sort key is extracted from the JSON blob at read time.
_SELECT_SORTED = ("SELECT payload FROM lnpl_rows WHERE entity_id = ? "
                  "ORDER BY json_extract(payload, ?), row_key")
_INSERT_IF_ABSENT = ("INSERT OR IGNORE INTO lnpl_rows (entity_id, row_key, payload) "
                     "VALUES (?, ?, ?)")
_INSERT_ROW = "INSERT INTO lnpl_rows (entity_id, row_key, payload) VALUES (?, ?, ?)"
# Every successful write bumps `_version`, whether or not this call checks it
# against a prior read (`_touch`'s bare update never reads-then-mutates
# through a binding, so it has no observed version to check — issue #92 scopes
# the guard to `persist()`, the read-modify-write path that loses updates).
_UPDATE_ROW = ("UPDATE lnpl_rows SET payload = ?, _version = _version + 1 "
              "WHERE entity_id = ? AND row_key = ?")
# `persist()`'s conditional form: the write only lands if `_version` still
# matches what the read that produced this row observed. 0 rows affected
# means someone else's write landed first — a lost-update guard, not a
# real fault, so it becomes `DriverError` and the interpreter's existing
# retry/failure_reason path (RFC-0003) surfaces it without a new concept.
_UPDATE_ROW_VERSIONED = ("UPDATE lnpl_rows SET payload = ?, _version = _version + 1 "
                         "WHERE entity_id = ? AND row_key = ? AND _version = ?")
_DELETE_ROW = "DELETE FROM lnpl_rows WHERE entity_id = ? AND row_key = ?"

# issue #102, D1 (revised after measurement — see docs/backends.md "outbox
# row identity"): `emission_id` is NOT the primary key here. It is
# `"%s#%d" % (effect_id, len(outbox)+1)` (interp.py), a counter local to one
# Interpreter instance — every fresh `lnpl run` starts that counter at 1, so
# a second run of the same document against the same store reproduces the
# same `emission_id` for its first emission of a given effect. That is not a
# duplicate delivery; it is a distinct emission from a distinct run, and a
# PK on `emission_id` made the second run's INSERT fail outright (reproduced
# 2026-08-24, two `lnpl run` invocations against one sqlite store). At-least-
# once dedupe is about the SAME delivery being redelivered — the delivery's
# identity is `seq`, a storage-owned surrogate key, not `emission_id`, which
# is deterministic-trace-owned (golden outputs and the mode A/B differential
# read it — RFC-0003's contract there is untouched by this table).
# `emission_id` stays a plain column so the trace value that produced a row
# is still visible; it is `seq` that `ack` addresses. Status marking, not
# deletion, still holds: `delivered_at` is what a drained-then-acked row
# loses, never the row itself. `created_at` is millis since epoch (bound
# parameter, `time.time()` below), not sqlite's own `CURRENT_TIMESTAMP` —
# kept for the drain output even though `seq` (not `created_at`) is now the
# order/cursor key, since `seq` already IS insertion order and doubles as
# the monotonic cursor a Last-Event-ID-style consumer (t103) needs.
_CREATE_OUTBOX_TABLE = """
CREATE TABLE IF NOT EXISTS lnpl_outbox (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    emission_id  TEXT NOT NULL,
    event        TEXT NOT NULL,
    payload      TEXT NOT NULL,
    created_at   INTEGER NOT NULL,
    delivered_at INTEGER
)
"""
_INSERT_OUTBOX = ("INSERT INTO lnpl_outbox (emission_id, event, payload, created_at) "
                  "VALUES (?, ?, ?, ?)")
_SELECT_OUTBOX_SEQ = "SELECT 1 FROM lnpl_outbox WHERE seq = ?"
_SELECT_UNDELIVERED = ("SELECT seq, emission_id, event, payload, created_at "
                       "FROM lnpl_outbox WHERE delivered_at IS NULL ORDER BY seq")
_SELECT_UNDELIVERED_LIMIT = _SELECT_UNDELIVERED + " LIMIT ?"
# issue #103: the SSE tail's read — scoped to one event, `delivered_at`
# ignored entirely (that column is the drain/ack consumer's alone).
_SELECT_OUTBOX_SINCE = ("SELECT seq, emission_id, event, payload, created_at "
                        "FROM lnpl_outbox WHERE event = ? AND seq > ? ORDER BY seq")
# The `delivered_at IS NULL` guard is what makes a re-ack idempotent without a
# second read: acking an already-delivered seq matches zero rows and reports
# no error, its `delivered_at` left exactly as the first ack set it.
_MARK_DELIVERED = ("UPDATE lnpl_outbox SET delivered_at = ? "
                   "WHERE seq = ? AND delivered_at IS NULL")

# issue #113, r1: `(workflow_id, key)` claims a slot the moment a request
# with that `Idempotency-Key` arrives -- INSERTed and committed immediately,
# so a genuinely concurrent second request with the same key sees it right
# away (`idempotency_begin` below). The final disposition (`http_status`/
# `body`) is written by a SEPARATE statement, AFTER `run_workflow` returns,
# deliberately outside that execution's own commit/rollback boundary: the
# plan first had this row's whole lifecycle living inside that boundary, but
# `run_workflow` calls `self.repo.rollback()` unconditionally on any failure
# (`interp.py`), and a rollback there would undo the finalizing UPDATE and
# revert the row to `in-progress` forever -- worse than not having the
# feature. `status` is `in-progress` or `done`; `done` is what a later
# request replays regardless of whether the run it recorded succeeded or
# failed (Stripe's contract: a same-key retry gets back the SAME result,
# never a second execution).
_CREATE_IDEMPOTENCY_TABLE = """
CREATE TABLE IF NOT EXISTS lnpl_idempotency (
    key         TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    status      TEXT NOT NULL,
    http_status INTEGER,
    body        TEXT,
    created_at  INTEGER NOT NULL,
    PRIMARY KEY (workflow_id, key)
)
"""
_SELECT_IDEMPOTENCY = ("SELECT status, http_status, body, created_at "
                       "FROM lnpl_idempotency WHERE workflow_id = ? AND key = ?")
_INSERT_IDEMPOTENCY_IN_PROGRESS = (
    "INSERT INTO lnpl_idempotency (key, workflow_id, status, created_at) "
    "VALUES (?, ?, 'in-progress', ?)")
_UPDATE_IDEMPOTENCY_DONE = (
    "UPDATE lnpl_idempotency SET status = 'done', http_status = ?, body = ? "
    "WHERE workflow_id = ? AND key = ?")
_DELETE_IDEMPOTENCY = "DELETE FROM lnpl_idempotency WHERE workflow_id = ? AND key = ?"


def _encode(row):
    return json.dumps(row, ensure_ascii=False, sort_keys=True)


class _VersionedRow(dict):
    """A row as `_read` found it, carrying the `_version` sqlite observed at
    that read. Equality, iteration, and `json.dumps` (via `_encode`) see only
    the dict's own items — `observed_version` is a plain instance attribute,
    invisible to every user-facing surface (payload, response, wire) and
    read only by `persist()` to gate the write against a change since this
    read landed (issue #92; no vocabulary added, nothing exposed).
    """

    def __init__(self, data, version):
        super().__init__(data)
        self.observed_version = version


class SqliteRepositoryDriver(RepositoryDriver):
    """A file-backed repository. One connection, owned by the creating thread.

    Concurrency follows the sqlite guidance rather than a retry loop: WAL so a
    writer does not block readers, `busy_timeout` so a connection that meets a
    lock waits instead of erroring immediately, and one connection per run
    (opening one costs ~0.05ms, so a pool would buy nothing). The journal-mode
    and synchronous pragmas persist on the file, so they are set when the file
    is created and not re-asserted on every later open.
    """

    def __init__(self, path):
        self.raw_path = path
        resolved = self._resolve(path)
        self.path = str(resolved)
        is_new = not resolved.exists()
        # issue #79: set before `begin()` ever runs, so every write path
        # below has a flag to check from the first call. `_in_transaction`
        # is "this execution wants a boundary"; `_sql_transaction_open` is
        # "the literal SQL BEGIN has actually been issued" — kept apart
        # because BEGIN is deferred to the first write (see `begin`).
        self._in_transaction = False
        self._sql_transaction_open = False
        try:
            self._conn = sqlite3.connect(self.path)
            self._conn.execute("PRAGMA busy_timeout = %d" % BUSY_TIMEOUT_MS)
            if is_new:
                self._conn.execute("PRAGMA journal_mode = WAL")
                self._conn.execute("PRAGMA synchronous = NORMAL")
            self._conn.execute(_CREATE_TABLE)
            self._conn.execute(_CREATE_OUTBOX_TABLE)
            self._conn.execute(_CREATE_IDEMPOTENCY_TABLE)
            self._conn.commit()
        except sqlite3.Error as exc:
            raise DriverError("cannot open the sqlite store at %r: %s"
                              % (path, exc)) from exc

    @staticmethod
    def _resolve(path):
        """Absolute, `~`-expanded, and resolved once so every later component
        agrees on one path. The parent must already exist and be writable: a
        store the process cannot create is a startup fault, and finding that
        out at the first read would report it as a missing row instead.

        The message carries the value as *received*. A resolved path the
        operator never typed is a second thing for them to work out.
        """
        if not str(path).strip():
            raise ValueError(
                "--backend sqlite: needs a file path, got an empty one "
                "(e.g. --backend sqlite:./store.db)")
        resolved = Path(path).expanduser().resolve()
        parent = resolved.parent
        if not parent.is_dir():
            raise ValueError(
                "--backend sqlite: the parent directory does not exist: %r" % path)
        if not os.access(str(parent), os.W_OK):
            raise ValueError(
                "--backend sqlite: the parent directory is not writable: %r" % path)
        return resolved

    # -- contract ----------------------------------------------------------

    def seed(self, rows):
        try:
            self._ensure_sql_transaction()
            for entity_id, table in (rows or {}).items():
                for key, row in table.items():
                    self._conn.execute(_INSERT_IF_ABSENT,
                                       (entity_id, key, _encode(row)))
            self._end_write()
        except sqlite3.Error as exc:
            raise DriverError("cannot seed the repository: %s" % exc) from exc

    def begin(self):
        """Issue #79, RFC-0032: request a transaction boundary spanning
        this execution. The literal SQL `BEGIN` is deferred to the first
        write (`_ensure_sql_transaction`, called from every write path
        below) rather than issued here.

        Why lazy: sqlite pins a deferred transaction's read snapshot at
        its FIRST statement, read or write, for the transaction's whole
        life — a second read inside the same open transaction still sees
        the pre-transaction data even after another connection commits a
        change, and a write attempted afterward is refused outright
        (`OperationalError: database is locked`, regardless of which
        table it touches — confirmed empirically, not merely documented
        behavior). If `begin()` opened the transaction eagerly, the
        workflow's very first *read* would pin that stale snapshot, and
        the first write after any concurrent commit would hit that raw
        engine error instead of this driver's own `_version` conflict
        check (issue #92) ever running. Deferring `BEGIN` to the first
        write keeps every read up to that point in ordinary autocommit
        mode — always current — so the first write's conditional UPDATE
        is what decides a conflict, on a fresh view, the same as before
        this RFC per-op-committed every write individually.

        A second `begin()` before this boundary is closed is refused
        (`DriverError`): which `rollback` would then undo, and how far,
        would otherwise depend on the driver, making `policy rollback`
        drift from one implicit transaction per execution into something
        driver-dependent."""
        if self._in_transaction:
            raise DriverError(
                "begin() called while a transaction is already open — "
                "nested transactions are not supported; commit() or "
                "rollback() the open one first")
        self._in_transaction = True

    def commit(self):
        try:
            if self._sql_transaction_open:
                self._conn.commit()
        except sqlite3.Error as exc:
            raise DriverError("cannot commit transaction: %s" % exc) from exc
        finally:
            self._in_transaction = False
            self._sql_transaction_open = False

    def rollback(self):
        try:
            if self._sql_transaction_open:
                self._conn.rollback()
        except sqlite3.Error as exc:
            raise DriverError("cannot roll back transaction: %s" % exc) from exc
        finally:
            self._in_transaction = False
            self._sql_transaction_open = False

    def _ensure_sql_transaction(self):
        """Open the literal SQL transaction on the first write only, once
        per execution (issue #79 — see `begin`'s docstring for why)."""
        if self._in_transaction and not self._sql_transaction_open:
            try:
                self._conn.execute("BEGIN")
            except sqlite3.Error as exc:
                raise DriverError("cannot begin transaction: %s" % exc) from exc
            self._sql_transaction_open = True

    def _end_write(self):
        """Close out the write statement(s) just issued: commit immediately,
        unless a workflow-level transaction (`begin`) is holding the
        connection open (issue #79) — then that boundary's own `commit`/
        `rollback` decides this write's fate along with the rest of the run."""
        if not self._in_transaction:
            self._conn.commit()

    def idempotency_begin(self, workflow_id, key, now_ms, ttl_ms):
        """Claim `(workflow_id, key)` -- issue #113, r1. Two outcomes ask the
        caller to run nothing: `("in-progress", None)` (someone else owns
        this key right now -- 409) or `("done", (http_status, body))` (a
        prior run already finished -- replay it, whether it succeeded or
        failed). `("started", None)` means this call just claimed the key
        and the caller should run the workflow.

        Every statement here is its own immediately-committed write,
        deliberately outside `begin`/`commit`/`rollback` above: a concurrent
        request with the same key must see the claim the instant it lands,
        long before `run_workflow` ever calls `begin()`.
        """
        try:
            row = self._conn.execute(_SELECT_IDEMPOTENCY,
                                     (workflow_id, key)).fetchone()
        except sqlite3.Error as exc:
            raise DriverError("cannot read idempotency key %r: %s"
                              % (key, exc)) from exc
        if row is not None:
            status, http_status, body, created_at = row
            if now_ms - created_at < ttl_ms:
                if status == "in-progress":
                    return "in-progress", None
                return "done", (http_status,
                                json.loads(body) if body is not None else None)
            # D10: past its TTL -- clear it and fall through to claim fresh,
            # the same as if this key had never been used.
            try:
                self._conn.execute(_DELETE_IDEMPOTENCY, (workflow_id, key))
                self._conn.commit()
            except sqlite3.Error as exc:
                raise DriverError(
                    "cannot clear expired idempotency key %r: %s"
                    % (key, exc)) from exc
        try:
            self._conn.execute(_INSERT_IDEMPOTENCY_IN_PROGRESS,
                               (key, workflow_id, now_ms))
            self._conn.commit()
            return "started", None
        except sqlite3.IntegrityError:
            # Lost a race with a concurrent claim between the SELECT above
            # and this INSERT -- the other request owns the key now.
            return "in-progress", None
        except sqlite3.Error as exc:
            raise DriverError("cannot claim idempotency key %r: %s"
                              % (key, exc)) from exc

    def idempotency_finish(self, workflow_id, key, http_status, body):
        """Record the final disposition -- a SEPARATE statement, issued
        AFTER `run_workflow` returns (issue #113, r1). Deliberately outside
        that execution's own commit/rollback boundary: `run_workflow` calls
        `self.repo.rollback()` unconditionally on any failure, and writing
        this finalize step INSIDE that boundary would have a failed run's
        rollback undo it too -- reverting the row to `in-progress` forever,
        which blocks every future retry instead of replaying the failure
        (docs/serving.md's idempotency section)."""
        try:
            self._conn.execute(_UPDATE_IDEMPOTENCY_DONE,
                               (http_status, json.dumps(body), workflow_id, key))
            self._conn.commit()
        except sqlite3.Error as exc:
            raise DriverError("cannot record idempotency result for %r: %s"
                              % (key, exc)) from exc

    def execute(self, entity_id, operation, key):
        if operation in READ_OPS:
            return self._read(entity_id, key)
        if operation == "create":
            return self._create(entity_id, key)
        if operation in ("update", "delete"):
            return self._touch(entity_id, operation, key)
        raise DriverError("unsupported repository operation %r (accepted: %s)"
                          % (operation, ", ".join(ACCEPTED_OPS)))

    def query(self, entity_id):
        try:
            found = self._conn.execute(_SELECT_ALL_ROWS, (entity_id,)).fetchall()
        except sqlite3.Error as exc:
            raise DriverError("cannot query %s: %s" % (entity_id, exc)) from exc
        return [json.loads(row[0]) for row in found]

    def query_sorted(self, entity_id, field):
        try:
            found = self._conn.execute(
                _SELECT_SORTED, (entity_id, "$." + field)).fetchall()
        except sqlite3.Error as exc:
            raise DriverError("cannot query %s sorted by %s: %s"
                              % (entity_id, field, exc)) from exc
        return [json.loads(row[0]) for row in found]

    def persist(self, entity_id, key, row):
        version = getattr(row, "observed_version", None)
        try:
            self._ensure_sql_transaction()
            if version is None:
                self._conn.execute(_UPDATE_ROW, (_encode(row), entity_id, key))
                self._end_write()
                return
            cursor = self._conn.execute(
                _UPDATE_ROW_VERSIONED, (_encode(row), entity_id, key, version))
            if cursor.rowcount == 0:
                # issue #79: only roll back locally outside a workflow
                # transaction. Inside one (`_in_transaction`), a local
                # rollback here would discard every write this same
                # execution already made — the execution boundary's own
                # `rollback()` is what cleans up once this `DriverError`
                # becomes a `RunError` and the run is decided failed.
                if not self._in_transaction:
                    self._conn.rollback()
                raise DriverError(
                    "write conflict: row changed since read (%s %s)"
                    % (entity_id, key))
            self._end_write()
        except sqlite3.Error as exc:
            raise DriverError("cannot persist %s: %s" % (entity_id, exc)) from exc

    def record_emission(self, emission):
        """Persist one `EventEmit` registration (issue #102, D1/D2).

        `emission` is the same `{"emission_id", "event", "payload"}` dict the
        interpreter's in-memory `outbox` already holds — this call is what
        makes it survive the process. `emission_id` rides in as a plain
        column, not the row's identity: two separate runs of the same
        document legitimately reproduce the same `emission_id` for their
        first emission of a given effect (it is a per-Interpreter counter,
        interp.py), and each is a genuinely distinct emission, not a
        redelivery of one — so a second row for a repeated `emission_id` is
        the correct outcome, never a conflict. `seq` (sqlite's own
        AUTOINCREMENT) is the row's real identity; `ack_outbox` addresses by
        it.
        """
        try:
            self._ensure_sql_transaction()
            self._conn.execute(
                _INSERT_OUTBOX,
                (emission["emission_id"], emission["event"],
                 _encode(emission["payload"]), int(time.time() * 1000)))
            self._end_write()
        except sqlite3.Error as exc:
            raise DriverError("cannot record emission %s: %s"
                              % (emission["emission_id"], exc)) from exc

    def drain_outbox(self, limit=None):
        """Every undelivered emission, `seq` ascending — insertion order,
        which doubles as a monotonic delivery cursor (issue #102, D3
        revised: `seq`, not `created_at`/`emission_id`, is the row's real
        order/identity — see the schema comment above `_CREATE_OUTBOX_TABLE`).
        Never a delivered row — `ack_outbox` is what removes one from this
        view, by marking `delivered_at`, not by deleting it (D1). Empty list
        when nothing is undelivered, never `None` — the same empty-is-a-
        value contract `query`/`query_sorted` already state for their own
        reads.
        """
        try:
            if limit is None:
                found = self._conn.execute(_SELECT_UNDELIVERED).fetchall()
            else:
                found = self._conn.execute(
                    _SELECT_UNDELIVERED_LIMIT, (limit,)).fetchall()
        except sqlite3.Error as exc:
            raise DriverError("cannot drain outbox: %s" % exc) from exc
        return [{"seq": row[0], "emission_id": row[1], "event": row[2],
                "payload": json.loads(row[3]), "created_at": row[4]}
               for row in found]

    def read_outbox(self, event, after_seq=0):
        """Every emission of `event` with `seq > after_seq`, ascending (issue
        #103): the SSE subscribe surface's tail read, unaffected by
        `delivered_at` (see the schema comment above `_CREATE_OUTBOX_TABLE`
        and the `RepositoryDriver.read_outbox` contract docstring). Empty
        list, never `None`, matching `drain_outbox`'s own contract.
        """
        try:
            found = self._conn.execute(
                _SELECT_OUTBOX_SINCE, (event, after_seq)).fetchall()
        except sqlite3.Error as exc:
            raise DriverError("cannot read outbox for %s: %s"
                              % (event, exc)) from exc
        return [{"seq": row[0], "emission_id": row[1], "event": row[2],
                "payload": json.loads(row[3]), "created_at": row[4]}
               for row in found]

    def ack_outbox(self, seqs):
        """Mark every row in `seqs` delivered (issue #102, D3 revised: `seq`
        is the delivery identity `ack` addresses, not `emission_id` — see
        the schema comment above `_CREATE_OUTBOX_TABLE`).

        Fails closed: every seq is checked to exist BEFORE anything is
        written, so an unknown seq in the batch leaves the known ones
        untouched too — a caller must never learn "some of these worked"
        from a message that only names the ones that did not. A known seq
        already delivered is a no-op success (idempotent re-ack): the
        `_MARK_DELIVERED` guard makes that true without a second read here.
        """
        try:
            missing = [seq for seq in seqs
                      if self._conn.execute(
                          _SELECT_OUTBOX_SEQ, (seq,)).fetchone() is None]
            if missing:
                raise DriverError(
                    "outbox ack: unknown seq(s): %s"
                    % ", ".join(str(seq) for seq in missing))
            now = int(time.time() * 1000)
            for seq in seqs:
                self._conn.execute(_MARK_DELIVERED, (now, seq))
            self._conn.commit()
        except sqlite3.Error as exc:
            raise DriverError("cannot ack outbox: %s" % exc) from exc

    def close(self):
        conn, self._conn = getattr(self, "_conn", None), None
        if conn is not None:
            conn.close()

    # -- internals ---------------------------------------------------------

    def _read(self, entity_id, key):
        try:
            found = self._conn.execute(_SELECT_ROW, (entity_id, key)).fetchone()
        except sqlite3.Error as exc:
            raise DriverError("cannot read %s: %s" % (entity_id, exc)) from exc
        if found is None:
            return None
        payload, version = found
        return _VersionedRow(json.loads(payload), version)

    def _create(self, entity_id, key):
        try:
            self._ensure_sql_transaction()
            self._conn.execute(_INSERT_ROW,
                               (entity_id, key, _encode({"id": key})))
            self._end_write()
        except sqlite3.IntegrityError as exc:
            # Byte-identical to FakeRepository's message: one shared contract
            # suite asserts this text against both drivers, and the rule it
            # guards — never retry a non-idempotent effect — is only testable
            # while a create can actually fail.
            raise ConflictError("repository create conflicts: %s already exists"
                                % entity_id) from exc
        except sqlite3.Error as exc:
            raise DriverError("cannot create %s: %s" % (entity_id, exc)) from exc
        return {"affected": 1}

    def _touch(self, entity_id, operation, key):
        """`affected` is the true row count here, where the Fake answers 1
        unconditionally. The difference never reaches an observable: the
        interpreter reads only `row is not None` from a write's answer.
        """
        statement = _DELETE_ROW if operation == "delete" else _UPDATE_ROW
        try:
            if operation == "delete":
                self._ensure_sql_transaction()
                cursor = self._conn.execute(statement, (entity_id, key))
            else:
                # The read stays outside the transaction (still autocommit,
                # so still current) — only the write below opens it, per
                # `begin`'s lazy-BEGIN rationale (issue #79).
                current = self._read(entity_id, key)
                self._ensure_sql_transaction()
                cursor = self._conn.execute(
                    statement, (_encode(current if current is not None else {"id": key}),
                                entity_id, key))
            self._end_write()
        except sqlite3.Error as exc:
            raise DriverError("cannot %s %s: %s" % (operation, entity_id, exc)) from exc
        return {"affected": cursor.rowcount if cursor.rowcount >= 0 else 0}


# --------------------------------------------------------------------------
# jwt
# --------------------------------------------------------------------------

def _b64u_encode(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_decode(text):
    """Restore the padding a compact JWS strips. A malformed segment is a fault
    of the token, so it leaves as TokenError — a decoder exception escaping to
    the caller would turn a bad request into a 500."""
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as exc:
        raise TokenError("token segment is not valid base64url") from exc


def _decode_json_segment(text, what):
    try:
        value = json.loads(_b64u_decode(text))
    except (UnicodeDecodeError, ValueError) as exc:
        raise TokenError("token %s is not valid JSON" % what) from exc
    if not isinstance(value, dict):
        raise TokenError("token %s is not an object" % what)
    return value


class HmacTokenProvider(TokenProvider):
    """HS256 issuance and verification over stdlib `hmac`.

    No JWT library is added for this: the primitive that has to be right is the
    HMAC itself, and that is `hmac.new(...)` plus `hmac.compare_digest` for a
    constant-time comparison. What is written here is the encoding and the
    verification checklist, neither of which is a cryptographic algorithm.

    Refresh tokens, rotation, and revocation are deliberately absent — all
    three need a server-side session store this platform does not have, and a
    refresh flow without one would be a longer-lived access token wearing a
    different name. `docs/backends.md` records that.
    """

    def __init__(self, secret):
        if isinstance(secret, str):
            secret = secret.encode("utf-8")
        # Measured in bytes, not characters: "é" * 16 is 16 characters and 32
        # bytes of key material, and it is the bytes that HMAC consumes.
        if len(secret) < MIN_SECRET_BYTES:
            raise TokenError(
                "the JWT signing secret must be at least %d bytes, got %d"
                % (MIN_SECRET_BYTES, len(secret)))
        self._secret = secret

    # -- contract ----------------------------------------------------------

    def issue(self, subject, audience, ttl_ms=None):
        now = int(time.time())
        # `is not None`, not `or`: ttl_ms=0 is a legitimate request for an
        # already-expiring token, and `or` would silently hand back the
        # 15-minute default instead.
        ttl_s = (DEFAULT_TTL_MS if ttl_ms is None else ttl_ms) // 1000
        header = {"alg": ACCEPTED_ALGS[0], "typ": "JWT"}
        claims = {"iss": ISSUER, "aud": audience, "sub": subject,
                  "jti": uuid.uuid4().hex, "iat": now, "nbf": now,
                  "exp": now + ttl_s}
        signing_input = "%s.%s" % (
            _b64u_encode(json.dumps(header, sort_keys=True).encode("utf-8")),
            _b64u_encode(json.dumps(claims, sort_keys=True).encode("utf-8")))
        return "%s.%s" % (signing_input, _b64u_encode(self._sign(signing_input)))

    def verify(self, token, audience):
        """The checklist, in order. Order matters: the algorithm is settled
        before any key is used, and the signature is settled before a single
        claim is trusted — every check after it reads data an attacker would
        otherwise choose."""
        parts = (token or "").split(".")
        if len(parts) != 3:
            raise TokenError("token is not a compact JWS (expected 3 segments, "
                             "got %d)" % len(parts))
        encoded_header, encoded_claims, encoded_signature = parts

        header = _decode_json_segment(encoded_header, "header")
        alg = header.get("alg")
        if alg not in ACCEPTED_ALGS:
            raise TokenError("unaccepted alg %r (accepted: %s)"
                             % (alg, ", ".join(ACCEPTED_ALGS)))

        expected = self._sign("%s.%s" % (encoded_header, encoded_claims))
        if not hmac.compare_digest(expected, _b64u_decode(encoded_signature)):
            raise TokenError("token signature does not verify")

        if header.get("typ") != "JWT":
            raise TokenError("unexpected typ %r (expected 'JWT')"
                             % header.get("typ"))

        claims = _decode_json_segment(encoded_claims, "claims")
        if claims.get("iss") != ISSUER:
            raise TokenError("unexpected iss %r (expected %r)"
                             % (claims.get("iss"), ISSUER))

        declared = claims.get("aud")
        holds = declared if isinstance(declared, list) else [declared]
        if audience not in holds:
            raise TokenError("token audience %r does not match %r"
                             % (declared, audience))

        now = int(time.time())
        nbf, exp = claims.get("nbf"), claims.get("exp")
        if not isinstance(exp, int):
            raise TokenError("token carries no exp")
        if isinstance(nbf, int) and now < nbf - LEEWAY_S:
            raise TokenError("token is not valid yet")
        if now >= exp + LEEWAY_S:
            raise TokenError("token has expired")
        return claims

    # -- internals ---------------------------------------------------------

    def _sign(self, signing_input):
        return hmac.new(self._secret, signing_input.encode("ascii"),
                        hashlib.sha256).digest()


def audience_for_path(path):
    """The served path's service slug, which is the audience a token for that
    path must carry.

    Deriving it from the path rather than from configuration means the issuer
    and the verifier read one function, so the two can never drift; and a token
    minted for one service is not accepted by its neighbour.
    """
    segments = (path or "").split("/")
    if len(segments) < 2 or segments[0] != "" or not segments[1]:
        raise ValueError("cannot derive an audience from path %r "
                         "(expected '/<service>/<workflow>')" % path)
    return segments[1]


# --------------------------------------------------------------------------
# network
# --------------------------------------------------------------------------

# RFC-0027 §5: no policy timeout declared -> this, never an infinite wait
# (backend/common/reliability/timeouts-and-retries — library defaults are
# unreliable and some are infinite; one hung call without a timeout exhausts
# the pool).
DEFAULT_NETWORK_TIMEOUT_MS = 30_000


class FakeNetworkDriver(NetworkDriver):
    """Reference implementation (RFC-0027 §1). `stubs` is `{target: (status,
    body)}`, built from a spec's `given call <target> returns <status>` lines
    (RFC-0027 §7) or empty by default. An unstubbed target answers
    deterministically — `(200, {})` — rather than raising, so a spec case
    that names no stub is still reproducible.
    """

    def __init__(self, stubs=None):
        self.stubs = dict(stubs or {})
        # issue #107: every call recorded, trace headers included — the
        # unit-test-facing way to assert what the runtime sent.
        self.received = []

    def call(self, target, payload, timeout_ms, trace_headers=None):
        self.received.append({"target": target, "payload": payload,
                              "trace_headers": dict(trace_headers or {})})
        return self.stubs.get(target, (200, {}))

    def close(self):
        pass


def _is_url_literal(target):
    """True when `target` is already `http(s)://host[:port]/path` — the
    resolvable-URL shape `HttpNetworkDriver.call`'s entry check requires.
    Shared by the resolution step below so a literal is classified exactly
    once, the same way, in both places.
    """
    import urllib.parse
    parts = urllib.parse.urlsplit(target)
    return parts.scheme in ("http", "https") and bool(parts.hostname)


class HttpNetworkDriver(NetworkDriver):
    """`http.client` only — standard library, zero dependencies (RFC-0027
    §1). `target` is read as a URL, or resolved from `endpoints`/`capabilities`
    when it is a logical name (issue #101) — either way the resolved URL goes
    through the same entry validation before a connection opens.

    `endpoints`: {logical name -> URL}. `capabilities`: {logical name ->
    {"method": "GET"/"POST", "headers": {...}}}, already resolved (secret
    values substituted) by the caller — this class never reads the
    environment or a capability declaration itself (issue #101's secrets
    principle: the driver only ever sees a header VALUE, never an ENV name).
    A target with no entry in `capabilities` defaults to POST/no extra
    headers — the pre-#101 behaviour for a mapped-but-undeclared name.
    """

    def __init__(self, endpoints=None, capabilities=None):
        self._endpoints = dict(endpoints or {})
        self._capabilities = dict(capabilities or {})

    def _resolve(self, target):
        """target -> (url, method, headers). Raises DriverError for a
        logical name with no `endpoints` entry — the CLI's startup check
        (issue #101 D3) is meant to catch this before a run ever starts;
        this is the defense-in-depth path for a driver used directly.
        """
        if _is_url_literal(target):
            return target, "POST", {}
        url = self._endpoints.get(target)
        if url is None:
            raise DriverError(
                "network target %r has no --endpoint mapping or "
                "LNPL_ENDPOINT_%s environment variable (a logical name needs "
                "one or the other under --network http)"
                % (target, target.upper()))
        cap = self._capabilities.get(target)
        method = cap["method"] if cap else "POST"
        headers = dict(cap["headers"]) if cap else {}
        return url, method, headers

    def call(self, target, payload, timeout_ms, trace_headers=None):
        import http.client
        import urllib.parse

        url, method, headers = self._resolve(target)
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            # A logical name (RFC-0027 examples' `call PaymentGateway as p`)
            # or a non-http(s) scheme has no host `urlsplit` can hand to
            # `http.client` — left unchecked, `HTTPConnection(None, ...)`
            # raises a raw AttributeError the exception clause below does not
            # catch (issue #90). Reject before opening a connection, not
            # after — now checked against the RESOLVED url (issue #101),
            # since `target` itself may be a logical name `_resolve` already
            # mapped; this check's own logic is unchanged.
            raise DriverError(
                "network target %r is not a resolvable URL (the http driver "
                "needs `http(s)://host[:port]/path`; a logical name has no "
                "address here)" % url)
        path = urllib.parse.urlunsplit(("", "", parts.path or "/",
                                        parts.query, "")) or "/"
        body = None
        if method != "GET":
            body = json.dumps(payload).encode("utf-8")
            headers = dict(headers, **{"Content-Type": "application/json"})
        # issue #107, D8: trace headers are merged in LAST, after any
        # capability-declared headers — the runtime's observation headers
        # always win over an author's declaration, never the reverse.
        headers.update(trace_headers or {})
        try:
            conn = http.client.HTTPSConnection(
                parts.hostname, parts.port, timeout=timeout_ms / 1000
            ) if parts.scheme == "https" else http.client.HTTPConnection(
                parts.hostname, parts.port, timeout=timeout_ms / 1000)
            try:
                conn.request(method, path, body=body, headers=headers)
                response = conn.getresponse()
                raw = response.read()
            finally:
                conn.close()
        except (OSError, http.client.HTTPException) as exc:
            # No response arrived at all — connect refused, DNS failure,
            # timeout. A 5xx status never reaches this branch: the connection
            # already succeeded by the time a status line exists (RFC-0027 §3).
            raise DriverError(str(exc)) from exc
        try:
            parsed = json.loads(raw) if raw else {}
        except ValueError:
            # RFC-0027 §1: the value shape (dict) stays stable even when the
            # peer does not speak JSON.
            parsed = {}
        return response.status, parsed if isinstance(parsed, dict) else {}

    def close(self):
        pass


# --------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------

def _driver_entry_points():
    """Every entry-point registered under `lnpl.drivers`, across the stdlib
    API's version split: 3.10+ takes `group=` as a select filter; 3.9's
    `entry_points()` takes no arguments and returns a `{group: [EntryPoint,
    ...]}` mapping instead (`pyproject.toml`'s declared floor is 3.9).
    """
    try:
        return importlib_metadata.entry_points(group=DRIVERS_ENTRY_POINT_GROUP)
    except TypeError:
        return importlib_metadata.entry_points().get(
            DRIVERS_ENTRY_POINT_GROUP, [])


def _registered_scheme_names():
    return sorted(ep.name for ep in _driver_entry_points())


def open_repository(spec):
    """`--backend`'s value -> a RepositoryDriver, or None for the default.

    `None` means "the Interpreter builds its own FakeRepository", which keeps
    the untouched path byte-identical to what it was before this issue. The
    lookup is a closed table with a defined miss: an unrecognized selector
    names itself and the accepted set rather than resolving to something
    plausible.

    Beyond the two built-in schemes, `<scheme>:<arg>` is looked up in the
    `lnpl.drivers` entry-points group (issue #75) — an external package
    registers `scheme = "module:factory"`, and a matching selector loads that
    factory and calls it with `arg`. Built-ins are matched first and always
    win: `fake`/`sqlite` are checked above before any entry-point lookup
    runs, so a package cannot register `sqlite` and shadow the real one.
    """
    if spec == "fake":
        return None
    if spec.startswith("sqlite:"):
        return SqliteRepositoryDriver(spec[len("sqlite:"):])
    scheme, _, arg = spec.partition(":")
    for entry_point in _driver_entry_points():
        if entry_point.name == scheme:
            try:
                factory = entry_point.load()
            except Exception as exc:
                raise DriverError(
                    "backend %r registered via entry-point %r failed to "
                    "load: %s" % (spec, entry_point.value, exc)) from exc
            return factory(arg)
    raise ValueError(
        "unknown backend %r (built-in: %s; registered entry-points: %s)"
        % (spec, ", ".join(BACKENDS),
           ", ".join(_registered_scheme_names()) or "none"))


def open_network(spec, endpoints=None, capabilities=None):
    """`--network`'s value -> a NetworkDriver, or None for the default
    (RFC-0027 §1, the `open_repository` selector mirrored).

    `None` means "the Interpreter builds its own FakeNetworkDriver". The
    lookup is a closed table with a defined miss, same as `open_repository`.

    `endpoints`/`capabilities` (issue #101) are ignored for `fake` — the fake
    driver has no notion of either — and passed through to `HttpNetworkDriver`
    for `http`.
    """
    if spec == "fake":
        return None
    if spec == "http":
        return HttpNetworkDriver(endpoints=endpoints, capabilities=capabilities)
    raise ValueError("unknown network %r (accepted: %s)"
                     % (spec, ", ".join(NETWORKS)))

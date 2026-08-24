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
from pathlib import Path

from .repo_policy import READ_OPS

# The operations a RepositoryCall can carry, as a closed set. A miss is a
# diagnostic that names the accepted values, never a plausible no-op.
WRITE_OPS = ("create", "update", "delete")
ACCEPTED_OPS = tuple(READ_OPS) + WRITE_OPS

# The closed table of backend selectors `--backend` accepts.
BACKENDS = ("fake", "sqlite")

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

    def close(self):
        """Release resources. Safe to call more than once."""
        raise NotImplementedError


class CacheDriver:
    """The `redis` capability's adapter contract.

    Reference implementation: `interp.FakeCache`. No persistent implementation
    ships here, and that is a decision rather than an omission: RFC-0003
    denominates a cache TTL in the run's injected clock, which starts at 0 in
    every process. A persisted entry would be compared against a fresh clock
    and read as live forever, so "a persistent cache" would be a store whose
    expiry contract is untrue. `docs/backends.md` records the gap.
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
    """

    def call(self, target, payload, timeout_ms):
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
        try:
            self._conn = sqlite3.connect(self.path)
            self._conn.execute("PRAGMA busy_timeout = %d" % BUSY_TIMEOUT_MS)
            if is_new:
                self._conn.execute("PRAGMA journal_mode = WAL")
                self._conn.execute("PRAGMA synchronous = NORMAL")
            self._conn.execute(_CREATE_TABLE)
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
            for entity_id, table in (rows or {}).items():
                for key, row in table.items():
                    self._conn.execute(_INSERT_IF_ABSENT,
                                       (entity_id, key, _encode(row)))
            self._conn.commit()
        except sqlite3.Error as exc:
            raise DriverError("cannot seed the repository: %s" % exc) from exc

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

    def persist(self, entity_id, key, row):
        version = getattr(row, "observed_version", None)
        try:
            if version is None:
                self._conn.execute(_UPDATE_ROW, (_encode(row), entity_id, key))
                self._conn.commit()
                return
            cursor = self._conn.execute(
                _UPDATE_ROW_VERSIONED, (_encode(row), entity_id, key, version))
            if cursor.rowcount == 0:
                self._conn.rollback()
                raise DriverError(
                    "write conflict: row changed since read (%s %s)"
                    % (entity_id, key))
            self._conn.commit()
        except sqlite3.Error as exc:
            raise DriverError("cannot persist %s: %s" % (entity_id, exc)) from exc

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
            self._conn.execute(_INSERT_ROW,
                               (entity_id, key, _encode({"id": key})))
            self._conn.commit()
        except sqlite3.IntegrityError as exc:
            # Byte-identical to FakeRepository's message: one shared contract
            # suite asserts this text against both drivers, and the rule it
            # guards — never retry a non-idempotent effect — is only testable
            # while a create can actually fail.
            raise DriverError("repository create conflicts: %s already exists"
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
                cursor = self._conn.execute(statement, (entity_id, key))
            else:
                current = self._read(entity_id, key)
                cursor = self._conn.execute(
                    statement, (_encode(current if current is not None else {"id": key}),
                                entity_id, key))
            self._conn.commit()
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

    def call(self, target, payload, timeout_ms):
        return self.stubs.get(target, (200, {}))

    def close(self):
        pass


class HttpNetworkDriver(NetworkDriver):
    """`http.client` only — standard library, zero dependencies (RFC-0027
    §1). `target` is read as a URL; the method is fixed `POST` (RFC-0027
    §Open Questions 4).
    """

    def call(self, target, payload, timeout_ms):
        import http.client
        import urllib.parse

        parts = urllib.parse.urlsplit(target)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            # A logical name (RFC-0027 examples' `call PaymentGateway as p`)
            # or a non-http(s) scheme has no host `urlsplit` can hand to
            # `http.client` — left unchecked, `HTTPConnection(None, ...)`
            # raises a raw AttributeError the exception clause below does not
            # catch (issue #90). Reject before opening a connection, not after.
            raise DriverError(
                "network target %r is not a resolvable URL (the http driver "
                "needs `http(s)://host[:port]/path`; a logical name has no "
                "address here)" % target)
        body = json.dumps(payload).encode("utf-8")
        path = urllib.parse.urlunsplit(("", "", parts.path or "/",
                                        parts.query, "")) or "/"
        try:
            conn = http.client.HTTPSConnection(
                parts.hostname, parts.port, timeout=timeout_ms / 1000
            ) if parts.scheme == "https" else http.client.HTTPConnection(
                parts.hostname, parts.port, timeout=timeout_ms / 1000)
            try:
                conn.request("POST", path, body=body,
                             headers={"Content-Type": "application/json"})
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

def open_repository(spec):
    """`--backend`'s value -> a RepositoryDriver, or None for the default.

    `None` means "the Interpreter builds its own FakeRepository", which keeps
    the untouched path byte-identical to what it was before this issue. The
    lookup is a closed table with a defined miss: an unrecognized selector
    names itself and the accepted set rather than resolving to something
    plausible.
    """
    if spec == "fake":
        return None
    if spec.startswith("sqlite:"):
        return SqliteRepositoryDriver(spec[len("sqlite:"):])
    raise ValueError("unknown backend %r (accepted: %s)"
                     % (spec, ", ".join(BACKENDS)))


def open_network(spec):
    """`--network`'s value -> a NetworkDriver, or None for the default
    (RFC-0027 §1, the `open_repository` selector mirrored).

    `None` means "the Interpreter builds its own FakeNetworkDriver". The
    lookup is a closed table with a defined miss, same as `open_repository`.
    """
    if spec == "fake":
        return None
    if spec == "http":
        return HttpNetworkDriver()
    raise ValueError("unknown network %r (accepted: %s)"
                     % (spec, ", ".join(NETWORKS)))

"""LNPL -> Semantic IR lowering (RFC-0002 Appendix A).

Two rules decided here are the ones RFC-0002 A.4 left open:

R2 — node id derivation (A.4-7). One uniform rule:
    id = <kind prefix> "." <name split at PascalCase boundaries, lowercased,
                            joined by ".", with a trailing segment that merely
                            repeats the kind's own word removed>
  so `LoginService` as a Service becomes `svc.login`, while `UserCreated` as an
  Event keeps both segments (`created` is not the word "event") -> `event.user.created`.

R1 — Effect derivation (A.4-3). A step line's first token is a Verb (the grammar
  guarantees it), so deriving effects is a *lookup in a closed lexicon*, not
  inference. Authors keep declaring intent; the mapping stays deterministic.
  A verb outside the lexicon derives no Effect — silence, never a guess.
  The *derivation* stays silent; the compiler does not. Issue #36 was not R1 but
  the step after it: "derives no Effect" was also spelled "says nothing", so a
  step that does nothing looked exactly like a step that works. Deriving nothing
  now emits an `unknown-verb` diagnostic, and the IR is unchanged.
"""

import difflib
import os
import re

from .diagnostics import ENFORCED, ENFORCEMENT, Diagnostics
from .lexer import (COMPARATORS, SCHEDULE_RECURRENCES, SCHEDULE_ZONES,
                    is_duration)
from .parser import parse
from .refinements import (BASE_CATEGORY, FACET_NAMES, PRESETS, facets_for_base,
                          preset)
from .repo_policy import binding_name

KIND_PREFIX = {
    "Entity": "entity",
    "Service": "svc",
    "Workflow": "wf",
    "Event": "event",
    "Capability": "cap",
    "Refinement": "refine",
    "Policy": "policy",
    "Security": "security",
    "Performance": "perf",
}

# The word each declaration kind "is" — a trailing name segment equal to it is
# redundant and gets stripped (R2).
KIND_WORD = {
    "Entity": "entity",
    "Service": "service",
    "Workflow": "workflow",
    "Event": "event",
    "Capability": "capability",
}

# Short slug per derived Effect kind, used as the last id segment (R2).
GUARD_SLUG = {"when": "when", "until": "until", "repeat": "repeat"}

EFFECT_SLUG = {
    "Assignment": "assign",
    "Validation": "check",
    "RepositoryCall": "repo",
    "CacheAccess": "cache",
    "NetworkCall": "net",
    "Transaction": "tx",
    "Authorization": "authz",
    "EventEmit": "emit",
    "BusinessRule": "rule",
    "Response": "respond",
    "Annotation": "note",
}

# The one verb whose object is a value expression rather than an entity name
# (RFC-0015). It stays in `VERB_LEXICON` below so the closed table still answers
# "which verbs exist"; `_WfContext._step` routes it to its own derivation.
ASSIGN_VERB = "set"

# The second Assignment-deriving verb (issue #94): `format <target> from
# "<template>" [with <ref>...]`. Routed the same way `ASSIGN_VERB` is —
# `_WfContext._step` sends it to its own derivation rather than
# `_derive_effect`, because its object is a template + reference list, not an
# entity name.
FORMAT_VERB = "format"

# issue #96: `respond <ref> [<ref>...]` — a flat FieldMask over References,
# declaring the workflow's response body. Routed the same way `FORMAT_VERB`
# is: its object is a list of References, not a single entity name, so
# `_WfContext._step` sends it to its own derivation (`_derive_respond`)
# rather than `_derive_effect`. Unlike `format`/`set` it derives no
# Assignment — nothing is written — so it gets its own IR node kind,
# `Response`.
RESPOND_VERB = "respond"

# issue #111: `note "<template>" [with <ref>...]` — a span annotation, not an
# Effect (nothing changes state, the same judgment `respond` made for
# `Response`). Routed the same way `RESPOND_VERB` is: its object is a
# template + reference list, not an entity name, so `_WfContext._step` sends
# it to its own derivation (`_derive_note`) rather than `_derive_effect`.
NOTE_VERB = "note"

# issue #111, D3: more than this many `note`s in one workflow is a
# `note-cap-exceeded` compile warning — "log what earns its place" enforced
# at the vocabulary level, not left to author discipline.
NOTE_CAP = 16

# R1: the closed step-verb lexicon. verb -> (Effect kind, fixed fields)
VERB_LEXICON = {
    "set": ("Assignment", {}),
    "validate": ("Validation", {}),
    "authenticate": ("RepositoryCall", {"operation": "read"}),
    "load": ("RepositoryCall", {"operation": "read"}),
    "find": ("RepositoryCall", {"operation": "read"}),
    "read": ("RepositoryCall", {"operation": "read"}),
    # RFC-0025 §1: reuses the `query` operation `IDEMPOTENT_OPS`/`READ_OPS`/the
    # schema already carried but no verb had ever reached (RFC-0025 §Motivation).
    # `_derive_effect`'s generic `RepositoryCall` branch needs no change — the
    # entry's shape is identical to every other read-family verb's.
    "list": ("RepositoryCall", {"operation": "query"}),
    "create": ("RepositoryCall", {"operation": "create"}),
    "insert": ("RepositoryCall", {"operation": "create"}),
    "update": ("RepositoryCall", {"operation": "update"}),
    "delete": ("RepositoryCall", {"operation": "delete"}),
    "cache": ("CacheAccess", {"operation": "set"}),
    "invalidate": ("CacheAccess", {"operation": "invalidate"}),
    "call": ("NetworkCall", {}),
    "request": ("NetworkCall", {}),
    "emit": ("EventEmit", {}),
    "publish": ("EventEmit", {}),
    "authorize": ("Authorization", {}),
    # issue #94: States.Format-style string assembly, absorbed as a verb
    # rather than an expression extension (RFC-0028's design rule, first
    # applied). Shares `set`'s Assignment kind and binding rule; the shape
    # of its right-hand side is what `_derive_format` and `condition.FormatCall`
    # differ on.
    "format": ("Assignment", {}),
    # issue #96: declares the workflow's response body — a FieldMask, not an
    # Effect that changes state, so it gets its own kind rather than reusing
    # one of the nine Effect kinds above.
    "respond": ("Response", {}),
    # issue #111: see `NOTE_VERB` — a span annotation, not an Effect, gets
    # its own kind for the same reason `respond` does.
    "note": ("Annotation", {}),
}

# RFC-0026: `unknown-verb`'s did-you-mean, tier 1. The closed lexicon's actual
# failure mode is a semantic near-synonym, not a typo (the 7th audit: a
# plausible-sounding verb parses and becomes a no-op) — a character-similarity
# matcher alone cannot catch `persist` for `create` (ratio 0.31, below any
# usable cutoff). This table is suggestion-only — it does NOT extend
# VERB_LEXICON, so `gen_plugin_references.py` (which reads VERB_LEXICON only)
# never surfaces it. Ambiguous candidates spanning two verbs (e.g. `store`,
# `send`) are deliberately absent — a wrong suggestion is worse than none.
VERB_ALIASES = {
    "persist": "create",
    "save": "create",
    "fetch": "read",
    "get": "read",
    "retrieve": "read",
    "lookup": "read",
    "remove": "delete",
    "erase": "delete",
    "modify": "update",
    "change": "update",
    "notify": "emit",
}

# What a refusal calls the construct it is about. The guard check and the
# assignment check share `_Scope.check_reference`, and the message used to
# hard-code "guard condition" for both — so a rejected `set` sent the author
# looking for a guard they never wrote (r3 N-2). The subject travels with the
# call instead.
GUARD_SUBJECT = "guard condition"
ASSIGN_SUBJECT = "assignment"
RESPOND_SUBJECT = "response"

# The verbs that put a SINGLE-ROW binding in the execution scope, computed from
# the same test the lowerer uses to build `read_entities`. A refusal that names
# the repair has to name the *current* repair. `operation == "read"` only —
# `list` also derives `RepositoryCall`, but RFC-0025 §5 binds it to a RowSet,
# not a row, so it is not a fix for a single-row reference (RFC-0025 §6.1/§6.2).
READ_VERBS = tuple(verb for verb, (kind, attrs) in VERB_LEXICON.items()
                   if kind == "RepositoryCall"
                   and attrs.get("operation") == "read")

# Refinement surface forms (RFC-0002 §Full grammar).
PASCAL_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")      # PascalName
NUMBER_RE = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")    # Number
WORD_RE = re.compile(r"^[a-z][a-zA-Z0-9]*$")        # Word

POLICY_NAMES = ("retry", "rollback", "timeout", "parallel")
SECURITY_MECHANISMS = ("jwt", "role")
PERF_METRICS = ("response", "cache", "parallel", "prefetch", "batch")
VALUELESS_PERF = ("parallel", "prefetch", "batch")
ARGUMENT_MECHANISMS = ("role",)

# issue #119, D2: the read-only `caller` scope's closed field vocabulary —
# mirrors `interp.CALLER_NAMESPACE`/`caller_view`. No `roles` (plural), no
# `contains` — a single role, same as `interp.caller_view` resolves.
CALLER_NAMESPACE = "caller"
CALLER_FIELDS = ("subject", "role")

# `capability http <Name>` (issue #101 / RFC-0027): the outbound HTTP method
# and auth-scheme vocabularies. Closed sets, widened only on demand (issue
# text) — the same "add a table row, not a branch" shape as POLICY_NAMES etc.
HTTP_METHODS = ("get", "post", "put", "patch", "delete")
HTTP_AUTH_KINDS = ("bearer", "apikey")
# issue #109, D4: RFC 9110 §9.2.2 idempotent methods. `post`/`patch` are the
# two NOT in this set — pairing either with `retry` risks re-applying a
# non-idempotent effect (a double charge), hence the compile warning below.
HTTP_IDEMPOTENT_METHODS = ("get", "put", "delete")

# issue #99, D2: `expose` opt-in list surface. `list` is the only verb — a
# closed set of one, widened only if a later issue asks for more (RFC-0016
# §Open Questions precedent). The sort field's base type is restricted to
# Integer|DateTime because both compare with a plain `<`/`>` and serialize to
# a JSON value `json_extract` and Python's own `<` agree on ordering for
# (RFC-0025's `list` keyword already means something else — a RowSet bound
# inside a workflow body; this is a different grammar position, `service ...
# expose ...`, not a workflow step, so the two do not collide).
EXPOSE_VERBS = ("list",)
EXPOSE_SORT_BASES = ("Integer", "DateTime")


class LowerError(Exception):
    """Raised when a declaration cannot be lowered to IR."""


class LoaderError(LowerError):
    """Raised by `load_sources` for a multi-file input it cannot merge.

    A subclass of `LowerError` so every existing consumer that already
    catches `LowerError` (cli.py's `main()`, mcp_server.py's generic
    `except Exception`) handles this without new wiring (RFC-0031).
    """


def load_sources(paths):
    """The single loader every LNPL consumer shares (RFC-0031, issue #77;
    namespace/`internal` layout: RFC-0033).

    `paths` — a sequence of file paths, or a single directory path. A lone
    directory is inspected once to decide its layout (RFC-0033 §Reference-level
    "네임스페이스 유도"):

    - `*.lnpl` files directly under it -> **no namespace** (RFC-0031's
      original behavior, byte-identical): those files are collected in
      filename-sorted order, and any sibling subdirectories are ignored
      (mixed file+directory is not a namespace layout — files win).
    - zero `*.lnpl` files directly under it, only subdirectories -> a
      **namespace root**: each 1st-level subdirectory (visited in
      name-sorted order) becomes a namespace for the `*.lnpl` files inside
      it (see `_namespace_files`), including a nested `internal/` — the one
      extra level of depth RFC-0033 allows.

    Anything else (an explicit list of paths, even a single non-directory
    path) is a plain file list, merged in the given order with no namespace
    — RFC-0031's original explicit-list behavior, unchanged.

    Returns `list[Decl]` — exactly what `parser.parse()` already returns for
    one file, concatenated in merge order, with each `Decl`'s `.namespace`/
    `.internal` set from its file's path — so `lower()` and every other
    decls consumer needs no change beyond reading those two attributes.

    A declaration name repeated in two different files *within the same
    namespace* (namespace `None` counts as one) is rejected: `LoaderError`
    names both `<file>:<line>` locations, using the RFC-0033 qualified name
    (`<namespace>.<name>`, or the bare name when unnamespaced — byte-identical
    to pre-RFC-0033's message). The same name in two *different* namespaces
    is not a collision (RFC-0033's core relaxation). A name repeated within
    the *same* file is not this function's concern — that is whatever
    `lower()` already did with it (e.g. the entity/refine namespace check,
    RFC-0011 A.7(e)); this check only fires across a file boundary, so a
    single-file call can never trigger it (RFC-0031 D7: one source argument
    stays byte-identical).

    A bare `str` is accepted as shorthand for `[str]` (one path) — a plain
    string is itself a sequence of characters, and every pre-RFC-0031 caller
    of `cli.compile_source`/`cli._compile` passes one path this way; without
    this, `paths` would silently iterate character-by-character.
    """
    if isinstance(paths, str):
        paths = [paths]
    paths = list(paths)
    if not paths:
        raise LoaderError("no source given")

    if len(paths) == 1 and os.path.isdir(paths[0]):
        directory = paths[0]
        top_files = sorted(name for name in os.listdir(directory)
                           if name.endswith(".lnpl"))
        if top_files:
            files = [(os.path.join(directory, name), None, False)
                     for name in top_files]
        else:
            namespaces = sorted(
                name for name in os.listdir(directory)
                if os.path.isdir(os.path.join(directory, name)))
            if not namespaces:
                raise LoaderError("directory %r has no .lnpl files" % directory)
            files = []
            for namespace in namespaces:
                files.extend(_namespace_files(
                    os.path.join(directory, namespace), namespace))
    else:
        # An explicit list mixing in a directory is not "a single directory"
        # (the branch above) and not a file list either — reject it with a
        # LoaderError naming the offender, instead of letting `open()` raise
        # a bare IsADirectoryError past this function's contract.
        for path in paths:
            if os.path.isdir(path):
                raise LoaderError(
                    "%r is a directory — give a directory alone, or list "
                    ".lnpl files explicitly, not both" % path)
        files = [(path, None, False) for path in paths]

    merged = []
    declared_in = {}  # (namespace, decl name) -> (file, lineno) of first sighting
    for path, namespace, internal in files:
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        file_decls = parse(source)
        for decl in file_decls:
            decl.namespace = namespace
            decl.internal = internal
            key = (namespace, decl.name)
            prior = declared_in.get(key)
            if prior is not None and prior[0] != path:
                raise LoaderError(
                    "duplicate declaration %r: first declared at %s:%d, "
                    "again at %s:%d"
                    % (_qualified_name(namespace, decl.name),
                       prior[0], prior[1], path, decl.lineno))
            declared_in.setdefault(key, (path, decl.lineno))
        merged.extend(file_decls)
    return merged


def _qualified_name(namespace, name):
    """RFC-0033: the display/id form of a declared name — `<namespace>.<name>`
    when namespaced, the bare name otherwise (byte-identical to pre-RFC-0033
    for the `namespace=None` case, which is every call before RFC-0033)."""
    return "%s.%s" % (namespace, name) if namespace else name


def _namespace_files(ns_dir, namespace):
    """RFC-0033: the `(path, namespace, internal)` triples one 1st-level
    namespace directory contributes, filename-sorted (RFC-0031's determinism
    rule, extended to the whole namespace subtree so the merge order is
    reproducible regardless of `internal/`'s presence).

    A subdirectory of `ns_dir` other than exactly `internal` is a namespace
    layout nested past the one level RFC-0033 allows (`billing/eu/order.lnpl`)
    and is rejected; so is anything inside `internal/` that is itself a
    directory — `internal/` gets no further subdirectories of its own
    (RFC-0033 §Reference-level "네임스페이스 유도": "깊이는 `internal/` 한
    층까지만 허용한다").
    """
    entries = []  # (sort key, absolute path, internal)
    for name in sorted(os.listdir(ns_dir)):
        full = os.path.join(ns_dir, name)
        if os.path.isdir(full):
            if name != "internal":
                raise LoaderError(
                    "%r is nested more than one directory level below "
                    "namespace %r — RFC-0033 allows only an `internal/` "
                    "directory there" % (full, namespace))
            for iname in sorted(os.listdir(full)):
                ifull = os.path.join(full, iname)
                if os.path.isdir(ifull):
                    raise LoaderError(
                        "%r is nested inside `internal/` — RFC-0033 gives "
                        "`internal/` no subdirectories of its own" % ifull)
                if iname.endswith(".lnpl"):
                    entries.append((os.path.join("internal", iname), ifull, True))
        elif name.endswith(".lnpl"):
            entries.append((name, full, False))
    if not entries:
        raise LoaderError("namespace directory %r has no .lnpl files" % ns_dir)
    entries.sort(key=lambda e: e[0])
    return [(path, namespace, internal) for _, path, internal in entries]


def split_pascal(name):
    """`UserCreated` -> ['user', 'created']; `postgres` -> ['postgres'].

    A run of capitals is one word (`HTTPSEndpoint` -> ['https', 'endpoint']).
    When the run is followed by a lowercase letter, its last capital starts
    that next word: `APIKey` -> ['api', 'key'], not ['apik', 'ey']. Digits
    stay with the word they follow (`X509Certificate` -> ['x509',
    'certificate']).
    """
    parts, cur = [], ""
    for i, ch in enumerate(name):
        starts_word = ch.isupper() and cur and (
            not name[i - 1].isupper()
            or (i + 1 < len(name) and name[i + 1].islower()))
        if starts_word:
            parts.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        parts.append(cur)
    return [p.lower() for p in parts]


def derive_segments(name, kind):
    """R2 segment derivation, including the redundant-kind-word strip."""
    parts = split_pascal(name)
    word = KIND_WORD.get(kind)
    if word and len(parts) > 1 and parts[-1] == word:
        parts = parts[:-1]
    return parts


def derive_id(name, kind, namespace=None):
    """R2 + RFC-0033: full node id for a declaration.

    `namespace`, when given, inserts its `split_pascal` segments between the
    kind prefix and the name's own segments — `entity Order` in namespace
    `billing` becomes `entity.billing.order` (RFC-0033 §Reference-level
    "`derive_id`"). `namespace=None` — every call before RFC-0033, and every
    call in a compile unit with no subdirectories — yields the exact
    pre-RFC-0033 id: byte-identical.
    """
    if kind not in KIND_PREFIX:
        raise LowerError("no id prefix defined for kind %r" % kind)
    ns_segs = split_pascal(namespace) if namespace else []
    return ".".join([KIND_PREFIX[kind]] + ns_segs + derive_segments(name, kind))


class Module:
    """Lowered module: a flat node table plus the emit order (RFC-0001 D17)."""

    def __init__(self, name):
        self.name = name
        self._nodes = {}
        self._order = []
        # Compile-time diagnostics for this module. Deliberately beside the node
        # table, not in it: `to_document()` is the program's meaning and stays
        # byte-identical, so the golden `.lir.json` files never move.
        self.diagnostics = Diagnostics()

    def add(self, node):
        nid = node["id"]
        if nid in self._nodes:
            raise LowerError("duplicate node id %r" % nid)
        self._nodes[nid] = node
        self._order.append(nid)
        return node

    def get(self, nid):
        return self._nodes.get(nid)

    def nodes(self):
        return [self._nodes[i] for i in self._order]

    def to_document(self, version="0.1"):
        # Lazy import: `provenance` pulls in `vocab`/`capabilities`, both of
        # which import from this module at their own module level, so a
        # top-level import here would cycle (issue #136 plan D4). By the time
        # `to_document()` runs, `lower` is already fully loaded, so the cycle
        # never forms.
        from lnpl import provenance
        return {"lir_version": version, "module": self.name, "nodes": self.nodes(),
                "provenance": provenance.build()}


def _node(kind, nid, **fields):
    node = {"kind": kind, "id": nid}
    node.update({k: v for k, v in fields.items() if v is not None})
    return node


def _looks_like_url(target):
    """Advisory only (declared-not-bound, issue #101): a bare logical name vs.
    a URL literal. `drivers.HttpNetworkDriver` is the authority that actually
    rejects a malformed URL at the resolved target (RFC-0027, unchanged by
    #101) — this just decides whether `call <target>` needed a capability."""
    return target.startswith("http://") or target.startswith("https://")


def _parse_http_auth(line):
    """One `auth ...` line -> {"kind", "env"} or {"kind", "header", "env"}.

    RFC-0027 secrets principle (`--jwt-secret-env` precedent): only the
    environment variable's NAME is ever recorded — never a value.
    """
    tokens = line.tokens
    if len(tokens) < 2 or tokens[1] not in HTTP_AUTH_KINDS:
        raise LowerError(
            "line %d: `auth` takes one of %s"
            % (line.lineno, "/".join(HTTP_AUTH_KINDS)))
    kind = tokens[1]
    if kind == "bearer":
        if len(tokens) != 4 or tokens[2] != "from":
            raise LowerError(
                "line %d: `auth bearer` needs `from <ENV_NAME>`" % line.lineno)
        return {"kind": "bearer", "env": tokens[3]}
    if len(tokens) != 5 or tokens[3] != "from":
        raise LowerError(
            "line %d: `auth apikey` needs `<HEADER_NAME> from <ENV_NAME>`"
            % line.lineno)
    return {"kind": "apikey", "header": tokens[2], "env": tokens[4]}


def _parse_http_retry(line):
    """`retry <N> backoff <duration> [jitter]` -> {"count", "backoff_ms",
    "jitter"} (issue #109, D2). `N` must be a positive integer — `retry 0`
    is not a way to spell "no retry", it is just not a sentence anyone
    should write (the way to mean "no retry" is to not write the clause at
    all, RFC-0027-style declared-not-bound)."""
    from .lexer import duration_ms_or_none
    tokens = line.tokens
    if (len(tokens) < 4 or not tokens[1].isdigit() or tokens[2] != "backoff"):
        raise LowerError(
            "line %d: `retry` needs `<N> backoff <duration> [jitter]`"
            % line.lineno)
    count = int(tokens[1])
    if count < 1:
        raise LowerError(
            "line %d: `retry` count must be a positive integer, got %r"
            % (line.lineno, tokens[1]))
    backoff_ms = duration_ms_or_none(tokens[3])
    if backoff_ms is None:
        raise LowerError(
            "line %d: `retry backoff` needs a duration like `200ms`, got %r"
            % (line.lineno, tokens[3]))
    jitter = False
    rest = tokens[4:]
    if rest:
        if rest != ["jitter"]:
            raise LowerError(
                "line %d: `retry` takes only a trailing `jitter` flag, got %r"
                % (line.lineno, " ".join(rest)))
        jitter = True
    return {"count": count, "backoff_ms": backoff_ms, "jitter": jitter}


def _parse_http_breaker(line):
    """`breaker after <N> within <duration>` -> {"threshold", "window_ms"}
    (issue #109, D5)."""
    from .lexer import duration_ms_or_none
    tokens = line.tokens
    if (len(tokens) != 5 or tokens[1] != "after" or not tokens[2].isdigit()
            or tokens[3] != "within"):
        raise LowerError(
            "line %d: `breaker` needs `after <N> within <duration>`"
            % line.lineno)
    threshold = int(tokens[2])
    if threshold < 1:
        raise LowerError(
            "line %d: `breaker after` count must be a positive integer, "
            "got %r" % (line.lineno, tokens[2]))
    window_ms = duration_ms_or_none(tokens[4])
    if window_ms is None:
        raise LowerError(
            "line %d: `breaker within` needs a duration like `1m`, got %r"
            % (line.lineno, tokens[4]))
    return {"threshold": threshold, "window_ms": window_ms}


def _parse_http_path(line):
    """`path "<template>"` -> the template string (issue #109, D6). The
    quoted-literal shape mirrors `condition._parse_template_token` exactly
    (one double-quoted word, no embedded quote) since both feed the same
    `{}`-placeholder convention; kept as its own copy here rather than an
    import because this one additionally requires a leading `/` — a URL
    path, not `format`'s arbitrary string."""
    tokens = line.tokens
    if len(tokens) != 2:
        raise LowerError(
            "line %d: `path` takes one double-quoted template, no spaces"
            % line.lineno)
    token = tokens[1]
    if len(token) < 2 or token[0] != '"' or token[-1] != '"':
        raise LowerError(
            "line %d: `path` template must be one double-quoted word"
            % line.lineno)
    template = token[1:-1]
    if '"' in template:
        raise LowerError(
            "line %d: `path` template contains an embedded quote" % line.lineno)
    if not template.startswith("/"):
        raise LowerError(
            "line %d: `path` template must start with `/`, got %r"
            % (line.lineno, template))
    if "{}" not in template:
        raise LowerError(
            "line %d: `path` template %r has no `{}` placeholder — `path` "
            "exists only to be substituted by a `with <ref>...` call site; "
            "a fixed path with no placeholder belongs in the endpoint URL "
            "itself, not in a `path` declaration" % (line.lineno, template))
    return template


def _parse_http_capability(d, diagnostics=None):
    """`capability http <Name>` body lines -> {"method", "auth", "retry",
    "path", "breaker"} — the last three present only when declared.

    `method` is required (no silent POST default — issue #101's whole point is
    that method/auth are declared, not guessed); every other keyword is
    optional and may appear at most once (issue #109 widens the same shape).

    `diagnostics` (issue #109, D4), when given, gets a `retry-on-non-idempotent`
    warning when `method post`/`patch` is declared alongside `retry` — the
    non-idempotent methods, RFC 9110 §9.2.2.
    """
    method = None
    auth = None
    retry = None
    breaker = None
    path = None
    for line in d.items:
        head = line.tokens[0]
        if head == "method":
            if method is not None:
                raise LowerError(
                    "line %d: capability http %s declares `method` twice"
                    % (line.lineno, d.name))
            if len(line.tokens) != 2 or line.tokens[1] not in HTTP_METHODS:
                raise LowerError(
                    "line %d: `method` takes one of %s"
                    % (line.lineno, "/".join(HTTP_METHODS)))
            method = line.tokens[1]
        elif head == "auth":
            if auth is not None:
                raise LowerError(
                    "line %d: capability http %s declares `auth` twice"
                    % (line.lineno, d.name))
            auth = _parse_http_auth(line)
        elif head == "retry":
            if retry is not None:
                raise LowerError(
                    "line %d: capability http %s declares `retry` twice"
                    % (line.lineno, d.name))
            retry = _parse_http_retry(line)
        elif head == "breaker":
            if breaker is not None:
                raise LowerError(
                    "line %d: capability http %s declares `breaker` twice"
                    % (line.lineno, d.name))
            breaker = _parse_http_breaker(line)
        elif head == "path":
            if path is not None:
                raise LowerError(
                    "line %d: capability http %s declares `path` twice"
                    % (line.lineno, d.name))
            path = _parse_http_path(line)
        else:
            raise LowerError(
                "line %d: capability http takes `method`/`auth`/`retry`/"
                "`breaker`/`path`, got %r" % (line.lineno, head))
    if method is None:
        raise LowerError(
            "line %d: capability http %s declares no `method` — one of %s "
            "is required" % (d.lineno, d.name, "/".join(HTTP_METHODS)))
    if (retry is not None and method not in HTTP_IDEMPOTENT_METHODS
            and diagnostics is not None):
        diagnostics.add(
            code="retry-on-non-idempotent",
            where=derive_id(d.name, "Capability"),
            subject="method %s" % method,
            message="capability http %s declares `method %s` with `retry` — "
                    "a non-idempotent method may be applied more than once "
                    "on a retry; pair it with an idempotency key (issue "
                    "#113) or drop `retry`" % (d.name, method),
            line=d.lineno)
    return {"method": method, "auth": auth, "retry": retry,
            "breaker": breaker, "path": path}


def _parse_event_body(d):
    """`event ...` body lines -> `(subscribe: bool, consume: (name, lineno) or None)`.

    Two shapes share this clause-free content-line slot (parser.py:366-372):
    `subscribe` (issue #103, D1) — a bare flag, one word, at most once, the
    same shape `_parse_perf_line`'s `VALUELESS_PERF` branch already gives a
    flag metric — and `consume by <Workflow>` (issue #118, D1) — exactly
    three tokens, at most once. Neither excludes the other, and neither
    excludes an `on <Entity> ...`/`on schedule ...` source parsed separately
    from `d.extra` above: `subscribe` means "expose over SSE", `consume by`
    means "run this workflow on arrival" — independent opt-ins on the same
    declaration.

    Structural validation only. `subscribe` reaching the IR is what
    `serve.py` reads to derive the SSE route (D2); the consume target's
    *existence* as a declared workflow is checked by the caller, which alone
    has `by_kind["workflow"]` in hand — this function only shapes the line.
    """
    subscribed = False
    consume = None
    for line in d.items:
        tokens = line.tokens
        if tokens == ["subscribe"]:
            if subscribed:
                raise LowerError(
                    "line %d: event %s declares `subscribe` twice"
                    % (line.lineno, d.name))
            subscribed = True
            continue
        if len(tokens) == 3 and tokens[0] == "consume" and tokens[1] == "by":
            if consume is not None:
                raise LowerError(
                    "line %d: event %s declares `consume by` twice"
                    % (line.lineno, d.name))
            consume = (tokens[2], line.lineno)
            continue
        raise LowerError(
            "line %d: event %s takes only a bare `subscribe` line or "
            "`consume by <Workflow>`, got %r"
            % (line.lineno, d.name, " ".join(tokens)))
    return subscribed, consume


def _parse_policy_line(tokens, lineno):
    head = tokens[0]
    if head not in POLICY_NAMES:
        raise LowerError("line %d: unknown policy %r (allowed: %s)"
                         % (lineno, head, ", ".join(POLICY_NAMES)))
    if head == "retry":
        if len(tokens) != 2 or not tokens[1].isdigit():
            raise LowerError("line %d: `retry` needs an integer" % lineno)
        return {"name": "retry", "value": int(tokens[1])}
    if head == "timeout":
        if len(tokens) != 2 or not is_duration(tokens[1]):
            raise LowerError("line %d: `timeout` needs a duration (e.g. 3s)" % lineno)
        return {"name": "timeout", "value": tokens[1]}
    if head == "parallel":
        # issue #108 D2-r1: the bare flag form stays valid (cap falls back to
        # the block's own step count at run time — interp.py); an optional
        # integer argument sets an explicit concurrency cap, the same arity
        # `retry` above already has.
        if len(tokens) == 1:
            return {"name": "parallel"}
        if (len(tokens) != 2 or not tokens[1].isdigit()
                or int(tokens[1]) < 1):
            # A cap of 0 workers can never run a block's steps at all — not
            # a smaller concurrency limit, a stuck one — so it is refused
            # here rather than silently falling back to "no cap" the way
            # `con["parallel_cap"] or len(steps)` (interp.py) treats any
            # falsy value. Refusing it at the source is what keeps this
            # RFC-0041/RFC-0003's "N is never exceeded" claim actually true
            # for every value the grammar accepts.
            raise LowerError("line %d: `parallel` takes an optional positive "
                             "integer cap (e.g. `parallel 3`)" % lineno)
        return {"name": "parallel", "value": int(tokens[1])}
    if len(tokens) != 1:
        raise LowerError("line %d: `%s` takes no argument" % (lineno, head))
    return {"name": head}


def _parse_perf_line(tokens, lineno):
    metric = tokens[0]
    if metric not in PERF_METRICS:
        raise LowerError("line %d: unknown performance metric %r (allowed: %s)"
                         % (lineno, metric, ", ".join(PERF_METRICS)))
    if metric in VALUELESS_PERF:
        # A flag metric carries no value; `budgets[].value` is optional for exactly
        # this reason (schema revision 2026-07-31, formerly gap A.4-5).
        if len(tokens) != 1:
            raise LowerError("line %d: `%s` is a flag and takes no value"
                             % (lineno, metric))
        return {"metric": metric}
    if metric == "response":
        if len(tokens) != 3 or tokens[1] not in COMPARATORS:
            raise LowerError("line %d: `response` needs <comparator> <duration>" % lineno)
        return {"metric": "response", "value": tokens[1] + tokens[2]}
    if len(tokens) != 2:
        raise LowerError("line %d: `%s` needs one value" % (lineno, metric))
    return {"metric": metric, "value": tokens[1]}


_TIME_OF_DAY_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


def _schedule_source(spec, lineno):
    """`{every, at, zone}` -> the IR's schedule source, or a refusal.

    Every refusal names the accepted set, because the sets are small and closed
    and an author who guessed wrong has no other way to discover them.
    """
    every, at, zone = spec["every"], spec["at"], spec["zone"]
    if every not in SCHEDULE_RECURRENCES:
        raise LowerError(
            "line %d: unknown schedule recurrence %r (allowed: %s). RFC-0016 "
            "§Open Questions records why the set is this small"
            % (lineno, every, ", ".join(SCHEDULE_RECURRENCES)))
    if not _TIME_OF_DAY_RE.match(at):
        raise LowerError(
            "line %d: invalid time of day %r — write HH:MM with two digits "
            "each, from 00:00 to 23:59" % (lineno, at))
    if zone not in SCHEDULE_ZONES:
        if "/" in zone:
            raise LowerError(
                "line %d: unsupported schedule zone %r (allowed: %s). An IANA "
                "zone name has to be resolved against a tz database, and a "
                "minimal build image carries none — the set of accepted "
                "programs would then depend on the machine compiling them. "
                "RFC-0016 §Open Questions tracks vendoring one"
                % (lineno, zone, ", ".join(SCHEDULE_ZONES)))
        raise LowerError(
            "line %d: unsupported schedule zone %r (allowed: %s). A zone "
            "abbreviation is ambiguous and a bare offset ignores DST, so "
            "RFC-0016 accepts neither" % (lineno, zone, ", ".join(SCHEDULE_ZONES)))
    return {"every": every, "at": at, "zone": zone}


def _declaration_diagnostics(diagnostics, clause, names, where):
    """Report every declaration the runtime does not actually enforce (#38).

    The status comes from `diagnostics.ENFORCEMENT`, which is the canonical
    matrix — so a claim that something is enforced has to be made there (and
    survive `test_enforcement_matrix.py`), not decided here per call site.

    A name absent from the matrix is skipped rather than guessed at: the parsers
    above already reject anything outside the closed sets, so an absent key means
    the matrix and the language drifted, which is the drift gate's failure to
    report, not a new error to invent at compile time.

    `names` is `[(name, lineno), ...]` (RFC-0024) — the source line of the
    clause line each name came from, paired at the call site where the parser's
    per-line `lineno` is still in hand, and carried straight through to the
    diagnostic rather than re-derived here.
    """
    for name, lineno in names:
        entry = ENFORCEMENT.get((clause, name))
        if entry is None or entry[0] == ENFORCED:
            continue
        status, note = entry
        code = ("declared-measured-only" if status == "measured"
                else "declared-not-enforced")
        diagnostics.add(code=code, where=where,
                        subject="%s %s" % (clause, name),
                        message="declared but %s: %s" % (status, note),
                        line=lineno)


def _parse_security_line(tokens, lineno):
    head = tokens[0]
    if head not in SECURITY_MECHANISMS:
        raise LowerError("line %d: unknown security mechanism %r "
                         "(allowed: jwt, role <r>)" % (lineno, head))
    if head in ARGUMENT_MECHANISMS:
        if len(tokens) != 2:
            raise LowerError("line %d: `%s` needs one argument" % (lineno, head))
        return head + " " + tokens[1]
    if len(tokens) != 1:
        raise LowerError("line %d: `%s` takes no argument" % (lineno, head))
    return head


def _parse_expose_line(tokens, lineno, registry, base_of):
    """issue #99, D2: `list <Entity> by <field>` -> `{entity, field}`.

    Unlike `_parse_security_line`/`_parse_policy_line` this is not a closed
    keyword lookup alone: `<Entity>` and `<field>` are live references, so a
    typo here is a dangling reference (RFC-0001 structure rule 6), same as an
    undeclared capability in a `database` line — not a guess at what was
    meant.
    """
    verb = tokens[0]
    if verb not in EXPOSE_VERBS:
        raise LowerError("line %d: unknown expose verb %r (allowed: %s)"
                         % (lineno, verb, ", ".join(EXPOSE_VERBS)))
    if len(tokens) != 4 or tokens[2] != "by":
        raise LowerError(
            "line %d: `expose %s` needs `%s <Entity> by <field>`"
            % (lineno, verb, verb))
    entity_name, field_name = tokens[1], tokens[3]
    entity = next((e for e in registry.values() if e["name"] == entity_name), None)
    if entity is None:
        raise LowerError(
            "line %d: %r is not a declared entity (dangling reference — "
            "RFC-0001 structure rule 6)" % (lineno, entity_name))
    field = next((f for f in entity["fields"] if f["name"] == field_name), None)
    if field is None:
        raise LowerError("line %d: entity %s has no field %r"
                         % (lineno, entity_name, field_name))
    base = base_of.get(field["type"], field["type"])
    if base not in EXPOSE_SORT_BASES:
        raise LowerError(
            "line %d: expose list sort field must be Integer or DateTime "
            "(allowed: %s), but %s.%s is base %r"
            % (lineno, ", ".join(EXPOSE_SORT_BASES), entity_name, field_name, base))
    return {"entity": entity["id"], "field": field_name}


# issue #116, D1: `list <Entity> where <cond> [order by <field> [desc]]
# [limit <N>]` — clause order fixed, all three tail clauses (`where`'s
# condition included) collectively optional (a bare `list <Entity>` is
# still the RFC-0025 form). Comparators split by D2: `<`/`<=`/`>`/`>=` keep
# the Integer/DateTime dimension restriction `_dimension_of` already
# enforces for guards; `==`/`!=` additionally allow any base type, as long
# as both sides agree, since equality does not need an evaluator the way an
# ordering does.
_LIST_ORDER_COMPARATORS = ("<", "<=", ">", ">=")


def _parse_list_clauses(rest, lineno, entity, base_of):
    """`list <Entity>`'s trailing tokens (issue #116, D1) -> `(predicate,
    order, limit)`, each `None` when absent. Called only when `rest` is
    non-empty — the empty case is the RFC-0025 regression path and never
    reaches here (`_derive_effect` returns the unchanged 4-key node for it).
    """
    if rest[0] != "where":
        raise LowerError(
            "line %d: `list` accepts `where <cond> [order by <field> "
            "[desc]] [limit <N>]`, got %r" % (lineno, " ".join(rest)))
    boundary = len(rest)
    for i in range(1, len(rest)):
        if rest[i] in ("order", "limit"):
            boundary = i
            break
    cond_tokens = rest[1:boundary]
    if not cond_tokens:
        raise LowerError("line %d: `where` needs a condition" % lineno)
    predicate = _parse_predicate_terms(" ".join(cond_tokens), lineno, entity, base_of)
    tail = rest[boundary:]

    order = None
    if tail[:1] == ["order"]:
        if len(tail) < 3 or tail[1] != "by":
            raise LowerError(
                "line %d: `order` must be `order by <field> [desc]`" % lineno)
        field_name = tail[2]
        consumed = 3
        desc = False
        if len(tail) > 3 and tail[3] == "desc":
            desc = True
            consumed = 4
        order = _parse_list_order_field(field_name, desc, lineno, entity, base_of)
        tail = tail[consumed:]

    limit = None
    if tail[:1] == ["limit"]:
        if len(tail) < 2:
            raise LowerError(
                "line %d: `limit` needs exactly one integer argument" % lineno)
        if not tail[1].isdigit():
            raise LowerError(
                "line %d: `limit` needs a positive integer, got %r"
                % (lineno, tail[1]))
        n = int(tail[1])
        if n < 1:
            raise LowerError(
                "line %d: `limit` must be at least 1, got %d" % (lineno, n))
        limit = n
        tail = tail[2:]

    if tail:
        raise LowerError(
            "line %d: unexpected trailing tokens %r after `list` clauses "
            "(clause order is where -> order by -> limit)"
            % (lineno, " ".join(tail)))

    return predicate, order, limit


def _parse_predicate_terms(cond_text, lineno, entity, base_of):
    """`where`'s condition text -> a conjunction list of `{field, op,
    value}` dicts (issue #116, D4) — a structured node, not the raw text,
    so the field name reaching the driver is always one the compiler
    already whitelisted (RFC-0016's injection principle applied to `list`).

    Reuses `condition.parse_condition` verbatim (D1: no new parser) — this
    function only judges what that parser already produced, against the
    entity being listed.
    """
    from .condition import And, ConditionError, Presence, Ref, parse_condition, value_to_string

    try:
        cond = parse_condition(cond_text)
    except ConditionError as e:
        raise LowerError("line %d: %s" % (lineno, e))
    if isinstance(cond, Presence):
        raise LowerError(
            "line %d: `list where` supports comparisons only (no `exists`/"
            "`missing` presence checks), got %r" % (lineno, cond_text))
    terms = cond.terms if isinstance(cond, And) else (cond,)

    fields_by_name = {f["name"]: f for f in entity["fields"]}
    result = []
    for term in terms:
        left = term.left
        if not isinstance(left, Ref) or left.namespace is not None:
            raise LowerError(
                "line %d: the left side of a `list where` comparison must "
                "be a bare field of %s, got %r"
                % (lineno, entity["name"], value_to_string(left)))
        field = fields_by_name.get(left.field)
        if field is None:
            raise LowerError(
                "line %d: entity %s has no field %r (candidates: %s)"
                % (lineno, entity["name"], left.field,
                   ", ".join(sorted(fields_by_name)) or "none"))
        base = base_of.get(field["type"], field["type"])
        if term.op in _LIST_ORDER_COMPARATORS:
            if base not in EXPOSE_SORT_BASES:
                raise LowerError(
                    "line %d: `list where` order comparison (%s) needs an "
                    "Integer or DateTime field, but %s.%s is base %r"
                    % (lineno, term.op, entity["name"], left.field, base))
        elif base not in EXPOSE_SORT_BASES:
            # D2: equality across any type, but only between two references
            # of the same declared base — there is no literal syntax for a
            # UUID/Text/Email value in this grammar (`condition.py`'s
            # `Operand` is `Reference | Integer | Duration`), so a Lit or
            # Arith on the right can never be the same type as a non-
            # scalar/instant field. The same-base-type check itself needs
            # the workflow's binding scope (which entity a qualified
            # reference names) — deferred to `_check_list_predicate`, the
            # post-pass every other guard-shaped check already runs in.
            if not isinstance(term.right, Ref):
                raise LowerError(
                    "line %d: %s.%s is %s — equality against it needs a "
                    "reference (a single-row binding field or "
                    "`input.%s`), not a literal or arithmetic expression"
                    % (lineno, entity["name"], left.field, base, left.field))
        result.append({"field": left.field, "op": term.op,
                       "value": value_to_string(term.right)})
    return result


def _parse_list_order_field(field_name, desc, lineno, entity, base_of):
    """`order by <field> [desc]` (issue #116, D7) — reuses `expose list`'s
    sort-field check (`EXPOSE_SORT_BASES`) verbatim, plus a candidates list
    on an unknown field (issue #116 DoD item 5)."""
    fields_by_name = {f["name"]: f for f in entity["fields"]}
    field = fields_by_name.get(field_name)
    if field is None:
        raise LowerError(
            "line %d: entity %s has no field %r (candidates: %s)"
            % (lineno, entity["name"], field_name,
               ", ".join(sorted(fields_by_name)) or "none"))
    base = base_of.get(field["type"], field["type"])
    if base not in EXPOSE_SORT_BASES:
        raise LowerError(
            "line %d: `order by` field must be Integer or DateTime "
            "(allowed: %s), but %s.%s is base %r"
            % (lineno, ", ".join(EXPOSE_SORT_BASES), entity["name"],
               field_name, base))
    return {"field": field_name, "desc": desc}


def _number(tok):
    """RFC-0002 `Number` -> int when it has no fraction, else float.

    `min 1` must stay `1`: the A.6.4 fragment for PositiveInteger writes an
    integer, and a float would serialize as 1.0 and stop matching it.
    """
    return float(tok) if "." in tok else int(tok)


def _enum_value(tok, lineno):
    """RFC-0002 `EnumValue ::= Word | Number`."""
    if NUMBER_RE.match(tok):
        return _number(tok)
    if WORD_RE.match(tok):
        return tok
    raise LowerError("line %d: %r is not a valid enum value (a Word or a Number)"
                     % (lineno, tok))


def _check_enum_member(value, base, lineno):
    """RFC-0011 A.6.3 — a member must be a value the base can actually hold.

    `Integer` is narrower than its category: `enum` enumerates the admissible
    values, so a member with a fractional part is dead. `min`/`max` are bounds
    and stay category-wide — `min 1.5` on an Integer still admits every int >= 2.
    """
    if BASE_CATEGORY[base] == "text":
        ok, form = isinstance(value, str), "a Word"
    elif base == "Integer":
        ok, form = isinstance(value, int), "a Number with no fractional part"
    else:                       # Decimal -- the only other base admitting enum
        ok, form = isinstance(value, (int, float)), "a Number"
    if not ok:
        raise LowerError("line %d: enum value %r cannot be a value of base %r "
                         "(allowed: %s — RFC-0011 A.6.3)"
                         % (lineno, value, base, form))


def _parse_facet_line(tokens, lineno, allowed, base):
    """One FacetLine -> (name, value). RFC-0001 A.6.3 / RFC-0002 §Full grammar.

    The order of the checks is a contract the tests rely on: vocabulary, then
    applicability to the base's category, then arity, then value form. So
    `maxLength` on a Boolean fails as inapplicable, not as a bad number.
    """
    name = tokens[0]
    if name not in FACET_NAMES:
        raise LowerError("line %d: unknown facet %r (allowed: %s)"
                         % (lineno, name, ", ".join(FACET_NAMES)))
    if name not in allowed:
        raise LowerError(
            "line %d: facet %r does not apply to base %r (allowed: %s)"
            % (lineno, name, base,
               ", ".join(sorted(allowed)) or "none — this base admits no facets"))
    if name == "enum":
        if len(tokens) < 2:
            raise LowerError("line %d: `enum` needs at least one value" % lineno)
        values = [_enum_value(t, lineno) for t in tokens[1:]]
        for value in values:
            _check_enum_member(value, base, lineno)
        return name, values
    if len(tokens) != 2:
        raise LowerError("line %d: `%s` needs exactly one value" % (lineno, name))
    if name == "pattern":
        # A space or `#` inside the regex is removed by the lexer before we see
        # it, so compiling the value is what catches a truncation that breaks a
        # construct (`^a[b#c]$` -> `^a[b`). A truncation that still compiles
        # (`^a#b$` -> `^a`) survives — see test_KNOWN_LIMITATION_* in test_lower.
        try:
            re.compile(tokens[1])
        except re.error as exc:
            raise LowerError(
                "line %d: `pattern` is not a valid regex: %s (a space or `#` "
                "inside the regex is removed by the lexer — RFC-0002 §Full grammar)"
                % (lineno, exc))
        return name, tokens[1]
    if name in ("minLength", "maxLength"):
        if not tokens[1].isdigit():
            raise LowerError("line %d: `%s` needs a non-negative integer, got %r"
                             % (lineno, name, tokens[1]))
        return name, int(tokens[1])
    if not NUMBER_RE.match(tokens[1]):
        raise LowerError("line %d: `%s` needs a number, got %r"
                         % (lineno, name, tokens[1]))
    return name, _number(tokens[1])


def _refinement_node(name, base, facets):
    """A.6.2 — the one Refinement node shape.

    A user declaration and a built-in preset both come through here, so a preset
    serializes to exactly the node the user would have written (A.6.4: presets
    are not privileged).
    """
    return _node("Refinement", derive_id(name, "Refinement"),
                 name=name, base=base, facets=facets)


def _lower_refine(decl, taken):
    """One `refine` block -> a Refinement node. A.7 invariants b/c/d/e live here."""
    if not PASCAL_RE.match(decl.name):
        raise LowerError("line %d: refinement name %r must be PascalCase"
                         % (decl.lineno, decl.name))
    base = decl.extra["base"]
    if base not in BASE_CATEGORY:
        raise LowerError(
            "line %d: %r is not one of the 18 semantic types — a refinement's "
            "base cannot itself be a refinement (RFC-0001 A.6.2)"
            % (decl.lineno, base))
    if decl.name in taken:
        raise LowerError(
            "line %d: %r is already a semantic type, a built-in preset, an "
            "entity, or a refinement declared in this module "
            "(RFC-0001 A.6.2, RFC-0011 A.7)"
            % (decl.lineno, decl.name))
    allowed = facets_for_base(base)
    facets = {}
    for line in decl.items:
        name, value = _parse_facet_line(line.tokens, line.lineno, allowed, base)
        if name in facets:
            raise LowerError("line %d: facet %r is given twice" % (line.lineno, name))
        facets[name] = value
    if not facets:
        raise LowerError("refinement %s declares no facets" % decl.name)
    return _refinement_node(decl.name, base, facets)


def _resolve_type(name, refined_names, used_presets, lineno):
    """A.6.1 name resolution. Returns `name` unchanged — `fields[].type` holds a
    type name, never a node id.

    Order: the 18 base names, then this document's Refinements. A built-in preset
    a field names joins that second group and is recorded so it gets emitted
    (A.6.4 emit-on-use), which is what makes the document self-contained.
    """
    if name in BASE_CATEGORY or name in refined_names:
        return name
    if name in PRESETS:
        if name not in used_presets:
            used_presets.append(name)      # first-use order keeps output stable
        return name
    raise LowerError(
        "line %d: %r is not one of the 18 semantic types, a refinement declared "
        "in this module, or a built-in preset (RFC-0001 A.6.1)" % (lineno, name))


def lower(decls, module_name):
    """[Decl] -> Module, emitting nodes in RFC-0001 canonical order."""
    mod = Module(module_name)

    by_kind = {"capability": [], "entity": [], "event": [], "service": [],
               "workflow": [], "refine": []}
    for d in decls:
        by_kind[d.kind].append(d)

    # ---- Refinements (RFC-0001 A.6). A declared block becomes a node whether or
    # not a field names it; the built-in presets are appended on use, below.
    # RFC-0011 A.7 (e): an entity and a refinement land in one
    # `components/schemas` name space, so a collision must fail here rather than
    # at generation time. `by_kind` is built above, so an entity declared later
    # in the file than the `refine` still takes its name.
    taken = set(BASE_CATEGORY) | set(PRESETS) | {d.name for d in by_kind["entity"]}
    refine_nodes = []
    refined_names = set()
    used_presets = []
    for d in by_kind["refine"]:
        refine_nodes.append(_lower_refine(d, taken))
        taken.add(d.name)
        refined_names.add(d.name)

    # Entity registry. A module may declare several entities; a step selects one
    # by naming it as its object (`load order`), which the grammar already gives us.
    # With a single entity the object may be omitted, as the golden scenario does.
    registry = {}
    for decl in by_kind["entity"]:
        fields = []
        for line in decl.clauses.get("field", []):
            if len(line.tokens) not in (2, 3):
                raise LowerError(
                    "line %d: field must be `<name> <Type>` or `<name> <Type> "
                    "derived`" % line.lineno)
            if len(line.tokens) == 3 and line.tokens[2] != "derived":
                raise LowerError(
                    "line %d: unknown field modifier %r — `derived` is the "
                    "only one (issue #95)" % (line.lineno, line.tokens[2]))
            if not WORD_RE.match(line.tokens[0]):
                raise LowerError(
                    "line %d: field name %r must be a lowercase word — "
                    "`<name> <Type>` where <name> starts with a lowercase "
                    "letter followed by letters or digits only (%s)"
                    % (line.lineno, line.tokens[0], WORD_RE.pattern))
            field = {"name": line.tokens[0],
                    "type": _resolve_type(line.tokens[1], refined_names,
                                          used_presets, line.lineno)}
            if len(line.tokens) == 3:
                field["derived"] = True
            fields.append(field)
        if not fields:
            raise LowerError("entity %s declares no fields" % decl.name)
        from .condition import PAYLOAD_NAMESPACE
        from .repo_policy import binding_name as _binding_name
        if _binding_name({"name": decl.name}) == PAYLOAD_NAMESPACE:
            raise LowerError(
                "line %d: entity %r would bind as %r, which RFC-0015 reserves "
                "for the run's input payload (`input.<field>`) — rename the "
                "entity" % (decl.lineno, decl.name, PAYLOAD_NAMESPACE))
        eid = derive_id(decl.name, "Entity", decl.namespace)
        if eid in registry:
            raise LowerError("two entities derive the same id %r" % eid)
        registry[eid] = {"decl": decl, "id": eid, "name": decl.name, "fields": fields}

    # Declared type name -> one of the 18 bases. RFC-0015's operand check asks
    # "is this an Integer", and `refine SafeStock of Integer` must answer yes,
    # so the question is put to the base rather than to the written name.
    base_of = {name: name for name in BASE_CATEGORY}
    base_of.update({n["name"]: n["base"] for n in refine_nodes})
    base_of.update({name: entry["base"] for name, entry in PRESETS.items()})

    cap_ids = [derive_id(d.name, "Capability") for d in by_kind["capability"]]
    cap_by_name = {d.name: derive_id(d.name, "Capability") for d in by_kind["capability"]}
    # issue #101/#109: which declared capabilities carry outbound HTTP
    # metadata, and what it is — `_derive_effect`'s NetworkCall branch reads
    # `http_caps` both to flag a `call <target>` naming no `capability http`
    # declaration (membership) and to check a `with <ref>...` clause's
    # argument count against the capability's declared `path` template's
    # `{}` count (issue #109, D6). Parsed once here, not re-parsed by the
    # Capability node-emission loop below, so a diagnostic like
    # `retry-on-non-idempotent` is never emitted twice for the same line.
    http_caps = {d.name: _parse_http_capability(d, diagnostics=mod.diagnostics)
                for d in by_kind["capability"]
                if d.extra.get("capability_kind") == "http"}

    # ---- workflow ownership: nearest preceding service (RFC-0002 A.2 R2) ----
    owner_of = {}
    last_service = None
    for d in decls:
        if d.kind == "service":
            last_service = d
        elif d.kind == "workflow":
            owner_of[id(d)] = last_service

    # ---- Service nodes (+ their constraints, emitted later) ----
    # #112: which services declare `policy rollback`, keyed by `id(d)` so
    # `owner_of` (above) can answer "does this workflow's service claim
    # rollback?" for `_check_rollback_escapes_network` below.
    rollback_services = set()
    service_nodes, constraint_nodes = [], []
    for d in by_kind["service"]:
        sid = derive_id(d.name, "Service")
        segs = derive_segments(d.name, "Service")
        constraints = []
        if "policy" in d.clauses:
            pid = ".".join([KIND_PREFIX["Policy"]] + segs)
            rules = [_parse_policy_line(line.tokens, line.lineno) for line in d.clauses["policy"]]
            if any(r["name"] == "rollback" for r in rules):
                rollback_services.add(id(d))
            constraint_nodes.append(_node("Policy", pid, rules=rules))
            constraints.append(pid)
            _declaration_diagnostics(
                mod.diagnostics, "policy",
                [(r["name"], line.lineno)
                 for r, line in zip(rules, d.clauses["policy"])], pid)
        if "security" in d.clauses:
            secid = ".".join([KIND_PREFIX["Security"]] + segs)
            mechs = [_parse_security_line(line.tokens, line.lineno) for line in d.clauses["security"]]
            constraint_nodes.append(_node("Security", secid, mechanisms=mechs))
            constraints.append(secid)
            # `role admin` is the same declaration as `role owner` as far as
            # enforcement goes, so the head token is the subject.
            _declaration_diagnostics(
                mod.diagnostics, "security",
                [(m.split(" ", 1)[0], line.lineno)
                 for m, line in zip(mechs, d.clauses["security"])], secid)
        if "performance" in d.clauses:
            perfid = ".".join([KIND_PREFIX["Performance"]] + segs)
            budgets = [_parse_perf_line(line.tokens, line.lineno) for line in d.clauses["performance"]]
            constraint_nodes.append(_node("Performance", perfid, budgets=budgets))
            constraints.append(perfid)
            _declaration_diagnostics(
                mod.diagnostics, "performance",
                [(b["metric"], line.lineno)
                 for b, line in zip(budgets, d.clauses["performance"])], perfid)
        # issue #99, D2: `expose list <Entity> by <field>` -> one Expose node
        # per line, ids scoped under the service the same way `goal` lines
        # become numbered BusinessRule nodes below. Expose nodes ride in
        # `children` (not `constraints`): like a Workflow, and unlike
        # Security/Policy/Performance, an Expose node synthesizes a servable
        # route rather than constraining one.
        expose_nodes = []
        for n, line in enumerate(d.clauses.get("expose", []), start=1):
            parsed = _parse_expose_line(line.tokens, line.lineno, registry, base_of)
            expose_nodes.append(_node(
                "Expose", "%s.expose.%d" % (sid, n),
                entity=parsed["entity"], field=parsed["field"], line=line.lineno))
        # Capability attribution (formerly the provisional R3). A service takes the
        # capabilities its own `database` clause names; with no such clause, a
        # single-service module attributes all of them, and a multi-service module
        # is a compile error rather than a guess.
        declared = []
        for line in d.clauses.get("database", []):
            if len(line.tokens) != 1:
                raise LowerError("line %d: a database line names one capability"
                                 % line.lineno)
            capname = line.tokens[0]
            if capname not in cap_by_name:
                raise LowerError("line %d: %r is not a declared capability "
                                 "(dangling reference — RFC-0001 structure rule 6)"
                                 % (line.lineno, capname))
            if cap_by_name[capname] not in declared:
                declared.append(cap_by_name[capname])
        if declared:
            requires = declared
        elif len(by_kind["service"]) == 1:
            requires = list(cap_ids)
        elif cap_ids:
            raise LowerError(
                "service %s declares no `database` clause, and this module has %d "
                "services — capability attribution would be a guess. Name the "
                "capabilities each service requires in its `database` clause."
                % (d.name, len(by_kind["service"])))
        else:
            requires = []

        # `goal` lines become BusinessRule nodes owned by this Service (RFC-0002
        # Appendix A.2: GoalLine -> BusinessRule). Until this existed the clause
        # parsed and then vanished — the worst kind of gap, a declaration that
        # silently does nothing.
        goal_nodes = []
        for n, line in enumerate(d.clauses.get("goal", []), start=1):
            statement = " ".join(line.tokens)
            goal_nodes.append(_node("BusinessRule", "%s.goal.%d" % (sid, n),
                                    name=statement, statement=statement,
                                    line=line.lineno))

        children = [g["id"] for g in goal_nodes]
        children += [derive_id(w.name, "Workflow")
                     for w in by_kind["workflow"] if owner_of.get(id(w)) is d]
        children += [e["id"] for e in expose_nodes]
        service_nodes.append(_node(
            "Service", sid, name=d.name,
            requires=requires or None,
            constraints=constraints or None,
            children=children or None,
            line=d.lineno))
        service_nodes.extend(goal_nodes)
        service_nodes.extend(expose_nodes)

    # A.6.4 emit-on-use: a preset a field named rides into this document as a
    # node, built by the same function a declaration uses. An unused preset is
    # not emitted.
    for name in used_presets:
        spec = preset(name)
        refine_nodes.append(_refinement_node(name, spec["base"], spec["facets"]))

    for n in refine_nodes:
        mod.add(n)

    for n in service_nodes:
        mod.add(n)

    for ent in registry.values():
        # RFC-0033: `namespace` rides the node only when set — `_node` drops
        # `None` fields, so a compile unit with no subdirectories emits the
        # exact pre-RFC-0033 Entity node (byte-identical `to_document()`).
        mod.add(_node("Entity", ent["id"], name=ent["name"], fields=ent["fields"],
                      namespace=ent["decl"].namespace, line=ent["decl"].lineno))

    # issue #118, D1: workflow ids known before any workflow is lowered — the
    # names are already in `by_kind["workflow"]` from parsing, and `consume
    # by <Workflow>` needs to validate against them right here, in the same
    # pass that builds each Event node (lowering a workflow body is a
    # separate, later concern).
    declared_workflow_ids = {derive_id(w.name, "Workflow") for w in by_kind["workflow"]}

    declared_event_ids = set()
    # eid -> (entity id, create|update|delete) for `on`-sourced events only —
    # issue #98's mismatch/orphaned checks apply to this coupling and nowhere
    # else (a schedule-sourced or bare `event X` has no step to check against).
    event_sources = {}
    # eid -> consume workflow id, issue #118 D3's cycle check reads this once
    # every workflow (and its own `emit`s) has been lowered, below.
    event_consumes = {}
    for d in by_kind["event"]:
        eid = derive_id(d.name, "Event")
        declared_event_ids.add(eid)
        source = None
        if "on" in d.extra:
            ent_name, trigger = d.extra["on"]
            ref = derive_id(ent_name, "Entity")
            if mod.get(ref) is None:
                raise LowerError("line %d: event source references undeclared entity %r "
                                 "(dangling reference — RFC-0001 structure rule 6)"
                                 % (d.lineno, ent_name))
            source = {"ref": ref, "on": trigger}
            event_sources[eid] = (ref, trigger)
        elif "schedule" in d.extra:
            source = _schedule_source(d.extra["schedule"], d.lineno)
            # RFC-0016: the declaration reaches the IR and the OpenAPI schedule
            # metadata and stops there. Saying so is what separates it from
            # `performance batch`, which parses into silence (t3 F-2).
            _declaration_diagnostics(mod.diagnostics, "event",
                                     [("schedule", d.lineno)], where=eid)
        subscribe, consume_decl = _parse_event_body(d)
        consume = None
        if consume_decl is not None:
            consume_name, consume_lineno = consume_decl
            consume = derive_id(consume_name, "Workflow")
            if consume not in declared_workflow_ids:
                raise LowerError(
                    "line %d: event %s declares `consume by %s`, which is not "
                    "a declared workflow (declared: %s)"
                    % (consume_lineno, d.name, consume_name,
                       ", ".join(sorted(declared_workflow_ids))
                       if declared_workflow_ids else "none declared"))
            event_consumes[eid] = consume
        mod.add(_node("Event", eid, name=d.name, source=source,
                      subscribe=subscribe or None, consume=consume,
                      line=d.lineno))

    # ---- Workflows: step nodes, guards, blocks + derived Effects (R1) ----
    # wid -> set of event ids this workflow's own `emit`/`publish` steps
    # reference — issue #118 D3's cycle check needs every workflow's emitted
    # events in hand, so it runs once after this loop, not per-workflow.
    emits_by_workflow = {}
    for d in by_kind["workflow"]:
        wid = derive_id(d.name, "Workflow")
        ctx = _WfContext(wid, registry, mod.diagnostics, http_caps, base_of,
                         namespace=d.namespace)
        top_ids = [ctx.plan(item) for item in d.items]
        mod.add(_node("Workflow", wid, name=d.name, children=top_ids or None,
                      line=d.lineno))
        for node in ctx.emitted:
            mod.add(node)
        emits_by_workflow[wid] = {node["event"] for node in ctx.emitted
                                  if node["kind"] == "EventEmit"}
        _check_scoped_conditions(ctx.emitted, registry, d.name, base_of,
                                 top_ids, diagnostics=mod.diagnostics)
        _check_event_refs(ctx.emitted, declared_event_ids, d.name)
        _check_guard_scope(ctx.emitted, top_ids, ctx.step_lines, registry,
                           mod.diagnostics, d.name)
        _check_parallel_write_conflict(ctx.emitted, registry, d.name)
        _check_event_source_mismatch(ctx.emitted, top_ids, event_sources,
                                     d.name, mod.diagnostics)
        _check_derived_never_assigned(ctx.emitted, registry, d.name,
                                      mod.diagnostics)
        # #112: `owner_of` (RFC-0002 A.2 R2) names the owning service, if
        # any; `rollback_services` (built above, service loop runs first)
        # says whether that service declared `policy rollback`.
        owner = owner_of.get(id(d))
        has_rollback = owner is not None and id(owner) in rollback_services
        _check_rollback_escapes_network(ctx.emitted, d.name, has_rollback,
                                        mod.diagnostics, verbs=ctx.network_verbs)
        _check_note_cap(ctx.emitted, d.name, mod.diagnostics)

    _check_event_consume_cycles(event_consumes, emits_by_workflow, mod.diagnostics)

    for n in constraint_nodes:
        mod.add(n)

    for d in by_kind["capability"]:
        # Reuses the parse done above building `http_caps` — never re-parsed
        # here, so a diagnostic it raises (e.g. `retry-on-non-idempotent`)
        # fires exactly once per declaration.
        http_fields = http_caps.get(d.name, {})
        mod.add(_node("Capability", derive_id(d.name, "Capability"),
                      name=d.name, version=d.extra.get("version"),
                      line=d.lineno, **http_fields))

    return mod


class _WfContext:
    """Turns one workflow body into nodes, numbering ids as it goes."""

    def __init__(self, wid, registry, diagnostics, http_caps=None, base_of=None,
                namespace=None):
        self.wid = wid
        self.registry = registry
        self.diagnostics = diagnostics
        # RFC-0033 §Reference-level "짧은 이름 해소": the declaring workflow's
        # own namespace (`None` for a compile unit with no subdirectories —
        # every call before RFC-0033), so `_resolve_entity`/`_derive_assignment`/
        # `_derive_respond` can prefer an entity in this same namespace, and
        # `internal/` visibility can tell "same namespace" from "other".
        self.namespace = namespace
        # issue #116: `list <Entity> where ...`'s left-side field validation
        # needs the declared-type -> base map to apply the same Integer/
        # DateTime (order comparisons) and any-type (equality) rules
        # `_parse_expose_line`/guards already apply — computed once at
        # document scope (module-level, before any workflow is lowered) and
        # threaded down here rather than re-derived per step.
        self.base_of = base_of or {}
        # name -> {"method", "auth", "retry", "breaker", "path"} for every
        # declared `capability http` (issues #101, #109). `_derive_effect`'s
        # NetworkCall branch reads both membership (a target naming no entry
        # gets `declared-not-bound`) and `path`, to check a `with <ref>...`
        # clause's argument count against the template's `{}` count.
        self.http_caps = http_caps or {}
        self.emitted = []
        self._step_n = 0
        self._guard_n = 0
        self._block_n = {"parallel": 0, "pipeline": 0}
        # step id -> source line. Nodes carry their own optional `line` field
        # since RFC-0024, but `_check_guard_scope` (RFC-0023) runs after every
        # step in the workflow has already been emitted and needs the orphan
        # step's line rather than the node it is about — recording the pairing
        # here as it is made is simpler than re-deriving it from `self.emitted`.
        self.step_lines = {}
        # issue #125: `NetworkCall` nodes carry no `verb` field (`call` and
        # `request` both lower to the same node, `VERB_LEXICON`), so the two
        # diagnostics that quote a `NetworkCall` step's verb need it recorded
        # somewhere that isn't the IR — this side map, not serialized, keyed
        # by the Effect node's `eid` (not `step_id`; `ctx.emitted` holds the
        # derived Effect nodes, whose `id` is `eid`).
        self.network_verbs = {}

    def plan(self, item):
        """Emit the nodes for one body item; returns the id the parent should own."""
        if item["item"] == "step":
            return self._step(item["line"])
        if item["item"] == "block":
            return self._block(item["block"])
        if item["item"] == "guard":
            return self._guard(item["guard"], item["guarded"])
        raise LowerError("unknown body item %r" % item["item"])

    def _next_step_id(self):
        self._step_n += 1
        return "%s.step.%d" % (self.wid, self._step_n)

    def _registry_with_create_bindings(self):
        """`set`/`format`/`respond` resolve `<binding>.<field>` through
        `_derive_assignment`/`_derive_format`/`_derive_respond`'s own
        `registry`-keyed lookup, immediately — before `_check_scoped_conditions`
        ever runs. issue #97 / RFC-0012 Updates: a `create <Entity> as <name>`
        binding needs to satisfy that SAME lookup, with zero change to those
        three functions — `repo_policy.binding_name` is idempotent on an
        already-camelCase string (`name[:1].lower() + name[1:]`), so a
        synthetic entry whose `name` IS the `as` name resolves through the
        exact loop those functions already run (`for ent in registry.values():
        if binding_name(ent) == binding`), keeping its real `id`/`fields` so
        the derived node still names the real entity.

        Scoped to `self` (per-workflow, rebuilt from `self.emitted` so far) —
        unlike `self.registry` (document-global), two workflows reusing the
        same `as` name for different entities never collide.
        """
        extra = {}
        for node in self.emitted:
            if (node["kind"] == "RepositoryCall"
                    and node.get("operation") == "create" and node.get("result")):
                entity = self.registry[node["entity"]]
                extra["__create_as__.%s" % node["result"]] = dict(
                    entity, name=node["result"])
        if not extra:
            return self.registry
        merged = dict(self.registry)
        merged.update(extra)
        return merged

    def _step(self, line):
        step_id = self._next_step_id()
        self.step_lines[step_id] = line.lineno
        verb = line.tokens[0]
        obj = line.tokens[1] if len(line.tokens) > 1 else None
        if verb == ASSIGN_VERB:
            derived = _derive_assignment(
                step_id, line, self._registry_with_create_bindings(),
                namespace=self.namespace)
        elif verb == FORMAT_VERB:
            derived = _derive_format(
                step_id, line, self._registry_with_create_bindings())
        elif verb == RESPOND_VERB:
            derived = _derive_respond(
                step_id, line, self._registry_with_create_bindings(),
                namespace=self.namespace)
        elif verb == NOTE_VERB:
            derived = _derive_note(step_id, line)
        else:
            derived = _derive_effect(step_id, verb, obj, self.registry,
                                     line.lineno, line.tokens[2:],
                                     diagnostics=self.diagnostics,
                                     step_text=" ".join(line.tokens),
                                     http_caps=self.http_caps,
                                     verb_sink=self.network_verbs,
                                     base_of=self.base_of,
                                     namespace=self.namespace)
        if derived is None:
            # R1 derived nothing, which is correct. Saying nothing about it is
            # what issue #36 reports, so the fact leaves as a diagnostic while
            # the emitted node stays exactly as before.
            #
            # RFC-0026: `line=` gives an agent a jump target without regexing
            # `where`. The suggestion is two-tier — VERB_ALIASES first (the
            # semantic near-synonym case, e.g. `persist`->`create`), then
            # difflib for a spelling typo (`craete`->`create`, cutoff 0.6 — a
            # wrong suggestion is worse than none) — offered both in the
            # message and as a structured `suggestion` so a caller can act on
            # it without parsing prose.
            suggestion = VERB_ALIASES.get(verb)
            if suggestion is None:
                close = difflib.get_close_matches(verb, VERB_LEXICON, n=1,
                                                   cutoff=0.6)
                suggestion = close[0] if close else None
            suffix = " — did you mean '%s'?" % suggestion if suggestion else ""
            self.diagnostics.add(
                code="unknown-verb",
                where="line %d" % line.lineno, subject=verb, line=line.lineno,
                suggestion=suggestion,
                message="`%s` is outside VERB_LEXICON: this step derives no "
                        "Effect and runs as a descriptive no-op%s"
                        % (" ".join(line.tokens), suffix))
        self.emitted.append(_node("WorkflowStep", step_id,
                                  name=" ".join(line.tokens),
                                  children=[derived["id"]] if derived else None,
                                  line=line.lineno))
        if derived:
            self.emitted.append(derived)
        return step_id

    def _block(self, block):
        kind = "Concurrency" if block["type"] == "parallel" else "Pipeline"
        self._block_n[block["type"]] += 1
        slug = "%s.%d" % (block["type"], self._block_n[block["type"]])
        node_id = "%s.%s" % (self.wid, slug)
        child_ids = [self._step(line) for line in block["steps"]]
        if not child_ids:
            raise LowerError("line %d: `%s` block has no steps"
                             % (block["lineno"], block["type"]))
        if kind == "Concurrency":
            self.emitted.append(_node(kind, node_id, mode="parallel",
                                      children=child_ids, line=block["lineno"]))
        else:
            # RFC-0001 requires Pipeline.name; the grammar makes the name optional,
            # so an unnamed pipeline gets a derived one (formerly gap A.4-4).
            name = block["name"] or slug
            self.emitted.append(_node(kind, node_id, name=name, children=child_ids,
                                      line=block["lineno"]))
        return node_id

    def _guard(self, guard, guarded):
        self._guard_n += 1
        node_id = "%s.guard.%d" % (self.wid, self._guard_n)
        inner_id = self.plan(guarded)
        fields = {"mode": guard["mode"]}
        if guard["mode"] == "repeat":
            fields["count"] = int(guard["arg"])
        else:
            fields["condition"] = guard["arg"]
        # RFC-0028 §Reference-level Specification/3: additive, `when`-only.
        # `parser.py` only ever populates this for `mode == "when"`.
        if guard.get("alternatives"):
            fields["alternatives"] = list(guard["alternatives"])
        self.emitted.append(_node("Guard", node_id, children=[inner_id],
                                  line=guard["lineno"], **fields))
        return node_id


STEP_SUBJECT = "step"

# What a guarded state change is called when it escapes its guard. Lives beside
# GUARD_SUBJECT for the same reason that one does: the wording travels with the
# diagnostic instead of being spelled again at each site.
ORPHAN_HINT = ("Repeat the guard line before this step, or wrap both in a "
               "`parallel` block.")


def _touched_entities(step_node, by_id):
    """Entity ids this WorkflowStep reads or writes, from its derived Effects.

    Read off the Effect nodes rather than off the step's words: the Effect is
    what execution acts on, and it is the production derivation both modes
    already agree about. A `CacheAccess` carries a key rather than an entity, so
    it contributes nothing here — the consequence this check is about is a
    change to *stored* state.
    """
    found = set()
    for child_id in step_node.get("children") or []:
        child = by_id.get(child_id)
        if child is None:
            continue
        if child["kind"] in ("RepositoryCall", "Assignment"):
            if child.get("entity"):
                found.add(child["entity"])
        elif child["kind"] == "Validation":
            if child.get("target"):
                found.add(child["target"])
    return found


# The write family D5 cares about — a step here changes a stored row, so two
# of them racing inside one `parallel` block (no order to resolve who wins)
# is the non-determinism the check refuses. `list`/`read`/`find`/etc. are
# absent on purpose: two readers, or a reader beside a writer, touch nothing
# that depends on which one ran first.
WRITE_OPS = ("create", "update", "delete")


def _written_entity(step_node, by_id):
    """The entity id this WorkflowStep writes, or `None` if it writes none.

    Narrower than `_touched_entities`: only the write family matters here
    (`_touched_entities`'s own docstring already draws this line for reads).
    """
    for child_id in step_node.get("children") or []:
        child = by_id.get(child_id)
        if child is None:
            continue
        if child["kind"] == "RepositoryCall" and child.get("operation") in WRITE_OPS:
            return child.get("entity")
    return None


def _check_parallel_write_conflict(emitted, registry, workflow_name):
    """issue #108 D5: two steps writing the same entity inside one `parallel`
    block is a compile error, not a diagnostic.

    RFC-0012's execution-scope binding is order-dependent (a later step reads
    what an earlier one bound), and a `parallel` block runs its steps
    concurrently — there is no "earlier". Two writers racing on the same
    entity would make the row that survives non-deterministic between runs,
    which is a correctness bug neither step shows on its own (each parses and
    lowers fine alone). `LowerError`, not a diagnostic: non-determinism is not
    something a caller can accept and route around the way `unenforced` is.

    Concurrency blocks cannot nest and cannot be guarded (RFC-0002's
    `parallel` grammar), so a flat scan of each block's direct children is
    exhaustive — no recursion into nested blocks is possible.
    """
    by_id = {node["id"]: node for node in emitted}
    for node in emitted:
        if node["kind"] != "Concurrency":
            continue
        writers = {}
        for child_id in node.get("children") or []:
            step = by_id.get(child_id)
            if step is None or step["kind"] != "WorkflowStep":
                continue
            entity = _written_entity(step, by_id)
            if entity is None:
                continue
            writers.setdefault(entity, []).append(step)
        for entity_id, steps in writers.items():
            if len(steps) < 2:
                continue
            lines = sorted(s.get("line") for s in steps if s.get("line") is not None)
            entity_name = registry.get(entity_id, {}).get("name", entity_id)
            raise LowerError(
                "workflow %s: `parallel` block has %d steps writing %s at "
                "lines %s — same-entity writes inside one `parallel` block "
                "are non-deterministic (RFC-0012 binding is order-dependent, "
                "and a `parallel` block has no order); split them across "
                "separate steps or serialize them outside the block"
                % (workflow_name, len(steps), entity_name,
                   ", ".join(str(line) for line in lines)))


def _steps_outside_guards(node_id, by_id):
    """WorkflowSteps reachable from `node_id` that no Guard owns.

    A Guard subtree is skipped whole: whatever is under a guard is already
    conditional, and whether *that* guard is the right one is a different
    question from the one this check asks.
    """
    node = by_id.get(node_id)
    if node is None:
        return []
    if node["kind"] == "Guard":
        return []
    if node["kind"] == "WorkflowStep":
        return [node]
    out = []
    for child_id in node.get("children") or []:
        out.extend(_steps_outside_guards(child_id, by_id))
    return out


def _check_guard_scope(emitted, top_ids, step_lines, registry, diagnostics,
                       workflow_name):
    """A guard owns the next item only — say so when that silently matters.

    RFC-0002 gives `when` exactly one item, and `references/grammar.md` documents
    it. But the grammar is not where an author is standing when they write

        when product.stock >= input.quantity
        create order
        set product.stock to product.stock - input.quantity

    which compiles with no diagnostic at all and then decrements stock on a run
    where the guard was false. Only the *runtime* said anything, through
    `guard-skipped-steps`, and only about the one step the guard did own.

    The judgement is a consequence, not a shape. "A step follows a guard" is
    ordinary and correct — every workflow does it. What is worth a warning is a
    step that touches the very state the guard was protecting, from outside the
    guard. So the condition's own references decide the entity set, and only a
    later unguarded step that reads or writes one of those entities is reported.
    Shape alone would fire on `examples/guarded.lnpl`, where two guards sit in a
    row over different concerns, and a check that must be exempted per example
    measures nothing (issue #35 taught this repo that lesson once already).
    """
    from .condition import ConditionError, parse_condition, references
    from .repo_policy import binding_name

    by_id = {node["id"]: node for node in emitted}
    entity_of_binding = {binding_name(ent): ent["id"]
                         for ent in registry.values()}
    ordered = list(top_ids or [])

    for i, nid in enumerate(ordered):
        guard = by_id.get(nid)
        if guard is None or guard["kind"] != "Guard":
            continue
        text = guard.get("condition")
        if not text:
            continue                      # `repeat` carries a count
        try:
            cond = parse_condition(text)
        except ConditionError:
            continue                      # already refused elsewhere
        if cond is None:
            continue

        protected = set()
        for name in references(cond):
            binding = name.split(".")[0]
            eid = entity_of_binding.get(binding)
            if eid:
                protected.add(eid)
        if not protected:
            continue                      # e.g. `input.` only — no row to protect

        for later_id in ordered[i + 1:]:
            for step in _steps_outside_guards(later_id, by_id):
                if not (_touched_entities(step, by_id) & protected):
                    continue
                where = step_lines.get(step["id"])
                diagnostics.add(
                    code="guard-orphaned-steps",
                    where=("line %d" % where) if where else workflow_name,
                    subject=step["name"], line=where,
                    message="`%s %s` owns only the next item, so `%s` runs "
                            "whether or not that condition held. %s"
                            % (guard.get("mode", "when"), text, step["name"],
                               ORPHAN_HINT))


def _check_event_refs(emitted, declared_event_ids, workflow_name):
    """Refuse an `emit`/`publish` whose event is not declared in this module.

    Same dangling-reference rule the event *source* already obeys (RFC-0001
    structure rule 6), applied to the reference direction. The interpreter also
    refuses an unknown event id at run time, and that check stays: it defends
    hand-assembled IR. But a reference that cannot resolve is decidable from the
    document, so it is decided here — otherwise a guard that skips the step
    hides the defect behind rc=0 (issue #45, t4 F-2).

    The declared ids are listed in the message: the compiler knows them, and a
    caller who mistyped an event name needs the candidates to fix it.
    """
    for node in emitted:
        if node["kind"] != "EventEmit":
            continue
        ref = node.get("event")
        if ref in declared_event_ids:
            continue
        raise LowerError(
            "workflow %s: `emit`/`publish` references %r, which is not a declared "
            "event (declared: %s)"
            % (workflow_name, ref,
               ", ".join(sorted(declared_event_ids)) if declared_event_ids
               else "none declared"))


def _check_event_consume_cycles(event_consumes, emits_by_workflow, diagnostics):
    """Issue #118, D3: warn (never error) when `consume by` and `emit` chain
    back to an event already in the chain — event -> its consuming workflow
    -> that workflow's own emitted events -> ... -> the same event again.

    A *static* signal for a possible infinite runtime dispatch loop, not
    proof of one: a guard inside the consuming workflow may keep the loop
    from ever actually firing, so the program is not necessarily wrong (the
    same reasoning `guard-orphaned-steps` already applies to a different
    shape of "this looks off but might be fine"). That is why this is a
    diagnostic, not a `LowerError` — unlike `consume by`'s undeclared-target
    case above, which the author cannot mean.

    The graph is bipartite (event id, workflow id) with two edge kinds —
    `event -> workflow` from `consume`, `workflow -> event` from `emit` —
    walked by one standard white/gray/black cycle-detecting DFS. Iterative,
    with an explicit frame stack rather than Python's call stack: a module
    with hundreds of chained `consume by`/`emit` declarations must not blow
    the interpreter's recursion limit lowering it.
    """
    graph = {}
    for eid, wid in event_consumes.items():
        graph.setdefault(eid, set()).add(wid)
    for wid, emitted_events in emits_by_workflow.items():
        for eid in emitted_events:
            graph.setdefault(wid, set()).add(eid)

    reported = set()

    def report(path_stack, closing_node):
        cycle = path_stack[path_stack.index(closing_node):] + [closing_node]
        key = frozenset(cycle[:-1])
        if key in reported:
            return
        reported.add(key)
        # Canonical rendering: rotate to the smallest id, so the same cycle
        # reads identically no matter which node the DFS started from.
        start = cycle.index(min(cycle[:-1]))
        rotated = cycle[start:-1] + cycle[:start] + [cycle[start]]
        path = " -> ".join(rotated)
        diagnostics.add(
            code="event-consume-cycle",
            where=rotated[0],
            subject="cycle %s" % path,
            message="`consume by`/`emit` forms a cycle: %s — if this path "
                    "ever runs unguarded, dispatching the event re-triggers "
                    "the same workflow forever"
                    % path)

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {}
    for root in graph:
        if color.get(root, WHITE) != WHITE:
            continue
        color[root] = GRAY
        path_stack = [root]
        # Each frame: [node, its neighbors (sorted for a deterministic
        # message), the index of the next neighbor still to visit].
        frames = [[root, sorted(graph.get(root, ())), 0]]
        while frames:
            node, neighbors, i = frames[-1]
            if i >= len(neighbors):
                color[node] = BLACK
                frames.pop()
                path_stack.pop()
                continue
            frames[-1][2] += 1
            nxt = neighbors[i]
            nxt_color = color.get(nxt, WHITE)
            if nxt_color == GRAY:
                report(path_stack, nxt)
            elif nxt_color == WHITE and nxt in graph:
                color[nxt] = GRAY
                path_stack.append(nxt)
                frames.append([nxt, sorted(graph.get(nxt, ())), 0])


def _guard_owner_map(top_ids, by_id):
    """node id -> the `Guard` node that owns it, or `None` at the top level.

    Same tree RFC-0023's `_steps_outside_guards` already walks (top-level
    order, a `Guard`'s single child, a block's several), generalised to record
    *which* guard owns a node instead of filtering guarded ones out. Every
    node reachable from `top_ids` gets an entry, including a `WorkflowStep`'s
    own Effect children — an `EventEmit`/`RepositoryCall` id needs the same
    owner its parent step has.
    """
    owner = {}

    def walk(node_id, guard):
        node = by_id.get(node_id)
        if node is None:
            return
        owner[node_id] = guard
        if node["kind"] == "Guard":
            children = node.get("children") or []
            if children:
                walk(children[0], node)
            return
        for child_id in node.get("children") or []:
            walk(child_id, guard)

    for nid in top_ids or []:
        walk(nid, None)
    return owner


def _guard_key(guard):
    """A guard's protection identity for scope comparison (issue #98).

    Two *physically distinct* `Guard` nodes with the same mode+condition (the
    "repeat the guard line" remedy) count as the same scope — node identity
    would wrongly flag that remedy as still broken. `None` (top level, no
    guard) is its own key: unconditional steps always run together.
    """
    if guard is None:
        return None
    if guard.get("mode") == "repeat":
        return ("repeat", guard.get("count"))
    return (guard.get("mode"), guard.get("condition"))


def _check_event_source_mismatch(emitted, top_ids, event_sources, workflow_name,
                                 diagnostics):
    """`event-source-mismatch` (warning) / `event-source-orphaned` (info) — #98.

    `event <E> on <Entity> <op>` claims E is the event for `<op> <entity>`, but
    nothing checked `emit E` against that claim. A guard that skips `create
    order` still lets an unguarded `emit orderPlaced` beside it fire — the
    declaration becomes a lie at runtime with no compile-time signal.

    For each `on`-sourced event this workflow `emit`s:
      * no `<op> <entity>` `RepositoryCall` runs here at all -> the source is
        descriptive only for this workflow -> `event-source-orphaned` (info,
        same grading logic as `declared-not-enforced`: no local edit removes
        it short of restructuring the workflow or dropping the source/emit);
      * one runs, but none share the emit's guard scope (`_guard_key`) ->
        `event-source-mismatch` (warning: moving the emit under that scope, or
        that scope's condition under the emit, removes it — `ORPHAN_HINT`
        names both remedies, same wording RFC-0023 already uses);
      * one runs and shares the emit's guard scope -> silent.

    A schedule-sourced or source-less event (`event X` alone) never appears in
    `event_sources`, so its `emit` is untouched (issue #98 §3).
    """
    by_id = {node["id"]: node for node in emitted}
    owner = _guard_owner_map(top_ids, by_id)

    for step in emitted:
        if step["kind"] != "EventEmit":
            continue
        eid = step.get("event")
        source = event_sources.get(eid)
        if source is None:
            continue
        entity_ref, op = source
        op_steps = [n for n in emitted
                    if n["kind"] == "RepositoryCall"
                    and n.get("entity") == entity_ref
                    and n.get("operation") == op]
        where = step.get("line")
        where_str = ("line %d" % where) if where else workflow_name
        if not op_steps:
            diagnostics.add(
                code="event-source-orphaned",
                where=where_str, subject=eid, line=where,
                message="`emit %s` fires, but workflow %s never runs `%s` on "
                        "the entity its `on` source declares — the source "
                        "declaration is descriptive only here"
                        % (eid, workflow_name, op))
            continue
        emit_scope = _guard_key(owner.get(step["id"]))
        if any(_guard_key(owner.get(rs["id"])) == emit_scope for rs in op_steps):
            continue
        diagnostics.add(
            code="event-source-mismatch",
            where=where_str, subject=eid, line=where,
            message="`emit %s` is not in the same guard scope as the `%s` "
                    "step its `on` source declares, so it can fire whether "
                    "or not that step ran. %s" % (eid, op, ORPHAN_HINT))


def _check_derived_never_assigned(emitted, registry, workflow_name, diagnostics):
    """`derived-never-assigned` (warning) — issue #95.

    A `derived` field is server-computed, so a `create` step for an entity
    that declares one is a lie unless something in this workflow actually
    fills it. `set`/`format` both lower to an `Assignment` node carrying
    `entity`/`target` (D5: no new verb), so checking for one is the same
    "did the document say what it claims" scan `_check_event_source_mismatch`
    already runs for `emit` — this is that check's field-level twin.

    Deliberately workflow-scoped and order-blind: the field only needs to be
    assigned *somewhere* in the workflow that creates it, not before the
    `create` step specifically — RFC-0015 already refuses `set` on a row this
    workflow never read, which is a stronger, separate guarantee than this
    diagnostic is trying to add.
    """
    assigned = {(node["entity"], node["target"].rsplit(".", 1)[-1])
               for node in emitted if node["kind"] == "Assignment"}
    for step in emitted:
        if step["kind"] != "RepositoryCall" or step.get("operation") != "create":
            continue
        entity = registry.get(step["entity"])
        if entity is None:
            continue
        where = step.get("line")
        where_str = ("line %d" % where) if where else workflow_name
        for field in entity["fields"]:
            if not field.get("derived"):
                continue
            if (entity["id"], field["name"]) in assigned:
                continue
            diagnostics.add(
                code="derived-never-assigned",
                where=where_str, subject="%s.%s" % (entity["id"], field["name"]),
                line=where,
                message="`create %s` never assigns %s's derived field %r — "
                        "add a `set`/`format` step that fills it somewhere in "
                        "this workflow" % (entity["name"], entity["name"],
                                          field["name"]))


def _check_note_cap(emitted, workflow_name, diagnostics):
    """`note-cap-exceeded` (warning) — issue #111, D3.

    More than `NOTE_CAP` `note`s in one workflow is drift toward free-form
    logging, the exact thing the closed verb table exists to prevent (issue
    #111's "no arbitrary output stream" guarantee). Trimming notes makes this
    go away, so it grades `warning` by the same "does editing the program
    remove it" test every other code's grade already answers (#52) — the
    workflow still compiles and runs.
    """
    count = sum(1 for node in emitted if node["kind"] == "Annotation")
    if count <= NOTE_CAP:
        return
    diagnostics.add(
        code="note-cap-exceeded",
        where=workflow_name, subject=workflow_name,
        message="workflow %r has %d `note` annotations, over the %d-per-"
                "workflow cap — trim to the notes that earn their place"
                % (workflow_name, count, NOTE_CAP))


def _check_rollback_escapes_network(emitted, workflow_name, has_rollback, diagnostics,
                                    verbs=None):
    """`rollback-escapes-network` (warning) — issue #112.

    RFC-0032 opens one transaction per `run_workflow` execution and rolls it
    back on failure, but that only undoes the writes (and outbox
    registrations) the transaction actually owns — a `NetworkCall` step is
    outside it. A workflow whose service declares `policy rollback` reads as
    "this undoes itself on failure," and a `call`/`request` step in it makes
    that a lie: the call already happened by the time anything rolls back,
    and nothing undoes it.

    `has_rollback` is decided once by the caller from `owner_of` (RFC-0002
    A.2 R2) before this runs, so a workflow with no owning service is never
    checked here — with no `policy` block there is no "rollback" claim to
    contradict. One diagnostic per `NetworkCall` step (not one per
    workflow): each is a separate step an author has to either move or wrap,
    so collapsing them into one line would hide the rest.

    `verbs` (issue #125) is `_WfContext.network_verbs`, keyed by the
    `NetworkCall` node's own `id` (an Effect node's `eid`, which is what
    `step["id"]` is here — `emitted` holds derived Effect nodes, not
    `WorkflowStep` wrappers) — it lets this diagnostic quote the author's
    `call`/`request` verb instead of assuming `call`.
    """
    if not has_rollback:
        return
    verbs = verbs or {}
    for step in emitted:
        if step["kind"] != "NetworkCall":
            continue
        line = step.get("line")
        where_str = ("line %d" % line) if line else workflow_name
        verb = verbs.get(step["id"], "call")
        subject = "%s %s" % (verb, step.get("target", "unspecified"))
        diagnostics.add(
            code="rollback-escapes-network",
            where=where_str, subject=subject, line=line,
            message="workflow %s declares 'policy rollback', but step "
                    "`%s` leaves the transaction boundary — a rollback "
                    "cannot undo it" % (workflow_name, subject))


def _check_scoped_conditions(emitted, registry, workflow_name, base_of=None,
                             top_ids=None, diagnostics=None):
    """Refuse a guard reference that can never resolve, or can never be compared.

    Five judgements, all decidable from the document alone (RFC-0012 §G12.5,
    RFC-0015 §Static rejections, RFC-0025 §3):

      * a qualified reference names a bound row, and a binding exists only where
        this workflow READS that entity — `list`/`query` does not bind a row,
        only a RowSet (RFC-0025 §5/§6.2), so it does not count here;
      * `input.<field>` names the run's payload, whose shape is the union of every
        declared entity's fields — a name outside that union is a typo, not a
        field;
      * an operand whose declared type is not Integer cannot be compared at all,
        so the refusal belongs here rather than in a runtime `TypeError` (t2 F-4
        reported exactly that traceback escaping to the operator);
      * a comparison of two literals decides nothing, so it is an authoring
        mistake rather than a guard;
      * an `Aggregate` (`sum`/`count`) names a declared entity, agrees in shape
        with its function, and (for `sum`) sums an Integer field (RFC-0025 §3) —
        and, separately, a `warning` (not a rejection) when no earlier unguarded
        `list` of that entity precedes it (RFC-0025 §4).

    A bare reference stays unchecked: the payload is not part of the document,
    and `when token missing` asks about the request rather than about a row. That
    is also why `input.` is the spelling worth preferring — it is checked.
    """
    from .condition import (Aggregate, ConditionError, FormatCall, Lit,
                            parse_condition,
                            parse_value_or_aggregate, references)
    from .repo_policy import binding_name

    by_binding = {binding_name(ent): ent for ent in registry.values()}
    # RFC-0025 §6.1/§6.2: `list`/`query` no longer binds a single row, so only
    # `read` puts an entity in the SINGLE-ROW scope — narrowed from the old
    # `operation in READ_OPS` (which also matched `query`, a branch no verb
    # ever reached before RFC-0025 gave `list` that operation).
    read_entities = {node["entity"] for node in emitted
                     if node["kind"] == "RepositoryCall"
                     and node.get("operation") == "read"}
    declared_fields = {f["name"]: f for ent in registry.values()
                       for f in ent["fields"]}
    # RFC-0027 §2/§4: a `call/request ... as <name>` binding has no backing
    # Entity, so it cannot be checked against a declared field list — a
    # response body's shape is only known at run time. `check_reference`
    # treats a qualified reference into this set the way it already treats a
    # bare payload reference: unchecked here, resolved (or absent) at runtime
    # (RFC-0012 §G12.4).
    network_bindings = {node["result"] for node in emitted
                        if node["kind"] == "NetworkCall" and node.get("result")}
    # issue #97 / RFC-0012 Updates: `create <Entity> as <name>` binds the
    # created row's own Entity shape under `<name>` — a separate namespace
    # from `by_binding` (the entity's default binding name), since the two
    # are guaranteed disjoint by the collision check `_derive_effect` runs
    # at emission time.
    create_bindings = {node["result"]: registry[node["entity"]]
                       for node in emitted
                       if node["kind"] == "RepositoryCall"
                       and node.get("operation") == "create"
                       and node.get("result")}
    scope = _Scope(workflow_name, by_binding, read_entities, declared_fields,
                   base_of or {}, network_bindings, create_bindings)
    by_id = {node["id"]: node for node in emitted}

    # Source order, not emission order: `_WfContext._guard` emits its guarded step
    # BEFORE the Guard that owns it, so a flat pass over `emitted` would see an
    # assignment as preceding the guard that in fact runs first. The
    # assigned-then-read judgement below is about the order an author wrote, so
    # the walk has to be the tree's.
    assigned = set()
    # RFC-0025 §4: entities a `list` has reached so far, OUTSIDE any guard — a
    # guard's own `list` does not count (its condition may be false), the same
    # exemption RFC-0023 §3 gives `_steps_outside_guards`. Populated only by
    # this walk, in program order, so an `Aggregate` sees exactly the `list`s
    # that precede it in the text.
    listed = set()

    def visit(ids, guarded=False):
        for nid in ids:
            node = by_id.get(nid)
            if node is None:
                continue
            kind = node["kind"]
            if kind == "Guard":
                _check_guard(node, scope, assigned, workflow_name,
                             parse_condition, references, ConditionError, Lit)
                visit(node.get("children") or [], guarded=True)
            elif kind == "WorkflowStep":
                for child_id in node.get("children") or []:
                    child = by_id.get(child_id)
                    if child is None:
                        continue
                    if child["kind"] == "RepositoryCall":
                        if child.get("operation") == "query":
                            if not guarded:
                                listed.add(child["entity"])
                            if child.get("predicate"):
                                _check_list_predicate(child, registry, scope,
                                                     workflow_name)
                        continue
                    if child["kind"] == "Response":
                        text = "respond %s" % " ".join(child["refs"])
                        _check_respond(child["refs"], scope, text, base_of or {})
                        continue
                    if child["kind"] != "Assignment":
                        continue
                    rhs = parse_value_or_aggregate(child["expression"])
                    if isinstance(rhs, FormatCall):
                        # issue #94: format's own type rule, not the numeric/
                        # instant one `check_reference` enforces below — a
                        # Text-family target and reference arguments of any
                        # type (Password excluded) are exactly what `set`'s
                        # rule would refuse.
                        text = "format %s from %r%s" % (
                            child["target"], rhs.template,
                            (" with " + " ".join(a.name for a in rhs.args))
                            if rhs.args else "")
                        _check_format(child["target"], rhs, scope, text,
                                     base_of or {})
                    else:
                        # The target and the expression's operands are
                        # references like any other, so the same judgements
                        # apply — including "is it an Integer".
                        text = "set %s to %s" % (child["target"], child["expression"])
                        scope.check_reference(child["target"], text,
                                              ASSIGN_SUBJECT, is_target=True)
                        if isinstance(rhs, Aggregate):
                            entity_id = _check_aggregate(rhs, by_binding, base_of or {},
                                                         workflow_name, text)
                            if entity_id not in listed and diagnostics is not None:
                                line = child.get("line")
                                diagnostics.add(
                                    code="aggregation-orphaned-list",
                                    where=("line %d" % line) if line else workflow_name,
                                    subject=text,
                                    message="`%s` reads a RowSet no earlier "
                                            "unguarded `list` fills in this "
                                            "workflow, so it is always empty and "
                                            "this always evaluates to 0"
                                            % text,
                                    line=line)
                        else:
                            for name in references(rhs):
                                scope.check_reference(name, text, ASSIGN_SUBJECT)
                            # The expression is a `Value` like any other, so
                            # `instant + instant` is as meaningless here as in a
                            # guard.
                            _value_dimension(rhs, scope, text, ASSIGN_SUBJECT)
                    assigned.add(child["target"])
            else:
                visit(node.get("children") or [], guarded=guarded)

    visit(top_ids or [])


def _check_list_predicate(node, registry, scope, workflow_name):
    """issue #116, D1/D2: a `list where` predicate's RIGHT side, judged the
    same way a guard condition's operands are — reusing `scope` rather than
    a second lookup, so "which binding names a declared entity, read by
    this workflow" is answered once, the same way, everywhere.

    The LEFT side (which field, which base type) was already validated at
    lowering time (`_parse_predicate_terms`, when the entity's own field
    list was in hand with no scope needed); this is the half that needs the
    workflow's binding state (`by_binding`/`read_entities`), so it runs here,
    in the same post-pass every other guard-shaped check already runs in.
    """
    from .condition import parse_value

    entity = registry[node["entity"]]
    fields_by_name = {f["name"]: f for f in entity["fields"]}
    for term in node["predicate"]:
        field = fields_by_name[term["field"]]
        left_base = scope.base_of.get(field["type"], field["type"])
        right_value = parse_value(term["value"])
        text = "list %s where %s %s %s" % (
            entity["name"], term["field"], term["op"], term["value"])
        if left_base in EXPOSE_SORT_BASES:
            # Integer/DateTime: the same scalar/instant dimension check a
            # guard's `_check_dimensions` applies, unchanged by this issue.
            left_dim = "instant" if left_base == "DateTime" else "scalar"
            right_dim = _value_dimension(right_value, scope, text)
            if right_dim is not None and right_dim != left_dim:
                raise LowerError(
                    "workflow %s: %r compares %s (%s) with %s (%s) — "
                    "RFC-0016 compares like with like"
                    % (workflow_name, text, term["field"], left_dim,
                       _describe(right_value), right_dim))
        else:
            # D2: any-type equality — `_parse_predicate_terms` already
            # refused a Lit/Arith here, so `right_value` is a `Ref`.
            # Reading the field it names (as opposed to plain dimension
            # checking) is the part that needs `scope`.
            right_field = scope.resolve_field(right_value.name, text,
                                             subject="list where")
            if right_field is not None:
                right_base = scope.base_of.get(right_field["type"],
                                              right_field["type"])
                if right_base != left_base:
                    raise LowerError(
                        "workflow %s: %r compares %s (%s) with %s (%s) — "
                        "equality needs the same declared type on both sides"
                        % (workflow_name, text, term["field"], left_base,
                           right_value.name, right_base))


def _check_aggregate(agg, by_binding, base_of, workflow_name, text):
    """RFC-0025 §3: static rejections for one `Aggregate` operand.

    Judged here rather than in `condition.py` because it needs the document —
    which entities are declared, which fields they have, which type each is —
    the same split RFC-0015's Integer-only check already draws (that module's
    own docstring: "this module never sees the document").

    Returns the entity id the aggregate reads, so the caller can also judge
    RFC-0025 §4 (was it `list`ed first) without re-resolving the binding.
    """
    binding = agg.ref.namespace or agg.ref.name
    entity = by_binding.get(binding)
    if entity is None:
        raise LowerError(
            "workflow %s: aggregate %r names %r, which is not a declared "
            "entity" % (workflow_name, text, binding))
    if agg.func == "count":
        if agg.ref.namespace is not None:
            raise LowerError(
                "workflow %s: aggregate %r — `count` takes an entity, not a "
                "field (write `count %s`, not `count %s`)"
                % (workflow_name, text, binding, agg.ref.name))
        return entity["id"]
    # agg.func == "sum"
    if agg.ref.namespace is None:
        raise LowerError(
            "workflow %s: aggregate %r — `sum` needs a field "
            "(`sum <entity>.<field>`), not a bare entity"
            % (workflow_name, text))
    field = agg.ref.field
    fields = {f["name"]: f for f in entity["fields"]}
    if field not in fields:
        raise LowerError(
            "workflow %s: aggregate %r names field %r, which entity %s does "
            "not declare" % (workflow_name, text, field, entity["name"]))
    declared = fields[field].get("type")
    base = base_of.get(declared, declared)
    if base != "Integer":
        raise LowerError(
            "workflow %s: aggregate %r sums %s.%s, whose declared type %s is "
            "not Integer — RFC-0025 sums whole numbers only (no evaluator for "
            "Money, Decimal, or the other composite types)"
            % (workflow_name, text, binding, field, declared))
    return entity["id"]


def _check_format(target, rhs, scope, text, base_of):
    """issue #94, D3(b)/(c): `format`'s own type rule.

    Neither side goes through `_dimension_of` (RFC-0016's Integer/DateTime
    check) — that rule is for arithmetic and comparison, and `format` does
    neither. Its target must be Text-family (the one field type arithmetic
    and comparisons never accept, which is exactly why the language had no
    way to write one before this verb); its arguments may be any type
    EXCEPT Password — the masking chokepoint (issue #43) that this verb
    would otherwise let an author route around by assembling a masked
    field's value into an unmasked one.
    """
    target_field = scope.resolve_field(target, text, ASSIGN_SUBJECT, is_target=True)
    if target_field is None:
        raise LowerError(
            "workflow %s: format target %r must name a bound row's field "
            "(`<binding>.<field>`), not a bare or input reference"
            % (scope.workflow_name, text))
    declared = target_field.get("type")
    base = base_of.get(declared, declared)
    if base != "Text":
        raise LowerError(
            "workflow %s: format target %r has declared type %s, whose base "
            "is %s — format writes only to a Text-family field (RFC-0016 "
            "gives Text no numeric/instant dimension, so no other verb could "
            "ever write one; format is the one verb that assembles strings)"
            % (scope.workflow_name, text, declared, base))
    for ref in rhs.args:
        arg_field = scope.resolve_field(ref.name, text, ASSIGN_SUBJECT)
        if arg_field is None:
            continue                      # bare/network reference — unchecked
        arg_declared = arg_field.get("type")
        arg_base = base_of.get(arg_declared, arg_declared)
        if arg_base == "Password":
            raise LowerError(
                "workflow %s: format argument %r has declared type %s, "
                "whose base is Password — format must not assemble a "
                "Password field into a string (issue #43's masking "
                "chokepoint: a masked field's value must never leave "
                "through an unmasked one)"
                % (scope.workflow_name, ref.name, arg_declared))


def _check_respond(refs, scope, text, base_of):
    """issue #96, D3: `respond`'s own reference rule.

    Reuses `_Scope.resolve_field` (issue #45's existing Reference check) for
    "does this reference name a bound row's declared field, and was that
    entity actually read" — no new lookup invented. `resolve_field` returning
    None means a bare or network-result reference, neither of which has a
    declared field type for the OpenAPI 200 schema to derive (D6), so that is
    refused here the same way `_check_format`'s target check refuses one.
    Then, the Password rule: `format`'s argument check forbids assembling a
    masked field into an unmasked one (issue #43's masking chokepoint);
    `respond` extends that same chokepoint to the response surface itself.
    """
    for ref in refs:
        field = scope.resolve_field(ref, text, RESPOND_SUBJECT)
        if field is None:
            raise LowerError(
                "workflow %s: respond reference %r must name a bound row's "
                "field (`<binding>.<field>`), not a bare or network-result "
                "reference — a response field needs a declared type"
                % (scope.workflow_name, ref))
        declared = field.get("type")
        base = base_of.get(declared, declared)
        if base == "Password":
            raise LowerError(
                "workflow %s: respond reference %r has declared type %s, "
                "whose base is Password — respond must not surface a "
                "Password field in the response (issue #43's masking "
                "chokepoint: a masked field's value must never leave "
                "through an unmasked one)"
                % (scope.workflow_name, ref, declared))


def _check_literal_zero_divisor(value, where):
    """RFC-0028 §Reference-level Specification/2: a literal `0` divisor always
    fails (the run could only ever end in `RunError`), so it is refused here
    rather than sent to a run that cannot do anything else. A REFERENCED
    divisor is a runtime value — that is §2's `RunError` row, decided at run
    time because the document alone cannot know it will be 0.

    `Arith.left`/`.right` are `Ref | Lit`, never `Arith` (RFC-0015: arithmetic
    does not nest), so this needs no recursion.
    """
    from .condition import Arith, Lit
    if isinstance(value, Arith) and value.op == '/' \
            and isinstance(value.right, Lit) and value.right.value == 0:
        raise LowerError(
            "%s: divides by the literal 0 — division by zero is not a "
            "runtime input here: the right operand is the literal 0"
            % where)


def _check_guard(node, scope, assigned, workflow_name, parse_condition,
                 references, ConditionError, Lit):
    """One Guard's condition (and, since RFC-0028, each `or` alternative):
    every reference resolvable, comparable, and stable.

    Each alternative is an independent `Condition` — RFC-0028 does not widen
    `Condition`'s grammar — so it gets exactly the same checks the primary
    condition does, one text at a time.
    """
    text = node.get("condition")
    if not text:
        return                            # `repeat` carries a count, not a condition
    for one_text in (text,) + tuple(node.get("alternatives") or ()):
        _check_one_condition(one_text, scope, assigned, workflow_name,
                             parse_condition, references, ConditionError, Lit)


def _check_one_condition(text, scope, assigned, workflow_name, parse_condition,
                         references, ConditionError, Lit):
    try:
        cond = parse_condition(text)
    except ConditionError:
        return                            # the parser already refused it
    if cond is None:
        return

    for name in references(cond):
        scope.check_reference(name, text)
        # RFC-0015: mode B receives every condition field as an i64 parameter
        # fixed at entry, so a guard reading a value an earlier step assigned
        # would compare the pre-assignment number there and the current one
        # here. Refusing is what keeps the two modes one language.
        if name in assigned:
            raise LowerError(
                "workflow %s: guard condition %r reads %r, which an earlier "
                "step assigns — a guard must not depend on a value this "
                "workflow changed (RFC-0015: mode B fixes condition fields "
                "at entry). Move the guard above the assignment."
                % (workflow_name, text, name))

    for term in _comparisons(cond):
        if isinstance(term.left, Lit) and isinstance(term.right, Lit):
            raise LowerError(
                "workflow %s: guard condition %r compares two literals, so it "
                "decides nothing — name a field on at least one side"
                % (workflow_name, text))
        where = "workflow %s: guard condition %r" % (workflow_name, text)
        _check_literal_zero_divisor(term.left, where)
        _check_literal_zero_divisor(term.right, where)

    _check_dimensions(cond, scope, text)


def _value_dimension(value, scope, text, subject=GUARD_SUBJECT):
    """One `Value`'s dimension: `"instant"`, `"scalar"`, or None if undecidable.

    RFC-0016 §Reference-level Specification. Two dimensions, not three: a
    Duration literal IS an i64 count of milliseconds, so it shares `scalar` with
    Integer. Splitting it out would only add refusals (`stock <= 30d`) that this
    issue does not ask for and that no program in the tree writes.

    None propagates: if either operand's type is not in the document, the whole
    value is undecidable and the comparison is left to the runtime, which is the
    behaviour bare references already had.
    """
    from .condition import Arith, Lit, Ref

    if isinstance(value, Lit):
        return "scalar"
    if isinstance(value, Ref):
        return scope.check_reference(value.name, text, subject)
    if isinstance(value, Arith):
        left = _value_dimension(value.left, scope, text, subject)
        right = _value_dimension(value.right, scope, text, subject)
        if left is None or right is None:
            return None
        if left == "instant" and right == "instant":
            if value.op == "-":
                return "scalar"           # elapsed milliseconds
            raise LowerError(
                "workflow %s: %r adds two instants (%s %s %s), which names no "
                "point in time — subtract them to get the elapsed duration, or "
                "add a duration to one of them (RFC-0016)"
                % (scope.workflow_name, text, _describe(value.left), value.op,
                   _describe(value.right)))
        if left == "instant" or right == "instant":
            return "instant"              # instant +/- duration stays an instant
        return "scalar"
    return None


def _describe(value):
    """How to name one operand in a diagnostic.

    A reference is named; a literal is described. `value_to_string` normalises a
    duration to its coarsest unit, so echoing a literal back would print `30d`
    at an author who wrote `43200m` and leave them looking for a token that is
    not in their source.
    """
    from .condition import Arith, Lit, Ref, value_to_string
    if isinstance(value, Ref):
        return value.name
    if isinstance(value, Lit):
        return "a duration literal" if value.is_duration else "a number literal"
    if isinstance(value, Arith):
        return value_to_string(value)
    return value_to_string(value)


def _check_dimensions(cond, scope, text, subject=GUARD_SUBJECT):
    """Refuse a comparison whose two sides are not the same kind of quantity.

    This is what turns t2 F-5 ③ (`payment.createdAt <= 43200m`) from "DateTime
    has no evaluator" into the judgement an author can act on: an instant and a
    duration are both i64 underneath, so nothing stops the machine comparing
    them — only the type system does, and it has to say why.
    """
    for term in _comparisons(cond):
        left = _value_dimension(term.left, scope, text, subject)
        right = _value_dimension(term.right, scope, text, subject)
        if left is None or right is None:
            continue                      # undecidable from the document alone
        if left != right:
            raise LowerError(
                "workflow %s: %r compares %s (%s) with %s (%s) — RFC-0016 "
                "compares like with like. An instant and a number are not the "
                "same quantity; subtract two instants to get a duration, then "
                "compare that to a duration such as `30d`"
                % (scope.workflow_name, text, _describe(term.left), left,
                   _describe(term.right), right))


def _comparisons(cond):
    """The Comparison terms of a condition, whether or not it is an `and`."""
    from .condition import And, Comparison
    if isinstance(cond, Comparison):
        return (cond,)
    if isinstance(cond, And):
        return cond.terms
    return ()


class _Scope:
    """What the document says about the names a workflow's values may use.

    One object rather than seven parameters threaded through three functions:
    the guard check, the assignment check and the type check all ask the same
    three questions of the same document.
    """

    def __init__(self, workflow_name, by_binding, read_entities, declared_fields,
                 base_of, network_bindings=frozenset(), create_bindings=None):
        self.workflow_name = workflow_name
        self.by_binding = by_binding
        self.read_entities = read_entities
        self.declared_fields = declared_fields
        # RFC-0027 §2/§4: names bound by `call/request ... as <name>` — no
        # Entity behind them, so `check_reference` skips the field-existence
        # check for these (a response body has no declared shape).
        self.network_bindings = network_bindings
        # issue #97 / RFC-0012 Updates: names bound by `create ... as
        # <name>` — UNLIKE a network result, this row DOES have a declared
        # Entity shape (the noun `create` names), so it gets the same
        # field-checked treatment a `read` binding gets, not the "any field
        # name accepted" treatment `network_bindings` gets. `binding ->
        # entity node`, keyed by the `as` name, not the entity's own binding
        # name.
        self.create_bindings = create_bindings or {}
        self.base_of = base_of

    def check_reference(self, name, text, subject=GUARD_SUBJECT,
                        is_target=False):
        """One `Reference`, judged against the document.

        Returns the operand's DIMENSION (`"instant"` or `"scalar"`), or None
        when the document does not declare a type for it — a bare reference
        names a payload field the document never describes, so its dimension is
        decided at runtime, exactly as its value is.
        """
        field_node = self.resolve_field(name, text, subject, is_target)
        if field_node is None:
            return None
        return self._dimension_of(field_node, name, text)

    def resolve_field(self, name, text, subject=GUARD_SUBJECT,
                      is_target=False):
        """One `Reference`, resolved to its field's declaration — every
        judgement `check_reference` makes EXCEPT the final numeric/instant
        dimension (`_dimension_of`).

        Returns the field's declaration dict, or None when the document does
        not structurally describe it (a bare reference, or a network-result
        binding whose response shape is not declared — RFC-0027 §2/§4).
        Raises `LowerError` for every reference that IS structurally
        checkable but fails: unknown binding, undeclared field, or a binding
        this workflow never reads.

        A caller that also needs the numeric/instant dimension calls
        `check_reference`, which applies `_dimension_of` on top of this. A
        caller with its OWN type rule — `format`'s Text-only target,
        Password-forbidden argument (issue #94) — calls this directly, since
        `_dimension_of` would refuse every Text-family field `format` exists
        to write.
        """
        from .condition import PAYLOAD_NAMESPACE
        if "." not in name:
            return None                   # bare reference — a payload field
        binding, _, field = name.partition(".")

        if binding == PAYLOAD_NAMESPACE:
            if field not in self.declared_fields:
                raise LowerError(
                    "workflow %s: %r names input field %r, which no entity "
                    "declares (declared fields: %s)"
                    % (self.workflow_name, text, field,
                       ", ".join(sorted(self.declared_fields)) or "none"))
            return self.declared_fields[field]

        if binding == CALLER_NAMESPACE:
            # issue #119: the caller scope has no Entity behind it — no field
            # declaration to borrow a dimension from, so this reads like a
            # network-result binding (resolved, and dimensionless, at
            # runtime) rather than like a payload field.
            if field not in CALLER_FIELDS:
                raise LowerError(
                    "workflow %s: %r names caller field %r, which does not "
                    "exist (the caller scope has only: %s)"
                    % (self.workflow_name, text, field,
                       ", ".join(CALLER_FIELDS)))
            return None

        if binding in self.network_bindings:
            # RFC-0027 §2/§4: a network result binding's shape is not
            # declared anywhere (a response body is not an Entity), so any
            # field name is accepted here — the same "unchecked, resolved at
            # runtime" treatment `input.*` gets, one level down.
            return None

        if binding in self.create_bindings:
            # issue #97 / RFC-0012 Updates: a `create ... as <name>` binding
            # is live the instant the row is created — no "this workflow
            # never reads it" gate applies here, unlike a plain entity
            # binding (RFC-0012 §G12.2/§G12.5), since the row was just made
            # by this same step.
            entity = self.create_bindings[binding]
            fields = {f["name"]: f for f in entity["fields"]}
            if field not in fields:
                raise LowerError(
                    "workflow %s: %s %r names field %r, which entity %s "
                    "does not declare"
                    % (self.workflow_name, subject, text, field, entity["name"]))
            return fields[field]

        entity = self.by_binding.get(binding)
        if entity is None:
            raise LowerError(
                "workflow %s: %s %r names %r, which is not a "
                "declared entity" % (self.workflow_name, subject, text, binding))
        fields = {f["name"]: f for f in entity["fields"]}
        if field not in fields:
            raise LowerError(
                "workflow %s: %s %r names field %r, which entity %s "
                "does not declare"
                % (self.workflow_name, subject, text, field, entity["name"]))
        if entity["id"] not in self.read_entities:
            # Same judgement, three wordings — because the repair differs by
            # where the reference sits. A guard keeps its original sentence
            # verbatim: RFC-0012 §G12.5 quotes it, and t1/t3 measured that its
            # "false forever" clause is what makes the cause legible. An
            # assignment TARGET must not be sent to `input.<field>` at all —
            # `_derive_assignment` refuses that on the left of `to`, so the
            # guard's repair line would walk the author into a second,
            # unrelated refusal (r3 N-2).
            if is_target:
                raise LowerError(
                    "workflow %s: %s %r assigns to %s, but this workflow never "
                    "reads it — no binding can ever exist, so there is nothing "
                    "to assign to (read it first with one of %s, or create it "
                    "with `as` if this step creates it; `set` writes only to "
                    "a row this workflow read or created)"
                    % (self.workflow_name, subject, text, entity["id"],
                       " / ".join("`%s`" % v for v in READ_VERBS)))
            if subject != GUARD_SUBJECT:
                raise LowerError(
                    "workflow %s: %s %r reads %s, but this workflow never "
                    "reads it — no binding can ever exist, so the reference "
                    "resolves to nothing (to read the run's input instead, "
                    "write `input.%s`)"
                    % (self.workflow_name, subject, text, entity["id"], field))
            raise LowerError(
                "workflow %s: %s %r reads %s, but this workflow "
                "never reads it — no binding can ever exist, so the guard would "
                "be false forever (to check the run's input instead, write "
                "`input.%s`)"
                % (self.workflow_name, subject, text, entity["id"], field))
        return fields[field]

    def _dimension_of(self, field_node, name, text):
        """The operand's dimension, or a refusal (RFC-0015 §D6, RFC-0016).

        t2 F-4 is the reason this is a compile error and not a runtime one: a
        `Money` guard compiled with no warning and then failed with a raw
        `TypeError: '<=' not supported between instances of 'dict' and 'int'`
        from inside the interpreter.

        RFC-0016 moved `DateTime` out of the refusal and gave it a dimension
        instead: it has an evaluator now (UTC epoch-milliseconds), so what it
        cannot do is be compared to a plain number, which is a different
        judgement made by `_check_dimensions`.
        """
        declared = field_node.get("type")
        base = self.base_of.get(declared, declared)
        if base == "Integer":
            return "scalar"
        if base == "DateTime":
            return "instant"
        raise LowerError(
            "workflow %s: %r uses %s, whose declared type %s is neither "
            "Integer nor DateTime — RFC-0016 computes over whole numbers and "
            "instants only (Money and the composite types have no evaluator in "
            "either mode)"
            % (self.workflow_name, text, name, declared))


def _derive_effect(step_id, verb, obj, registry, lineno, rest=(),
                   diagnostics=None, step_text=None, http_caps=None,
                   verb_sink=None, base_of=None, namespace=None):
    """R1: closed-lexicon lookup. Returns an Effect node dict, or None.

    `rest` is the step line's tokens past the object (`tokens[2:]`) — every
    verb but `NetworkCall` and `create`/`insert` ignores it; those read an
    `as <name>` trailing clause there (RFC-0027 §2, extended to `create` by
    issue #97 / RFC-0012 Updates — `update`/`delete` still ignore `rest`,
    since they answer an affected-row count, not a row). `NetworkCall` also
    reads an optional leading `with <ref>...` clause there (issue #109, D6).

    `diagnostics`/`step_text` (issue #91) let `_resolve_entity` report an
    `unknown-entity` warning for a step object that names no declared entity,
    without changing which entity it falls back to resolving.

    `http_caps` (issues #101, #109) is name -> the declared `capability http`
    fields. The `NetworkCall` branch uses membership to flag a target with no
    matching declaration (it runs with method POST and no auth either way,
    so this is informational, not a rejection), and reads `path` to check a
    `with <ref>...` clause's argument count against the template's `{}` count.

    `verb_sink` (issue #125) is `_WfContext.network_verbs` — the `NetworkCall`
    branch records `eid -> verb` there so `_check_rollback_escapes_network`
    can quote the author's own verb later, without adding a `verb` field to
    the IR node itself.
    """
    http_caps = http_caps or {}
    entry = VERB_LEXICON.get(verb)
    if entry is None:
        return None
    kind, fixed = entry
    eid = "%s.%s" % (step_id, EFFECT_SLUG[kind])

    if kind == "Validation":
        from .condition import PAYLOAD_NAMESPACE
        # `input` (RFC-0015 §D6) is the reserved payload keyword, not an
        # entity noun — the loop below would never match it against a
        # declared entity, and it is not #91's "unknown entity" failure mode.
        validation_diagnostics = None if obj == PAYLOAD_NAMESPACE else diagnostics
        ent = _resolve_entity(registry, obj, verb, lineno,
                              diagnostics=validation_diagnostics, step_text=step_text,
                              namespace=namespace)
        field_names = [f["name"] for f in ent["fields"]]
        if obj and obj in field_names:
            ftype = next(f["type"] for f in ent["fields"] if f["name"] == obj)
            return _node(kind, eid, target="%s.%s" % (ent["id"], obj), rule=ftype,
                        line=lineno)
        # `input` (or no object) validates the workflow's input payload: every
        # declared field is checked by its semantic type's built-in rule.
        return _node(kind, eid, target=ent["id"], rule="semantic-types",
                    line=lineno)

    if kind == "RepositoryCall":
        ent = _resolve_entity(registry, obj, verb, lineno,
                              diagnostics=diagnostics, step_text=step_text,
                              namespace=namespace)
        if fixed["operation"] == "create" and rest:
            # issue #97 / RFC-0012 Updates: `create <noun> as <name>` reuses
            # RFC-0027 §2's result-binding notation and its two static checks
            # verbatim (camelCase shape, collision with an entity's
            # single-row binding name) — `update`/`delete` are untouched,
            # since they answer an affected-row count, not a row to bind.
            if len(rest) == 2 and rest[0] == "as":
                name = rest[1]
                if not re.match(r"^[a-z][a-zA-Z0-9]*$", name):
                    raise LowerError(
                        "line %d: `as %s` is not a valid binding name — it "
                        "must be camelCase, like every other binding name "
                        "(RFC-0012 §G12.1)" % (lineno, name))
                for e in registry.values():
                    if name == binding_name(e):
                        raise LowerError(
                            "line %d: `as %s` collides with entity %s's "
                            "single-row binding name — a result binding "
                            "cannot share a name with it "
                            "(RFC-0027 §2)" % (lineno, name, e["name"]))
                return _node(kind, eid, entity=ent["id"],
                            operation=fixed["operation"], result=name,
                            line=lineno)
            raise LowerError(
                "line %d: create accepts either no trailing words or "
                "'as <name>', got %r" % (lineno, tuple(rest)))
        if fixed["operation"] == "query" and rest:
            # issue #116, D1: `list <Entity> where <cond> [order by <field>
            # [desc]] [limit <N>]`. `_node` drops a `None`-valued kwarg, so
            # the empty-`rest` case just below stays the unchanged 4-key
            # node RFC-0025 already emits — the "predicate=None path is
            # byte-identical" regression this issue's constraints require.
            predicate, order, limit = _parse_list_clauses(
                rest, lineno, ent, base_of or {})
            return _node(kind, eid, entity=ent["id"], operation=fixed["operation"],
                        predicate=predicate, order=order, limit=limit, line=lineno)
        return _node(kind, eid, entity=ent["id"], operation=fixed["operation"],
                    line=lineno)

    if kind == "CacheAccess":
        base = obj
        if base is None:
            ent = _resolve_entity(registry, None, verb, lineno, namespace=namespace)
            base = ent["id"].split(".")[-1]
        return _node(kind, eid, key="%s:{id}" % base, operation=fixed["operation"],
                    line=lineno)

    if kind == "NetworkCall":
        target = obj or "unspecified"
        if verb_sink is not None:
            verb_sink[eid] = verb
        cap = http_caps.get(target)
        if (diagnostics is not None and not _looks_like_url(target)
                and cap is None):
            diagnostics.add(
                code="declared-not-bound", where=eid,
                subject="%s %s" % (verb, target),
                message="%r has no `capability http` declaration — it runs "
                        "with method POST and no auth" % target,
                line=lineno)
        # issue #109, D6: an optional leading `with <ref>...` clause,
        # substituted into the target capability's declared `path` template
        # at run time (`condition.parse_format`'s `{}`-count convention
        # reused here, not its runtime substitution — that one does not
        # escape, and a URL path must, `drivers.py`'s job).
        tail = list(rest)
        path_args = None
        if tail and tail[0] == "with":
            j = 1
            while j < len(tail) and tail[j] != "as":
                j += 1
            arg_tokens = tail[1:j]
            if not arg_tokens:
                raise LowerError(
                    "line %d: `with` needs at least one reference" % lineno)
            from .condition import _is_reference_name
            for tok in arg_tokens:
                if not _is_reference_name(tok):
                    raise LowerError(
                        "line %d: `with` argument must be camelCase or "
                        "binding.field, got %r" % (lineno, tok))
            path_args = list(arg_tokens)
            tail = tail[j:]
        template = cap.get("path") if cap else None
        placeholders = template.count("{}") if template else 0
        given = len(path_args) if path_args is not None else 0
        if placeholders != given:
            if template is None:
                raise LowerError(
                    "line %d: `with` needs a `path` declared on capability "
                    "http %s to substitute into" % (lineno, target))
            raise LowerError(
                "line %d: capability http %s's `path` %r has %d `{}` "
                "placeholder(s) but `with` gives %d argument(s)"
                % (lineno, target, template, placeholders, given))
        if not tail:
            # RFC-0027 §3: the unbound, backward-compatible form — no
            # `result` field, byte-identical to the pre-RFC-0027 no-op.
            node = _node(kind, eid, target=target, line=lineno)
            if path_args is not None:
                node["path_args"] = path_args
            return node
        if len(tail) == 2 and tail[0] == "as":
            name = tail[1]
            # RFC-0027 §2, check 1: `<name>.status` must be a valid
            # `Reference` (RFC-0012 §G12.1), which requires camelCase — the
            # same shape `condition._is_camel_name` already enforces for
            # every other binding name.
            if not re.match(r"^[a-z][a-zA-Z0-9]*$", name):
                raise LowerError(
                    "line %d: `as %s` is not a valid binding name — it must "
                    "be camelCase, like every other binding name "
                    "(RFC-0012 §G12.1)" % (lineno, name))
            # RFC-0027 §2, check 2: a network result binding and an entity's
            # single-row binding share the same grammar position
            # (`<binding>.<field>`), so their names cannot collide — unlike
            # RowSet bindings (RFC-0025 §5), which are disambiguated by the
            # `Aggregate` production's distinct first token instead.
            for ent in registry.values():
                if name == binding_name(ent):
                    raise LowerError(
                        "line %d: `as %s` collides with entity %s's "
                        "single-row binding name — a network result "
                        "binding cannot share a name with it "
                        "(RFC-0027 §2)" % (lineno, name, ent["name"]))
            node = _node(kind, eid, target=target, result=name, line=lineno)
            if path_args is not None:
                node["path_args"] = path_args
            return node
        raise LowerError(
            "line %d: call/request accepts either no trailing words, "
            "'with <ref>...', 'as <name>', or both, got %r"
            % (lineno, tuple(rest)))

    if kind == "Authorization":
        return _node(kind, eid, requirement=obj or "unspecified", line=lineno)

    if kind == "EventEmit":
        # `emit <Event>`: the object names a declared event. Without one there is
        # nothing to reference, and RFC-0001 makes `event` required on EventEmit.
        if obj is None:
            raise LowerError(
                "line %d: `%s` needs the event to emit as its object "
                "(e.g. `emit userCreated`)" % (lineno, verb))
        return _node(kind, eid, event=_event_ref(obj, lineno), line=lineno)

    raise LowerError("line %d: no derivation defined for %s" % (lineno, kind))


def _derive_assignment(step_id, line, registry, namespace=None):
    """`set <binding>.<field> to <value>` -> an Assignment Effect node (RFC-0015).

    `set` is in `VERB_LEXICON` like every other verb — one closed table is what
    keeps "which verbs exist" answerable in one place, and it is what puts `set`
    into the generated `verbs.md`. What it cannot share is `_derive_effect`'s
    object handling: every other verb's object names an entity, and this one's
    names a field of a bound row.
    """
    from .condition import ConditionError, PAYLOAD_NAMESPACE, parse_assignment
    from .condition import value_to_string
    from .repo_policy import binding_name

    text = " ".join(line.tokens)
    try:
        target, value = parse_assignment(text)
    except ConditionError as exc:
        raise LowerError("line %d: %s" % (line.lineno, exc))

    _check_literal_zero_divisor(value, "line %d: assignment %r" % (line.lineno, text))

    binding, _, field = target.partition(".")
    if not field:
        raise LowerError(
            "line %d: assignment target %r must name a bound row's field "
            "(`<binding>.<field>`) — a bare name is an input field, and the "
            "input is not state this workflow owns" % (line.lineno, target))
    if binding == PAYLOAD_NAMESPACE:
        raise LowerError(
            "line %d: %r assigns to the run's input, which is not state — "
            "assign to a row this workflow read (`<binding>.%s`)"
            % (line.lineno, text, field))
    if binding == CALLER_NAMESPACE:
        # issue #119, D4: same reasoning as `input` above — RFC-0015 §G15.2
        # — but the state in question is the CALLER's identity, not this
        # run's payload, so the message names that instead of repeating
        # the input wording verbatim.
        raise LowerError(
            "line %d: %r assigns to the caller scope, which is not state "
            "this workflow owns — it is the verified identity of who "
            "called it, read-only (`<binding>.%s`)"
            % (line.lineno, text, field))

    entity = None
    for ent in registry.values():
        if binding_name(ent) == binding:
            entity = ent
            break
    if entity is None:
        raise LowerError(
            "line %d: assignment target %r names %r, which is not a declared "
            "entity" % (line.lineno, target, binding))
    if field not in {f["name"] for f in entity["fields"]}:
        raise LowerError(
            "line %d: assignment target %r names field %r, which entity %s does "
            "not declare" % (line.lineno, target, field, entity["name"]))
    _check_internal_visibility(entity, namespace, line.lineno, "set", target)

    eid = "%s.%s" % (step_id, EFFECT_SLUG["Assignment"])
    return _node("Assignment", eid, target=target,
                 expression=value_to_string(value), entity=entity["id"],
                 line=line.lineno)


def _derive_format(step_id, line, registry):
    """`format <binding>.<field> from "<template>" [with <ref>...]` -> an
    Assignment Effect node (issue #94). Structurally the same shape
    `_derive_assignment` builds — same binding rule, same node fields — just
    parsed by `condition.parse_format` instead of `parse_assignment`. The
    template's `{}`-vs-argument-count check already happened inside
    `parse_format`; what THIS function still owns is what `_derive_assignment`
    owns too: does the target name a declared entity this document has, and
    does that entity declare the field. Whether the target was actually READ
    (so a binding exists at runtime) needs the whole step list and is
    `_check_scoped_conditions`'s job, same as for `set` — this function alone
    cannot see the steps around it.
    """
    from .condition import ConditionError, PAYLOAD_NAMESPACE, parse_format
    from .condition import value_to_string
    from .repo_policy import binding_name

    text = " ".join(line.tokens)
    try:
        target, value = parse_format(text)
    except ConditionError as exc:
        raise LowerError("line %d: %s" % (line.lineno, exc))

    binding, _, field = target.partition(".")
    if not field:
        raise LowerError(
            "line %d: format target %r must name a bound row's field "
            "(`<binding>.<field>`) — a bare name is an input field, and the "
            "input is not state this workflow owns" % (line.lineno, target))
    if binding == PAYLOAD_NAMESPACE:
        raise LowerError(
            "line %d: %r formats into the run's input, which is not state — "
            "format into a row this workflow read (`<binding>.%s`)"
            % (line.lineno, text, field))
    if binding == CALLER_NAMESPACE:
        # issue #119, D4: see `_derive_assignment` — same reasoning, this
        # function's own verb wording.
        raise LowerError(
            "line %d: %r formats into the caller scope, which is not state "
            "this workflow owns — it is the verified identity of who "
            "called it, read-only (`<binding>.%s`)"
            % (line.lineno, text, field))

    entity = None
    for ent in registry.values():
        if binding_name(ent) == binding:
            entity = ent
            break
    if entity is None:
        raise LowerError(
            "line %d: format target %r names %r, which is not a declared "
            "entity" % (line.lineno, target, binding))
    if field not in {f["name"] for f in entity["fields"]}:
        raise LowerError(
            "line %d: format target %r names field %r, which entity %s does "
            "not declare" % (line.lineno, target, field, entity["name"]))

    eid = "%s.%s" % (step_id, EFFECT_SLUG["Assignment"])
    return _node("Assignment", eid, target=target,
                 expression=value_to_string(value), entity=entity["id"],
                 line=line.lineno)


def _derive_respond(step_id, line, registry, namespace=None):
    """`respond <ref> [<ref>...]` -> a Response node (issue #96, D1).

    A flat FieldMask over References — no nesting, no aliases, no conditions,
    no wildcards, so unlike `format`/`set` there is no sub-grammar to parse:
    each token after the verb IS a Reference, verbatim. Same two-phase split
    those two verbs use: this function checks each reference's OWN shape — a
    real dot, a declared entity, a declared field — the same immediate check
    `_derive_assignment`/`_derive_format` already apply to their one target.
    Whether the entity was actually READ (so a binding exists at runtime) and
    whether a referenced field is Password-typed (issue #43's masking
    chokepoint) both need the whole step list and stay
    `_check_scoped_conditions`'s job, via `_check_respond` — the same split
    `format`'s Password check uses.
    """
    from .repo_policy import binding_name

    refs = line.tokens[1:]
    if not refs:
        raise LowerError(
            "line %d: `respond` names no references — list at least one "
            "`<binding>.<field>`" % line.lineno)

    for ref in refs:
        binding, _, field = ref.partition(".")
        if not field:
            raise LowerError(
                "line %d: respond reference %r must name a bound row's "
                "field (`<binding>.<field>`), not a bare name"
                % (line.lineno, ref))
        entity = None
        for ent in registry.values():
            if binding_name(ent) == binding:
                entity = ent
                break
        if entity is None:
            raise LowerError(
                "line %d: respond reference %r names %r, which is not a "
                "declared entity" % (line.lineno, ref, binding))
        if field not in {f["name"] for f in entity["fields"]}:
            raise LowerError(
                "line %d: respond reference %r names field %r, which entity "
                "%s does not declare"
                % (line.lineno, ref, field, entity["name"]))
        _check_internal_visibility(entity, namespace, line.lineno, "respond", ref)

    eid = "%s.%s" % (step_id, EFFECT_SLUG["Response"])
    return _node("Response", eid, refs=list(refs), line=line.lineno)


def _derive_note(step_id, line):
    """`note "<template>" [with <ref>...]` -> an Annotation node (issue #111,
    D1/D2).

    `note`'s author-facing shape — verb, template, optional `with`-clause; no
    target, no `from` — is structurally the SAME right-hand side
    `condition._parse_format_rhs` already parses (the reader `format`'s
    stored `Assignment.expression` re-reads), so this reuses it verbatim
    rather than inventing a second template parser. `_parse_format_rhs`
    itself does not check the `{}`-count-vs-argument-count rule (it exists to
    re-read an already-validated expression) — `_check_placeholder_count` is
    called here explicitly, the same way `parse_format` calls it for the
    author-facing `format` grammar. Unlike `format`/`respond`, `note` names
    no declared entity or field, so there is nothing here for
    `_resolve_entity`/binding-shape checks to do — a reference's existence,
    and whether it is Password-typed, are both RUN-time questions
    (`interp.py`'s Annotation branch, D4): an observability channel must not
    be able to fail a compile or a run over a stale/unbound reference.
    """
    from .condition import ConditionError, _check_placeholder_count, _parse_format_rhs

    text = " ".join(line.tokens)
    try:
        fmt = _parse_format_rhs(line.tokens, text)
        _check_placeholder_count(fmt.template, fmt.args, text)
    except ConditionError as exc:
        raise LowerError("line %d: %s" % (line.lineno, exc))

    eid = "%s.%s" % (step_id, EFFECT_SLUG["Annotation"])
    return _node("Annotation", eid, template=fmt.template,
                 refs=[ref.name for ref in fmt.args], line=line.lineno)


def _check_internal_visibility(entity, namespace, lineno, verb, obj):
    """RFC-0033 §Reference-level "`internal/` 가시성 검사": reject a step that
    references a `Decl` whose `internal` flag is set from any namespace other
    than the one that declared it. `namespace == decl.namespace` covers both
    "same namespace" and the no-namespace case (`None == None`) — a `Decl`
    can only be `internal` when it has a namespace, so this is a no-op
    (byte-identical) whenever nothing in the compile unit is namespaced.
    """
    decl = entity["decl"]
    if decl.internal and decl.namespace != namespace:
        raise LoaderError(
            "line %d: `%s %s` references %r, declared `internal` to "
            "namespace %r — not visible from %s (RFC-0033 `internal/` "
            "visibility)"
            % (lineno, verb, obj or "", entity["name"], decl.namespace,
               ("namespace %r" % namespace) if namespace
               else "outside any namespace"))
    return entity


def _resolve_entity(registry, obj, verb, lineno, diagnostics=None, step_text=None,
                    namespace=None):
    """Pick the entity a step operates on.

    The object names it when there is a choice; with exactly one entity declared
    the object may be omitted. Ambiguity is an error that lists the candidates —
    picking one would make the program's meaning depend on declaration order.

    Issue #91: when the object *is* given, matches no declared entity's
    lowercase-concatenated name and no field name, and exactly one entity is
    declared, the single-entity fallback below still resolves it — unchanged,
    per issue #91 §4 — but a `diagnostics` accumulator now records an
    `unknown-entity` warning first, symmetric to `unknown-verb` (#36/#82). An
    object that is ambiguous across >1 declared entity keeps raising, as
    before: that case is not a silent pass and is out of #91's scope.

    RFC-0033 §Reference-level "짧은 이름 해소": `obj` matching more than one
    declared entity's bare/qualified form is new — only reachable once a
    namespace layout lets two entities share a bare name (`load_sources`
    still forbids it within one namespace, so every pre-RFC-0033 call, and
    every call in a compile unit with no subdirectories, has at most one
    match here and falls straight through to the unchanged loop below).
    When it happens: an entity in the step's OWN namespace (`namespace`,
    threaded down from the declaring workflow) wins if exactly one does;
    otherwise a `LowerError` lists only the entities whose bare name
    actually collided (RFC-0033's fix for issue #117 measurement item 4 —
    not the whole registry).
    """
    if not registry:
        raise LowerError("line %d: `%s` needs an entity in scope, and the module "
                         "declares none" % (lineno, verb))
    if obj:
        bare_matches = [ent for ent in registry.values()
                        if obj == ent["id"].split(".", 1)[1].replace(".", "")
                        or obj == "".join(split_pascal(ent["name"]))]
        if len(bare_matches) > 1:
            same_ns = [ent for ent in bare_matches
                      if ent["decl"].namespace == namespace]
            if len(same_ns) == 1:
                return _check_internal_visibility(
                    same_ns[0], namespace, lineno, verb, obj)
            by_qualified = sorted(
                bare_matches,
                key=lambda ent: _qualified_name(ent["decl"].namespace, ent["name"]))
            candidates = [_qualified_name(ent["decl"].namespace, ent["name"])
                         for ent in by_qualified]
            # The example token is the RFC's "bare id, no dots" form (the
            # same one `_resolve_entity`'s own match check above accepts as
            # an explicit qualified reference) — lowercase, unlike the
            # display-qualified `candidates` list above.
            example_token = by_qualified[0]["id"].split(".", 1)[1].replace(".", "")
            raise LowerError(
                "line %d: `%s %s` does not say which entity it means — "
                "declared in %d namespaces (%s). Name the entity with its "
                "namespace prefix (e.g. `%s %s`) or move the step into one "
                "of those namespaces."
                % (lineno, verb, obj, len(candidates), ", ".join(candidates),
                   verb, example_token))
        for ent in registry.values():
            if obj == ent["id"].split(".", 1)[1].replace(".", "") \
               or obj == "".join(split_pascal(ent["name"])):
                return _check_internal_visibility(ent, namespace, lineno, verb, obj)
            if obj in [f["name"] for f in ent["fields"]]:
                return _check_internal_visibility(ent, namespace, lineno, verb, obj)
        if len(registry) == 1:
            ent = next(iter(registry.values()))
            if diagnostics is not None:
                # D3: with exactly one entity declared, it is unconditionally
                # the suggestion — the same lowercase-concatenated form the
                # match above just failed against.
                suggestion = "".join(split_pascal(ent["name"]))
                text = step_text or ("%s %s" % (verb, obj))
                diagnostics.add(
                    code="unknown-entity",
                    where="line %d" % lineno, subject=obj, line=lineno,
                    suggestion=suggestion,
                    message="%s — '%s' names no declared entity; declared: %s"
                            " — did you mean '%s'?"
                            % (text, obj, suggestion, suggestion))
            return _check_internal_visibility(ent, namespace, lineno, verb, obj)
    if len(registry) == 1:
        return _check_internal_visibility(
            next(iter(registry.values())), namespace, lineno, verb, obj)
    raise LowerError(
        "line %d: `%s %s` does not say which entity it means, and this module "
        "declares %d (%s). Name the entity as the step's object."
        % (lineno, verb, obj or "", len(registry),
           ", ".join(sorted(e["name"] for e in registry.values()))))


def _event_ref(obj, lineno):
    """`userCreated` -> `event.user.created` (the R2 id rule, applied to an event)."""
    pascal = obj[0].upper() + obj[1:] if obj else obj
    if not re.match(r"^[A-Za-z][A-Za-z0-9]*$", obj or ""):
        raise LowerError("line %d: %r is not a valid event name" % (lineno, obj))
    return derive_id(pascal, "Event")

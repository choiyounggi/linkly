"""Knowledge Base access — RFC-0005 §Consumption Interface.

Three operations, exactly as RFC-0005 names them:

    kb.route(task_description) -> [doc_id]
    kb.load(doc_id) -> document
    kb.verify(doc_id, version) -> bool

The important constraint is on `route`: it must decide from the **routing index
alone** (the 1st tier of the 3-tier progressive disclosure), never by reading
document bodies. If routing read bodies, the tiering would buy nothing — the whole
point is that an agent pays for a body only after the trigger matched.

`load` is therefore the only operation that touches a body, and `verify` compares a
pinned version so an agent can detect that the knowledge it reasoned against has
moved underneath it.

## Pack layering (issue #137)

The core documents under `kb/` are not the only source `KnowledgeBase` can
read from — an organization can layer its own packs on top without forking
core, borrowing OPA's multi-bundle "roots" model: a pack declares the `doc_id`
prefix it owns (`pack.toml`'s `doc_id_prefix`), and two packs whose prefixes
overlap fail to load rather than silently merging (`open_policy_agent.org
/docs/management-bundles`: "roots are not overlapping ... will result in an
error"). A pack is discovered by, in merge order: the `lnpl.kb` entry-points
group (name-sorted), the `LNPL_KB_PACKS` environment variable, then the
repeated `--kb-pack` CLI flag — composed by `resolve_pack_roots` and passed
to `KnowledgeBase(packs=...)`.

Three closed rules govern a pack's documents once loaded:

  - a pack `doc_id` that collides with a **core** id is silently ignored —
    core always wins, the same "built-in never shadowed" discipline the
    driver SPI uses (`drivers.py::BuiltinShadowingTest`)
  - two packs' `doc_id_prefix` values may never be identical or nest — that
    is a `KbError` at construction time, before either pack's documents are
    read
  - every document a pack contributes must itself carry an id starting with
    that pack's own `doc_id_prefix + "-"` — a document that does not is a
    `KbError` when the index is built

`packs=None` (the default) reproduces the exact pre-#137 behavior byte for
byte — no pack scanning happens, `categories()` is exactly the core 12
categories, and `load()`'s `path` field is unchanged.
"""

import os
import re
from importlib import metadata as importlib_metadata

from lnpl import resources

CATEGORIES = ("Architecture", "Naming", "Performance", "Security", "Testing",
              "Concurrency", "Database", "Cloud", "Patterns", "AntiPatterns",
              "Style", "Framework")

STATUSES = ("draft", "verified", "deprecated")
REQUIRED_FRONTMATTER = ("id", "category", "triggers", "version", "status", "sources")

# Words that carry no routing signal — dropping them keeps a long task
# description from matching everything.
STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "is",
    "를", "을", "이", "가", "은", "는", "에", "의", "와", "과", "때", "할", "한",
}

# ---- KB packs (issue #137) -------------------------------------------------

KB_ENTRY_POINT_GROUP = "lnpl.kb"

# `doc_id_prefix` values a pack may never claim — they would collide with the
# core namespace's own vocabulary ("core") or with the project name itself.
RESERVED_PREFIXES = frozenset({"lnpl", "core"})

_PREFIX_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_MANIFEST_REQUIRED_KEYS = ("name", "version", "doc_id_prefix")


class KbError(Exception):
    """Raised when the KB is malformed or a requested document is absent."""


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _tokens(text):
    parts = re.split(r"[^0-9A-Za-z가-힣_.-]+", text.lower())
    return {p for p in parts if p and p not in STOPWORDS and len(p) > 1}


def _prefixes_overlap(a, b):
    """D3(b) — OPA roots: identical or one nests inside the other."""
    return a == b or a.startswith(b) or b.startswith(a)


def _registered_pack_summary(packs):
    return ", ".join("%s(%s)" % (p["name"], p["doc_id_prefix"]) for p in packs) or "none"


def _load_pack_manifest(pack_root):
    """`pack.toml` -> {"name", "version", "doc_id_prefix", "categories", "root"}.

    D1: `name`/`version`/`doc_id_prefix` are required; `categories` is an
    optional list. `doc_id_prefix` must match `^[a-z][a-z0-9-]*$` and must not
    be a reserved word (`RESERVED_PREFIXES`).
    """
    manifest_path = os.path.join(pack_root, "pack.toml")
    if not os.path.isfile(manifest_path):
        raise KbError("pack at %r has no pack.toml manifest" % pack_root)

    # Imported here, not at module level — tomllib is stdlib-only from Python
    # 3.11 (this project supports >=3.9, pyproject.toml), and cli.py imports
    # this module unconditionally at its own top level. A module-level
    # `import tomllib` would break `python -m lnpl` under the
    # walk-up-failed module-fallback path on any interpreter below 3.11, even
    # when no pack is ever loaded (#114 pattern).
    import tomllib

    try:
        with open(manifest_path, "rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise KbError("%s: %s" % (manifest_path, exc)) from exc

    missing = [k for k in _MANIFEST_REQUIRED_KEYS if k not in data]
    if missing:
        raise KbError("%s: missing required key(s): %s"
                      % (manifest_path, ", ".join(missing)))

    prefix = data["doc_id_prefix"]
    if not isinstance(prefix, str) or not _PREFIX_RE.match(prefix):
        raise KbError("%s: doc_id_prefix %r must match ^[a-z][a-z0-9-]*$"
                      % (manifest_path, prefix))
    if prefix in RESERVED_PREFIXES:
        raise KbError("%s: doc_id_prefix %r is reserved (reserved: %s)"
                      % (manifest_path, prefix, ", ".join(sorted(RESERVED_PREFIXES))))

    categories = data.get("categories", [])
    if not isinstance(categories, list) or not all(isinstance(c, str) for c in categories):
        raise KbError("%s: categories must be a list of strings, got %r"
                      % (manifest_path, categories))

    return {
        "name": data["name"],
        "version": data["version"],
        "doc_id_prefix": prefix,
        "categories": categories,
        "root": pack_root,
    }


def _scan_category_docs(root):
    """`root`'s `<category>/index.md` routing tables -> {doc_id: {category,
    triggers, path}}. Shared by the core root and every pack root — both are
    laid out the same way (RFC-0005 category directories + per-category
    routing tables)."""
    idx = {}
    for cat_dir in sorted(os.listdir(root)):
        cat_path = os.path.join(root, cat_dir)
        if not os.path.isdir(cat_path):
            continue
        cat_index = os.path.join(cat_path, "index.md")
        if not os.path.isfile(cat_index):
            raise KbError("category %r has no index.md" % cat_dir)
        with open(cat_index, encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r"^\|\s*`([a-z0-9-]+)`\s*\|(.*)\|\s*$", line)
                if not m:
                    continue
                doc_id, triggers = m.group(1), m.group(2).strip()
                path = os.path.join(cat_path, doc_id + ".md")
                if not os.path.isfile(path):
                    raise KbError("index lists %r but %s is missing"
                                  % (doc_id, path))
                idx[doc_id] = {"category": cat_dir, "triggers": triggers,
                               "path": path}
    return idx


def _kb_pack_entry_points():
    """Every entry-point registered under `lnpl.kb`, across the stdlib API's
    version split — same pattern `drivers.py::_driver_entry_points` uses
    (`pyproject.toml`'s declared floor is 3.9)."""
    try:
        return importlib_metadata.entry_points(group=KB_ENTRY_POINT_GROUP)
    except TypeError:
        return importlib_metadata.entry_points().get(KB_ENTRY_POINT_GROUP, [])


def discover_entry_point_packs():
    """Every `lnpl.kb` entry-point, resolved to its pack root path, name-sorted
    (D2). Each entry-point's loaded value is a zero-argument callable
    returning the pack's root directory as a string."""
    roots = []
    for ep in sorted(_kb_pack_entry_points(), key=lambda e: e.name):
        try:
            factory = ep.load()
            root = factory()
        except Exception as exc:
            raise KbError("kb pack entry-point %r (%s) failed to load: %s"
                          % (ep.name, ep.value, exc)) from exc
        roots.append(root)
    return roots


def resolve_pack_roots(flag_packs=None, env_value=None):
    """D2 merge order for pack roots: entry-points (name-sorted) -> env ->
    flag. `env_value` is `LNPL_KB_PACKS` (`os.pathsep`-separated),
    `flag_packs` is the repeated `--kb-pack` values in the order given. Core
    itself is not part of this list — `KnowledgeBase` always scans its own
    root first, unconditionally."""
    roots = list(discover_entry_point_packs())
    if env_value:
        roots.extend(p for p in env_value.split(os.pathsep) if p)
    if flag_packs:
        roots.extend(flag_packs)
    return roots


class KnowledgeBase:
    """A KB rooted at a directory laid out per RFC-0005."""

    def __init__(self, root=None, packs=None):
        if root is not None:
            self.root = root
        else:
            try:
                self.root = resources.data_path("kb")
            except resources.DataNotFoundError as exc:
                raise KbError(str(exc)) from exc
        if not os.path.isdir(self.root):
            raise KbError("no KB at %s" % self.root)
        self._index = None        # doc_id -> {category, dir, triggers, path}

        # D3(b): prefix conflicts are a construction-time error, before any
        # pack's documents are ever read — manifest-only validation, so it
        # never needs to scan a directory tree.
        self._packs = []
        for pack_root in (packs or []):
            manifest = _load_pack_manifest(pack_root)
            for other in self._packs:
                if _prefixes_overlap(manifest["doc_id_prefix"], other["doc_id_prefix"]):
                    raise KbError(
                        "pack %r's doc_id_prefix %r overlaps pack %r's prefix "
                        "%r — prefixes must not be identical or nest (core: "
                        "no prefix; registered packs: %s)"
                        % (manifest["name"], manifest["doc_id_prefix"],
                           other["name"], other["doc_id_prefix"],
                           _registered_pack_summary(self._packs)))
            self._packs.append(manifest)

    # ---- tier 1: the routing index -------------------------------------
    def index(self):
        """Load the routing index only — never a document body."""
        if self._index is not None:
            return self._index
        root_index = os.path.join(self.root, "INDEX.md")
        if not os.path.isfile(root_index):
            raise KbError("missing routing index %s" % root_index)
        idx = _scan_category_docs(self.root)
        if not idx:
            raise KbError("routing index yielded no documents")

        # Packs layer on top, in constructor order (D2's merge order is
        # decided by whoever composed `packs=`). D3(a): a pack doc_id already
        # claimed by core is silently ignored — core always wins. D3(c):
        # every other pack doc_id must start with that pack's own prefix.
        for pack in self._packs:
            pack_idx = _scan_category_docs(pack["root"])
            prefix = pack["doc_id_prefix"]
            for doc_id, meta in pack_idx.items():
                if not doc_id.startswith(prefix + "-"):
                    raise KbError(
                        "pack %r doc %r does not start with its own "
                        "doc_id_prefix %r- (core: no prefix required; "
                        "registered packs: %s)"
                        % (pack["name"], doc_id, prefix,
                           _registered_pack_summary(self._packs)))
                if doc_id in idx:
                    continue
                meta = dict(meta)
                meta["pack"] = pack["name"]
                meta["pack_root"] = pack["root"]
                idx[doc_id] = meta

        self._index = idx
        return idx

    def categories(self):
        """Core `CATEGORIES` union every loaded pack's declared categories
        (D5). `index()` and `kb --lint` both check membership against this,
        not the bare module constant, so a pack's new category is accepted."""
        cats = set(CATEGORIES)
        for pack in self._packs:
            cats.update(pack["categories"])
        return tuple(sorted(cats))

    # ---- RFC-0005 consumption interface --------------------------------
    def route(self, task_description):
        """kb.route(task_description) -> [doc_id], ranked, possibly empty.

        Decided from the index alone. An empty list is a valid answer: the KB
        having nothing to say is different from the KB guessing.
        """
        wanted = _tokens(task_description)
        if not wanted:
            return []
        scored = []
        for doc_id, meta in self.index().items():
            haystack = _tokens(meta["triggers"] + " " + doc_id.replace("-", " "))
            overlap = len(wanted & haystack)
            if overlap:
                scored.append((overlap, doc_id))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [doc_id for _score, doc_id in scored]

    def load(self, doc_id):
        """kb.load(doc_id) -> {frontmatter fields..., body}.

        D7 (issue #137 item 7): a core document's `path` is unchanged —
        relative to the repo root, byte-identical to before packs existed. A
        pack document's `path` is relative to *its own pack root* instead
        (a repo-root-relative path would be nonsensical for a pack living
        outside the repo, and an absolute path is a machine-specific value
        that breaks determinism/portability — OPA bundles address their own
        contents the same pack-relative way). A pack document also carries a
        `pack` key naming which root the path is relative to; core documents
        never get that key, so its mere presence tells a caller which base
        to resolve `path` against.
        """
        meta = self.index().get(doc_id)
        if meta is None:
            raise KbError("no such document: %r" % doc_id)
        with open(meta["path"], encoding="utf-8") as fh:
            text = fh.read()
        front, body = _split_frontmatter(text, doc_id)
        doc = dict(front)
        doc["body"] = body
        if "pack" in meta:
            doc["pack"] = meta["pack"]
            doc["path"] = os.path.relpath(meta["path"], meta["pack_root"])
        else:
            doc["path"] = os.path.relpath(meta["path"], _repo_root())
        return doc

    def verify(self, doc_id, version):
        """kb.verify(doc_id, version) -> bool. Exact match, never a range."""
        try:
            doc = self.load(doc_id)
        except KbError:
            return False
        return doc["version"] == version

    # ---- integrity -----------------------------------------------------
    def lint(self):
        """Return a list of problems; empty means the KB satisfies RFC-0005."""
        problems = []
        for doc_id in sorted(self.index()):
            try:
                doc = self.load(doc_id)
            except KbError as exc:
                problems.append(str(exc))
                continue
            for field in REQUIRED_FRONTMATTER:
                if not doc.get(field):
                    problems.append("%s: missing frontmatter %r" % (doc_id, field))
            if doc.get("id") != doc_id:
                problems.append("%s: frontmatter id is %r" % (doc_id, doc.get("id")))
            if doc.get("category") not in self.categories():
                problems.append("%s: category %r is not a recognized "
                                "category (core + packs: %s)"
                                % (doc_id, doc.get("category"),
                                   ", ".join(self.categories())))
            if doc.get("status") not in STATUSES:
                problems.append("%s: status %r is not draft/verified/deprecated"
                                % (doc_id, doc.get("status")))
            if not re.match(r"^\d+\.\d+\.\d+$", str(doc.get("version", ""))):
                problems.append("%s: version %r is not semver"
                                % (doc_id, doc.get("version")))
            if len(doc["body"].splitlines()) > 500:
                problems.append("%s: body exceeds the 500-line budget" % doc_id)
        return problems


def _split_frontmatter(text, doc_id):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise KbError("%s: missing YAML frontmatter" % doc_id)
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise KbError("%s: unterminated frontmatter" % doc_id)

    front, key = {}, None
    for line in lines[1:end]:
        if not line.strip():
            continue
        if line.startswith("  - ") and key:
            front.setdefault(key, [])
            if not isinstance(front[key], list):
                front[key] = []
            front[key].append(line[4:].strip())
            continue
        if ":" not in line:
            raise KbError("%s: cannot parse frontmatter line %r" % (doc_id, line))
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        front[key] = value if value else []
    return front, "\n".join(lines[end + 1:]).strip()

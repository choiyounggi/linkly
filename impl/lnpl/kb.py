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
"""

import os
import re

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


class KbError(Exception):
    """Raised when the KB is malformed or a requested document is absent."""


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _tokens(text):
    parts = re.split(r"[^0-9A-Za-z가-힣_.-]+", text.lower())
    return {p for p in parts if p and p not in STOPWORDS and len(p) > 1}


class KnowledgeBase:
    """A KB rooted at a directory laid out per RFC-0005."""

    def __init__(self, root=None):
        self.root = root or os.path.join(_repo_root(), "kb")
        if not os.path.isdir(self.root):
            raise KbError("no KB at %s" % self.root)
        self._index = None        # doc_id -> {category, dir, triggers, path}

    # ---- tier 1: the routing index -------------------------------------
    def index(self):
        """Load the routing index only — never a document body."""
        if self._index is not None:
            return self._index
        idx = {}
        root_index = os.path.join(self.root, "INDEX.md")
        if not os.path.isfile(root_index):
            raise KbError("missing routing index %s" % root_index)
        for cat_dir in sorted(os.listdir(self.root)):
            cat_path = os.path.join(self.root, cat_dir)
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
        if not idx:
            raise KbError("routing index yielded no documents")
        self._index = idx
        return idx

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
        """kb.load(doc_id) -> {frontmatter fields..., body}."""
        meta = self.index().get(doc_id)
        if meta is None:
            raise KbError("no such document: %r" % doc_id)
        with open(meta["path"], encoding="utf-8") as fh:
            text = fh.read()
        front, body = _split_frontmatter(text, doc_id)
        doc = dict(front)
        doc["body"] = body
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
            if doc.get("category") not in CATEGORIES:
                problems.append("%s: category %r is not one of the fixed 12"
                                % (doc_id, doc.get("category")))
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

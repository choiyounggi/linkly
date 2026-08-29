"""`.lir.json` provenance — issue #136.

`to_document()` attaches a `provenance` block so a `.lir.json` says what
vocabulary and enforcement generation it was compiled against, and which
extension slots were registered at the time — the minimal SLSA build
provenance lesson ("artifacts should say what made them") applied to the
compiler's own hub artifact.

Determinism is the whole point: two compiles of the same source, in the same
environment, must produce byte-identical provenance. No timestamps, no
build-host identifiers — only canonical digests of the compiler's own
constant tables (`lnpl.vocab.vocabulary_document()`, `lnpl.diagnostics.
ENFORCEMENT`) and the registered-extension names t-cap's `SLOTS` table
already enumerates (issue #134; reused here, not re-created).

`check()` is the consumer-side counterpart: report-only, never raises. A
`.lir.json` from before this issue simply has no `provenance` key, and
`check()` treats that as "nothing to compare" rather than an error.
"""

import hashlib
import json

from lnpl.capabilities import SLOTS
from lnpl.diagnostics import ENFORCEMENT
from lnpl import vocab


def _canonical_digest(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _current_vocabulary_digest():
    return _canonical_digest(vocab.vocabulary_document())


def _current_enforcement_digest():
    # `ENFORCEMENT` is keyed by `(clause, name)` tuples, which JSON object
    # keys cannot be — collapse each key to `"clause.name"` before hashing.
    document = {
        "%s.%s" % (clause, name): {"status": status, "note": note}
        for (clause, name), (status, note) in ENFORCEMENT.items()
    }
    return _canonical_digest(document)


def _current_extensions():
    """`{"<slot>": [registered names...]}` for every t-cap slot, always.

    Names only — no `.load()` attempt (D3: provenance records what was
    registered, not whether it still loads; that health check is t-cap's
    `capabilities_document()`, a separate concern this module does not
    duplicate).
    """
    return {
        slot: sorted(ep.name for ep in entry_points_fn())
        for slot, _group, _builtin, entry_points_fn in SLOTS
    }


def build():
    """The `provenance` block `to_document()` attaches to every compile."""
    from lnpl import __version__
    return {
        "compiler": __version__,
        "vocabulary_digest": _current_vocabulary_digest(),
        "enforcement_digest": _current_enforcement_digest(),
        "extensions": _current_extensions(),
    }


def check(document):
    """Compare `document`'s `provenance` block against the current environment.

    Report-only (issue #136: "provenance는 진단이지 게이트가 아니다") — never
    raises, regardless of how malformed or absent the block is.

    Returns `{"vocabulary_match": bool | None, "enforcement_match": bool |
    None, "missing_extensions": {"<slot>": [names...]}}`. A document with no
    `provenance` block (pre-#136) reports both matches as `None` and an empty
    `missing_extensions` — there is nothing to compare, which is not the same
    as a mismatch.
    """
    prov_block = document.get("provenance")
    if prov_block is None:
        return {"vocabulary_match": None, "enforcement_match": None,
                 "missing_extensions": {}}

    vocabulary_match = prov_block.get("vocabulary_digest") == _current_vocabulary_digest()
    enforcement_match = prov_block.get("enforcement_digest") == _current_enforcement_digest()

    current_extensions = _current_extensions()
    doc_extensions = prov_block.get("extensions") or {}
    missing_extensions = {}
    for slot, doc_names in doc_extensions.items():
        currently_registered = set(current_extensions.get(slot, []))
        missing = [name for name in doc_names if name not in currently_registered]
        if missing:
            missing_extensions[slot] = missing

    return {
        "vocabulary_match": vocabulary_match,
        "enforcement_match": enforcement_match,
        "missing_extensions": missing_extensions,
    }

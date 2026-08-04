"""The refinement registry — facet vocabulary, base categories, built-in presets
(RFC-0001 부록 A.6.3/A.6.4, issue #31).

RFC-0001 fixes exactly 18 semantic types and forbids new primitives; a user type
may only be a *refinement* of one of them. A refinement narrows its base with
`facets`, drawn from a closed vocabulary of six. Which facets a base admits is
decided by the base's category, with no per-type exceptions:

    text-ish (9)    minLength maxLength pattern enum
    numeric (2)     min max enum
    boolean (1)     none — already closed at two values
    composite (6)   none in v0.1 — no notation points at an inner field

Three presets are usable with no declaration. They are NOT privileged: `lower`
runs them through the same node builder a user declaration goes through, so a
preset serializes to exactly the node the user would have written by hand.

This module imports nothing from the rest of `lnpl` — `lower` and the Wave 3
consumers project their views from it, never the reverse. The consequence is
that the 18 base names are spelled here a second time; `tests/test_refinements.py`
binds that copy back to `types.SEMANTIC_TYPES` so the two cannot drift.
"""

import copy

# The closed facet vocabulary (A.6.3). Extending it is an RFC amendment, not a
# grammar extension, so nothing here is configurable.
FACET_NAMES = ("minLength", "maxLength", "pattern", "min", "max", "enum")

CATEGORY_FACETS = {
    "text": frozenset(("minLength", "maxLength", "pattern", "enum")),
    "numeric": frozenset(("min", "max", "enum")),
    "boolean": frozenset(),
    "composite": frozenset(),
}

# The 18 bases in the order A.6.3's category table lists them.
BASE_CATEGORY = {
    "UUID": "text",
    "Email": "text",
    "Password": "text",
    "DateTime": "text",
    "Phone": "text",
    "Currency": "text",
    "Html": "text",
    "Markdown": "text",
    "Text": "text",
    "Integer": "numeric",
    "Decimal": "numeric",
    "Boolean": "boolean",
    "Money": "composite",
    "GeoLocation": "composite",
    "Address": "composite",
    "Image": "composite",
    "File": "composite",
    "Json": "composite",
}

# A.6.4. The names are reserved: a module may not redeclare them.
PRESETS = {
    "Url": {"base": "Text",
            "facets": {"pattern": r"^https?://[^\s]+$", "maxLength": 2048}},
    "Slug": {"base": "Text",
             "facets": {"pattern": r"^[a-z0-9-]{1,64}$", "maxLength": 64}},
    "PositiveInteger": {"base": "Integer", "facets": {"min": 1}},
}


def facets_for_base(base):
    """The facet names A.6.3 allows on `base`; empty for boolean and composite.

    Raises KeyError for a name outside the 18 — callers test membership in
    BASE_CATEGORY first, which is also the `base` validity check (A.6.2).
    """
    return CATEGORY_FACETS[BASE_CATEGORY[base]]


def preset(name):
    """The built-in preset `name` as {"base": ..., "facets": ...}, or None.

    The result is a deep copy: a caller may put it straight into an IR node and
    mutate it without corrupting this process-wide table.
    """
    entry = PRESETS.get(name)
    return None if entry is None else copy.deepcopy(entry)

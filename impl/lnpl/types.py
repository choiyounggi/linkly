"""The semantic type registry — one source of truth (RFC-0001 §Semantic Type,
issue #24).

RFC-0001 fixes exactly 18 semantic types (13 domain + 5 auxiliary) and forbids
new primitives; user types may only be *refinements* of these (issue #31). Each
entry carries everything the rest of the platform needs, so the knowledge lives
in one place instead of drifting across three:

    openapi  the OpenAPI 3.1 schema for a field of this type
    sample   a valid instance, used to synthesize default fixtures (issue #23)
    check    the validation rule, as data applied by `interp.check_semantic_type`:
               ("pattern", regex, ignorecase)  str(value) must match
               ("py", pytype)                  isinstance (int excludes bool)
               ("nonempty",)                   str(value) must be truthy
               None                            no Phase 1 rule; a present,
                                               non-null value passes

This module imports nothing from the rest of `lnpl` — `interp` and `openapi`
project their views from it, never the reverse.
"""

UUID_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
EMAIL_RE = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
DATETIME_RE = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"

SEMANTIC_TYPES = {
    "UUID": {
        "openapi": {"type": "string", "format": "uuid"},
        "sample": "3f2504e0-4f89-41d3-9a0c-0305e82c3301",
        "check": ("pattern", UUID_RE, True),
    },
    "Email": {
        "openapi": {"type": "string", "format": "email"},
        "sample": "user@example.com",
        "check": ("pattern", EMAIL_RE, False),
    },
    "Password": {
        "openapi": {"type": "string", "format": "password", "writeOnly": True},
        "sample": "s3cret-value",
        "check": ("nonempty",),
    },
    "DateTime": {
        "openapi": {"type": "string", "format": "date-time"},
        "sample": "2026-07-31T09:00:00Z",
        "check": ("pattern", DATETIME_RE, False),
    },
    "Phone": {
        "openapi": {"type": "string", "pattern": r"^\+[1-9]\d{1,14}$"},
        "sample": "+14155550100",
        "check": None,
    },
    "Money": {
        "openapi": {"type": "object",
                    "properties": {"amount": {"type": "string", "format": "decimal"},
                                   "currency": {"type": "string", "minLength": 3,
                                                "maxLength": 3}},
                    "required": ["amount", "currency"]},
        "sample": {"amount": "0", "currency": "USD"},
        "check": None,
    },
    "Currency": {
        "openapi": {"type": "string", "minLength": 3, "maxLength": 3},
        "sample": "USD",
        "check": None,
    },
    "GeoLocation": {
        "openapi": {"type": "object",
                    "properties": {"lat": {"type": "number", "minimum": -90,
                                           "maximum": 90},
                                   "lng": {"type": "number", "minimum": -180,
                                           "maximum": 180}},
                    "required": ["lat", "lng"]},
        "sample": {"lat": 0, "lng": 0},
        "check": None,
    },
    "Address": {
        "openapi": {"type": "object",
                    "properties": {"line1": {"type": "string"},
                                   "line2": {"type": "string"},
                                   "city": {"type": "string"},
                                   "region": {"type": "string"},
                                   "postalCode": {"type": "string"},
                                   "country": {"type": "string", "minLength": 2,
                                               "maxLength": 2}},
                    "required": ["line1", "city", "country"]},
        "sample": {"line1": "1 Main St", "city": "Springfield", "country": "US"},
        "check": None,
    },
    "Image": {
        "openapi": {"type": "object",
                    "properties": {"uri": {"type": "string", "format": "uri"},
                                   "mediaType": {"type": "string"}},
                    "required": ["uri", "mediaType"]},
        "sample": {"uri": "https://example.com/i.png", "mediaType": "image/png"},
        "check": None,
    },
    "File": {
        "openapi": {"type": "object",
                    "properties": {"uri": {"type": "string", "format": "uri"},
                                   "mediaType": {"type": "string"},
                                   "sizeBytes": {"type": "integer"}},
                    "required": ["uri"]},
        "sample": {"uri": "https://example.com/f.pdf", "mediaType": "application/pdf"},
        "check": None,
    },
    "Json": {
        "openapi": {},
        "sample": {},
        "check": None,
    },
    "Html": {
        "openapi": {"type": "string"},
        "sample": "<p>x</p>",
        "check": None,
    },
    "Markdown": {
        "openapi": {"type": "string"},
        "sample": "# x",
        "check": None,
    },
    "Text": {
        "openapi": {"type": "string"},
        "sample": "text",
        "check": ("py", str),
    },
    "Integer": {
        "openapi": {"type": "integer", "format": "int64"},
        "sample": 1,
        "check": ("py", int),
    },
    "Decimal": {
        "openapi": {"type": "string", "format": "decimal"},
        "sample": "0",
        "check": None,
    },
    "Boolean": {
        "openapi": {"type": "boolean"},
        "sample": True,
        "check": ("py", bool),
    },
}

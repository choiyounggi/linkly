"""W3C Trace Context (https://www.w3.org/TR/trace-context/) — `traceparent`
parsing and generation for issue #107.

This module is pure functions only — no I/O, no global state. It is imported
by `wsgi.py` and `drivers.py`, never the reverse.
"""

import uuid

_HEX = set("0123456789abcdef")


def _is_lower_hex(value, length):
    return len(value) == length and all(c in _HEX for c in value)


def parse_traceparent(raw):
    """Validate-reject a `traceparent` header value at the trust boundary
    (allowlist, not sanitize — security-input-validation-at-trust-boundaries).

    Returns `{"version", "trace_id", "parent_id", "flags"}` (lowercase hex
    strings) on success, `None` on any malformed or unsafe input — this
    function never raises.
    """
    if not isinstance(raw, str) or not raw:
        return None

    parts = raw.split("-")
    if len(parts) < 4:
        return None
    # D4: a version above "00" may carry more than 4 dash-separated fields.
    # We only ever read the first four under the 00 layout.
    version, trace_id, parent_id, flags = parts[0], parts[1], parts[2], parts[3]

    if not _is_lower_hex(version, 2):
        return None
    if not _is_lower_hex(trace_id, 32):
        return None
    if not _is_lower_hex(parent_id, 16):
        return None
    if not _is_lower_hex(flags, 2):
        return None

    if version == "ff":
        return None
    if trace_id == "0" * 32:
        return None
    if parent_id == "0" * 16:
        return None

    # D4: version > "00" is not rejected — the first four fields already
    # parsed under the 00 layout, so adopt them as-is, version included.
    return {"version": version, "trace_id": trace_id, "parent_id": parent_id,
            "flags": flags}


def format_traceparent(trace_id, span_id, flags="01"):
    """Build an outbound `traceparent` header value. Always emits version
    "00" (the only version this runtime produces). Raises `ValueError` on
    malformed input — this is construction from already-valid runtime state,
    not a trust boundary, so it fails loud instead of silently coercing.
    """
    if not _is_lower_hex(trace_id, 32):
        raise ValueError("trace_id must be 32 lowercase hex characters")
    if not _is_lower_hex(span_id, 16):
        raise ValueError("span_id must be 16 lowercase hex characters")
    if not _is_lower_hex(flags, 2):
        raise ValueError("flags must be 2 lowercase hex characters")
    return "00-%s-%s-%s" % (trace_id, span_id, flags)


def new_trace_id():
    """32 lowercase hex characters. D9: regenerate on the all-zeroes case
    the spec forbids (astronomically unlikely, but a documented invariant)."""
    trace_id = uuid.uuid4().hex
    while trace_id == "0" * 32:
        trace_id = uuid.uuid4().hex
    return trace_id


def new_span_id():
    """16 lowercase hex characters. D9: regenerate on all-zeroes."""
    span_id = uuid.uuid4().hex[:16]
    while span_id == "0" * 16:
        span_id = uuid.uuid4().hex[:16]
    return span_id

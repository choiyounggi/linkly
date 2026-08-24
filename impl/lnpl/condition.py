"""Guard condition parsing and evaluation — SSOT.

RFC-0008: All condition interpretation passes through parse_condition().
No condition is evaluated differently in parser vs. runtime vs. compiler.

Syntax (RFC-0002 §Full grammar as updated by RFC-0008, RFC-0012, RFC-0015,
then RFC-0028):

  Condition  ::= Presence | Comparison ('and' Comparison)*
  Presence   ::= Reference ('exists' | 'missing')
  Comparison ::= Value Comparator Value
  Comparator ::= '<' | '<=' | '>' | '>=' | '==' | '!='
  Value      ::= Operand (ArithOp Operand)?     -- at most ONE binary operator
  Operand    ::= Reference | Integer | Duration
  ArithOp    ::= '+' | '-' | '*' | '/'           -- RFC-0028 added `*`/`/`
  Reference  ::= CamelName | Namespace '.' CamelName
  Namespace  ::= 'input' | CamelName
  Integer    ::= [0-9]+                          -- unsigned
  Duration   ::= Integer ('ms' | 's' | 'm' | 'h' | 'd')   -- 'h'/'d': RFC-0016

Three properties of that grammar are decisions, not omissions (RFC-0015,
`*`/`/` reversed by RFC-0028 — see that RFC's §Alternatives):

  **No `or` inside a `Condition`, no `not`, no parentheses.** RFC-0028 puts
  `or` back into the language, but as a guard-line STRUCTURE (`AltGuard`,
  `parser.py`) rather than a `Condition`-grammar operator — this module's
  grammar is unchanged by it. An unbounded expression language would have to
  be evaluated identically by an interpreter and by emitted MLIR; every
  production added here is a second evaluator to keep honest.

  **`and` combines Comparisons only.** Mode B decides existence through one
  run-level boolean (`run_binary(skip=...)`) and comparisons through i64
  parameters. A condition mixing the two channels could produce a step set mode A
  never produces, so a Presence stays a condition on its own.

  **Arithmetic nests zero levels.** `a - b - c` needs a precedence rule, and a
  precedence rule is a thing an author can get wrong silently.

A qualified `Reference` names a bound row's field (`product.stock`) or, under the
reserved `input` namespace, the run's input payload (`input.quantity`); a bare
one names an input payload field (RFC-0012 §G12.1). This module owns the SYNTAX
of that distinction only. Whether the binding names a declared entity, whether
that entity declares the field, and whether the operand's declared type can be
compared at all are decided where the document is in scope (`lower.py`,
RFC-0012 §G12.5, RFC-0015 §Static rejections) — this module never sees the
document.
"""

import calendar
import re
from dataclasses import dataclass
from typing import Optional, Tuple, Union

# The token tables live in `lexer` because that is what the generated reference
# (`plugins/lnpl/skills/lnpl-authoring/references/grammar.md`) is rendered from.
# Spelling them a second time here is how the reference and the parser drift.
from .lexer import (AGG_FUNCS, ARITH_OPS, COMPARATORS, DURATION_UNIT_MS,
                    INT64_MAX, INT64_MIN, LOGICAL_OPS, PAYLOAD_NAMESPACE,
                    duration_ms_or_none)

LOGICAL_AND = LOGICAL_OPS[0]
PRESENCE_KINDS = ('exists', 'missing')

# i64 — the domain mode B compiles to. Mode A checks against the same bounds so a
# value that would wrap in the compiled path fails in both (RFC-0015 §Value domain).
# Defined in `lexer` (which imports nothing) and re-exported here, because the
# duration table needs to range-check and lives there; every caller that already
# says `from .condition import INT64_MAX` is unaffected.
__all__ = ["INT64_MIN", "INT64_MAX"]

# RFC-0016 §Reference-level Specification. A `DateTime` entering a comparison is
# encoded to UTC epoch-milliseconds, so an explicit zone designator is REQUIRED:
# a zoneless timestamp binds to whatever zone the reading machine is in, which
# would make the same document decide differently per machine. Alphabetic zone
# abbreviations (`KST`, `EST`) are deliberately not matched — they are ambiguous.
INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(?:(Z|z)|([+-])(\d{2}):?(\d{2}))$")

# The same shape WITHOUT the zone requirement. Used only to tell "this is a
# date-time the author forgot to zone" apart from "this is not a date-time at
# all", so the diagnostic can name the real problem instead of falling through
# to `Cannot compare non-numeric`.
_INSTANT_SHAPE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}")

# Largest unit first — `value_to_string` returns on the first exact division, so
# 86400000 must be tried before 3600000 or a day would render as `24h`.
_DURATION_RENDER = tuple(sorted(DURATION_UNIT_MS.items(),
                                key=lambda kv: -kv[1]))


class ConditionError(Exception):
    """Raised when condition text is malformed or unsupported."""


@dataclass(frozen=True)
class Ref:
    """A `Reference` operand: `stock`, `product.stock`, `input.quantity`."""
    name: str

    @property
    def namespace(self):
        """`product` for `product.stock`; None for a bare name."""
        head, sep, _ = self.name.partition(".")
        return head if sep else None

    @property
    def field(self):
        """The last segment: `stock` for both `stock` and `product.stock`."""
        _, sep, tail = self.name.partition(".")
        return tail if sep else self.name


@dataclass(frozen=True)
class Lit:
    """An `Integer` or `Duration` operand. Durations are carried in milliseconds."""
    value: int
    is_duration: bool = False


@dataclass(frozen=True)
class Arith:
    """`<operand> ('+'|'-') <operand>` — exactly one operator, never nested."""
    left: Union[Ref, Lit]
    op: str
    right: Union[Ref, Lit]

    def __post_init__(self):
        if self.op not in ARITH_OPS:
            raise ValueError(f"invalid arithmetic operator: {self.op}")


Value = Union[Ref, Lit, Arith]


@dataclass(frozen=True)
class Aggregate:
    """`sum <ref>` or `count <ref>` (RFC-0025 §2) — an `AssignStep` right-hand
    side, never a `Value`. It does not combine with arithmetic (`sum x + 1` is
    not this grammar), so it is a sibling of `Value`, not an `Operand`.

    Whether `func` and `ref`'s shape actually agree (`count` takes one segment,
    `sum` takes two) is not decided here — this module owns syntax only, and
    that judgement needs the document (RFC-0025 §3, decided in `lower.py`,
    the same split RFC-0015's Integer-only check already makes).
    """
    func: str
    ref: Ref

    def __post_init__(self):
        if self.func not in AGG_FUNCS:
            raise ValueError(f"invalid aggregate function: {self.func}")


# An `AssignStep`'s right-hand side: a `Value` or an `Aggregate` (RFC-0025 §2).
AssignRHS = Union[Value, Aggregate]


@dataclass(frozen=True)
class Presence:
    """Existence check: `<field> exists` or `<field> missing`."""
    field: str
    kind: str  # 'exists' | 'missing'

    def __post_init__(self):
        if self.kind not in PRESENCE_KINDS:
            raise ValueError(f"invalid presence kind: {self.kind}")


@dataclass(frozen=True)
class Comparison:
    """Relational comparison: `<value> <op> <value>`.

    `left`/`right` are `Value`s, not a field name and an integer: RFC-0015 made
    the right side a full operand, and keeping a `field`/`value` pair beside them
    would let a stale reader take the left name and silently ignore the right
    one. The old attributes are gone on purpose.
    """
    left: Value
    op: str
    right: Value

    def __post_init__(self):
        if self.op not in COMPARATORS:
            raise ValueError(f"invalid comparator: {self.op}")


@dataclass(frozen=True)
class And:
    """`<comparison> and <comparison> [and ...]` — two or more terms."""
    terms: Tuple[Comparison, ...]

    def __post_init__(self):
        if len(self.terms) < 2:
            raise ValueError("`and` needs at least two terms")
        for term in self.terms:
            if not isinstance(term, Comparison):
                raise ValueError("`and` combines comparisons only")


Condition = Union[Presence, Comparison, And, None]  # None = no guard


def parse_condition(text: Optional[str]) -> Condition:
    """Parse a guard condition string into Presence, Comparison, or And.

    Returns None if text is None or empty. Raises ConditionError if text
    violates the grammar or references an unsupported form.

    This is the ONLY function that interprets condition syntax. All four gates
    (parser, lowering, mode-A runtime, mode-B compiler) call this function.
    """
    if not text or not text.strip():
        return None

    tokens = text.split()
    groups = _split_on_and(tokens, text)

    if len(groups) == 1:
        return _parse_term(groups[0], text, allow_presence=True)

    return And(tuple(_parse_term(group, text, allow_presence=False)
                     for group in groups))


def parse_assignment(text: Optional[str]) -> Tuple[str, AssignRHS]:
    """`set <Reference> to <Value|Aggregate>` -> (target name, right-hand side).

    Lives here rather than in `lower` so the assignment's right-hand side is
    parsed by the same code a guard's operands are (or, since RFC-0025, the
    same code an aggregate reference is). A second parser is a second grammar.
    """
    tokens = (text or "").split()
    if not tokens or tokens[0] != "set":
        raise ConditionError(f"assignment must start with `set`: {text!r}")
    if "to" not in tokens[1:]:
        raise ConditionError(
            f"assignment needs `to`: {text!r} "
            "(the form is `set <binding>.<field> to <value>`)")
    at = tokens.index("to", 1)
    target_tokens = tokens[1:at]
    value_tokens = tokens[at + 1:]
    if len(target_tokens) != 1:
        raise ConditionError(
            f"assignment target must be one reference: {text!r}")
    target = target_tokens[0]
    if not _is_reference_name(target):
        raise ConditionError(
            f"assignment target must be camelCase or binding.field: {text!r}")
    if not value_tokens:
        raise ConditionError(f"assignment needs a value after `to`: {text!r}")
    return target, _parse_value_or_aggregate(value_tokens, text)


def is_instant_text(raw) -> bool:
    """True when `raw` is a zoned RFC 3339 timestamp `encode_instant` accepts."""
    return isinstance(raw, str) and INSTANT_RE.match(raw) is not None


def looks_like_instant(raw) -> bool:
    """True when `raw` has a date-time shape, zoned or not.

    `is_instant_text` answers "can I encode this"; this one answers "did the
    author mean a date-time", which is what lets an unzoned value produce a
    diagnostic about the missing zone instead of about non-numeric text.
    """
    return isinstance(raw, str) and _INSTANT_SHAPE_RE.match(raw) is not None


def encode_instant(raw, where) -> int:
    """A zoned RFC 3339 timestamp -> UTC epoch-milliseconds (i64). SSOT.

    RFC-0016 §Reference-level Specification. Both modes call THIS function --
    mode A from `interp.eval_value`, mode B from `backend.encode_condition_value`
    -- so the two cannot disagree about what instant a string names. Encoding in
    milliseconds rather than days keeps 09:00 and 23:59 distinct, which is what
    makes a "within 30 days" boundary mean the same thing regardless of the time
    of day the run happens at.

    Parsing is done from the regex's own fields rather than through
    `datetime.fromisoformat`, which infers a zone for a zoneless string and
    would reintroduce the per-machine reading this function exists to refuse.
    """
    if not isinstance(raw, str):
        raise ConditionError("%s is not a date-time: %r" % (where, raw))
    m = INSTANT_RE.match(raw)
    if m is None:
        if looks_like_instant(raw):
            raise ConditionError(
                "%s is a date-time without a zone designator: %r — write an "
                "explicit `Z` or a numeric offset such as `+09:00` (RFC-0016: "
                "a zoneless timestamp names a different instant on every "
                "machine, so it has no single value to compare)" % (where, raw))
        raise ConditionError("%s is not a date-time: %r" % (where, raw))

    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac, zulu, sign, off_h, off_m = (m.group(7), m.group(8), m.group(9),
                                      m.group(10), m.group(11))

    # Sub-second precision truncates to milliseconds (toward zero), the unit the
    # i64 domain carries. `.5` is 500 ms, `.0005` is 0 ms.
    millis = int((frac or ".0")[1:].ljust(3, "0")[:3])

    try:
        # `timegm` reads the tuple as UTC; unlike `mktime` it never consults the
        # machine's TZ. Field ranges are validated below, not by this call.
        days_epoch = calendar.timegm((year, month, day, 0, 0, 0, 0, 1, 0))
    except (ValueError, OverflowError):
        raise ConditionError("%s is not a valid date: %r" % (where, raw))
    if not (1 <= month <= 12 and 1 <= day <= 31
            and hour <= 23 and minute <= 59 and second <= 60):
        raise ConditionError("%s is not a valid date-time: %r" % (where, raw))

    total = ((days_epoch + hour * 3600 + minute * 60 + second) * 1000) + millis
    if zulu is None:
        offset_ms = (int(off_h) * 3600 + int(off_m) * 60) * 1000
        total = total - offset_ms if sign == "+" else total + offset_ms
    if total < INT64_MIN or total > INT64_MAX:
        raise ConditionError(
            "%s is outside the 64-bit millisecond domain: %r" % (where, raw))
    return total


def parse_value(text: Optional[str]) -> Value:
    """A `Value` on its own — the assignment's right-hand side, re-read from the IR.

    `Assignment.expression` is stored as its normalized string (the same choice
    `Guard.condition` makes), so every consumer that needs its operands parses it
    back through here rather than keeping a second, structured copy in the node.

    Raises on an `Aggregate` string (`"sum ..."` / `"count ..."`) — a caller that
    wants either reads `parse_value_or_aggregate` instead. Kept separate so a
    caller that specifically needs arithmetic (mode B's parameter encoding,
    which has no constant-folding path for an aggregate) fails loudly on the
    form it cannot handle rather than silently receiving an `Aggregate`.
    """
    tokens = (text or "").split()
    if not tokens:
        raise ConditionError(f"missing value: {text!r}")
    return _parse_value(tokens, text)


def parse_value_or_aggregate(text: Optional[str]) -> AssignRHS:
    """An `Assignment.expression` re-read from the IR — a `Value` or an
    `Aggregate` (RFC-0025 §2). The general-purpose reader: use this unless the
    caller specifically cannot handle an `Aggregate` (see `parse_value`).
    """
    tokens = (text or "").split()
    if not tokens:
        raise ConditionError(f"missing value: {text!r}")
    return _parse_value_or_aggregate(tokens, text)


def references(cond) -> Tuple[str, ...]:
    """Every `Reference` name the condition or value mentions, in source order.

    One collector, shared by `lower`'s scope/type checks and by mode B's
    parameter list. Deriving that list twice is how the two would disagree about
    which fields a guard reads.
    """
    if cond is None:
        return ()
    if isinstance(cond, Presence):
        return (cond.field,)
    if isinstance(cond, And):
        out = []
        for term in cond.terms:
            out.extend(references(term))
        return tuple(out)
    if isinstance(cond, Comparison):
        return references(cond.left) + references(cond.right)
    if isinstance(cond, Arith):
        return references(cond.left) + references(cond.right)
    if isinstance(cond, Ref):
        return (cond.name,)
    if isinstance(cond, Lit):
        return ()
    if isinstance(cond, Aggregate):
        return references(cond.ref)
    raise ValueError(f"unknown condition type: {type(cond)}")


def condition_to_string(cond: Condition) -> Optional[str]:
    """Reverse: convert a parsed Condition back to its normalized string form.

    The normalized string is what the IR stores and what both modes compare on
    (issue #44's skip record carries it), so this is the one spelling of a
    condition: terms in source order joined by ` and `, single spaces
    throughout.
    """
    if cond is None:
        return None
    if isinstance(cond, Presence):
        return f"{cond.field} {cond.kind}"
    if isinstance(cond, Comparison):
        return "%s %s %s" % (value_to_string(cond.left), cond.op,
                             value_to_string(cond.right))
    if isinstance(cond, And):
        return " and ".join(condition_to_string(t) for t in cond.terms)
    raise ValueError(f"unknown condition type: {type(cond)}")


def guard_condition_text(condition: Optional[str],
                         alternatives: Optional[Tuple[str, ...]] = None) -> Optional[str]:
    """RFC-0028 §Reference-level Specification/4·5 — the ONE spelling of an
    alt-guard's combined condition for skip records and mode A/B comparison.

    No alternatives: `condition` unchanged (byte-identical to every guard
    before this RFC — the backward-compatibility guarantee). With
    alternatives: `condition` and each alternative, source order, joined by
    `" or "`. This is display/comparison text only — it is never fed back
    through `parse_condition` (RFC-0028 does not add `or` to the `Condition`
    grammar). Mode A's `interp._skip_record` and mode B's
    `backend.restore_skips` both call this so they cannot independently drift
    on the join rule.
    """
    if not alternatives:
        return condition
    return " or ".join([condition, *alternatives])


def value_to_string(value: AssignRHS) -> str:
    """Normalized spelling of one `Value` or `Aggregate`."""
    if isinstance(value, Ref):
        return value.name
    if isinstance(value, Lit):
        if value.is_duration:
            # Coarsest exact unit, so `30d` round-trips as `30d` rather than as
            # `43200m`. Descending order matters: every day is also a whole
            # number of hours and minutes, so the first exact match must be the
            # largest unit. `0` has no coarsest unit and renders as `0ms`.
            for unit, mult in _DURATION_RENDER:
                if value.value and value.value % mult == 0:
                    return "%d%s" % (value.value // mult, unit)
            return "%dms" % value.value
        return str(value.value)
    if isinstance(value, Arith):
        return "%s %s %s" % (value_to_string(value.left), value.op,
                             value_to_string(value.right))
    if isinstance(value, Aggregate):
        return "%s %s" % (value.func, value.ref.name)
    raise ValueError(f"unknown value type: {type(value)}")


# ---- parsing internals ------------------------------------------------------


def _split_on_and(tokens, text):
    """Token list -> list of term token lists. Empty groups are a syntax error."""
    groups, cur = [], []
    for tok in tokens:
        if tok == LOGICAL_AND:
            groups.append(cur)
            cur = []
        else:
            cur.append(tok)
    groups.append(cur)
    for group in groups:
        if not group:
            raise ConditionError(
                f"`and` needs a comparison on both sides: {text!r}")
    return groups


def _parse_term(tokens, text, allow_presence):
    if len(tokens) < 2:
        raise ConditionError(f"condition too short: {text!r}")

    if len(tokens) == 2 and tokens[1] in PRESENCE_KINDS:
        if not allow_presence:
            raise ConditionError(
                f"`{tokens[1]}` cannot appear inside `and`: {text!r} "
                "(RFC-0015: `and` combines comparisons only — write the "
                "presence check as its own guard)")
        if not _is_reference_name(tokens[0]):
            raise ConditionError(
                f"field must be camelCase or binding.field: {text!r}")
        return Presence(tokens[0], tokens[1])

    op_positions = [i for i, tok in enumerate(tokens) if tok in COMPARATORS]
    if not op_positions:
        raise ConditionError(
            f"no comparator in {' '.join(tokens)!r}: {text!r} "
            "(expected one of %s, or `<field> exists|missing`)"
            % " ".join(COMPARATORS))
    if len(op_positions) > 1:
        raise ConditionError(
            f"more than one comparator in {' '.join(tokens)!r}: {text!r} "
            "(chain range checks with `and` instead)")

    at = op_positions[0]
    left = _parse_value(tokens[:at], text)
    right = _parse_value(tokens[at + 1:], text)
    return Comparison(left, tokens[at], right)


def _parse_value_or_aggregate(tokens, text):
    """`Value | Aggregate` (RFC-0025 §2) — dispatched on the first token, since
    `sum`/`count` cannot start a `Value` (they are not valid `Operand`s)."""
    if tokens and tokens[0] in AGG_FUNCS:
        return _parse_aggregate(tokens, text)
    return _parse_value(tokens, text)


def _parse_aggregate(tokens, text):
    """`AggFunc Reference` (RFC-0025 §2). Whether the reference has the right
    number of segments for its function (`count` takes one, `sum` takes two)
    is not judged here — that needs the document, and is `lower.py`'s job
    (RFC-0025 §3), the same split RFC-0015 draws for the Integer-only check.
    """
    if len(tokens) != 2:
        raise ConditionError(
            f"aggregate needs exactly one reference: {text!r} "
            "(the form is `sum <ref>` or `count <ref>`)")
    func, ref_token = tokens
    if not _is_reference_name(ref_token):
        raise ConditionError(
            f"aggregate reference must be camelCase or binding.field: {text!r}")
    return Aggregate(func, Ref(ref_token))


def _parse_value(tokens, text):
    if not tokens:
        raise ConditionError(f"missing operand: {text!r}")
    if len(tokens) == 1:
        return _parse_operand(tokens[0], text)
    if len(tokens) == 3:
        if tokens[1] not in ARITH_OPS:
            raise ConditionError(
                f"invalid arithmetic operator {tokens[1]!r}: {text!r} "
                "(RFC-0028 supports `+` `-` `*` `/` only)")
        return Arith(_parse_operand(tokens[0], text), tokens[1],
                     _parse_operand(tokens[2], text))
    raise ConditionError(
        f"unsupported operand form {' '.join(tokens)!r}: {text!r} "
        "(a value is `<operand>` or `<operand> +|- <operand>` — "
        "RFC-0015 does not nest arithmetic)")


def _parse_operand(token, text):
    if token.isdigit():
        value = int(token)
        if value > INT64_MAX:
            raise ConditionError(
                "integer literal %r is past the 64-bit domain both modes "
                "compile to: %r" % (token, text))
        return Lit(value)
    try:
        duration = duration_ms_or_none(token)
    except OverflowError as e:
        raise ConditionError("%s: %r" % (e, text))
    if duration is not None:
        return Lit(duration, is_duration=True)
    if _is_reference_name(token):
        return Ref(token)
    raise ConditionError(f"invalid operand {token!r}: {text!r}")


def _is_camel_name(s: str) -> bool:
    """Check if s matches camelCase: [a-z][a-zA-Z0-9]*."""
    if not s:
        return False
    if not s[0].islower():
        return False
    return all(c.isalnum() for c in s)


def _is_reference_name(s: str) -> bool:
    """Check if s matches `Reference` (RFC-0012): CamelName ('.' CamelName)?.

    Exactly one or two segments. `a.b.c` is refused: a bound row is a flat
    mapping, so a three-segment path names nothing an evaluator could walk —
    the same judgement RFC-0008 made about productions with no evaluator.

    The grammar's own words are not references. `and` would otherwise be a legal
    bare name, which would make `a and b` parse as something no one wrote.
    """
    if s in (LOGICAL_AND, 'to') + PRESENCE_KINDS:
        return False
    segments = s.split(".")
    if len(segments) > 2:
        return False
    return all(_is_camel_name(segment) for segment in segments)

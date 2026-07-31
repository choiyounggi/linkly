"""Guard condition parsing and evaluation — SSOT.

RFC-0008: All condition interpretation passes through parse_condition().
No condition is evaluated differently in parser vs. runtime vs. compiler.

Syntax (RFC-0002 §Full grammar as updated by RFC-0008):
  Condition ::= Presence | Comparison
  Presence  ::= CamelName ('exists' | 'missing')
  Comparison ::= CamelName Comparator (Integer | Duration)
  Comparator ::= '<' | '<=' | '>' | '>=' | '==' | '!='
  Duration  ::= Integer ('ms' | 's' | 'm')
"""

from dataclasses import dataclass
from typing import Union, Optional


class ConditionError(Exception):
    """Raised when condition text is malformed or unsupported."""


@dataclass(frozen=True)
class Presence:
    """Existence check: `<field> exists` or `<field> missing`."""
    field: str
    kind: str  # 'exists' | 'missing'

    def __post_init__(self):
        if self.kind not in ('exists', 'missing'):
            raise ValueError(f"invalid presence kind: {self.kind}")


@dataclass(frozen=True)
class Comparison:
    """Relational comparison: `<field> <op> <value>`."""
    field: str
    op: str  # '<' | '<=' | '>' | '>=' | '==' | '!='
    value: int  # always integer (Duration converted to ms)
    is_duration: bool = False  # track if original was Duration for readability

    def __post_init__(self):
        VALID_OPS = ('<', '<=', '>', '>=', '==', '!=')
        if self.op not in VALID_OPS:
            raise ValueError(f"invalid comparator: {self.op}")
        if not isinstance(self.value, int) or self.value < 0:
            raise ValueError(f"invalid comparison value: {self.value}")


Condition = Union[Presence, Comparison, None]  # None = no guard


def parse_condition(text: Optional[str]) -> Condition:
    """Parse a guard condition string into Presence or Comparison.

    Returns None if text is None or empty. Raises ConditionError if text
    violates the grammar or references an unsupported form.

    This is the ONLY function that interprets condition syntax. All three
    gates (parser, mode-A runtime, mode-B compiler) call this function.
    """
    if not text or not text.strip():
        return None

    tokens = text.split()
    if len(tokens) < 2:
        raise ConditionError(f"condition too short: {text!r}")

    field = tokens[0]
    if not _is_camel_name(field):
        raise ConditionError(f"field must be camelCase: {text!r}")

    if len(tokens) == 2 and tokens[1] in ('exists', 'missing'):
        return Presence(field, tokens[1])

    if len(tokens) == 3:
        op = tokens[1]
        value_str = tokens[2]
        VALID_OPS = ('<', '<=', '>', '>=', '==', '!=')
        if op not in VALID_OPS:
            raise ConditionError(f"invalid comparator {op!r}: {text!r}")

        # Parse value: integer or duration
        if value_str.isdigit():
            value = int(value_str)
            return Comparison(field, op, value, is_duration=False)

        # Duration: <digits>(ms|s|m)
        for unit, multiplier in [('ms', 1), ('s', 1000), ('m', 60000)]:
            if value_str.endswith(unit):
                num_str = value_str[:-len(unit)]
                if num_str.isdigit():
                    value_ms = int(num_str) * multiplier
                    return Comparison(field, op, value_ms, is_duration=True)

        raise ConditionError(f"invalid value {value_str!r}: {text!r}")

    raise ConditionError(f"unsupported condition form: {text!r} "
                         "(RFC-0008 supports only `<field> exists|missing` "
                         "and `<field> <op> <value>`, where <value> is Integer or Duration)")


def _is_camel_name(s: str) -> bool:
    """Check if s matches camelCase: [a-z][a-zA-Z0-9]*."""
    if not s:
        return False
    if not s[0].islower():
        return False
    return all(c.isalnum() for c in s)


def condition_to_string(cond: Condition) -> Optional[str]:
    """Reverse: convert parsed Condition back to normalized string form.

    Used for serialization and debugging.
    """
    if cond is None:
        return None
    if isinstance(cond, Presence):
        return f"{cond.field} {cond.kind}"
    if isinstance(cond, Comparison):
        if cond.is_duration:
            # Find best unit for readability
            if cond.value % 60000 == 0:
                return f"{cond.field} {cond.op} {cond.value // 60000}m"
            if cond.value % 1000 == 0:
                return f"{cond.field} {cond.op} {cond.value // 1000}s"
        return f"{cond.field} {cond.op} {cond.value}"
    raise ValueError(f"unknown condition type: {type(cond)}")

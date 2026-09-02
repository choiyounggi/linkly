"""`Diagnostic.hint` (issue #165) — a concrete repair instruction alongside
`code`/`severity`, for all 18 core `CODES` plus optional extension-registered
codes (RFC-0042). Mirrors `test_extension_diagnostics.py`'s in-process
entry-point fixture pattern for the extension half.
"""

import os
import unittest
from unittest import mock

from lnpl import cli
from lnpl import diagnostics as diagnostics_module
from lnpl.diagnostics import CODES, HINTS, Diagnostic, to_records
from lnpl.diagnostics import extension_diagnostic_records

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# A module that compiles with zero core diagnostics (mirrors
# test_extension_diagnostics.py's CLEAN_SRC), so the only diagnostics in the
# output are whatever the registered extension emits.
CLEAN_SRC = """
capability postgres
entity Payment
    field
        id UUID
        cardNumber Password
        amountCents Integer
service PaymentService
    policy
        retry 0
workflow Approval
    validate payment
    find payment
    when payment.amountCents <= 1000000
    update payment
"""


def _register_partial_hint():
    """One code declares a `hint`, the other does not."""
    return {
        "codes": {
            "with-hint": {"severity": "info", "description": "x",
                          "hint": "do the thing"},
            "no-hint": {"severity": "info", "description": "y"},
        },
        "check": lambda document, config: [
            {"code": "with-hint", "where": "w1", "subject": "s1",
             "message": "m1", "line": 1},
            {"code": "no-hint", "where": "w2", "subject": "s2",
             "message": "m2", "line": 2},
        ],
    }


class HintTableCompletenessTest(unittest.TestCase):
    """Normal: every core code has a hint entry — the LLM self-repair loop
    reads this field directly, so a gap here is a silent gap in the channel."""

    def test_hints_covers_exactly_the_18_closed_codes(self):
        self.assertEqual(set(HINTS), set(CODES))


class DiagnosticHintPropertyTest(unittest.TestCase):
    """Normal: `Diagnostic.hint` resolves through `HINTS`, derived like
    `severity`, not stored."""

    def test_hint_matches_the_hints_table_entry(self):
        d = Diagnostic(code="guard-orphaned-steps", where="line 10",
                        subject="guard-orphaned-steps", message="m")
        self.assertEqual(
            d.hint,
            "Repeat the guard line before this step, or wrap both in a "
            "`parallel` block.")


class ToRecordsHintKeyTest(unittest.TestCase):
    """Normal: `to_records()` carries a non-empty `hint` for a real,
    hinted diagnostic."""

    def test_to_records_includes_a_non_empty_hint(self):
        d = Diagnostic(code="unknown-verb", where="line 3", subject="foo",
                        message="m")
        records = to_records([d])
        self.assertEqual(len(records), 1)
        self.assertIn("hint", records[0])
        self.assertTrue(records[0]["hint"])


class ExtensionHintPassthroughTest(unittest.TestCase):
    """Boundary/contract: an extension's per-code `hint` passes through when
    declared, and resolves to `None` — never a `KeyError` — when it is not."""

    def setUp(self):
        self.workdir = os.path.join(REPO, ".claude", "tmp", "diag-hint")
        os.makedirs(self.workdir, exist_ok=True)
        self.src = os.path.join(self.workdir, "clean.lnpl")
        with open(self.src, "w", encoding="utf-8") as fh:
            fh.write(CLEAN_SRC)

    def test_declared_hint_passes_through_and_undeclared_resolves_to_none(self):
        with mock.patch.object(diagnostics_module, "load_extensions",
                                return_value={
                                    "hinttest": _register_partial_hint()}):
            doc = cli.compile_source([self.src])
            records = extension_diagnostic_records(doc)

        by_code = {r["code"]: r for r in records}
        self.assertEqual(by_code["hinttest/with-hint"]["hint"], "do the thing")
        self.assertIsNone(by_code["hinttest/no-hint"]["hint"])


if __name__ == "__main__":
    unittest.main()

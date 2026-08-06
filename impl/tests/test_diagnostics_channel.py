"""The diagnostics channel itself — record, accumulator, formatter (issues #36, #38).

These tests pin the *channel*, not its producers: what a `Diagnostic` accepts,
what order `Diagnostics` preserves, and what `format_lines` emits. The producers
(lowering, interpreter, CLI) have their own files.

The channel exists because #36 and #38 are the same failure mode — the platform
not telling you what it cannot do — and a second way of expressing a diagnostic
would reintroduce it. So the invariants asserted here are the contract every
producer leans on: a stable `code` callers branch on, a human `message` nobody
branches on, and one formatter.
"""

import unittest

from lnpl.diagnostics import (CODES, ENFORCEMENT, ENFORCEMENT_STATUSES,
                              SEVERITIES, Diagnostic, Diagnostics, format_lines)


def _diag(code="unknown-verb", severity="warning", where="line 1",
          subject="generate", message="m"):
    return Diagnostic(code=code, severity=severity, where=where,
                      subject=subject, message=message)


class TestDiagnosticRecord(unittest.TestCase):
    def test_fields_round_trip(self):
        d = _diag(code="declared-not-enforced", where="security.login",
                  subject="security jwt", message="declared but unenforced")
        self.assertEqual(d.code, "declared-not-enforced")
        self.assertEqual(d.severity, "warning")
        self.assertEqual(d.where, "security.login")
        self.assertEqual(d.subject, "security jwt")
        self.assertEqual(d.message, "declared but unenforced")

    def test_unknown_code_is_rejected(self):
        with self.assertRaises(ValueError) as cm:
            _diag(code="nope")
        self.assertIn("nope", str(cm.exception))

    def test_unknown_severity_is_rejected(self):
        with self.assertRaises(ValueError) as cm:
            _diag(severity="fatal")
        self.assertIn("fatal", str(cm.exception))

    def test_every_declared_code_is_constructible(self):
        # The closed set is the contract; a code in CODES that the record
        # rejects would be a contract nobody can honour.
        self.assertEqual(len(CODES), 5)
        for code in CODES:
            self.assertEqual(_diag(code=code).code, code)

    def test_record_is_frozen(self):
        d = _diag()
        with self.assertRaises(Exception):
            d.code = "declared-not-enforced"


class TestDiagnosticsAccumulator(unittest.TestCase):
    def test_add_preserves_insertion_order(self):
        diags = Diagnostics()
        diags.add(code="unknown-verb", severity="warning", where="line 3",
                  subject="generate", message="a")
        diags.add(code="declared-not-enforced", severity="warning",
                  where="security.login", subject="security jwt", message="b")
        diags.add(code="unknown-verb", severity="warning", where="line 5",
                  subject="audit", message="c")
        self.assertEqual([d.subject for d in diags.all()],
                         ["generate", "security jwt", "audit"])
        self.assertEqual([d.code for d in diags.all()],
                         ["unknown-verb", "declared-not-enforced", "unknown-verb"])

    def test_add_returns_the_record_it_stored(self):
        diags = Diagnostics()
        returned = diags.add(code="unknown-verb", severity="warning",
                             where="line 1", subject="generate", message="m")
        self.assertIs(returned, diags.all()[0])

    def test_by_code_selects_only_that_code(self):
        diags = Diagnostics()
        diags.add(code="unknown-verb", severity="warning", where="line 3",
                  subject="generate", message="a")
        diags.add(code="declared-not-enforced", severity="warning",
                  where="security.login", subject="security jwt", message="b")
        diags.add(code="unknown-verb", severity="warning", where="line 5",
                  subject="audit", message="c")
        picked = diags.by_code("unknown-verb")
        self.assertEqual(len(picked), 2)
        self.assertEqual([d.subject for d in picked], ["generate", "audit"])

    def test_by_code_rejects_a_code_outside_the_closed_set(self):
        diags = Diagnostics()
        with self.assertRaises(ValueError) as cm:
            diags.by_code("no-such-code")
        self.assertIn("no-such-code", str(cm.exception))

    def test_extend_accepts_another_accumulator(self):
        left, right = Diagnostics(), Diagnostics()
        left.add(code="unknown-verb", severity="warning", where="line 1",
                 subject="generate", message="a")
        right.add(code="authorization-not-verified", severity="warning",
                  where="wf.t.step.1.authz", subject="admin", message="b")
        left.extend(right)
        self.assertEqual([d.subject for d in left.all()], ["generate", "admin"])
        # extend must not mutate the source
        self.assertEqual(len(right), 1)

    def test_extend_accepts_a_plain_iterable_of_records(self):
        diags = Diagnostics()
        diags.extend([_diag(subject="generate"), _diag(subject="audit")])
        self.assertEqual([d.subject for d in diags.all()], ["generate", "audit"])

    def test_empty_accumulator(self):
        diags = Diagnostics()
        self.assertEqual(len(diags), 0)
        self.assertFalse(diags)
        self.assertEqual(diags.all(), [])
        self.assertEqual(format_lines(diags), [])

    def test_all_returns_a_copy(self):
        diags = Diagnostics()
        diags.add(code="unknown-verb", severity="warning", where="line 1",
                  subject="generate", message="m")
        snapshot = diags.all()
        snapshot.append(_diag(subject="audit"))
        self.assertEqual(len(diags), 1)
        self.assertEqual([d.subject for d in diags.all()], ["generate"])

    def test_duplicate_diagnostics_are_not_collapsed(self):
        # Two occurrences of the same unknown verb are two sites to fix, so the
        # channel reports both rather than deduping to one.
        diags = Diagnostics()
        diags.add(code="unknown-verb", severity="warning", where="line 3",
                  subject="generate", message="m")
        diags.add(code="unknown-verb", severity="warning", where="line 7",
                  subject="generate", message="m")
        self.assertEqual(len(diags), 2)
        self.assertEqual([d.where for d in diags.all()], ["line 3", "line 7"])


class TestFormatLines(unittest.TestCase):
    def test_no_diagnostics_produces_no_output_at_all(self):
        # Not even a summary line: a clean compile must stay silent.
        self.assertEqual(format_lines(Diagnostics()), [])
        self.assertEqual(format_lines([]), [])

    def test_one_diagnostic_produces_its_line_plus_a_summary(self):
        diags = Diagnostics()
        diags.add(code="unknown-verb", severity="warning", where="line 31",
                  subject="generate", message="runs as a descriptive no-op")
        lines = format_lines(diags)
        self.assertEqual(len(lines), 2)
        self.assertEqual(
            lines[0],
            "warning: unknown-verb [line 31] generate — runs as a descriptive no-op")
        self.assertEqual(lines[1], "1 warning(s), 0 error(s)")

    def test_summary_counts_each_severity(self):
        diags = Diagnostics()
        diags.add(code="unknown-verb", severity="warning", where="line 1",
                  subject="generate", message="m")
        diags.add(code="unknown-verb", severity="error", where="line 2",
                  subject="audit", message="m")
        diags.add(code="unknown-verb", severity="warning", where="line 3",
                  subject="return", message="m")
        lines = format_lines(diags)
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[-1], "2 warning(s), 1 error(s)")

    def test_accepts_a_plain_list_of_records(self):
        lines = format_lines([_diag(where="line 9", subject="audit",
                                    message="m")])
        self.assertEqual(lines[0], "warning: unknown-verb [line 9] audit — m")

    def test_severities_is_the_closed_set_the_summary_counts(self):
        self.assertEqual(SEVERITIES, ("warning", "error"))


class TestEnforcementMatrix(unittest.TestCase):
    """The matrix is the canonical source the docs table is checked against.

    Only its shape is pinned here; that it covers exactly the language's closed
    declaration sets, and that the document agrees with it, is the drift gate's
    job (test_enforcement_matrix.py).
    """

    def test_matrix_has_the_expected_row_count(self):
        # Asserted before any set comparison elsewhere, so a matrix that parsed
        # to zero rows cannot make a coverage check pass vacuously.
        self.assertEqual(len(ENFORCEMENT), 13)   # 12 + RFC-0016's event schedule

    def test_every_status_is_in_the_canonical_set(self):
        self.assertEqual(ENFORCEMENT_STATUSES,
                         ("enforced", "measured", "unenforced"))
        for key, (status, note) in ENFORCEMENT.items():
            self.assertIn(status, ENFORCEMENT_STATUSES, "bad status for %r" % (key,))

    def test_every_row_carries_a_non_empty_note(self):
        for key, (status, note) in ENFORCEMENT.items():
            self.assertTrue(note.strip(), "empty note for %r" % (key,))

    def test_keys_are_clause_name_pairs(self):
        for key in ENFORCEMENT:
            self.assertIsInstance(key, tuple)
            self.assertEqual(len(key), 2)
            # `event` joined the three service clauses in RFC-0016: a schedule
            # trigger is a declaration with an enforcement status like any other.
            self.assertIn(key[0], ("policy", "security", "performance", "event"))

    def test_the_four_declarations_issue_38_names_are_unenforced_or_measured(self):
        # The issue's own examples; if one of these ever reads "enforced" the
        # claim must be backed by real enforcement, not a table edit.
        self.assertEqual(ENFORCEMENT[("security", "jwt")][0], "unenforced")
        self.assertEqual(ENFORCEMENT[("security", "role")][0], "unenforced")
        self.assertEqual(ENFORCEMENT[("policy", "rollback")][0], "unenforced")
        self.assertEqual(ENFORCEMENT[("performance", "response")][0], "measured")

    def test_genuinely_enforced_declarations_are_marked_enforced(self):
        # The negative control for the row above: if everything were marked
        # unenforced the matrix would carry no information.
        self.assertEqual(ENFORCEMENT[("policy", "retry")][0], "enforced")
        self.assertEqual(ENFORCEMENT[("policy", "timeout")][0], "enforced")
        self.assertEqual(ENFORCEMENT[("performance", "cache")][0], "enforced")


if __name__ == "__main__":
    unittest.main()

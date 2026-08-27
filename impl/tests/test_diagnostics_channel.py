"""The diagnostics channel itself — record, accumulator, formatter (issues #36, #38, #52).

These tests pin the *channel*, not its producers: what a `Diagnostic` accepts,
what order `Diagnostics` preserves, and what `format_lines` emits. The producers
(lowering, interpreter, CLI) have their own files.

The channel exists because #36 and #38 are the same failure mode — the platform
not telling you what it cannot do — and a second way of expressing a diagnostic
would reintroduce it. So the invariants asserted here are the contract every
producer leans on: a stable `code` callers branch on, a human `message` nobody
branches on, and one formatter.

Issue #52 added the severity ladder. Its invariant lives here too: severity is
*derived* from the code, so a producer cannot grade the same fact two ways in
two places, and `--strict` has something real to select on.
"""

import unittest

from lnpl.diagnostics import (CODES, ENFORCEMENT, ENFORCEMENT_STATUSES,
                              SEVERITIES, SEVERITY_OF, Diagnostic, Diagnostics,
                              format_lines)


def _diag(code="unknown-verb", where="line 1", subject="generate", message="m"):
    return Diagnostic(code=code, where=where, subject=subject, message=message)


class TestSeverityLadder(unittest.TestCase):
    """#52: the grade axis. Severity is a fact of the code, not a call-site argument."""

    def test_severities_is_an_ordered_three_rung_ladder(self):
        # Tuple order *is* the ranking — the gate compares by index, so a
        # reordering here silently reverses every threshold comparison.
        self.assertEqual(SEVERITIES, ("info", "warning", "error"))
        self.assertLess(SEVERITIES.index("info"), SEVERITIES.index("warning"))
        self.assertLess(SEVERITIES.index("warning"), SEVERITIES.index("error"))

    def test_the_table_covers_exactly_the_closed_code_set(self):
        # Neither direction may drift: a code with no grade cannot be built,
        # and a grade for a retired code is a row nothing reaches.
        self.assertEqual(set(SEVERITY_OF), set(CODES))
        self.assertEqual(len(SEVERITY_OF), 16)

    def test_each_code_carries_its_assigned_grade(self):
        # Spelled out one by one rather than looped: this table *is* the
        # decision, so a change to any row must fail a named assertion.
        self.assertEqual(SEVERITY_OF["unknown-verb"], "warning")
        self.assertEqual(SEVERITY_OF["unknown-entity"], "warning")
        self.assertEqual(SEVERITY_OF["guard-skipped-steps"], "warning")
        self.assertEqual(SEVERITY_OF["guard-orphaned-steps"], "warning")
        self.assertEqual(SEVERITY_OF["event-source-mismatch"], "warning")
        self.assertEqual(SEVERITY_OF["derived-never-assigned"], "warning")
        self.assertEqual(SEVERITY_OF["declared-not-enforced"], "info")
        self.assertEqual(SEVERITY_OF["declared-measured-only"], "info")
        self.assertEqual(SEVERITY_OF["authorization-not-verified"], "warning")
        self.assertEqual(SEVERITY_OF["validation-sample-derived"], "info")
        self.assertEqual(SEVERITY_OF["event-source-orphaned"], "info")
        self.assertEqual(SEVERITY_OF["declared-not-bound"], "info")
        self.assertEqual(SEVERITY_OF["stored-row-shape-mismatch"], "warning")

    def test_every_grade_is_a_rung_of_the_ladder(self):
        for code, severity in SEVERITY_OF.items():
            self.assertIn(severity, SEVERITIES, "bad grade for %r" % code)

    def test_the_error_rung_is_reserved_and_reaches_nothing_today(self):
        """`--strict=error` currently gates on nothing, and that is deliberate.

        Severity is derived, so no producer and no test can fabricate an
        error-grade record. Whoever first maps a code to `error` lands here and
        has to decide what `--strict=error` then means before the suite goes
        green again.
        """
        self.assertNotIn("error", SEVERITY_OF.values())

    def test_the_two_grades_in_use_both_have_members(self):
        # The negative control for the row above: if the table collapsed to one
        # grade the ladder would carry no information and the gate could not
        # discriminate — exactly the #52 defect, in which all five read "warning".
        self.assertIn("info", SEVERITY_OF.values())
        self.assertIn("warning", SEVERITY_OF.values())


class TestDiagnosticRecord(unittest.TestCase):
    def test_fields_round_trip(self):
        d = _diag(code="declared-not-enforced", where="security.login",
                  subject="security jwt", message="declared but unenforced")
        self.assertEqual(d.code, "declared-not-enforced")
        self.assertEqual(d.severity, "info")
        self.assertEqual(d.where, "security.login")
        self.assertEqual(d.subject, "security jwt")
        self.assertEqual(d.message, "declared but unenforced")

    def test_severity_is_derived_from_the_code(self):
        self.assertEqual(_diag(code="unknown-verb").severity, "warning")
        self.assertEqual(_diag(code="declared-measured-only").severity, "info")

    def test_severity_cannot_be_supplied_by_the_caller(self):
        # The whole point of #52's table: a record cannot disagree with it, so
        # there is no argument through which a call site could grade a fact.
        with self.assertRaises(TypeError):
            Diagnostic(code="unknown-verb", severity="error", where="line 1",
                       subject="generate", message="m")

    def test_unknown_code_is_rejected(self):
        with self.assertRaises(ValueError) as cm:
            _diag(code="nope")
        self.assertIn("nope", str(cm.exception))

    def test_every_declared_code_is_constructible_and_graded(self):
        # The closed set is the contract; a code in CODES that the record
        # rejects would be a contract nobody can honour.
        self.assertEqual(len(CODES), 16)
        for code in CODES:
            self.assertEqual(_diag(code=code).code, code)
            self.assertEqual(_diag(code=code).severity, SEVERITY_OF[code])

    def test_record_is_frozen(self):
        d = _diag()
        with self.assertRaises(Exception):
            d.code = "declared-not-enforced"


class TestDiagnosticsAccumulator(unittest.TestCase):
    def test_add_preserves_insertion_order(self):
        diags = Diagnostics()
        diags.add(code="unknown-verb", where="line 3",
                  subject="generate", message="a")
        diags.add(code="declared-not-enforced",
                  where="security.login", subject="security jwt", message="b")
        diags.add(code="unknown-verb", where="line 5",
                  subject="audit", message="c")
        self.assertEqual([d.subject for d in diags.all()],
                         ["generate", "security jwt", "audit"])
        self.assertEqual([d.code for d in diags.all()],
                         ["unknown-verb", "declared-not-enforced", "unknown-verb"])

    def test_add_grades_the_record_from_the_table(self):
        diags = Diagnostics()
        diags.add(code="declared-not-enforced", where="event.daily.rollup",
                  subject="event schedule", message="m")
        diags.add(code="unknown-verb", where="line 5", subject="audit", message="m")
        self.assertEqual([d.severity for d in diags.all()], ["info", "warning"])

    def test_add_is_keyword_only(self):
        # A bare `*` in the signature: a stale positional call fails at the call
        # site instead of binding a grade string into `where`.
        diags = Diagnostics()
        with self.assertRaises(TypeError):
            diags.add("unknown-verb", "line 1", "generate", "m")

    def test_add_rejects_a_severity_argument(self):
        diags = Diagnostics()
        with self.assertRaises(TypeError):
            diags.add(code="unknown-verb", severity="warning", where="line 1",
                      subject="generate", message="m")

    def test_add_returns_the_record_it_stored(self):
        diags = Diagnostics()
        returned = diags.add(code="unknown-verb",
                             where="line 1", subject="generate", message="m")
        self.assertIs(returned, diags.all()[0])

    def test_by_code_selects_only_that_code(self):
        diags = Diagnostics()
        diags.add(code="unknown-verb", where="line 3",
                  subject="generate", message="a")
        diags.add(code="declared-not-enforced",
                  where="security.login", subject="security jwt", message="b")
        diags.add(code="unknown-verb", where="line 5",
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
        left.add(code="unknown-verb", where="line 1",
                 subject="generate", message="a")
        right.add(code="authorization-not-verified",
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
        diags.add(code="unknown-verb", where="line 1",
                  subject="generate", message="m")
        snapshot = diags.all()
        snapshot.append(_diag(subject="audit"))
        self.assertEqual(len(diags), 1)
        self.assertEqual([d.subject for d in diags.all()], ["generate"])

    def test_duplicate_diagnostics_are_not_collapsed(self):
        # Two occurrences of the same unknown verb are two sites to fix, so the
        # channel reports both rather than deduping to one.
        diags = Diagnostics()
        diags.add(code="unknown-verb", where="line 3",
                  subject="generate", message="m")
        diags.add(code="unknown-verb", where="line 7",
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
        diags.add(code="unknown-verb", where="line 31",
                  subject="generate", message="runs as a descriptive no-op")
        lines = format_lines(diags)
        self.assertEqual(len(lines), 2)
        self.assertEqual(
            lines[0],
            "warning: unknown-verb [line 31] generate — runs as a descriptive no-op")
        self.assertEqual(lines[1], "0 info, 1 warning(s), 0 error(s)")

    def test_the_line_prefix_is_the_derived_grade(self):
        # An info diagnostic must not print as "warning:" — the prefix is how a
        # reader tells "you wrote a typo" from "the platform does not do this".
        lines = format_lines([_diag(code="declared-not-enforced",
                                    where="event.daily.rollup",
                                    subject="event schedule",
                                    message="declared but unenforced")])
        self.assertEqual(
            lines[0],
            "info: declared-not-enforced [event.daily.rollup] event schedule "
            "— declared but unenforced")

    def test_summary_counts_each_grade_present(self):
        diags = Diagnostics()
        diags.add(code="unknown-verb", where="line 1",
                  subject="generate", message="m")
        diags.add(code="declared-not-enforced", where="security.login",
                  subject="security jwt", message="m")
        diags.add(code="unknown-verb", where="line 3",
                  subject="return", message="m")
        lines = format_lines(diags)
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[-1], "1 info, 2 warning(s), 0 error(s)")

    def test_accepts_a_plain_list_of_records(self):
        lines = format_lines([_diag(where="line 9", subject="audit",
                                    message="m")])
        self.assertEqual(lines[0], "warning: unknown-verb [line 9] audit — m")


class TestEnforcementMatrix(unittest.TestCase):
    """The matrix is the canonical source the docs table is checked against.

    Only its shape is pinned here; that it covers exactly the language's closed
    declaration sets, and that the document agrees with it, is the drift gate's
    job (test_enforcement_matrix.py).
    """

    def test_matrix_has_the_expected_row_count(self):
        # Asserted before any set comparison elsewhere, so a matrix that parsed
        # to zero rows cannot make a coverage check pass vacuously.
        self.assertEqual(len(ENFORCEMENT), 12)   # 11 + RFC-0016's event schedule; issue #127 removed security.encrypt

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
        # `policy rollback` was the fourth example at #38's writing; issue
        # #79/RFC-0032 backed it with real enforcement (the execution
        # boundary), so it now lives in the enforced test below instead.
        # `security role` was the second example; issue #119's service-level
        # gate (403 on mismatch/absence) backed it too, same move.
        self.assertEqual(ENFORCEMENT[("security", "jwt")][0], "unenforced")
        self.assertEqual(ENFORCEMENT[("performance", "response")][0], "measured")

    def test_genuinely_enforced_declarations_are_marked_enforced(self):
        # The negative control for the row above: if everything were marked
        # unenforced the matrix would carry no information.
        self.assertEqual(ENFORCEMENT[("policy", "retry")][0], "enforced")
        self.assertEqual(ENFORCEMENT[("policy", "timeout")][0], "enforced")
        self.assertEqual(ENFORCEMENT[("policy", "rollback")][0], "enforced")
        self.assertEqual(ENFORCEMENT[("performance", "cache")][0], "enforced")
        self.assertEqual(ENFORCEMENT[("security", "role")][0], "enforced")


if __name__ == "__main__":
    unittest.main()

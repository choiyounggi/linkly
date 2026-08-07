"""`docs/ENFORCEMENT-MATRIX.md` may not drift away from the code (issue #38).

The document is the human-readable copy; `diagnostics.ENFORCEMENT` and
`lower.VERB_LEXICON` are canonical. A doc that quietly says "enforced" about
something nobody enforces is worse than no doc, so the two are compared here.

Five named checks, each owning one property, each with its own negative control
that mutates only what that check owns:

    (1) matrix completeness  — ENFORCEMENT covers exactly the language's closed
                               declaration sets
    (2) document coverage    — the §B table holds exactly ENFORCEMENT's rows
    (3) document validity    — each §B row's status and code cell match the code
    (4) verb cross-reference — the §A table matches VERB_LEXICON, and the three
                               verbs the golden uses are still outside it
    (5) diagnostic severity  — each §C row's severity cell matches SEVERITY_OF

Coverage and validity are deliberately separate: a set-equality check on row
names is blind to cell contents, so a table can reach full coverage while a cell
holds a swapped value. Each negative control below asserts BOTH that the real
document passes and that the mutant fails, because a check that has only ever
been observed failing has not been shown to discriminate.
"""

import os
import re
import unittest

from lnpl.diagnostics import (CODES, ENFORCEMENT, ENFORCEMENT_STATUSES,
                              SEVERITY_OF)
from lnpl.lexer import EVENT_TRIGGERS
from lnpl.lower import (PERF_METRICS, POLICY_NAMES, SECURITY_MECHANISMS,
                        VERB_LEXICON)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOC = os.path.join(REPO, "docs", "ENFORCEMENT-MATRIX.md")

HEADING_A = "## A. 스텝 동사 → 도출 Effect"
HEADING_B = "## B. 서비스 선언 → 집행 상태"
HEADING_C = "## C. 진단 코드"

NO_DIAGNOSTIC = "—"  # the sentinel an `enforced` row carries in the code column

DELIMITER_RE = re.compile(r"^[\s:-]+$")


class AnchorMissing(AssertionError):
    """The heading or table a check keys on could not be located.

    Raised rather than returning "nothing to check": a check that reports
    success when its anchor disappears stops guarding the moment somebody
    rewords a heading.
    """


def read_doc():
    with open(DOC, encoding="utf-8") as fh:
        return fh.read()


def section(markdown, heading):
    """The text from `heading` up to the next `## ` heading."""
    lines = markdown.splitlines()
    try:
        start = lines.index(heading)
    except ValueError:
        raise AnchorMissing("no section titled %r in the document" % heading)
    for offset, line in enumerate(lines[start + 1:], start=start + 1):
        if line.startswith("## "):
            return "\n".join(lines[start:offset])
    return "\n".join(lines[start:])


def split_cells(row):
    """GFM row -> cells, splitting on unescaped pipes and unescaping each cell.

    `.strip("|")` would remove a *run* of pipes and corrupt a cell ending in an
    escaped one, so the outer delimiters come off with anchored patterns.
    """
    row = re.sub(r"(?<!\\)\|$", "", re.sub(r"^\|", "", row.strip()))
    return [c.replace(r"\|", "|").strip() for c in re.split(r"(?<!\\)\|", row)]


def first_table_rows(body):
    """The first *contiguous* run of table lines.

    A section may hold more than one table — §A carries the lexicon table and
    then a smaller one for the verbs outside it — so collecting every line that
    starts with a pipe would silently merge them, and the second table's header
    would read as a data row.
    """
    rows, started = [], False
    for line in body.splitlines():
        if line.strip().startswith("|"):
            started = True
            rows.append(line)
        elif started:
            break
    return rows


def parse_table(markdown, heading, columns):
    """Body rows of the first table under `heading`, as lists of cells."""
    body = section(markdown, heading)
    rows = first_table_rows(body)
    if not rows:
        raise AnchorMissing("no table under %r" % heading)
    header = split_cells(rows[0])
    if len(header) != columns:
        raise AnchorMissing("table under %r has %d columns, expected %d"
                            % (heading, len(header), columns))
    out = []
    for row in rows[1:]:
        cells = split_cells(row)
        if all(DELIMITER_RE.match(c or "-") for c in cells):
            continue  # the |---|---| delimiter row
        if len(cells) != columns:
            # A short row would silently read as empty cells under GFM.
            raise AnchorMissing("row %r under %r has %d cells, expected %d"
                                % (row, heading, len(cells), columns))
        out.append(cells)
    if not out:
        raise AnchorMissing("table under %r has no body rows" % heading)
    return out


# ---- the four checks, as pure functions over text so a mutant can be fed in ----

def matrix_completeness_errors(enforcement_keys, policy, security, perf,
                               triggers=EVENT_TRIGGERS):
    """(1) Does the matrix cover exactly the language's closed sets?

    RFC-0016 added a fourth set: the event-source kinds that carry an
    enforcement status. It is a parameter with a default rather than a hard
    reference so the negative controls below can mutate it like the others.
    """
    expected = ({("policy", n) for n in policy}
                | {("security", n) for n in security}
                | {("performance", n) for n in perf}
                | {("event", n) for n in triggers})
    missing = sorted(expected - set(enforcement_keys))
    extra = sorted(set(enforcement_keys) - expected)
    errors = []
    if missing:
        errors.append("matrix is missing %r" % (missing,))
    if extra:
        errors.append("matrix has entries the language does not declare: %r" % (extra,))
    return errors


def table_b_rows(markdown):
    """§B as {(clause, name): (status, code)}."""
    rows = parse_table(markdown, HEADING_B, 5)
    return {(cells[0], cells[1]): (cells[2], cells[3]) for cells in rows}, len(rows)


def document_coverage_errors(markdown):
    """(2) Does §B hold exactly the matrix's rows? Cell values are check 3's job."""
    rows, count = table_b_rows(markdown)
    errors = []
    if count != len(rows):
        errors.append("§B has %d rows but only %d distinct (clause, name) keys"
                      % (count, len(rows)))
    missing = sorted(set(ENFORCEMENT) - set(rows))
    extra = sorted(set(rows) - set(ENFORCEMENT))
    if missing:
        errors.append("§B does not document %r" % (missing,))
    if extra:
        errors.append("§B documents rows absent from ENFORCEMENT: %r" % (extra,))
    return errors


def document_validity_errors(markdown):
    """(3) Does each §B cell hold the value the code says?"""
    rows, _ = table_b_rows(markdown)
    errors = []
    for key, (status, code) in sorted(rows.items()):
        if status not in ENFORCEMENT_STATUSES:
            errors.append("%r: status %r is not one of %r"
                          % (key, status, ENFORCEMENT_STATUSES))
            continue
        expected = ENFORCEMENT.get(key)
        if expected is None:
            continue  # a coverage problem, owned by check 2
        if status != expected[0]:
            errors.append("%r: document says %r, code says %r"
                          % (key, status, expected[0]))
        if status == "enforced":
            if code != NO_DIAGNOSTIC:
                errors.append("%r: an enforced row must carry %r, found %r"
                              % (key, NO_DIAGNOSTIC, code))
        elif code not in CODES:
            errors.append("%r: %r is not a declared diagnostic code" % (key, code))
    return errors


def diagnostic_severity_errors(markdown):
    """(5) Does §C's severity column hold the grade the code holds?

    The grade is decided by `diagnostics.SEVERITY_OF` alone (issue #52,
    RFC-0021's ladder); §C is a human-readable copy of it, exactly as §B is a
    copy of `ENFORCEMENT`.

    This check exists because the two drifted and nothing noticed: after the
    ladder landed, three codes had become `info` while the document still called
    every one of them a `warning`. The check that was here asserted the
    DOCUMENT'S OWN claim — that the severity column held only "warning" — so it
    stayed green on a document that contradicted the code. Comparing against
    `SEVERITY_OF` is what makes it a check rather than a restatement.
    """
    errors = []
    for cells in parse_table(markdown, HEADING_C, 4):
        code, documented = cells[0], cells[1]
        if code not in SEVERITY_OF:
            errors.append("%r: not a declared diagnostic code" % code)
        elif SEVERITY_OF[code] != documented:
            errors.append("%r: documented as %r, the code grades it %r"
                          % (code, documented, SEVERITY_OF[code]))
    return errors


def verb_reference_errors(markdown):
    """(4) Does §A match VERB_LEXICON, and are the golden's three verbs still out?"""
    rows = parse_table(markdown, HEADING_A, 3)
    documented = {cells[0]: cells[1] for cells in rows}
    errors = []
    if len(documented) != len(rows):
        errors.append("§A lists a verb more than once")
    missing = sorted(set(VERB_LEXICON) - set(documented))
    extra = sorted(set(documented) - set(VERB_LEXICON))
    if missing:
        errors.append("§A does not document %r" % (missing,))
    if extra:
        errors.append("§A documents verbs absent from VERB_LEXICON: %r" % (extra,))
    for verb, kind in sorted(documented.items()):
        if verb in VERB_LEXICON and kind != VERB_LEXICON[verb][0]:
            errors.append("%s: document says %r, lexicon says %r"
                          % (verb, kind, VERB_LEXICON[verb][0]))
    return errors


class TestMatrixCompleteness(unittest.TestCase):
    """Check 1 — the code table against the language's closed sets."""

    def test_the_closed_sets_are_the_size_this_check_assumes(self):
        # Asserted before any set comparison: a source list that parsed to zero
        # items would satisfy set equality against anything.
        self.assertEqual(len(POLICY_NAMES), 4)
        self.assertEqual(len(SECURITY_MECHANISMS), 3)
        self.assertEqual(len(PERF_METRICS), 5)
        self.assertEqual(len(EVENT_TRIGGERS), 1)
        self.assertEqual(len(ENFORCEMENT), 13)   # 12 + RFC-0016's schedule

    def test_enforcement_covers_exactly_the_closed_sets(self):
        self.assertEqual(
            matrix_completeness_errors(ENFORCEMENT, POLICY_NAMES,
                                       SECURITY_MECHANISMS, PERF_METRICS), [])

    def test_negative_control_a_declaration_absent_from_the_matrix_is_caught(self):
        mutated = dict(ENFORCEMENT)
        del mutated[("security", "role")]
        errors = matrix_completeness_errors(mutated, POLICY_NAMES,
                                            SECURITY_MECHANISMS, PERF_METRICS)
        self.assertTrue(errors, "check 1 did not notice a missing declaration")
        self.assertIn("role", str(errors))

    def test_negative_control_a_matrix_entry_the_language_lacks_is_caught(self):
        mutated = dict(ENFORCEMENT)
        mutated[("security", "mfa")] = ("unenforced", "invented")
        errors = matrix_completeness_errors(mutated, POLICY_NAMES,
                                            SECURITY_MECHANISMS, PERF_METRICS)
        self.assertTrue(errors, "check 1 did not notice an invented declaration")
        self.assertIn("mfa", str(errors))


class TestDocumentCoverage(unittest.TestCase):
    """Check 2 — every matrix row is documented. Says nothing about cell values."""

    def setUp(self):
        self.markdown = read_doc()

    def test_the_document_covers_every_matrix_row(self):
        self.assertEqual(document_coverage_errors(self.markdown), [])

    def test_negative_control_a_deleted_row_is_caught(self):
        mutant = self.markdown.replace(
            "| security | role | unenforced | declared-not-enforced | "
            "역할을 무엇과도 대조하지 않는다 |\n", "")
        self.assertNotEqual(mutant, self.markdown, "the mutation did not apply")
        errors = document_coverage_errors(mutant)
        self.assertTrue(errors, "check 2 did not notice a deleted row")
        self.assertIn("role", str(errors))

    def test_negative_control_a_deleted_row_leaves_validity_green(self):
        # Each mutation must redden exactly the check that owns it: the rows
        # that remain still carry correct values.
        mutant = self.markdown.replace(
            "| security | role | unenforced | declared-not-enforced | "
            "역할을 무엇과도 대조하지 않는다 |\n", "")
        self.assertEqual(document_validity_errors(mutant), [])


class TestDocumentValidity(unittest.TestCase):
    """Check 3 — each documented row holds the value the code holds."""

    def setUp(self):
        self.markdown = read_doc()

    def test_every_documented_status_matches_the_code(self):
        self.assertEqual(document_validity_errors(self.markdown), [])

    def test_negative_control_a_flipped_status_is_caught(self):
        # The defect this whole gate exists for: the document claiming that
        # something unenforced is enforced.
        mutant = self.markdown.replace(
            "| policy | rollback | unenforced | declared-not-enforced |",
            "| policy | rollback | enforced | declared-not-enforced |")
        self.assertNotEqual(mutant, self.markdown, "the mutation did not apply")
        errors = document_validity_errors(mutant)
        self.assertTrue(errors, "check 3 did not notice a flipped status")
        self.assertIn("rollback", str(errors))

    def test_negative_control_a_flipped_status_leaves_coverage_green(self):
        mutant = self.markdown.replace(
            "| policy | rollback | unenforced | declared-not-enforced |",
            "| policy | rollback | enforced | declared-not-enforced |")
        self.assertEqual(document_coverage_errors(mutant), [])

    def test_negative_control_an_unknown_status_word_is_caught(self):
        mutant = self.markdown.replace(
            "| security | jwt | unenforced | declared-not-enforced |",
            "| security | jwt | partially | declared-not-enforced |")
        self.assertNotEqual(mutant, self.markdown, "the mutation did not apply")
        errors = document_validity_errors(mutant)
        self.assertTrue(errors, "check 3 did not notice an invented status")
        self.assertIn("partially", str(errors))

    def test_negative_control_an_undeclared_diagnostic_code_is_caught(self):
        mutant = self.markdown.replace(
            "| security | jwt | unenforced | declared-not-enforced |",
            "| security | jwt | unenforced | declared-someday |")
        self.assertNotEqual(mutant, self.markdown, "the mutation did not apply")
        errors = document_validity_errors(mutant)
        self.assertTrue(errors, "check 3 did not notice an invented code")
        self.assertIn("declared-someday", str(errors))

    def test_negative_control_an_enforced_row_claiming_a_diagnostic_is_caught(self):
        mutant = self.markdown.replace(
            "| policy | retry | enforced | — |",
            "| policy | retry | enforced | declared-not-enforced |")
        self.assertNotEqual(mutant, self.markdown, "the mutation did not apply")
        errors = document_validity_errors(mutant)
        self.assertTrue(errors, "check 3 did not notice a bogus code on an "
                                "enforced row")


class TestVerbCrossReference(unittest.TestCase):
    """Check 4 — §A against VERB_LEXICON, plus the golden's three verbs."""

    def setUp(self):
        self.markdown = read_doc()

    def test_the_verb_table_matches_the_lexicon(self):
        # 16 through RFC-0014; `set` (RFC-0015) is the seventeenth.
        self.assertEqual(len(VERB_LEXICON), 17)
        self.assertEqual(verb_reference_errors(self.markdown), [])

    def test_the_three_golden_verbs_are_named_and_still_outside_the_lexicon(self):
        # A cross-reference, not a keyword check: if somebody adds `generate` to
        # VERB_LEXICON this reddens and forces the document to be rewritten.
        out_of_lexicon = section(self.markdown, HEADING_A)
        for verb in ("generate", "audit", "return"):
            self.assertIn(verb, out_of_lexicon,
                          "the document stopped naming %r" % verb)
            self.assertNotIn(verb, VERB_LEXICON,
                             "%r joined VERB_LEXICON; §A now lies" % verb)

    def test_the_policy_is_stated_in_both_polarities(self):
        # "not a compile error" and "a diagnostic is always emitted" are two
        # claims; a document keeping only the first would read as permission to
        # stay silent.
        body = section(self.markdown, HEADING_A)
        self.assertIn("컴파일 에러가 아니다", body)
        self.assertIn("`unknown-verb` 진단이 발생한다", body)

    def test_negative_control_a_wrong_effect_kind_is_caught(self):
        mutant = self.markdown.replace("| validate | Validation |",
                                       "| validate | CacheAccess |")
        self.assertNotEqual(mutant, self.markdown, "the mutation did not apply")
        errors = verb_reference_errors(mutant)
        self.assertTrue(errors, "check 4 did not notice a wrong effect kind")
        self.assertIn("validate", str(errors))

    def test_negative_control_a_dropped_verb_is_caught(self):
        mutant = self.markdown.replace(
            "| invalidate | CacheAccess | operation `invalidate` |\n", "")
        self.assertNotEqual(mutant, self.markdown, "the mutation did not apply")
        errors = verb_reference_errors(mutant)
        self.assertTrue(errors, "check 4 did not notice a dropped verb")
        self.assertIn("invalidate", str(errors))

    def test_negative_control_a_wrong_effect_kind_leaves_table_b_green(self):
        mutant = self.markdown.replace("| validate | Validation |",
                                       "| validate | CacheAccess |")
        self.assertEqual(document_coverage_errors(mutant), [])
        self.assertEqual(document_validity_errors(mutant), [])


class TestGateFailsClosed(unittest.TestCase):
    """A check whose anchor vanished must report failure, never success."""

    def setUp(self):
        self.markdown = read_doc()

    def test_a_renamed_section_b_heading_raises(self):
        mutant = self.markdown.replace(HEADING_B, "## B. 선언 상태 요약")
        self.assertNotEqual(mutant, self.markdown, "the mutation did not apply")
        with self.assertRaises(AnchorMissing):
            document_coverage_errors(mutant)

    def test_a_renamed_section_a_heading_raises(self):
        mutant = self.markdown.replace(HEADING_A, "## A. 동사표")
        self.assertNotEqual(mutant, self.markdown, "the mutation did not apply")
        with self.assertRaises(AnchorMissing):
            verb_reference_errors(mutant)

    def test_a_deleted_table_raises_rather_than_passing_vacuously(self):
        body = section(self.markdown, HEADING_B)
        mutant = self.markdown.replace(
            body, HEADING_B + "\n\n표는 나중에 채운다.\n")
        with self.assertRaises(AnchorMissing):
            document_coverage_errors(mutant)

    def test_a_short_row_raises_rather_than_reading_as_empty_cells(self):
        # GFM inserts empty cells for a short row, which would let a truncated
        # row pass as a documented one.
        #
        # The row is located by its (clause, name) key rather than quoted whole:
        # a copy of the full line here is a literal anchor into a prose cell,
        # and it goes stale the moment someone rewords the 근거 — at which point
        # the mutation stops applying and this control silently stops
        # controlling anything. Issue #25 reworded exactly this row.
        prefix = "| security | jwt |"
        row = next((line for line in self.markdown.splitlines()
                    if line.startswith(prefix)), None)
        self.assertIsNotNone(row, "the §B jwt row is gone")
        mutant = self.markdown.replace(row, prefix + " unenforced |")
        self.assertNotEqual(mutant, self.markdown, "the mutation did not apply")
        with self.assertRaises(AnchorMissing):
            document_coverage_errors(mutant)


class TestPathDependentEnforcement(unittest.TestCase):
    """A declaration enforced on one path and ignored on another must say so.

    `security jwt` is the case: issue #25 gave it a real verification path, but
    the diagnostic is emitted at compile time, which cannot know the backend.
    The status therefore describes the weakest path, and the reason has to name
    the path that does enforce it — otherwise the single status is simply false
    for one of the two.
    """

    def test_the_jwt_reason_names_the_path_that_enforces_it(self):
        _, reason = ENFORCEMENT[("security", "jwt")]

        self.assertIn("--jwt-secret-env", reason)
        self.assertIn("serve", reason)

    def test_the_jwt_reason_still_says_the_default_path_does_not(self):
        """Both halves, or the row reads as a promise the default cannot keep."""
        status, reason = ENFORCEMENT[("security", "jwt")]

        self.assertEqual("unenforced", status)
        self.assertIn("default", reason)

    def test_the_document_repeats_the_same_path(self):
        row = next(line for line in read_doc().splitlines()
                   if line.startswith("| security | jwt |"))

        self.assertIn("--jwt-secret-env", row)

    def test_rollback_still_reports_nothing_to_compensate(self):
        """A real store arrived in #25; a transaction boundary did not. This
        row must not drift toward `enforced` on the strength of the store."""
        status, reason = ENFORCEMENT[("policy", "rollback")]

        self.assertEqual("unenforced", status)
        self.assertIn("compensate", reason)


class TestDiagnosticCodeTable(unittest.TestCase):
    """§C documents the closed code set callers branch on."""

    def setUp(self):
        self.markdown = read_doc()

    def test_section_c_documents_every_code(self):
        rows = parse_table(self.markdown, HEADING_C, 4)
        documented = [cells[0] for cells in rows]
        self.assertEqual(len(documented), len(CODES))
        self.assertEqual(sorted(documented), sorted(CODES))

    def test_every_documented_severity_matches_the_code(self):
        # Replaces an assertion that every documented severity was "warning".
        # That was the document repeating itself: it could not fail on a grade
        # the code disagreed with, only on one the document spelled differently.
        self.assertEqual(diagnostic_severity_errors(self.markdown), [])

    def test_negative_control_a_flipped_severity_is_caught(self):
        mutant = self.markdown.replace(
            "| guard-skipped-steps | warning |",
            "| guard-skipped-steps | info |")
        self.assertNotEqual(mutant, self.markdown, "the mutation did not apply")
        errors = diagnostic_severity_errors(mutant)
        self.assertTrue(errors, "check 5 did not notice a flipped severity")
        self.assertIn("guard-skipped-steps", str(errors))

    def test_negative_control_a_flipped_severity_leaves_coverage_green(self):
        # Each mutation must redden exactly the check that owns it: the code set
        # §C documents is unchanged by a wrong grade.
        mutant = self.markdown.replace(
            "| guard-skipped-steps | warning |",
            "| guard-skipped-steps | info |")
        rows = parse_table(mutant, HEADING_C, 4)
        self.assertEqual(sorted(cells[0] for cells in rows), sorted(CODES))

    def test_negative_control_an_invented_severity_word_is_caught(self):
        # Boundary: a grade outside the ladder is not merely a mismatch.
        mutant = self.markdown.replace(
            "| unknown-verb | warning |", "| unknown-verb | critical |")
        self.assertNotEqual(mutant, self.markdown, "the mutation did not apply")
        errors = diagnostic_severity_errors(mutant)
        self.assertTrue(errors, "check 5 did not notice an invented grade")
        self.assertIn("critical", str(errors))

    def test_the_ladder_is_not_flat(self):
        # The regression that hid the drift for a whole wave: if every code
        # carried one grade, `--strict=<level>` would have nothing to select on
        # and a document claiming "all warning" would be accidentally right.
        documented = {cells[1] for cells in
                      parse_table(self.markdown, HEADING_C, 4)}
        self.assertGreater(len(documented), 1,
                           "§C must show more than one grade, or RFC-0021's "
                           "threshold has nothing to choose between")

    def test_the_runtime_code_is_documented_as_runtime(self):
        rows = {cells[0]: cells[3] for cells in
                parse_table(self.markdown, HEADING_C, 4)}
        self.assertIn("런타임", rows["authorization-not-verified"])
        self.assertIn("컴파일 타임", rows["unknown-verb"])


class TestCellSplitting(unittest.TestCase):
    """The parser itself, since every check above depends on it."""

    def test_a_plain_row_splits_to_its_cells(self):
        self.assertEqual(split_cells("| a | b | c |"), ["a", "b", "c"])

    def test_an_escaped_pipe_stays_inside_its_cell(self):
        # `split("|")` would report 4 cells here and the checks would misread
        # every column after it.
        self.assertEqual(split_cells(r"| a | create\|update | c |"),
                         ["a", "create|update", "c"])

    def test_a_trailing_escaped_pipe_survives(self):
        self.assertEqual(split_cells(r"| a | b\| |"), ["a", "b|"])

    def test_an_empty_cell_is_preserved(self):
        self.assertEqual(split_cells("| a |  | c |"), ["a", "", "c"])

    def test_a_missing_section_raises_anchor_missing(self):
        with self.assertRaises(AnchorMissing) as cm:
            section("# nothing here\n", HEADING_B)
        self.assertIn("B.", str(cm.exception))

    def test_only_the_first_table_of_a_section_is_read(self):
        # §A holds two tables. Merging them made the second table's header row
        # ("verb") read as a documented verb, which is how this was found.
        body = "\n".join(["| a | b |", "|---|---|", "| one | two |", "",
                          "prose in between", "",
                          "| c | d |", "|---|---|", "| three | four |"])
        self.assertEqual(first_table_rows(body),
                         ["| a | b |", "|---|---|", "| one | two |"])

    def test_the_verb_section_really_does_hold_two_tables(self):
        # Guards the test above from becoming vacuous if the document is ever
        # restructured into a single table.
        body = section(read_doc(), HEADING_A)
        all_rows = [l for l in body.splitlines() if l.strip().startswith("|")]
        self.assertGreater(len(all_rows), len(first_table_rows(body)))


if __name__ == "__main__":
    unittest.main()

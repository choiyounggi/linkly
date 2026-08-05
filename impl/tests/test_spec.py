"""`spec` blocks become a test-suite artifact, not IR nodes (RFC-0002 A.4-2)."""

import os
import unittest

from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.spec import SpecError, extract, run_manifest, _payload_from_given

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SRC = """
capability postgres
capability redis
entity User
    field
        id UUID
        email Email
        password Password
service LoginService
    policy
        retry 3
        timeout 3s
    performance
        response < 50ms
        cache 5m
workflow Login
    validate input
    authenticate
    cache user
    spec
        given
            valid account
        when
            login
        expect
            completed
            steps 3
            cache written
"""


def build(src=SRC):
    decls = parse(src)
    return lower(decls, "login").to_document(), extract(decls, "login")


class TestExtraction(unittest.TestCase):
    def test_spec_produces_a_case_but_no_ir_node(self):
        doc, manifest = build()
        self.assertEqual(len(manifest["cases"]), 1)
        self.assertNotIn("Spec", [n["kind"] for n in doc["nodes"]])

    def test_case_targets_the_derived_workflow_id(self):
        _doc, manifest = build()
        self.assertEqual(manifest["cases"][0]["workflow"], "wf.login")

    def test_workflow_without_a_spec_yields_no_case(self):
        src = SRC[: SRC.index("    spec")]
        _doc, manifest = build(src)
        self.assertEqual(manifest["cases"], [])

    def test_spec_without_expect_is_rejected(self):
        src = SRC[: SRC.index("        expect")]
        with self.assertRaises(SpecError) as ctx:
            build(src)
        self.assertIn("`expect` section", str(ctx.exception))

    def test_content_directly_under_spec_is_rejected(self):
        src = SRC.replace("    spec\n", "    spec\n        stray line\n")
        with self.assertRaises(SpecError) as ctx:
            build(src)
        self.assertIn("takes no content lines", str(ctx.exception))


class TestExecution(unittest.TestCase):
    def test_manifest_runs_and_every_expectation_passes(self):
        doc, manifest = build()
        passed, failed, _lines = run_manifest(manifest, doc)
        self.assertEqual(failed, 0)
        self.assertEqual(passed, 3)

    def test_a_wrong_expectation_fails(self):
        # The point of a spec is that it can be wrong: 3 steps, not 99.
        doc, manifest = build(SRC.replace("steps 3", "steps 99"))
        _passed, failed, lines = run_manifest(manifest, doc)
        self.assertEqual(failed, 1)
        self.assertTrue(any("steps=3 want=99" in l for l in lines))

    def test_unsupported_expectation_fails_rather_than_passing_silently(self):
        doc, manifest = build(SRC.replace("            cache written",
                                          "            vibes good"))
        _passed, failed, lines = run_manifest(manifest, doc)
        self.assertEqual(failed, 1)
        self.assertTrue(any("unsupported expectation" in l for l in lines))

    def test_empty_repository_fixture_drives_a_failure_expectation(self):
        src = SRC.replace("            valid account", "            empty repository")
        src = src.replace("            completed\n", "            failed\n")
        src = src.replace("            steps 3\n", "            attempts 4\n")
        src = src.replace("            cache written\n", "")
        doc, manifest = build(src)
        passed, failed, lines = run_manifest(manifest, doc)
        self.assertEqual(failed, 0, lines)
        self.assertEqual(passed, 2)


class TestGoldenSpec(unittest.TestCase):
    def test_the_committed_golden_spec_passes(self):
        with open(os.path.join(REPO, "examples", "login.lnpl"), encoding="utf-8") as fh:
            src = fh.read()
        decls = parse(src)
        doc = lower(decls, "login").to_document()
        manifest = extract(decls, "login")
        self.assertTrue(manifest["cases"], "golden lost its spec block")
        passed, failed, lines = run_manifest(manifest, doc)
        self.assertEqual(failed, 0, lines)
        self.assertGreaterEqual(passed, 4)


ENTITY = {"id": "entity.link", "name": "Link",
          "fields": [{"name": "slug", "type": "Text"},
                     {"name": "target", "type": "Text"}]}


class TestPayloadFromGiven(unittest.TestCase):
    """A `given` line the runner cannot interpret must be refused, not silently
    absorbed as a field assignment (issue #28)."""

    def test_unrecognized_given_is_rejected_not_absorbed(self):
        # Was silently stored as payload["frobnicate"] = "widgets".
        with self.assertRaises(SpecError):
            _payload_from_given(["frobnicate widgets"], ENTITY)

    def test_field_set_requires_a_declared_field(self):
        with self.assertRaises(SpecError):
            _payload_from_given(["bogus value"], ENTITY)

    def test_declared_field_is_set(self):
        payload, _stored = _payload_from_given(["slug abc123"], ENTITY)
        self.assertEqual(payload["slug"], "abc123")

    def test_no_field_requires_a_declared_field(self):
        # `no slog` (typo for slug) must error rather than no-op silently.
        with self.assertRaises(SpecError):
            _payload_from_given(["no slog"], ENTITY)

    def test_no_declared_field_drops_it(self):
        payload, _stored = _payload_from_given(["no slug"], ENTITY)
        self.assertNotIn("slug", payload)

    def test_valid_narrative_is_generic_not_login_specific(self):
        # `valid <anything>` is a narrative marker, not a field assignment.
        payload, _stored = _payload_from_given(["valid link"], ENTITY)
        self.assertNotIn("valid", payload)
        self.assertNotIn("link", payload)

    def test_valid_account_and_empty_repository_still_accepted(self):
        _payload_from_given(["valid account"], ENTITY)     # must not raise
        _payload_from_given(["empty repository"], ENTITY)  # must not raise


class TestGenericNarrativeSpecRuns(unittest.TestCase):
    def test_spec_with_generic_valid_narrative_runs(self):
        src = SRC.replace("            valid account", "            valid session")
        decls = parse(src)
        doc = lower(decls, "login").to_document()
        manifest = extract(decls, "login")
        passed, failed, lines = run_manifest(manifest, doc)
        self.assertEqual(failed, 0, lines)


# ---- issue #39: the expectation vocabulary ---------------------------------

SHOP = """
capability postgres
capability redis
entity Product
    field
        id UUID
        stock Integer
        name Text
entity Order
    field
        id UUID
        total Money
event OrderPlaced on Order create
service ShopService
    policy
        retry 0
        timeout 3s
    performance
        response < 50ms
        cache 5m
workflow Checkout
    find product
    when product.stock > 0
    create order
    emit orderPlaced
    spec
        given
%s
        when
            checkout
        expect
%s
"""


def run_shop(given, expect):
    """Build a one-case manifest from `given`/`expect` lines and run it."""
    src = SHOP % ("\n".join("            " + g for g in given),
                  "\n".join("            " + e for e in expect))
    decls = parse(src)
    doc = lower(decls, "shop").to_document()
    return run_manifest(extract(decls, "shop"), doc)


class TestResultExpectation(unittest.TestCase):
    """`result <ref> …` — issue #39's return-value assertion.

    It is deliberately the SAME grammar and the SAME resolver the guards use
    (RFC-0012): the expectation is parsed by `parse_condition` and evaluated
    against `result["bindings"]`. That is what makes "guards and expect share one
    scope" a fact about the code rather than a claim.
    """

    def test_a_true_qualified_expectation_passes(self):
        passed, failed, lines = run_shop(["valid product"],
                                         ["completed", "result product.stock > 0"])
        self.assertEqual(failed, 0, lines)
        self.assertEqual(passed, 2, lines)

    def test_a_false_qualified_expectation_fails(self):
        # Must FAIL, not pass silently — a spec that always passes is not a spec.
        passed, failed, lines = run_shop(["valid product"],
                                         ["result product.stock > 99"])
        self.assertEqual(failed, 1, lines)
        self.assertEqual(passed, 0, lines)

    def test_it_reads_the_stored_row_not_the_payload(self):
        # `stored` puts 0 in the row while the payload keeps the sample's 1.
        # Asserting BOTH forms in one case is the sharpest statement of the scope
        # rule: the qualified form sees 0, the bare form sees 1.
        passed, failed, lines = run_shop(
            ["valid product", "stored product stock 0"],
            ["result product.stock == 0", "result stock > 0"])
        self.assertEqual(failed, 0, lines)
        self.assertEqual(passed, 2, lines)

    def test_a_bare_expectation_reads_the_payload(self):
        passed, failed, lines = run_shop(["valid product", "stock 7"],
                                         ["result stock == 7"])
        self.assertEqual(failed, 0, lines)

    def test_presence_form_is_accepted(self):
        passed, failed, lines = run_shop(["valid product"],
                                         ["result product.name exists"])
        self.assertEqual(failed, 0, lines)

    # ---- boundary ----------------------------------------------------------
    def test_an_unresolvable_reference_is_missing_not_an_error(self):
        passed, failed, lines = run_shop(["valid product"],
                                         ["result product.nosuch missing"])
        self.assertEqual(failed, 0, lines)

    # ---- error -------------------------------------------------------------
    def test_an_unparseable_expectation_is_refused(self):
        with self.assertRaises(SpecError):
            run_shop(["valid product"], ["result product.stock exceeds budget"])


class TestEntityStateExpectation(unittest.TestCase):
    """`rows <Name> <N>` — issue #39's entity-state assertion.

    The key is `rows`, not `entity`: `entity` opens a declaration in LNPL
    (lexer KEYWORDS_TOP), so an expect line starting with it never reaches the
    expectation table at all.
    """

    def test_the_created_entity_has_one_row(self):
        passed, failed, lines = run_shop(["valid product"],
                                         ["rows Order 1"])
        self.assertEqual(failed, 0, lines)

    def test_a_wrong_row_count_fails(self):
        passed, failed, lines = run_shop(["valid product"],
                                         ["rows Order 5"])
        self.assertEqual(failed, 1, lines)

    def test_a_skipped_create_leaves_the_table_empty(self):
        # Boundary: zero rows. The guard closes on the stored row, so `create
        # order` never runs and Order stays empty.
        passed, failed, lines = run_shop(
            ["valid product", "stored product stock 0"], ["rows Order 0"])
        self.assertEqual(failed, 0, lines)

    def test_an_undeclared_entity_is_refused(self):
        with self.assertRaises(SpecError):
            run_shop(["valid product"], ["rows Widget 1"])


class TestEventExpectation(unittest.TestCase):
    """`emitted <Name> …` — issue #39's event-payload assertion.

    `emitted`, not `event`, for the same reason `rows` is not `entity`.
    """

    def test_an_emitted_event_is_observed(self):
        passed, failed, lines = run_shop(["valid product"],
                                         ["emitted OrderPlaced"])
        self.assertEqual(failed, 0, lines)

    def test_the_emission_count_is_assertable(self):
        passed, failed, lines = run_shop(["valid product"],
                                         ["emitted OrderPlaced count 1"])
        self.assertEqual(failed, 0, lines)

    def test_a_wrong_count_fails(self):
        passed, failed, lines = run_shop(["valid product"],
                                         ["emitted OrderPlaced count 3"])
        self.assertEqual(failed, 1, lines)

    def test_a_payload_field_is_assertable(self):
        passed, failed, lines = run_shop(["valid product"],
                                         ["emitted OrderPlaced payload stock exists"])
        self.assertEqual(failed, 0, lines)

    def test_a_field_absent_from_the_payload_is_missing(self):
        # Boundary: a field the emission does not carry.
        passed, failed, lines = run_shop(["valid product"],
                                         ["emitted OrderPlaced payload nosuch missing"])
        self.assertEqual(failed, 0, lines)

    def test_asserting_a_payload_field_with_no_emission_fails(self):
        # Boundary: the EMPTY outbox. `emit` is unguarded here, so drive the
        # empty case through a run that fails before reaching it.
        passed, failed, lines = run_shop(
            ["valid product", "empty repository"],
            ["emitted OrderPlaced payload stock exists"])
        self.assertEqual(
            failed, 1,
            "with nothing emitted there is no payload to satisfy the assertion; "
            "it must fail rather than pass vacuously. Report: %s" % lines)

    def test_an_undeclared_event_is_refused(self):
        with self.assertRaises(SpecError):
            run_shop(["valid product"], ["emitted NoSuchEvent"])

    def test_an_unknown_event_form_is_refused(self):
        with self.assertRaises(SpecError):
            run_shop(["valid product"], ["emitted OrderPlaced wobbled"])


class TestErrorExpectation(unittest.TestCase):
    """`error step|reason …` — issue #39's failure assertion."""

    def test_the_failing_step_is_assertable(self):
        passed, failed, lines = run_shop(["valid product", "empty repository"],
                                         ["failed", "error step find product"])
        self.assertEqual(failed, 0, lines)

    def test_the_failure_reason_is_assertable(self):
        passed, failed, lines = run_shop(["valid product", "empty repository"],
                                         ["error reason no row"])
        self.assertEqual(failed, 0, lines)

    def test_a_wrong_step_name_fails(self):
        passed, failed, lines = run_shop(["valid product", "empty repository"],
                                         ["error step create order"])
        self.assertEqual(failed, 1, lines)

    def test_asserting_an_error_on_a_successful_run_fails(self):
        # Boundary: nothing failed, so there is no reason. This must FAIL, which
        # is the whole difference between an assertion and a no-op.
        passed, failed, lines = run_shop(["valid product"],
                                         ["error reason anything"])
        self.assertEqual(failed, 1, lines)

    def test_an_unknown_error_form_is_refused(self):
        with self.assertRaises(SpecError):
            run_shop(["valid product"], ["error wobbled"])


class TestEffectsExpectation(unittest.TestCase):
    """`effects <N>` — the total observable effect count.

    This is the hook issue #36's follow-up needs: a step that derives no effect
    lowers the total, so a spec can state that the workflow actually did
    something. Per-step assertion is deliberately left to that follow-up.
    """

    def test_the_total_effect_count_is_assertable(self):
        # find(Repository) + create(Repository) + emit(EventEmit) = 3
        passed, failed, lines = run_shop(["valid product"], ["effects 3"])
        self.assertEqual(failed, 0, lines)

    def test_a_wrong_total_fails(self):
        passed, failed, lines = run_shop(["valid product"], ["effects 99"])
        self.assertEqual(failed, 1, lines)

    def test_a_closed_guard_lowers_the_total(self):
        # Boundary: the guarded create never runs, so its effect is not counted.
        passed, failed, lines = run_shop(
            ["valid product", "stored product stock 0"], ["effects 2"])
        self.assertEqual(failed, 0, lines)


class TestStoredGiven(unittest.TestCase):
    """`given stored <entity> <field> <value>` — prior repository state.

    Without it a spec cannot express a row that differs from the input, and
    `default_rows` seeds the row AS the payload — so issue #37's behaviour would
    be inexpressible in the language its own spec blocks are written in.
    """

    def test_it_seeds_the_row_without_touching_the_payload(self):
        passed, failed, lines = run_shop(
            ["valid product", "stored product stock 0"],
            ["result product.stock == 0", "result stock > 0"])
        self.assertEqual(failed, 0, lines)

    def test_an_undeclared_entity_is_refused(self):
        with self.assertRaises(SpecError):
            run_shop(["valid product", "stored widget stock 0"], ["completed"])

    def test_an_undeclared_field_is_refused(self):
        with self.assertRaises(SpecError):
            run_shop(["valid product", "stored product nosuch 0"], ["completed"])

    def test_combining_it_with_an_empty_repository_is_refused(self):
        # Boundary: the two `given`s contradict — there is no row to store into
        # an empty store. Refuse rather than silently letting one win.
        with self.assertRaises(SpecError):
            run_shop(["empty repository", "stored product stock 0"], ["completed"])

    def test_a_malformed_stored_line_is_refused(self):
        with self.assertRaises(SpecError):
            run_shop(["stored product"], ["completed"])


class TestExistingVocabularyIsUnchanged(unittest.TestCase):
    """Control: issue #39 EXTENDS the vocabulary; it must not move any of it."""

    def test_the_seven_original_expectations_are_still_registered(self):
        from lnpl.spec import EXPECTATIONS
        for key in ("completed", "failed", "steps", "slo", "duration", "cache",
                    "attempts"):
            self.assertIn(key, EXPECTATIONS)

    def test_the_committed_login_spec_still_passes(self):
        doc, manifest = build()
        passed, failed, lines = run_manifest(manifest, doc)
        self.assertEqual(failed, 0, lines)
        self.assertEqual(passed, 3, lines)


# ---- issue #39 acceptance item 2: a no-op step (#36) must fail its spec ------

# Same shape as SHOP, with one extra step whose verb is outside VERB_LEXICON.
# `ponder` derives no Effect, so the step runs and does nothing — issue #36's
# no-op. `expect steps N` still counts it, which is exactly the blindness issue
# #39 names.
SHOP_WITH_NOOP = SHOP.replace(
    "    find product\n",
    "    find product\n    ponder existence\n")


def run_shop_src(src, given, expect):
    src = src % ("\n".join("            " + g for g in given),
                 "\n".join("            " + e for e in expect))
    decls = parse(src)
    doc = lower(decls, "shop").to_document()
    return run_manifest(extract(decls, "shop"), doc)


class TestNoOpStepFailsTheSpec(unittest.TestCase):
    """`effects complete` — every step that ran performed at least one Effect.

    Issue #39's second acceptance item. A verb outside `VERB_LEXICON` derives no
    Effect (issue #36), so the step executes and does nothing; `expect steps N`
    counts it just the same, and the spec stays GREEN while the implementation is
    missing. This assertion is the one that goes RED.

    It is deliberately OPT-IN rather than an automatic failure for every module
    carrying an `unknown-verb` diagnostic: the golden `examples/login.lnpl`
    declares three descriptive steps (`generate token`, `audit login`,
    `return token`) and `diagnostics.py` records that as a legitimate way to
    write LNPL. Failing every such spec would reject the golden scenario.
    """

    # ---- the negative control, both directions -----------------------------
    def test_a_no_op_step_fails_the_assertion(self):
        passed, failed, lines = run_shop_src(SHOP_WITH_NOOP, ["valid product"],
                                             ["effects complete"])
        self.assertEqual(failed, 1,
                         "a step whose verb derives no Effect must fail "
                         "`effects complete`. Report: %s" % lines)
        self.assertEqual(passed, 0, lines)

    def test_the_same_assertion_passes_when_every_step_is_effective(self):
        # The other direction. Without this the check could simply always fail.
        passed, failed, lines = run_shop_src(SHOP, ["valid product"],
                                             ["effects complete"])
        self.assertEqual(failed, 0,
                         "every step in the clean workflow derives an Effect, so "
                         "the assertion must hold. Report: %s" % lines)
        self.assertEqual(passed, 1, lines)

    def test_the_failure_names_the_offending_step(self):
        _passed, _failed, lines = run_shop_src(SHOP_WITH_NOOP, ["valid product"],
                                               ["effects complete"])
        self.assertTrue(any("ponder existence" in l for l in lines),
                        "the report must name the step that did nothing, or the "
                        "author cannot find it. Report: %s" % lines)

    # ---- the blindness this closes -----------------------------------------
    def test_step_count_alone_stays_green_on_the_same_workflow(self):
        # The point of issue #39: `steps` counts the no-op step and passes, so a
        # spec asserting only the count is GREEN while a step does nothing. Both
        # assertions run against the SAME source here, so the contrast is the
        # measurement, not two different fixtures.
        passed, failed, lines = run_shop_src(SHOP_WITH_NOOP, ["valid product"],
                                             ["steps 4"])
        self.assertEqual(failed, 0,
                         "`steps 4` counts the no-op step and passes — this is "
                         "the blindness `effects complete` closes, and it must "
                         "still be demonstrable. Report: %s" % lines)
        self.assertEqual(passed, 1, lines)

    # ---- boundary cases ----------------------------------------------------
    def test_a_workflow_whose_every_step_is_a_no_op_fails(self):
        src = SHOP.replace("    find product\n    when product.stock > 0\n"
                           "    create order\n    emit orderPlaced\n",
                           "    ponder existence\n    muse quietly\n")
        passed, failed, lines = run_shop_src(src, ["valid product"],
                                             ["effects complete"])
        self.assertEqual(failed, 1, lines)
        self.assertEqual(passed, 0, lines)

    def test_a_skipped_no_op_step_does_not_fail_it(self):
        # Boundary: the no-op sits under a guard that closes, so it never runs.
        # `effects complete` is an assertion about what THIS RUN did; a step that
        # did not execute did nothing wrong. The compile-time `unknown-verb`
        # diagnostic is what reports it in that case.
        src = SHOP.replace("    create order\n",
                           "    create order\n    when product.stock > 99\n"
                           "    ponder existence\n")
        passed, failed, lines = run_shop_src(src, ["valid product"],
                                             ["effects complete"])
        self.assertEqual(failed, 0,
                         "the guarded no-op never ran, so there is no executed "
                         "step without an Effect. Report: %s" % lines)

    # ---- error case --------------------------------------------------------
    def test_an_unknown_effects_form_is_refused(self):
        with self.assertRaises(SpecError):
            run_shop_src(SHOP, ["valid product"], ["effects wobbled"])

    def test_the_numeric_form_still_works(self):
        # Control: extending `effects` must not move `effects <N>`.
        passed, failed, lines = run_shop_src(SHOP, ["valid product"], ["effects 3"])
        self.assertEqual(failed, 0, lines)


class TestSpecCommandSurfacesDiagnostics(unittest.TestCase):
    """`lnpl spec` reports compile diagnostics like `compile` and `run` do.

    PR #41 made `unknown-verb` visible, but `cmd_spec` dropped the accumulator on
    the floor — so the one command whose whole job is verification was the one
    that stayed silent about a step doing nothing.
    """

    def test_the_unknown_verb_diagnostic_reaches_stderr(self):
        import contextlib
        import io
        import os
        import tempfile
        from lnpl import cli
        src = SHOP_WITH_NOOP % ("            valid product", "            completed")
        tmpdir = os.path.join(REPO, ".claude", "tmp")
        os.makedirs(tmpdir, exist_ok=True)
        fd, path = tempfile.mkstemp(dir=tmpdir, suffix=".lnpl")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(src)
        self.addCleanup(os.remove, path)
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(err):
            cli.main(["spec", path, "--run"])
        self.assertIn("unknown-verb", err.getvalue(),
                      "`lnpl spec` must report that a step derives no Effect; "
                      "got %r" % err.getvalue())
        self.assertIn("ponder", err.getvalue())

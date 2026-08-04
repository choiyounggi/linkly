"""Lowering rules: R2 (id derivation) and R1 (closed verb lexicon)."""

import json
import os
import unittest

from lnpl.lower import LowerError, derive_id, lower, split_pascal
from lnpl.parser import parse
from lnpl.refinements import PRESETS
from lnpl.types import SEMANTIC_TYPES

GOLDEN = """
capability postgres
entity User
    field
        id UUID
        email Email
service LoginService
    policy
        retry 3
workflow Login
    validate input
    authenticate
    cache user
"""


def ir(source):
    return lower(parse(source), "t").to_document()


def by_id(doc):
    return {n["id"]: n for n in doc["nodes"]}


class TestIdDerivation(unittest.TestCase):
    """R2 — one uniform rule, including the redundant-kind-word strip."""

    def test_pascal_split(self):
        self.assertEqual(split_pascal("UserCreated"), ["user", "created"])
        self.assertEqual(split_pascal("postgres"), ["postgres"])

    def test_strips_segment_that_repeats_the_kind(self):
        # `LoginService` as a Service: the trailing `service` is redundant.
        self.assertEqual(derive_id("LoginService", "Service"), "svc.login")

    def test_keeps_segment_that_only_looks_like_a_suffix(self):
        # `created` is not the word "event", so nothing is stripped.
        self.assertEqual(derive_id("UserCreated", "Event"), "event.user.created")

    def test_single_segment_names(self):
        self.assertEqual(derive_id("User", "Entity"), "entity.user")
        self.assertEqual(derive_id("Login", "Workflow"), "wf.login")
        self.assertEqual(derive_id("postgres", "Capability"), "cap.postgres")

    def test_boundary_single_segment_equal_to_kind_word_is_kept(self):
        # Stripping would leave an empty id, so the rule requires >1 segment.
        self.assertEqual(derive_id("Service", "Service"), "svc.service")

    def test_unknown_kind_is_an_error(self):
        with self.assertRaises(LowerError):
            derive_id("Whatever", "NoSuchKind")


class TestVerbLexicon(unittest.TestCase):
    """R1 — a step's verb selects an Effect by lookup, never by inference."""

    def setUp(self):
        self.doc = ir(GOLDEN)
        self.nodes = by_id(self.doc)

    def test_validate_derives_a_validation(self):
        node = self.nodes["wf.login.step.1.check"]
        self.assertEqual(node["kind"], "Validation")
        self.assertEqual(node["target"], "entity.user")
        self.assertEqual(node["rule"], "semantic-types")

    def test_object_naming_a_field_narrows_the_target(self):
        doc = ir(GOLDEN.replace("validate input", "validate email"))
        node = by_id(doc)["wf.login.step.1.check"]
        self.assertEqual(node["target"], "entity.user.email")
        self.assertEqual(node["rule"], "Email")

    def test_authenticate_derives_a_read(self):
        node = self.nodes["wf.login.step.2.repo"]
        self.assertEqual(node["kind"], "RepositoryCall")
        self.assertEqual(node["operation"], "read")
        self.assertEqual(node["entity"], "entity.user")

    def test_cache_derives_a_set_with_a_key_template(self):
        node = self.nodes["wf.login.step.3.cache"]
        self.assertEqual(node["kind"], "CacheAccess")
        self.assertEqual(node["operation"], "set")
        self.assertEqual(node["key"], "user:{id}")

    def test_verb_outside_the_lexicon_derives_nothing(self):
        doc = ir(GOLDEN + "    ponder existence\n")
        step = by_id(doc)["wf.login.step.4"]
        self.assertEqual(step["name"], "ponder existence")
        self.assertNotIn("children", step)   # silence, never a guess

    def test_emit_references_the_event_named_as_its_object(self):
        doc = ir(GOLDEN + "    emit userCreated\n")
        node = by_id(doc)["wf.login.step.4.emit"]
        self.assertEqual(node["kind"], "EventEmit")
        self.assertEqual(node["event"], "event.user.created")

    def test_emit_without_an_object_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            ir(GOLDEN + "    emit\n")
        self.assertIn("needs the event to emit", str(ctx.exception))


class TestControlFlow(unittest.TestCase):
    """Guards and blocks: one Guard kind with a mode, not three kinds."""

    SRC = """
capability postgres
entity User
    field
        id UUID
        email Email
service Dash
workflow LoadDashboard
    when profile missing
    load user
    repeat 3
    cache user
    parallel
        read user
        find user
    merge
    pipeline Enrich
        validate email
"""

    def setUp(self):
        self.nodes = by_id(ir(self.SRC))

    def test_when_guard_becomes_one_guard_node(self):
        node = self.nodes["wf.load.dashboard.guard.1"]
        self.assertEqual(node["kind"], "Guard")
        self.assertEqual(node["mode"], "when")
        self.assertEqual(node["condition"], "profile missing")
        self.assertEqual(len(node["children"]), 1)

    def test_repeat_guard_carries_a_count_not_a_condition(self):
        node = self.nodes["wf.load.dashboard.guard.2"]
        self.assertEqual(node["mode"], "repeat")
        self.assertEqual(node["count"], 3)
        self.assertNotIn("condition", node)

    def test_parallel_becomes_concurrency(self):
        node = self.nodes["wf.load.dashboard.parallel.1"]
        self.assertEqual(node["kind"], "Concurrency")
        self.assertEqual(node["mode"], "parallel")
        self.assertEqual(len(node["children"]), 2)

    def test_named_pipeline_keeps_its_name(self):
        self.assertEqual(self.nodes["wf.load.dashboard.pipeline.1"]["name"], "Enrich")

    def test_unnamed_pipeline_gets_a_derived_name(self):
        src = self.SRC.replace("pipeline Enrich", "pipeline")
        node = by_id(ir(src))["wf.load.dashboard.pipeline.1"]
        self.assertEqual(node["name"], "pipeline.1")

    def test_empty_block_is_rejected(self):
        src = self.SRC.replace("    pipeline Enrich\n        validate email\n",
                               "    pipeline Enrich\n")
        with self.assertRaises(LowerError) as ctx:
            ir(src)
        self.assertIn("no steps", str(ctx.exception))


class TestMultiEntity(unittest.TestCase):
    """A module may declare several entities; the step object selects one."""

    TWO = """
capability postgres
entity User
    field
        id UUID
        email Email
entity Order
    field
        id UUID
        total Money
service S
workflow W
    load user
    find order
"""

    def test_both_entities_are_emitted(self):
        nodes = by_id(ir(self.TWO))
        self.assertEqual(nodes["entity.user"]["name"], "User")
        self.assertEqual(nodes["entity.order"]["name"], "Order")

    def test_the_step_object_selects_the_entity(self):
        nodes = by_id(ir(self.TWO))
        self.assertEqual(nodes["wf.w.step.1.repo"]["entity"], "entity.user")
        self.assertEqual(nodes["wf.w.step.2.repo"]["entity"], "entity.order")

    def test_an_ambiguous_step_lists_the_candidates_instead_of_picking_one(self):
        src = self.TWO.replace("    load user\n    find order\n", "    load\n")
        with self.assertRaises(LowerError) as ctx:
            ir(src)
        msg = str(ctx.exception)
        self.assertIn("does not say which entity", msg)
        self.assertIn("Order", msg)
        self.assertIn("User", msg)

    def test_a_single_entity_module_still_allows_an_omitted_object(self):
        # The golden scenario relies on this: `authenticate` has no object.
        node = by_id(ir(GOLDEN))["wf.login.step.2.repo"]
        self.assertEqual(node["entity"], "entity.user")

    def test_two_entities_deriving_the_same_id_is_refused(self):
        src = self.TWO.replace("entity Order", "entity UserEntity")
        # `UserEntity` as an Entity strips the redundant `entity` -> entity.user
        with self.assertRaises(LowerError) as ctx:
            ir(src)
        self.assertIn("derive the same id", str(ctx.exception))


class TestCapabilityAttribution(unittest.TestCase):
    """Formerly the provisional R3 — now a rule with a defined multi-service case."""

    TWO = """
capability postgres
capability redis
entity User
    field
        id UUID
service Alpha
    database
        postgres
workflow A
    load user
service Beta
    database
        redis
workflow B
    load user
"""

    def test_single_service_module_takes_every_capability(self):
        node = by_id(ir(GOLDEN))["svc.login"]
        self.assertEqual(node["requires"], ["cap.postgres"])

    def test_database_clause_attributes_per_service(self):
        nodes = by_id(ir(self.TWO))
        self.assertEqual(nodes["svc.alpha"]["requires"], ["cap.postgres"])
        self.assertEqual(nodes["svc.beta"]["requires"], ["cap.redis"])

    def test_multi_service_without_a_database_clause_is_an_error_not_a_guess(self):
        src = self.TWO.replace("    database\n        redis\n", "")
        with self.assertRaises(LowerError) as ctx:
            ir(src)
        self.assertIn("would be a guess", str(ctx.exception))

    def test_database_clause_naming_an_undeclared_capability_is_rejected(self):
        src = self.TWO.replace("        redis", "        kafka")
        with self.assertRaises(LowerError) as ctx:
            ir(src)
        self.assertIn("not a declared capability", str(ctx.exception))


class TestStructure(unittest.TestCase):
    def test_flat_table_children_are_id_strings(self):
        doc = ir(GOLDEN)
        for node in doc["nodes"]:
            for child in node.get("children", []):
                self.assertIsInstance(child, str)

    def test_workflow_attaches_to_the_nearest_preceding_service(self):
        doc = ir(GOLDEN)
        self.assertEqual(by_id(doc)["svc.login"]["children"], ["wf.login"])

    def test_capabilities_land_in_requires(self):
        doc = ir(GOLDEN)
        self.assertEqual(by_id(doc)["svc.login"]["requires"], ["cap.postgres"])

    def test_dangling_event_source_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir(GOLDEN + "event Ghost on Missing create\n")
        self.assertIn("dangling", str(ctx.exception))

    def test_flag_performance_metric_serializes_without_a_value(self):
        src = GOLDEN.replace("    policy\n        retry 3",
                             "    performance\n        prefetch")
        node = by_id(ir(src))["perf.login"]
        self.assertEqual(node["budgets"], [{"metric": "prefetch"}])

    def test_flag_performance_metric_rejects_a_value(self):
        src = GOLDEN.replace("    policy\n        retry 3",
                             "    performance\n        prefetch 5m")
        with self.assertRaises(LowerError) as ctx:
            ir(src)
        self.assertIn("takes no value", str(ctx.exception))

    def test_a_goal_clause_becomes_business_rules_owned_by_the_service(self):
        src = GOLDEN.replace("    policy\n        retry 3",
                             "    goal\n        authenticate user\n        cache profile")
        nodes = by_id(ir(src))
        rules = [n for n in nodes.values() if n["kind"] == "BusinessRule"]
        self.assertEqual([r["statement"] for r in rules],
                         ["authenticate user", "cache profile"])
        # and they are owned, not orphaned
        for rule in rules:
            self.assertIn(rule["id"], nodes["svc.login"]["children"])


# A user-declared refinement. It cannot be called `Slug`: A.6.4 reserves the
# three preset names, so `Code` carries the same facets under its own name.
CODE_DECL = """
refine Code of Text
    pattern ^[a-z0-9-]{1,64}$
    maxLength 64
entity Link
    field
        code Code
"""


def refinements_of(doc):
    return [n for n in doc["nodes"] if n["kind"] == "Refinement"]


class TestRefinementLowering(unittest.TestCase):
    """`refine` -> a Refinement node (RFC-0001 A.6.2), and the invariants A.7
    assigns to the compile pass rather than to the schema."""

    def test_declared_refinement_becomes_a_node(self):
        node = by_id(ir(CODE_DECL))["refine.code"]
        self.assertEqual(node, {
            "kind": "Refinement",
            "id": "refine.code",
            "name": "Code",
            "base": "Text",
            "facets": {"pattern": "^[a-z0-9-]{1,64}$", "maxLength": 64},
        })

    def test_refinement_has_no_children_and_is_an_entry_node(self):
        doc = ir(CODE_DECL)
        node = by_id(doc)["refine.code"]
        self.assertNotIn("children", node)
        for other in doc["nodes"]:
            self.assertNotIn("refine.code", other.get("children", []))

    def test_refinement_id_comes_from_derive_id(self):
        # A.6.5: no new id rule — the existing R2 derivation plus the `refine`
        # kind prefix. These three are the ids A.6.4 fixes for the presets.
        self.assertEqual(derive_id("Url", "Refinement"), "refine.url")
        self.assertEqual(derive_id("Slug", "Refinement"), "refine.slug")
        self.assertEqual(derive_id("PositiveInteger", "Refinement"),
                         "refine.positive.integer")

    def test_refinement_is_emitted_before_the_entity(self):
        kinds = [n["kind"] for n in ir(CODE_DECL)["nodes"]]
        self.assertLess(kinds.index("Refinement"), kinds.index("Entity"))

    def test_declared_but_unused_refinement_is_still_emitted(self):
        # A declaration is a node whether or not a field names it (RFC-0002
        # A.2: one declaration = one node). Only presets are emit-on-use.
        src = ("refine Short of Text\n    maxLength 8\n"
               "entity Link\n    field\n        slug Text\n")
        self.assertEqual([n["id"] for n in refinements_of(ir(src))],
                         ["refine.short"])

    def test_two_refinements_keep_declaration_order(self):
        src = ("refine Bee of Text\n    maxLength 2\n"
               "refine Ant of Text\n    maxLength 3\n"
               "entity Link\n    field\n        slug Text\n")
        self.assertEqual([n["name"] for n in refinements_of(ir(src))],
                         ["Bee", "Ant"])

    def test_validate_step_carries_the_refinement_name_as_the_rule(self):
        """`validate <field>` copies the field's TYPE NAME into Validation.rule.

        With a refinement-typed field that string becomes the refinement's name,
        with no code change in the effect derivation. This is the exact handoff
        point where Wave 3's interpreter has to apply the refinement instead of a
        base type, so it is asserted directly: a later refactor that severed it
        would otherwise pass silently.
        """
        src = ("refine Code of Text\n    maxLength 8\n"
               "entity Link\n    field\n        code Code\n"
               "workflow Shorten\n    validate code\n")
        checks = [n for n in ir(src)["nodes"] if n["kind"] == "Validation"]
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]["rule"], "Code")
        self.assertEqual(checks[0]["target"], "entity.link.code")

    # ---- A.7 ⓑ: facets has at least one entry ----

    def test_refine_with_no_facets_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Code of Text\nentity Link\n    field\n        code Code\n")
        self.assertIn("declares no facets", str(ctx.exception))

    # ---- A.7 ⓒ: enum has at least one item ----

    def test_bare_enum_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Kind of Text\n    enum\nentity L\n    field\n        k Kind\n")
        self.assertIn("at least one value", str(ctx.exception))

    # ---- A.7 ⓓ: the facet applies to the base's category ----

    def test_maxlength_on_boolean_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Flag of Boolean\n    maxLength 3\n"
               "entity L\n    field\n        f Flag\n")
        self.assertIn("does not apply to base", str(ctx.exception))
        self.assertIn("Boolean", str(ctx.exception))

    def test_min_on_text_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Short of Text\n    min 1\n"
               "entity L\n    field\n        s Short\n")
        self.assertIn("does not apply to base", str(ctx.exception))

    def test_pattern_on_a_composite_base_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Blob of Json\n    pattern ^x$\n"
               "entity L\n    field\n        b Blob\n")
        self.assertIn("does not apply to base", str(ctx.exception))

    def test_maxlength_on_integer_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Big of Integer\n    maxLength 3\n"
               "entity L\n    field\n        b Big\n")
        self.assertIn("does not apply to base", str(ctx.exception))

    # ---- A.7 ⓔ: the name is unique against bases, presets, and each other ----

    def test_name_colliding_with_a_base_type_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Text of Text\n    maxLength 8\n"
               "entity L\n    field\n        s Text\n")
        self.assertIn("already a semantic type", str(ctx.exception))

    def test_name_colliding_with_a_preset_is_rejected(self):
        # A.6.4: the three preset names are reserved and cannot be redeclared,
        # even to the identical content. This is what keeps A.6.1's resolution
        # order deterministic.
        for name in ("Url", "Slug", "PositiveInteger"):
            with self.assertRaises(LowerError) as ctx:
                ir("refine %s of Text\n    maxLength 8\n"
                   "entity L\n    field\n        s Text\n" % name)
            self.assertIn("already a semantic type", str(ctx.exception))

    def test_duplicate_refinement_name_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Short of Text\n    maxLength 8\n"
               "refine Short of Text\n    maxLength 9\n"
               "entity L\n    field\n        s Short\n")
        self.assertIn("already a semantic type", str(ctx.exception))

    # ---- base must be one of the 18: no refinement of a refinement ----

    def test_refining_a_refinement_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Slugish of Text\n    maxLength 8\n"
               "refine Deeper of Slugish\n    maxLength 4\n"
               "entity L\n    field\n        s Deeper\n")
        self.assertIn("not one of the 18 semantic types", str(ctx.exception))

    def test_refining_a_preset_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Tighter of Slug\n    maxLength 4\n"
               "entity L\n    field\n        s Tighter\n")
        self.assertIn("not one of the 18 semantic types", str(ctx.exception))

    def test_unknown_base_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Slugish of Bogus\n    maxLength 8\n"
               "entity L\n    field\n        s Slugish\n")
        self.assertIn("not one of the 18 semantic types", str(ctx.exception))

    # ---- the emitted name must satisfy the schema's PascalCase pattern ----

    def test_lowercase_refinement_name_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine slug of Text\n    maxLength 8\n"
               "entity L\n    field\n        s Text\n")
        self.assertIn("must be PascalCase", str(ctx.exception))

    # ---- facet vocabulary and duplicates ----

    def test_unknown_facet_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Short of Text\n    maxLenght 8\n"
               "entity L\n    field\n        s Short\n")
        self.assertIn("unknown facet", str(ctx.exception))

    def test_repeating_a_facet_is_rejected(self):
        # The object key is unique, so a second value would silently win.
        with self.assertRaises(LowerError) as ctx:
            ir("refine Short of Text\n    maxLength 8\n    maxLength 9\n"
               "entity L\n    field\n        s Short\n")
        self.assertIn("given twice", str(ctx.exception))

    # ---- facet value forms (RFC-0002 Integer / Number / EnumValue) ----

    def test_facet_line_without_a_value_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Short of Text\n    pattern\n"
               "entity L\n    field\n        s Short\n")
        self.assertIn("needs exactly one value", str(ctx.exception))

    def test_facet_line_with_two_values_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Short of Text\n    maxLength 8 9\n"
               "entity L\n    field\n        s Short\n")
        self.assertIn("needs exactly one value", str(ctx.exception))

    def test_enum_with_exactly_one_item(self):
        src = ("refine Kind of Text\n    enum draft\n"
               "entity L\n    field\n        k Kind\n")
        self.assertEqual(refinements_of(ir(src))[0]["facets"], {"enum": ["draft"]})

    def test_minlength_zero_is_accepted(self):
        src = ("refine Short of Text\n    minLength 0\n"
               "entity L\n    field\n        s Short\n")
        value = refinements_of(ir(src))[0]["facets"]["minLength"]
        self.assertEqual(value, 0)
        self.assertIsInstance(value, int)

    def test_negative_length_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Short of Text\n    minLength -1\n"
               "entity L\n    field\n        s Short\n")
        self.assertIn("non-negative integer", str(ctx.exception))

    def test_non_numeric_length_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Short of Text\n    maxLength eight\n"
               "entity L\n    field\n        s Short\n")
        self.assertIn("non-negative integer", str(ctx.exception))

    def test_min_accepts_a_negative_and_a_decimal(self):
        src = ("refine Temp of Decimal\n    min -40.5\n    max 100\n"
               "entity L\n    field\n        t Temp\n")
        facets = refinements_of(ir(src))[0]["facets"]
        self.assertEqual(facets, {"min": -40.5, "max": 100})
        self.assertIsInstance(facets["min"], float)

    def test_integer_valued_min_stays_an_int(self):
        # The preset PositiveInteger's canonical fragment writes `1`; a float
        # would serialize as 1.0 and stop matching the RFC's node.
        src = ("refine Positive of Integer\n    min 1\n"
               "entity L\n    field\n        n Positive\n")
        value = refinements_of(ir(src))[0]["facets"]["min"]
        self.assertEqual(value, 1)
        self.assertIsInstance(value, int)

    def test_non_numeric_min_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Positive of Integer\n    min one\n"
               "entity L\n    field\n        n Positive\n")
        self.assertIn("needs a number", str(ctx.exception))

    def test_enum_mixes_words_and_numbers(self):
        src = ("refine Kind of Text\n    enum draft 1 2.5\n"
               "entity L\n    field\n        k Kind\n")
        values = refinements_of(ir(src))[0]["facets"]["enum"]
        self.assertEqual(values, ["draft", 1, 2.5])
        self.assertEqual([type(v) for v in values], [str, int, float])

    def test_enum_rejects_a_pascal_value(self):
        # EnumValue ::= Word | Number, and Word starts lowercase.
        with self.assertRaises(LowerError) as ctx:
            ir("refine Kind of Text\n    enum Draft\n"
               "entity L\n    field\n        k Kind\n")
        self.assertIn("not a valid enum value", str(ctx.exception))

    # ---- pattern: compiled, per the orchestrator's Correction 1 ----

    def test_pattern_with_a_space_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Short of Text\n    pattern ^a b$\n"
               "entity L\n    field\n        s Short\n")
        self.assertIn("needs exactly one value", str(ctx.exception))

    def test_pattern_starting_with_a_hash_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Short of Text\n    pattern #abc\n"
               "entity L\n    field\n        s Short\n")
        self.assertIn("needs exactly one value", str(ctx.exception))

    def test_pattern_truncated_into_a_broken_regex_is_rejected(self):
        # `^a[b#c]$` loses everything from `#`, leaving `^a[b` — an unterminated
        # character set. Compiling the value is what catches it.
        with self.assertRaises(LowerError) as ctx:
            ir("refine Short of Text\n    pattern ^a[b#c]$\n"
               "entity L\n    field\n        s Short\n")
        self.assertIn("not a valid regex", str(ctx.exception))

    def test_uncompilable_pattern_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Short of Text\n    pattern ^a(b$\n"
               "entity L\n    field\n        s Short\n")
        self.assertIn("not a valid regex", str(ctx.exception))

    def test_KNOWN_LIMITATION_mid_regex_hash_silently_truncates(self):
        """`^a#b$` lowers to the pattern `^a`, with no diagnostic.

        The lexer drops from `#` to end of line, leaving a well-formed 2-token
        facet line whose value has been cut short. `^a` compiles, so the
        re.compile() gate above cannot catch it. Turning this into an error
        would require amending frozen Wave 1 lexer behavior, which is out of
        scope. Asserted and named here so the next reader sees a known
        limitation rather than an accident; reported to the orchestrator for an
        RFC-0002 Open Question decision.
        """
        src = ("refine Short of Text\n    pattern ^a#b$\n"
               "entity L\n    field\n        s Short\n")
        self.assertEqual(refinements_of(ir(src))[0]["facets"]["pattern"], "^a")


class TestTypeResolution(unittest.TestCase):
    """A.6.1 name resolution and A.6.4 emit-on-use.

    `fields[].type` holds a NAME, resolved against the 18 base names and then the
    Refinements of the same document. A built-in preset a field names joins that
    document as a node, so a consumer never has to read the compiler's table.
    """

    def test_preset_is_emitted_when_a_field_uses_it(self):
        src = "entity Link\n    field\n        slug Slug\n        target Url\n"
        nodes = by_id(ir(src))
        self.assertEqual(nodes["refine.slug"], {
            "kind": "Refinement", "id": "refine.slug", "name": "Slug",
            "base": "Text",
            "facets": {"pattern": "^[a-z0-9-]{1,64}$", "maxLength": 64}})
        self.assertEqual(nodes["refine.url"], {
            "kind": "Refinement", "id": "refine.url", "name": "Url",
            "base": "Text",
            "facets": {"pattern": r"^https?://[^\s]+$", "maxLength": 2048}})
        # the field keeps the NAME, not the node id
        self.assertEqual(nodes["entity.link"]["fields"],
                         [{"name": "slug", "type": "Slug"},
                          {"name": "target", "type": "Url"}])

    def test_positive_integer_preset_emits_its_rfc_value(self):
        src = "entity Link\n    field\n        hits PositiveInteger\n"
        node = by_id(ir(src))["refine.positive.integer"]
        self.assertEqual(node, {
            "kind": "Refinement", "id": "refine.positive.integer",
            "name": "PositiveInteger", "base": "Integer", "facets": {"min": 1}})
        self.assertIsInstance(node["facets"]["min"], int)

    def test_unused_preset_is_absent(self):
        src = "entity Link\n    field\n        slug Slug\n"
        ids = [n["id"] for n in refinements_of(ir(src))]
        self.assertEqual(ids, ["refine.slug"])
        self.assertNotIn("refine.url", ids)
        self.assertNotIn("refine.positive.integer", ids)

    def test_no_refinements_means_no_refinement_nodes(self):
        src = "entity Link\n    field\n        slug Text\n"
        self.assertEqual(refinements_of(ir(src)), [])

    def test_declared_and_preset_nodes_are_structurally_identical(self):
        """A preset is not privileged (A.6.4): both go through one builder.

        The two cannot share a name — A.6.4 reserves `Slug` — so identity is
        asserted modulo the identifying pair, which is exactly what "the same
        node the user would have written" means.
        """
        declared = refinements_of(ir(
            "refine Code of Text\n"
            "    pattern ^[a-z0-9-]{1,64}$\n"
            "    maxLength 64\n"
            "entity L\n    field\n        c Code\n"))[0]
        from_preset = refinements_of(ir(
            "entity L\n    field\n        slug Slug\n"))[0]

        self.assertEqual(set(declared), set(from_preset))
        self.assertEqual({k: v for k, v in declared.items()
                          if k not in ("id", "name")},
                         {k: v for k, v in from_preset.items()
                          if k not in ("id", "name")})
        # and the identifying pair is derived the same way for both
        self.assertEqual(declared["id"], derive_id(declared["name"], "Refinement"))
        self.assertEqual(from_preset["id"],
                         derive_id(from_preset["name"], "Refinement"))

    def test_preset_and_declared_refinements_coexist(self):
        src = ("refine Short of Text\n    maxLength 8\n"
               "entity Link\n    field\n        s Short\n        slug Slug\n")
        self.assertEqual([n["name"] for n in refinements_of(ir(src))],
                         ["Short", "Slug"])

    def test_preset_used_twice_is_emitted_once(self):
        src = ("entity Link\n    field\n        slug Slug\n"
               "entity Post\n    field\n        slug Slug\n")
        self.assertEqual([n["id"] for n in refinements_of(ir(src))],
                         ["refine.slug"])

    def test_preset_emission_follows_first_use_order(self):
        src = ("entity Link\n    field\n        target Url\n        slug Slug\n")
        self.assertEqual([n["name"] for n in refinements_of(ir(src))],
                         ["Url", "Slug"])

    # ---- A.7 ⓐ: every fields[].type resolves ----

    def test_unresolvable_field_type_is_rejected(self):
        # Before A.6.1 this was accepted silently, which is the defect A.7 ⓐ
        # names. It is an error for the first time here.
        with self.assertRaises(LowerError) as ctx:
            ir("entity Foo\n    field\n        bar Bogus\n")
        self.assertIn("RFC-0001 A.6.1", str(ctx.exception))
        self.assertIn("Bogus", str(ctx.exception))

    def test_field_type_with_a_typo_on_a_declared_name_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Code of Text\n    maxLength 8\n"
               "entity L\n    field\n        c Codee\n")
        self.assertIn("RFC-0001 A.6.1", str(ctx.exception))

    def test_field_type_with_a_typo_on_a_preset_name_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("entity L\n    field\n        s Slugg\n")
        self.assertIn("RFC-0001 A.6.1", str(ctx.exception))

    def test_base_type_field_still_resolves(self):
        src = "entity User\n    field\n        id UUID\n        email Email\n"
        self.assertEqual(by_id(ir(src))["entity.user"]["fields"],
                         [{"name": "id", "type": "UUID"},
                          {"name": "email", "type": "Email"}])

    def test_declared_refinement_resolves_a_field(self):
        src = ("refine Code of Text\n    maxLength 8\n"
               "entity L\n    field\n        c Code\n")
        self.assertEqual(by_id(ir(src))["entity.l"]["fields"],
                         [{"name": "c", "type": "Code"}])

    def test_refinement_declared_after_the_entity_still_resolves(self):
        # Resolution is document-scoped, not source-order-scoped (A.6.1 says
        # "the same IR document", not "declared earlier").
        src = ("entity L\n    field\n        c Code\n"
               "refine Code of Text\n    maxLength 8\n")
        self.assertEqual(by_id(ir(src))["entity.l"]["fields"],
                         [{"name": "c", "type": "Code"}])

    def test_validate_step_carries_a_preset_name_as_the_rule(self):
        # The Wave 3 handoff, for a preset rather than a declared refinement.
        src = ("entity Link\n    field\n        slug Slug\n"
               "workflow Shorten\n    validate slug\n")
        checks = [n for n in ir(src)["nodes"] if n["kind"] == "Validation"]
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]["rule"], "Slug")
        self.assertEqual(checks[0]["target"], "entity.link.slug")

    def test_emitted_preset_node_is_not_the_registry_object(self):
        # A consumer mutating the document must not corrupt the process-wide
        # preset table for every later compile in this interpreter.
        src = "entity Link\n    field\n        slug Slug\n"
        node = by_id(ir(src))["refine.slug"]
        node["facets"]["maxLength"] = 1
        node["facets"]["pattern"] = "clobbered"
        self.assertEqual(PRESETS["Slug"]["facets"],
                         {"pattern": "^[a-z0-9-]{1,64}$", "maxLength": 64})
        self.assertEqual(by_id(ir(src))["refine.slug"]["facets"],
                         {"pattern": "^[a-z0-9-]{1,64}$", "maxLength": 64})


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestNoRegressionForRefinementFreeModules(unittest.TestCase):
    """A module with no refinement must lower to exactly what it did before —
    no new nodes, no reordering."""

    def test_login_example_lowers_unchanged(self):
        with open(os.path.join(REPO_ROOT, "examples", "login.lnpl"),
                  encoding="utf-8") as fh:
            source = fh.read()
        with open(os.path.join(REPO_ROOT, "examples", "login.lir.json"),
                  encoding="utf-8") as fh:
            golden = json.load(fh)
        self.assertEqual(lower(parse(source), golden["module"]).to_document(),
                         golden)

    def test_refinement_free_module_emits_no_refinement_nodes(self):
        self.assertEqual(refinements_of(ir(GOLDEN)), [])


class TestEmittedIrValidatesAgainstTheFrozenSchema(unittest.TestCase):
    """What this pass emits must satisfy schemas/lir.schema.json (Wave 1, frozen)."""

    SOURCE = """
refine Code of Text
    maxLength 8
    minLength 1
entity Link
    field
        id UUID
        code Code
        slug Slug
        target Url
        hits PositiveInteger
"""

    def _document(self):
        return lower(parse(self.SOURCE), "refinement").to_document()

    def test_lowered_refinement_document_validates(self):
        import jsonschema
        with open(os.path.join(REPO_ROOT, "schemas", "lir.schema.json"),
                  encoding="utf-8") as fh:
            schema = json.load(fh)
        jsonschema.validate(self._document(), schema)

    def test_all_four_refinements_are_present(self):
        # one declared + three presets, so the document resolves every field
        # name without reading the compiler's built-in table (A.6.4).
        self.assertEqual([n["name"] for n in refinements_of(self._document())],
                         ["Code", "Slug", "Url", "PositiveInteger"])

    def test_each_refinement_node_has_exactly_the_required_fields(self):
        # The schema sets additionalProperties:false on nodeRefinement; pin the
        # exact key set here too so a stray field fails fast with a clear name.
        for node in refinements_of(self._document()):
            self.assertEqual(set(node), {"kind", "id", "name", "base", "facets"})

    def test_every_field_type_resolves_inside_the_document(self):
        doc = self._document()
        names = {n["name"] for n in refinements_of(doc)}
        entity = by_id(doc)["entity.link"]
        for field in entity["fields"]:
            self.assertTrue(field["type"] in SEMANTIC_TYPES or field["type"] in names,
                            "%r resolves to nothing in this document" % field["type"])


if __name__ == "__main__":
    unittest.main()

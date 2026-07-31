"""Lowering rules: R2 (id derivation) and R1 (closed verb lexicon)."""

import unittest

from lnpl.lower import LowerError, derive_id, lower, split_pascal
from lnpl.parser import parse

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


if __name__ == "__main__":
    unittest.main()

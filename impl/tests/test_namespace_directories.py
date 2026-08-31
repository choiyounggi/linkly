"""RFC-0033 — directory namespaces + `internal/` visibility (issue #146).

One rule per `impl/tests/test_namespace_directories.py` class, each named after
the RFC-0033 §Reference-level Specification subsection it tests. The byte-
identical guarantee (D4) compares against fixtures committed under
`impl/tests/lnpl_fixtures/rfc0033_byte_identical/`, generated from the
pre-RFC-0033 compiler (`3c1db72`) — see that directory's own generation note.
The scale-pressure regression fixtures (D5) reuse `scripts/gen_scale_corpus.py`
(issue #117) rather than re-deriving its domain/shared-noun corpus model.
"""

import importlib.util
import json
import os
import shutil
import tempfile
import unittest

from lnpl.lower import (LoaderError, LowerError, derive_id, load_sources,
                        lower)
from lnpl.openapi import _entity_for_target, generate as generate_openapi

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TMP_ROOT = os.path.join(REPO, ".claude", "tmp")
os.makedirs(TMP_ROOT, exist_ok=True)

FIXTURE_DIR = os.path.join(REPO, "impl", "tests", "lnpl_fixtures",
                           "rfc0033_byte_identical")
LINKHUB_SINGLE = os.path.join(REPO, "examples", "linkhub.lnpl")
CHECKOUT_SINGLE = os.path.join(REPO, "examples", "checkout.lnpl")
LINKHUB_SPLIT_DIR = os.path.join(REPO, "impl", "tests", "lnpl_fixtures", "linkhub")

GEN_PATH = os.path.join(REPO, "scripts", "gen_scale_corpus.py")
_spec = importlib.util.spec_from_file_location("gen_scale_corpus", GEN_PATH)
gen_scale_corpus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen_scale_corpus)


class _TmpDirCase(unittest.TestCase):
    """Common `.claude/tmp` scratch-directory scaffolding (repo policy —
    impl/tests/test_tmp_hygiene.py enforces `dir=TMP_ROOT` + cleanup)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="rfc0033-", dir=TMP_ROOT)
        self.addCleanup(shutil.rmtree, self.tmpdir, ignore_errors=True)

    def _write(self, relpath, content):
        full = os.path.join(self.tmpdir, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(content)
        return full


ORDER_ENTITY = "entity Order\n    field\n        id UUID\n        total Money\n"
FIND_ORDER_WF = "workflow FindOrder\n    find order\n"


class NamespaceDerivationTest(_TmpDirCase):
    """RFC-0033 §Reference-level "네임스페이스 유도"."""

    def test_files_directly_under_the_directory_get_no_namespace(self):
        self._write("a.lnpl", ORDER_ENTITY)
        decls = load_sources(self.tmpdir)
        self.assertEqual([d.namespace for d in decls], [None])
        self.assertEqual([d.internal for d in decls], [False])

    def test_mixed_files_and_subdirectories_ignores_the_subdirectory(self):
        self._write("a.lnpl", ORDER_ENTITY)
        self._write("billing/b.lnpl", "entity Item\n    field\n        id UUID\n")
        decls = load_sources(self.tmpdir)
        self.assertEqual(len(decls), 1)
        self.assertIsNone(decls[0].namespace)
        self.assertEqual(decls[0].name, "Order")

    def test_a_namespace_root_assigns_the_subdirectory_name(self):
        self._write("billing/order.lnpl", ORDER_ENTITY)
        self._write("shipping/order.lnpl",
                    "entity Order\n    field\n        id UUID\n        carrier Text\n")
        decls = load_sources(self.tmpdir)
        by_ns = {d.namespace: d for d in decls}
        self.assertEqual(set(by_ns), {"billing", "shipping"})
        self.assertFalse(any(d.internal for d in decls))

    def test_namespace_directories_are_visited_in_name_sorted_order(self):
        self._write("shipping/order.lnpl",
                    "entity Order\n    field\n        id UUID\n")
        self._write("billing/order.lnpl", ORDER_ENTITY)
        decls = load_sources(self.tmpdir)
        # RFC-0031's determinism rule, extended to namespace-dir traversal:
        # billing (b) sorts before shipping (s) regardless of write order.
        self.assertEqual(decls[0].namespace, "billing")
        self.assertEqual(decls[-1].namespace, "shipping")

    def test_internal_directory_inherits_the_parent_namespace_and_is_flagged(self):
        self._write("billing/order.lnpl", ORDER_ENTITY)
        self._write("billing/internal/ledger.lnpl",
                    "entity Ledger\n    field\n        id UUID\n")
        decls = load_sources(self.tmpdir)
        by_name = {d.name: d for d in decls}
        self.assertEqual(by_name["Order"].namespace, "billing")
        self.assertFalse(by_name["Order"].internal)
        self.assertEqual(by_name["Ledger"].namespace, "billing")
        self.assertTrue(by_name["Ledger"].internal)

    def test_a_namespace_directory_with_no_lnpl_files_is_rejected(self):
        os.makedirs(os.path.join(self.tmpdir, "billing", "empty"))
        self._write("shipping/order.lnpl", ORDER_ENTITY)
        with self.assertRaises(LoaderError):
            load_sources(self.tmpdir)

    def test_depth_beyond_one_namespace_level_is_rejected(self):
        self._write("billing/eu/order.lnpl", ORDER_ENTITY)
        with self.assertRaisesRegex(LoaderError, "nested more than one"):
            load_sources(self.tmpdir)

    def test_a_subdirectory_inside_internal_is_rejected(self):
        self._write("billing/internal/sub/x.lnpl",
                    "entity X\n    field\n        id UUID\n")
        with self.assertRaisesRegex(LoaderError, "internal/.*no subdirectories"):
            load_sources(self.tmpdir)

    def test_explicit_file_list_across_directories_stays_unnamespaced(self):
        a = self._write("billing/order.lnpl", ORDER_ENTITY)
        b = self._write("shipping/item.lnpl",
                        "entity Item\n    field\n        id UUID\n")
        decls = load_sources([a, b])
        self.assertTrue(all(d.namespace is None for d in decls))

    def test_an_empty_directory_still_raises_the_pre_rfc0033_message(self):
        with self.assertRaisesRegex(LoaderError, "no \\.lnpl files"):
            load_sources(self.tmpdir)


class DuplicateDeclarationScopeTest(_TmpDirCase):
    """RFC-0033 §Reference-level "중복 선언 검사 — 네임스페이스 내 유일로 완화"."""

    def test_same_name_same_namespace_two_files_is_rejected(self):
        self._write("billing/a.lnpl", ORDER_ENTITY)
        self._write("billing/b.lnpl", "entity Order\n    field\n        id UUID\n")
        with self.assertRaisesRegex(LoaderError, "duplicate declaration 'billing.Order'"):
            load_sources(self.tmpdir)

    def test_same_name_different_namespaces_is_not_a_collision(self):
        self._write("billing/order.lnpl", ORDER_ENTITY)
        self._write("shipping/order.lnpl",
                    "entity Order\n    field\n        id UUID\n        carrier Text\n")
        decls = load_sources(self.tmpdir)  # must not raise
        self.assertEqual(len(decls), 2)

    def test_same_name_no_namespace_stays_the_pre_rfc0033_bare_message(self):
        a = self._write("a.lnpl", ORDER_ENTITY)
        b = self._write("b.lnpl", "entity Order\n    field\n        id UUID\n")
        with self.assertRaisesRegex(LoaderError, r"duplicate declaration 'Order'"):
            load_sources([a, b])

    def test_internal_shares_its_parent_namespace_for_duplicate_purposes(self):
        self._write("billing/order.lnpl", ORDER_ENTITY)
        self._write("billing/internal/order.lnpl",
                    "entity Order\n    field\n        id UUID\n")
        with self.assertRaisesRegex(LoaderError, "duplicate declaration 'billing.Order'"):
            load_sources(self.tmpdir)


class DeriveIdNamespaceTest(unittest.TestCase):
    """RFC-0033 §Reference-level "`derive_id`"."""

    def test_no_namespace_is_byte_identical_to_pre_rfc0033(self):
        self.assertEqual(derive_id("Order", "Entity"),
                         derive_id("Order", "Entity", None))
        self.assertEqual(derive_id("Order", "Entity", None), "entity.order")

    def test_a_namespace_inserts_its_segments_after_the_kind_prefix(self):
        self.assertEqual(derive_id("Order", "Entity", "billing"),
                         "entity.billing.order")

    def test_internal_does_not_change_the_id(self):
        # RFC-0033: internal is a visibility tag, not a namespace — the id
        # only ever reflects the (inherited) namespace.
        self.assertEqual(derive_id("Ledger", "Entity", "billing"),
                         "entity.billing.ledger")


class ShortNameResolutionTest(_TmpDirCase):
    """RFC-0033 §Reference-level "짧은 이름 해소"."""

    def _compile(self):
        return lower(load_sources(self.tmpdir), "shop")

    def test_same_namespace_wins_over_a_cross_namespace_collision(self):
        self._write("billing/order.lnpl", ORDER_ENTITY + "\n" + FIND_ORDER_WF)
        self._write("shipping/order.lnpl",
                    "entity Order\n    field\n        id UUID\n        carrier Text\n")
        doc = self._compile().to_document()
        step_effects = [n for n in doc["nodes"] if n["kind"] == "RepositoryCall"]
        self.assertEqual(len(step_effects), 1)
        self.assertEqual(step_effects[0]["entity"], "entity.billing.order")

    def test_qualified_bare_id_form_references_a_specific_namespace(self):
        self._write("billing/order.lnpl", ORDER_ENTITY)
        self._write("shipping/order.lnpl",
                    "entity Order\n    field\n        id UUID\n        carrier Text\n"
                    "\nworkflow FindBillingOrder\n    find billingorder\n")
        doc = self._compile().to_document()
        step_effects = [n for n in doc["nodes"] if n["kind"] == "RepositoryCall"]
        self.assertEqual(step_effects[0]["entity"], "entity.billing.order")

    def test_ambiguous_cross_namespace_reference_lists_only_the_colliding_candidates(self):
        self._write("billing/order.lnpl", ORDER_ENTITY)
        self._write("shipping/order.lnpl",
                    "entity Order\n    field\n        id UUID\n        carrier Text\n")
        self._write("probe/probe.lnpl", "workflow Probe\n    find order\n")
        with self.assertRaises(LowerError) as ctx:
            self._compile()
        message = str(ctx.exception)
        self.assertIn("declared in 2 namespaces", message)
        self.assertIn("billing.Order", message)
        self.assertIn("shipping.Order", message)
        self.assertIn("find billingorder", message)

    def test_global_unique_fallback_still_applies_with_no_namespace(self):
        # Regression: a compile unit with no subdirectories can never have
        # more than one bare-name match (load_sources forbids it), so the
        # pre-RFC-0033 single-entity fallback (with its `unknown-entity`
        # diagnostic) is unchanged.
        self._write("a.lnpl", ORDER_ENTITY + "\nworkflow FindThing\n    find thing\n")
        mod = lower(load_sources(self.tmpdir), "shop")
        self.assertEqual(len(mod.diagnostics.by_code("unknown-entity")), 1)


class InternalVisibilityTest(_TmpDirCase):
    """RFC-0033 §Reference-level "`internal/` 가시성 검사"."""

    def _write_billing_and_internal_ledger(self):
        self._write("billing/order.lnpl", ORDER_ENTITY)
        self._write("billing/internal/ledger.lnpl",
                    "entity Ledger\n    field\n        id UUID\n        balance Integer\n")

    def test_same_namespace_may_reference_its_own_internal_declaration(self):
        self._write_billing_and_internal_ledger()
        self._write("billing/use_ledger.lnpl",
                    "workflow UseLedger\n    find ledger\n")
        doc = lower(load_sources(self.tmpdir), "shop").to_document()  # must not raise
        effects = [n for n in doc["nodes"] if n["kind"] == "RepositoryCall"]
        self.assertEqual(effects[0]["entity"], "entity.billing.ledger")

    def test_a_different_namespace_referencing_internal_via_step_object_is_rejected(self):
        self._write_billing_and_internal_ledger()
        self._write("shipping/use_ledger.lnpl",
                    "workflow UseLedger\n    find ledger\n")
        with self.assertRaisesRegex(LoaderError, "declared `internal` to namespace 'billing'"):
            lower(load_sources(self.tmpdir), "shop")

    def test_a_different_namespace_referencing_internal_via_set_is_rejected(self):
        # No preceding `find` — `set`'s binding resolution (`_derive_assignment`)
        # matches the module-level registry directly, independent of whether
        # this workflow read the row first (that's a separate, later check),
        # so this isolates the `set`-specific internal-visibility check.
        self._write_billing_and_internal_ledger()
        self._write("shipping/touch_ledger.lnpl",
                    "workflow TouchLedger\n"
                    "    set ledger.balance to 0\n")
        with self.assertRaisesRegex(LoaderError, "declared `internal` to namespace 'billing'"):
            lower(load_sources(self.tmpdir), "shop")

    def test_a_different_namespace_referencing_internal_via_respond_is_rejected(self):
        self._write_billing_and_internal_ledger()
        self._write("shipping/show_ledger.lnpl",
                    "workflow ShowLedger\n"
                    "    respond ledger.balance\n")
        with self.assertRaisesRegex(LoaderError, "declared `internal` to namespace 'billing'"):
            lower(load_sources(self.tmpdir), "shop")

    def test_no_namespace_compile_unit_can_never_trigger_internal_rejection(self):
        # Regression: `internal` can only be True when `load_sources` derived
        # a namespace layout, so a flat compile unit is unaffected.
        self._write("a.lnpl", ORDER_ENTITY + "\n" + FIND_ORDER_WF)
        lower(load_sources(self.tmpdir), "shop")  # must not raise


class OpenApiSchemaNamingTest(_TmpDirCase):
    """RFC-0033 §Reference-level "OpenAPI `components/schemas`"."""

    def test_namespaced_entities_get_qualified_schema_names_with_no_dangling_refs(self):
        self._write(
            "billing/order.lnpl",
            "entity Order\n    field\n        id UUID\n        total Text\n")
        self._write(
            "shipping/order.lnpl",
            "entity Order\n    field\n        id UUID\n        carrier Text\n")
        doc = lower(load_sources(self.tmpdir), "shop").to_document()
        openapi = generate_openapi(doc)  # must not raise OpenApiError (dangling $ref)
        self.assertIn("billing.Order", openapi["components"]["schemas"])
        self.assertIn("shipping.Order", openapi["components"]["schemas"])

    def test_no_namespace_schema_names_stay_bare(self):
        doc = lower(load_sources(LINKHUB_SINGLE), "linkhub").to_document()
        openapi = generate_openapi(doc)
        for name in openapi["components"]["schemas"]:
            self.assertNotIn(".", name)


SERVICE_AND_CREATE_WF = (
    "\nservice Shop\n    goal\n        accept one\n\n"
    "workflow CreateIt\n    validate %s\n    create %s\n")


class ValidationTargetResolutionTest(_TmpDirCase):
    """r2 F1: `_operation` resolves a `Validation` node's `target` back to its
    entity to attach `requestBody`. It used to rebuild the id with a fixed
    two-segment slice, which names no real entity as soon as the id has more
    segments — a multi-word entity name (`OrderItem` -> `entity.order.item`,
    true since long before RFC-0033) or an RFC-0033 namespace prefix
    (`entity.billing.order`). The lookup missed and the operation lost its
    `requestBody` silently, so these assert the body is present AND points at
    the right schema — asserting only "no exception" would not have caught it.
    """

    def _post_ops(self, source_arg, module="shop"):
        doc = lower(load_sources(source_arg), module).to_document()
        openapi = generate_openapi(doc)
        return {path: ops["post"] for path, ops in openapi["paths"].items()
                if "post" in ops}

    def _sole_request_ref(self, ops):
        bodied = [op for op in ops.values() if "requestBody" in op]
        self.assertEqual(len(bodied), 1, "expected exactly one POST with a body")
        return bodied[0]["requestBody"]["content"]["application/json"]["schema"]["$ref"]

    def test_a_namespaced_entity_keeps_its_request_body(self):
        self._write("billing/order.lnpl",
                    "entity Order\n    field\n        id UUID\n        total Text\n"
                    + SERVICE_AND_CREATE_WF % ("order", "order"))
        ref = self._sole_request_ref(self._post_ops(self.tmpdir))
        self.assertEqual(ref, "#/components/schemas/billing.Order")

    def test_a_flat_single_word_entity_is_unchanged(self):
        # The control: a 2-segment id is exactly the case the old fixed slice
        # got right, so it must resolve identically after the fix.
        self._write("a.lnpl",
                    "entity Order\n    field\n        id UUID\n        total Text\n"
                    + SERVICE_AND_CREATE_WF % ("order", "order"))
        ref = self._sole_request_ref(self._post_ops(self.tmpdir))
        self.assertEqual(ref, "#/components/schemas/Order")

    def test_a_flat_multi_word_entity_keeps_its_request_body(self):
        # Boundary: 3-segment id with NO namespace — the pre-RFC-0033 half of
        # this defect, which the fixed slice also silently dropped.
        self._write("a.lnpl",
                    "entity OrderItem\n    field\n        id UUID\n        sku Text\n"
                    + SERVICE_AND_CREATE_WF % ("orderitem", "orderitem"))
        ref = self._sole_request_ref(self._post_ops(self.tmpdir))
        self.assertEqual(ref, "#/components/schemas/OrderItem")

    def test_a_field_level_validation_resolves_to_its_owning_entity(self):
        # `validate <field>` targets `<entity id>.<field>`, one segment deeper
        # again — and under a namespace that is 4 segments.
        self._write("billing/order.lnpl",
                    "entity Order\n    field\n        id UUID\n        total Text\n"
                    + SERVICE_AND_CREATE_WF % ("total", "order"))
        ref = self._sole_request_ref(self._post_ops(self.tmpdir))
        self.assertEqual(ref, "#/components/schemas/billing.Order")

    def test_an_internal_entity_resolves_from_its_own_namespace(self):
        # `internal/` boundary: visibility narrows, but the id/target shape is
        # the parent namespace's, so resolution must still land.
        self._write("billing/internal/ledger.lnpl",
                    "entity Ledger\n    field\n        id UUID\n        balance Integer\n")
        self._write("billing/use.lnpl", SERVICE_AND_CREATE_WF % ("ledger", "ledger"))
        ref = self._sole_request_ref(self._post_ops(self.tmpdir))
        self.assertEqual(ref, "#/components/schemas/billing.Ledger")

    def test_a_whole_entity_validation_of_a_multi_word_name_resolves(self):
        # `Order` (`entity.order`) is a dotted prefix of `OrderItem`
        # (`entity.order.item`), so resolving by prefix search could land on
        # `Order`. A whole-entity validation must still name `OrderItem`.
        self._write("a.lnpl",
                    "entity Order\n    field\n        id UUID\n        total Text\n\n"
                    "entity OrderItem\n    field\n        id UUID\n        sku Text\n"
                    + SERVICE_AND_CREATE_WF % ("orderitem", "orderitem"))
        ref = self._sole_request_ref(self._post_ops(self.tmpdir))
        self.assertEqual(ref, "#/components/schemas/OrderItem")

    def test_a_field_target_colliding_with_another_entity_id_resolves_to_its_owner(self):
        # r2 audit: `Order` with a field named `item`, alongside an
        # `OrderItem` entity, makes `validate item` emit target
        # `entity.order.item` — byte-identical to `OrderItem`'s OWN id. The
        # body must be `Order` (whose field was validated); resolving the
        # target string alone silently answered `OrderItem`.
        self._write("a.lnpl",
                    "entity Order\n    field\n        id UUID\n        item Text\n\n"
                    "entity OrderItem\n    field\n        id UUID\n        sku Text\n"
                    + SERVICE_AND_CREATE_WF % ("item", "order"))
        ref = self._sole_request_ref(self._post_ops(self.tmpdir))
        self.assertEqual(ref, "#/components/schemas/Order")

    def test_the_colliding_whole_entity_form_still_resolves_to_the_other_entity(self):
        # The twin of the case above, same declarations and the SAME target
        # string, differing only in `rule` — proving the two are told apart
        # by the label and not by the id text.
        self._write("a.lnpl",
                    "entity Order\n    field\n        id UUID\n        item Text\n\n"
                    "entity OrderItem\n    field\n        id UUID\n        sku Text\n"
                    + SERVICE_AND_CREATE_WF % ("orderitem", "orderitem"))
        ref = self._sole_request_ref(self._post_ops(self.tmpdir))
        self.assertEqual(ref, "#/components/schemas/OrderItem")


class EntityForTargetUnitTest(unittest.TestCase):
    """r2 F1, at the unit the resolution actually lives in.

    `_entity_for_target` takes the whole Validation node because `target`
    alone is ambiguous: the two shapes `lower.py` emits can produce the same
    string, and only `rule` separates them.
    """

    ENTITIES = [{"id": "entity.order", "name": "Order"},
                {"id": "entity.order.item", "name": "OrderItem"},
                {"id": "entity.billing.order", "name": "Order"}]

    @staticmethod
    def _whole(target):
        return {"target": target, "rule": "semantic-types"}

    @staticmethod
    def _field(target, ftype="Text"):
        return {"target": target, "rule": ftype}

    def test_a_whole_entity_target_resolves_to_that_entity(self):
        self.assertEqual(
            _entity_for_target(self._whole("entity.billing.order"),
                               self.ENTITIES)["id"],
            "entity.billing.order")

    def test_a_field_target_resolves_to_its_owning_entity(self):
        self.assertEqual(
            _entity_for_target(self._field("entity.billing.order.total"),
                               self.ENTITIES)["id"],
            "entity.billing.order")

    def test_one_target_string_resolves_two_ways_by_rule(self):
        # The core of the r2 audit finding, isolated: identical `target`,
        # opposite answers, decided only by `rule`.
        target = "entity.order.item"
        self.assertEqual(
            _entity_for_target(self._whole(target), self.ENTITIES)["id"],
            "entity.order.item")
        self.assertEqual(
            _entity_for_target(self._field(target), self.ENTITIES)["id"],
            "entity.order")

    def test_a_deep_field_target_strips_exactly_one_segment(self):
        self.assertEqual(
            _entity_for_target(self._field("entity.order.item.sku"),
                               self.ENTITIES)["id"],
            "entity.order.item")

    def test_an_unmatched_target_returns_none(self):
        self.assertIsNone(
            _entity_for_target(self._whole("entity.nosuch"), self.ENTITIES))

    def test_no_entities_at_all_returns_none(self):
        self.assertIsNone(_entity_for_target(self._whole("entity.order"), []))

    def test_a_shared_segment_prefix_is_not_a_match(self):
        # `entity.orders` must not resolve to `entity.order` — the id has to
        # match whole, not by character prefix.
        self.assertIsNone(
            _entity_for_target(self._whole("entity.orders"), self.ENTITIES))

    def test_a_node_without_a_rule_is_read_as_the_field_form(self):
        # Defensive boundary: every Validation node `lower.py` emits carries
        # `rule`, so this only pins the absent-key path to a deterministic
        # answer instead of a KeyError.
        self.assertEqual(
            _entity_for_target({"target": "entity.order.item"},
                               self.ENTITIES)["id"],
            "entity.order")


class ByteIdenticalGuaranteeTest(unittest.TestCase):
    """D4: a compile unit with no subdirectories is byte-identical to the
    pre-RFC-0033 compiler (fixtures committed from `3c1db72`)."""

    def _assert_matches_fixture(self, decls_source, module_name, fixture_name):
        doc = lower(load_sources(decls_source), module_name).to_document()
        with open(os.path.join(FIXTURE_DIR, fixture_name + ".json"),
                  encoding="utf-8") as fh:
            baseline = json.load(fh)
        self.assertEqual(doc, baseline)

    def test_linkhub_single_file(self):
        self._assert_matches_fixture(LINKHUB_SINGLE, "linkhub", "linkhub_single")

    def test_checkout_single_file(self):
        self._assert_matches_fixture(CHECKOUT_SINGLE, "checkout", "checkout_single")

    def test_linkhub_split_directory(self):
        # RFC-0031's directory form (files only, no subdirectories) — the
        # explicit "directory-shaped" example RFC-0033's Guide-level
        # Explanation cites as unaffected.
        self._assert_matches_fixture(LINKHUB_SPLIT_DIR, "linkhub", "linkhub_split_dir")


class ScalePressureRegressionTest(unittest.TestCase):
    """D5: issue #117's measured collision scenario, promoted to a regression
    fixture — reuses `scripts/gen_scale_corpus.py` (issue #117, t117 Task 01)
    rather than re-deriving its domain/shared-noun corpus model."""

    ENTITIES = 10  # docs/scale-pressure-measurement.md's smallest measured
                  # scale: 2 shared nouns (`Status`, `Order`) each land in
                  # exactly 2 of the 5 domains — enough to prove all three
                  # assertions without N=50's slower compile.

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="rfc0033-scale-", dir=TMP_ROOT)
        cls.written, cls.pool_report = gen_scale_corpus.generate(
            cls.ENTITIES, cls.tmpdir, seed=0, disambiguate=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _domains_declaring(self, noun):
        """Which of the 5 generated domain directories declare `entity <noun>`
        — read from the generator's own output, not hardcoded, so this stays
        correct if the generator's seed=0 draw ever changes."""
        found = []
        for domain in gen_scale_corpus.DOMAINS:
            domain_dir = os.path.join(self.tmpdir, domain)
            for name in os.listdir(domain_dir):
                with open(os.path.join(domain_dir, name), encoding="utf-8") as fh:
                    if ("entity %s\n" % noun) in fh.read():
                        found.append(domain)
                        break
        return found

    def test_a_flat_placement_reproduces_the_measured_collision(self):
        # (a) explicit file list across the 5 domain dirs == "no namespace"
        # (RFC-0033's own rule: only a *single directory* argument can ever
        # derive a namespace) — the exact pressure issue #117 measured.
        with self.assertRaises(LoaderError):
            load_sources(sorted(self.written))

    def test_a_namespaced_placement_compiles_with_zero_collisions(self):
        # (b) the same corpus, compiled as a single directory (namespace
        # root: no `.lnpl` directly under it, 5 subdirectories) — the
        # collision RFC-0033 exists to resolve.
        decls = load_sources(self.tmpdir)  # must not raise
        mod = lower(decls, "scale")
        entity_ids = [n["id"] for n in mod.to_document()["nodes"]
                     if n["kind"] == "Entity"]
        self.assertEqual(len(entity_ids), len(set(entity_ids)))
        self.assertEqual(len(entity_ids), self.ENTITIES)

    def test_unknown_entity_candidates_shrink_to_the_namespace_boundary(self):
        # (c) issue #117 measurement item 4: pre-RFC-0033 the candidate list
        # would be every declared entity (`self.ENTITIES`); RFC-0033 shrinks
        # it to just the entities whose bare name actually collided.
        colliding_domains = self._domains_declaring("Status")
        self.assertGreaterEqual(
            len(colliding_domains), 2,
            "corpus doesn't exercise this assertion — 'Status' didn't collide "
            "at seed=0/N=%d" % self.ENTITIES)
        probe_dir = os.path.join(self.tmpdir, "zzz_probe")
        os.makedirs(probe_dir, exist_ok=True)
        with open(os.path.join(probe_dir, "probe.lnpl"), "w", encoding="utf-8") as fh:
            fh.write("workflow ProbeStatus\n    find status\n")
        self.addCleanup(shutil.rmtree, probe_dir, ignore_errors=True)
        with self.assertRaises(LowerError) as ctx:
            lower(load_sources(self.tmpdir), "scale")
        message = str(ctx.exception)
        self.assertIn("declared in %d namespaces" % len(colliding_domains), message)
        self.assertLess(len(colliding_domains), self.ENTITIES)


if __name__ == "__main__":
    unittest.main()

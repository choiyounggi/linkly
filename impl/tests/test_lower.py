"""Lowering rules: R2 (id derivation) and R1 (closed verb lexicon)."""

import json
import os
import unittest

from lnpl.lower import LowerError, WORD_RE, derive_id, lower, split_pascal
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

    def test_pascal_split_keeps_a_capital_run_whole(self):
        # A run of capitals is one word. When a lowercase letter follows the
        # run, the run's LAST capital opens that next word — `APIKey` is
        # api+key, not apik+ey.
        self.assertEqual(split_pascal("URL"), ["url"])
        self.assertEqual(split_pascal("APIKey"), ["api", "key"])
        self.assertEqual(split_pascal("HTTPSEndpoint"), ["https", "endpoint"])
        self.assertEqual(split_pascal("FetchAPIToken"), ["fetch", "api", "token"])
        self.assertEqual(split_pascal("AB"), ["ab"])
        self.assertEqual(split_pascal("ABc"), ["a", "bc"])
        # Not a PascalName, but `split_pascal` also takes already-lowercase
        # names (`capability postgres`), so its behavior here is defined.
        self.assertEqual(split_pascal("aBC"), ["a", "bc"])

    def test_pascal_split_digits_stay_with_their_word(self):
        # A digit is not uppercase, so it joins the word it follows; an
        # uppercase letter after a digit opens a new one.
        self.assertEqual(split_pascal("Api2Key"), ["api2", "key"])
        self.assertEqual(split_pascal("X509Certificate"), ["x509", "certificate"])
        # Documented limitation: `IPv6` mixes a two-letter acronym with a
        # lowercase-led token, so `P` (before lowercase `v`) opens a word. No
        # case-only rule recovers `ipv6` — that needs a dictionary. This is
        # also what the pre-fix rule produced, so it is not a new regression.
        self.assertEqual(split_pascal("IPv6Address"), ["i", "pv6", "address"])

    def test_pascal_split_boundary_inputs(self):
        self.assertEqual(split_pascal(""), [])
        self.assertEqual(split_pascal("A"), ["a"])
        self.assertEqual(split_pascal("Url"), ["url"])
        self.assertEqual(split_pascal("postgres"), ["postgres"])

    def test_acronym_id_composes_with_the_kind_word_strip(self):
        # The acronym run survives the redundant-kind-word strip: `svc.a.p.i`
        # (pre-fix) was also a collision risk once the suffix was dropped.
        self.assertEqual(derive_id("APIService", "Service"), "svc.api")
        self.assertEqual(derive_id("APIKey", "Entity"), "entity.api.key")

    def test_shipped_names_keep_their_ids(self):
        # Every declared name in the three shipped examples, plus the presets
        # emitted on use. None has consecutive capitals, so none may move.
        self.assertEqual(derive_id("UserCreated", "Event"), "event.user.created")
        self.assertEqual(derive_id("LoginService", "Service"), "svc.login")
        self.assertEqual(derive_id("ClickCount", "Refinement"), "refine.click.count")
        self.assertEqual(derive_id("URL", "Refinement"), "refine.url")
        self.assertEqual(derive_id("postgres", "Capability"), "cap.postgres")

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
        # The event has to be declared for the reference to resolve — an `emit`
        # of an undeclared event is a compile error (issue #45, see
        # TestStructure.test_emit_of_an_undeclared_event_is_rejected).
        src = GOLDEN.replace("service LoginService",
                             "event UserCreated on User create\nservice LoginService")
        doc = ir(src + "    emit userCreated\n")
        node = by_id(doc)["wf.login.step.4.emit"]
        self.assertEqual(node["kind"], "EventEmit")
        self.assertEqual(node["event"], "event.user.created")

    def test_emit_without_an_object_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            ir(GOLDEN + "    emit\n")
        self.assertIn("needs the event to emit", str(ctx.exception))


EMIT_WITH_SRC = """capability postgres

entity Order
    field
        id UUID
        customerId Text
        total Integer derived

entity Customer
    field
        id UUID
        secret Password

event OrderPlaced

service Orders
    policy
        retry 0

workflow Checkout
    create order as newOrder
    find customer
    call OrdersApi as orderResult
"""


# issue #204: a dedicated fixture (not EMIT_WITH_SRC) because these cases
# need a derived field whose value is computable from an Integer input
# (EMIT_WITH_SRC's own fields are UUID/Text/Password, none Integer) and a
# second derived field whose base IS Text (`format` only ever writes a
# Text-family target, RFC-0016) so the `format`-fills-it case (R7) has a
# field it is legal to write.
DERIVED_EMIT_SRC = """capability postgres

entity Order
    field
        id UUID
        quantity Integer
        total Integer derived
        label Text derived

event OrderPlaced

service ShopService
    policy
        retry 0

workflow PlaceOrder
"""


class TestEmitWithClause(unittest.TestCase):
    """issue #178, RFC-0049: `emit <Event> with <ref>...` -> `payloadMap`."""

    def test_bare_emit_stays_payloadmap_free(self):
        # R2: byte-identical to the pre-#178 node — no `payloadMap` key.
        doc = ir(EMIT_WITH_SRC + "    emit orderPlaced\n")
        node = by_id(doc)["wf.checkout.step.4.emit"]
        self.assertEqual(node["kind"], "EventEmit")
        self.assertNotIn("payloadMap", node)

    def test_with_clause_compiles_to_the_payload_map_shape(self):
        # R1: create-as alias field + input.<field>, ordered, field = the
        # ref's own trailing dot-segment.
        doc = ir(EMIT_WITH_SRC +
                 "    emit orderPlaced with newOrder.id input.customerId\n")
        node = by_id(doc)["wf.checkout.step.4.emit"]
        self.assertEqual(node["payloadMap"],
                         [{"field": "id", "ref": "newOrder.id"},
                          {"field": "customerId", "ref": "input.customerId"}])

    def test_a_bare_ref_in_with_is_refused(self):
        # R3: neither a bound row's field, a network-result binding, nor
        # `input.<field>` -- the dot-check runs before any scope lookup.
        with self.assertRaises(LowerError) as ctx:
            ir(EMIT_WITH_SRC + "    emit orderPlaced with unknownRef\n")
        self.assertIn("unknownRef", str(ctx.exception))

    def test_a_network_result_ref_is_admitted_unchecked(self):
        # R3: `call ... as <name>` has no declared shape to check against --
        # `scope.resolve_field` returns None for it, same as a bare ref, but
        # the dot-check above already told the two apart.
        doc = ir(EMIT_WITH_SRC + "    emit orderPlaced with orderResult.status\n")
        node = by_id(doc)["wf.checkout.step.4.emit"]
        self.assertEqual(node["payloadMap"],
                         [{"field": "status", "ref": "orderResult.status"}])

    def test_a_password_field_ref_is_refused(self):
        # R4: the masking chokepoint (issue #43), same rule `respond` uses.
        with self.assertRaises(LowerError) as ctx:
            ir(EMIT_WITH_SRC + "    emit orderPlaced with customer.secret\n")
        msg = str(ctx.exception)
        self.assertIn("customer.secret", msg)
        self.assertIn("Password", msg)

    def test_duplicate_mapped_field_names_are_refused(self):
        # R5: `newOrder.id` and `customer.id` both map to trailing field `id`.
        with self.assertRaises(LowerError) as ctx:
            ir(EMIT_WITH_SRC +
               "    emit orderPlaced with newOrder.id customer.id\n")
        msg = str(ctx.exception)
        self.assertIn("id", msg)
        self.assertIn("newOrder.id", msg)
        self.assertIn("customer.id", msg)

    def test_non_with_trailing_words_are_now_refused(self):
        # R6: previously silently dropped -- issue #178's root defect.
        with self.assertRaises(LowerError) as ctx:
            ir(EMIT_WITH_SRC + "    emit orderPlaced foo bar\n")
        self.assertIn("('foo', 'bar')", str(ctx.exception))

    def test_with_and_no_refs_is_refused(self):
        # R7: boundary -- zero refs after `with`.
        with self.assertRaises(LowerError) as ctx:
            ir(EMIT_WITH_SRC + "    emit orderPlaced with\n")
        self.assertIn("with` needs at least one reference", str(ctx.exception))

    def test_a_derived_field_ref_is_refused(self):
        # R11: `total` is `derived` and never `set`/`format`-assigned.
        with self.assertRaises(LowerError) as ctx:
            ir(EMIT_WITH_SRC + "    emit orderPlaced with newOrder.total\n")
        msg = str(ctx.exception)
        self.assertIn("newOrder.total", msg)
        self.assertIn("derived", msg)

    def test_a_preceding_unguarded_set_admits_the_derived_ref(self):
        # R1: `set` on the same binding+field, unguarded (both unguarded is
        # "the same scope" by definition), strictly before the `emit`.
        doc = ir(DERIVED_EMIT_SRC +
                 "    create order as o\n"
                 "    set o.total to input.quantity * 2\n"
                 "    emit orderPlaced with o.id o.total\n")
        node = by_id(doc)["wf.place.order.step.3.emit"]
        self.assertEqual(node["payloadMap"],
                         [{"field": "id", "ref": "o.id"},
                          {"field": "total", "ref": "o.total"}])

    def test_the_refusal_names_the_missing_assignment_and_the_emit_line(self):
        # R2's message half: DERIVED_EMIT_SRC is 16 lines, `create` is line
        # 17, so the `emit` the message must point at is line 18.
        with self.assertRaises(LowerError) as ctx:
            ir(DERIVED_EMIT_SRC +
               "    create order as o\n"
               "    emit orderPlaced with o.total\n")
        msg = str(ctx.exception)
        self.assertIn("no `set`/`format` on o.total precedes this `emit` "
                      "(line 18)", msg)
        self.assertIn("derived", msg)

    def test_assigned_in_a_guard_emitted_outside_it_is_refused(self):
        # R3: the guard wraps exactly the `set` (RFC-0002: one item), so the
        # `emit` right after it is unguarded -- a different scope.
        with self.assertRaises(LowerError) as ctx:
            ir(DERIVED_EMIT_SRC +
               "    create order as o\n"
               "    when input.quantity > 0\n"
               "    set o.total to input.quantity * 2\n"
               "    emit orderPlaced with o.total\n")
        msg = str(ctx.exception)
        self.assertIn("o.total", msg)
        self.assertIn("derived", msg)
        self.assertIn("same guard scope", msg)

    def test_assigned_and_emitted_in_one_parallel_block_is_admitted(self):
        # R4: same guard scope via "put creator and reader in one block
        # under the guard" (references/grammar.md's own remedy, reused by
        # #198's ORPHAN_HINT).
        doc = ir(DERIVED_EMIT_SRC +
                 "    create order as o\n"
                 "    when input.quantity > 0\n"
                 "    parallel\n"
                 "        set o.total to input.quantity * 2\n"
                 "        emit orderPlaced with o.total\n"
                 "    merge\n")
        node = by_id(doc)["wf.place.order.step.3.emit"]
        self.assertEqual(node["payloadMap"], [{"field": "total", "ref": "o.total"}])

    def test_assigned_and_emitted_under_the_repeated_guard_line_is_admitted(self):
        # R4b: same guard scope via "repeat the guard line" -- a second,
        # physically distinct Guard node with the same mode+condition counts
        # as the same scope (`_guard_key`'s own contract).
        doc = ir(DERIVED_EMIT_SRC +
                 "    create order as o\n"
                 "    when input.quantity > 0\n"
                 "    set o.total to input.quantity * 2\n"
                 "    when input.quantity > 0\n"
                 "    emit orderPlaced with o.total\n")
        node = by_id(doc)["wf.place.order.step.3.emit"]
        self.assertEqual(node["payloadMap"], [{"field": "total", "ref": "o.total"}])

    def test_assigned_after_the_emit_is_refused(self):
        # R5: textual order, even unguarded (same scope is not enough).
        with self.assertRaises(LowerError) as ctx:
            ir(DERIVED_EMIT_SRC +
               "    create order as o\n"
               "    emit orderPlaced with o.total\n"
               "    set o.total to input.quantity * 2\n")
        self.assertIn("no `set`/`format` on o.total precedes",
                      str(ctx.exception))

    def test_assigned_on_a_different_binding_is_refused(self):
        # R6: `o2.total` does not satisfy a reference to `o.total`, even
        # though both bindings are the same entity.
        with self.assertRaises(LowerError) as ctx:
            ir(DERIVED_EMIT_SRC +
               "    create order as o\n"
               "    create order as o2\n"
               "    set o2.total to input.quantity * 2\n"
               "    emit orderPlaced with o.total\n")
        self.assertIn("no `set`/`format` on o.total precedes",
                      str(ctx.exception))

    def test_a_preceding_format_admits_the_derived_ref(self):
        # R7: `format` counts exactly like `set` -- uses `label` (Text-family,
        # since `format` never writes an Integer target, RFC-0016).
        doc = ir(DERIVED_EMIT_SRC +
                 "    create order as o\n"
                 "    format o.label from \"{}\" with o.quantity\n"
                 "    emit orderPlaced with o.label\n")
        node = by_id(doc)["wf.place.order.step.3.emit"]
        self.assertEqual(node["payloadMap"], [{"field": "label", "ref": "o.label"}])

    def test_an_unguarded_assignment_emitted_under_a_guard_is_refused(self):
        # D5: the mirror image of R3 -- an unconditionally-assigned derived
        # field does NOT get #198's "unconditional creation is always bound"
        # exemption; the brief's literal "same guard scope" wording governs.
        with self.assertRaises(LowerError) as ctx:
            ir(DERIVED_EMIT_SRC +
               "    create order as o\n"
               "    set o.total to input.quantity * 2\n"
               "    when input.quantity > 0\n"
               "    emit orderPlaced with o.total\n")
        self.assertIn("no `set`/`format` on o.total precedes",
                      str(ctx.exception))


LOOKUP_SRC = """capability postgres

entity Order
    field
        id UUID
        productId Text
        total Integer derived
        secret Password

entity Product
    field
        id UUID
        stock Integer

service Orders
    policy
        retry 0

workflow Checkout
%s"""


class TestLookupKeyStaticCheck(unittest.TestCase):
    """issue #175 / RFC-0052 §Static checks: which refs a `by <ref>` lookup
    key may name. The G12.5 ⓒ gate is whole-workflow membership (order-blind,
    coordinator ruling r1): a binding used before its read compiles and fails
    at run time instead."""

    def _lookup_of(self, body, step_text):
        doc = ir(LOOKUP_SRC % body)
        steps = {n["name"]: n for n in doc["nodes"] if n["kind"] == "WorkflowStep"}
        nodes = by_id(doc)
        call = nodes[steps[step_text]["children"][0]]
        self.assertEqual(call["kind"], "RepositoryCall")
        return call.get("lookup")

    def test_a_binding_the_workflow_never_reads_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            ir(LOOKUP_SRC % "    find product by order.productId\n")
        msg = str(ctx.exception)
        self.assertIn("never reads it", msg)
        self.assertIn("lookup key", msg)

    def test_a_binding_read_later_in_the_workflow_is_admitted(self):
        """Order-blind positive control: `find order` comes AFTER the
        reference and the check still admits it (whole-workflow membership)."""
        body = ("    find product by order.productId\n"
                "    find order\n")
        self.assertEqual(self._lookup_of(body, "find product by order.productId"),
                         "order.productId")

    def test_a_self_reference_is_admitted(self):
        """`find order by order.productId` makes `order` a read entity by
        itself, so the static gate is satisfied. At run time it is only
        useful when an earlier step of the same run already bound `order`;
        otherwise the ref resolves to nothing and the step fails with a named
        RunError (RFC-0052 §Runtime, t175b) — never here."""
        body = "    find order by order.productId\n"
        self.assertEqual(self._lookup_of(body, "find order by order.productId"),
                         "order.productId")

    def test_a_create_alias_from_an_earlier_step_is_admitted(self):
        body = ("    create order as placed\n"
                "    find product by placed.productId\n")
        self.assertEqual(self._lookup_of(body, "find product by placed.productId"),
                         "placed.productId")

    def test_a_derived_field_is_refused(self):
        for body in ("    find order\n    find product by order.total\n",
                     "    create order as placed\n"
                     "    update product by placed.total\n"):
            with self.subTest(body=body):
                with self.assertRaises(LowerError) as ctx:
                    ir(LOOKUP_SRC % body)
                self.assertIn("`derived`", str(ctx.exception))

    def test_a_password_field_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            ir(LOOKUP_SRC % "    find order\n    delete product by order.secret\n")
        msg = str(ctx.exception)
        self.assertIn("Password", msg)
        self.assertIn("RFC-0052", msg)

    def test_input_fields_are_admitted_even_when_declared_derived_or_password(self):
        for ref in ("input.productId", "input.total", "input.secret"):
            with self.subTest(ref=ref):
                self.assertEqual(
                    self._lookup_of("    find product by %s\n" % ref,
                                    "find product by %s" % ref), ref)

    def test_an_undeclared_input_field_is_refused(self):
        with self.assertRaises(LowerError):
            ir(LOOKUP_SRC % "    find product by input.nope\n")

    def test_bare_caller_and_network_result_refs_are_admitted(self):
        cases = [("    find product by productId\n", "find product by productId"),
                 ("    find product by caller.subject\n",
                  "find product by caller.subject"),
                 ("    call OrdersApi as fetched\n"
                  "    find product by fetched.id\n", "find product by fetched.id")]
        for body, step in cases:
            with self.subTest(step=step):
                self.assertEqual(self._lookup_of(body, step), step.split(" by ")[1])

    def test_a_lookup_nested_in_a_guard_or_parallel_block_is_checked_too(self):
        """The post-pass walks into guard and block children, so a Password
        key cannot slip through by sitting inside `when` or `parallel`."""
        for body in ("    find order\n    when input.stock > 0\n"
                     "        find product by order.secret\n",
                     "    find order\n    parallel\n"
                     "        find product by order.secret\n    merge\n"):
            with self.subTest(body=body):
                with self.assertRaises(LowerError) as ctx:
                    ir(LOOKUP_SRC % body)
                self.assertIn("Password", str(ctx.exception))

    def test_an_unknown_caller_field_is_refused(self):
        with self.assertRaises(LowerError):
            ir(LOOKUP_SRC % "    find product by caller.email\n")


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


class TestEntityFieldNames(unittest.TestCase):
    """Issue #149 — a field name must be a `WORD_RE` identifier.

    `_entity_for_target` (openapi.py) resolves a `Validation` target by
    stripping exactly one trailing segment; a dotted field name defeats that
    and the generated OpenAPI silently drops `requestBody`. Rejecting the
    name at declaration closes the door for good.
    """

    def test_a_dotted_field_name_is_rejected(self):
        # The issue #149 repro, verbatim.
        with self.assertRaises(LowerError) as ctx:
            ir("entity Order\n    field\n        id UUID\n        foo.bar Integer\n")
        msg = str(ctx.exception)
        self.assertIn("foo.bar", msg)
        self.assertIn(WORD_RE.pattern, msg)

    def test_a_field_name_starting_with_an_uppercase_letter_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("entity Order\n    field\n        id UUID\n        Total Integer\n")
        msg = str(ctx.exception)
        self.assertIn("Total", msg)
        self.assertIn(WORD_RE.pattern, msg)

    def test_a_field_name_with_digits_and_internal_capitals_is_accepted(self):
        doc = ir("entity Order\n    field\n        line1Total Integer\n")
        self.assertEqual(by_id(doc)["entity.order"]["fields"],
                         [{"name": "line1Total", "type": "Integer"}])

    def test_the_derived_modifier_still_lowers_with_a_valid_name(self):
        doc = ir("entity Order\n    field\n        id UUID\n"
                 "        total Integer derived\n")
        self.assertEqual(by_id(doc)["entity.order"]["fields"],
                         [{"name": "id", "type": "UUID"},
                          {"name": "total", "type": "Integer", "derived": True}])


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

    def test_emit_of_an_undeclared_event_is_rejected(self):
        """Issue #45 / t4 F-2: the same dangling-reference rule, for `emit`.

        `emit notification` synthesizes `event.notification`, but the module
        declares `event.notification.sent`. This used to compile and validate
        clean and only fail in the interpreter — and when a guard skipped the
        step, it never failed at all. The candidate list is part of the
        contract: the compiler knows the declared ids, so it names them.
        """
        src = (GOLDEN + "event NotificationSent on User create\n"
                        "workflow Notify\n    emit notification\n")
        with self.assertRaises(LowerError) as ctx:
            ir(src)
        msg = str(ctx.exception)
        self.assertIn("event.notification", msg)        # the synthesized id
        self.assertIn("event.notification.sent", msg)   # the declared candidate
        self.assertIn("Notify", msg)                    # the owning workflow

    def test_emit_in_a_module_with_no_events_says_none_are_declared(self):
        src = GOLDEN + "workflow Notify\n    emit userCreated\n"
        with self.assertRaises(LowerError) as ctx:
            ir(src)
        msg = str(ctx.exception)
        self.assertIn("event.user.created", msg)
        self.assertIn("none declared", msg)

    def test_emit_matching_a_declared_event_still_lowers(self):
        """Non-destructive: the valid program is unchanged."""
        src = (GOLDEN + "event NotificationSent on User create\n"
                        "workflow Notify\n    emit notificationSent\n")
        doc = ir(src)
        node = by_id(doc)["wf.notify.step.1.emit"]
        self.assertEqual(node["kind"], "EventEmit")
        self.assertEqual(node["event"], "event.notification.sent")

    def test_boundary_declared_event_with_no_emit_lowers(self):
        doc = ir(GOLDEN + "event NotificationSent on User create\n")
        self.assertEqual(by_id(doc)["event.notification.sent"]["kind"], "Event")
        self.assertEqual([n for n in doc["nodes"] if n["kind"] == "EventEmit"], [])

    def test_boundary_module_with_no_workflow_lowers(self):
        doc = ir("entity User\n    field\n        id UUID\n"
                 "event NotificationSent on User create\n")
        self.assertEqual([n["kind"] for n in doc["nodes"] if n["kind"] == "Workflow"], [])
        self.assertEqual(by_id(doc)["event.notification.sent"]["kind"], "Event")

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
        self.assertEqual(derive_id("URL", "Refinement"), "refine.url")
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
        for name in ("URL", "Slug", "PositiveInteger"):
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

    # RFC-0011 widened ⓔ to the module's entity names (2026-08-05). An entity
    # and a refinement land in one `components/schemas` key space, so a shared
    # name silently overwrote one of them; `openapi.py` caught it at generation
    # time, which is one layer too late for consumers that skip the generator.

    def test_a_refinement_named_like_an_entity_is_rejected(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Link of Text\n    maxLength 8\n"
               "entity Link\n    field\n        code Text\n")
        self.assertIn("an entity", str(ctx.exception))
        self.assertIn("'Link'", str(ctx.exception))

    def test_the_entity_may_be_declared_before_or_after_the_refine(self):
        # `lower` groups declarations by kind before lowering any of them, so
        # the collision is found whichever order the file uses. Both orders are
        # asserted because only one of them is the "obvious" one to implement.
        after = ("refine Link of Text\n    maxLength 8\n"
                 "entity Link\n    field\n        code Text\n")
        before = ("entity Link\n    field\n        code Text\n"
                  "refine Link of Text\n    maxLength 8\n")
        for src in (after, before):
            with self.assertRaises(LowerError) as ctx:
                ir(src)
            self.assertIn("an entity", str(ctx.exception))

    def test_a_name_differing_only_in_case_is_not_a_collision(self):
        # `components/schemas` keys are case-sensitive, so `Link` and `link` are
        # two distinct keys and neither overwrites the other -- there is no harm
        # to prevent. RFC-0011 A.7 fixes the judgment as exact equality.
        doc = ir("refine Link of Text\n    maxLength 8\n"
                 "entity link\n    field\n        code Text\n")
        named = [(n["kind"], n["name"]) for n in doc["nodes"]
                 if n.get("name") in ("Link", "link")]
        self.assertEqual(sorted(named), [("Entity", "link"),
                                         ("Refinement", "Link")])

    def test_a_merely_similar_entity_name_is_not_a_collision(self):
        doc = ir("refine Linkish of Text\n    maxLength 8\n"
                 "entity Link\n    field\n        code Text\n")
        self.assertEqual(sorted(n["name"] for n in doc["nodes"]
                                if n["kind"] in ("Entity", "Refinement")),
                         ["Link", "Linkish"])

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

    # ---- RFC-0011 A.6.3: an enum member must be a value its base can hold ----
    #
    # INVERTED 2026-08-05. This case used to assert that `enum draft 1 2.5` on a
    # `Text` base lowers with all three members, which was correct under the
    # pre-RFC-0011 A.6.3 ("배열(문자열 또는 수치)", with no member/base rule). A
    # `Text` field holds a string, so `1` and `2.5` were members no value could
    # ever match -- an unsatisfiable schema with no diagnostic. RFC-0011 narrows
    # the rule and the compiler now rejects the source instead of lowering it.

    def test_enum_mixing_words_and_numbers_on_text_is_rejected(self):
        src = ("refine Kind of Text\n    enum draft 1 2.5\n"
               "entity L\n    field\n        k Kind\n")
        with self.assertRaises(LowerError) as ctx:
            ir(src)
        self.assertIn("cannot be a value of base", str(ctx.exception))
        self.assertIn("'Text'", str(ctx.exception))
        # The first offending member is named, not just the fact of a violation.
        self.assertIn("enum value 1 ", str(ctx.exception))

    def test_enum_of_words_on_text_is_accepted(self):
        src = ("refine Kind of Text\n    enum draft published\n"
               "entity L\n    field\n        k Kind\n")
        values = refinements_of(ir(src))[0]["facets"]["enum"]
        self.assertEqual(values, ["draft", "published"])
        self.assertEqual([type(v) for v in values], [str, str])

    def test_text_enum_rejects_a_numeric_member(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Kind of Text\n    enum 1\n"
               "entity L\n    field\n        k Kind\n")
        self.assertIn("cannot be a value of base", str(ctx.exception))
        self.assertIn("a Word", str(ctx.exception))

    def test_decimal_enum_accepts_an_int_and_a_float(self):
        # `Decimal` admits both notations, so the mix that fails on Integer
        # below is legal here. The two tests differ only in the base.
        src = ("refine Price of Decimal\n    enum 1 2.5\n"
               "entity L\n    field\n        p Price\n")
        values = refinements_of(ir(src))[0]["facets"]["enum"]
        self.assertEqual(values, [1, 2.5])
        self.assertEqual([type(v) for v in values], [int, float])

    def test_integer_enum_rejects_a_fractional_member(self):
        with self.assertRaises(LowerError) as ctx:
            ir("refine Score of Integer\n    enum 1 2.5\n"
               "entity L\n    field\n        s Score\n")
        self.assertIn("enum value 2.5 ", str(ctx.exception))
        self.assertIn("no fractional part", str(ctx.exception))

    def test_integer_enum_rejects_a_decimal_notation_whole_number(self):
        # The rule keys on NOTATION, not numeric value: `2.0` parses to a float
        # via the same `_number` rule `min`/`max` use, and an Integer field holds
        # an int. Numerically 2.0 == 2, which is exactly why this needs pinning.
        with self.assertRaises(LowerError) as ctx:
            ir("refine Score of Integer\n    enum 2.0\n"
               "entity L\n    field\n        s Score\n")
        self.assertIn("enum value 2.0 ", str(ctx.exception))
        self.assertIn("no fractional part", str(ctx.exception))

    def test_integer_enum_accepts_whole_numbers(self):
        src = ("refine Score of Integer\n    enum 1 2 3\n"
               "entity L\n    field\n        s Score\n")
        values = refinements_of(ir(src))[0]["facets"]["enum"]
        self.assertEqual(values, [1, 2, 3])
        self.assertEqual([type(v) for v in values], [int, int, int])

    def test_a_pascal_enum_value_still_fails_on_form_first(self):
        # Check order is a contract (`_parse_facet_line`'s docstring): value FORM
        # is judged before member/base compatibility, so `Draft` reports "not a
        # valid enum value" rather than the RFC-0011 message. A future refactor
        # that reorders the two would redden here.
        with self.assertRaises(LowerError) as ctx:
            ir("refine Kind of Text\n    enum Draft\n"
               "entity L\n    field\n        k Kind\n")
        self.assertIn("not a valid enum value", str(ctx.exception))
        self.assertNotIn("cannot be a value of base", str(ctx.exception))

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
        src = "entity Link\n    field\n        slug Slug\n        target URL\n"
        nodes = by_id(ir(src))
        self.assertEqual(nodes["refine.slug"], {
            "kind": "Refinement", "id": "refine.slug", "name": "Slug",
            "base": "Text",
            "facets": {"pattern": "^[a-z0-9-]{1,64}$", "maxLength": 64}})
        self.assertEqual(nodes["refine.url"], {
            "kind": "Refinement", "id": "refine.url", "name": "URL",
            "base": "Text",
            "facets": {"pattern": r"^https?://[^\s]+$", "maxLength": 2048}})
        # the field keeps the NAME, not the node id
        self.assertEqual(nodes["entity.link"]["fields"],
                         [{"name": "slug", "type": "Slug"},
                          {"name": "target", "type": "URL"}])

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
        src = ("entity Link\n    field\n        target URL\n        slug Slug\n")
        self.assertEqual([n["name"] for n in refinements_of(ir(src))],
                         ["URL", "Slug"])

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

    def test_the_old_url_spelling_no_longer_resolves(self):
        # The preset is `URL` (issue #31). `Url` was the shipped misspelling,
        # forced by a since-fixed `split_pascal` defect that derived
        # `refine.u.r.l`; it is a plain unknown name now, not an alias.
        with self.assertRaises(LowerError) as ctx:
            ir("entity L\n    field\n        target Url\n")
        self.assertIn("RFC-0001 A.6.1", str(ctx.exception))
        self.assertIn("Url", str(ctx.exception))

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
        # `provenance` (issue #136) is excluded from golden comparisons — its
        # digests are environment-dependent (docs/compatibility.md §2).
        compiled = lower(parse(source), golden["module"]).to_document()
        compiled.pop("provenance")
        self.assertEqual(compiled, golden)

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
        target URL
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
                         ["Code", "Slug", "URL", "PositiveInteger"])

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


SCOPED_SOURCE = """
capability postgres
entity Product
    field
        id UUID
        stock Integer
        name Text
entity Order
    field
        id UUID
        total Money
service ShopService
    policy
        retry 0
workflow Checkout
    find product
    when %s
    create order
"""


class TestScopedGuardReferenceIsCheckedAtCompileTime(unittest.TestCase):
    """RFC-0012 §G12.5: a qualified reference is resolved where the document is
    in scope, so a reference that can never bind fails the build instead of
    silently evaluating false at run time (the failure mode §G12.4 would give it).
    """

    def _lower(self, condition):
        return lower(parse(SCOPED_SOURCE % condition), "shop")

    def test_a_reference_to_a_read_entity_lowers(self):
        # Normal case: `find product` reads entity.product, and Product declares
        # `stock`, so all three checks hold.
        mod = self._lower("product.stock > 0")
        guard = mod.get("wf.checkout.guard.1")
        self.assertEqual(guard["condition"], "product.stock > 0")

    def test_an_undeclared_binding_is_refused(self):
        with self.assertRaises(LowerError) as caught:
            self._lower("widget.stock > 0")
        self.assertIn("not a declared entity", str(caught.exception))
        self.assertIn("widget", str(caught.exception),
                      "the refusal must name the binding that resolved to "
                      "nothing; got %r" % str(caught.exception))

    def test_an_undeclared_field_is_refused(self):
        with self.assertRaises(LowerError) as caught:
            self._lower("product.nosuch > 0")
        self.assertIn("does not declare", str(caught.exception))
        self.assertIn("nosuch", str(caught.exception))

    def test_a_reference_to_an_entity_the_workflow_never_reads_is_refused(self):
        # `Order` is created, never read, so no read can ever bind it. Without
        # this check the guard would quietly compare against nothing and be
        # false forever — a declared guard that is really a no-op.
        with self.assertRaises(LowerError) as caught:
            self._lower("order.total > 0")
        self.assertIn("never reads it", str(caught.exception))
        self.assertIn("entity.order", str(caught.exception))

    def test_a_presence_reference_is_checked_the_same_way(self):
        # The check is on the reference, not on the comparison form.
        with self.assertRaises(LowerError) as caught:
            self._lower("widget.name exists")
        self.assertIn("not a declared entity", str(caught.exception))

    # ---- issue #177 / RFC-0050: the numeric-shape predicate -----------------
    def test_a_numeric_predicate_on_a_declared_integer_field_lowers(self):
        mod = self._lower("product.stock is-numeric")
        self.assertEqual(mod.get("wf.checkout.guard.1")["condition"],
                         "product.stock is-numeric")

    def test_a_numeric_predicate_on_a_declared_text_field_is_refused(self):
        # Same `_dimension_of` rule a comparison or a presence check gets.
        with self.assertRaises(LowerError) as caught:
            self._lower("product.name is-not-numeric")
        self.assertIn("neither Integer nor DateTime", str(caught.exception))

    def test_a_numeric_predicate_reference_is_checked_the_same_way(self):
        with self.assertRaises(LowerError) as caught:
            self._lower("widget.stock is-numeric")
        self.assertIn("not a declared entity", str(caught.exception))

    def test_a_text_predicate_mixed_into_and_is_refused_not_crashed(self):
        # The widened `And` must still reach the dimension check, and the
        # `_comparisons` consumers must skip the predicate term cleanly.
        with self.assertRaises(LowerError) as caught:
            self._lower("product.stock > 1 and product.name is-numeric")
        self.assertIn("neither Integer nor DateTime", str(caught.exception))

    def test_a_predicate_mixed_into_and_with_a_valid_comparison_lowers(self):
        mod = self._lower("product.stock > 1 and product.stock is-numeric")
        self.assertEqual(mod.get("wf.checkout.guard.1")["condition"],
                         "product.stock > 1 and product.stock is-numeric")

    def test_a_bare_numeric_predicate_is_decided_at_runtime(self):
        mod = self._lower("rate is-numeric")
        self.assertEqual(mod.get("wf.checkout.guard.1")["condition"],
                         "rate is-numeric")

    # ---- boundary: the bare form must be untouched -------------------------
    def test_a_bare_reference_is_not_checked(self):
        # RFC-0012 G12.3: bare names are payload fields. They are NOT entity
        # fields, so applying the entity checks to them would reject correct
        # programs — `when token missing` asks about the request, not a row.
        mod = self._lower("stock > 0")
        self.assertEqual(mod.get("wf.checkout.guard.1")["condition"], "stock > 0")

    def test_a_bare_reference_naming_no_declared_field_still_lowers(self):
        mod = self._lower("anythingAtAll > 0")
        self.assertEqual(mod.get("wf.checkout.guard.1")["condition"],
                         "anythingAtAll > 0")

    def test_a_repeat_guard_has_no_condition_to_check(self):
        # Boundary: `repeat` carries `count`, not `condition`. The check must not
        # trip over a guard with no condition at all.
        source = SCOPED_SOURCE.replace("when %s", "repeat 2")
        mod = lower(parse(source), "shop")
        self.assertEqual(mod.get("wf.checkout.guard.1")["count"], 2)


MONEY_PREDICATE_SOURCE = """
capability postgres
entity Product
    field
        id UUID
        stock Integer
        price Money
        cost Money
entity Order
    field
        id UUID
service ShopService
    policy
        retry 0
workflow Checkout
    find product
    when %s
    create order
"""


class TestNumericPredicateRefusesMoney(unittest.TestCase):
    """RFC-0051 §Compatibility: once Money is a dimension, `_dimension_of` no
    longer refuses a Money field under the numeric-shape predicate (RFC-0050)
    by itself — a structural check on the predicate's own field does."""

    def _lower(self, condition):
        return lower(parse(MONEY_PREDICATE_SOURCE % condition), "shop")

    def test_a_money_field_under_either_predicate_is_refused(self):
        for kind in ("is-numeric", "is-not-numeric"):
            with self.subTest(kind=kind):
                with self.assertRaises(LowerError) as caught:
                    self._lower("product.price %s" % kind)
                message = str(caught.exception)
                self.assertIn("product.price", message)
                self.assertIn("declared type is Money", message)
                self.assertIn("RFC-0050", message)
                self.assertIn("RFC-0051", message)

    def test_a_money_predicate_inside_and_is_refused(self):
        with self.assertRaises(LowerError) as caught:
            self._lower("product.stock > 1 and product.cost is-numeric")
        self.assertIn("product.cost", str(caught.exception))
        self.assertIn("RFC-0050", str(caught.exception))

    def test_the_check_is_scoped_to_the_predicate_field(self):
        # A Money comparison and an Integer predicate in one `and` both hold.
        cond = "product.price > product.cost and product.stock is-numeric"
        mod = self._lower(cond)
        self.assertEqual(mod.get("wf.checkout.guard.1")["condition"], cond)

    def test_an_undeclared_reference_under_the_predicate_is_unaffected(self):
        mod = self._lower("price is-numeric")
        self.assertEqual(mod.get("wf.checkout.guard.1")["condition"],
                         "price is-numeric")


class TestPresenceRefusesMoney(unittest.TestCase):
    """RFC-0051 §Compatibility: `exists`/`missing` on a declared Money field
    stays refused — the Gate-1 subset opens Money comparison and arithmetic
    only, not presence."""

    def _lower(self, condition):
        return lower(parse(MONEY_PREDICATE_SOURCE % condition), "shop")

    def test_money_exists_is_refused(self):
        with self.assertRaises(LowerError) as caught:
            self._lower("product.price exists")
        message = str(caught.exception)
        self.assertIn("product.price", message)
        self.assertIn("declared type is Money", message)
        self.assertIn("RFC-0051", message)

    def test_money_missing_is_refused(self):
        with self.assertRaises(LowerError) as caught:
            self._lower("product.cost missing")
        self.assertIn("product.cost", str(caught.exception))
        self.assertIn("RFC-0051", str(caught.exception))

    def test_integer_exists_is_still_admitted(self):
        mod = self._lower("product.stock exists")
        self.assertEqual(mod.get("wf.checkout.guard.1")["condition"],
                         "product.stock exists")

    def test_an_undeclared_reference_under_presence_is_unaffected(self):
        mod = self._lower("price missing")
        self.assertEqual(mod.get("wf.checkout.guard.1")["condition"],
                         "price missing")


NUMERIC_PREDICATE_SOURCE = """
capability postgres
entity Order
    field
        id UUID
        amount Integer
service OrderService
    security
        jwt
    policy
        timeout 5s
workflow Convert
    call Fx as fxResult
    when %s
    create order
"""


class TestNumericPredicateOnUndeclaredReferences(unittest.TestCase):
    """Issue #177 / RFC-0050 static rule: a predicate on a reference the
    document gives no type — a network result field, `caller.*`, a bare
    payload field — lowers and is decided at runtime."""

    def _lower(self, when_line):
        return lower(parse(NUMERIC_PREDICATE_SOURCE % when_line), "fx")

    def _guard(self, mod):
        guards = [n for n in mod.to_document()["nodes"] if n["kind"] == "Guard"]
        self.assertEqual(len(guards), 1)
        return guards[0]

    def test_a_network_result_field_lowers(self):
        guard = self._guard(self._lower(
            "fxResult.status == 200 and fxResult.rate is-numeric"))
        self.assertEqual(guard["condition"],
                         "fxResult.status == 200 and fxResult.rate is-numeric")

    def test_a_caller_field_lowers(self):
        guard = self._guard(self._lower("caller.role is-not-numeric"))
        self.assertEqual(guard["condition"], "caller.role is-not-numeric")

    def test_an_or_alternative_using_the_predicate_passes_the_guard_check(self):
        guard = self._guard(self._lower(
            "fxResult.status != 200\n    or fxResult.rate is-not-numeric"))
        self.assertEqual(guard["condition"], "fxResult.status != 200")
        self.assertEqual(guard["alternatives"], ["fxResult.rate is-not-numeric"])

    def test_an_or_alternative_on_an_undeclared_binding_is_still_refused(self):
        # The alternative goes through the same reference check.
        with self.assertRaises(LowerError) as caught:
            self._lower("fxResult.status != 200\n    or widget.rate is-numeric")
        self.assertIn("not a declared entity", str(caught.exception))


ASSIGN_SOURCE = """
capability postgres
entity Product
    field
        id UUID
        stock Integer
        name Text
entity Order
    field
        id UUID
        total Integer
service ShopService
    policy
        retry 0
workflow Checkout
    find product
    create order
    %s
"""


class TestAssignmentDiagnosticNamesTheStepItIsAbout(unittest.TestCase):
    """이슈 #56 [2] / r3 N-2: 진단이 `set` 스텝을 "guard condition"이라 부르던 것.

    가드 검사와 할당 검사가 `_Scope.check_reference` 하나를 공유하는데, 메시지가
    주어를 "guard condition"으로 못박고 있었다. 그래서 `set`이 거부될 때 저자는
    자기가 쓰지도 않은 가드를 찾아다녔다. 게다가 그 메시지가 붙여 주던 수리 안내
    (\"대신 `input.<필드>`를 써라\")는 **할당 대상에 대해서는 틀린 안내**다 —
    `input.`을 대상으로 쓰면 `_derive_assignment`가 따로 거부한다.

    여기서 고정하는 것은 문면뿐이다. 예외 종류도, 거부 조건도, 무엇이 통과하는지도
    그대로여야 한다.
    """

    def _lower(self, step):
        return lower(parse(ASSIGN_SOURCE % step), "shop")

    def _refusal(self, step):
        with self.assertRaises(LowerError) as caught:
            self._lower(step)
        return str(caught.exception)

    # -- 정상: 오칭 교정 ---------------------------------------------------
    def test_an_assignment_is_not_called_a_guard_condition(self):
        message = self._refusal("set order.total to 1")
        self.assertNotIn("guard condition", message)
        self.assertIn("assignment", message)

    def test_the_refusal_points_at_the_read_verbs_not_the_input_namespace(self):
        """대상은 `input.`으로 고칠 수 없다 — 안내가 그리로 보내면 안 된다."""
        message = self._refusal("set order.total to 1")
        self.assertRegex(message, r"`read`|`load`|`find`")
        self.assertNotIn("input.total", message)

    def test_the_refusal_still_names_the_entity_and_the_step(self):
        message = self._refusal("set order.total to 1")
        self.assertIn("entity.order", message)
        self.assertIn("set order.total to 1", message)

    # -- 에러 계약이 그대로인가 -------------------------------------------
    def test_the_rejection_is_still_a_lower_error_on_the_same_condition(self):
        with self.assertRaises(LowerError):
            self._lower("set order.total to 1")

    def test_an_assignment_to_a_read_binding_still_lowers(self):
        """정상 대조군: 거부가 '늘 거부'가 아님을 보인다."""
        mod = self._lower("set product.stock to product.stock - 1")
        self.assertEqual(mod.get("wf.checkout.step.3.assign")["target"],
                         "product.stock")

    # -- 회귀: 진짜 가드는 여전히 가드다 -----------------------------------
    def test_a_guard_is_still_called_a_guard_condition(self):
        with self.assertRaises(LowerError) as caught:
            lower(parse(SCOPED_SOURCE % "order.total > 0"), "shop")
        self.assertIn("guard condition", str(caught.exception))

    # -- 경계: 대상과 피연산자는 다른 안내를 받는다 ------------------------
    def test_an_operand_may_still_be_pointed_at_the_input_namespace(self):
        """피연산자에서는 `input.`이 옳은 수리다 — 대상 규칙이 번지면 안 된다."""
        message = self._refusal("set product.stock to order.total")
        self.assertIn("assignment", message)
        self.assertNotIn("guard condition", message)
        self.assertIn("input.total", message)

    def test_an_operand_naming_an_undeclared_input_field_is_still_refused(self):
        message = self._refusal("set product.stock to input.nosuch")
        self.assertIn("input field", message)
        self.assertNotIn("guard condition", message)



# RFC-0053 Track B: `optional` fields in guards.
OPTIONAL_GUARD_SOURCE = """
capability postgres
entity Customer
    field
        id UUID
        name Text
        nickname Text optional
        score Integer optional
        bonus Integer optional
        total Integer
        balance Money optional
        price Money
entity Order
    field
        id UUID
service CustomerService
    policy
        retry 0
workflow Greet
    find customer
%s
"""

OPTIONAL_CUSTOMER_ID = "0b6f1c2e-4444-4a2b-9c3d-000000000208"


def optional_guard_module(body):
    return lower(parse(OPTIONAL_GUARD_SOURCE % body), "crm")


class TestPresenceOnOptionalFields(unittest.TestCase):
    """RFC-0053 §6 3.2: `exists`/`missing` is open on an `optional` field of
    any declared type; a non-optional Text/Money field is still refused."""

    def test_presence_on_optional_text_field_compiles(self):
        mod = optional_guard_module("    when customer.nickname exists\n    create order")
        self.assertEqual(mod.get("wf.greet.guard.1")["condition"],
                         "customer.nickname exists")

    def test_missing_on_optional_text_field_compiles(self):
        mod = optional_guard_module("    when customer.nickname missing\n    create order")
        self.assertEqual(mod.get("wf.greet.guard.1")["condition"],
                         "customer.nickname missing")

    def test_presence_on_non_optional_text_field_still_refused(self):
        with self.assertRaises(LowerError) as caught:
            optional_guard_module("    when customer.name exists\n    create order")
        self.assertIn("customer.name", str(caught.exception))
        self.assertIn("neither Integer nor DateTime", str(caught.exception))

    def test_presence_on_optional_money_field_compiles(self):
        mod = optional_guard_module("    when customer.balance exists\n    create order")
        self.assertEqual(mod.get("wf.greet.guard.1")["condition"],
                         "customer.balance exists")

    def test_presence_on_non_optional_money_field_still_refused(self):
        with self.assertRaises(LowerError) as caught:
            optional_guard_module("    when customer.price exists\n    create order")
        self.assertIn("declared type is Money", str(caught.exception))
        self.assertIn("RFC-0051", str(caught.exception))

    def test_comparison_on_optional_text_field_ordering_still_refused(self):
        # Boundary: the Presence exemption (RFC-0053 §6 3.2) and the equality
        # exemption (RFC-0054) are both independent of `optional` — ordering
        # comparison on a Text-family field stays refused either way.
        with self.assertRaises(LowerError) as caught:
            optional_guard_module(
                "    when customer.nickname > input.nickname\n    create order")
        self.assertIn("neither Integer nor DateTime", str(caught.exception))

    def test_comparison_on_optional_text_field_equality_now_compiles(self):
        # RFC-0054: equality is independent of `optional`.
        mod = optional_guard_module(
            "    when customer.nickname == input.nickname\n    create order")
        guard = mod.get("wf.greet.guard.1")
        self.assertEqual("customer.nickname == input.nickname", guard["condition"])
        self.assertEqual([["customer.nickname", "input.nickname"]],
                         guard["textEqualityOperands"])


class TestPresenceOnOptionalFieldsAtRuntime(unittest.TestCase):
    """The guard compiled above gates on the stored row's key."""

    def run_greet(self, row):
        from lnpl.interp import Interpreter
        from lnpl.repo_policy import row_key
        doc = optional_guard_module(
            "    when customer.nickname exists\n    create order").to_document()
        payload = {"id": OPTIONAL_CUSTOMER_ID}
        rows = {"entity.customer": {row_key("entity.customer", payload): row}}
        interp = Interpreter(doc, repo_rows=rows)
        result = interp.run_workflow("wf.greet", payload)
        self.assertEqual("completed", result["status"], result.get("failure_reason"))
        return interp.repo.rows.get("entity.order", {})

    def test_a_present_optional_text_field_opens_the_guard(self):
        orders = self.run_greet({"id": OPTIONAL_CUSTOMER_ID, "name": "Ada",
                                 "total": 1, "price": {"amount": "1.00", "currency": "USD"},
                                 "nickname": "Countess"})
        self.assertEqual(1, len(orders))

    def test_an_absent_optional_text_field_closes_the_guard(self):
        orders = self.run_greet({"id": OPTIONAL_CUSTOMER_ID, "name": "Ada",
                                 "total": 1, "price": {"amount": "1.00", "currency": "USD"}})
        self.assertEqual({}, orders)

    def test_a_null_optional_text_field_closes_the_guard(self):
        orders = self.run_greet({"id": OPTIONAL_CUSTOMER_ID, "name": "Ada",
                                 "total": 1, "price": {"amount": "1.00", "currency": "USD"},
                                 "nickname": None})
        self.assertEqual({}, orders)


INPUT_PRESENCE_SOURCE = """
capability postgres
%s
service CrmService
    policy
        retry 0
workflow Note
    when input.note exists
    create customer
"""

CUSTOMER_NOTE_OPTIONAL = "entity Customer\n    field\n        id UUID\n        note Text optional\n"
CUSTOMER_NOTE_REQUIRED = "entity Customer\n    field\n        id UUID\n        note Text\n"
ORDER_NOTE_REQUIRED = "entity Order\n    field\n        id UUID\n        note Text\n"
ORDER_NOTE_OPTIONAL = "entity Order\n    field\n        id UUID\n        note Text optional\n"


class TestInputPresenceAcrossEntities(unittest.TestCase):
    """RFC-0053 §11 first rule / RFC-0015 §3 new row: `input.<field>
    exists` needs every declaring entity to agree on `optional`."""

    def lower_entities(self, *entities):
        return lower(parse(INPUT_PRESENCE_SOURCE % "".join(entities)), "crm")

    def assert_ambiguous(self, *entities):
        with self.assertRaises(LowerError) as caught:
            self.lower_entities(*entities)
        message = str(caught.exception)
        self.assertIn("Customer, Order", message)
        self.assertIn("RFC-0053", message)
        self.assertIn("input.note exists", message)

    def test_input_field_presence_ambiguous_entities_refused(self):
        self.assert_ambiguous(CUSTOMER_NOTE_OPTIONAL, ORDER_NOTE_REQUIRED)

    def test_input_field_presence_ambiguous_entities_refused_other_order(self):
        self.assert_ambiguous(ORDER_NOTE_REQUIRED, CUSTOMER_NOTE_OPTIONAL)

    def test_input_field_presence_both_optional_compiles(self):
        mod = self.lower_entities(CUSTOMER_NOTE_OPTIONAL, ORDER_NOTE_OPTIONAL)
        self.assertEqual(mod.get("wf.note.guard.1")["condition"], "input.note exists")

    def test_input_field_presence_single_entity_optional_compiles(self):
        mod = self.lower_entities(CUSTOMER_NOTE_OPTIONAL)
        self.assertEqual(mod.get("wf.note.guard.1")["condition"], "input.note exists")

    def test_input_field_presence_single_entity_required_text_still_refused(self):
        # Boundary: one declaring entity -> no ambiguity, the type rule decides.
        with self.assertRaises(LowerError) as caught:
            self.lower_entities(CUSTOMER_NOTE_REQUIRED)
        self.assertIn("neither Integer nor DateTime", str(caught.exception))

    def test_input_field_presence_namespaced_duplicate_entities_refused(self):
        import shutil
        import tempfile
        from lnpl import cli
        base = os.path.join(REPO_ROOT, ".claude", "tmp")
        os.makedirs(base, exist_ok=True)
        root = tempfile.mkdtemp(prefix="lnpl-t208b-", dir=base)
        self.addCleanup(shutil.rmtree, root, True)
        files = {
            "billing/customer.lnpl": CUSTOMER_NOTE_OPTIONAL,
            "shipping/customer.lnpl": CUSTOMER_NOTE_REQUIRED,
            "billing/app.lnpl": ("service CrmService\n    policy\n        retry 0\n"
                                 "workflow Note\n    when input.note exists\n"
                                 "    create customer\n"),
        }
        for rel, text in files.items():
            path = os.path.join(root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        with self.assertRaises(Exception) as caught:
            cli.compile_source([root])
        message = str(caught.exception)
        self.assertIn("billing.Customer", message)
        self.assertIn("shipping.Customer", message)
        self.assertIn("RFC-0053", message)


ARITH_GUARD_SOURCE = OPTIONAL_GUARD_SOURCE
ARITH_CODE = "optional-field-unguarded-arithmetic"
SET_SCORE = "    set customer.total to customer.score + 1"


def arith_warnings(body):
    return list(optional_guard_module(body).diagnostics.by_code(ARITH_CODE))


class TestOptionalUnguardedArithmetic(unittest.TestCase):
    """RFC-0053 §8: `set`/guard arithmetic on an optional field is
    protected only by the nearest enclosing `when <same field> exists`."""

    def test_arithmetic_inside_the_exact_guard_no_warning(self):
        self.assertEqual([], arith_warnings(
            "    when customer.score exists\n" + SET_SCORE))

    def test_arithmetic_inside_pipeline_under_the_guard_no_warning(self):
        self.assertEqual([], arith_warnings(
            "    when customer.score exists\n    pipeline\n" + SET_SCORE))

    def test_arithmetic_inside_parallel_under_the_guard_no_warning(self):
        self.assertEqual([], arith_warnings(
            "    when customer.score exists\n    parallel\n" + SET_SCORE
            + "\n    merge"))

    def test_arithmetic_after_the_guard_ends_warns(self):
        found = arith_warnings(
            "    when customer.score exists\n    create order\n" + SET_SCORE)
        self.assertEqual(["customer.score"], [d.subject for d in found])
        self.assertEqual("warning", found[0].severity)
        self.assertEqual(23, found[0].line)
        self.assertIn("when customer.score exists", found[0].message)
        self.assertIn("RFC-0053", found[0].message)
        self.assertIn("when <ref> exists", found[0].hint)

    def test_arithmetic_with_no_guard_at_all_warns(self):
        found = arith_warnings(SET_SCORE)
        self.assertEqual(["customer.score"], [d.subject for d in found])
        self.assertEqual(21, found[0].line)

    def test_arithmetic_under_or_alternative_warns(self):
        found = arith_warnings(
            "    when customer.score exists\n    or customer.total > 0\n" + SET_SCORE)
        self.assertEqual(["customer.score"], [d.subject for d in found])

    def test_arithmetic_under_until_warns(self):
        found = arith_warnings("    until customer.score exists\n" + SET_SCORE)
        self.assertEqual(["customer.score"], [d.subject for d in found])

    def test_arithmetic_under_guard_on_different_field_warns(self):
        found = arith_warnings("    when customer.bonus exists\n" + SET_SCORE)
        self.assertEqual(["customer.score"], [d.subject for d in found])

    def test_arithmetic_under_missing_guard_warns(self):
        # `missing` is the opposite of protection.
        found = arith_warnings("    when customer.score missing\n" + SET_SCORE)
        self.assertEqual(["customer.score"], [d.subject for d in found])

    def test_arithmetic_on_a_required_field_never_warns(self):
        self.assertEqual([], arith_warnings(
            "    set customer.total to customer.total + 1"))

    def test_a_plain_read_without_arithmetic_does_not_warn(self):
        # §8: the warning covers arithmetic only; a bare read stays a
        # runtime RunError when the value is absent.
        self.assertEqual([], arith_warnings("    set customer.total to customer.score"))

    def test_guard_comparison_arithmetic_on_optional_field_warns(self):
        found = arith_warnings("    when customer.score + 1 > 5\n    create order")
        self.assertEqual(["customer.score"], [d.subject for d in found])
        self.assertEqual(21, found[0].line)

    def test_guard_comparison_arithmetic_cannot_be_protected_by_an_outer_guard(self):
        # Guards never nest: a guard line closes the open `pipeline`, so the
        # second guard is top-level and its arithmetic still warns (RFC-0053 §8).
        found = arith_warnings(
            "    when customer.score exists\n    pipeline\n    create order\n"
            "    when customer.score + 1 > 5\n    create order")
        self.assertEqual(["customer.score"], [d.subject for d in found])
        self.assertEqual(24, found[0].line)

    def test_guard_comparison_arithmetic_on_a_required_field_no_warning(self):
        self.assertEqual([], arith_warnings(
            "    when customer.total + 1 > 5\n    create order"))

    def test_guard_alternative_arithmetic_on_optional_field_warns(self):
        found = arith_warnings(
            "    when customer.total > 5\n    or customer.bonus * 2 > 5\n"
            "    create order")
        self.assertEqual(["customer.bonus"], [d.subject for d in found])

    def test_guard_comparison_without_arithmetic_does_not_warn(self):
        self.assertEqual([], arith_warnings("    when customer.score > 5\n    create order"))


TEXT_GUARD_SOURCE = """
capability postgres
refine OrderStatus of Text
    enum pending paid cancelled
entity Order
    field
        id UUID
        status OrderStatus
        expected OrderStatus
        note Text
        ownerId UUID
        secret Password
        ratio Decimal
        rush Boolean
        stock Integer
service OrderService
    policy
        retry 0
workflow CancelOrder
    find order
%s
"""


def text_guard_module(body):
    return lower(parse(TEXT_GUARD_SOURCE % body), "shop")


def text_guard(condition):
    return text_guard_module(
        "    when %s\n    update order" % condition).get("wf.cancel.order.guard.1")


def text_guard_refusal(test, condition):
    with test.assertRaises(LowerError) as caught:
        text_guard(condition)
    return str(caught.exception)


class TestTextEqualityGuards(unittest.TestCase):
    """RFC-0054: a guard compares a Text-family field with `==`/`!=`."""

    def test_guard_equality_on_text_field_compiles(self):
        guard = text_guard("order.note == input.note")
        self.assertEqual("order.note == input.note", guard["condition"])
        self.assertEqual([["input.note", "order.note"]],
                         guard["textEqualityOperands"])

    def test_guard_equality_on_enum_field_against_input_compiles(self):
        # The issue's CancelOrder guard, with `expected` declared so
        # `input.expected` names a field (RFC-0012 checks input names).
        guard = text_guard("order.status == input.expected")
        self.assertEqual([["input.expected", "order.status"]],
                         guard["textEqualityOperands"])

    def test_the_issues_literal_source_now_fails_only_on_the_input_name(self):
        # Issue #207's CancelOrder verbatim: `expected` is declared nowhere, so
        # RFC-0012's input-name check refuses it — no longer the type rule.
        source = ("refine OrderStatus of Text\n    enum pending paid cancelled\n\n"
                  "entity Order\n    field\n        id UUID\n"
                  "        status OrderStatus\n\nservice OrderService\n\n"
                  "workflow CancelOrder\n    find order\n"
                  "    when order.status == input.expected\n    update order\n")
        with self.assertRaises(LowerError) as caught:
            lower(parse(source), "g2")
        message = str(caught.exception)
        self.assertIn("names input field 'expected', which no entity declares",
                      message)
        self.assertNotIn("neither Integer nor DateTime", message)

    def test_guard_equality_on_enum_text_field_compiles(self):
        guard = text_guard("order.status == paid")
        self.assertEqual([["order.status", "paid"]], guard["textEqualityOperands"])

    def test_guard_inequality_on_text_field_compiles(self):
        guard = text_guard("order.status != cancelled")
        self.assertEqual([["cancelled", "order.status"]],
                         guard["textEqualityOperands"])

    def test_text_equality_mirrored_operand_order(self):
        self.assertEqual(text_guard("order.status == paid")["textEqualityOperands"],
                         text_guard("paid == order.status")["textEqualityOperands"])

    def test_plain_text_field_accepts_any_bare_literal(self):
        guard = text_guard("order.note == anything")
        self.assertEqual([["anything", "order.note"]], guard["textEqualityOperands"])

    def test_guard_ordering_on_text_field_still_refused(self):
        for op in ("<", "<=", ">", ">="):
            message = text_guard_refusal(self, "order.status %s paid" % op)
            self.assertIn("neither Integer nor DateTime", message, op)

    def test_guard_equality_on_password_field_still_refused_citing_masking(self):
        message = text_guard_refusal(self, "order.secret == hunter")
        self.assertIn("order.secret", message)
        self.assertIn("RFC-0001", message)
        self.assertIn("mask", message)
        self.assertNotIn("RFC-0054", message)

    def test_guard_equality_on_decimal_field_still_refused(self):
        message = text_guard_refusal(self, "order.ratio == input.ratio")
        self.assertIn("neither Integer nor DateTime", message)

    def test_guard_equality_on_boolean_field_still_refused(self):
        message = text_guard_refusal(self, "order.rush == input.rush")
        self.assertIn("neither Integer nor DateTime", message)

    def test_enum_literal_not_a_member_is_refused_with_a_suggestion(self):
        message = text_guard_refusal(self, "order.status == paidd")
        self.assertIn("'paidd'", message)
        self.assertIn("pending, paid, cancelled", message)
        self.assertIn("did you mean 'paid'?", message)

    def test_enum_literal_with_no_close_match_lists_the_members(self):
        # `shipped` is close to no member (difflib cutoff 0.6), so there is
        # no did-you-mean, but the refusal still names what may be written.
        message = text_guard_refusal(self, "order.status == shipped")
        self.assertIn("'shipped'", message)
        self.assertIn("OrderStatus", message)
        self.assertIn("pending, paid, cancelled", message)
        self.assertNotIn("did you mean", message)

    def test_enum_literal_on_the_left_is_checked_too(self):
        message = text_guard_refusal(self, "shipped != order.status")
        self.assertIn("'shipped'", message)

    def test_two_text_family_fields_of_different_bases_refused(self):
        message = text_guard_refusal(self, "order.status == order.ownerId")
        self.assertIn("same declared type", message)
        self.assertIn("OrderStatus", message)
        self.assertIn("UUID", message)

    def test_text_field_against_a_number_literal_is_refused(self):
        message = text_guard_refusal(self, "order.status == 5")
        self.assertIn("like with like", message)

    def test_arithmetic_on_either_side_of_a_text_equality_is_refused(self):
        message = text_guard_refusal(self, "order.status == order.stock + 1")
        self.assertIn("arithmetic", message)
        self.assertIn("RFC-0054", message)
        # A Text field inside the arithmetic hits the plain dimension refusal.
        message = text_guard_refusal(self, "order.note + 1 == paid")
        self.assertIn("neither Integer nor DateTime", message)

    def test_two_bare_integer_names_in_equality_unaffected_by_rfc_0054(self):
        guard = text_guard("stock == available")
        self.assertEqual("stock == available", guard["condition"])
        self.assertNotIn("textEqualityOperands", guard)

    def test_a_bare_name_on_the_left_of_an_unrelated_comparison_is_unaffected(self):
        guard = text_guard("available == order.stock")
        self.assertNotIn("textEqualityOperands", guard)

    def test_an_integer_guard_ir_carries_no_new_key(self):
        guard = text_guard("order.stock > 0")
        self.assertEqual({"kind", "id", "mode", "condition", "children", "line"},
                         set(guard) - {"meta"})

    def test_and_chain_records_only_the_text_term(self):
        guard = text_guard("order.status == pending and order.stock > 0")
        self.assertEqual([["order.status", "pending"]],
                         guard["textEqualityOperands"])

    def test_alternatives_record_one_entry_per_text(self):
        guard = text_guard_module(
            "    when order.stock > 100\n    or order.status == pending\n"
            "    update order").get("wf.cancel.order.guard.1")
        self.assertEqual([[], ["order.status", "pending"]],
                         guard["textEqualityOperands"])

    def test_list_where_text_equality_is_unaffected_by_rfc_0054(self):
        mod = text_guard_module("    list order where status == input.expected")
        calls = [n for n in mod.nodes() if n.get("operation") == "query"]
        self.assertEqual(
            [{"field": "status", "op": "==", "value": "input.expected"}],
            calls[0]["predicate"])
        self.assertFalse(any("textEqualityOperands" in n for n in mod.nodes()))


class TestSetOnATextFieldNamesFormat(unittest.TestCase):
    """Issue #207 item 6: `set` cannot write Text, and the refusal says how."""

    def refusal(self, step):
        with self.assertRaises(LowerError) as caught:
            text_guard_module("    %s\n    update order" % step)
        return str(caught.exception)

    def test_set_text_field_to_bare_literal_names_format(self):
        message = self.refusal("set order.status to paid")
        self.assertIn("a Text field (declared type OrderStatus)", message)
        self.assertIn("format order.status from", message)

    def test_set_text_field_to_quoted_literal_names_format(self):
        message = self.refusal('set order.status to "paid"')
        self.assertIn("a Text field (declared type OrderStatus)", message)
        self.assertIn("format order.status from", message)

    def test_set_plain_text_field_to_a_reference_names_format(self):
        message = self.refusal("set order.note to input.note")
        self.assertIn("format order.note from", message)

    def test_set_uuid_field_to_bare_literal_still_gets_the_generic_message(self):
        # `format` cannot write UUID either, so no hint here.
        message = self.refusal("set order.ownerId to abc")
        self.assertIn("neither Integer nor DateTime", message)
        self.assertNotIn("format", message)

    def test_set_uuid_field_to_quoted_literal_keeps_the_parse_error(self):
        message = self.refusal('set order.ownerId to "abc"')
        self.assertNotIn("format", message)

    def test_set_integer_field_unaffected(self):
        mod = text_guard_module(
            "    set order.stock to order.stock + 1\n    update order")
        steps = [n for n in mod.nodes() if n["kind"] == "Assignment"]
        self.assertEqual("order.stock", steps[0]["target"])


# RFC-0056: the issue #206 `Reserve` program, with the business rejection
# written where the author means it.
FAIL_MODULE = """
entity Product
    field
        id UUID
        stock Integer
entity Order
    field
        id UUID
        quantity Integer
service ShopService
workflow Reserve
    find product
%s
    create order
"""

GUARDED_FAIL = "    when product.stock < input.quantity\n    fail %s"


def fail_ir(body):
    return ir(FAIL_MODULE % body)


class TestFailVerbLowering(unittest.TestCase):
    """RFC-0056: `fail <kebab-code>` lowers to a WorkflowStep with exactly one
    `Rejection` child carrying the code; every malformed code, and a `fail`
    no guard owns, is a compile error naming the rule."""

    def _rejections(self, doc):
        return [n for n in doc["nodes"] if n["kind"] == "Rejection"]

    def test_guarded_fail_lowers_to_one_rejection_with_the_code(self):
        doc = fail_ir(GUARDED_FAIL % "out-of-stock")
        nodes = by_id(doc)
        [rejection] = self._rejections(doc)
        self.assertEqual("out-of-stock", rejection["code"])
        self.assertEqual({"kind", "id", "code", "line"}, set(rejection))
        step = nodes[rejection["id"].rsplit(".", 1)[0]]
        self.assertEqual("WorkflowStep", step["kind"])
        self.assertEqual("fail out-of-stock", step["name"])
        self.assertEqual([rejection["id"]], step["children"])
        self.assertTrue(rejection["id"].endswith(".reject"))

    def test_the_lowered_document_validates_against_the_ir_schema(self):
        import jsonschema
        with open(os.path.join(REPO_ROOT, "schemas", "lir.schema.json"),
                  encoding="utf-8") as fh:
            schema = json.load(fh)
        jsonschema.validate(fail_ir(GUARDED_FAIL % "out-of-stock"), schema)

    def test_a_rejection_without_a_code_violates_the_ir_schema(self):
        import jsonschema
        with open(os.path.join(REPO_ROOT, "schemas", "lir.schema.json"),
                  encoding="utf-8") as fh:
            schema = json.load(fh)
        doc = fail_ir(GUARDED_FAIL % "out-of-stock")
        self._rejections(doc)[0].pop("code")
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(doc, schema)

    def test_a_single_character_code_is_kebab_case(self):
        [rejection] = self._rejections(fail_ir(GUARDED_FAIL % "x"))
        self.assertEqual("x", rejection["code"])

    def test_a_non_kebab_code_is_refused(self):
        for code in ("OutOfStock", "out_of_stock", "-out", "out-", "out--of",
                     "out-of-stock!"):
            with self.subTest(code=code):
                with self.assertRaises(LowerError) as ctx:
                    fail_ir(GUARDED_FAIL % code)
                self.assertIn("kebab-case", str(ctx.exception))
                self.assertIn(code, str(ctx.exception))

    def test_a_bare_fail_without_a_code_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            fail_ir("    when product.stock < input.quantity\n    fail")
        self.assertIn("needs a kebab-case code", str(ctx.exception))

    def test_trailing_words_after_the_code_are_refused(self):
        # Same rule `create order because reasons` already follows: words the
        # compiler would not act on are an error, never a silent no-op.
        with self.assertRaises(LowerError) as ctx:
            fail_ir(GUARDED_FAIL % "out-of-stock because empty")
        self.assertIn("one code", str(ctx.exception))
        self.assertIn("because", str(ctx.exception))

    def test_every_reserved_problem_code_is_refused(self):
        from lnpl.lexer import RESERVED_PROBLEM_CODES
        for code in RESERVED_PROBLEM_CODES:
            with self.subTest(code=code):
                with self.assertRaises(LowerError) as ctx:
                    fail_ir(GUARDED_FAIL % code)
                self.assertIn("reserved problem code", str(ctx.exception))

    def test_an_unguarded_fail_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            fail_ir("    fail out-of-stock")
        msg = str(ctx.exception)
        self.assertIn("not guarded", msg)
        self.assertIn("Reserve", msg)
        self.assertIn("RFC-0056", msg)

    def test_a_fail_under_repeat_is_refused(self):
        # `repeat N` runs its body at least once, so it cannot be false: the
        # `fail` would end every run failed, same as no guard at all.
        with self.assertRaises(LowerError) as ctx:
            fail_ir("    repeat 2\n    fail out-of-stock")
        self.assertIn("not guarded", str(ctx.exception))

    def test_a_fail_under_until_is_guarded(self):
        # `until` can run zero rounds (RFC-0014 example 2), so it can skip.
        doc = fail_ir("    until product.stock < input.quantity\n"
                      "    fail out-of-stock")
        self.assertEqual(["out-of-stock"],
                         [n["code"] for n in self._rejections(doc)])

    def test_a_fail_inside_a_guarded_block_is_guarded(self):
        doc = fail_ir("    when product.stock < input.quantity\n"
                      "    parallel\n"
                      "        note \"rejecting\"\n"
                      "        fail out-of-stock\n"
                      "    merge")
        self.assertEqual(["out-of-stock"],
                         [n["code"] for n in self._rejections(doc)])

    def test_a_fail_inside_an_unguarded_block_is_refused(self):
        with self.assertRaises(LowerError) as ctx:
            fail_ir("    parallel\n"
                    "        fail out-of-stock\n"
                    "    merge")
        self.assertIn("not guarded", str(ctx.exception))

    def test_fail_is_no_longer_an_unknown_verb(self):
        doc = lower(parse(FAIL_MODULE % (GUARDED_FAIL % "out-of-stock")), "t")
        self.assertEqual([], list(doc.diagnostics.by_code("unknown-verb")))

    def test_a_workflow_without_fail_lowers_with_no_rejection(self):
        doc = fail_ir("    when product.stock < input.quantity\n"
                      "    note \"short\"")
        self.assertEqual([], self._rejections(doc))


if __name__ == "__main__":
    unittest.main()

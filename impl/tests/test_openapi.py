"""IR -> OpenAPI: every fact in the output must trace to a node in the IR."""

import json
import os
import unittest

from lnpl import refinements
from lnpl.lower import LowerError, lower
from lnpl.openapi import (DECIMAL_FACET_KEYWORD, FACET_KEYWORD, NARROWING,
                          TYPE_SCHEMA, OpenApiError, _refinement_schema, _slug,
                          generate)
from lnpl.parser import parse
from lnpl.types import SEMANTIC_TYPES

SRC = """
capability postgres
capability redis
capability jwt
entity User
    field
        id UUID
        email Email
        password Password
        createdAt DateTime
service LoginService
    policy
        retry 3
        timeout 3s
    security
        jwt
    performance
        response < 50ms
        cache 5m
workflow Login
    validate input
    authenticate
    cache user
"""


# A module whose refinements are declared but used by no field. A user-declared
# `refine` is emitted whether or not a field uses it (emit-on-use is a preset
# rule only), so this fixture exercises the schema side without needing field
# resolution. Its three refinements between them carry all six facets.
REFINE_SRC = r"""
refine Handle of Text
    minLength 0
    maxLength 20
    pattern ^[a-z]+$
    enum draft
refine Score of Integer
    min 1
    max 100
    enum 1 2 3
refine Price of Decimal
    min 0
    max 99.5
    enum 1 2.5
entity Thing
    field
        a Text
service ThingService
workflow Touch
    validate input
"""


# Fields typed by all three presets plus a refinement the preset table has
# never heard of, and two fields sharing one refinement.
SHORTEN_SRC = """
refine Handle of Text
    minLength 3
entity Link
    field
        slug Slug
        target Url
        hits PositiveInteger
        owner Handle
        alias Handle
service ShortenService
workflow Shorten
    validate input
"""

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def spec_for(src=SRC):
    return generate(lower(parse(src), "login").to_document())


def schemas_for(src):
    return spec_for(src)["components"]["schemas"]


class TestStructure(unittest.TestCase):
    def setUp(self):
        self.spec = spec_for()

    def test_path_comes_from_the_service_and_workflow_names(self):
        self.assertEqual(list(self.spec["paths"]), ["/login-service/login"])

    def test_operation_lists_the_declared_steps(self):
        desc = self.spec["paths"]["/login-service/login"]["post"]["description"]
        self.assertIn("validate input -> authenticate -> cache user", desc)

    def test_request_body_references_the_validated_entity(self):
        op = self.spec["paths"]["/login-service/login"]["post"]
        ref = op["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        self.assertEqual(ref, "#/components/schemas/User")

    def test_generated_document_declares_its_provenance(self):
        self.assertIn("Generated from Semantic IR", self.spec["info"]["description"])


class TestConstraintProjection(unittest.TestCase):
    """Policy / Security / Performance are the only source of these fields."""

    def setUp(self):
        self.op = spec_for()["paths"]["/login-service/login"]["post"]

    def test_response_budget_becomes_the_slo_extension(self):
        self.assertEqual(self.op["x-response-slo-ms"], 50)

    def test_policy_becomes_retry_and_timeout_extensions(self):
        self.assertEqual(self.op["x-retry"], 3)
        self.assertEqual(self.op["x-timeout-ms"], 3000)

    def test_security_jwt_becomes_bearer_auth_and_a_401(self):
        self.assertEqual(self.op["security"], [{"bearerAuth": []}])
        self.assertIn("401", self.op["responses"])

    def test_no_security_declaration_means_no_security_block(self):
        src = SRC.replace("    security\n        jwt\n", "")
        op = spec_for(src)["paths"]["/login-service/login"]["post"]
        self.assertNotIn("security", op)
        self.assertNotIn("401", op["responses"])

    def test_absent_constraints_produce_no_extensions(self):
        src = SRC.replace("    performance\n        response < 50ms\n        cache 5m\n", "")
        op = spec_for(src)["paths"]["/login-service/login"]["post"]
        self.assertNotIn("x-response-slo-ms", op)


class TestSchemaMapping(unittest.TestCase):
    def setUp(self):
        self.schemas = spec_for()["components"]["schemas"]

    def test_password_is_write_only_with_a_password_format(self):
        pw = self.schemas["User"]["properties"]["password"]
        self.assertEqual(pw["format"], "password")
        self.assertTrue(pw["writeOnly"])

    def test_semantic_types_map_to_formats_not_bare_strings(self):
        props = self.schemas["User"]["properties"]
        self.assertEqual(props["id"]["format"], "uuid")
        self.assertEqual(props["email"]["format"], "email")
        self.assertEqual(props["createdAt"]["format"], "date-time")

    def test_fields_are_required_and_the_object_is_closed(self):
        schema = self.schemas["User"]
        self.assertEqual(sorted(schema["required"]),
                         ["createdAt", "email", "id", "password"])
        self.assertFalse(schema["additionalProperties"])

    def test_guarded_steps_are_reported_as_conditional(self):
        src = SRC.replace("    authenticate\n", "    when token missing\n    authenticate\n")
        op = spec_for(src)["paths"]["/login-service/login"]["post"]
        self.assertEqual(op["x-conditional-steps"], ["authenticate"])


class TestRefusals(unittest.TestCase):
    def test_an_unmapped_semantic_type_is_an_error_not_an_empty_schema(self):
        # Money maps; a hypothetical unmapped type must raise rather than emit {}.
        doc = lower(parse(SRC), "login").to_document()
        for node in doc["nodes"]:
            if node["kind"] == "Entity":
                node["fields"].append({"name": "x", "type": "NotAType"})
        with self.assertRaises(OpenApiError) as ctx:
            generate(doc)
        self.assertIn("no OpenAPI mapping", str(ctx.exception))

    def test_dangling_constraint_reference_is_an_error(self):
        doc = lower(parse(SRC), "login").to_document()
        for node in doc["nodes"]:
            if node["kind"] == "Service":
                node["constraints"] = ["policy.nope"]
        with self.assertRaises(OpenApiError) as ctx:
            generate(doc)
        self.assertIn("dangling", str(ctx.exception))


class TestRefinementSchemas(unittest.TestCase):
    """A Refinement node -> a named schema: the base schema, strengthened."""

    def setUp(self):
        self.schemas = schemas_for(REFINE_SRC)

    def test_text_facets_project_length_pattern_and_enum(self):
        # minLength / maxLength / pattern / enum -- four of the six facets.
        self.assertEqual(self.schemas["Handle"],
                         {"type": "string", "minLength": 0, "maxLength": 20,
                          "pattern": "^[a-z]+$", "enum": ["draft"]})

    def test_integer_facets_project_minimum_and_maximum(self):
        # min / max -- the remaining two facets, plus enum on a numeric base.
        self.assertEqual(self.schemas["Score"],
                         {"type": "integer", "format": "int64",
                          "minimum": 1, "maximum": 100, "enum": [1, 2, 3]})

    def test_the_three_presets_project_to_their_intended_schemas(self):
        # The preset nodes are emitted on use, so this task feeds the generator
        # the exact node literals the compiler produces (measured on 806ff38).
        self.assertEqual(
            _refinement_schema({"kind": "Refinement", "id": "refine.slug",
                                "name": "Slug", "base": "Text",
                                "facets": {"pattern": r"^[a-z0-9-]{1,64}$",
                                           "maxLength": 64}}),
            {"type": "string", "pattern": r"^[a-z0-9-]{1,64}$",
             "maxLength": 64})
        self.assertEqual(
            _refinement_schema({"kind": "Refinement", "id": "refine.url",
                                "name": "Url", "base": "Text",
                                "facets": {"pattern": r"^https?://[^\s]+$",
                                           "maxLength": 2048}}),
            {"type": "string", "pattern": r"^https?://[^\s]+$",
             "maxLength": 2048})
        self.assertEqual(
            _refinement_schema({"kind": "Refinement",
                                "id": "refine.positive.integer",
                                "name": "PositiveInteger", "base": "Integer",
                                "facets": {"min": 1}}),
            {"type": "integer", "format": "int64", "minimum": 1})

    def test_a_refinement_keeps_its_base_schema(self):
        # "Strengthens, never replaces": the base's own keywords survive.
        self.assertEqual(self.schemas["Handle"]["type"], "string")
        self.assertEqual(self.schemas["Score"]["format"], "int64")

    def test_a_declared_but_unused_refinement_still_gets_a_schema(self):
        # The compiler emits a user-declared refinement whether or not a field
        # uses it (emit-on-use is a preset rule). `Thing` uses none of these,
        # so what we expect here is presence, not absence.
        self.assertEqual([n["name"] for n in
                          lower(parse(REFINE_SRC), "login").to_document()["nodes"]
                          if n["kind"] == "Refinement"],
                         ["Handle", "Score", "Price"])
        self.assertTrue({"Handle", "Score", "Price"} <= set(self.schemas))

    def test_refinement_schemas_precede_entity_schemas(self):
        self.assertEqual(list(self.schemas),
                         ["Handle", "Score", "Price", "Thing"])

    def test_generate_does_not_mutate_the_shared_type_registry(self):
        # TYPE_SCHEMA is a module-level dict; writing facets into it would
        # poison every later call in the process.
        again = schemas_for(REFINE_SRC)
        self.assertEqual(TYPE_SCHEMA["Text"], {"type": "string"})
        self.assertEqual(SEMANTIC_TYPES["Text"]["openapi"], {"type": "string"})
        self.assertEqual(again["Thing"]["properties"]["a"], {"type": "string"})

    def test_a_refinement_with_exactly_one_facet(self):
        src = "refine One of Text\n    maxLength 1\n" + REFINE_SRC
        self.assertEqual(schemas_for(src)["One"],
                         {"type": "string", "maxLength": 1})

    def test_min_length_zero_survives_as_an_integer_zero(self):
        # A falsy facet value must not be dropped.
        self.assertEqual(self.schemas["Handle"]["minLength"], 0)
        self.assertIsInstance(self.schemas["Handle"]["minLength"], int)

    def test_enum_with_a_single_member_stays_a_one_item_list(self):
        self.assertEqual(self.schemas["Handle"]["enum"], ["draft"])


class TestDecimalFacets(unittest.TestCase):
    """`Decimal` encodes as a string, so numeric keywords do not apply to it."""

    def setUp(self):
        self.schemas = schemas_for(REFINE_SRC)

    def test_decimal_numeric_facets_become_extensions(self):
        self.assertEqual(self.schemas["Price"],
                         {"type": "string", "format": "decimal",
                          "x-min": 0, "x-max": 99.5, "x-enum": [1, 2.5]})

    def test_decimal_schema_carries_no_numeric_json_schema_keyword(self):
        self.assertNotIn("minimum", self.schemas["Price"])
        self.assertNotIn("maximum", self.schemas["Price"])
        self.assertNotIn("enum", self.schemas["Price"])

    def test_decimal_base_is_string_encoded(self):
        # The premise the extension mapping rests on. If Decimal ever encodes
        # as a number, this reddens first and the mapping must be revisited.
        self.assertEqual(TYPE_SCHEMA["Decimal"],
                         {"type": "string", "format": "decimal"})

    def test_a_numeric_keyword_on_a_string_schema_would_validate_nothing(self):
        # Why the extension mapping exists. `minimum` is ignored on a string
        # instance, and a numeric `enum` makes the schema unsatisfiable.
        from jsonschema import Draft202012Validator as V
        self.assertTrue(
            V({"type": "string", "format": "decimal", "minimum": 1})
            .is_valid("-99"))
        self.assertFalse(V({"type": "string", "enum": [1, 2]}).is_valid("1"))

    def test_an_integer_base_uses_real_json_schema_keywords(self):
        # The contrast: on Integer the projection really is enforced.
        from jsonschema import Draft202012Validator as V
        self.assertFalse(V(self.schemas["Score"]).is_valid(0))
        self.assertTrue(V(self.schemas["Score"]).is_valid(1))


class TestBaseKeywordConflict(unittest.TestCase):
    """A facet composes onto a keyword the base fixes -- by intersecting it.

    RFC-0001 A.6.2: a refinement NARROWS its base. So a facet the base already
    constrains has an answer per keyword, and the answers differ: an upper
    bound intersects by taking the smaller, a lower bound by taking the larger,
    and two patterns intersect only as a conjunction. A facet that would widen
    the base is refused -- widening is not narrowing.
    """

    TAIL = "entity Thing\n    field\n        a Text\nservice S\nworkflow W\n    validate input\n"

    def test_a_narrowing_pattern_composes_with_the_bases_pattern(self):
        # WAS `test_replacing_a_base_pattern_is_refused`, which pinned the
        # defect: A.6.3 (rfcs/0001-semantic-ir.md:303) puts `Phone` in the text
        # category with `pattern` allowed and adds "개별 타입 예외는 두지
        # 않는다", so a country-specific phone number is a legal refinement --
        # the single most obvious one anyone would write on this base. The
        # runtime already composes base+facet as an intersection; only the
        # generator refused. JSON Schema has no "matches both patterns"
        # keyword, so the intersection is an `allOf` and the base's pattern
        # keeps its place.
        from jsonschema import Draft202012Validator as V
        src = ("refine KoreanPhone of Phone\n    pattern ^\\+82[0-9]{9,10}$\n"
               + self.TAIL)
        schema = schemas_for(src)["KoreanPhone"]
        self.assertEqual(schema,
                         {"type": "string", "pattern": r"^\+[1-9]\d{1,14}$",
                          "allOf": [{"pattern": r"^\+82[0-9]{9,10}$"}]})
        self.assertTrue(V(schema).is_valid("+821012345678"))
        self.assertFalse(V(schema).is_valid("+14155550100"))
        self.assertFalse(V(schema).is_valid("+8210"))

    def test_two_disjoint_patterns_are_composed_but_not_detected(self):
        # A stated limitation, pinned so it cannot be lost silently. This is
        # the input the old `test_replacing_a_base_pattern_is_refused` used:
        # `^[0-9]+$` and the base's `^\+...` share no string, so the `allOf`
        # below is uninhabited -- and `_reject_uninhabited` does not attempt
        # regex satisfiability, so it is emitted. Refusing it would require
        # deciding regex disjointness, which is out of scope by decision.
        from jsonschema import Draft202012Validator as V
        src = "refine Local of Phone\n    pattern ^[0-9]+$\n" + self.TAIL
        schema = schemas_for(src)["Local"]
        self.assertEqual(schema["allOf"], [{"pattern": "^[0-9]+$"}])
        for probe in ("0101234", "+821012345678", "+14155550100", ""):
            self.assertFalse(V(schema).is_valid(probe), probe)

    def test_a_length_facet_that_contradicts_the_bases_other_bound_is_refused(self):
        # WAS `test_relaxing_a_base_keyword_is_refused`. Still refused, for the
        # true reason instead of a false one: `maxLength 2` NARROWS the base's
        # `maxLength 3` (so the old "you may not relax it" was misdescribing
        # its own input), but `Currency` also fixes `minLength 3`, and no
        # string is both >= 3 and <= 2 long.
        src = "refine Ccy of Currency\n    maxLength 2\n" + self.TAIL
        with self.assertRaises(OpenApiError) as ctx:
            spec_for(src)
        self.assertIn("unsatisfiable", str(ctx.exception))
        self.assertIn("minLength 3 exceeds maxLength 2", str(ctx.exception))

    def test_a_narrowing_minlength_composes_and_is_then_judged_on_its_merits(self):
        # `Currency` + `minLength` is one of the three combinations A.6.3
        # permits and the old rule refused outright. It now composes (4 is a
        # narrowing of the base's 3) and is refused only by what the result
        # says: 4 <= len <= 3 admits nothing.
        src = "refine Ccy of Currency\n    minLength 4\n" + self.TAIL
        with self.assertRaises(OpenApiError) as ctx:
            spec_for(src)
        self.assertIn("unsatisfiable", str(ctx.exception))
        self.assertIn("minLength 4 exceeds maxLength 3", str(ctx.exception))

    def test_a_widening_minlength_is_refused(self):
        # The direction that is not a narrowing at all. `minLength 2` admits
        # strings the base rejects, and A.6.2 has no such thing.
        src = "refine Ccy of Currency\n    minLength 2\n" + self.TAIL
        with self.assertRaises(OpenApiError) as ctx:
            spec_for(src)
        self.assertIn("widens", str(ctx.exception))
        self.assertIn("narrows its base", str(ctx.exception))
        self.assertIn("Currency", str(ctx.exception))

    def test_a_widening_maxlength_is_refused(self):
        src = "refine Ccy of Currency\n    maxLength 4\n" + self.TAIL
        with self.assertRaises(OpenApiError) as ctx:
            spec_for(src)
        self.assertIn("widens", str(ctx.exception))
        self.assertIn("A.6.2", str(ctx.exception))

    def test_restating_the_base_value_is_allowed(self):
        src = "refine Iso of Currency\n    maxLength 3\n" + self.TAIL
        self.assertEqual(schemas_for(src)["Iso"],
                         {"type": "string", "minLength": 3, "maxLength": 3})

    def test_restating_the_bases_lower_bound_is_allowed(self):
        # The other half of the zero-width narrowing: restating a lower bound
        # is the boundary between narrowing and widening, and is legal.
        src = "refine Iso of Currency\n    minLength 3\n" + self.TAIL
        self.assertEqual(schemas_for(src)["Iso"],
                         {"type": "string", "minLength": 3, "maxLength": 3})

    def test_restating_the_bases_pattern_needs_no_allof(self):
        # The third zero-width narrowing, and the one that would otherwise emit
        # a redundant conjunct: an identical pattern is already the
        # intersection, so it composes in place.
        src = ("refine Same of Phone\n    pattern ^\\+[1-9]\\d{1,14}$\n"
               + self.TAIL)
        self.assertEqual(schemas_for(src)["Same"],
                         {"type": "string", "pattern": r"^\+[1-9]\d{1,14}$"})

    def test_a_base_without_the_keyword_takes_the_facet(self):
        src = "refine Tag of Text\n    maxLength 3\n" + self.TAIL
        self.assertEqual(schemas_for(src)["Tag"],
                         {"type": "string", "maxLength": 3})

    def test_a_pattern_on_a_base_that_carries_none_needs_no_allof(self):
        # What made the old rule fire inconsistently: `UUID`/`Email`/`DateTime`
        # carry their regex as a non-assertive `format`, so refining them with
        # a `pattern` always worked, while `Phone` -- same A.6.3 category, same
        # intent -- was refused for carrying a real `pattern`. The new rule
        # asks "does this narrow?", which is answerable either way; these two
        # keep composing exactly as before, with no `allOf`.
        uuid = schemas_for("refine U of UUID\n    pattern ^a.*$\n" + self.TAIL)["U"]
        self.assertEqual(uuid, {"type": "string", "format": "uuid",
                                "pattern": "^a.*$"})
        email = schemas_for("refine E of Email\n    pattern ^a.*$\n" + self.TAIL)["E"]
        self.assertEqual(email, {"type": "string", "format": "email",
                                 "pattern": "^a.*$"})

    def test_the_narrowing_table_states_a_direction_per_keyword(self):
        # The rule itself. No base among the 18 carries `minimum`/`maximum`, so
        # those two rows are unreachable through a base today and are asserted
        # here as the rule rather than through a composition.
        self.assertEqual(NARROWING, {"minLength": max, "minimum": max,
                                     "maxLength": min, "maximum": min})
        self.assertEqual(sorted(k for k, v in NARROWING.items() if v is min),
                         ["maxLength", "maximum"])

    def test_no_facet_a_base_admits_is_refused(self):
        # The review's 18x6 sweep, as a test: every combination A.6.3 permits
        # must compose. Values are chosen to narrow -- for a bound the base
        # already fixes, the only inhabited narrowing `Currency` has is its own
        # value, so restating it is the narrowing of zero (see the two tests
        # above).
        combinations, refused = 0, []
        for base in refinements.BASE_CATEGORY:
            base_schema = TYPE_SCHEMA[base]
            values = {"minLength": base_schema.get("minLength", 1),
                      "maxLength": base_schema.get("maxLength", 8),
                      "pattern": "^[a-z]+$", "min": 1, "max": 100,
                      "enum": [1] if base in ("Integer", "Decimal") else ["a"]}
            for facet in sorted(refinements.facets_for_base(base)):
                combinations += 1
                try:
                    _refinement_schema(_refine("R", base, {facet: values[facet]}))
                except OpenApiError as exc:
                    refused.append("%s.%s -> %s" % (base, facet, exc))
        self.assertEqual(combinations, 42)
        self.assertEqual(refused, [])


class TestCompilerOwnedRefusals(unittest.TestCase):
    """Cases the compiler refuses first, so they never reach the generator.

    The generator refuses them too (`TestGeneratorOwnedRefusals`) -- these
    assert which layer speaks first for a `.lnpl` source, not that the other
    layer is silent.
    """

    TAIL = "entity Thing\n    field\n        a Text\nservice S\nworkflow W\n    validate input\n"

    def test_a_facet_on_a_boolean_base_never_reaches_the_generator(self):
        with self.assertRaises(LowerError) as ctx:
            lower(parse("refine Flag of Boolean\n    maxLength 3\n" + self.TAIL),
                  "login")
        self.assertIn("does not apply to base", str(ctx.exception))
        self.assertIn("Boolean", str(ctx.exception))

    def test_a_facet_outside_the_vocabulary_never_reaches_the_generator(self):
        with self.assertRaises(LowerError) as ctx:
            lower(parse("refine X of Text\n    maxLenght 8\n" + self.TAIL),
                  "login")
        self.assertIn("unknown facet", str(ctx.exception))

    def test_every_facet_name_has_a_projection(self):
        # Coverage. Assert the source list's size first: a vocabulary that
        # parsed to nothing would make the set equality pass vacuously.
        self.assertEqual(len(refinements.FACET_NAMES), 6)
        self.assertEqual(set(FACET_KEYWORD), set(refinements.FACET_NAMES))

    def test_every_facet_a_decimal_admits_has_a_projection(self):
        self.assertEqual(set(DECIMAL_FACET_KEYWORD),
                         set(refinements.CATEGORY_FACETS["numeric"]))


def _refine(name, base, facets):
    """A Refinement node as the compiler serializes one (RFC-0001 A.6.2).

    `lower` refuses most of the inputs below before they reach the generator,
    so these are hand-built -- which is the point: `generate` is a public entry
    point and RFC-0001 A.7 puts invariant ⓓ outside what the IR JSON Schema
    checks, so a schema-valid document can carry them.
    """
    return {"kind": "Refinement", "id": "refine.%s" % name.lower(),
            "name": name, "base": base, "facets": facets}


class TestGeneratorOwnedRefusals(unittest.TestCase):
    """A facet outside the base's category is an `OpenApiError`, not a crash.

    `openapi.py`'s contract is that it raises `OpenApiError` for anything the
    IR states that it cannot express. Before this, `Decimal` + a length facet
    left through a raw `KeyError`, and `Boolean`/`Json` + a length facet were
    emitted as if they meant something.
    """

    def test_a_length_facet_on_a_decimal_base_is_an_openapi_error(self):
        # The sharp one: DECIMAL_FACET_KEYWORD carries three of the six facet
        # names, so this used to be an uncaught KeyError('minLength').
        with self.assertRaises(OpenApiError) as ctx:
            _refinement_schema(_refine("Bad", "Decimal", {"minLength": 3}))
        self.assertIn("does not apply to base", str(ctx.exception))
        self.assertIn("Decimal", str(ctx.exception))
        self.assertIn("minLength", str(ctx.exception))

    def test_a_facet_on_a_boolean_base_is_an_openapi_error(self):
        # A.6.3: the boolean category admits no facet -- it is closed at two
        # values. This used to emit {"type": "boolean", "maxLength": 3}.
        with self.assertRaises(OpenApiError) as ctx:
            _refinement_schema(_refine("Bad", "Boolean", {"maxLength": 3}))
        self.assertIn("does not apply to base", str(ctx.exception))
        self.assertIn("Boolean", str(ctx.exception))

    def test_a_facet_on_a_composite_base_is_an_openapi_error(self):
        # A.6.3: composite bases admit no facet in v0.1 -- there is no notation
        # for an inner field. `Json` used to emit {"maxLength": 3}: no type at
        # all, so every keyword the base would have contributed was absent too.
        with self.assertRaises(OpenApiError) as ctx:
            _refinement_schema(_refine("Bad", "Json", {"maxLength": 3}))
        self.assertIn("does not apply to base", str(ctx.exception))
        self.assertIn("Json", str(ctx.exception))

    def test_a_facet_outside_the_vocabulary_is_an_openapi_error(self):
        with self.assertRaises(OpenApiError) as ctx:
            _refinement_schema(_refine("Bad", "Text", {"maxLenght": 8}))
        self.assertIn("maxLenght", str(ctx.exception))

    def test_a_base_outside_the_eighteen_is_an_openapi_error(self):
        # `facets_for_base` raises KeyError for a name outside the 18, which
        # would be the same contract break one line further down.
        with self.assertRaises(OpenApiError) as ctx:
            _refinement_schema(_refine("Bad", "NotAType", {"maxLength": 3}))
        self.assertIn("NotAType", str(ctx.exception))
        self.assertIn("A.6.2", str(ctx.exception))

    def test_the_refusal_surfaces_through_the_public_entry_point(self):
        # Not just the private helper: `generate` is what `cli.cmd_openapi`
        # calls, and what this file's other tests call on hand-built documents.
        doc = lower(parse(SRC), "login").to_document()
        doc["nodes"].insert(0, _refine("Bad", "Decimal", {"maxLength": 3}))
        with self.assertRaises(OpenApiError) as ctx:
            generate(doc)
        self.assertIn("does not apply to base", str(ctx.exception))

    def test_an_in_category_facet_still_composes_on_every_category(self):
        # The guard must refuse the forbidden without over-refusing the legal.
        self.assertEqual(_refinement_schema(_refine("T", "Text", {"maxLength": 3})),
                         {"type": "string", "maxLength": 3})
        self.assertEqual(_refinement_schema(_refine("N", "Integer", {"min": 1})),
                         {"type": "integer", "format": "int64", "minimum": 1})
        self.assertEqual(_refinement_schema(_refine("D", "Decimal", {"min": 1})),
                         {"type": "string", "format": "decimal", "x-min": 1})

    def test_every_facet_every_base_admits_has_a_keyword(self):
        # What makes the guard a total fix rather than a per-base patch: past
        # it, the keyword lookup cannot KeyError for ANY of the 18 bases. A new
        # base whose category admits a facet with no projection reddens here.
        self.assertEqual(len(refinements.BASE_CATEGORY), 18)
        for base in refinements.BASE_CATEGORY:
            keywords = DECIMAL_FACET_KEYWORD if base == "Decimal" else FACET_KEYWORD
            missing = sorted(f for f in refinements.facets_for_base(base)
                             if f not in keywords)
            self.assertEqual(missing, [], "base %s" % base)


class TestUninhabitedRefusals(unittest.TestCase):
    """A composition no instance can satisfy is a mistake, not a type.

    RFC-0001 A.6.2: a refinement narrows its base. Narrowing to nothing emits a
    contract that rejects 100% of traffic, and `check_schema` does not catch it
    -- an uninhabited schema is still a well-formed one.
    """

    TAIL = ("entity Thing\n    field\n        a Text\n"
            "service S\nworkflow W\n    validate input\n")

    def test_a_text_bound_pair_that_crosses_is_refused(self):
        # Reachable from a `.lnpl` file: the compiler accepts this module.
        src = "refine R of Text\n    minLength 10\n    maxLength 5\n" + self.TAIL
        with self.assertRaises(OpenApiError) as ctx:
            spec_for(src)
        self.assertIn("unsatisfiable", str(ctx.exception))
        self.assertIn("minLength", str(ctx.exception))
        self.assertIn("maxLength", str(ctx.exception))

    def test_a_numeric_bound_pair_that_crosses_is_refused(self):
        src = "refine R of Integer\n    min 100\n    max 1\n" + self.TAIL
        with self.assertRaises(OpenApiError) as ctx:
            spec_for(src)
        self.assertIn("unsatisfiable", str(ctx.exception))
        self.assertIn("minimum", str(ctx.exception))

    def test_a_decimal_bound_pair_that_crosses_is_refused(self):
        # `Decimal`'s bounds ride `x-min`/`x-max`, which no validator enforces
        # -- but a contract that states min 100 and max 1 is contradictory
        # whether or not a validator reads it.
        src = "refine R of Decimal\n    min 100\n    max 1\n" + self.TAIL
        with self.assertRaises(OpenApiError) as ctx:
            spec_for(src)
        self.assertIn("unsatisfiable", str(ctx.exception))
        self.assertIn("x-min", str(ctx.exception))

    def test_bounds_that_meet_exactly_are_inhabited_and_allowed(self):
        # The boundary: min == max admits exactly one length. The check must be
        # `>`, not `>=`, or this legal composition dies with it.
        from jsonschema import Draft202012Validator as V
        src = "refine R of Text\n    minLength 5\n    maxLength 5\n" + self.TAIL
        schema = schemas_for(src)["R"]
        self.assertEqual(schema,
                         {"type": "string", "minLength": 5, "maxLength": 5})
        self.assertTrue(V(schema).is_valid("abcde"))
        self.assertFalse(V(schema).is_valid("abcd"))
        self.assertFalse(V(schema).is_valid("abcdef"))

    def test_bounds_one_step_past_meeting_are_refused(self):
        # One past the boundary above.
        src = "refine R of Text\n    minLength 6\n    maxLength 5\n" + self.TAIL
        with self.assertRaises(OpenApiError) as ctx:
            spec_for(src)
        self.assertIn("unsatisfiable", str(ctx.exception))

    def test_numeric_bounds_that_meet_at_zero_are_allowed(self):
        # Falsy bounds are values, not absences.
        src = "refine R of Integer\n    min 0\n    max 0\n" + self.TAIL
        self.assertEqual(schemas_for(src)["R"],
                         {"type": "integer", "format": "int64",
                          "minimum": 0, "maximum": 0})

    def test_an_empty_enum_is_refused(self):
        # Hand-built: `lower` enforces A.7 invariant ⓒ (enum has >= 1 member)
        # first, and `lir.schema.json` deliberately does not (A.7 says
        # `minItems` 미사용), so a schema-valid document can carry this.
        with self.assertRaises(OpenApiError) as ctx:
            _refinement_schema(_refine("R", "Text", {"enum": []}))
        self.assertIn("unsatisfiable", str(ctx.exception))
        self.assertIn("empty enum", str(ctx.exception))

    def test_a_single_member_enum_is_allowed(self):
        from jsonschema import Draft202012Validator as V
        src = "refine R of Text\n    enum draft\n" + self.TAIL
        schema = schemas_for(src)["R"]
        self.assertEqual(schema, {"type": "string", "enum": ["draft"]})
        self.assertTrue(V(schema).is_valid("draft"))
        self.assertFalse(V(schema).is_valid("published"))

    def test_a_numeric_enum_on_a_text_base_is_refused(self):
        # `refine HttpStatus of Text` + `enum 200 404` is a thing a user would
        # write, and it used to emit {"type": "string", "enum": [200, 404]} --
        # a request schema that rejects every payload. A.6.3 permits `enum` on
        # both the text and numeric categories without tying the member type to
        # the base, and `lower._enum_value` resolves 200 to an int, so the
        # mismatch is constructible from a `.lnpl` file.
        src = "refine HttpStatus of Text\n    enum 200 404\n" + self.TAIL
        with self.assertRaises(OpenApiError) as ctx:
            spec_for(src)
        self.assertIn("unsatisfiable", str(ctx.exception))
        self.assertIn("[200, 404]", str(ctx.exception))
        self.assertIn("string", str(ctx.exception))

    def test_a_string_enum_on_a_numeric_base_is_refused(self):
        # The other direction.
        src = "refine R of Integer\n    enum alpha beta\n" + self.TAIL
        with self.assertRaises(OpenApiError) as ctx:
            spec_for(src)
        self.assertIn("unsatisfiable", str(ctx.exception))
        self.assertIn("integer", str(ctx.exception))

    def test_the_compiler_still_accepts_what_the_generator_now_refuses(self):
        # The premise of the two tests above: this is a generator-side refusal
        # of a module the rest of the toolchain accepts, not a parse error. If
        # the check ever moves into `lower`, this reddens and says so.
        src = "refine HttpStatus of Text\n    enum 200 404\n" + self.TAIL
        node = [n for n in lower(parse(src), "login").to_document()["nodes"]
                if n["kind"] == "Refinement"][0]
        self.assertEqual(node["facets"], {"enum": [200, 404]})

    def test_a_boolean_enum_member_is_refused(self):
        # Python's bool subclasses int, so a naive isinstance(m, int) admits
        # `True` onto an integer base -- where JSON `true` is not a number
        # instance and validates against nothing.
        with self.assertRaises(OpenApiError) as ctx:
            _refinement_schema(_refine("R", "Integer", {"enum": [True]}))
        self.assertIn("unsatisfiable", str(ctx.exception))
        self.assertIn("[True]", str(ctx.exception))

    def test_only_the_mismatched_members_are_named(self):
        with self.assertRaises(OpenApiError) as ctx:
            _refinement_schema(_refine("R", "Text", {"enum": ["ok", 200]}))
        self.assertIn("[200]", str(ctx.exception))
        self.assertNotIn("'ok'", str(ctx.exception))

    def test_a_matching_enum_composes_on_both_categories(self):
        from jsonschema import Draft202012Validator as V
        text = schemas_for("refine R of Text\n    enum a b\n" + self.TAIL)["R"]
        self.assertEqual(text, {"type": "string", "enum": ["a", "b"]})
        self.assertTrue(V(text).is_valid("a"))
        self.assertFalse(V(text).is_valid("c"))
        num = schemas_for("refine N of Integer\n    enum 1 2\n" + self.TAIL)["N"]
        self.assertEqual(num, {"type": "integer", "format": "int64",
                               "enum": [1, 2]})
        self.assertTrue(V(num).is_valid(1))
        self.assertFalse(V(num).is_valid(3))

    def test_a_decimal_enum_is_numeric_by_design_and_not_type_checked(self):
        # `Decimal` encodes as a string but its members are legitimately
        # numeric, and they ride `x-enum`. Applying the member-type rule here
        # would refuse the correct case, so the check keys on `enum` only.
        src = "refine R of Decimal\n    enum 1 2.5\n" + self.TAIL
        self.assertEqual(schemas_for(src)["R"],
                         {"type": "string", "format": "decimal",
                          "x-enum": [1, 2.5]})

    def test_the_shipped_module_still_generates(self):
        # The check must not over-refuse: every refinement the real example
        # declares still composes.
        self.assertEqual(sorted(schemas_for(SHORTEN_SRC)),
                         ["Handle", "Link", "PositiveInteger", "Slug", "Url"])


def _all_refs(obj):
    """Every `$ref` string anywhere in a generated document."""
    if isinstance(obj, dict):
        out = []
        for key, value in obj.items():
            if key == "$ref":
                out.append(value)
            else:
                out.extend(_all_refs(value))
        return out
    if isinstance(obj, list):
        return [r for item in obj for r in _all_refs(item)]
    return []


class TestRefinementFields(unittest.TestCase):
    """A field typed by a refinement references its named schema."""

    def setUp(self):
        self.schemas = schemas_for(SHORTEN_SRC)

    def test_a_refinement_typed_field_is_a_bare_ref(self):
        # Whole-dict equality, so a sibling keyword would redden this.
        self.assertEqual(self.schemas["Link"]["properties"]["slug"],
                         {"$ref": "#/components/schemas/Slug"})

    def test_the_three_presets_produce_the_schemas_the_fields_point_at(self):
        self.assertEqual(self.schemas["Slug"],
                         {"type": "string", "pattern": r"^[a-z0-9-]{1,64}$",
                          "maxLength": 64})
        self.assertEqual(self.schemas["Url"],
                         {"type": "string", "pattern": r"^https?://[^\s]+$",
                          "maxLength": 2048})
        self.assertEqual(self.schemas["PositiveInteger"],
                         {"type": "integer", "format": "int64", "minimum": 1})

    def test_a_user_declared_refinement_the_registry_never_heard_of_works(self):
        # `Handle` exists only as a node in the lowered document, so a
        # generator reading the built-in preset table would drop it.
        self.assertNotIn("Handle", refinements.PRESETS)
        self.assertEqual(self.schemas["Handle"],
                         {"type": "string", "minLength": 3})
        self.assertEqual(self.schemas["Link"]["properties"]["owner"],
                         {"$ref": "#/components/schemas/Handle"})

    def test_two_fields_share_one_schema(self):
        self.assertEqual(list(self.schemas).count("Handle"), 1)
        self.assertEqual(self.schemas["Link"]["properties"]["owner"],
                         self.schemas["Link"]["properties"]["alias"])

    def test_base_typed_fields_are_still_inline(self):
        self.assertEqual(schemas_for(SRC)["User"]["properties"]["email"],
                         {"type": "string", "format": "email"})

    def test_a_refinement_typed_field_is_still_required(self):
        self.assertEqual(sorted(self.schemas["Link"]["required"]),
                         ["alias", "hits", "owner", "slug", "target"])

    def test_an_unmapped_type_is_still_refused_beside_the_refinements(self):
        doc = lower(parse(SHORTEN_SRC), "login").to_document()
        for node in doc["nodes"]:
            if node["kind"] == "Entity":
                node["fields"].append({"name": "x", "type": "NotAType"})
        with self.assertRaises(OpenApiError) as ctx:
            generate(doc)
        self.assertIn("no OpenAPI mapping", str(ctx.exception))


class TestRefResolution(unittest.TestCase):
    """Every `$ref` must resolve inside the document that carries it."""

    def test_every_ref_in_the_document_resolves(self):
        spec = spec_for(SHORTEN_SRC)
        refs = _all_refs(spec)
        # Name them rather than count them: an empty sweep would pass the loop
        # below while proving nothing, and the requestBody ref is the reason
        # this sweeps the whole document instead of just the schemas.
        self.assertEqual(sorted(refs), [
            "#/components/schemas/Handle", "#/components/schemas/Handle",
            "#/components/schemas/Link", "#/components/schemas/PositiveInteger",
            "#/components/schemas/Slug", "#/components/schemas/Url"])
        for ref in refs:
            self.assertTrue(ref.startswith("#/components/schemas/"), ref)
            self.assertIn(ref.rsplit("/", 1)[1], spec["components"]["schemas"])

    def test_every_named_schema_is_a_valid_json_schema(self):
        from jsonschema import Draft202012Validator as V
        schemas = schemas_for(SHORTEN_SRC)
        self.assertEqual(len(schemas), 5)
        for schema in schemas.values():
            V.check_schema(schema)

    def test_a_document_without_refinements_has_only_the_entity_ref(self):
        self.assertEqual(_all_refs(spec_for()), ["#/components/schemas/User"])


class TestNameCollision(unittest.TestCase):
    """An entity and a refinement share one `components/schemas` namespace."""

    SRC = """
refine Link of Text
    maxLength 8
entity Link
    field
        code Text
service S
workflow W
    validate input
"""

    def test_the_compiler_does_not_reject_this_collision(self):
        # RFC-0001 A.7 invariant 5 lists the 18 base types, the presets and
        # other refinements -- not entity names. So the compiler lets this
        # through and the generator is the last line of defence. If the
        # compiler ever starts rejecting it, this reddens first.
        doc = lower(parse(self.SRC), "login").to_document()
        self.assertEqual(sorted(n["kind"] for n in doc["nodes"]
                                if n.get("name") == "Link"),
                         ["Entity", "Refinement"])

    def test_an_entity_named_like_a_refinement_is_refused(self):
        with self.assertRaises(OpenApiError) as ctx:
            spec_for(self.SRC)
        self.assertIn("name collision", str(ctx.exception))
        self.assertIn("Link", str(ctx.exception))

    def test_a_merely_similar_name_is_not_a_collision(self):
        schemas = schemas_for(self.SRC.replace("refine Link of",
                                               "refine Linkish of"))
        self.assertEqual(list(schemas), ["Linkish", "Link"])


class TestNoRefinementRegression(unittest.TestCase):
    """A module with no refinement must generate exactly what it did before."""

    def _login(self):
        with open(os.path.join(REPO_ROOT, "examples", "login.lnpl"),
                  encoding="utf-8") as fh:
            return lower(parse(fh.read()), "login").to_document()

    def test_the_login_document_declares_no_refinement(self):
        # What the byte-identity check below is allowed to assume. Once login
        # gains a refinement both tests redden together, as they should.
        self.assertEqual([n for n in self._login()["nodes"]
                          if n["kind"] == "Refinement"], [])

    def test_login_generates_byte_identically_to_the_committed_golden(self):
        with open(os.path.join(REPO_ROOT, "examples", "login.openapi.json"),
                  encoding="utf-8") as fh:
            golden = fh.read()
        emitted = json.dumps(generate(self._login()), indent=2,
                             ensure_ascii=False)
        self.assertEqual(emitted.strip(), golden.strip())

    def test_no_refinement_means_no_extra_schema_keys(self):
        self.assertEqual(list(generate(self._login())["components"]["schemas"]),
                         ["User"])


class TestSlug(unittest.TestCase):
    """`_slug` derives the path and the operationId, so its word split is API.

    It used to start a new word at every capital, so an acronym exploded:
    `APIKey` -> `a-p-i-key`. The rule is the one `lower.split_pascal` uses --
    a capital starts a word only when it is not inside a run of capitals, or is
    the last capital of a run before a lowercase letter.
    """

    def test_an_acronym_stays_one_word(self):
        self.assertEqual(_slug("APIKey"), "api-key")
        self.assertEqual(_slug("HTTPServer"), "http-server")
        self.assertEqual(_slug("UserID"), "user-id")

    def test_ordinary_pascal_case_is_unchanged(self):
        self.assertEqual(_slug("ShortenService"), "shorten-service")
        self.assertEqual(_slug("LoginService"), "login-service")
        self.assertEqual(_slug("Login"), "login")

    def test_boundaries(self):
        self.assertEqual(_slug(""), "")
        self.assertEqual(_slug("A"), "a")
        self.assertEqual(_slug("AB"), "ab")        # a run with nothing after it
        self.assertEqual(_slug("ABc"), "a-bc")     # the run's last capital splits
        self.assertEqual(_slug("aB"), "a-b")       # lowercase then a capital
        self.assertEqual(_slug("lower"), "lower")

    def test_both_consumers_of_the_slug_agree(self):
        # `_slug` feeds the path AND the operationId; a fix in one place must
        # move both, or a generated client's method name stops matching its URL.
        src = ("entity Thing\n    field\n        a Text\n"
               "service APIService\nworkflow FetchHTTPDoc\n    validate input\n")
        spec = spec_for(src)
        self.assertEqual(list(spec["paths"]), ["/api-service/fetch-http-doc"])
        self.assertEqual(
            spec["paths"]["/api-service/fetch-http-doc"]["post"]["operationId"],
            "api_service_fetch_http_doc")

    def test_every_committed_openapi_artifact_still_regenerates_identically(self):
        # The regression this change could plausibly cause: no example name
        # carries an acronym, so all three must be byte-identical. If one moves,
        # the fix is broader than believed.
        for name in ("login", "shorten", "checkout"):
            with self.subTest(example=name):
                with open(os.path.join(REPO_ROOT, "examples", name + ".lnpl"),
                          encoding="utf-8") as fh:
                    doc = lower(parse(fh.read()), name).to_document()
                with open(os.path.join(REPO_ROOT, "examples",
                                       name + ".openapi.json"),
                          encoding="utf-8") as fh:
                    golden = fh.read()
                emitted = json.dumps(generate(doc), indent=2, ensure_ascii=False)
                self.assertEqual(emitted.strip(), golden.strip())


if __name__ == "__main__":
    unittest.main()

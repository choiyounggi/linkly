"""IR -> OpenAPI: every fact in the output must trace to a node in the IR."""

import json
import os
import unittest

from lnpl import refinements
from lnpl.lower import LowerError, lower
from lnpl.openapi import (DECIMAL_FACET_KEYWORD, FACET_KEYWORD, TYPE_SCHEMA,
                          OpenApiError, _refinement_schema, generate)
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
    """A facet may not quietly replace a keyword the base already fixes."""

    TAIL = "entity Thing\n    field\n        a Text\nservice S\nworkflow W\n    validate input\n"

    def test_relaxing_a_base_keyword_is_refused(self):
        src = "refine Ccy of Currency\n    maxLength 2\n" + self.TAIL
        with self.assertRaises(OpenApiError) as ctx:
            spec_for(src)
        self.assertIn("strengthens its base", str(ctx.exception))
        self.assertIn("Currency", str(ctx.exception))

    def test_replacing_a_base_pattern_is_refused(self):
        src = "refine Local of Phone\n    pattern ^[0-9]+$\n" + self.TAIL
        with self.assertRaises(OpenApiError) as ctx:
            spec_for(src)
        self.assertIn("strengthens its base", str(ctx.exception))
        self.assertIn("Phone", str(ctx.exception))

    def test_restating_the_base_value_is_allowed(self):
        src = "refine Iso of Currency\n    maxLength 3\n" + self.TAIL
        self.assertEqual(schemas_for(src)["Iso"],
                         {"type": "string", "minLength": 3, "maxLength": 3})

    def test_a_base_without_the_keyword_takes_the_facet(self):
        src = "refine Tag of Text\n    maxLength 3\n" + self.TAIL
        self.assertEqual(schemas_for(src)["Tag"],
                         {"type": "string", "maxLength": 3})


class TestCompilerOwnedRefusals(unittest.TestCase):
    """Cases the generator has no branch for, because they never reach it."""

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


if __name__ == "__main__":
    unittest.main()

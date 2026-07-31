"""IR -> OpenAPI: every fact in the output must trace to a node in the IR."""

import unittest

from lnpl.lower import lower
from lnpl.openapi import OpenApiError, generate
from lnpl.parser import parse

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


def spec_for(src=SRC):
    return generate(lower(parse(src), "login").to_document())


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


if __name__ == "__main__":
    unittest.main()

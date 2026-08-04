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
        payload = _payload_from_given(["slug abc123"], ENTITY)
        self.assertEqual(payload["slug"], "abc123")

    def test_no_field_requires_a_declared_field(self):
        # `no slog` (typo for slug) must error rather than no-op silently.
        with self.assertRaises(SpecError):
            _payload_from_given(["no slog"], ENTITY)

    def test_no_declared_field_drops_it(self):
        payload = _payload_from_given(["no slug"], ENTITY)
        self.assertNotIn("slug", payload)

    def test_valid_narrative_is_generic_not_login_specific(self):
        # `valid <anything>` is a narrative marker, not a field assignment.
        payload = _payload_from_given(["valid link"], ENTITY)
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

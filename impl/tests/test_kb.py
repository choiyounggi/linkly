"""KB access — RFC-0005 §Consumption Interface, and the routing tier boundary."""

import os
import unittest

from lnpl.kb import CATEGORIES, KbError, KnowledgeBase

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestIntegrity(unittest.TestCase):
    def setUp(self):
        self.kb = KnowledgeBase()

    def test_the_seeded_kb_satisfies_rfc_0005(self):
        self.assertEqual(self.kb.lint(), [])

    def test_all_twelve_categories_are_seeded(self):
        cats = {meta["category"] for meta in self.kb.index().values()}
        self.assertEqual(len(cats), 12)
        for c in CATEGORIES:
            self.assertIn(c.lower(), cats)

    def test_every_document_carries_at_least_one_source(self):
        for doc_id in self.kb.index():
            self.assertTrue(self.kb.load(doc_id)["sources"], doc_id)

    def test_missing_kb_directory_is_an_error(self):
        with self.assertRaises(KbError):
            KnowledgeBase(root=os.path.join(REPO, "no-such-kb"))


class TestRouting(unittest.TestCase):
    """route() must decide from the index alone (tier 1 of 3)."""

    def setUp(self):
        self.kb = KnowledgeBase()

    def test_routes_the_golden_scenario_step_to_the_jwt_document(self):
        # This is the exact call RFC-0006's Examples cycle makes.
        self.assertEqual(self.kb.route("generate token")[0], "security-jwt-issuance")

    def test_routes_a_korean_query_too(self):
        self.assertEqual(self.kb.route("retry 가 멈추지 않을 때")[0],
                         "antipatterns-unbounded-retry")

    def test_an_unmatched_query_returns_empty_not_a_guess(self):
        self.assertEqual(self.kb.route("zzz qqq wwww"), [])

    def test_empty_description_returns_empty(self):
        self.assertEqual(self.kb.route("   "), [])

    def test_routing_does_not_read_document_bodies(self):
        # A phrase that appears only in a body, never in a trigger, must not route.
        body = self.kb.load("antipatterns-unbounded-retry")["body"]
        self.assertIn("증폭", body)
        self.assertEqual(self.kb.route("증폭"), [],
                         "route() matched a body-only phrase — the routing tier is leaking")

    def test_results_are_ranked_by_trigger_overlap(self):
        ranked = self.kb.route("cache ttl eviction")
        self.assertTrue(ranked)
        self.assertIn(ranked[0], ("cloud-redis-cache-provisioning",
                                  "performance-response-budget-caching"))


class TestLoadAndVerify(unittest.TestCase):
    def setUp(self):
        self.kb = KnowledgeBase()

    def test_load_returns_frontmatter_and_body(self):
        doc = self.kb.load("security-jwt-issuance")
        self.assertEqual(doc["id"], "security-jwt-issuance")
        self.assertEqual(doc["category"], "Security")
        self.assertTrue(doc["body"])

    def test_load_of_an_unknown_document_is_an_error(self):
        with self.assertRaises(KbError):
            self.kb.load("nope")

    def test_verify_is_an_exact_version_match(self):
        self.assertTrue(self.kb.verify("security-jwt-issuance", "0.1.0"))
        self.assertFalse(self.kb.verify("security-jwt-issuance", "0.1.1"))

    def test_verify_of_a_missing_document_is_false_not_an_error(self):
        self.assertFalse(self.kb.verify("nope", "0.1.0"))

    def test_body_stays_within_the_500_line_budget(self):
        for doc_id in self.kb.index():
            self.assertLessEqual(len(self.kb.load(doc_id)["body"].splitlines()), 500)


if __name__ == "__main__":
    unittest.main()

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


class TestSecurityMaskingRouting(unittest.TestCase):
    """Issue #50 t2 F-14: a masking query landed on the naming document.

    `route()` ranks by trigger-token overlap alone, so "결제 카드번호 필드
    마스킹" matched Naming's `필드` and nothing in Security — the KB had no
    masking entry at all. The fix is content, not scoring: the Security index
    now carries a masking document whose triggers hold both the Korean and the
    English vocabulary an author actually types.
    """

    MASKING = "security-sensitive-field-masking"

    def setUp(self):
        self.kb = KnowledgeBase()

    # ---- normal: the query from the QA case ------------------------------
    def test_the_qa_cases_masking_query_routes_to_security(self):
        self.assertEqual(self.kb.route("결제 카드번호 필드 마스킹")[0], self.MASKING)

    def test_the_naming_document_is_no_longer_the_answer(self):
        """The precise regression: not just "security ranks", but naming loses."""
        self.assertNotEqual(self.kb.route("결제 카드번호 필드 마스킹")[0],
                            "naming-entity-field-conventions")

    def test_an_english_masking_query_routes_there_too(self):
        self.assertEqual(self.kb.route("sensitive field masking")[0], self.MASKING)

    # ---- the document itself is loadable and honest -----------------------
    def test_the_document_loads_and_names_the_masked_type(self):
        from lnpl.interp import MASKED_TYPES
        doc = self.kb.load(self.MASKING)
        self.assertEqual(doc["category"], "Security")
        for name in MASKED_TYPES:
            self.assertIn(name, doc["body"],
                          "%s를 안 적으면 무엇이 마스킹되는지 알 수 없다" % name)

    # ---- error -------------------------------------------------------------
    def test_loading_a_neighbouring_typo_is_an_error_not_a_guess(self):
        with self.assertRaises(KbError):
            self.kb.load(self.MASKING + "-typo")

    # ---- boundary / negative control ---------------------------------------
    def test_an_uncovered_security_query_still_returns_nothing(self):
        """The KB having nothing to say must stay different from guessing.

        t2 F-14 also reported "환불 기간 제한 정책" -> no match. That is the
        correct answer (no policy/limit document exists), and adding the masking
        entry must not turn it into a bad one.
        """
        self.assertEqual(self.kb.route("환불 기간 제한 정책"), [])

    def test_empty_query_returns_empty(self):
        self.assertEqual(self.kb.route(""), [])


class TestCloudCategoryRouting(unittest.TestCase):
    """Issue #196: the KB `cloud` category gains six documents."""

    QUESTIONS = [
        ("postgres 백엔드에 rate limit을 얼마로?", "cloud-postgres-provisioning"),
        ("how do I attach postgres and how much load does it hold",
         "cloud-postgres-provisioning"),
        ("lnpl serve or gunicorn, how many workers", "cloud-serving-topology"),
        ("gunicorn 워커 수를 몇 개로 둘까", "cloud-serving-topology"),
        ("where do traces go", "cloud-observability-export"),
        ("trace exporter 어디로 내보내나", "cloud-observability-export"),
        ("where do secrets live", "cloud-secrets-and-config"),
        ("시크릿을 파일로 주입하는 방법", "cloud-secrets-and-config"),
        ("how do I roll out a schema change", "cloud-schema-change-rollout"),
        ("무중단 스키마 변경 순서", "cloud-schema-change-rollout"),
        ("what does the outbox guarantee", "cloud-event-delivery"),
        ("이벤트 전달 보장은 at-least-once인가", "cloud-event-delivery"),
    ]

    def setUp(self):
        self.kb = KnowledgeBase()

    # ---- normal -------------------------------------------------------
    def test_each_cloud_question_routes_to_its_document_first(self):
        for question, doc_id in self.QUESTIONS:
            with self.subTest(question=question):
                self.assertEqual(self.kb.route(question)[:1], [doc_id])

    # ---- boundary -------------------------------------------------------
    def test_the_readme_agents_sample_step_still_routes_to_redis(self):
        self.assertEqual(self.kb.route("cache user")[0],
                         "cloud-redis-cache-provisioning")

    def test_the_six_cloud_documents_are_draft_and_cite_existing_files(self):
        doc_ids = sorted({doc_id for _, doc_id in self.QUESTIONS})
        self.assertEqual(len(doc_ids), 6)
        for doc_id in doc_ids:
            doc = self.kb.load(doc_id)
            self.assertEqual(doc["category"], "Cloud")
            self.assertEqual(doc["status"], "draft")
            self.assertTrue(doc["sources"])
            for src in doc["sources"]:
                if not src.startswith("http"):
                    self.assertTrue(os.path.isfile(os.path.join(REPO, src)), src)

    # ---- error -------------------------------------------------------------
    def test_a_misspelled_cloud_id_is_an_error_not_a_guess(self):
        with self.assertRaises(KbError):
            self.kb.load("cloud-postgres-provision")


if __name__ == "__main__":
    unittest.main()

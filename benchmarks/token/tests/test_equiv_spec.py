"""Ported linkhub.lnpl spec blocks (issue #142), run against the FastAPI port.

Loud-skip convention matches impl/tests/test_backend.py's NEEDS_TOOLS: this
benchmark's fastapi/httpx are installed only in benchmarks/token/.venv, never
in the project's own dependencies (see ../PROTOCOL.md), so a project-venv
run must skip these tests with a visible reason, never silently pass 0 tests.

Case <-> examples/linkhub.lnpl spec block:
  test_save_bookmark_success            <- SaveBookmark spec 1 (normal)
  test_save_bookmark_rejects_invalid_url <- SaveBookmark spec 2 (error)
  test_get_bookmark_empty_repository_fails <- GetBookmark spec (boundary)
"""

import os
import sys
import unittest
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "equiv"))

try:
    from fastapi.testclient import TestClient

    import linkhub_fastapi

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

NEEDS_FASTAPI = unittest.skipUnless(
    HAS_FASTAPI,
    "fastapi/httpx not installed — run from benchmarks/token/.venv "
    "(python3.13 -m venv benchmarks/token/.venv && "
    "benchmarks/token/.venv/bin/pip install tiktoken fastapi httpx pytest)",
)


@NEEDS_FASTAPI
class LinkHubEquivSpecTest(unittest.TestCase):
    def setUp(self):
        self.app = linkhub_fastapi.create_app()
        self.client = TestClient(self.app)

    def _payload(self, **overrides):
        payload = {
            "id": str(uuid.uuid4()),
            "url": "https://example.com/article",
            "title": "An article",
            "owner": str(uuid.uuid4()),
        }
        payload.update(overrides)
        return payload

    def test_save_bookmark_success(self):
        # spec: given empty repository / when saveBookmark
        # expect completed, effects complete, rows Bookmark 1, cache written
        store = self.app.state.store
        self.assertEqual(len(store.bookmarks), 0)

        response = self.client.post("/bookmarks", json=self._payload())

        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(store.bookmarks), 1)
        self.assertEqual(len(store.cache), 1)
        self.assertEqual(len(store.events), 1)
        self.assertEqual(store.events[0]["name"], "BookmarkSaved")

    def test_save_bookmark_rejects_invalid_url(self):
        # spec: given input.url not-a-url / when saveBookmark
        # expect failed, effects complete, error reason does not match URL's pattern
        store = self.app.state.store

        response = self.client.post("/bookmarks", json=self._payload(url="not-a-url"))

        self.assertEqual(response.status_code, 422)
        body_text = response.text
        self.assertIn("does not match URL's pattern", body_text)
        self.assertEqual(len(store.bookmarks), 0)

    def test_get_bookmark_empty_repository_fails(self):
        # spec: given empty repository / when getBookmark
        # expect failed, effects complete, rows Bookmark 0
        store = self.app.state.store
        self.assertEqual(len(store.bookmarks), 0)

        response = self.client.get(f"/bookmarks/{uuid.uuid4()}")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(len(store.bookmarks), 0)


if __name__ == "__main__":
    unittest.main()

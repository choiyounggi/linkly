"""Issue #99 — the GET query surface: single-row GET (D1, automatic) and the
opt-in cursor-paginated `expose list` GET (D2/D3).

Pure logic (`encode_cursor`/`decode_cursor`/`paginate`/`_parse_limit`) is
tested directly, without a socket, the same way `MapResultTest` in
test_serve.py tests `map_result`. The HTTP round trip through `ServerTestCase`
covers what only a real request can: routing, auth reuse (M3, D5), and the
masking chokepoint on the new response channel (mirrors
`test_masking_holds_on_the_200_response_channel`, D7's sweep, in
test_serve.py).

A shared `interp.FakeRepository` instance stands in for a persistent backend
(`repository_factory=lambda: SHARED`) — the default dev server seeds and
discards a throwaway store per POST (serve.py's own docstring: "the
in-memory, presence-checked server it has always been"), so GET would never
find anything to read without one.
"""

import json
import unittest

from lnpl.interp import FakeRepository
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.serve import (CursorError, decode_cursor, encode_cursor, paginate,
                        _parse_limit)
from tests.test_serve import ServerTestCase

ORDERS_SRC = """capability postgres

entity Order
    field
        id UUID
        placedAt DateTime
        total Integer
        secret Password

service Orders
    policy
        retry 0
    security
        jwt
    expose
        list Order by placedAt

workflow SaveOrder
    validate order
    find order
"""


def compile_doc(source, module="m"):
    return lower(parse(source), module).to_document()


def uid(n):
    """A valid-UUID id for test row `n` — `id` is typed UUID, so a bare label
    like `"o-1"` fails the entity's own `validate` step before GET is ever
    reached."""
    return "3f2504e0-4f89-41d3-9a0c-0305e82c33%02x" % n


def order_payload(id_, placed_at, total=100):
    return {"id": id_, "placedAt": placed_at, "total": total,
           "secret": "s3cret-value"}


class CursorAndPaginateTest(unittest.TestCase):
    """Pure-function coverage — no server."""

    def test_encode_decode_round_trips(self):
        self.assertEqual((5, "entity.order#a"),
                         decode_cursor(encode_cursor(5, "entity.order#a")))

    def test_decode_rejects_undecodable_base64(self):
        with self.assertRaises(CursorError):
            decode_cursor("!!!not-base64!!!")

    def test_decode_rejects_wrong_shape_json(self):
        import base64
        token = base64.urlsafe_b64encode(b'{"only": "one key"}').rstrip(b"=").decode()
        with self.assertRaises(CursorError):
            decode_cursor(token)

    def test_paginate_returns_all_rows_when_under_the_limit(self):
        rows = [{"id": "a", "n": 1}, {"id": "b", "n": 2}]
        page, next_cursor = paginate(rows, "n", "e", after=None, limit=50)
        self.assertEqual(rows, page)
        self.assertIsNone(next_cursor)

    def test_paginate_sets_next_cursor_when_more_rows_remain(self):
        rows = [{"id": "a", "n": 1}, {"id": "b", "n": 2}, {"id": "c", "n": 3}]
        page, next_cursor = paginate(rows, "n", "e", after=None, limit=2)
        self.assertEqual(rows[:2], page)
        self.assertIsNotNone(next_cursor)

    def test_paginate_resumes_after_a_cursor(self):
        rows = [{"id": "a", "n": 1}, {"id": "b", "n": 2}, {"id": "c", "n": 3}]
        after = (rows[0]["n"], "e#a")
        page, next_cursor = paginate(rows, "n", "e", after=after, limit=50)
        self.assertEqual(rows[1:], page)

    def test_paginate_raises_cursor_error_on_cross_type_comparison(self):
        # A forged cursor whose value type does not match the field's own —
        # D3's "위조 커서 400" at the comparison boundary.
        rows = [{"id": "a", "n": 1}]
        with self.assertRaises(CursorError):
            paginate(rows, "n", "e", after=("not-a-number", "e#z"), limit=50)

    def test_parse_limit_none_is_the_default(self):
        self.assertEqual(50, _parse_limit(None))

    def test_parse_limit_rejects_zero(self):
        with self.assertRaises(ValueError):
            _parse_limit("0")

    def test_parse_limit_rejects_non_digit(self):
        with self.assertRaises(ValueError):
            _parse_limit("abc")

    def test_parse_limit_rejects_over_the_ceiling(self):
        with self.assertRaises(ValueError):
            _parse_limit("201")

    def test_parse_limit_accepts_the_ceiling(self):
        self.assertEqual(200, _parse_limit("200"))


class GetSingleTest(ServerTestCase):
    def setUp(self):
        self.repo = FakeRepository()
        self.port = self.start(compile_doc(ORDERS_SRC),
                               repository_factory=lambda: self.repo)

    def _save(self, payload):
        resp, body = self.post_json(self.port, "/orders/save-order", payload)
        self.assertEqual(200, resp.status, body)

    def test_get_single_returns_200_with_masked_row(self):
        self._save(order_payload(uid(1), "2026-01-01T00:00:00Z"))
        resp, raw = self.request(self.port, "GET", "/orders/order/%s" % uid(1),
                                 headers={"Authorization": "Bearer x"})
        body = json.loads(raw)
        self.assertEqual(200, resp.status)
        self.assertEqual(uid(1), body["id"])
        self.assertEqual("***", body["secret"])
        self.assertNotIn(b"s3cret-value", raw)

    def test_get_single_missing_row_is_404(self):
        resp, raw = self.request(self.port, "GET", "/orders/order/%s" % uid(99),
                                 headers={"Authorization": "Bearer x"})
        self.assertEqual(404, resp.status)
        self.assertEqual("not-found", json.loads(raw)["code"])

    def test_get_single_missing_auth_is_401(self):
        # D5: the same M3 judgment a POST workflow route already used.
        resp, raw = self.request(self.port, "GET", "/orders/order/%s" % uid(1))
        self.assertEqual(401, resp.status)
        self.assertEqual("auth-missing", json.loads(raw)["code"])

    def test_get_single_with_no_backend_configured_is_404(self):
        port = self.start(compile_doc(ORDERS_SRC))     # no repository_factory
        resp, raw = self.request(port, "GET", "/orders/order/%s" % uid(1),
                                 headers={"Authorization": "Bearer x"})
        self.assertEqual(404, resp.status)


class GetListTest(ServerTestCase):
    def setUp(self):
        self.repo = FakeRepository()
        self.port = self.start(compile_doc(ORDERS_SRC),
                               repository_factory=lambda: self.repo)

    def _save(self, payload):
        resp, body = self.post_json(self.port, "/orders/save-order", payload)
        self.assertEqual(200, resp.status, body)

    def _list(self, query=""):
        path = "/orders/order" + ("?" + query if query else "")
        resp, raw = self.request(self.port, "GET", path,
                                 headers={"Authorization": "Bearer x"})
        return resp, json.loads(raw)

    def test_empty_list_is_200_with_empty_items_and_null_next(self):
        resp, body = self._list()
        self.assertEqual(200, resp.status)
        self.assertEqual([], body["items"])
        self.assertIsNone(body["next"])

    def test_list_missing_auth_is_401(self):
        resp, raw = self.request(self.port, "GET", "/orders/order")
        self.assertEqual(401, resp.status)
        self.assertEqual("auth-missing", json.loads(raw)["code"])

    def test_list_without_expose_is_404(self):
        # An entity this service never exposes (and no workflow touches, so
        # it gets no single-row route either): opt-in only (D2).
        src = ORDERS_SRC + "\nentity Untouched\n    field\n        id UUID\n"
        port = self.start(compile_doc(src, "m2"))
        resp, raw = self.request(port, "GET", "/orders/untouched",
                                 headers={"Authorization": "Bearer x"})
        self.assertEqual(404, resp.status)
        self.assertEqual("not-found", json.loads(raw)["code"])

    def test_forged_cursor_is_400(self):
        self._save(order_payload(uid(1), "2026-01-01T00:00:00Z"))
        resp, body = self._list("after=not-a-real-cursor")
        self.assertEqual(400, resp.status)
        self.assertEqual("cursor-invalid", body["code"])

    def test_limit_zero_is_400(self):
        resp, body = self._list("limit=0")
        self.assertEqual(400, resp.status)
        self.assertEqual("limit-invalid", body["code"])

    def test_limit_over_ceiling_is_400(self):
        resp, body = self._list("limit=201")
        self.assertEqual(400, resp.status)
        self.assertEqual("limit-invalid", body["code"])

    def test_limit_one_pages_a_single_item_with_a_next_cursor(self):
        self._save(order_payload(uid(1), "2026-01-01T00:00:00Z"))
        self._save(order_payload(uid(2), "2026-01-02T00:00:00Z"))
        resp, body = self._list("limit=1")
        self.assertEqual(200, resp.status)
        self.assertEqual(1, len(body["items"]))
        self.assertEqual(uid(1), body["items"][0]["id"])
        self.assertIsNotNone(body["next"])

    def test_limit_at_the_ceiling_is_accepted(self):
        self._save(order_payload(uid(1), "2026-01-01T00:00:00Z"))
        resp, body = self._list("limit=200")
        self.assertEqual(200, resp.status)
        self.assertEqual(1, len(body["items"]))

    def test_equal_sort_values_tiebreak_by_row_key(self):
        # Boundary: two rows share `placedAt` — order must still be total and
        # deterministic (row_key, RFC-0025 §7's tiebreak, D3).
        same_time = "2026-01-01T00:00:00Z"
        self._save(order_payload(uid(2), same_time))
        self._save(order_payload(uid(1), same_time))
        resp, body = self._list("limit=1")
        first_id = body["items"][0]["id"]
        resp2, body2 = self._list("limit=1&after=%s" % body["next"])
        second_id = body2["items"][0]["id"]
        self.assertEqual({uid(1), uid(2)}, {first_id, second_id})
        self.assertNotEqual(first_id, second_id)
        self.assertIsNone(body2["next"])

    def test_cursor_traversal_visits_every_row_exactly_once(self):
        ids = [uid(i) for i in range(7)]
        for i, id_ in enumerate(ids):
            self._save(order_payload(id_, "2026-01-%02dT00:00:00Z" % (i + 1)))

        seen = []
        cursor = None
        for _ in range(len(ids) + 1):        # +1: one extra call must be a no-op
            query = "limit=3" + ("&after=%s" % cursor if cursor else "")
            resp, body = self._list(query)
            self.assertEqual(200, resp.status)
            seen.extend(item["id"] for item in body["items"])
            cursor = body["next"]
            if cursor is None:
                break

        self.assertEqual(ids, seen)          # every row, in order, no loss/dup
        self.assertIsNone(cursor)             # the last page's cursor is null

    def test_masking_holds_on_the_list_response_channel(self):
        self._save(order_payload(uid(1), "2026-01-01T00:00:00Z"))
        resp, raw = self.request(self.port, "GET", "/orders/order",
                                 headers={"Authorization": "Bearer x"})
        self.assertNotIn(b"s3cret-value", raw)
        self.assertIn(b"***", raw)

    def test_list_with_no_backend_configured_is_200_with_empty_items(self):
        port = self.start(compile_doc(ORDERS_SRC))      # no repository_factory
        resp, raw = self.request(port, "GET", "/orders/order",
                                 headers={"Authorization": "Bearer x"})
        body = json.loads(raw)
        self.assertEqual(200, resp.status)
        self.assertEqual([], body["items"])


if __name__ == "__main__":
    unittest.main()

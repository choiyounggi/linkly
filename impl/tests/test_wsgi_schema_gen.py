"""issue #147 D3: `_schema_gen` (the storage-layer schema-generation stamp)
must never reach an HTTP response. `lnpl serve`'s GET single/list handlers
(`wsgi.py` `_get_single`/`_get_list`) read the repository directly, bypassing
interp.py's own strip on the `run`/`RepositoryCall` path — so this pins the
second strip wsgi.py itself must apply.

A row is seeded with the stamp already present (`FakeRepository.seed`,
bypassing any workflow write) so the test isolates wsgi.py's own strip from
interp.py's write-side injection, covered separately in test_schema_gen.py.
"""

import json
import unittest

from lnpl.interp import FakeRepository, SCHEMA_GEN_KEY
from lnpl.repo_policy import row_key
from tests.test_serve import ServerTestCase
from tests.test_serve_get import ORDERS_SRC, compile_doc, order_payload, uid


class SchemaGenNeverLeaksThroughServeTest(ServerTestCase):

    def setUp(self):
        self.repo = FakeRepository()
        self.doc = compile_doc(ORDERS_SRC)
        self.entity_id = next(n["id"] for n in self.doc["nodes"]
                              if n["kind"] == "Entity")
        self.port = self.start(self.doc, repository_factory=lambda: self.repo)

    def _seed_stamped_row(self, payload):
        stamped = dict(payload, **{SCHEMA_GEN_KEY: "deadbeef1234"})
        self.repo.seed({self.entity_id:
                        {row_key(self.entity_id, stamped): stamped}})

    def test_get_single_never_exposes_the_stamp(self):
        self._seed_stamped_row(order_payload(uid(1), "2026-01-01T00:00:00Z"))

        resp, raw = self.request(self.port, "GET", "/orders/order/%s" % uid(1),
                                 headers={"Authorization": "Bearer x"})

        self.assertEqual(200, resp.status)
        body = json.loads(raw)
        self.assertEqual(uid(1), body["id"])
        self.assertNotIn(SCHEMA_GEN_KEY, body)
        self.assertNotIn(SCHEMA_GEN_KEY.encode("ascii"), raw)

    def test_get_list_never_exposes_the_stamp(self):
        self._seed_stamped_row(order_payload(uid(2), "2026-01-02T00:00:00Z"))

        resp, raw = self.request(self.port, "GET", "/orders/order",
                                 headers={"Authorization": "Bearer x"})

        self.assertEqual(200, resp.status)
        body = json.loads(raw)
        self.assertEqual(1, len(body["items"]))
        self.assertNotIn(SCHEMA_GEN_KEY, body["items"][0])
        self.assertNotIn(SCHEMA_GEN_KEY.encode("ascii"), raw)


if __name__ == "__main__":
    unittest.main()

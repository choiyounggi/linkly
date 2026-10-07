"""요청당 결정적 카운터 — 성능 회귀의 PR 차단 게이트 (issue #195).

절대 처리량·지연은 러너마다 달라서 PR 게이트가 될 수 없다(주간
`load-weekly.yml`이 리포트만 남긴다). 대신 요청 1건이 하는 일의 양을 센다:
DB 연결 생성 수(`sqlite3.connect` 호출), 연결 닫힘 수(`close`), 저장소 문장
수(`execute`), 드라이버 생성 수(`repository_factory` 호출). 이 넷은 실행마다
똑같으므로 정확한 값으로 단언한다 — `<= 1`이 아니라 `== 1`인 이유는 저장소에
닿지도 않은 요청(0)이 조용히 통과하지 않게 하기 위해서다.

`_ConnectPerCallDriver`는 일부러 느리게 만든 대조군이다: 문장마다 연결을 하나
더 연다. `DegradedDoubleControlTest`가 매 실행마다 카운터가 그 회귀를 실제로
본다는 것을 증명한다.
"""
import collections
import contextlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from lnpl.drivers import SqliteRepositoryDriver
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.wsgi import build_app, make_wsgi_app

from tests.test_wsgi_contract import call_wsgi

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

ORDER = "entity.order"
ORDER_ID = "11111111-1111-4111-8111-111111111111"
MISSING_ID = "22222222-2222-4222-8222-222222222222"
CANCEL_PATH = "/order-service/cancel-order"
GET_PATH = "/order-service/order/" + ORDER_ID

SOURCE = """
entity Order
    field
        id UUID
        quantity Integer

service OrderService

workflow CancelOrder
    find order by input.id
    set order.quantity to 0
    update order by input.id
"""

RequestCounts = collections.namedtuple(
    "RequestCounts", "status connects closes executes factory_calls")


def compile_source(source, module="mod"):
    return lower(parse(source), module).to_document()


def payload(order_id):
    return json.dumps({"id": order_id, "quantity": 5}).encode("utf-8")


class _ConnectPerCallDriver(SqliteRepositoryDriver):
    """The deliberately degraded double: one extra connection per statement."""

    def execute(self, entity_id, operation, key):
        sqlite3.connect(self.path).close()
        return super().execute(entity_id, operation, key)


def count_request(app, method, path, body=b"", factory_calls=None):
    """Drive one request and count what it did to the store.

    The patches cover this one call only, so building the app (and
    `build_app()`'s own start-up probe) is never counted.
    """
    with mock.patch("lnpl.drivers.sqlite3.connect",
                    wraps=sqlite3.connect) as connect, \
            mock.patch.object(SqliteRepositoryDriver, "close", autospec=True,
                              side_effect=SqliteRepositoryDriver.close) as close, \
            mock.patch.object(SqliteRepositoryDriver, "execute", autospec=True,
                              side_effect=SqliteRepositoryDriver.execute) as execute:
        before = factory_calls[0] if factory_calls is not None else 0
        status, _headers, _body = call_wsgi(app, method, path, body=body)
        after = factory_calls[0] if factory_calls is not None else 0
    return RequestCounts(status, connect.call_count, close.call_count,
                         execute.call_count, after - before)


class _CountedStoreTestCase(unittest.TestCase):
    DRIVER_CLASS = SqliteRepositoryDriver

    def setUp(self):
        base = os.path.join(REPO_ROOT, ".claude", "tmp")
        os.makedirs(base, exist_ok=True)
        self.box = tempfile.mkdtemp(prefix="lnpl-t195-", dir=base)
        self.addCleanup(shutil.rmtree, self.box, True)
        self.path = os.path.join(self.box, "store.db")
        seeder = SqliteRepositoryDriver(self.path)
        seeder.seed({ORDER: {"%s#%s" % (ORDER, ORDER_ID):
                             {"id": ORDER_ID, "quantity": 5}}})
        seeder.close()
        self.factory_calls = [0]

    def factory(self):
        self.factory_calls[0] += 1
        return self.DRIVER_CLASS(self.path)

    def app(self):
        return make_wsgi_app(compile_source(SOURCE),
                             repository_factory=self.factory)

    def count(self, method, path, body=b""):
        return count_request(self.app(), method, path, body,
                             factory_calls=self.factory_calls)


class PerRequestCounterGateTest(_CountedStoreTestCase):
    """The PR gate: exact per-request counts on the sqlite and fake paths."""

    def test_workflow_post_opens_one_connection_and_closes_it(self):
        counts = self.count("POST", CANCEL_PATH, payload(ORDER_ID))
        self.assertEqual(200, counts.status)
        self.assertEqual(1, counts.connects)
        self.assertEqual(1, counts.closes)
        self.assertEqual(1, counts.factory_calls)

    def test_workflow_post_issues_two_repository_statements(self):
        counts = self.count("POST", CANCEL_PATH, payload(ORDER_ID))
        self.assertEqual(200, counts.status)
        self.assertEqual(2, counts.executes)

    def test_get_single_opens_one_connection_and_issues_one_statement(self):
        counts = self.count("GET", GET_PATH)
        self.assertEqual(200, counts.status)
        self.assertEqual(1, counts.connects)
        self.assertEqual(1, counts.closes)
        self.assertEqual(1, counts.executes)

    def test_read_miss_404_still_opens_one_connection_and_closes_it(self):
        counts = self.count("POST", CANCEL_PATH, payload(MISSING_ID))
        self.assertEqual(404, counts.status)
        self.assertEqual(1, counts.connects)
        self.assertEqual(1, counts.closes)

    def test_fake_backend_opens_no_connection(self):
        with contextlib.redirect_stderr(io.StringIO()):
            app = make_wsgi_app(compile_source(SOURCE))
            counts = count_request(app, "POST", CANCEL_PATH, payload(ORDER_ID))
        self.assertEqual(200, counts.status)
        self.assertEqual(0, counts.connects)
        self.assertEqual(0, counts.executes)

    def test_build_app_path_opens_one_connection_per_request(self):
        source_path = os.path.join(self.box, "orders.lnpl")
        with open(source_path, "w", encoding="utf-8") as fh:
            fh.write(SOURCE)
        env = {k: v for k, v in os.environ.items() if not k.startswith("LNPL_")}
        with mock.patch.dict(os.environ, env, clear=True):
            app = build_app(sources=source_path, backend="sqlite:" + self.path)
        counts = count_request(app, "POST", CANCEL_PATH, payload(ORDER_ID))
        self.assertEqual(200, counts.status)
        self.assertEqual(1, counts.connects)
        self.assertEqual(1, counts.closes)


class DegradedDoubleControlTest(_CountedStoreTestCase):
    """Positive control: the counters do see a connection-per-statement regression."""

    DRIVER_CLASS = _ConnectPerCallDriver

    def test_degraded_double_is_counted_on_workflow_post(self):
        counts = self.count("POST", CANCEL_PATH, payload(ORDER_ID))
        self.assertEqual(200, counts.status)
        self.assertEqual(3, counts.connects)
        self.assertEqual(1, counts.closes)

    def test_degraded_double_is_counted_on_get_single(self):
        counts = self.count("GET", GET_PATH)
        self.assertEqual(200, counts.status)
        self.assertEqual(2, counts.connects)


if __name__ == "__main__":
    unittest.main()

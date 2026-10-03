"""Issue #113: GET single carries an `ETag` (weak validator, `_version`-
based); a state-changing POST's `If-Match` conditions on the FIRST entity
the workflow reads (there is no single targeted resource the way a REST
PUT/PATCH has one) and a mismatch is 412. D12's opt-in (`observed_version`)
is the SAME attribute `drivers.py`'s `persist()` already reads -- no new
check invented, just reused the other direction.
"""

import base64
import contextlib
import hashlib
import hmac
import io
import json
import os
import tempfile
import time
import unittest

from lnpl.drivers import (DriverError, FakeNetworkDriver, HmacTokenProvider,
                          SqliteRepositoryDriver)
from lnpl.lower import lower
from lnpl.parser import parse
from lnpl.wsgi import make_wsgi_app

from tests.fixtures import VALUE_INVENTORY, VALUE_PAYMENT
from tests.test_wsgi_contract import call_wsgi

PROD = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
PRODUCT_PATH = "/order-service/product/%s" % PROD
PLACE_ORDER_PATH = "/order-service/place-order"
SECRET = b"0123456789abcdef0123456789abcdef"            # exactly 32 bytes
AUDIENCE = "order-service"

BY_REF_PROD = "66666666-6666-4666-8666-666666666666"
BY_REF_ORDER_1 = "77777777-7777-4777-8777-777777777777"
BY_REF_ORDER_2 = "77777777-7777-4777-8777-777777777778"

R5_UNSEEDED_PROD = "88888888-8888-4888-8888-888888888888"
R5_ORDER = "99999999-9999-4999-8999-999999999999"

BINDING_PROD = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
BINDING_ORDER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

SELF_REF_ORDER = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
SELF_REF_PRODUCT_ID = "22222222-2222-4222-8222-222222222222"

NETWORK_PROD = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"

CALLER_SUB_PROD = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
CALLER_ORDER = "ffffffff-ffff-4fff-8fff-ffffffffffff"

ABSENT_INPUT_ORDER = "11111111-1111-4111-8111-111111111111"

BY_REF_SOURCE = """capability postgres

entity Product
    field
        id UUID
        stock Integer

entity Order
    field
        id UUID
        productId UUID
        quantity Integer

event OrderPlaced on Order create

service OrderService
    policy
        timeout 5s

workflow PlaceOrder
    find product by input.productId
    set product.stock to product.stock - input.quantity
    create order
    emit orderPlaced
"""

BARE_SOURCE = """capability postgres

entity Product
    field
        id UUID
        stock Integer

entity Order
    field
        id UUID
        quantity Integer

event OrderPlaced on Order create

service OrderService
    policy
        timeout 5s

workflow PlaceOrder
    find product by productId
    set product.stock to product.stock - input.quantity
    create order
"""

BINDING_SOURCE = """capability postgres

entity Product
    field
        id UUID
        stock Integer

entity Order
    field
        id UUID
        productId UUID

event OrderPlaced on Order create

service OrderService
    policy
        timeout 5s

workflow PlaceOrder
    create order as placed
    find product by placed.productId
    emit orderPlaced
"""

SELF_REF_SOURCE = """capability postgres

entity Order
    field
        id UUID
        productId UUID

service OrderService
    policy
        timeout 5s

workflow PlaceOrder
    find order by order.productId
"""

NETWORK_SOURCE = """capability postgres

entity Product
    field
        id UUID
        stock Integer

service OrderService
    policy
        timeout 5s

workflow PlaceOrder
    call ProductLookup as productLookup
    find product by productLookup.productId
"""

CALLER_SUBJECT_SOURCE = """capability postgres

entity Product
    field
        id UUID
        stock Integer

entity Order
    field
        id UUID
        quantity Integer

event OrderPlaced on Order create

service OrderService
    security
        jwt
    policy
        timeout 5s

workflow PlaceOrder
    find product by caller.subject
    set product.stock to product.stock - input.quantity
    create order
    emit orderPlaced
"""

CALLER_ROLE_SOURCE = """capability postgres

entity Product
    field
        id UUID
        stock Integer

service OrderService
    security
        jwt
    policy
        timeout 5s

workflow PlaceOrder
    find product by caller.role
"""


def _forge_hs256_token(secret, **claims_overrides):
    """A genuinely-signed HS256 token, same shape `test_role_gate.py`'s
    `forge()` builds -- hand-signed so a claim set without the fixed shape
    `HmacTokenProvider.issue` mints can still be tested (issue #199, D4)."""
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    claims = {"iss": "lnpl", "aud": AUDIENCE, "sub": "u1", "jti": "j-1",
              "iat": now, "nbf": now, "exp": now + 900}
    claims.update(claims_overrides)

    def b64u(raw):
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    signing_input = "%s.%s" % (b64u(json.dumps(header).encode("utf-8")),
                               b64u(json.dumps(claims).encode("utf-8")))
    sig = hmac.new(secret, signing_input.encode("ascii"), hashlib.sha256).digest()
    return "%s.%s" % (signing_input, b64u(sig))


def compile_source(source, module="mod"):
    return lower(parse(source), module).to_document()


class EtagIfMatchTest(unittest.TestCase):

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.path = os.path.join(box.name, "store.db")
        self.doc = compile_source(VALUE_INVENTORY)
        self.app = make_wsgi_app(
            self.doc, repository_factory=lambda: SqliteRepositoryDriver(self.path))
        for n in range(2, 13):
            setattr(self, "path%d" % n, os.path.join(box.name, "store%d.db" % n))
        seed = SqliteRepositoryDriver(self.path)
        seed.seed({"entity.product": {"entity.product#%s" % PROD:
                                      {"id": PROD, "stock": 100}}})
        seed.close()

    def _get_product(self):
        return call_wsgi(self.app, "GET", PRODUCT_PATH)

    def _place_order(self, headers=None):
        payload = {"id": PROD, "quantity": 1}
        return call_wsgi(self.app, "POST", PLACE_ORDER_PATH,
                         body=json.dumps(payload).encode("utf-8"),
                         headers=headers or {})

    # -- normal --------------------------------------------------------

    def test_get_single_carries_an_etag_matching_version(self):
        status, headers, body = self._get_product()

        self.assertEqual(200, status)
        self.assertEqual('W/"0"', headers.get("ETag"))

    def test_if_match_hit_lets_the_write_through(self):
        _, headers, _ = self._get_product()
        etag = headers["ETag"]

        status, _, body = self._place_order({"If-Match": etag})

        self.assertEqual(200, status)
        self.assertEqual("completed", body["status"])

    def test_the_version_advances_after_a_write(self):
        self._place_order()
        _, headers, _ = self._get_product()

        self.assertEqual('W/"1"', headers.get("ETag"))

    # -- error: stale If-Match -------------------------------------------

    def test_if_match_miss_is_412(self):
        _, headers, _ = self._get_product()
        stale_etag = headers["ETag"]
        self._place_order()                       # advances the version

        status, _, body = self._place_order({"If-Match": stale_etag})

        self.assertEqual(412, status)
        self.assertEqual("precondition-failed", body["code"])

    def test_malformed_if_match_is_400_not_412(self):
        """Decided (task boundary): a value this server never issued as its
        own ETag is a request-format error (400), not a failed precondition
        (412) -- the server cannot even evaluate the condition. Several
        malformed shapes, not just one -- an unquoted number, RFC 9110's
        `*` (not produced by this server's own GET, so not accepted), and
        a multi-value If-Match list (also not produced here)."""
        for bad in ("not-an-etag", "0", "*", 'W/"0", W/"1"', 'w/"0"'):
            with self.subTest(if_match=bad):
                status, _, body = self._place_order({"If-Match": bad})
                self.assertEqual(400, status)
                self.assertEqual("precondition-invalid", body["code"])

    def test_a_repository_error_during_the_precondition_read_defers_to_the_workflow(self):
        """`_check_if_match` (wsgi.py) swallows a `DriverError` from its own
        pre-read and lets the request proceed -- the workflow's own read of
        the same entity hits the same broken driver right after and surfaces
        the fault the normal way (M8/M14), rather than this check
        translating it a second time under a different code."""
        class _BrokenReadDriver(SqliteRepositoryDriver):
            def execute(self, entity_id, operation, key):
                if operation == "read":
                    raise DriverError("the store is unreachable")
                return super().execute(entity_id, operation, key)

        app = make_wsgi_app(
            self.doc, repository_factory=lambda: _BrokenReadDriver(self.path))
        payload = {"id": PROD, "quantity": 1}

        status, _, body = call_wsgi(app, "POST", PLACE_ORDER_PATH,
                                    body=json.dumps(payload).encode("utf-8"),
                                    headers={"If-Match": 'W/"0"'})

        # Not 400/412 (the precondition check itself never rejected this) --
        # the workflow's own read hits the same broken driver and the
        # failure surfaces as an ordinary failed run (never a 500 from an
        # escaped exception).
        self.assertNotIn(status, (400, 412))
        self.assertIn(status, (500, 409))

    # -- boundary: no read step -> nothing to condition on ----------------

    def test_if_match_on_a_workflow_with_no_read_step_is_ignored(self):
        """`VALUE_PAYMENT`'s `Approve` never reads anything -- If-Match has
        no row to check against, so it is skipped, not rejected."""
        doc = compile_source(VALUE_PAYMENT)
        app = make_wsgi_app(doc, repository_factory=lambda: SqliteRepositoryDriver(self.path))
        payload = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3302", "amount": 500}

        status, _, body = call_wsgi(app, "POST", "/payment-service/approve",
                                    body=json.dumps(payload).encode("utf-8"),
                                    headers={"If-Match": 'W/"999"'})

        self.assertEqual(200, status)
        self.assertEqual("completed", body["status"])

    # -- boundary: no observed_version (fake backend, D12) -----------------

    def test_fake_backend_never_issues_an_etag(self):
        doc = compile_source(VALUE_INVENTORY)
        app = make_wsgi_app(doc)  # no repository_factory -> fake

        status, headers, body = call_wsgi(app, "GET", PRODUCT_PATH)

        self.assertEqual(404, status)          # fake seeds nothing per request
        self.assertNotIn("ETag", headers)

    def test_fake_backend_ignores_if_match_and_runs_normally(self):
        doc = compile_source(VALUE_PAYMENT)
        app = make_wsgi_app(doc)
        payload = {"id": "3f2504e0-4f89-41d3-9a0c-0305e82c3303", "amount": 500}

        status, _, body = call_wsgi(app, "POST", "/payment-service/approve",
                                    body=json.dumps(payload).encode("utf-8"),
                                    headers={"If-Match": 'W/"0"'})

        self.assertEqual(200, status)
        self.assertEqual("completed", body["status"])

    # -- regression: no If-Match is byte-identical (D13) --------------------

    def test_no_if_match_runs_exactly_as_before(self):
        status, _, body = self._place_order()

        self.assertEqual(200, status)
        self.assertEqual("completed", body["status"])

    # -- by <ref> (RFC-0052): stale/matching If-Match, row absent --------

    def _post(self, app, payload, headers=None):
        return call_wsgi(app, "POST", PLACE_ORDER_PATH,
                         body=json.dumps(payload).encode("utf-8"),
                         headers=headers or {})

    def _no_writes(self, path):
        driver = SqliteRepositoryDriver(path)
        self.addCleanup(driver.close)
        self.assertEqual(0, len(driver.query("entity.order")))
        self.assertEqual(0, len(driver.read_outbox("event.order.placed")))

    def test_stale_if_match_against_by_ref_lookup_is_412(self):
        app = make_wsgi_app(compile_source(BY_REF_SOURCE),
                            repository_factory=lambda: SqliteRepositoryDriver(self.path2))
        seed = SqliteRepositoryDriver(self.path2)
        seed.seed({"entity.product": {"entity.product#%s" % BY_REF_PROD:
                                      {"id": BY_REF_PROD, "stock": 100}}})
        seed.close()
        _, headers, _ = call_wsgi(app, "GET", "/order-service/product/%s" % BY_REF_PROD)
        stale_etag = headers["ETag"]
        self._post(app, {"id": BY_REF_ORDER_1, "productId": BY_REF_PROD, "quantity": 1})

        status, _, body = self._post(
            app, {"id": BY_REF_ORDER_2, "productId": BY_REF_PROD, "quantity": 1},
            {"If-Match": stale_etag})

        self.assertEqual(412, status)
        self.assertEqual("precondition-failed", body["code"])
        driver = SqliteRepositoryDriver(self.path2)
        self.assertEqual(1, len(driver.query("entity.order")))
        self.assertEqual(1, len(driver.read_outbox("event.order.placed")))
        driver.close()

    def test_if_match_hit_against_a_by_ref_lookup_lets_the_write_through(self):
        app = make_wsgi_app(compile_source(BY_REF_SOURCE),
                            repository_factory=lambda: SqliteRepositoryDriver(self.path3))
        seed = SqliteRepositoryDriver(self.path3)
        seed.seed({"entity.product": {"entity.product#%s" % BY_REF_PROD:
                                      {"id": BY_REF_PROD, "stock": 100}}})
        seed.close()
        _, headers, _ = call_wsgi(app, "GET", "/order-service/product/%s" % BY_REF_PROD)

        status, _, body = self._post(
            app, {"id": BY_REF_ORDER_1, "productId": BY_REF_PROD, "quantity": 1},
            {"If-Match": headers["ETag"]})

        self.assertEqual(200, status)
        self.assertEqual("completed", body["status"])
        _, headers2, body2 = call_wsgi(app, "GET", "/order-service/product/%s" % BY_REF_PROD)
        self.assertEqual('W/"1"', headers2["ETag"])
        self.assertEqual(99, body2["stock"])

    def test_if_match_present_and_addressed_row_absent_is_412(self):
        app = make_wsgi_app(compile_source(BY_REF_SOURCE),
                            repository_factory=lambda: SqliteRepositoryDriver(self.path4))

        status, _, body = self._post(
            app, {"id": R5_ORDER, "productId": R5_UNSEEDED_PROD, "quantity": 1},
            {"If-Match": 'W/"0"'})

        self.assertEqual(412, status)
        self.assertEqual("precondition-failed", body["code"])
        self._no_writes(self.path4)

    # -- unresolvable before execution: binding / self-ref / network -----

    def test_if_match_against_a_binding_bound_by_an_earlier_create_is_400_precondition_unsupported(self):
        app = make_wsgi_app(compile_source(BINDING_SOURCE),
                            repository_factory=lambda: SqliteRepositoryDriver(self.path5))

        status, _, body = self._post(
            app, {"id": BINDING_ORDER, "productId": BINDING_PROD}, {"If-Match": 'W/"0"'})

        self.assertEqual(400, status)
        self.assertEqual("precondition-unsupported", body["code"])
        self._no_writes(self.path5)

    def test_if_match_absent_runs_the_binding_lookup_shape_normally(self):
        app = make_wsgi_app(compile_source(BINDING_SOURCE),
                            repository_factory=lambda: SqliteRepositoryDriver(self.path6))
        seed = SqliteRepositoryDriver(self.path6)
        seed.seed({"entity.product": {"entity.product#%s" % BINDING_PROD:
                                      {"id": BINDING_PROD, "stock": 10}}})
        seed.close()

        status, _, body = self._post(app, {"id": BINDING_ORDER, "productId": BINDING_PROD})

        self.assertEqual(200, status)
        self.assertEqual("completed", body["status"])
        driver = SqliteRepositoryDriver(self.path6)
        self.assertEqual(1, len(driver.query("entity.order")))
        self.assertEqual(1, len(driver.read_outbox("event.order.placed")))
        driver.close()

    def test_if_match_against_a_self_referential_lookup_is_400_precondition_unsupported(self):
        app = make_wsgi_app(compile_source(SELF_REF_SOURCE),
                            repository_factory=lambda: SqliteRepositoryDriver(self.path7))

        status, _, body = self._post(
            app, {"id": SELF_REF_ORDER, "productId": SELF_REF_PRODUCT_ID},
            {"If-Match": 'W/"0"'})

        self.assertEqual(400, status)
        self.assertEqual("precondition-unsupported", body["code"])

    def test_if_match_against_a_network_result_lookup_is_400_precondition_unsupported(self):
        driver = FakeNetworkDriver({"ProductLookup": (200, {"productId": NETWORK_PROD})})
        app = make_wsgi_app(compile_source(NETWORK_SOURCE),
                            repository_factory=lambda: SqliteRepositoryDriver(self.path8),
                            network=driver)

        status, _, body = self._post(app, {"id": NETWORK_PROD}, {"If-Match": 'W/"0"'})

        self.assertEqual(400, status)
        self.assertEqual("precondition-unsupported", body["code"])

    # -- unresolvable before execution: safe shape, value absent ---------

    def test_if_match_against_an_absent_input_field_lookup_value_is_400_precondition_unsupported(self):
        app = make_wsgi_app(compile_source(BY_REF_SOURCE),
                            repository_factory=lambda: SqliteRepositoryDriver(self.path9))
        buf = io.StringIO()

        with contextlib.redirect_stderr(buf):
            status, _, body = self._post(
                app, {"id": ABSENT_INPUT_ORDER, "quantity": 1}, {"If-Match": 'W/"0"'})

        self.assertEqual(400, status)
        self.assertEqual("precondition-unsupported", body["code"])
        self.assertNotIn("Traceback", buf.getvalue())
        self._no_writes(self.path9)

    def test_if_match_against_an_empty_body_bare_lookup_value_is_400_precondition_unsupported(self):
        app = make_wsgi_app(compile_source(BARE_SOURCE),
                            repository_factory=lambda: SqliteRepositoryDriver(self.path10))
        buf = io.StringIO()

        with contextlib.redirect_stderr(buf):
            status, _, body = call_wsgi(app, "POST", PLACE_ORDER_PATH,
                                        body=b"{}", headers={"If-Match": 'W/"0"'})

        self.assertEqual(400, status)
        self.assertEqual("precondition-unsupported", body["code"])
        self.assertNotIn("Traceback", buf.getvalue())

    def test_if_match_against_an_absent_caller_claim_lookup_value_is_400_precondition_unsupported(self):
        app = make_wsgi_app(compile_source(CALLER_ROLE_SOURCE),
                            repository_factory=lambda: SqliteRepositoryDriver(self.path11),
                            token_provider=HmacTokenProvider(SECRET))
        token = _forge_hs256_token(SECRET)
        buf = io.StringIO()

        with contextlib.redirect_stderr(buf):
            status, _, body = call_wsgi(app, "POST", PLACE_ORDER_PATH, body=b"{}",
                                        headers={"If-Match": 'W/"0"',
                                                 "Authorization": "Bearer " + token})

        self.assertEqual(400, status)
        self.assertEqual("precondition-unsupported", body["code"])
        self.assertNotIn("Traceback", buf.getvalue())

    # -- caller.<claim> is resolvable pre-execution -----------------------

    def test_if_match_against_a_caller_ref_lookup_is_evaluated(self):
        app = make_wsgi_app(compile_source(CALLER_SUBJECT_SOURCE),
                            repository_factory=lambda: SqliteRepositoryDriver(self.path12),
                            token_provider=HmacTokenProvider(SECRET))
        seed = SqliteRepositoryDriver(self.path12)
        seed.seed({"entity.product": {"entity.product#%s" % CALLER_SUB_PROD:
                                      {"id": CALLER_SUB_PROD, "stock": 100}}})
        seed.close()
        headers = {"If-Match": 'W/"0"',
                   "Authorization": "Bearer " + _forge_hs256_token(SECRET, sub=CALLER_SUB_PROD)}

        status, _, body = self._post(app, {"id": CALLER_ORDER, "quantity": 1}, headers)
        self.assertEqual(200, status)
        self.assertEqual("completed", body["status"])

        status2, _, body2 = self._post(app, {"id": CALLER_ORDER, "quantity": 1}, headers)
        self.assertEqual(412, status2)
        self.assertEqual("precondition-failed", body2["code"])

    # -- no `by` at all, missing id: 412, never a crash or unsupported ----

    def test_if_match_present_and_id_missing_on_a_no_by_workflow_is_412_not_a_crash_or_unsupported(self):
        status, _, body = call_wsgi(self.app, "POST", PLACE_ORDER_PATH,
                                    body=json.dumps({"quantity": 1}).encode("utf-8"),
                                    headers={"If-Match": 'W/"0"'})

        self.assertEqual(412, status)
        self.assertEqual("precondition-failed", body["code"])

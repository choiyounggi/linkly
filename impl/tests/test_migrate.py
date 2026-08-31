"""`lnpl migrate <source...> --entity E --set field=value --backend
sqlite:<path> [--dry-run]` (issue #147): expand-contract's "migrate" step —
backfill one field onto every row of one entity that lacks it, never
overwriting an existing value, re-stamping `_schema_gen` on every row
actually written.
"""

import contextlib
import io
import json
import os
import tempfile
import unittest

from lnpl import cli
from lnpl.drivers import SqliteRepositoryDriver
from lnpl.interp import SCHEMA_GEN_KEY, schema_generation
from lnpl.migrate import MigrateError, run_migration
from lnpl.repo_policy import row_key

SOURCE = """capability postgres

entity Account
    field
        id UUID
        label Text
        status Text
        priority Integer
        active Boolean

service AccountService
    policy
        timeout 5s

workflow Fetch
    read account
"""

ACCOUNT_1 = "11111111-1111-1111-1111-111111111111"
ACCOUNT_2 = "22222222-2222-2222-2222-222222222222"
ACCOUNT_3 = "33333333-3333-3333-3333-333333333333"


class MigrateTestCase(unittest.TestCase):

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.dir = box.name
        self.source = os.path.join(self.dir, "account.lnpl")
        with open(self.source, "w", encoding="utf-8") as fh:
            fh.write(SOURCE)
        self.db = os.path.join(self.dir, "store.db")
        doc = cli.compile_source([self.source])
        self.doc = doc
        self.entity_id = next(n["id"] for n in doc["nodes"]
                              if n["kind"] == "Entity")
        self.entity_node = next(n for n in doc["nodes"] if n["kind"] == "Entity")

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def seed(self, *rows):
        driver = SqliteRepositoryDriver(self.db)
        try:
            table = {row_key(self.entity_id, row): row for row in rows}
            driver.seed({self.entity_id: table})
        finally:
            driver.close()

    def raw_row(self, row_id):
        driver = SqliteRepositoryDriver(self.db)
        try:
            found = driver._conn.execute(
                "SELECT payload FROM lnpl_rows WHERE entity_id = ? AND row_key = ?",
                (self.entity_id, row_key(self.entity_id, {"id": row_id}))).fetchone()
        finally:
            driver.close()
        return json.loads(found[0]) if found else None

    def migrate(self, *extra_argv):
        return self.run_cli(
            ["migrate", self.source, "--entity", "Account",
             "--backend", "sqlite:" + self.db, *extra_argv])


class NormalBackfillTest(MigrateTestCase):
    """(정상) 모든 행에 field가 없으면 전부 채우고, 재스탬프한다."""

    def test_every_row_missing_the_field_is_backfilled_and_restamped(self):
        self.seed({"id": ACCOUNT_1, "label": "a"}, {"id": ACCOUNT_2, "label": "b"})

        rc, out, err = self.migrate("--set", "status=active")

        self.assertEqual(0, rc, err)
        result = json.loads(out)
        self.assertEqual({"scanned": 2, "updated": 2, "skipped": 0}, result)
        expected_stamp = schema_generation(self.entity_node)
        for account_id in (ACCOUNT_1, ACCOUNT_2):
            row = self.raw_row(account_id)
            self.assertEqual("active", row["status"])
            self.assertEqual(expected_stamp, row[SCHEMA_GEN_KEY])


class BooleanFieldTest(MigrateTestCase):
    """(정상+에러) `--set`의 Boolean 파싱 — true/false만 값이고, JSON에도
    실제 boolean으로 저장된다 (문자열이나 0/1 정수가 아니다)."""

    def test_true_and_false_are_parsed_and_stored_as_real_booleans(self):
        # Two separate migrate calls, ACCOUNT_2 seeded only before the
        # second: `migrate` backfills every row of the entity still missing
        # the field, so seeding both up front before the first ("true")
        # call would let it also claim ACCOUNT_2, leaving nothing for the
        # second ("false") call to touch (expand semantics never overwrites).
        self.seed({"id": ACCOUNT_1, "label": "a"})
        rc, out, err = self.migrate("--set", "active=true")
        self.assertEqual(0, rc, err)
        self.assertIs(True, self.raw_row(ACCOUNT_1)["active"])

        self.seed({"id": ACCOUNT_2, "label": "b"})
        rc, out, err = self.migrate("--set", "active=false")
        self.assertEqual(0, rc, err)
        self.assertIs(False, self.raw_row(ACCOUNT_2)["active"])

    def test_value_parsing_is_case_insensitive(self):
        self.seed({"id": ACCOUNT_1, "label": "a"})

        rc, out, err = self.migrate("--set", "active=TRUE")

        self.assertEqual(0, rc, err)
        self.assertIs(True, self.raw_row(ACCOUNT_1)["active"])

    def test_a_non_boolean_value_is_refused_and_writes_nothing(self):
        self.seed({"id": ACCOUNT_1, "label": "a"})

        rc, out, err = self.migrate("--set", "active=maybe")

        self.assertEqual(2, rc)
        self.assertEqual("", out)
        self.assertIn("active", err)
        row = self.raw_row(ACCOUNT_1)
        self.assertNotIn("active", row)
        self.assertNotIn(SCHEMA_GEN_KEY, row)


class DryRunTest(MigrateTestCase):
    """(경계) --dry-run은 카운트만 내고 저장소를 바꾸지 않는다."""

    def test_dry_run_reports_counts_without_writing(self):
        self.seed({"id": ACCOUNT_1, "label": "a"})

        rc, out, err = self.migrate("--set", "status=active", "--dry-run")

        self.assertEqual(0, rc, err)
        self.assertEqual({"scanned": 1, "updated": 1, "skipped": 0}, json.loads(out))
        row = self.raw_row(ACCOUNT_1)
        self.assertNotIn("status", row)
        self.assertNotIn(SCHEMA_GEN_KEY, row)


class OnlyMissingFieldRowsAreTouchedTest(MigrateTestCase):
    """(정상) 이미 값이 있는 행은 절대 덮어쓰지 않는다 (expand 의미론)."""

    def test_a_row_that_already_has_the_field_is_skipped_untouched(self):
        self.seed({"id": ACCOUNT_1, "label": "a", "status": "manual"},
                  {"id": ACCOUNT_2, "label": "b"})

        rc, out, err = self.migrate("--set", "status=active")

        self.assertEqual(0, rc, err)
        self.assertEqual({"scanned": 2, "updated": 1, "skipped": 1}, json.loads(out))
        untouched = self.raw_row(ACCOUNT_1)
        self.assertEqual("manual", untouched["status"])
        self.assertNotIn(SCHEMA_GEN_KEY, untouched)   # never touched -> never re-stamped
        backfilled = self.raw_row(ACCOUNT_2)
        self.assertEqual("active", backfilled["status"])
        self.assertIn(SCHEMA_GEN_KEY, backfilled)


class TypeMismatchRejectedTest(MigrateTestCase):
    """(에러) 선언 타입과 안 맞는 --set 값은 아무것도 쓰지 않고 거부한다."""

    def test_a_non_integer_value_for_an_integer_field_is_refused(self):
        self.seed({"id": ACCOUNT_3, "label": "c"})

        rc, out, err = self.migrate("--set", "priority=not-a-number")

        self.assertEqual(2, rc)
        self.assertEqual("", out)
        self.assertIn("priority", err)
        row = self.raw_row(ACCOUNT_3)
        self.assertNotIn("priority", row)
        self.assertNotIn(SCHEMA_GEN_KEY, row)

    def test_an_undeclared_field_is_refused(self):
        rc, out, err = self.migrate("--set", "doesNotExist=1")

        self.assertEqual(2, rc)
        self.assertIn("doesNotExist", err)

    def test_an_undeclared_entity_is_refused(self):
        rc, out, err = self.run_cli(
            ["migrate", self.source, "--entity", "NoSuchEntity",
             "--set", "status=active", "--backend", "sqlite:" + self.db])

        self.assertEqual(2, rc)
        self.assertIn("NoSuchEntity", err)

    def test_the_fake_backend_is_rejected(self):
        rc, out, err = self.run_cli(
            ["migrate", self.source, "--entity", "Account",
             "--set", "status=active", "--backend", "fake"])

        self.assertNotEqual(0, rc)
        self.assertIn("migrate", err)


class EmptyTableTest(MigrateTestCase):
    """(경계) 빈 테이블 -> 스캔 0, 아무것도 쓰지 않고 rc 0."""

    def test_an_empty_store_scans_and_writes_nothing(self):
        rc, out, err = self.migrate("--set", "status=active")

        self.assertEqual(0, rc, err)
        self.assertEqual({"scanned": 0, "updated": 0, "skipped": 0}, json.loads(out))


class _InjectingRepository:
    """Wraps a real `SqliteRepositoryDriver`; the first `query()` call
    simulates a live server's own concurrent write landing right after
    `run_migration`'s initial table scan and before its per-row read+write
    (review r1 F1's failure window — the expand step in docs/migration.md
    runs while old and new code serve traffic against the same store)."""

    def __init__(self, inner, inject):
        self._inner = inner
        self._inject = inject
        self._injected = False

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def query(self, *args, **kwargs):
        rows = self._inner.query(*args, **kwargs)
        if not self._injected:
            self._injected = True
            self._inject()
        return rows


class ConcurrentWriteDuringMigrateTest(MigrateTestCase):
    """(에러/동시성, review r1 F1) query~persist 사이에 끼어든 남의 쓰기가
    migrate의 통짜 덮어쓰기로 소실되지 않는다."""

    def _inject_concurrent_write(self):
        other = SqliteRepositoryDriver(self.db)
        try:
            key = row_key(self.entity_id, {"id": ACCOUNT_1})
            current = other.execute(self.entity_id, "read", key)
            updated = dict(current)
            updated["visits"] = 5   # a field migrate never touches
            other.persist(self.entity_id, key, updated)
        finally:
            other.close()

    def test_a_concurrent_write_between_scan_and_persist_is_not_lost(self):
        self.seed({"id": ACCOUNT_1, "label": "a"})
        inner = SqliteRepositoryDriver(self.db)
        wrapped = _InjectingRepository(inner, self._inject_concurrent_write)

        try:
            result = run_migration(self.doc, wrapped, "Account", "status", "active")
        finally:
            inner.close()

        self.assertEqual({"scanned": 1, "updated": 1, "skipped": 0}, result)
        row = self.raw_row(ACCOUNT_1)
        self.assertEqual(5, row["visits"])         # the concurrent write survived
        self.assertEqual("active", row["status"])  # migrate's own backfill still applied


class _InjectingOnReReadRepository:
    """Wraps a real `SqliteRepositoryDriver`; the first `execute(..., "read",
    ...)` call (`run_migration`'s own per-row re-read) injects a concurrent
    write for that SAME row right after returning it — the narrower window
    a second audit pass of review r1 F1 found: between this function's own
    re-read and its own `persist()`, not the original whole-table-scan
    window `ConcurrentWriteDuringMigrateTest` above covers."""

    def __init__(self, inner, inject):
        self._inner = inner
        self._inject = inject
        self._injected = False

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def execute(self, entity_id, operation, key):
        result = self._inner.execute(entity_id, operation, key)
        if operation == "read" and not self._injected:
            self._injected = True
            self._inject()
        return result


class ConcurrentWriteDuringPerRowRereadTest(MigrateTestCase):
    """(에러/동시성, review r1 F1 재감사) per-row 재읽기 직후~persist 직전의
    더 좁은 경합은 조용히 잃지 않고 배치 전체를 시끄럽게 실패시킨다 — 두
    번째 감사가 발견한 것: 첫 수정은 `current`를 `dict(current)`로 복사해
    `observed_version`을 잃었고(interp.py에서 이미 한 번 낸 것과 같은
    실수), 그래서 이 경합에서 낙관적 잠금이 전혀 걸리지 않고 조용히
    소실됐었다."""

    def _inject_concurrent_write(self):
        other = SqliteRepositoryDriver(self.db)
        try:
            key = row_key(self.entity_id, {"id": ACCOUNT_1})
            current = other.execute(self.entity_id, "read", key)
            updated = dict(current)
            updated["visits"] = 9
            other.persist(self.entity_id, key, updated)
        finally:
            other.close()

    def test_a_write_between_the_per_row_reread_and_persist_fails_the_whole_batch(self):
        self.seed({"id": ACCOUNT_1, "label": "a"})
        inner = SqliteRepositoryDriver(self.db)
        wrapped = _InjectingOnReReadRepository(inner, self._inject_concurrent_write)

        try:
            with self.assertRaises(MigrateError):
                run_migration(self.doc, wrapped, "Account", "status", "active")
        finally:
            inner.close()

        # Loud failure, not a silent partial write: the whole transaction
        # rolled back, so migrate's own field never landed...
        row = self.raw_row(ACCOUNT_1)
        self.assertNotIn("status", row)
        self.assertNotIn(SCHEMA_GEN_KEY, row)
        # ...while the concurrent write — already committed on its own,
        # separate connection before migrate's rollback ever ran — stands.
        self.assertEqual(9, row["visits"])


if __name__ == "__main__":
    unittest.main()


NS_BILLING = """entity Order
    field
        id UUID
        status Text
"""

NS_SHIPPING = """entity Order
    field
        id UUID
        status Text
        carrier Text
"""

ORDER_1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class NamespacedEntityResolutionTest(unittest.TestCase):
    """RFC-0033 (#146) x `lnpl migrate` (#147).

    RFC-0033 makes "same short name, different namespace" a legal non-
    collision and `migrate` accepts a directory, so a bare `--entity Order`
    can name two entities at once. Resolution used to match `node["name"]`
    and take the first hit, which backfilled the wrong entity's rows with no
    error and no log line, and left the second entity unreachable under every
    spelling. These pin the refusal and the qualified spelling; the single-
    namespace cases pin that unambiguous layouts are untouched.
    """

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.dir = box.name
        self.db = os.path.join(self.dir, "store.db")

    def _write(self, relpath, text):
        path = os.path.join(self.dir, "src", relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def _src(self):
        return os.path.join(self.dir, "src")

    def _both_namespaces(self):
        self._write("billing/order.lnpl", NS_BILLING)
        self._write("shipping/order.lnpl", NS_SHIPPING)

    def _doc(self):
        return cli.compile_source([self._src()])

    def _entity(self, qualified):
        doc = self._doc()
        return next(n for n in doc["nodes"]
                    if n["kind"] == "Entity"
                    and "%s.%s" % (n.get("namespace"), n["name"]) == qualified)

    def _seed(self, entity_id, *rows):
        driver = SqliteRepositoryDriver(self.db)
        try:
            driver.seed({entity_id: {row_key(entity_id, r): r for r in rows}})
        finally:
            driver.close()

    def _raw(self, entity_id, row_id):
        driver = SqliteRepositoryDriver(self.db)
        try:
            found = driver._conn.execute(
                "SELECT payload FROM lnpl_rows WHERE entity_id = ? AND row_key = ?",
                (entity_id, row_key(entity_id, {"id": row_id}))).fetchone()
        finally:
            driver.close()
        return json.loads(found[0]) if found else None

    def _migrate(self, entity_arg, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(["migrate", self._src(), "--entity", entity_arg,
                           "--backend", "sqlite:" + self.db, *extra])
        return rc, out.getvalue(), err.getvalue()

    # (에러) 모호한 짧은 이름은 추측하지 않고 거부한다 — 이 결함의 본체.
    def test_an_ambiguous_bare_name_is_refused_not_guessed(self):
        self._both_namespaces()
        rc, _, err = self._migrate("Order", "--set", "status=new")

        self.assertNotEqual(0, rc)
        self.assertIn("ambiguous", err)

    def test_the_refusal_names_every_candidate(self):
        self._both_namespaces()
        rc, _, err = self._migrate("Order", "--set", "status=new")

        self.assertNotEqual(0, rc)
        self.assertIn("billing.Order", err)
        self.assertIn("shipping.Order", err)

    # (정상) 정규화된 이름은 정확히 그 엔티티에 도달한다.
    def test_a_qualified_name_reaches_the_second_namespace(self):
        self._both_namespaces()
        shipping = self._entity("shipping.Order")
        self._seed(shipping["id"], {"id": ORDER_1, "carrier": "ups"})

        rc, out, err = self._migrate("shipping.Order", "--set", "status=new")

        self.assertEqual(0, rc, err)
        self.assertEqual({"scanned": 1, "updated": 1, "skipped": 0},
                         json.loads(out))
        self.assertEqual("new", self._raw(shipping["id"], ORDER_1)["status"])

    def test_a_qualified_name_does_not_touch_the_other_namespace(self):
        self._both_namespaces()
        billing = self._entity("billing.Order")
        shipping = self._entity("shipping.Order")
        self._seed(billing["id"], {"id": ORDER_1})
        self._seed(shipping["id"], {"id": ORDER_1, "carrier": "ups"})

        rc, _, err = self._migrate("shipping.Order", "--set", "status=new")

        self.assertEqual(0, rc, err)
        self.assertIsNone(self._raw(billing["id"], ORDER_1).get("status"))

    # (경계) 네임스페이스가 하나뿐이면 짧은 이름이 그대로 동작한다.
    def test_a_bare_name_still_resolves_when_only_one_namespace_declares_it(self):
        self._write("billing/order.lnpl", NS_BILLING)
        billing = self._entity("billing.Order")
        self._seed(billing["id"], {"id": ORDER_1})

        rc, out, err = self._migrate("Order", "--set", "status=new")

        self.assertEqual(0, rc, err)
        self.assertEqual({"scanned": 1, "updated": 1, "skipped": 0},
                         json.loads(out))

    def test_a_namespaced_entity_is_reachable_by_its_bare_name_too(self):
        self._write("billing/order.lnpl", NS_BILLING)
        billing = self._entity("billing.Order")
        self._seed(billing["id"], {"id": ORDER_1})

        rc, _, err = self._migrate("billing.Order", "--set", "status=new")

        self.assertEqual(0, rc, err)
        self.assertEqual("new", self._raw(billing["id"], ORDER_1)["status"])

    # (에러) 존재하지 않는 이름은 여전히 undeclared로 거부된다.
    def test_an_unknown_qualified_name_is_still_undeclared(self):
        self._both_namespaces()
        rc, _, err = self._migrate("warehouse.Order", "--set", "status=new")

        self.assertNotEqual(0, rc)
        self.assertIn("no declared entity", err)

    def test_a_namespace_qualifier_on_a_flat_entity_is_undeclared(self):
        self._write("billing/order.lnpl", NS_BILLING)
        rc, _, err = self._migrate("shipping.Order", "--set", "status=new")

        self.assertNotEqual(0, rc)
        self.assertIn("no declared entity", err)

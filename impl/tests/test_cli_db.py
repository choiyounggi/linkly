"""`lnpl db check <source...> --backend sqlite:<path>` (issue #85).

The external backfill tool this JSON feeds needs one full-table statement,
not a per-row `run`: every row of every declared entity, checked against
the entity's own declaration, unmatched rows listed (entity/row_key/field/
expected_type/kind — never a value, D2), rc 1 iff any row is wrong-shaped,
rc 0 on a clean store. `--backend` is required and `fake` is rejected (no
persistent rows to check) — the same shape `outbox drain`/`outbox ack`
already established for a check that is meaningless without a real store.
"""

import contextlib
import io
import json
import os
import tempfile
import unittest

from lnpl import cli
from lnpl.drivers import SqliteRepositoryDriver
from lnpl.repo_policy import row_key

SOURCE = """capability postgres

entity Account
    field
        id UUID
        label Text
        cardSecret Password

service AccountService
    policy
        timeout 5s

workflow Fetch
    read account
"""

# Split for the multi-file test — same declarations, two files, explicit
# order (RFC-0031, issue #77): entity first, service+workflow second.
SOURCE_PART_ENTITY = """capability postgres

entity Account
    field
        id UUID
        label Text
        cardSecret Password
"""

SOURCE_PART_WORKFLOW = """service AccountService
    policy
        timeout 5s

workflow Fetch
    read account
"""

SECRET_VALUE = 135790

# `id` is declared `UUID`, which checks the RFC 4122 text shape, not merely
# "a string" — every row below needs one that actually matches.
ACCOUNT_1 = "11111111-1111-1111-1111-111111111111"
ACCOUNT_2 = "22222222-2222-2222-2222-222222222222"
ACCOUNT_3 = "33333333-3333-3333-3333-333333333333"

MATCHING_ROW = {"id": ACCOUNT_1, "label": "widget", "cardSecret": "tok-abc"}
STALE_ROW = {"id": ACCOUNT_2, "label": "widget"}  # missing cardSecret
# `label` is `Text` (`isinstance(value, str)`) — an int fails it. `Password`
# only checks `str(value)` is non-empty (RFC-0001 A.6.3), so a wrong-typed
# *value* has to land on `label`, not `cardSecret`, to exercise "type".
WRONG_TYPE_ROW = {"id": ACCOUNT_3, "label": SECRET_VALUE, "cardSecret": "tok-xyz"}


class DbCheckTestCase(unittest.TestCase):

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.dir = box.name
        self.source = os.path.join(self.dir, "account.lnpl")
        with open(self.source, "w", encoding="utf-8") as fh:
            fh.write(SOURCE)
        self.db = os.path.join(self.dir, "store.db")
        doc = cli.compile_source([self.source])
        self.entity_id = next(n["id"] for n in doc["nodes"]
                              if n["kind"] == "Entity")

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

    def check(self, source=None, extra_argv=()):
        return self.run_cli(
            ["db", "check", *(source or [self.source]),
             "--backend", "sqlite:" + self.db, *extra_argv])


class EmptyStoreTest(DbCheckTestCase):
    """(경계) 빈 DB -> rc 0, `[]`."""

    def test_an_empty_store_is_clean(self):
        rc, out, err = self.check()

        self.assertEqual(0, rc, err)
        self.assertEqual([], json.loads(out))


class MatchingStoreTest(DbCheckTestCase):
    """(경계) 선언과 정합한 행만 있는 DB -> rc 0, `[]` (회귀)."""

    def test_a_fully_matching_store_is_clean(self):
        self.seed(MATCHING_ROW)

        rc, out, err = self.check()

        self.assertEqual(0, rc, err)
        self.assertEqual([], json.loads(out))


class MismatchedStoreTest(DbCheckTestCase):
    """(정상) 구행 존재 -> rc 1 + 불일치 행 JSON 나열 (entity/row_key/field/kind)."""

    def test_a_stale_row_is_reported_missing(self):
        self.seed(STALE_ROW)

        rc, out, err = self.check()

        self.assertEqual(1, rc, err)
        findings = json.loads(out)
        self.assertEqual(1, len(findings), findings)
        entry = findings[0]
        self.assertEqual("Account", entry["entity"])
        self.assertEqual(row_key(self.entity_id, STALE_ROW), entry["row_key"])
        self.assertEqual("cardSecret", entry["field"])
        self.assertEqual("missing", entry["kind"])
        self.assertEqual("Password", entry["expected_type"])

    def test_mixed_clean_and_stale_rows_reports_only_the_stale_one(self):
        self.seed(MATCHING_ROW, STALE_ROW)

        rc, out, err = self.check()

        self.assertEqual(1, rc, err)
        findings = json.loads(out)
        self.assertEqual(1, len(findings), findings)
        self.assertEqual(row_key(self.entity_id, STALE_ROW), findings[0]["row_key"])


class ValueNonExposureTest(DbCheckTestCase):
    """(경계) 타입 불일치 행의 JSON 출력에 저장값이 없다 (D2)."""

    def test_a_wrong_typed_field_never_names_its_value(self):
        self.seed(WRONG_TYPE_ROW)

        rc, out, err = self.check()

        self.assertEqual(1, rc, err)
        findings = json.loads(out)
        self.assertEqual("type", findings[0]["kind"])
        self.assertNotIn(str(SECRET_VALUE), out)


class MultiFileSourceTest(DbCheckTestCase):
    """(경계) 다중 파일 소스도 load_sources로 병합돼 동일하게 동작 (t77)."""

    def test_two_files_merge_and_check_the_same_as_one(self):
        part1 = os.path.join(self.dir, "01_entity.lnpl")
        part2 = os.path.join(self.dir, "02_workflow.lnpl")
        with open(part1, "w", encoding="utf-8") as fh:
            fh.write(SOURCE_PART_ENTITY)
        with open(part2, "w", encoding="utf-8") as fh:
            fh.write(SOURCE_PART_WORKFLOW)
        self.seed(STALE_ROW)

        rc, out, err = self.check(source=[part1, part2])

        self.assertEqual(1, rc, err)
        findings = json.loads(out)
        self.assertEqual(1, len(findings), findings)
        self.assertEqual("cardSecret", findings[0]["field"])


class FakeBackendRejectedTest(DbCheckTestCase):
    """(에러) `fake`는 영속 저장소가 없어 db check가 rc != 0으로 거부."""

    def test_fake_backend_is_rejected(self):
        rc, out, err = self.run_cli(
            ["db", "check", self.source, "--backend", "fake"])

        self.assertNotEqual(0, rc)
        self.assertIn("db check", err)


if __name__ == "__main__":
    unittest.main()

"""`stored-row-shape-mismatch` — a `read`/`find` step's row vs. its entity
declaration (issue #85).

The generic JSON-blob store never validates a stored row against the entity
declaration on the way in or out, so a row written before a field was added
(or before a field's type was refined) reads back silently wrong-shaped —
the "quietly wrong" defect class this issue exists to close. The fix is not
enforcement: the runtime still returns the row as-is. It is visibility — a
warning-grade diagnostic, on the same channel `authorization-not-verified`
already uses (issue #38), naming the entity/field/expected-type/kind and
never the stored value (D2 — the masking chokepoint `SECRET_ACCOUNT`'s
`cardSecret Password` field already exists to test).
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

OLD_SHAPE_SRC = """capability postgres

entity Account
    field
        id UUID
        label Text

service AccountService
    policy
        timeout 5s

workflow Seed
    create account
"""

NEW_SHAPE_SRC = """capability postgres

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

SECRET_VALUE = 987654321  # a Password field must be str; an int is wrong-shaped

# `id` is declared `UUID`, which checks the RFC 4122 text shape (types.py's
# UUID_RE) — not merely "a string" — so every test id below must be one.
ACCOUNT_1 = "11111111-1111-1111-1111-111111111111"
ACCOUNT_2 = "22222222-2222-2222-2222-222222222222"
ACCOUNT_3 = "33333333-3333-3333-3333-333333333333"
ACCOUNT_4 = "44444444-4444-4444-4444-444444444444"


class RowShapeTestCase(unittest.TestCase):

    def setUp(self):
        box = tempfile.TemporaryDirectory()
        self.addCleanup(box.cleanup)
        self.dir = box.name
        self.old_source = os.path.join(self.dir, "old.lnpl")
        with open(self.old_source, "w", encoding="utf-8") as fh:
            fh.write(OLD_SHAPE_SRC)
        self.new_source = os.path.join(self.dir, "new.lnpl")
        with open(self.new_source, "w", encoding="utf-8") as fh:
            fh.write(NEW_SHAPE_SRC)
        self.db = os.path.join(self.dir, "store.db")
        doc = cli.compile_source([self.new_source])
        self.entity_id = next(n["id"] for n in doc["nodes"]
                              if n["kind"] == "Entity")

    def payload_file(self, payload, name="payload.json"):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return path

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def seed_row(self, key, row):
        driver = SqliteRepositoryDriver(self.db)
        try:
            driver.seed({self.entity_id: {key: row}})
        finally:
            driver.close()

    def create_old_shape_row(self, account_id=ACCOUNT_1):
        """A row persisted under `OLD_SHAPE_SRC` — no `cardSecret` key at
        all, because `NEW_SHAPE_SRC` added the field afterwards."""
        payload = self.payload_file({"id": account_id, "label": "widget"})
        rc, _, err = self.run_cli(
            ["run", self.old_source, "--backend", "sqlite:" + self.db,
             "--payload", payload])
        self.assertEqual(0, rc, err)

    def fetch(self, account_id=ACCOUNT_1, extra_argv=()):
        payload = self.payload_file({"id": account_id}, name="fetch.json")
        return self.run_cli(
            ["run", self.new_source, "--backend", "sqlite:" + self.db,
             "--payload", payload, "--json", *extra_argv])

    def row_shape_diagnostics(self, out):
        return [d for d in json.loads(out)["diagnostics"]
                if d["code"] == "stored-row-shape-mismatch"]


class MissingFieldWarningTest(RowShapeTestCase):
    """(정상) 필드 추가 후 구행 read -> warning 발화 (kind=missing)."""

    def test_reading_an_old_shape_row_warns_missing_field(self):
        self.create_old_shape_row()

        rc, out, err = self.fetch()

        self.assertEqual(0, rc, err)
        found = self.row_shape_diagnostics(out)
        self.assertEqual(1, len(found), found)
        self.assertEqual("warning", found[0]["severity"])
        self.assertIn("cardSecret", found[0]["message"])
        self.assertIn("Account", found[0]["subject"])


class TypeMismatchWarningTest(RowShapeTestCase):
    """(정상) 타입 불일치 -> warning(kind=type), 값은 메시지에 없음 (D2)."""

    def test_a_wrong_typed_field_warns_and_never_names_the_value(self):
        # `label` is `Text` (`isinstance(value, str)`) — an int fails it. A
        # `Password` field only checks `str(value)` is non-empty (RFC-0001
        # A.6.3), so a wrong-typed *value* has to land on `label` here, not
        # `cardSecret`, to actually exercise the "type" kind.
        self.seed_row(row_key(self.entity_id, {"id": ACCOUNT_2}),
                     {"id": ACCOUNT_2, "label": SECRET_VALUE, "cardSecret": "tok-xyz"})

        rc, out, err = self.fetch(account_id=ACCOUNT_2)

        self.assertEqual(0, rc, err)
        found = self.row_shape_diagnostics(out)
        self.assertEqual(1, len(found), found)
        self.assertIn("label", found[0]["message"])
        # The diagnostic channel specifically (D2) — not `run`'s whole JSON,
        # which legitimately echoes the bound row elsewhere (`result.bindings`).
        self.assertNotIn(str(SECRET_VALUE), json.dumps(found))
        self.assertNotIn(str(SECRET_VALUE), err)


class MatchingRowNoWarningTest(RowShapeTestCase):
    """(경계) 선언과 정합한 행은 무발화 — 회귀."""

    def test_a_fully_matching_row_emits_nothing(self):
        self.seed_row(row_key(self.entity_id, {"id": ACCOUNT_3}),
                     {"id": ACCOUNT_3, "label": "widget", "cardSecret": "tok-abc"})

        rc, out, err = self.fetch(account_id=ACCOUNT_3)

        self.assertEqual(0, rc, err)
        self.assertEqual([], self.row_shape_diagnostics(out))


class StrictGateTest(RowShapeTestCase):
    """(에러 게이트) --strict=warning + 구행 read -> rc != 0."""

    def test_strict_warning_turns_the_warning_into_a_nonzero_rc(self):
        self.create_old_shape_row(account_id=ACCOUNT_4)

        rc, out, err = self.fetch(account_id=ACCOUNT_4, extra_argv=("--strict=warning",))

        self.assertNotEqual(0, rc)
        self.assertTrue(self.row_shape_diagnostics(out))


if __name__ == "__main__":
    unittest.main()

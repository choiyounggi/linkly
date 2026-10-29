"""`lnpl db backup` (issue #238): an online copy of a sqlite store through the
SQLite backup API, its refusals, and the backup -> delete -> restore ->
`db check` -> row-count rehearsal. Every store lives under `.claude/tmp`,
never the system temp directory."""

import contextlib
import hashlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
import uuid
from unittest import mock

from lnpl import cli
from lnpl.drivers import SqliteRepositoryDriver
from lnpl.repo_policy import row_key

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

INSERT = "INSERT INTO lnpl_rows (entity_id, row_key, payload) VALUES (?, ?, ?)"

NON_SQLITE = ("error: db backup: backend '%s' does not support online backup; "
              "for postgres use pg_dump (see docs/backends.md §14)\n")


def make_row(i, label="seed"):
    return {"id": str(uuid.UUID(int=i)), "label": label, "cardSecret": "tok"}


class BackupTestCase(unittest.TestCase):

    def setUp(self):
        base = os.path.join(REPO, ".claude", "tmp")
        os.makedirs(base, exist_ok=True)
        self.dir = tempfile.mkdtemp(prefix="lnpl-t238-", dir=base)
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.source = os.path.join(self.dir, "account.lnpl")
        with open(self.source, "w", encoding="utf-8") as fh:
            fh.write(SOURCE)
        self.db = os.path.join(self.dir, "store.db")
        self.out = os.path.join(self.dir, "backup.db")
        doc = cli.compile_source([self.source])
        self.entity_id = next(n["id"] for n in doc["nodes"]
                              if n["kind"] == "Entity")

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def seed(self, rows):
        driver = SqliteRepositoryDriver(self.db)
        try:
            driver.seed({self.entity_id: {row_key(self.entity_id, r): r
                                          for r in rows}})
        finally:
            driver.close()

    def backup(self, out=None, backend=None):
        return self.run_cli(["db", "backup",
                             "--backend", backend or "sqlite:" + self.db,
                             "--out", out or self.out])

    @staticmethod
    def count(path):
        c = sqlite3.connect(path)
        try:
            return c.execute("SELECT count(*) FROM lnpl_rows").fetchone()[0]
        finally:
            c.close()


class BackupWhileWritingTest(BackupTestCase):
    """Scenario S1: 500 checkpointed rows, 200 committed rows still in the
    `-wal`, 50 rows in an open write transaction while the backup runs."""

    def _scenario(self, patch_run_backup=None):
        self.seed([make_row(i) for i in range(1, 501)])
        w = sqlite3.connect(self.db, isolation_level=None)
        self.addCleanup(w.close)
        w.execute("PRAGMA wal_autocheckpoint=0")
        w.execute("PRAGMA busy_timeout=5000")
        w.execute("BEGIN")
        for i in range(501, 701):
            row = make_row(i, "committed")
            w.execute(INSERT, (self.entity_id, row_key(self.entity_id, row),
                               json.dumps(row, sort_keys=True)))
        w.execute("COMMIT")
        self.assertGreater(os.path.getsize(self.db + "-wal"), 0)
        w.execute("BEGIN IMMEDIATE")
        for i in range(701, 751):
            row = make_row(i, "uncommitted")
            w.execute(INSERT, (self.entity_id, row_key(self.entity_id, row),
                               json.dumps(row, sort_keys=True)))
        if patch_run_backup is not None:
            with mock.patch("lnpl.sqlite_backup._run_backup",
                            side_effect=patch_run_backup):
                rc, out, err = self.backup()
        else:
            rc, out, err = self.backup()
        in_tx = w.in_transaction
        w.execute("COMMIT")
        final = self.count(self.db)
        return rc, out, err, in_tx, final

    def test_backup_api_copies_every_committed_row_and_nothing_else(self):
        rc, out, err, in_tx, final = self._scenario()
        self.assertEqual(0, rc, err)
        self.assertEqual("", err)
        self.assertEqual({"out": self.out, "rows": 700}, json.loads(out))
        self.assertEqual(700, self.count(self.out))
        self.assertIs(True, in_tx)
        self.assertEqual(750, final)
        c = sqlite3.connect(self.out)
        try:
            self.assertEqual("ok", c.execute("PRAGMA integrity_check").fetchone()[0])
        finally:
            c.close()
        self.assertFalse(os.path.exists(self.out + "-wal"))
        self.assertFalse(os.path.exists(self.out + "-shm"))

    def test_a_file_copy_stand_in_loses_the_wal_rows(self):
        # Known-bad control: a plain copy of the .db misses the -wal commits,
        # so the 700 equality above discriminates the backup API from it.
        rc, _out, err, _in_tx, _final = self._scenario(
            lambda src, dst: shutil.copyfile(self.db, self.out))
        self.assertEqual(0, rc, err)
        self.assertEqual(500, self.count(self.out))


class EmptyStoreTest(BackupTestCase):

    def test_an_empty_store_backs_up_to_zero_rows(self):
        SqliteRepositoryDriver(self.db).close()
        rc, out, err = self.backup()
        self.assertEqual(0, rc, err)
        self.assertEqual(0, json.loads(out)["rows"])
        self.assertTrue(os.path.isfile(self.out))


class ExistingOutTest(BackupTestCase):

    def test_an_existing_out_is_refused_and_left_unchanged(self):
        with open(self.out, "wb") as fh:
            fh.write(b"keep me")
        with open(self.out, "rb") as fh:
            before = hashlib.sha256(fh.read()).hexdigest()
        self.seed([make_row(1)])
        rc, out, err = self.backup()
        self.assertEqual(2, rc)
        self.assertEqual("", out)
        self.assertEqual("error: db backup: --out already exists, refusing to "
                         "overwrite: %r\n" % self.out, err)
        with open(self.out, "rb") as fh:
            self.assertEqual(before, hashlib.sha256(fh.read()).hexdigest())

    def test_out_equal_to_the_source_is_refused(self):
        self.seed([make_row(1), make_row(2)])
        rc, out, err = self.backup(out=self.db)
        self.assertEqual(2, rc)
        self.assertEqual("", out)
        self.assertEqual(2, self.count(self.db))


class NonSqliteBackendTest(BackupTestCase):

    def _refused(self, backend):
        with mock.patch("lnpl.cli._open_backend") as opened:
            rc, out, err = self.backup(backend=backend)
        opened.assert_not_called()
        return rc, out, err

    def test_fake_is_refused_with_the_pg_dump_pointer(self):
        rc, out, err = self._refused("fake")
        self.assertEqual(2, rc)
        self.assertEqual(NON_SQLITE % "fake", err)
        self.assertFalse(os.path.exists(self.out))

    def test_postgres_is_refused_without_echoing_the_dsn(self):
        rc, out, err = self._refused(
            "postgres:postgresql://app:fake-pass-4821@db.invalid/app")
        self.assertEqual(2, rc)
        self.assertEqual(NON_SQLITE % "postgres", err)
        self.assertNotIn("fake-pass-4821", err)
        self.assertFalse(os.path.exists(self.out))

    def test_an_unrecognized_selector_names_no_scheme(self):
        rc, out, err = self._refused("nosuch")
        self.assertEqual(2, rc)
        self.assertEqual(NON_SQLITE % "<unrecognized>", err)


class OutPathTest(BackupTestCase):

    def test_a_missing_parent_directory_is_an_operator_error(self):
        self.seed([make_row(1)])
        bad = os.path.join(self.dir, "missing-dir", "bak.db")
        rc, out, err = self.backup(out=bad)
        self.assertEqual(2, rc)
        self.assertEqual("", out)
        self.assertEqual("error: db backup: --out parent directory does not "
                         "exist: %r\n" % bad, err)
        self.assertNotIn("Traceback", err)

    def test_an_empty_out_is_refused(self):
        self.seed([make_row(1)])
        rc, out, err = self.run_cli(["db", "backup", "--backend",
                                     "sqlite:" + self.db, "--out", ""])
        self.assertEqual(2, rc)
        self.assertEqual("error: db backup: --out needs a file path, got an "
                         "empty one\n", err)


class SourceTest(BackupTestCase):

    def test_a_missing_source_is_refused_and_not_created(self):
        rc, out, err = self.backup()
        self.assertEqual(2, rc)
        self.assertEqual("error: db backup: no sqlite store at %r\n" % self.db, err)
        self.assertFalse(os.path.exists(self.db))

    def test_a_sqlite_file_without_lnpl_rows_is_refused(self):
        other = os.path.join(self.dir, "other.db")
        c = sqlite3.connect(other)
        try:
            c.execute("CREATE TABLE t (x)")
            c.commit()
        finally:
            c.close()
        rc, out, err = self.backup(backend="sqlite:" + other)
        self.assertEqual(2, rc)
        self.assertEqual("error: db backup: %r has no lnpl_rows table, so it is "
                         "not an lnpl store\n" % other, err)

    def test_a_text_file_is_refused(self):
        notes = os.path.join(self.dir, "notes.txt")
        with open(notes, "w", encoding="utf-8") as fh:
            fh.write("not a database\n")
        rc, out, err = self.backup(backend="sqlite:" + notes)
        self.assertEqual(2, rc)
        self.assertTrue(err.startswith(
            "error: db backup: cannot read %r as a sqlite database: " % notes), err)
        self.assertFalse(os.path.exists(self.out))

    def test_an_empty_sqlite_path_is_refused(self):
        rc, out, err = self.backup(backend="sqlite:")
        self.assertEqual(2, rc)
        self.assertEqual("error: db backup: --backend sqlite: needs a file path, "
                         "got an empty one (e.g. --backend sqlite:./store.db)\n", err)


class ReadOnlySourceDirTest(BackupTestCase):
    """A backup only reads its source: a read-only source directory (a
    sidecar mounting the data volume `:ro`) is not refused for writability."""

    def setUp(self):
        super().setUp()
        if os.geteuid() == 0:
            self.skipTest("root ignores directory permissions")
        self.ro = os.path.join(self.dir, "ro")
        os.makedirs(self.ro)
        self.db = os.path.join(self.ro, "store.db")

    def _lock(self):
        os.chmod(self.ro, 0o555)
        # Registered after the parent's rmtree, so it runs first.
        self.addCleanup(os.chmod, self.ro, 0o755)
        self.assertFalse(os.access(self.ro, os.W_OK))

    def test_a_live_store_in_a_read_only_directory_is_backed_up(self):
        self.seed([make_row(i) for i in (1, 2, 3)])
        writer = SqliteRepositoryDriver(self.db)  # keeps -wal/-shm, as `serve` does
        self.addCleanup(writer.close)
        self._lock()
        rc, out, err = self.backup()
        self.assertEqual(0, rc, err)
        self.assertEqual("", err)
        self.assertEqual({"out": self.out, "rows": 3}, json.loads(out))
        self.assertEqual(3, self.count(self.out))

    def test_a_closed_store_in_a_read_only_directory_is_refused_as_unreadable(self):
        # SQLite must create `-shm` to read a WAL store; with the writer gone
        # and the directory read-only it cannot, so this stays an rc 2 that
        # names the read, not the directory's writability.
        self.seed([make_row(1)])
        self._lock()
        rc, out, err = self.backup()
        self.assertEqual(2, rc)
        self.assertEqual("", out)
        self.assertTrue(err.startswith(
            "error: db backup: cannot read %r as a sqlite database: " % self.db), err)
        self.assertNotIn("not writable", err)
        self.assertNotIn("Traceback", err)
        self.assertFalse(os.path.exists(self.out))


class FailureTest(BackupTestCase):

    def test_a_sqlite_error_mid_copy_exits_1_and_removes_the_partial_file(self):
        self.seed([make_row(1)])
        with mock.patch("lnpl.sqlite_backup._run_backup",
                        side_effect=sqlite3.OperationalError("disk I/O error")):
            rc, out, err = self.backup()
        self.assertEqual(1, rc)
        self.assertEqual("error: db backup: backup failed: disk I/O error\n", err)
        self.assertFalse(os.path.exists(self.out))


class RestoreRehearsalTest(BackupTestCase):
    """The restore procedure of docs/backends.md §14, run in CI."""

    def test_backup_delete_restore_check_and_count(self):
        self.seed([make_row(i) for i in (1, 2, 3)])
        rc, out, err = self.backup()
        self.assertEqual(0, rc, err)
        self.assertEqual(3, json.loads(out)["rows"])
        for path in (self.db, self.db + "-wal", self.db + "-shm"):
            if os.path.exists(path):
                os.remove(path)
        for path in (self.db, self.db + "-wal", self.db + "-shm"):
            self.assertFalse(os.path.exists(path))
        shutil.copyfile(self.out, self.db)
        rc, out, err = self.run_cli(["db", "check", self.source,
                                     "--backend", "sqlite:" + self.db])
        self.assertEqual(0, rc, err)
        self.assertEqual([], json.loads(out))
        verify = os.path.join(self.dir, "verify.db")
        rc, out, err = self.backup(out=verify)
        self.assertEqual(0, rc, err)
        self.assertEqual(3, json.loads(out)["rows"])
        driver = SqliteRepositoryDriver(self.db)
        try:
            self.assertEqual(3, len(driver.query(self.entity_id)))
        finally:
            driver.close()


class DocAgreementTest(BackupTestCase):
    """docs/backends.md §14 quotes the command's real output; this fails
    whenever the command and the doc disagree."""

    def setUp(self):
        super().setUp()
        old = os.getcwd()
        os.chdir(self.dir)
        # Registered after the parent's rmtree, so it runs first.
        self.addCleanup(os.chdir, old)

    def section(self):
        with open(os.path.join(REPO, "docs", "backends.md"), encoding="utf-8") as fh:
            lines = fh.read().split("\n")
        start = next(i for i, line in enumerate(lines) if line.startswith("## 14."))
        end = next(i for i in range(start + 1, len(lines))
                   if lines[i].startswith("## 15."))
        return "\n".join(lines[start:end])

    def test_the_section_slice_is_bounded(self):
        s = self.section()
        self.assertTrue(s.startswith("## 14."))
        self.assertNotIn("\n## 15.", s)
        self.assertIn("lnpl db backup", s)

    def test_every_documented_output_matches_the_command(self):
        self.seed([make_row(i) for i in (1, 2, 3)])
        s = self.section()
        argv = ["db", "backup", "--backend", "sqlite:store.db", "--out", "backup.db"]
        rc, out, err = self.run_cli(argv)
        self.assertEqual(0, rc, err)
        self.assertIn(out.rstrip("\n"), s)
        rc, out, err = self.run_cli(argv)
        self.assertEqual(2, rc)
        self.assertIn(err.rstrip("\n"), s)
        rc, out, err = self.run_cli(["db", "backup", "--backend", "fake",
                                     "--out", "backup2.db"])
        self.assertEqual(2, rc)
        self.assertIn(err.rstrip("\n"), s)
        rc, out, err = self.run_cli([
            "db", "backup", "--backend",
            "postgres:postgresql://app:example-password@db.invalid/app",
            "--out", "backup2.db"])
        self.assertEqual(2, rc)
        self.assertIn(err.rstrip("\n"), s)
        for path in ("store.db", "store.db-wal", "store.db-shm"):
            if os.path.exists(path):
                os.remove(path)
        shutil.copyfile("backup.db", "store.db")
        rc, out, err = self.run_cli(["db", "check", "account.lnpl",
                                     "--backend", "sqlite:store.db"])
        self.assertEqual(0, rc, err)
        self.assertIn(out.rstrip("\n"), s)
        rc, out, err = self.run_cli(["db", "backup", "--backend", "sqlite:store.db",
                                     "--out", "verify.db"])
        self.assertEqual(0, rc, err)
        self.assertIn(out.rstrip("\n"), s)
        self.assertEqual(3, json.loads(out)["rows"])


if __name__ == "__main__":
    unittest.main()

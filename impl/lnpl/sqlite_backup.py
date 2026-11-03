"""`lnpl db backup` (issue #238) — an online copy of a sqlite store through the
SQLite backup API. A file copy of the `.db` misses commits still in its `-wal`
(docs/backends.md §14), so the copy is always made by `Connection.backup`.
"""

import os
import sqlite3
from pathlib import Path

from .drivers import BUSY_TIMEOUT_MS

_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


class BackupRefused(Exception):
    """An operator error found before anything was written (rc 2)."""


class BackupFailed(Exception):
    """sqlite failed during the copy; the partial copy is removed (rc 1)."""


def _run_backup(src, dst):
    # The only call of `.backup`: tests patch this name.
    src.backup(dst)


def _open_source(source_raw):
    """A read connection to an existing lnpl store. Never goes through
    `SqliteRepositoryDriver(...)`/`open_repository`: they create a missing
    file, and a backup must not invent the store it was asked to copy. Nor
    `SqliteRepositoryDriver._resolve`: it requires a writable parent, and a
    backup only reads (a sidecar may mount the data volume read-only)."""
    if not source_raw.strip():
        raise BackupRefused("db backup: --backend sqlite: needs a file path, got "
                            "an empty one (e.g. --backend sqlite:./store.db)")
    resolved = Path(source_raw).expanduser().resolve()
    if not resolved.is_file():
        raise BackupRefused("db backup: no sqlite store at %r" % source_raw)
    src = None
    try:
        src = sqlite3.connect(str(resolved))
        src.execute("PRAGMA busy_timeout = %d" % BUSY_TIMEOUT_MS)
        found = src.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' "
                            "AND name = 'lnpl_rows'").fetchone()
    except sqlite3.DatabaseError as exc:
        if src is not None:
            src.close()
        raise BackupRefused("db backup: cannot read %r as a sqlite database: %s"
                            % (source_raw, exc)) from exc
    if found is None:
        src.close()
        raise BackupRefused("db backup: %r has no lnpl_rows table, so it is not "
                            "an lnpl store" % source_raw)
    return src


def _create_out(out_raw):
    """Create `--out` as a new empty file, refusing anything already there.
    No `.resolve()`: a symlink at `--out` is refused rather than followed."""
    out = Path(out_raw).expanduser()
    if os.path.lexists(str(out)):
        raise BackupRefused("db backup: --out already exists, refusing to "
                            "overwrite: %r" % out_raw)
    for suffix in _SIDECAR_SUFFIXES:
        if os.path.lexists(str(out) + suffix):
            raise BackupRefused("db backup: a sqlite sidecar file already exists "
                                "next to --out: %r" % (out_raw + suffix))
    try:
        fd = os.open(str(out), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise BackupRefused("db backup: --out already exists, refusing to "
                            "overwrite: %r" % out_raw) from exc
    except FileNotFoundError as exc:
        raise BackupRefused("db backup: --out parent directory does not "
                            "exist: %r" % out_raw) from exc
    except PermissionError as exc:
        raise BackupRefused("db backup: --out parent directory is not "
                            "writable: %r" % out_raw) from exc
    except OSError as exc:
        raise BackupRefused("db backup: cannot create --out %r: %s"
                            % (out_raw, exc.strerror)) from exc
    os.close(fd)
    return out


def _remove_partial(out):
    for path in [str(out)] + [str(out) + s for s in _SIDECAR_SUFFIXES]:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def backup_sqlite(source_raw, out_raw):
    """Copy the store at `source_raw` to the new file `out_raw` and return the
    copy's `lnpl_rows` count. Raises `BackupRefused` before any write, and
    `BackupFailed` mid-copy after removing the partial copy."""
    if not out_raw.strip():
        raise BackupRefused("db backup: --out needs a file path, got an empty one")
    src = _open_source(source_raw)
    try:
        out = _create_out(out_raw)
        try:
            dst = sqlite3.connect(str(out))
            try:
                _run_backup(src, dst)
                rows = dst.execute("SELECT count(*) FROM lnpl_rows").fetchone()[0]
                dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                dst.close()
        except sqlite3.Error as exc:
            _remove_partial(out)
            raise BackupFailed("db backup: backup failed: %s" % exc) from exc
        return rows
    finally:
        src.close()

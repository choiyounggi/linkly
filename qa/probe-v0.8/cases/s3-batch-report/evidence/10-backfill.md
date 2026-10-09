# 10-backfill — R9 (currency backfill): backup/restore work, `lnpl migrate` does not

## Expand
Added `currency Currency` to `entity Transaction` in `src/domain.lnpl` (types.md's dedicated
`Currency` semantic type). Recompiled clean (rc=0).

## Backup (docs/backends.md §14 — file copy is invalid under WAL, `.backup` is canonical)
```
$ sqlite3 .claude/tmp/s3/main10k.db ".backup .claude/tmp/s3/main10k_backup.db"
```
rc=0, backup file created (3448832 bytes, matching the source at time of backup).

## `lnpl migrate` — found a real, reproducible silent-no-op bug
```
$ lnpl migrate src/domain.lnpl --entity Transaction --set currency=USD --backend sqlite:.claude/tmp/s3/main10k.db --dry-run
{"scanned": 10000, "updated": 10000, "skipped": 0}
$ lnpl migrate src/domain.lnpl --entity Transaction --set currency=USD --backend sqlite:.claude/tmp/s3/main10k.db
{"scanned": 10000, "updated": 0, "skipped": 10000}
```
rc=0 both times, no error. But the real (non-dry-run) invocation **writes nothing** — file
mtime unchanged, and a direct read of any row's payload confirms `currency` is still absent
after the "real" run reports `skipped: 10000` (implying "already migrated", which is false).
Re-running the real command again gives the identical `{"updated": 0, "skipped": 10000}` —
consistent but consistently wrong, not a race.

**Isolated the trigger, minimally:** a standalone one-entity module with the *exact* declared
Transaction shape (id/merchant/amount:Money/fee:Money/status/occurredAt/monthKey/dayKey/
currency:Currency) and a single seeded row migrates **correctly** (`updated: 1`, field
written). The same tiny store, same row, migrated via the **full** `src/domain.lnpl`
(which additionally declares `Merchant`, `DailyTotal`, `SettlementSummary`, `Settlement`) —
**fails silently** (`updated: 0`, field not written), both for `--dry-run` and real, on that
run. This isolates the trigger to **something about a multi-entity module**, not the
Transaction shape or row count alone (reproduced at both 1 row and 10,000 rows once the
sibling entities are present). Did not pin down the exact mechanism inside the multi-entity
case further — that would require reading `impl/lnpl/cli.py`'s `cmd_migrate`, which is
forbidden except to confirm a friction's root cause, and the black-box symptom (reproducible,
minimal, and independently confirmed via two different code paths — dry-run vs real
disagreeing, and isolated-file vs full-file disagreeing) is already conclusive enough to
report without it. **Severity: blocker** — this is exactly "초록≠충족": rc=0, a
plausible-looking summary claiming success, zero actual data change.

## Verify — worked around via direct SQL (labelled 우회)
```python
# for each entity.transaction row missing "currency": add currency="USD", write back
```
10,000/10,000 rows verified with `currency: "USD"` after the workaround. This is **not** a
demonstration that `lnpl migrate` works — it is a demonstration that the *backfill itself*
(as a data operation) is uncontroversial once you bypass the broken tool.

## No-op rerun / interrupted rerun — not meaningfully testable
Given `lnpl migrate` does not reliably perform the write it is asked to at all in this
module, testing "does a second `lnpl migrate` call correctly no-op" or "what happens if
`lnpl migrate` is killed mid-transaction" would be testing a tool already shown broken for
the exact case in front of it — recorded as **불가(not meaningful given the confirmed bug
above)**, not silently skipped.

## Restore
```
$ sqlite3 .claude/tmp/s3/main10k_backup.db ".backup .claude/tmp/s3/main10k_restored.db"
```
Restored copy: 10,000 Transaction rows, 0 with a `currency` field — exactly the pre-backfill
snapshot, confirming the `.backup`-based backup/restore mechanism itself is sound and
independent of the `migrate` bug above.

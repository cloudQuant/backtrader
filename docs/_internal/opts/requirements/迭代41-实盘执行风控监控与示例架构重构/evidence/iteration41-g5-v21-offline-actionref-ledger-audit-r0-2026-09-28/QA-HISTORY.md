# Independent QA history

Disposition for every entry: `LOCAL_OFFLINE_ONLY / NON-AUTHORIZING`.

## Initial rejected review

The first independent review rejected the candidate as incomplete:

- The projector expected only three `ctp_dispatch_commands` unique-index column signatures and its fixture omitted the frozen V21 session/request, managed-action, and local-queue-receipt unique indexes.
- Trigger validation compared only names and tables. A same-name no-op allocation-delete trigger was accepted.
- The counter test allowed a high-water value ahead of the maximum visible allocation.

That result is preserved here as a rejected finding; it was not replaced by the later successful report.

## Corrected schema review

The next review confirmed all four V21 command unique-index SQL definitions and predicates against the frozen `store.py` DDL, and confirmed all four ActionRef trigger bodies. Independent probes rejected an altered partial-index predicate and a same-name no-op trigger. The counter-ahead check was consistent with the frozen V21 allocator: allocation starts at one, no counter-seeding migration was found, and allocation plus command writes share a transaction.

This review found a separate first-read issue: SQLite changed the source `-wal`/`-shm` files when the projector opened a cold WAL database read-only, causing a false `source_changed_during_read` rejection.

## Final independent recheck

After the projector copied the main database and WAL into private temporary storage before opening SQLite:

- Independent focused tests passed: 10.
- Ruff and `py_compile` passed.
- A first projection of a schema-21 database with main, WAL, and SHM sidecars succeeded. The before/after hashes for each original component were byte-identical.
- A rollback-journal sentinel failed closed with `database_rollback_journal_present`.
- The no-op trigger and altered partial-index probes continued to fail closed.

The frozen Store-created schema probe used local source code and temporary files only. No native module, provider, account, credentials, or network was accessed. These checks do not authenticate source provenance, establish G5/F14/G4 acceptance, enable CTP writes, or authorize cutover.

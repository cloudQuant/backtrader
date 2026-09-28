# G5 / V21 ActionRef unification design blocker — independent QA archive

**Disposition: `DESIGN_ONLY / BLOCKED_FOR_PATCH / G5 NOT_ACCEPTED / NO_WRITE / LIVE_NO_GO`.** This archive records an author source/AST review and independent static QA. It does not integrate either allocator and does not establish provider-side duplicate ActionRefs.

## What the frozen evidence shows

- The author package is frozen at manifest SHA-256 `47BFFEEF1C94E2B6478F389DFA0C4653EB7993FA8B0DB71C3CA1E36963E0650E`. Its checker is AST/source-hash only and reports `STATIC_API_AND_MIGRATION_SPLIT_CONFIRMED`.
- The independent report SHA-256 is `516767E65FEEFD897203ACC1E459CB63610DBBE3944715F67123AB5052DFE486`. It verified the author manifest, four package checksums, and twenty source preimages; it independently confirmed separate G5/V21 allocators, incompatible worker/Store contracts and schema/migration paths, plus the missing trusted native ActionRef floor.
- The earlier collision proof is local fake-only: one synthetic account and in-memory SQLite, direct allocator calls each return `native_action_ref=1`. It did not stage a complete V21 cancel or insert its command-to-ActionRef mapping row. It does not show that a provider received or accepted a duplicate.
- No patch was produced. A one-sided change would leave another allocator active; migration cannot safely renumber ambiguous historical references. Any later candidate needs one shared account-keyed allocator, coordinated migration/stale-writer fencing, and a separately trusted native watermark/cutover.

## Scope limits

The independent QA was static/source-only and did not import project code, SDK/native modules, access provider/network/private configuration, or run a real account action. This archive is a design blocker record, not implementation, integration, or G5 acceptance. Keep all writes and live routes closed.

## Contents and integrity

`author-package/` and `independent-qa/` preserve the source packages and raw static evidence byte-for-byte. `ARCHIVE-MANIFEST.json` binds each copied file by relative path, size, and SHA-256. `evidence.zip` contains those files, this README, and the archive manifest; its CRC/content check is recorded in `ARCHIVE-RECEIPT.json`.

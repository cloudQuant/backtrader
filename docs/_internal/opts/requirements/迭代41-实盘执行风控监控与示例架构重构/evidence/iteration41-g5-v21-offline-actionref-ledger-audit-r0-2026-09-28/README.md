# V21 offline ActionRef ledger audit r0

**Disposition: `LOCAL_OFFLINE_ONLY / NO_AUTHORITY / NO_CUTOVER / NO_WRITE / LIVE_NO_GO`.** This is an isolated, non-integrated candidate. It is not registered or used by Backtrader, `bt_api_execution`, the CTP Store, a runtime, or a dispatch route. It does not change G5, SimNow, production, or account authority.

The archive contains only the projector, its synthetic SQLite tests, a code/test patch, freeze metadata, and review evidence. The full 32-file SDK source snapshot is intentionally not copied here; its frozen source manifest is retained for byte-hash identity checks.

## Frozen source and candidate

- Frozen input: `D:\temp\iteration41_v21_ctp_account_handoff_freeze_r3_20260927`.
- Frozen `SOURCE-MANIFEST.json` SHA-256: `b3a614d62b2a4cf1b0dbdfefee463015157dee38bf4c9c5119c64ef2d71d6d24`.
- Frozen `src/bt_api_execution/store.py` SHA-256: `1f01eda8466873b90359c25aad2b61cb378d7a9feb477fa8ec77a97fb2478e6a`.
- All 32 frozen source payloads were checked byte-identical in the isolated candidate before its new files were added.
- Candidate implementation: [offline_actionref_ledger_audit.py](src/bt_api_execution/offline_actionref_ledger_audit.py).
- Synthetic database tests: [test_offline_actionref_ledger_audit.py](tests/test_offline_actionref_ledger_audit.py).
- Code/test patch: [PATCH.diff](PATCH.diff).
- Hash freeze and verification details: [FROZEN-MANIFEST.json](FROZEN-MANIFEST.json).

The projector copies the supplied main database and WAL into a private temporary directory before opening SQLite read-only. It verifies the original main/WAL/SHM bundle before and after the operation. A rollback-journal sidecar fails closed. Its hashes are byte-integrity digests only; they do not authenticate an account, database origin, or complete history.

## Verification

The final focused run passed **10 tests**. Ruff check, Ruff format check, and `py_compile` passed. Tests use synthetic SQLite databases and exercise schema/index/trigger shape, ActionRef joins and payload digests, counter mismatch, legacy/UNKNOWN rejection, and main/WAL/SHM byte stability. The replay emitted one environment warning because its installed pytest does not recognize the existing `asyncio_default_fixture_loop_scope` configuration option; the test result was still 10 passed. Raw focused log, JUnit, lint/format/compile logs, and exit codes are retained alongside this README.

Independent QA confirmed the initial schema gaps were corrected and verified that a first read of a WAL-backed database no longer changes source bytes. It also confirmed that a same-name no-op trigger and a changed partial-index predicate fail closed. The original rejected QA findings and cold-WAL false rejection are preserved in [QA-HISTORY.md](QA-HISTORY.md); the final receipt is [independent-qa-receipt.md](independent-qa-receipt.md).

## Acceptance boundary

The auditor requires schema version 21, relevant column/type and key shapes, exact V21 command unique-index definitions and predicates, exact ActionRef trigger bodies, one-to-one CANCEL allocation/command joins, exact order-reservation targets, canonical payload digests, and a counter equal to the highest visible allocation. It rejects `UNKNOWN` and legacy command rows rather than resolving them.

This is only a local offline consistency projection. It does not merge the separate G5 and V21 ledgers, authenticate a native `MaxOrderActionRef` floor, coordinate a quiesced cutover, establish an account-wide writer fence, prove absence of tampering, send or cancel orders, or grant authority. The current G5/V21 acceptance blockers and all CTP route closures remain unchanged: **`NO_AUTHORITY / NO_CUTOVER / NO_WRITE / LIVE_NO_GO`**.

The outstanding path still needs one account-keyed allocator across the schema-5 G5 and schema-21 Store records, a reviewed migration and stale-writer fence, trusted native ActionRef floor/cutover evidence, and a lifecycle/worker contract that binds Store commands, SDK outbox, native requests, and callbacks to one durable command identity. The current worker contract does not accept the requested `action_identity=` binding, and the native-floor/query path has no trusted producer. `UNKNOWN` has no trusted resolution path. Separate G6-P external account-wide writer fencing/common-snapshot requirements, G4 exact pinned artifact provenance, and bounded G1 lifecycle supervision also remain open. SimNow G7-S has not run; production admission remains unavailable.

## Hash index

[hash-index.json](hash-index.json) records SHA-256 and byte length for each archived artifact except itself. Relative links in the archive were verified against files under this directory. No `AGENTS.md`, acceptance matrix, evidence index, shared source, or external SDK source was changed.

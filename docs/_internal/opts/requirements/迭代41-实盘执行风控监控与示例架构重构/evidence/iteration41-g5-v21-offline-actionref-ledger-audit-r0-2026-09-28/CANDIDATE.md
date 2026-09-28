# V21 offline ActionRef ledger projector r0

**Disposition: `LOCAL_OFFLINE_ONLY / NO_AUTHORITY / NO_CUTOVER / NO_WRITE / LIVE_NO_GO`.** This isolated candidate reads an offline copy of a `bt_api_execution` schema-21 SQLite database and returns a deterministic normalized projection. It does not import or call an SDK, native provider, account, network, credentials, or runtime route.

## Frozen input

The candidate was copied from `D:\temp\iteration41_v21_ctp_account_handoff_freeze_r3_20260927`. All 32 entries in the frozen `SOURCE-MANIFEST.json` matched byte-for-byte in the candidate copy before changes. The source manifest SHA-256 is `b3a614d62b2a4cf1b0dbdfefee463015157dee38bf4c9c5119c64ef2d71d6d24`; frozen `src/bt_api_execution/store.py` SHA-256 is `1f01eda8466873b90359c25aad2b61cb378d7a9feb477fa8ec77a97fb2478e6a`.

## Behavior

`src/bt_api_execution/offline_actionref_ledger_audit.py::project_v21_actionref_ledger` accepts an explicit account key and an offline database path. It requires `execution_meta.schema_version == 21`, exact relevant columns and declared types, primary and unique keys, all four V21 command unique-index definitions and predicates, and exact SQL bodies for the four ActionRef counter/allocation triggers. It hashes the input main/WAL/SHM bundle, copies the main file and WAL into a private temporary directory, verifies the original bundle did not change during the copy, opens only the temporary copy with `mode=ro` and `query_only`, runs `quick_check`, and verifies the original bundle stayed byte-identical. A rollback-journal sidecar fails closed. SQLite may manage temporary-copy sidecars; it never opens the supplied database directly.

It projects CANCEL allocations by joining each allocation row to its V2 dispatch command and exact order reservation, and checks request/native payload digests and `OrderActionRef`.

The report carries `authority=False` and `cutover_enabled=False`; `source_bundle_sha256` and `projection_sha256` are integrity digests only. The function rejects legacy command rows, UNKNOWN or unrecognized states, missing/orphan allocation rows, mismatched ActionRefs or OrderRef targets, missing reservations, and counters that differ from the highest visible allocation. The frozen allocator starts at one and updates the counter and allocation/command rows in one transaction; no counter-seeding migration path was found. This is stricter than the Store's local `counter >= action_ref` consistency check and does not prove source authenticity or tamper history.

## Limits

This projects only the frozen V21 schema. It does not read the historical G5 reservation schema, which lacks command IDs and lifecycle state, and it never infers those facts. It does not authenticate the source copy, establish a common quiesced cutover boundary, obtain trusted native `MaxOrderActionRef`, fence other writers, migrate rows, or authorize dispatch. The existing G5/V21 acceptance blockers remain unchanged.

## Focused verification

- `python -m pytest tests/test_offline_actionref_ledger_audit.py -q`: 10 passed, including first-read WAL byte stability, changed index predicate, same-name no-op trigger, strict counter, join, and UNKNOWN failures.
- `ruff check src/bt_api_execution/offline_actionref_ledger_audit.py tests/test_offline_actionref_ledger_audit.py`: passed.
- `ruff format --check src/bt_api_execution/offline_actionref_ledger_audit.py tests/test_offline_actionref_ledger_audit.py`: passed.
- `python -m py_compile src/bt_api_execution/offline_actionref_ledger_audit.py tests/test_offline_actionref_ledger_audit.py`: passed.

The tests use only synthetic SQLite data. Independent QA also checked the frozen schema/index/trigger DDL and first-read WAL behavior with local temporary files, without native/provider/account/network/credential access. Its initial rejected findings and later correction history are preserved in [QA-HISTORY.md](QA-HISTORY.md). These checks do not establish CTP authority or cutover readiness.

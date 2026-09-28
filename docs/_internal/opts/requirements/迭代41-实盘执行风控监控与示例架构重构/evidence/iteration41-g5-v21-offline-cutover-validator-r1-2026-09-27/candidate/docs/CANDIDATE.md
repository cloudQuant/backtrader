# Offline ActionRef cutover consistency candidate

**Disposition: `LOCAL_TYPED_CONTRACT_ONLY / NO_WRITE / NO_AUTHORITY / NOT A MIGRATION TOOL`.**

This isolated candidate compares two explicit, caller-produced, normalized in-memory snapshots. It never opens a database or file, writes rows, allocates or renumbers ActionRefs, or returns an authorization. The implementation is `src/offline_cutover_validator.py`; it has no SDK, provider, network, or runtime imports.

## Source relationship checked

- Current main G5 verifier: `backtrader_runtime/ctp_managed_action_authority.py`, SHA-256 `7caed2a83447173ff93755c5561713c2e2f8f410d21ae78e4a07cccd3f681c66`. It verifies the typed staged command and ActionRef payload/correlation consistency. It is not an owner of the historical tables below and does not allocate ActionRefs.
- Historical G5 table design is evidenced only in the old separate SDK candidate `implementation/sdk/src/bt_api_execution/ctp_identity_authority.py`, SHA-256 `8e7abdd2819f66b6ec3d5ff1d5a049fcbb91ae8e71327665ee925098d35f647d`. Its `ctp_action_ref_watermarks` columns are `(account_key, trading_day, legacy_ledger_max_action_ref, legacy_ledger_sha256, updated_at_ns)`. Its `ctp_action_identity_reservations` columns are `(account_key, trading_day, scope_key, managed_action_id, managed_intent_id, runtime_order_id, order_ref, native_action_ref, created_at_ns)`. This identifies a candidate schema, not a deployed or authoritative old G5 schema.
- Frozen V21 r3 Store: `src/bt_api_execution/store.py`, SHA-256 `1f01eda8466873b90359c25aad2b61cb378d7a9feb477fa8ec77a97fb2478e6a`. Its `ctp_native_action_ref_allocations` stores `(account_key, native_action_ref, scope_key, command_id, managed_action_id, allocated_at_ns)`. A normalized V21 snapshot must explicitly join the command/correlation row to provide trading day, reservation intent, runtime order ID, OrderRef, and command state. The allocation row by itself is not enough to compare the old composite identity.

The old G5 action reservation table has no command ID or state column; command state must come from a separately validated command export. Exact deployed joins, legacy schemas, and snapshots have not been established. The typed projection here is therefore a design contract and synthetic fixture shape, not an implementation of a real database export.

## Comparison contract

`CutoverBundle` pairs an old G5 snapshot and a V21 allocation-plus-command snapshot for one account. Each snapshot carries source name, account key, canonical payload digest, row count, completeness/readability flags, source high-water, and rows. Rows are compared field by field on account, trading day, scope, managed action ID, managed intent ID, runtime order ID, OrderRef, and native ActionRef. Source-local command IDs and allocation timestamps are not treated as shared identity fields. State must be known in both projections; any `UNKNOWN`, missing, or unsupported state rejects.

Both snapshots must be declared complete and readable; row count and digest must match their supplied content; source high-water must cover its rows; a positive high-water with no rows rejects; V21 high-water must not be below the old source high-water. Missing rows, duplicates, same-ref/different-action cases, moved action IDs, or any compared-field difference reject. Exact duplicate rows are rejected too; nothing is coalesced or deleted. A matching result only means these supplied projections are internally consistent.


Both snapshots must carry the same explicit `snapshot_boundary_id`; records captured at different boundaries are rejected. For each matched action, source command state must also be exactly equal. Only `READY`, `CLAIMED`, and `COMPLETED` are recognized; `UNKNOWN`, absent, unsupported, or mismatched state rejects. This is intentionally strict and can make a real cutover impossible until the exporter proves a shared quiesced snapshot boundary.

The API accepts exact `CutoverBundle`, `SnapshotManifest`, and `ActionRefEvidence` instances, an exact tuple for rows, and exact built-in primitive field types. It rejects arbitrary mappings, subclasses, and objects with custom comparison/serialization behavior. It validates these shapes before computing digests or comparing values; digest construction copies only primitive values and never calls a supplied row's `to_payload`. Exact Python types are an input-shape guard, not source authentication.
The SHA-256 is an integrity checksum over normalized payload, not source authentication. Caller-supplied `complete=True`, source names, checksums, and high-water marks are not trusted evidence. This code does not establish that an export contains every native action, authenticate an operator/provider snapshot, resolve historical UNKNOWN outcomes, or prove no other writer exists. It does not source a native `MaxOrderActionRef` floor.

## Validation

Synthetic tests: `python -m pytest -q tests/test_offline_cutover_validator.py` with `PYTHONPATH=src`; tests cover exact projection, every shared identity field mismatch, missing mappings, duplicates, UNKNOWN/unreadable/incomplete snapshots, tampered digest/count, and low high-water. Tests do not connect to an account or provider.

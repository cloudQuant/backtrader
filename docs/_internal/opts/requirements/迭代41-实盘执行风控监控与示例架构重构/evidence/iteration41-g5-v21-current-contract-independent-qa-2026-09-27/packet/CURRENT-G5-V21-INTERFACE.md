# Current G5/V21 ActionRef interface review — r0

**Disposition:** `SOURCE_IDENTITY_AUDIT / LOCAL_FAKE_ONLY / NO AUTHORITY / NO_WRITE / LIVE_NO_GO`.

This packet is bound to the current main-tree G5 sources and the exact V21 r3 Store/worker snapshot. It records the active typed call path and tests it locally; it does not integrate a runtime, alter G5 source, or grant write authority.

## Current source classification

The main-tree `backtrader_runtime/ctp_managed_action_authority.py` at SHA-256 `7caed2a83447173ff93755c5561713c2e2f8f410d21ae78e4a07cccd3f681c66` is a verifier for Store-staged commands. It does not define `CtpUnifiedOrderActionAuthority`, `reserve_cancel_action_identity`, `ctp_action_ref_watermarks`, or `ctp_action_identity_reservations`. The current account runtime candidate constructs `CtpManagedSingleWorkerCandidate`; the I9 session candidate sends a typed `CtpManagedPreparedDispatch` through `stage_prepared_dispatch`. The current candidate's default inventory does not register `ctp_managed_account_runtime_candidate`.

The current G5 adapter lazily accepts only installed `bt_api_execution` metadata version `0.2.0` and exact Store/command types. For CANCEL, `_action_digest` requires a positive `correlation.native_action_ref`, excludes `OrderActionRef` from the logical request, and checks the native request equals that logical request plus the correlated field. It reads and rechecks the persisted command at claim/final-check time; it does not create an ActionRef.

In V21 r3, `CtpManagedSingleWorkerCandidate.stage_prepared_dispatch` passes logical request fields and the typed managed action ID to `SqliteExecutionStore.stage_ctp_dispatch_command`. The Store rejects caller-provided native ActionRef fields, allocates the account counter, adds `OrderActionRef` only to the native payload, and persists the command and allocation mapping in its transaction. At claim, V21 calls `_require_ctp_native_action_ref_allocation` inside the Store transaction before it returns a claimed command to the worker. The worker only invokes its sender after that claim succeeds.

## Mapping-failure boundary

The fake cross-package test stages with a synthetic floor, reads the committed V21 mapping, and feeds the exact typed command to a byte-identical copy of the current G5 action digest. It verifies the reference and mapping survive a Store reopen.

The negative test removes the allocation row only after dropping the normal immutable-delete trigger to simulate damaged offline database state. The G5 digest still accepts the internally consistent command/payload: that digest checks value consistency, not the independent allocation table. The V21 Store claim gate then raises `DurableStoreError` for the missing mapping, leaves the command READY, and the fake sender is called zero times. This safety property belongs to the V21 claim transaction, not to the G5 digest alone.

The fake threaded staging case gives two distinct CANCELs references 38 and 39 above a synthetic floor of 37. A separate reopen case reads the same durable reference and mapping. These tests use one local Store and SQLite database; they do not prove multi-process, multi-host, or external account fencing.

## Historical dual-ledger evidence scope

The archived dual-allocation proof used an older, separate SDK-side G5 candidate at `D:\temp\iteration41-g5-order-authority-20260927-candidate\implementation\sdk\src\bt_api_execution\ctp_identity_authority.py`, SHA-256 `8e7abdd2819f66b6ec3d5ff1d5a049fcbb91ae8e71327665ee925098d35f647d`. Its archived repro and README are hash-bound in the manifest. That fake-only repro showed two old local ledgers could each issue 1 for the same synthetic account. Its README explicitly says it did not stage a complete V21 cancel or create a V21 `ctp_native_action_ref_allocations` row; it is a structural historical collision, not a provider duplicate.

The old G5 allocator source is not the current main G5 verifier module. Do not apply the historical G5 removal/migration diff to current main sources. Historical rows, packages outside this checkout, and deployed databases remain unknown until inventoried under an explicit offline cutover.

## Validation

- Fresh V21 r3 copy accepted the aggregate patch with `git -c core.autocrlf=false apply --check` and patch apply; all ten patched/new payload hashes matched the candidate.
- Candidate V21 suite: **275 passed, 2 skipped**.
- Cross-package fake contract packet: **4 passed** on both candidate and fresh patch replay.
- Ruff checks on changed V21 code/tests passed; both new test files passed format check.

See `LIMITATIONS.md` and `PREIMAGE-TARGET-MANIFEST.json` for trust boundary, exact source hashes, and unresolved external dependencies.

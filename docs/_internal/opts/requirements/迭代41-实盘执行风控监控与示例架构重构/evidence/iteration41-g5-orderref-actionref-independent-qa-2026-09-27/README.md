# Iteration 41 G5 OrderRef / ActionRef candidate

Status: `LOCAL_OFFLINE_CONTRACTS / NO_WRITE / LIVE_NO_GO`.

This is an isolated candidate under `D:\temp`. It did not edit the Backtrader
working tree, default runtime registry, CLI, protected configuration, or CTP
credentials. It did not open a session or use a network/provider. It does not
authorize SimNow or production orders/cancels.

## Source audit

The frozen Backtrader source was captured from `ad2c142b9a8b42cede85886528c681abdfcb8096`.
The relevant Store is `backtrader/stores/btapistore.py` (there is no
`ctpstore.py` in this checkout). Its managed CTP `_sdk_order_request` path
validates scope and then rejects before reaching the parent SDK runtime
OrderRef allocator. The nonmanaged legacy branch still reads/reserves a parent
SDK runtime binding; that is not evidence of unified managed authority.
Managed cancel also rejects before worker/API dispatch.

The copied `bt_api_execution` source snapshot is from submodule HEAD
`2700cb5454ef4c3d1780eda28b6f33307a860998`, with untracked `README.md`,
`pyproject.toml`, `src/`, and `tests/`. Its SQLite store durably reserves
account-scoped 12-digit OrderRefs and stages submit/cancel command rows, but
its native MaxOrderRef / legacy watermark seed is caller supplied. The source
does not contain a durable ActionRef table/API or native ActionRef callback
correlator, and it does not contain the `ctp_single_worker_candidate` API
expected by the current Backtrader candidate bridge. It is not a clean,
reviewed SDK pin.

The G5 matrix finding and development plan require one reservation authority;
they keep Store managed submit/cancel rejected while there is no shared
reservation port. A local `QUEUED` result is only queue admission, never a
provider acknowledgement. An unknown queued outcome must not be replayed.

## Candidate interface

`implementation/sdk/src/bt_api_execution/ctp_identity_authority.py` adds
`CtpUnifiedOrderActionAuthority` around one exact `SqliteExecutionStore`:

- Submit OrderRef delegates to the SDK transaction/lease-based reservation
  and requires exact durable readback. CTP OrderRef is checked as exactly 12
  ASCII digits; no truncation or alternate allocator is used.
- `import_legacy_order_mappings` imports the complete supplied mapping batch
  and seed watermark in one transaction, rejecting duplicates, conflicts,
  rollback, and mappings above the supplied legacy watermark. Seed hashes and
  maximum values remain caller assertions; they are not native account proof.
- Cancel ActionRef is account-wide, monotonic, unique, durable, and bounded to
  positive signed 32-bit CTP integer range. First allocation requires an
  explicit legacy ActionRef seed. The ActionRef row binds account/day/scope,
  managed action and order intents, runtime order ID, and OrderRef.
- Cancel command staging forbids caller `OrderActionRef`, adds the durable
  value, and verifies the same database command payload/hash and exact target
  on readback.

`implementation/backtrader_bridge/ctp_order_action_bridge.py` is an unregistered
Store-facing fake/offline seam. It requires exact Store/authority identity,
the same Store object in the fake worker, matching scope and an active writer
lease. It persists a typed queue receipt before fake dispatch; it rejects
unknown/mismatched receipts and never equates queue acceptance with provider
acknowledgement.

`implementation/main_repo_patch/G5_ORDERREF_ACTIONREF_AUTHORITY.patch` is the
proposed Backtrader bridge change against the frozen
`ctp_i9_parent_request_builder.py`. It reserves ActionRef in the injected
same-store authority before staging, passes the typed reservation to the
worker, requires exact worker echo and then reads back both identities. It
does not change `_sdk_order_request`, `_enqueue`, the default registry, or CLI.
The patched bridge requires a future worker implementation of
`stage_prepared_dispatch(..., action_identity=...)`. The current worker does
not expose that contract, so applying only this patch must fail closed before
dispatch.

The source files under `inputs/` and `frozen-input-manifest.json` preserve the
read-only audit inputs and their SHA-256 digests. `evidence/final-output-manifest.json`
records hashes for the candidate source, patch, logs, and other evidence; its
own hash is intentionally excluded.

## Offline verification

On Python 3.11, from PowerShell:

```powershell
$candidate = 'D:\temp\iteration41-g5-order-authority-20260927-candidate'
$env:PYTHONPATH = "$candidate\implementation\sdk\src;$candidate\implementation"
pytest -q "$candidate\implementation\tests\test_g5_unified_order_action_authority.py" `
  "$candidate\implementation\tests\test_g5_store_order_action_bridge.py"
ruff check "$candidate\implementation\sdk\src\bt_api_execution\ctp_identity_authority.py" `
  "$candidate\implementation\backtrader_bridge\ctp_order_action_bridge.py" `
  "$candidate\implementation\main_repo_patch\backtrader\stores\ctp_i9_parent_request_builder.py" `
  "$candidate\implementation\tests\test_g5_unified_order_action_authority.py" `
  "$candidate\implementation\tests\test_g5_store_order_action_bridge.py"
```

Evidence captured in `evidence/`:

- Candidate tests: **14 passed**. They cover restart persistence; concurrent
  OrderRef and ActionRef allocation; idempotent/conflicting legacy mappings;
  MaxOrderRef floor/overflow; exact 12-digit boundaries; ActionRef bounds and
  independence from RequestID; exact cancel target/action identity; typed
  queue receipt echo; no dispatch if receipt persistence fails; UNKNOWN
  no-replay behavior; same-store bridge binding; and conflicting database
  rejection.
- Frozen existing execution SDK tests: **27 passed**.
- Focused Backtrader bridge/session tests: **54 passed, 47 skipped**, one
  existing `asyncio_default_fixture_loop_scope` configuration warning. The
  normal plugin run also failed collection with the installed
  `pytest-asyncio` `Package.obj` compatibility error; that complete log is
  preserved. Retrying with `-p no:asyncio` passed the synchronous focus.
- Candidate Ruff and `py_compile`: passed.
- An initial candidate-test rerun used the wrong PYTHONPATH package root and
  failed collection; its log is preserved. The corrected final run passed.
- The first two candidate test failures and first Ruff finding are also
  preserved as historical correction evidence.

## Remaining acceptance prerequisites

This candidate does not close G5 for deployment. Before any managed CTP route
can be considered, the SDK producer must implement and cleanly pin the unified
OrderRef/ActionRef schema and worker API; a trusted native MaxOrderRef source,
legacy mapping import and ActionRef watermark/callback correlator must be
accepted; same-account single-writer fencing and process-crash/UNKNOWN
reconciliation need independent evidence; and the native CTP lifecycle, real
account and admission gates remain separately unaccepted. Until those are
reviewed in the canonical runtime, the managed Store hard rejects remain in
place and the status stays `NO_WRITE / LIVE_NO_GO`.

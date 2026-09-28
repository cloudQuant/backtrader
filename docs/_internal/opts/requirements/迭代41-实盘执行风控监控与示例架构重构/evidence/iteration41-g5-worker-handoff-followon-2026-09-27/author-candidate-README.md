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
does not contain a native ActionRef callback correlator, nor the
`ctp_single_worker_candidate` module expected by the Backtrader bridge. The
follow-on worker below is an isolated fake-only addition against this frozen
store API. It is not a clean, reviewed SDK pin.

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

`implementation/sdk/src/bt_api_execution/ctp_single_worker_candidate.py` adds
the missing fake worker call shape:

```python
stage_prepared_dispatch(
    prepared,
    *,
    cancel_target_projection=None,
    action_identity=None,
)
```

This retains the existing cancel-target keyword and adds the exact typed
`CtpActionIdentityReservation`. Submit still uses `stage_prepared_dispatch(prepared)`.
Cancel staging reads the identity back from the same authority, checks its
account/day/scope/action/order/OrderRef fields, stages the command, verifies
the native `OrderActionRef` payload and hash, and records a same-database
handoff row. It also retains `cancel_target_projection`, checks the projection
digest and exact account/order/session/CTP target fields, validates query
state, then requires equal readback from the same Store before staging. The
frozen SDK input does not contain the target-projection producer, persisted
projection table, or readback API; follow-on tests install a same-Store fake
readback port. That fake is a contract test only and does not equal the real
target ledger, native query verifier, or a clean SDK pin. Submit remains the
one-argument `stage_prepared_dispatch(prepared)` call and rejects cancel-only
values. A local queue receipt is persisted before the command claim. The
worker claims once before calling the injected SDK fake; an uncertain sender
result or a claim recovered after process loss becomes `UNKNOWN`, which blocks
replay.

`implementation/main_repo_patch/G5_ORDERREF_ACTIONREF_WORKER_HANDOFF.patch`
updates the Backtrader worker Protocol and documents the builder call. It
preserves the existing `cancel_target_projection=target_handle` argument and
the one-argument submit call. The ordinary Store path, default registry and
CLI remain unchanged. The direct worker-to-SDK-fake contract is tested. The
complete parent builder is not executable from these frozen inputs: the
candidate package metadata and other v2 store/projection contracts are not a
clean, accepted SDK pin. The patch therefore closes the isolated Python
keyword/signature gap; it does not establish production integration.

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
  "$candidate\implementation\tests\test_g5_store_order_action_bridge.py" `
  "$candidate\implementation\tests\test_g5_single_worker_action_handoff.py"
ruff check "$candidate\implementation\sdk\src\bt_api_execution\ctp_single_worker_candidate.py" `
  "$candidate\implementation\tests\test_g5_single_worker_action_handoff.py"
pytest -q "$candidate\inputs\sdk\tests"
```

Evidence captured in `evidence/`:

- Follow-on candidate tests: **21 passed**. The seven worker cases cover
  typed Store→worker→SDK fake handoff, mandatory ActionRef with idempotent
  retry after a pre-stage failure, same-Store projection readback and exact
  target-field rejection, one-argument submit compatibility, queue receipt
  write failure before sender entry, uncertainty after a possibly delivered
  send, and process loss after durable claim. Both restart cases assert no
  second sender call.
- Original identity/bridge tests: **14 passed**. They cover restart
  persistence; concurrent
  OrderRef and ActionRef allocation; idempotent/conflicting legacy mappings;
  MaxOrderRef floor/overflow; exact 12-digit boundaries; ActionRef bounds and
  independence from RequestID; exact cancel target/action identity; typed
  queue receipt echo; no dispatch if receipt persistence fails; UNKNOWN
  no-replay behavior; same-store bridge binding; and conflicting database
  rejection.
- Frozen existing execution SDK directory: **57 passed**.
- Follow-on worker source, identity authority, and new tests: Ruff and
  `py_compile` passed. The
  inherited full Backtrader source files have existing Ruff diagnostics; the
  changed Protocol signature itself is syntax-checked and included in patch
  application verification.
- Archived independent QA is at
  `D:\temp\iteration41-g5-order-authority-independent-qa-20260927`. It
  verified the author archive and inputs, independently reproduced the old
  worker signature rejection (0 worker body calls), and reported the frozen
  Backtrader focus as 49 passed / 47 skipped with `-p no:asyncio`. Its normal
  plugin run failed collection on the installed `pytest-asyncio` compatibility
  error. That result predates this follow-on worker patch.
- An initial candidate-test rerun used the wrong PYTHONPATH package root and
  failed collection; its log is preserved. The corrected final run passed.
- The first two candidate test failures and first Ruff finding are also
  preserved as historical correction evidence.

## Remaining acceptance prerequisites

This follow-on closes only the isolated Python call-shape gap and exercises a
fake local handoff. It does not close G5 for deployment. The OrderRef and
ActionRef seed values remain caller assertions; native watermarks and callback
correlation are unproven. The candidate worker is not installed, pinned,
registered, or connected to a provider. Same-account single-writer fencing,
independent crash/UNKNOWN reconciliation, the native CTP lifecycle, real
account evidence and admission gates remain separate acceptance work. The
frozen SDK source lacks the target-projection producer, durable ledger and
readback API, so the fake readback test is a blocking integration gap. The
ordinary managed Store hard rejects remain in place and status stays
`NO_WRITE / LIVE_NO_GO`.

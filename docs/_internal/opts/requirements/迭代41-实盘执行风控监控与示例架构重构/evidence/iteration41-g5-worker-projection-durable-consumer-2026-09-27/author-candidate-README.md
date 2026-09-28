# Iteration 41 G5 typed durable target consumer follow-on

**Status: `TYPED_DURABLE_CONSUMER_ONLY / BLOCKED / G5 NOT ACCEPTED`.**

This isolated candidate is under `D:\temp`. It edits no main-repository
production/default-route files, protected config, credentials, or real account.
It opens no provider/session and contains no real SDK dispatch. The previous
worker handoff candidate remains the base at
`D:\temp\iteration41-g5-order-authority-20260927-candidate`; this follow-on
adds a typed durable projection consumer and connects that row to the worker
handoff. It does not supply the trusted native-query producer required to make
the consumer usable for G5.

## Audited projection and identity contracts

The referenced V21 SDK source is
`D:\temp\g5-v21-execution-wheel-build-20260927\source\src\bt_api_execution\store.py`
(SHA-256 `1f01eda8466873b90359c25aad2b61cb378d7a9feb477fa8ec77a97fb2478e6a`,
schema version 21). It contains `CtpVerifiedOrderTargetProjection`, durable
`ctp_order_target_projections` and one-use
`ctp_order_target_projection_consumptions` tables, same-Store row readback,
immutable-row triggers, and a rejecting default verifier. Its verifier is a
Protocol only; there is no native query implementation. Its worker's
`stage_prepared_dispatch` does not accept `action_identity`, and its separate
per-account ActionRef allocator begins at 1. The frozen author worker
handoff's `action_identity` cannot be passed to that V21 worker, and the two
ActionRef authorities must not be mixed. V21's Store schema is version 21;
this candidate is an isolated adaptation to the frozen author's schema 6,
not a V21 Store pin or a direct database-compatibility claim.

The worker's typed identity maps without loss to the projection's reservation
and native target identity fields: account, scope, trading day, intent, runtime
order ID, OrderRef, query FrontID/SessionID, and instrument/exchange/order
system/front/session target. `OrderActionRef` is a separate action identity;
the candidate's `CtpUnifiedOrderActionAuthority` is its only allocator. Its
legacy maximum is still caller-supplied and unverified. Store staging now
rejects a CANCEL unless that candidate authority has durably issued the exact
ActionRef for the same reserved order. The V21 allocator is not imported or
accepted here.

The projection-only evidence fields (account fingerprint, registration
digest, query filter/record/source digests, query completion and uniqueness,
provider state, total/traded/remaining quantities, verifier identity and
freshness) cannot be recovered from the worker's prepared request. They must
come from a trusted verifier over a native query result and current SDK-owned
readback. `session_generation_id` is a query/session label bound to the
prepared dispatch session in this candidate; it is not OS `process_generation`
and does not prove process lifecycle ownership.

## Candidate behavior

The SDK Store adds the V21-shaped typed projection contract and durable row
layout to its isolated schema version 6. `issue_ctp_order_target_projection`
accepts only an exact typed verifier result, rechecks the OrderRef reservation
inside the write transaction, persists canonical JSON plus a digest and query
identity, then reads it back through an ephemeral handle issued by that exact
Store object. The projection and consumption rows are immutable. Cancel
staging checks target and dispatch-session identity and atomically writes the
command plus one-use projection consumption. Claim rechecks the consumed row,
reservation, target, session binding and freshness. A reopened Store does not
revive a prior in-memory handle; a claimed crash/uncertain sender is `UNKNOWN`
and never replayed.

The worker retains this call shape:

```python
stage_prepared_dispatch(
    prepared,
    *,
    cancel_target_projection=<CtpOrderTargetProjectionHandle>,
    action_identity=<CtpActionIdentityReservation>,
)
```

The existing submit call remains
`stage_prepared_dispatch(prepared)`. After claim, the worker rechecks the
projection immediately before entering the synchronous sender. If that
short-lived row expires after claim, it persists `UNKNOWN` and does not call
the sender. Awaitable senders are rejected before claim because this candidate
has no guarded asynchronous SDK-entry callback; it will not treat a delayed
coroutine as a valid handoff. The only sender tests use an injected local fake.

`_RejectCtpOrderTargetProjectionVerifier` is the default. The repository has
no trusted producer for a native query result, query-completion/readback
port, exact account/registration binding, or externally verified freshness.
Tests inject a verifier over a test-only synthetic evidence object solely to
exercise persistence, readback, one-use, and worker failure paths. A caller
mapping cannot be converted into a projection. That fake issuer is not a
native source, not an SDK pin, and not G5 evidence.

## Verification

The candidate focus suite covers typed Store→worker→SDK-fake handoff, retained
one-argument submit, default rejection of caller mappings, durable projection
readback and hash tamper checks, immutable/one-use rows, unissued ActionRef
rejection, wrong target rejection, expiry after claim before sender entry,
awaitable sender rejection, queue receipt write failure, claimed crash, and
uncertain sender receipt across reopen. The full SDK frozen test folder run
against this candidate source is separately recorded; expected legacy failures
are not suppressed: 53 pass and four fail. Three still assert schema version 5
after this isolated schema-6 addition; one direct CANCEL fixture omits the
now-required typed projection and candidate ActionRef. The same 57-test suite
passes against the untouched frozen SDK source only as a baseline. Candidate
changed files pass Ruff `E4,E7,E9,F,I` and `py_compile`; a broader Ruff run
also reports pre-existing import formatting in untouched frozen
`cancellation.py` and `facade.py`. Frozen source integrity checks 27 non-cache
manifest entries; the manifest also listed 23 generated `__pycache__` entries,
which are excluded because Python mutates/removes bytecode during imports.
See the [V21 contract audit](evidence/v21-projection-contract-audit.md).

Reproduce the candidate-focused tests from PowerShell:

```powershell
$candidate = 'D:\temp\iteration41-g5-worker-projection-durable-20260927-candidate'
$env:PYTHONPATH = "$candidate\implementation\sdk\src;$candidate\implementation"
python -m pytest "$candidate\implementation\tests" -q --tb=short
python -m ruff check --config "$candidate\inputs\sdk\pyproject.toml" `
  --select E4,E7,E9,F,I `
  "$candidate\implementation\sdk\src\bt_api_execution\store.py" `
  "$candidate\implementation\sdk\src\bt_api_execution\ctp_identity_authority.py" `
  "$candidate\implementation\sdk\src\bt_api_execution\ctp_single_worker_candidate.py" `
  "$candidate\implementation\sdk\src\bt_api_execution\__init__.py" `
  "$candidate\implementation\backtrader_bridge\ctp_order_action_bridge.py" `
  "$candidate\implementation\tests\test_g5_single_worker_action_handoff.py" `
  "$candidate\implementation\tests\test_g5_unified_order_action_authority.py" `
  "$candidate\implementation\tests\test_g5_store_order_action_bridge.py"
python -m py_compile `
  "$candidate\implementation\sdk\src\bt_api_execution\store.py" `
  "$candidate\implementation\sdk\src\bt_api_execution\ctp_identity_authority.py" `
  "$candidate\implementation\sdk\src\bt_api_execution\ctp_single_worker_candidate.py" `
  "$candidate\implementation\sdk\src\bt_api_execution\__init__.py" `
  "$candidate\implementation\backtrader_bridge\ctp_order_action_bridge.py" `
  "$candidate\implementation\tests\test_g5_single_worker_action_handoff.py" `
  "$candidate\implementation\tests\test_g5_unified_order_action_authority.py" `
  "$candidate\implementation\tests\test_g5_store_order_action_bridge.py"
```

For the frozen SDK comparison runs, set
`$env:PYTHONDONTWRITEBYTECODE='1'` and pass `-p no:cacheprovider` so test
execution does not touch archived interpreter caches. With the candidate
source first on `PYTHONPATH`, `inputs\sdk\tests` reports 53 passed / 4 failed
as listed above. With `inputs\sdk\src` first, the same 57 tests pass against
the untouched source baseline.

Patch delta from the prior worker handoff candidate:
`implementation/sdk_patch/G5_TYPED_TARGET_PROJECTION_DURABLE_CONSUMER.patch`.
Application/hash evidence is `evidence/g5-projection-patch-apply-check.log`;
test and static-check logs are in `evidence/`. The output manifest records
hashes of the changed source, patch and logs; its own hash is excluded.

## Blocking conditions and limits

- **G5 is not accepted.** The trusted SDK target-projection producer and
  current-query readback port are missing, so the default verifier rejects.
- The candidate OrderRef and ActionRef seed values are caller assertions; no
  native `MaxOrderRef`/`MaxOrderActionRef` snapshot or account cutover proof is
  integrated.
- The ActionRef allocator here is distinct from V21's allocator and cannot be
  combined with it. Candidate Store schema 6 is not V21 schema 21.
- The query session label is not bound to OS process-generation/lifecycle
  ownership, and local monotonic expiry is not a trusted native query clock.
- No real SDK, session, account, provider, runner, default route or live write
  was exercised or authorized. No real order or cancel was accepted.

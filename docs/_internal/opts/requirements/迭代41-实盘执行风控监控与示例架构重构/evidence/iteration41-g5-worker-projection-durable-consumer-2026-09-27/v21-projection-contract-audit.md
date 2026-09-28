# V21 projection / worker contract audit

**Disposition:** `TYPED_DURABLE_CONSUMER_ONLY / BLOCKED / G5 NOT ACCEPTED`.
This is a source-level compatibility audit of an isolated candidate. It is not
a V21 Store pin, native query verification, SDK acceptance, or trading approval.

## Audited V21 source

- Store source: `D:\temp\g5-v21-execution-wheel-build-20260927\source\src\bt_api_execution\store.py`
- SHA-256: `1f01eda8466873b90359c25aad2b61cb378d7a9feb477fa8ec77a97fb2478e6a`
- Store schema version: 21 (`_SCHEMA_VERSION`)
- Worker source: `D:\temp\g5-v21-execution-wheel-build-20260927\source\src\bt_api_execution\ctp_single_worker_candidate.py`
- Worker source SHA-256: `5e378ee77ad6c5e640ad2eca0dacd154849e6fcfe0d04d73e9da6eb2554087b3`
- `CtpVerifiedOrderTargetProjection` begins at Store line 664. Its fields bind
  account/scope/day, intent and reserved OrderRef, account/registration
  fingerprints, query source/filter/records digests, query completion and
  uniqueness, session/connection generations, exact native order identity,
  provider state and open quantities, verifier identity, and expiry.
- `CtpOrderTargetProjectionVerifier` is a Protocol at Store line 1540. Its
  method receives `native_query_evidence: Any` and must verify the native query
  result plus its current SDK-owned readback. The only source implementation
  found under V21 `src/bt_api_execution` is
  `_RejectCtpOrderTargetProjectionVerifier` at line 1912. There is no concrete
  native query producer or readback adapter in that source tree.
- V21 has durable `ctp_order_target_projections` and
  `ctp_order_target_projection_consumptions` tables, immutable projection
  triggers, and a default rejecting verifier. Its persistence is a reusable
  contract shape; it does not create native evidence.
- V21 worker `stage_prepared_dispatch` at line 420 accepts
  `cancel_target_projection` but has no `action_identity` keyword.
- V21 Store `_allocate_ctp_native_action_ref` at line 9242 owns an
  account-lifetime counter and initializes it to 1. It is a separate
  `OrderActionRef` allocator.

## Candidate adaptation and field compatibility

The isolated candidate adds Store schema version 6 to the frozen author SDK
source. It adapts the V21 projection fields and durable projection/one-use row
shape to that schema. It does not import V21 source or claim database
compatibility with schema 21.

The following worker/Store identity values map directly to V21 projection
identity values without conversion: account key, scope key, trading day,
managed intent ID, runtime order ID, OrderRef, query FrontID/SessionID,
instrument, exchange, OrderSysID, and target FrontID/SessionID. Candidate
`OrderActionRef` remains a separate action identity. Candidate Store staging
requires an exact ActionRef row previously issued by that same Store's
`CtpUnifiedOrderActionAuthority`; an arbitrary number is rejected.

The target's *evidence* fields cannot be reconstructed from a prepared cancel
request. They require a trusted verifier over an actual native query result:
the account fingerprint, registration digest, query filters and records,
source-evidence digest, completion/terminal/timeout/error/late-callback facts,
unique match count, current provider state and quantities, verifier identity,
and freshness. The candidate accepts the exact typed verifier return and
persists its canonical payload and digest. A Store-instance-scoped handle then
reads the durable row back and checks its digest, schema, reservation, scope,
target, and expiry. A matching durable hash establishes stored-byte
consistency only; it does not authenticate the evidence's native origin.

Tests use a test-only synthetic evidence type and test-only verifier to exercise
that durable contract. They do not monkeypatch the projection readback method.
The default verifier rejects. Caller mappings cannot be issued as projections.
No production verifier or producer is registered or present, so no
caller-supplied or synthetic projection makes a real cancel acceptable.

## ActionRef and generation boundaries

The candidate's only accepted ActionRef issuer is
`CtpUnifiedOrderActionAuthority`, backed by its own same-Store reservation
table. The legacy maximum/seed is caller supplied and remains unverified. V21's
independent per-account allocator also starts at 1. These allocators are not
merged, seeded from each other, or interchangeable. A future integration must
choose one authority and prove its account-lifetime cutover before dispatch;
this candidate has not done so.

`session_generation_id` identifies/binds a query and dispatch session label.
It is not an OS process-generation ID and does not prove which process owns the
native connection. The candidate uses local monotonic time for short-lived
projection checks and rechecks expiry after claim immediately before the
synchronous sender. It does not provide an externally trusted native query
clock. The worker rejects coroutine functions before claim and rejects any
awaitable sender result; a delayed async send-entry fence is not implemented.

## Verification and stopping point

- Candidate focus: 26 passed.
- Frozen SDK tests against candidate source: 53 passed, 4 failed (three old
  schema-v5 assertions, one legacy CANCEL fixture without the new typed
  projection and ActionRef requirement).
- Same frozen SDK tests against untouched frozen source: 57 passed (baseline).
- Changed candidate files: Ruff `E4,E7,E9,F,I` passed; `py_compile` passed.
- Broader Ruff scan also found existing import formatting in untouched frozen
  `cancellation.py` and `facade.py`.
- Frozen input manifest: 27 non-cache entries match; 23 listed generated
  bytecode entries are ignored by the integrity check because test/import
  execution mutates or removes interpreter caches.
- Store reopen preserves durable projection and one-use rows, but an earlier
  process's in-memory handle is not revived. Claimed crash/uncertain outcomes
  stay UNKNOWN and are not replayed. The tests are fake-only.

The candidate stops at the durable typed consumer. The V21-referenced source
does not provide a trusted native target-query producer or current SDK-owned
readback implementation. Until those exist and are pinned/reviewed, the
default Reject verifier remains in effect and G5 stays not accepted.

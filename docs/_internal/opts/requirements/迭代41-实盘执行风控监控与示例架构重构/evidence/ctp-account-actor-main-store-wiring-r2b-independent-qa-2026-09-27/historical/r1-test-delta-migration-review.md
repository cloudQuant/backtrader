# BtApiStore Actor r1: legacy CTP test-delta audit

## Verdict

Read-only audit of the frozen `AUTHOR_CANDIDATE / NO_WRITE` r1. The 21 failures are an intentional CTP-local-SDK boundary delta, not ordinary non-CTP compatibility failures. All 21 arise before their test bodies reach adapter dispatch, SDK queueing, request allocation, or receipt classification: each path constructs `provider="btapi"` with nested `exchange_kwargs: {"CTP": {}}`, and r1 classifies that as CTP. With no external actor port, Store construction raises `external account actor unavailable`.

Exact same three-file legacy regression focus passes 30/30 on the current main baseline and 9/30 on the frozen r1 candidate. The failure log contains 21 occurrences of the constructor gate error and 21 failing node IDs. The generic managed-execution/non-CTP focus passes on r1 (21/21 candidate boundary + generic adapter + live-dispatch tests). No ordinary non-CTP compatibility defect was identified in the 21-failure set; this is a narrow audit, not a whole-suite compatibility claim.

## Hash-bound source identity

- Frozen r1 manifest SHA-256: `ada5018781a7417206b88e3d934d59a67a77beab0c5e09e002a0e8f89a16ade4`.
- Exact base/current-main Store SHA-256: `dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826`.
- Frozen r1 Store SHA-256: `a25edc57d4a4ac225b1b152a2672ff2b108b3c497cef05cd46a8fb22c1e586b8`.
- Frozen r1 actor module SHA-256: `19f5935bc6aabcde178f60f62619757b01fa51b99ff5389120a8404e00e70372`; no corresponding module exists in current main.
- Baseline `test_managed_ctp_store_adapter.py` SHA-256: `2b5f929cac960ed6a7105eb2cc0b7401961fdb7c7b97761288d279b415b15e3f` (main and r1 identical).
- Baseline `test_managed_execution_store_adapter.py` SHA-256: `c9262dc03c3905a54b1397c10db12b1a5dc68508874e550590039d22a482a030` (main and r1 identical).
- Candidate 21-failure log SHA-256: `a56a716b3fda59cb71d00b8e9ba8c0239c2cdd80e9288682a118a1a7c85d9b8b`.
- Main exact-base rerun log SHA-256: `2990563f46564515e525768480213e650b33b67dbd9687f898304bf23b6499d1`.

## Why all 21 fail at the same boundary

The shared test helper at `tests/unit/stores/test_managed_ctp_store_adapter.py:472-492` constructs `BtApiStore(provider="btapi", api=<fake>, config={"exchange_kwargs": {"CTP": {}}, ...}, managed_execution_adapter=adapter)`. The CTP venue is nested in `exchange_kwargs`, so candidate `classify_store_route` returns `RouteKind.CTP`. The adapter-only compatibility carveout at `backtrader/stores/btapistore.py:3685-3705` requires `RouteKind.AMBIGUOUS` plus empty config and therefore does not admit these CTP tests. The constructor calls `require_account_actor_before_local_client` at `btapistore.py:3753`; the actor gate raises `external_account_actor_unavailable` when the port is absent at `ctp_account_actor_port.py:458`. The Store translates that to `BtApiStoreError` at 3754-3755. Candidate submit/cancel and dispatch guards later in the file are never reached.

The candidate log confirms 21/21 errors originate from that gate. `test_managed_ctp_rejects_generic_adapter_and_never_uses_legacy_write` is the sole extra assertion mismatch: it expected the later text `typed runtime adapter`; early CTP actor absence correctly wins.

## Per-node migration table

`FAIL_CLOSED_ASSERTION` means rewrite the current Store integration test to prove early constructor rejection and zero adapter/API/client/queue/allocator effects. `EXTERNAL_ACTOR_MIGRATION` means its business behavior needs a future authoritative actor API and cannot remain a local CTP SDK Store integration test. While that API is unavailable, any Store-level version must also prove the same early rejection. None is an ordinary non-CTP defect.

| Failing node | Disposition | Safe migration action |
|---|---|---|
| `test_managed_ctp_submission_projects_typed_identity_to_sdk_only` | `EXTERNAL_ACTOR_MIGRATION` | Replace Store→local CTP SDK queue projection with an external actor command contract; until that API exists, the Store integration variant must reject before adapter/client/queue. |
| `test_managed_ctp_rejects_generic_adapter_and_never_uses_legacy_write` | `FAIL_CLOSED_ASSERTION` | Assert CTP construction fails with external actor unavailable before adapter call/client resolution; retain counters for adapter and API at zero. |
| `test_managed_ctp_placeholder_is_a_local_rejection_before_queueing` | `FAIL_CLOSED_ASSERTION` | A local placeholder is not actor authority. Assert constructor rejection before submit/queue; preserve zero queue/API counters. |
| `test_fake_ctp_projection_adapter_submit_cancel_and_restart_are_queue_only` | `EXTERNAL_ACTOR_MIGRATION` | Move durability, recovery, and exact projection semantics to a service-owned actor/outbox contract; a fake local Store queue is not an external writer fence. |
| `test_fake_ctp_cancel_accepts_a_recovered_binding_without_framework_ref` | `EXTERNAL_ACTOR_MIGRATION` | Define service-authoritative cancel lookup/recovery before replacing the local fake durable reader; do not route directly to native cancel. |
| `test_fake_ctp_adapter_does_not_claim_at_most_once_without_durable_reservation` | `EXTERNAL_ACTOR_MIGRATION` | Prove durable idempotency/reservation and UNKNOWN retention at the account actor service; local memory/fake reader is insufficient. |
| `test_fake_ctp_projection_failures_freeze_and_surface_unknown_without_fallback[missing_projection]` | `EXTERNAL_ACTOR_MIGRATION` | Migrate as signed/current actor-receipt and authoritative UNKNOWN handling; no local SDK queue call. |
| `test_fake_ctp_projection_failures_freeze_and_surface_unknown_without_fallback[receipt_mismatch]` | `EXTERNAL_ACTOR_MIGRATION` | Migrate as signed/current actor-receipt and authoritative UNKNOWN handling; no local SDK queue call. |
| `test_fake_ctp_projection_failures_freeze_and_surface_unknown_without_fallback[reader_error]` | `EXTERNAL_ACTOR_MIGRATION` | Migrate reader/authoritative resolution semantics to the actor service; local fake reader failures cannot prove remote state. |
| `test_fake_ctp_cancel_projection_failures_freeze_and_surface_unknown[missing_projection]` | `EXTERNAL_ACTOR_MIGRATION` | Migrate cancel receipt and UNKNOWN-resolution semantics to the actor service; local SDK cancel queue remains closed. |
| `test_fake_ctp_cancel_projection_failures_freeze_and_surface_unknown[receipt_mismatch]` | `EXTERNAL_ACTOR_MIGRATION` | Migrate cancel receipt and UNKNOWN-resolution semantics to the actor service; local SDK cancel queue remains closed. |
| `test_managed_ctp_rejects_caller_owned_provider_identifiers_before_adapter` | `FAIL_CLOSED_ASSERTION` | Assert the absent actor blocks construction before adapter or provider-ID handling; keep a pure ID-validation contract separately if needed. |
| `test_managed_ctp_rejects_untyped_adapter_projection_without_direct_fallback` | `EXTERNAL_ACTOR_MIGRATION` | Replace local adapter projection with actor receipt verification; malformed/stale/unsigned receipt must not permit fallback. |
| `test_managed_ctp_real_queue_fails_before_second_orderref_allocator[queue]` | `FAIL_CLOSED_ASSERTION` | Assert front-door CTP denial occurs before SDK queue, allocator, or adapter callback; never exercise a local CTP queue to test a second allocator. |
| `test_managed_ctp_real_queue_fails_before_second_orderref_allocator[unknown_classification]` | `FAIL_CLOSED_ASSERTION` | Assert front-door CTP denial occurs before SDK queue, allocator, or adapter callback; never exercise a local CTP queue to test a second allocator. |
| `test_managed_ctp_order_request_refuses_a_second_orderref_allocator` | `FAIL_CLOSED_ASSERTION` | Assert CTP denial before local SDK request creation or any OrderRef allocation; service-owned identity needs a separate API contract. |
| `test_managed_ctp_cancel_projects_durable_cancel_id_without_native_ids` | `EXTERNAL_ACTOR_MIGRATION` | Requires authoritative service mapping for durable cancel identity and native order; no local SDK cancel path is acceptable. |
| `test_managed_ctp_cancel_rejects_missing_native_order_ref_before_queueing` | `FAIL_CLOSED_ASSERTION` | Assert no CTP Store/queue can be opened without actor authority; defer the native OrderRef recovery rule until the actor API defines it. |
| `test_managed_ctp_cancel_uses_the_typed_adapter_dispatch_callback` | `EXTERNAL_ACTOR_MIGRATION` | Replace the local typed-dispatch callback with an external actor cancel request and authoritative receipt; callback to local SDK stays unavailable. |
| `test_managed_ctp_orderref_from_sdk_ledger_is_not_reused_as_second_authority` | `FAIL_CLOSED_ASSERTION` | Assert CTP denial before SDK binding lookup/reservation; the old SDK ledger must not serve as an alternate account-wide authority. |
| `test_real_store_queue_receipts_classify_submit_and_recovered_cancel_as_unknown` | `EXTERNAL_ACTOR_MIGRATION` | Migrate UNKNOWN and recovery semantics to actor receipts/current service state; local Store queue receipt is not provider/actor observation. |

## Safe merge conditions and blocker

1. Do not restore the local CTP queue/SDK path to satisfy these old tests. For the eight `FAIL_CLOSED_ASSERTION` cases, assert rejection at construction, using API property traps and counters to prove no credential conversion, `_resolve_provider`, SDK/native import, adapter callback, queue, or OrderRef allocation ran.
2. For the thirteen `EXTERNAL_ACTOR_MIGRATION` cases, retain the business requirement as an explicit deferred migration table. Replace them only when the external actor API defines authenticated actor identity, signed/current per-action scope and expiry, durable idempotency/replay ownership, native-order/cancel resolution, and UNKNOWN/current-state recovery. A local fake projection reader or the Store's SDK queue receipt does not supply those facts.
3. Keep the known explicit non-CTP compatibility path covered independently; the existing generic managed-execution tests and r1's 21-test focused set pass. The 21 CTP-focused failures contain no non-CTP selector case.
4. **The r1 candidate is not safe to merge wholesale as production actor wiring under current `NO_WRITE / LIVE_NO_GO`.** Its explicit `account_actor_port` path checks an ABC/type, caller-selected context, caller-provided in-memory fake ledger, and an unkeyed receipt digest; it invokes the supplied port before local receipt comparison. There is no authenticated/codelisted service identity, signed receipt, trusted current epoch, durable account-wide fence, or same-session read/callback feed. Keep CTP construction closed unless/until that authority is code-owned and independently accepted. The adapter-only ambiguous route is separate and forbids local legacy dispatch, but does not fix actor authority.
5. This audit is read-only; it changes no source or test. It does not grant G1/G5/F14/live acceptance.

## Reproduction evidence

- `candidate_legacy_store_suite.log`: exact frozen r1 candidate run, **9 passed / 21 failed**.
- `main_exact_base_regression.log`: current main/base run, **30 passed**, one existing pytest configuration warning.
- `test_managed_ctp_store_adapter.py` and `test_managed_execution_store_adapter.py`: exact test source copies used for the migration table.
- `audit-inventory.json` and `audit-inventory.sha256`: SHA-256 inventory for this report package. The archive index records ZIP verification.

# Projection bridge migration report

## Replay and artifacts

The isolated replay reversed and reapplied `r2b-main-base-apply.patch` with
`core.autocrlf=false`. The intermediate Store hash was the recorded main-base
hash `dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826`;
after replay the Store, AccountActorPort module, and candidate wiring test
matched the r2b recorded hashes exactly: Store
`24f8199e199bbe84bbb113c3edbbee9e71d4736fdd8573297e24ead3298f2518`,
AccountActorPort `2e4b04d00c45ba9c6524c5ad0364273e6ecc1a1f653f595d21c3891be2644ee3`,
and candidate wiring test
`fc675d30a1cd3e303357406e81edc067af0b7559d2230ac6a2ee3732466cc2c6`. The
input patch SHA-256 is
`1a16aadb94edb99924553d6472bf72dcb02bd04c7f994276816d91991a729f37`.

The test-only migration patch is
[`projection-bridge-store-gate-migration.patch`](projection-bridge-store-gate-migration.patch),
SHA-256 `ced276afc091ecede150eeac956d3ebd87e0975db54443ffb2268a34437119b1`.
It changes only `tests/unit/stores/test_ctp_managed_projection_bridge.py`.
Input test SHA-256: `08095b558369f1c9674f10f0994e1344fc91a5a2bc6aed8a9aceec98872832bb`.
Migrated test SHA-256: `885d6b2e2163939057ad4f1bd50f5337885414141ecd14335560ef1b2a28e1cc`.

The exact replay baseline was **18 failed, 14 passed**. The migrated focus was
**32 passed, 0 failed**. Both JUnit files are retained:
[`before`](projection-bridge-before.junit.xml) and
[`after`](projection-bridge-after.junit.xml). The sole warning is the existing
Quandl deprecation warning. Runs used:
`python -B -m pytest tests/unit/stores/test_ctp_managed_projection_bridge.py -q --tb=short --junitxml=...`.
The patch passed a clean forward `git apply --check` and replay with
`core.autocrlf=false`; the result matched the migrated test hash above. The
first failed nodeid was renamed as shown in the table; the other 17 nodeids
remain unchanged and pass.

## Mapping of the 18 former failures

The first two tests now exercise the projection adapter directly. The
adapter's fake outbox is only a projection test fixture; it is not an
AccountActor or Store route authority.

| Former failing nodeid suffix (common prefix: `tests/unit/stores/test_ctp_managed_projection_bridge.py::`) | Preserved invariant and migrated result |
|---|---|
| `test_store_uses_outbox_projection_for_submit_and_cancel_without_legacy_fallback` | Renamed to `test_projection_adapter_uses_outbox_for_submit_and_cancel_without_legacy_fallback`; checks PENDING projection identity and receipt, submit replay idempotency, and cancel projection through the pure adapter seam. |
| `test_ambiguous_sdk_handoff_reads_back_unknown_and_does_not_retry` | Calls the adapter seam directly; an ambiguous queue handoff yields UNKNOWN, freezes once, and is not retried on replay. |
| `test_queue_receipt_commit_is_before_publication_and_worker_uses_typed_outbox_only` | A sealed NON_CTP Store private-queue harness checks receipt persistence before heap publication and typed projection dispatch without invoking the generic sender. |
| `test_receipt_writer_failure_leaves_managed_command_invisible_and_unsent` | The NON_CTP private-queue harness checks a receipt write failure leaves the command unpublished and dispatch/sender callbacks untouched. |
| `test_managed_worker_without_single_dispatch_port_never_calls_generic_sender` | The harness checks a worker command lacking its single dispatch port becomes UNKNOWN and does not call the generic sender. |
| `test_local_queue_rejection_is_durable_and_never_calls_outbox_dispatcher` | The harness checks local queue rejection is recorded, remains unpublished, and never calls the outbox dispatcher. |
| `test_managed_ctp_raw_enqueue_cancel_is_rejected_before_queue_or_sdk[False]` | Migrated to assert the CTP Store constructor gate rejects before client creation; the false recovery-state variant grants no local cancel route. |
| `test_managed_ctp_raw_enqueue_cancel_is_rejected_before_queue_or_sdk[True]` | Same fail-closed constructor contract for the true recovery-state variant. These two tests do not prove positive provider cancellation; that behavior still requires an external Actor and separate acceptance. |
| `test_managed_ctp_private_enqueue_requires_complete_matching_v2_binding[missing_all-submit]` | NON_CTP private-queue harness rejects submit with no binding before queue state or callbacks change. |
| `test_managed_ctp_private_enqueue_requires_complete_matching_v2_binding[missing_all-cancel]` | Same invariant for cancel with no binding. |
| `test_managed_ctp_private_enqueue_requires_complete_matching_v2_binding[binding_only-submit]` | NON_CTP private-queue harness rejects submit with a binding but no receipt writer or dispatcher. |
| `test_managed_ctp_private_enqueue_requires_complete_matching_v2_binding[binding_only-cancel]` | Same invariant for cancel with a binding but no receipt writer or dispatcher. |
| `test_managed_ctp_private_enqueue_requires_complete_matching_v2_binding[missing_writer-submit]` | NON_CTP private-queue harness rejects submit when the dispatcher exists but the receipt writer is absent. |
| `test_managed_ctp_private_enqueue_requires_complete_matching_v2_binding[missing_writer-cancel]` | Same invariant for cancel. |
| `test_managed_ctp_private_enqueue_requires_complete_matching_v2_binding[missing_dispatcher-submit]` | NON_CTP private-queue harness rejects submit when the receipt writer exists but the dispatcher is absent. |
| `test_managed_ctp_private_enqueue_requires_complete_matching_v2_binding[missing_dispatcher-cancel]` | Same invariant for cancel. |
| `test_managed_ctp_private_enqueue_requires_complete_matching_v2_binding[wrong_operation-submit]` | NON_CTP private-queue harness rejects a submit command whose binding is for cancel, before queue or sender effects. |
| `test_managed_ctp_private_enqueue_requires_complete_matching_v2_binding[wrong_operation-cancel]` | NON_CTP private-queue harness rejects a cancel command whose binding is for submit, before queue or sender effects. |

The queue harness uses a valid OKX NON_CTP Store and a bare sentinel solely to
select the private binding-validation branch. It calls private queue methods
only. It is a local test seam and does not cover a real CTP Store, actor-bound
dispatch, or an external provider.

## Remaining failures and limits

There are no remaining failures in this 32-case focused file; the post-run
JUnit has no failure elements. The two public CTP cancel cases now prove only
that the local CTP constructor is closed before client creation. Positive
provider cancel behavior remains unverified pending an external AccountActor
contract and independent acceptance. The NON_CTP queue harness preserves queue
ordering and port-validation invariants but cannot establish real CTP Store
integration. No fake actor was passed to BtApiStore or treated as trusted.

All work and test runs were in `D:\temp`; the shared checkout, private
configuration, SDK, native client, network, and orders were untouched.

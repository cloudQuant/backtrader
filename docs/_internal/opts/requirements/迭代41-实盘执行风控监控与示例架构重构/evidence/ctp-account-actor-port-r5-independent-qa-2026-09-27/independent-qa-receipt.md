# Independent QA — AccountActorPort r5

**Verdict: `PARTIAL / NEEDS_REVISION` — local fake boundary evidence only.** The candidate has useful route-snapshot and default-dispatch guards, but I found a constructor-time route mutation that reaches the local gateway factory after the descriptor has changed to CTP. This is not external actor, G6-P, F14, Store integration, or live acceptance.

## Frozen inputs and integrity

- r5 freeze: `D:\temp\iteration41-ctp-account-actor-port-r5-20260927`
- r5 `hashes/manifest.json` SHA-256: `73521009058983A0E34172C4CA0020C5F32F4CBF25DA7B1FB554F4D68BAAA4BD` (matches requested).
- Exact r4 base manifest SHA-256: `8F793CC85754F6FA447925BD0AD40570DD7F10480773F45500B56FD0933591A8`; r5 manifest names this exact hash as its base.
- Independent integrity verification: r4 9/9 payloads; r5 16/16 payloads; r5 repeated checksum index 18/18 entries. r5 source/test payload hashes and sizes match the manifest.
- r5 patch SHA-256: `5646BCD7959D2BE35F0EB38299B26F4D3CFFEA5C8CD4A6AB5ADD902E3B3E8D6C`.
- I copied r4 into the QA workspace, replayed the patch with `git apply --ignore-whitespace`, and compared all six changed source/test files to the frozen r5 candidate after newline normalization; all six matched. Plain `git apply --check` first failed on two CRLF-sensitive hunks; the successful whitespace-tolerant replay and exact normalized output comparison are both retained in this packet.

## Independent tests

- Focused frozen test file, run against replay2: **40 passed** under pytest and **40 passed** under unittest.
- Pytest ran with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, bytecode/cache disabled, and a `sitecustomize` guard inherited by subprocess tests. The guard blocks imports of `bt_api_py`/`_ctp` and raises on socket connect/DNS APIs. No real SDK, native module, network, private config, or provider was accessed.
- Independent guarded module-origin check resolves `account_actor_port`, `store_boundary_harness`, and `store_boundary_harness_testonly` only from the replay2 copy.
- Four added fake adversarial controls passed: hostile mapping and opaque route properties were not evaluated; shared nested route mutation stopped both existing handles before legacy calls; the ordinary harness rejected before calling a fake actor; and receipt/typed input paths remained bounded by existing tests.

## Counterexample: constructor route TOCTOU

At `source/store_boundary_harness.py:55-61`, the harness captures a route snapshot, then calls the injected `credential_resolver`, then constructs the gateway without rechecking the snapshot. My lazy fake used `provider="gateway"`, `backend="gateway"`, and `config.exchange_type="IB_WEB"`. The resolver changed that same nested mapping to `CTP`. Observed counts:

- initial classification: `non_ctp`
- classification after resolver: `ctp`
- `gateway_factory` calls after the mutation: **1**
- later submit: rejected with `store_route_changed_after_construction`
- legacy dispatch calls: `0`

The later operation check blocks an order, but it does not undo construction already performed against a stale route. The dedicated expected-security pytest/JUnit is intentionally red and retained. Recheck the snapshot after each callback that can mutate shared route state and before any factory/client creation, or pass a copied immutable route snapshot to those callbacks.

## Fake replay and test-only boundary

`StoreBoundaryHarness._dispatch_actor_command` at line 100 rejects typed commands as `trusted_durable_remote_actor_unavailable`; my fake actor observed **0** calls. By design, `store_boundary_harness_testonly.LocalFakeStoreBoundaryHarness` overrides this and sends to its injected actor after claiming an in-memory `FakeLocalActorReplayLedger`. Two fresh child processes each accepted the same command ID and each recorded **1 fake actor call**. This is consistent with the documented process-local ledger limit, not a cross-process replay guarantee.

The test-only module is referenced by the test file and documentation, not by another runtime module in the candidate source. It is not mechanically disabled: a caller can import it directly and supply any `CtpAccountActorPort` implementation. No such real actor was used here. The default harness remains closed; this explicit test-only class must not be wired into a runtime or treated as authority.

## Acceptance boundary

The local contract validates typed fields and compares receipt/context values but does not authenticate caller-supplied epochs or receipts, persist authority across processes, or establish an external account/session fence. R5 remains `LOCAL_FAKE` only. Fix the constructor TOCTOU before treating this revision as a clean local route-boundary candidate; external actor, durable cross-host uniqueness, trusted receipts, Store integration, and G6-P/F14 remain unproven.

## Raw evidence

`qa-manifest.json` hashes every included input copy, replay file, test, log, and JUnit result. The ZIP is adjacent to this directory and has its own reported SHA-256.

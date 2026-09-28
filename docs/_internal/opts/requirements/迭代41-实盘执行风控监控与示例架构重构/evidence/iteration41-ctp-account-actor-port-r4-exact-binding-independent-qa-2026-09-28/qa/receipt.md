# Independent QA receipt — Account Actor Port r4 replay

- Replay directory: `D:\temp\iteration41-ctp-account-actor-port-r4-qa-replay-20260928-01`
- Candidate: `D:\temp\iteration41-ctp-account-actor-port-r4-exact-binding-20260928-01`
- Base freeze: `D:\temp\iteration41-ctp-account-actor-port-freeze-20260927-r3-r1`
- All commands ran from the replay directory. No source files were copied into `qa-raw`; the three replay source/test files had the listed SHA-256 values before and after both reruns.

## Tested source hashes

| File | Bytes | SHA-256 |
|---|---:|---|
| `account_actor_port.py` | 25,739 | `e0d3147ec7ce867ec96f29e5dc3e8c4a9343b6ef2845b03e712a7676c9c55a48` |
| `store_boundary_harness.py` | 5,928 | `0126c81c87a207b8e9585bc0608533574156a631f4c03e9be1b34fbd4ce23aa6` |
| `tests/test_store_boundary_harness.py` | 33,710 | `51bd221458165f970ec10d7d1e0403663f7ca5b9e0a6a4ea69d3ab7bfc702dc3` |

## Captured runs

- Full suite: `python -B -m unittest discover -s tests -v` — exit 0, 36 passed.
- Focused selection: `python -B -m unittest -v test_store_boundary_harness.ActorReceiptBindingTests.test_stale_account_and_epoch_intents_reject_before_actor_or_fake_sink test_store_boundary_harness.ActorReceiptBindingTests.test_stale_epoch_wrong_account_or_wrong_session_intent_reject_before_actor test_store_boundary_harness.ActorReceiptBindingTests.test_invalid_receipts_never_reach_downstream_fake_sink test_store_boundary_harness.ActorReceiptBindingTests.test_duplicate_intent_is_claimed_once_before_actor_call test_store_boundary_harness.ActorReceiptBindingTests.test_receipt_wrong_operation_is_rejected_without_local_fallback test_store_boundary_harness.ActorReceiptBindingTests.test_receipt_wrong_digest_and_untyped_receipt_are_rejected test_store_boundary_harness.ActorReceiptBindingTests.test_receipt_failure_consumes_fake_local_replay_slot` — `PYTHONPATH=D:\temp\iteration41-ctp-account-actor-port-r4-qa-replay-20260928-01\tests`, exit 0, 7 passed.

`commands-and-exits.txt` records command, working directory, `PYTHONPATH`, and exit codes. Full captured streams are in `full-suite.stdout.txt`, `full-suite.stderr.txt`, `focused.stdout.txt`, and `focused.stderr.txt`. Python unittest wrote the test transcript to stderr; both stdout files are empty.

## Adversarial outcomes

- Stale account/epoch intent: fake actor calls 0; downstream fake sink calls 0.
- Mismatched returned receipt (context/account/epoch, command, digest, or operation): fake actor call 1; sink calls 0; no local fallback.
- Replayed command ID: first valid attempt reaches fake actor once and sink once; repeat is rejected before a second actor call.

## Authority and scope limits

This is local fake-only evidence. G6-P trusted external AccountActor is absent. Expected account/session/epoch values are caller-supplied, the command digest is unkeyed, and the replay ledger is in-memory and process-local. This does not authenticate actor identity, establish current account or epoch state, provide durable/cross-host idempotency or fencing, or prove provider state. No provider, SDK, credentials, network, runtime configuration, real actor/account, or real order/cancel route was used. The candidate is unintegrated and grants no write authority.

## Raw file hashes

- `commands-and-exits.txt`: 1,134 bytes, SHA-256 `15918d324e9d788ad83a78ea0007c3fde09795a2c331e07687f07c191b425387`
- `full-suite.stderr.txt`: 6,482 bytes, SHA-256 `f0392b017767ea48d7418e4fbb0a6fd3593dad3c66efc3192e0fac372178f90d`
- `full-suite.stdout.txt`: 0 bytes, SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- `focused.stderr.txt`: 1,408 bytes, SHA-256 `6d0c992cc7f1f1f7f92e4ae27b84498fe4b899dc074d1a38e4d7154cf3f29a36`
- `focused.stdout.txt`: 0 bytes, SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
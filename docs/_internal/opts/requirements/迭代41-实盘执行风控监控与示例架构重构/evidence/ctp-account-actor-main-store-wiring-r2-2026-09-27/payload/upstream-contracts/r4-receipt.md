# Account Actor Port r4 candidate receipt

Candidate: `ctp-account-actor-port-r4`  
Base freeze: `D:\temp\iteration41-ctp-account-actor-port-freeze-20260927-r3-r1`  
Base manifest SHA-256: `417ebef0fc2a85b4e37ee22122024b0118211c161795abb79dac438840b960a1`  
R4 manifest SHA-256: `8f793cc85754f6fa447925bd0ad40570dd7f10480773f45500b56fd0933591a8`

## Candidate changes

- Added `ActorCommandContextV1` for exact locally expected account reference, runtime id, mode, config digest, session id, front/session ids, session generation, and actor epoch.
- Added `CtpSubmitIntentV2` and `CtpCancelIntentV2`; each canonical command digest binds the operation, command id, context, and logical request fields. Cancel target front/session must equal the context.
- Added `ActorCommandExpectationV2` and exact `ActorCommandReceiptV2` validation for operation, command id, every context field, and digest.
- Added `FakeLocalActorReplayLedger`, an explicitly required in-memory test ledger that claims a command id once before actor invocation and retains the claim on actor errors or invalid receipts.
- Preserved the r3 code-owned route classifier and its explicit non-CTP selectors. Unknown/ambiguous providers, environment downgrade, nested CTP routing, and raw `api`/`api_cls` injection remain fail-closed without client introspection.

## Verification

From this frozen directory:

- `python -B -m unittest discover -s tests -v` — 34 passed.
- `python -m ruff check account_actor_port.py store_boundary_harness.py tests\test_store_boundary_harness.py` — clean.
- In-memory `compile()` check — 3 Python files compiled; no bytecode written.

The full output is in `test-results.txt`, `ruff-results.txt`, and `compile-results.txt`; the manifest covers each file.

## Limits

This is an isolated fake harness, not wired into Backtrader and not an external account actor. The context and actor epoch are caller-supplied values; the command digest is unkeyed; and the replay ledger is in-memory. These mechanisms only compare local DTO shape and bind test inputs. They do not authenticate the actor, prove current actor epoch, prevent cross-process or cross-host replay, establish an external account-writer fence, or establish a common provider snapshot. A production receipt protocol needs authenticated service identity, authoritative account/runtime/session bindings, durable server-side idempotency, cross-host fencing, and a read/callback snapshot contract.

A valid-looking fake receipt may be accepted by the harness when it matches the locally supplied expectation. Stale epoch, wrong account/session, wrong command/operation, and duplicate command cases are rejected by tests; this does not make the values authoritative. Invalid receipts are detected after the intended actor-port method has been invoked, and do not cause a local SDK/native fallback. No provider, native SDK, credentials, network, or default route was used or enabled.
# Account Actor Port r4 exact binding candidate receipt

Candidate: ctp-account-actor-port-r4-exact-binding-20260928-01
Directory: D:\temp\iteration41-ctp-account-actor-port-r4-exact-binding-20260928-01
Base freeze: D:\temp\iteration41-ctp-account-actor-port-freeze-20260927-r3-r1
Base manifest SHA-256: 417ebef0fc2a85b4e37ee22122024b0118211c161795abb79dac438840b960a1
Candidate manifest SHA-256: b9ab1042bbf9ad71490ffac9524d5bba6834d32bd5c05b3a64e9524eb0858167

## Candidate delta

The candidate starts from the manifest-verified r3-r1 freeze and carries the r4 typed context, intent digest, exact receipt comparison, and local one-shot replay claim. It adds an optional downstream fake receipt sink that can receive a receipt only after operation, command ID, full context (including account reference and actor epoch), and command digest compare exactly. The incoming stale-account/stale-epoch checks and the one-shot replay claim happen before the fake actor-port call.

The patch relative to the frozen r3-r1 preimage is in changes.patch.

## Fake-only verification

- python -B -m unittest discover -s tests -v: 36 passed.
- ruff check account_actor_port.py store_boundary_harness.py tests\test_store_boundary_harness.py: clean.
- In-memory compile of three Python files: passed.
- Test stdout/stderr and command results are included in the manifest.

No main repository source was changed. No provider, native SDK, credentials, network, protected runtime config, account, actor service, or order/cancel action was used.

## Trust limits

The expected account/session/actor epoch values are caller-supplied; the command digest is unkeyed; and replay state is in-memory and process-local. This does not authenticate an external AccountActor, establish its current epoch, prevent cross-process or cross-host replay, establish a durable account-wide fence, or establish G6-P authority. A stale or mismatched returned receipt can only be detected after the fake actor-port response; the tests establish that such a receipt does not reach the optional downstream fake sink and does not trigger a local fallback. The candidate is not integrated or registered and does not enable CTP writes.

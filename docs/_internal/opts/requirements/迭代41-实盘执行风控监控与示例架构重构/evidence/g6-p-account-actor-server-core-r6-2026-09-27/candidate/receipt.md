# G6-P Account Actor server core — isolated fake candidate r6

Candidate directory: `D:\temp\iteration41-g6-account-actor-server-core-candidate-20260927-r6`  
Base r5 directory: `D:\temp\iteration41-g6-account-actor-server-core-freeze-20260927-r1`  
Base r5 manifest SHA-256: `925a72915cca210431a25d7db1993d6290025f241b6d76fe170b0cbe8f9b0420`  
Base r5 receipt SHA-256: `0132ff5b6097483a131fac26d2c8ee42d1d9de7b2178466a2f950a8c07d469c2`  
R6 manifest SHA-256: `9bc5f75a23db4870123c89c9d8a160c1389495c8fe63a7adb2d4ea6c8b23ac61`

## Change made in r6

Schema v2 adds `actor_dispatch_lifecycle` with durable `AVAILABLE`, `REVOKED`, and `CLAIMED` states for existing outbox rows.

- `authorize_dispatch` rechecks active writer epoch, persisted session context, current snapshot pointer, all four snapshot domains, digest, and injected fake authority before returning an existing authorization. If the row is stale, it persists revocation and blocks the command before returning an error.
- Publishing a newer snapshot atomically revokes every unconsumed `AVAILABLE` authorization and changes its command to `BLOCKED`. The old outbox row remains immutable audit history, not a send credential.
- `claim_for_dispatch(writer, authorization) -> DispatchClaimV1` is the only supported local final gate. It compares the exact typed receipt with command/outbox rows, repeats the current snapshot and writer/session checks in one `BEGIN IMMEDIATE` transaction, and consumes `AVAILABLE` as `CLAIMED`.
- `CLAIMED` prevents newer snapshots and writer revoke/reclaim. There is intentionally no release, completion, or crash-recovery operation: process death leaves the local account frozen. The core does not invoke a provider or SDK.
- Schema v1 migration preserves old outbox rows, but marks all old authorizations `REVOKED` and commands `BLOCKED`; it never upgrades an old returned receipt to available.

## Verification

From this candidate directory:

- `PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests -v` — 56 passed, 0 failed.
- `python -m ruff check account_actor_port.py account_actor_server_core.py store_boundary_harness.py tests\test_store_boundary_harness.py tests\test_account_actor_server_core.py` — clean.
- In-memory compile check — 5 Python files compiled; no bytecode written.

Raw command output is in `test-results.txt`, `ruff-results.txt`, and `compile-results.txt`. Tests cover same-snapshot intent/authorization idempotency, v77 authorization invalidated by v78, persisted revocation, final claim rejection after cross-process reopen, explicit final-gate one-shot consumption, snapshot/writer freeze while claimed, process crash with durable claim, and migration of an existing v1 authorization to revoked audit-only history. The r5 independent QA script and its original output/receipt are preserved under `r5-counterexample/`; the complete frozen r5 candidate is preserved under `r5-counterexample/frozen-candidate/`.

## Trust limits and dispatch semantics

A `DispatchAuthorizationV1` is only a local outbox-row identity. It is not a provider receipt and cannot be used through the candidate's supported path without `claim_for_dispatch`. A newer snapshot invalidates it. The final gate gives a one-shot local `DispatchClaimV1`; there is no external dispatcher in this candidate. If a future dispatcher is added, it must accept only this final claim and must treat a crash after the claim as unknown/fenced. This candidate cannot safely clear that claim, so it is not operationally recoverable.

The local SQLite file is writable by the same user/process environment; another writer with file access can mutate or replace it and bypass this local gate. The fake HMAC verifier/key can attest synthetic caller-supplied data and is not an external trust root. Neither local SQLite transactions nor the claim establish authenticated actor identity, cross-host exclusion, manual-client fencing, or provider-side dispatch semantics.

**G6-P remains BLOCKED.** No real CTP SDK, provider, credentials, account, network, main Store, MCP, or default route is connected. CTP also has no proven common snapshot version for funds, orders, trades, and positions. Independent r6 QA is not yet recorded by this receipt.

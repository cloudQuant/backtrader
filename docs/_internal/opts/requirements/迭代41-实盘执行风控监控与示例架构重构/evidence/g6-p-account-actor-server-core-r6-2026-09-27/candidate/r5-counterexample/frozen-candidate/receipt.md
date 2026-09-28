# G6-P Account Actor durable core — isolated fake candidate r1

Candidate directory: `D:\temp\iteration41-g6-account-actor-server-core-freeze-20260927-r1`  
Base r4 directory: `D:\temp\iteration41-ctp-account-actor-port-freeze-20260927-r4`  
Base r4 manifest SHA-256: `8f793cc85754f6fa447925bd0ad40570dd7f10480773f45500b56fd0933591a8`  
R5 manifest SHA-256: `925a72915cca210431a25d7db1993d6290025f241b6d76fe170b0cbe8f9b0420`

## Implemented local contract

`account_actor_server_core.py` adds a SQLite-backed fake service core:

- `claim_writer` persists one ACTIVE owner per canonical account and issues a strictly increasing epoch plus a random opaque local capability. Active ownership survives process death and reopen. `revoke_writer` only revokes the exact active handle; a later claim increments the epoch.
- `bind_session` persists one exact `ActorCommandContextV1` per writer epoch: account, runtime, mode, config digest, session id, front/session ids, session generation, and actor epoch. A different session cannot replace it within the epoch.
- `publish_snapshot` accepts exactly four facts (`funds`, `orders`, `trades`, `positions`) with the same account, positive snapshot version, and source id. The complete canonical bundle digest is checked against the injected fake HMAC authority, then all facts and proof are stored atomically. Snapshot versions must increase per account.
- `reserve_intent` persists command identity and canonical payload/context. The durable key is `(account_ref, operation, intent_id)`. Exact retries return the same command; reused ids with changed payload, context, or snapshot version reject.
- `authorize_dispatch` takes `BEGIN IMMEDIATE` and rechecks the current writer capability/epoch, persisted session binding, stored command binding/digest, current snapshot version, exact four-domain set, and source proof before inserting the unique outbox row. Replay returns the same local row; no second row is inserted.
- Schema version and exact SQLite table definitions are checked on open. Unknown, partial, or altered schema is rejected without repair.

`authorize_dispatch` ends at a durable local outbox authorization. The core makes no provider, SDK, network, credential, or native call. It does not claim provider dispatch or exactly-once external side effects.

## Verification

From this frozen directory:

- `PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests -v` — 50 passed.
- `python -m ruff check account_actor_port.py account_actor_server_core.py store_boundary_harness.py tests\test_store_boundary_harness.py tests\test_account_actor_server_core.py` — clean.
- In-memory compile check — 5 Python files compiled; no bytecode written.

Tests include two competing processes claiming one account (one winner), process death leaving an unreclaimable ACTIVE claim, explicit revocation and stale epoch rejection, restart-safe intent dedupe, same intent id across SUBMIT/CANCEL, wrong account/session, incomplete/mixed snapshot rejection, missing authority at publish/final gate, current-version change after reserve, tampered domain bytes, and malformed schema rejection. Results and source hashes are in the manifest-covered files.

## Blocks and limits

This is a local SQLite/fake-authority model only. The fake HMAC key is test input and the fake verifier can attest caller-supplied synthetic data; neither authenticates an external source. The session binder is an in-process fake seam and does not prove an accepted CTP login. Caller-visible DTOs, local tokens, unkeyed command digests, local SQLite rows, and the fake key are not external authority.

SQLite `BEGIN IMMEDIATE` demonstrates local single-file serialization. It does not prove cross-host exclusion, protect against a privileged same-user writer/file replacement, fence human/manual clients, or establish one external account actor. No authenticated service identity, production key source/lifecycle, distributed writer lease, or crash-recovery supervisor exists. CTP does not currently expose a common version across funds, orders, trades, and positions; the four-domain snapshot contract is not provider evidence. Missing real source authority, shared snapshot, or external writer fence keeps G6-P blocked. The candidate is not connected to a main Store, SDK, MCP, default route, or production/simulation provider path.
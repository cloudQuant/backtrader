# Independent QA — G6-P local account actor server core r1

Date: 2026-09-27. Scope is the frozen fake SQLite server-core candidate only. No main production source, SDK, CTP native API, provider, credentials, account, or network was accessed.

## Freeze verification and test run

- Frozen source: `D:\temp\iteration41-g6-account-actor-server-core-freeze-20260927-r1`
- `manifest.json` SHA-256: `925a72915cca210431a25d7db1993d6290025f241b6d76fe170b0cbe8f9b0420`
- QA copy: `D:\temp\iteration41-g6-account-actor-server-core-r1-independent-qa-20260927`
- All 11 manifest-listed payload files match frozen byte lengths and SHA-256; see `payload-verification.json`.
- Python: 3.11.5. Imports resolve only to the QA copy (`module-origins.txt`).
- Command: `python -B -m unittest discover -s tests -v` with `PYTHONDONTWRITEBYTECODE=1`.
- Result: 50 passed, 0 failed, exit 0. Raw stdout/stderr and exit marker are preserved.

The frozen suite independently exercises the two-process writer-claim race (one claim winner), process death with durable ACTIVE/unreclaimable writer, old epoch after revocation, replay across reopen, exact four-domain/account/version/source checks, source proof invalidation, snapshot update between reservation and initial authorization, and malformed startup schema rejection.

## Supplemental fake-only probes

Raw script/output are `adversarial_server_core.py` and `adversarial-results.*`.

- Two spawned Python processes reserved the same exact intent concurrently. Both got the same digest and `RESERVED` readback; one command row existed.
- Removing one snapshot domain after reservation made the final authorization fail with `snapshot_domain_set_incomplete`; command stayed `RESERVED`, outbox row count stayed zero.
- A malformed existing schema was rejected at startup as `database_schema_shape_invalid` and left unrepaired.
- The injected `FakeSnapshotAuthorityV1` can attest an arbitrary well-formed four-domain snapshot (version 77 and synthetic funds value); the core accepted it and returned `AUTHORIZED_LOCAL_OUTBOX`. This is expected for the explicitly fake HMAC authority. It proves no external/current provider snapshot authority.
- A process with direct SQLite file-write access replaced the local writer row's token hash and owner id with a chosen token, then used a matching local `WriterEpochV1` to bind a session, publish a fake snapshot, reserve, and authorize. This records the local DB-file ACL as part of the trust boundary; it is not a cross-host or tamper-resistant authority.
- After an intent had a local authorization for snapshot v77, publishing v78 did not revoke that authorization. A repeated `authorize_dispatch` returned the same v77 authorization while `actor_current_snapshots` was 78. This is an idempotent replay of the already committed local decision, not evidence of an external dispatch. A downstream consumer must not treat it as a fresh current-snapshot check. There is no dispatch/revalidation method in this module.

## Boundary assessment

`BEGIN IMMEDIATE` transactions serialize these local database operations, and the tested failure paths preserve zero-outbox/RESERVED state. The candidate is not a service deployment: it has no authenticated service identity, provider login/session observation, protected secret/credential source, external account uniqueness or lease, host/file ACL enforcement, cross-host SQLite fencing, or provider dispatcher. Account references, owner ids and session contexts are supplied inside the local composition; the HMAC test key is caller-provided. `DispatchAuthorizationV1` means only a durable local outbox row and is explicitly not a provider acknowledgement.

**G6-P remains BLOCKED.** The 50 passing local fake tests verify a candidate contract only. They do not establish a trusted account actor, external snapshot authority, common live provider snapshot, cross-host writer exclusion, or final provider dispatch. No real SDK/provider/native path was invoked.

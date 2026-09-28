# G6-P local account actor core r1 — independent QA

Date: 2026-09-27. This record covers only the frozen r1 local SQLite/fake-authority candidate. It does not include or evaluate the in-progress r6 work.

## Frozen source and independent run

- Frozen source: `D:\temp\iteration41-g6-account-actor-server-core-freeze-20260927-r1`
- Frozen `manifest.json` SHA-256: `925a72915cca210431a25d7db1993d6290025f241b6d76fe170b0cbe8f9b0420`
- The independent QA verified all **11/11** frozen payload entries by byte length and SHA-256 before copying to an isolated QA directory. The imported module origin was the QA copy, not the mutable main tree.
- Independent QA packet manifest SHA-256: `9dd201cff9325765a08169a251e3026519b024a9afa550e78259abbef07ca6e7`
- Python 3.11.5; command: `python -B -m unittest discover -s tests -v` with `PYTHONDONTWRITEBYTECODE=1`.
- Result: **50 passed, 0 failed, exit 0**. The exact stdout/stderr/exit, module origins, payload verification, test source, and adversarial harness are retained in the raw archive.

The frozen tests cover same-account two-process writer-claim contention (one winner), process death leaving an ACTIVE writer unreclaimable, revocation of old epochs, replay across reopen, four-domain/account/version/source checks, invalidated source proof, a snapshot update between reservation and initial authorization, and malformed-schema rejection without startup repair. Supplemental QA confirmed that two processes reserving the same exact intent return one digest/one durable command row; deleting a snapshot domain blocks authorization with zero outbox rows; malformed schema rejects as `database_schema_shape_invalid`.

## Material counterexamples and limits

1. **v77 → v78 stale authorization replay:** reserve and authorize an intent against snapshot v77, then publish v78. A repeated `authorize_dispatch` returned the same prior v77 `DispatchAuthorizationV1`; database `actor_current_snapshots` was v78 while the command remained `AUTHORIZED` with `expected_snapshot_version=77` and one outbox row. This is an idempotent replay of a previously committed **local** decision. It is not a fresh current-snapshot proof and is not evidence of provider dispatch. The module has no dispatch/revalidation method; a consumer must not treat this return as current authorization.
2. **Fake HMAC authority:** an injected test signer attested a syntactically valid four-domain snapshot (v77, synthetic funds `999999999999999999.99` CNY); the core accepted it into `AUTHORIZED_LOCAL_OUTBOX`. The signature proves only the injected local test authority, not provider/account state.
3. **Same-host database writer:** a process with direct SQLite file-write access replaced the local writer row/token hash and then supplied a matching local `WriterEpochV1`; the core accepted a fake snapshot and wrote `AUTHORIZED_LOCAL_OUTBOX`. The local database-file ACL is therefore inside the trust boundary; the design does not establish tamper-resistant or cross-host authority.
4. **Domain removal:** deleting a required snapshot domain after reservation blocked authorization (`snapshot_domain_set_incomplete`), left the command `RESERVED`, and kept dispatch rows at zero.
5. No provider dispatch surface exists (`core_has_dispatch_method=false`); `DispatchAuthorizationV1` is a local outbox record, not a provider receipt.

## Conclusion

**G6-P: BLOCKED.** The r1 candidate passes its frozen fake/local contract, but does not establish an authenticated account actor, protected external snapshot authority, a common live provider snapshot, cross-host writer exclusion, or final provider dispatch. No main production source was changed. No SDK, CTP native API, provider, credential, account, or network was accessed. The r1 result must not be merged with or used to imply acceptance of the separate r6 work.

## Archived artifacts

- Raw QA packet: [`g6-p-account-actor-server-core-r1-independent-qa-2026-09-27.raw.zip`](g6-p-account-actor-server-core-r1-independent-qa-2026-09-27.raw.zip), SHA-256 `86BC3A91FAA325C69CC9FAA6D940A95150CF099E028DADC7DCA6D88D1A496D63`.
- ZIP index: [`g6-p-account-actor-server-core-r1-independent-qa-2026-09-27.raw.zip.index.json`](g6-p-account-actor-server-core-r1-independent-qa-2026-09-27.raw.zip.index.json), SHA-256 `1CB71432EA54AF0FFEFE24595834FB09482F6F9C1C3F64185ECAB8E90AD54A07`.
- Machine-readable summary: [`g6-p-account-actor-server-core-r1-independent-qa-2026-09-27.json`](g6-p-account-actor-server-core-r1-independent-qa-2026-09-27.json).

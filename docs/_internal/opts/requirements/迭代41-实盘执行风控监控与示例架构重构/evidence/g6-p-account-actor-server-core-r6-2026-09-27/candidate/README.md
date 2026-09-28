# External CTP Account Actor Port — offline candidate r6

This independent candidate models a fail-closed composition boundary, a small code-owned provider registry, a locally checked V2 intent/receipt binding, and a fake SQLite-backed service core. It does not edit or import the main Backtrader package, does not implement a remote service, and must not be treated as a CTP write route. Unknown providers, ambiguous gateway selectors, and all raw `api`/`api_cls` injection are rejected without introspection.

Run the isolated fake harness and service-core tests with:

    python -m unittest discover -s tests -v

The required result is zero API-class/gateway construction, connect, or ReqOrderInsert/ReqOrderAction calls for missing/default actor routes. The tests also cover CTP environment-downgrade attempts, nested route maps, unknown providers, and injected API objects with trap properties. `ActorCommandContextV1`, `CtpSubmitIntentV2`, `CtpCancelIntentV2`, `ActorCommandReceiptV2`, and `FakeLocalActorReplayLedger` exercise local DTO binding. `AccountActorServerCoreV1` adds fake durable epoch/revocation, account/action/intent idempotency, common four-domain snapshot verification, and an atomic local outbox authorization gate. The outbox row is not a provider dispatch or acknowledgement.

`FakeSnapshotAuthorityV1` is an injected test HMAC verifier. Its key is not a deployed credential or trust root. The local database and epoch capability do not establish cross-host exclusion, authenticated service identity, or protection from a privileged same-host database writer.

The r6 service core revalidates current snapshot authority before replaying an existing authorization. A newer snapshot revokes all unconsumed old outbox authorizations; v1 outbox rows migrate as revoked audit history. An outbox row is not a dispatch credential. `claim_for_dispatch` is the single-use local final gate and atomically consumes an authorization only while the exact writer/session and complete current four-domain snapshot still match. A claimed row pins the local snapshot and writer epoch; this candidate intentionally has no release/completion/recovery path, so crash leaves the account frozen. It does not implement a provider dispatcher.

See INTEGRATION_CONTRACT.md for the precise main Store call points, existing seam differences, and public-compatibility limitations.

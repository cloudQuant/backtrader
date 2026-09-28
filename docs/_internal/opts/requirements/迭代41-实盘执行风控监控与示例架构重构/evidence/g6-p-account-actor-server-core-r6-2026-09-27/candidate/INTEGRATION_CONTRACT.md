# Candidate Store integration contract

This is a D:\temp-only design slice. It is not wired into Backtrader and creates no external actor.

The existing main BtApiStore has a public managed-adapter seam. For non-CTP routes its generic ManagedExecutionAdapter receives a legacy_dispatch callback; CTP uses a specialized managed adapter that enqueues to the local SDK command route. Both remain local execution paths. The CTP F14 authority is a Protocol that claims and rechecks an action; it does not execute through a remote account actor. None of these is a substitute for this separate transport-neutral write port.

For a reviewed integration, add an optional code-owned CtpAccountActorPort to BtApiStore composition and use UnavailableCtpAccountActorPort when absent. Call the route classifier/gate from the raw requested provider/backend and explicit route config before `_resolve_provider` reads `BT_STORE_PROVIDER`, before `_apply_env_gateway_overrides`, before config credential extraction, SDK import, client construction, autostart, or connection. Environment overrides must not downgrade an explicitly requested CTP route. Known CTP routes require the actor and reject if it is unavailable; ambiguous and unsupported routes reject regardless of actor presence. Raw `api` and `api_cls` injection is rejected before any object attribute inspection. Submit/cancel must build exact typed logical intents and invoke only actor_port.submit_order/cancel_order. Do not pass `_submit_order_legacy` / `_cancel_order_ref_legacy` into the actor seam as native capabilities. Put defense-in-depth guards inside the private legacy dispatchers as well.

The candidate gate treats a CTP actor route as actor-owned and never instantiates a local CTP client. A real Store also uses CTP for market data and account queries; therefore a future actor client must supply the required read-only events/snapshot feed or the Store must remain unavailable. Do not silently construct local TraderClient for data after routing writes externally.

## r3 code-owned route registry

The classifier accepts only selectors represented by this small, explicit
registry. It does not infer safety from an arbitrary provider name or a
`_gateway` suffix:

| Selector | Candidate treatment |
|---|---|
| `ctp`, `ctp_gateway` | CTP, regardless of environment overrides |
| `okx`, `binance` | Non-CTP direct route when backend is omitted or `direct` |
| `btapi` | Non-CTP only with explicit complete route facts, all in `OKX`, `BINANCE`, `MT5`, `IB_WEB` |
| `gateway` | Non-CTP only with explicit `IB_WEB` or `MT5` route facts; no selector defaults to CTP |
| `ib_web_gateway`, `mt5_gateway` | Non-CTP only when explicit route facts exactly match the alias; no selector defaults to CTP |
| `futu`, `oanda`, `vc` | Explicitly unsupported |
| Any other selector, backend, or route value | Ambiguous and rejected before local construction |

Any CTP selector discovered in top-level exchange fields, `exchange_kwargs`,
or recursively nested `symbol_routes` takes precedence. Raw `api` and `api_cls`
injections are always ambiguous for this gate. The classifier never reads
attributes from either object. Environment provider changes do not grant a
non-CTP route; a requested CTP provider remains CTP even if environment fields
name `IB_WEB`, `MT5`, or another gateway.

This deliberately narrows compatibility. The public main Store documents
`provider="okx", api=...`; this candidate would reject that injected-client
form. It preserves code-owned direct `okx`/`binance` selectors and the observed
explicit gateway forms above. The main `BtApiStore` also accepts custom
providers and injected SDK classes; those require a separately reviewed
registry entry rather than implicit NON_CTP classification. These are
candidate rules, not a claim that all historical BtApiStore paths have been
integrated.

## r4 local binding contract and authority limit

`ActorCommandContextV1` carries account reference, runtime id, mode, config
digest, session id, session generation, and expected actor epoch. The V2
submit/cancel digest canonically binds this context, operation, command id, and
all logical intent fields. `ActorCommandReceiptV2` must return the exact
context, command id, and digest. The fake harness compares every field before
returning a receipt. Context mismatch rejects before actor-port invocation;
receipt mismatch never falls back to a local client. An explicit
`FakeLocalActorReplayLedger` reserves each command id once before the fake
actor call, and keeps the reservation after an exception or invalid receipt.

This is process-local test enforcement only. The context and actor epoch are
caller-supplied local expectations, the digest is unkeyed, and the replay
ledger is in-memory. They do not authenticate the actor, prove its current
epoch, prevent replay across processes/hosts, establish an external account
fence, or provide a common provider snapshot. A production protocol still
needs authenticated actor identity, authoritative account/runtime/session
bindings, a durable server-side idempotency ledger, cross-host fencing, and a
read/callback snapshot contract. No actor implementation or authenticated
receipt protocol exists in this candidate.

The fake actor in tests verifies only method/DTO plumbing and zero local calls. No real AccountActorPort implementation, credentials, service identity, deployment trust pin, external account fence, provider snapshot, callback feed, handoff or native API exists here. The candidate is fake-only and does not enable a default CTP route.

## r6 stale-authorization and final-gate behavior

The r6 core upgrades the local database to schema v2. A v1 outbox row is kept
for audit, while its lifecycle is created as `REVOKED` and its command becomes
`BLOCKED`; migration does not assume that a previously returned local receipt
was never observed. New rows have a separate lifecycle: `AVAILABLE` can be
revoked by a newer snapshot, or consumed once as `CLAIMED` by the final local
gate. `authorize_dispatch` rechecks the exact active writer and persisted
session context, then re-verifies current snapshot version, all four domains,
and fake proof before it returns an existing `AVAILABLE` authorization.

`claim_for_dispatch(writer, authorization) -> DispatchClaimV1` is the only
supported route from that row to a local dispatcher. It compares the typed
receipt against the durable command/outbox row and repeats the current
writer/session/four-domain/source-proof checks in one immediate transaction.
The transaction changes `AVAILABLE` to `CLAIMED`; repeated or stale receipts
reject. A newer snapshot, writer revocation, or new writer claim is blocked
while any row is `CLAIMED`. The candidate deliberately has no completion,
release, or stale-claim recovery method, so a process crash leaves a durable
freeze. Outbox rows are not sendable by direct read, and this module contains
no provider dispatcher or provider call.

This final gate and revocation model rely on the local code path and SQLite
transaction. They do not defend against another process with same-user database
write access, file replacement, or an uncooperative consumer that bypasses the
gate. The fake HMAC is not an external trust root. A production dispatcher
would need an authenticated actor, protected writer service, trusted source
authority, cross-host fence, complete provider snapshot semantics, and a
reviewed outcome/recovery protocol. G6-P remains blocked.

## r5 fake durable service core

`account_actor_server_core.py` is an independent SQLite service-core model. It does not change the r4 Store classifier or wire into Backtrader. Its public surface is `AccountActorServerCoreV1`, `WriterEpochV1`, `AccountActorIntentV1`, `AccountSnapshotBundleV1`, `SnapshotDomainFactV1`, `FakeSnapshotAuthorityV1`, and `DispatchAuthorizationV1`.

- `claim_writer(account_ref, owner_id)` takes an immediate SQLite write lock, issues a monotonically increasing account epoch and a random local capability, and leaves an ACTIVE claim durable. A process crash does not make the claim available again. `revoke_writer(exact_handle)` durably revokes the current exact epoch; only then can the next claim increment it.
- `bind_session(handle, context)` binds one exact runtime/mode/config/session, front/session id, generation, and epoch tuple to that writer epoch. Intents must match it before reservation; final outbox authorization re-reads and compares the persisted context and command digest in the same transaction.
- `publish_snapshot(handle, bundle)` accepts exactly one `funds`, `orders`, `trades`, and `positions` fact with identical canonical account reference, version, and source id. The injected fake verifier attests the canonical bundle digest. Snapshot versions increase monotonically per account.
- `reserve_intent(handle, intent, expected_snapshot_version=...)` durably deduplicates by `(account_ref, operation, intent_id)`. Exact retries read the existing command; a reused id with changed body or snapshot version rejects.
- `authorize_dispatch(handle, operation=..., intent_id=...)` uses one `BEGIN IMMEDIATE` transaction to recheck the live epoch, reserved command, current snapshot version, four-domain set, stored digest, and fake source proof, then inserts one unique transactional outbox row. Concurrent/replayed calls return the same local outbox authorization. There is no provider callback inside or outside this method.

These SQLite checks demonstrate local serialization and fail-closed record handling only. The session context is supplied through this fake in-process seam; it does not prove a live SDK login. The fake HMAC key is test input; the verifier is not an authenticated source authority. A service deployment still needs authenticated service identity, key lifecycle, cross-host writer fencing, a source contract that supplies one common funds/orders/trades/positions snapshot version, and a provider actor that owns all credentials/sessions/dispatch. CTP does not currently provide the common snapshot version assumed by this model. Manual clients, alternate processes with file access, and old local SDK routes remain outside this candidate. The outbox is only a durable local authorization fact; external side-effect exactly-once behavior cannot be inferred from it.

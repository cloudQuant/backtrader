# G6-P external Account Actor threat-model and acceptance review

Date: 2026-09-27 (Asia/Singapore)
Disposition: `G6-P F14_STRICT_BLOCKED / G8-P NOT_RUN / NO_WRITE / LIVE_NO_GO`.
This is an independent read-only source review. No credentials, private account/config data, provider, native SDK/session, or network were used. Main-repo source was bound to HEAD `ad2c142b9a8b42cede85886528c681abdfcb8096`; the worktree had 106 tracked modifications, so `main-source-evidence.json` pins each reviewed document/source file by byte count and SHA-256.

## Decision

A deployable Account Actor can address G6-P only if it is the actual sole credential/session owner and final native dispatcher. A service that merely returns a signed lease or `assert_active=True` while Backtrader still has usable CTP credentials/native access leaves a revoke-to-`ReqOrderInsert`/`ReqOrderAction` race and direct-writer bypass. The actor must bind each action to a current cross-host account epoch, a trusted same-version full account snapshot, and one durable one-use action claim, then recheck and dispatch inside its own serialized service boundary.

The public CTP query/request interface described by the reviewed evidence gives separate asynchronous query terminal callbacks, not a transaction/version shared by funds, all open orders, trades, and positions. `bIsLast`, repeated reads, a local SQLite lease, a signature, or a transport ACL cannot manufacture that missing common revision. Without a broker/provider snapshot watermark or a separately trusted complete event ledger with gap detection and a proven writer boundary, strict G6-P is not achievable using public CTP calls alone. Keep it blocked.

## Current route and bypass surface

The main source still has local dispatch paths: `BtApiStore.submit_order()` falls back to `_submit_order_legacy()` without a managed adapter; cancellation has analogous public/private legacy paths; the CTP managed path queues to the local SDK route; `_ensure_api_ready()` can instantiate/connect a direct or gateway client; CTP gateway construction imports the legacy gateway wrapper. Broker submit/cancel call the Store. The native SDK surface still contains direct `ReqOrderInsert` and `ReqOrderAction` calls. The G6-P source audit also identifies the older `GatewayClient` defaulting to an in-process CTP runtime and SDK direct calls as bypasses. The newer generic Router/SQLite writer authority coordinates participants using the same local database; its own source doc says it cannot exclude another host or an uncooperating provider session. Curve/ZAP/static peer ACL is transport identity, not an account epoch, complete snapshot, or egress boundary.

I also inspected the local D:\bt_api_py Router and writer-authority files (HEAD d3674e19a11b9f35f19ae756899bcf18854c8c46, 27 tracked modifications; exact hashes in gateway-source-evidence.json). Their code documents the same-database/cooperating-process limit. The ZMQ server path named in the service-contract review was absent at audit time, so its ACL summary here is from the main repo's hashed G6-P audit, not a fresh review of that external transport source.

Before integration, inventory and block every CTP path, including environment-selected provider/backend, `api`/`api_cls` injection, local gateway/autostart, managed and legacy dispatchers, SDK/native handles exposed through Store properties, direct TraderClient `Req*`, queue/arm helpers, raw gateway messages, and old gateway versions. Local Store gating cannot undo a caller-created native object; the production composition must not accept such an object in the first place. Read-only market/account projections must also come from the actor (or a separately proven non-write identity); silently opening a second local CTP client would restore the bypass.

## Required external proofs vs. local code tests

| Property | Deployable actor must prove | Local code can test; it cannot prove |
| --- | --- | --- |
| Full same-version state | One authoritative revision bound to account, TradingDay, session generation, and fence epoch; exact `account_funds`, **all** `open_orders` (including foreign/manual), `trades`, `positions`; counts, complete pagination/cursors, deterministic digest, source/watermark and gap detection. | Reject missing collections/pages, duplicate or inconsistent pages, mismatched version/account/day/epoch, stale watermarks, and false completeness flags before the fake executor. Tests cannot establish provider truth or atomicity. |
| Cross-host epoch/fence | Durable monotonic per-account epoch, CAS acquire/renew/revoke/transfer, stale owner rejected by the final service dispatcher, no epoch rollback after restart. Unknown/in-flight work prevents takeover. | Two local processes sharing SQLite test cooperating local serialization only. They do not prove another host/user/manual client is excluded. Require two isolated hosts and service audit. |
| Credential and egress custody | Only the actor service identity can retrieve usable CTP secrets/create the write session/reach the provider write network. OS/secret-store/firewall policy denies old workers, other hosts/users, terminals, direct SDK and break-glass paths; rotation/revocation is observable. | Assert Store never extracts credentials, imports SDK, constructs/connects a local client, or reaches native methods for actor-owned CTP routes. Only deployment IAM, secret ACL and network-egress logs prove custody/exclusion. |
| Final dispatch and revocation | In the same service/serial account owner: recheck current epoch, revoke state, one-use claim/action digest, approval/risk, snapshot version, session generation and expiry; persist `DISPATCHING` then invoke the unique native worker. Revocation/transfer and dispatch are linearly ordered. | Barrier fakes can explore both race schedules and prove adapter ordering. A client-side `assert_active()` followed by local native call is still TOCTOU. Only the deployed final dispatcher closes it. |
| Crash/unknown | Durable dedupe; any crash/timeout after possible send becomes `UNKNOWN`, does not resend, and freezes the account/epoch until exact reconciliation. Callback/request/order identity is preserved. | Inject crashes before claim, after claim, after native send, before callback and before journal commit; assert one possible send maximum and no takeover/retry while unknown. Fakes do not prove provider callback truth. |

## Independent AccountActorPort r2 review

Candidate: `D:\temp\iteration41-ctp-account-actor-port-freeze-20260927-r2`, frozen manifest SHA-256 `ac45026c48d247b66f0da18e59211c7bd2e610cdaa5e7bd605a89cf1625f7a76`. An independent exact copy is at `D:\temp\iteration41-g6p-account-actor-independent-review-20260927`. All 9 manifest payloads and sidecars verified; the 12-file source/copy trees matched. In the isolated copy, `python -m unittest discover -s tests -v` passed **15/15**, `py_compile` passed, and Ruff passed. Logs and the probe scripts are retained beside this review.

The candidate is a useful fake-only typed port/unavailable-default prototype, not an Account Actor implementation or G6-P evidence. It is not wired into BtApiStore and has no service identity, trust pin, account/session binding, cross-host epoch, snapshot, credential boundary, final native dispatch, callback owner, or bypass proof. Its receipt expressly limits the result to interface/fake plumbing.

Two source-level gate issues block direct integration without changes:

1. `classify_store_route(StoreRouteDescriptor(provider="custom-provider", api_cls=...))` returns `NON_CTP`; `require_account_actor_before_local_client(..., None)` allows it, and the harness constructs the local class. QA-only probe output: `unknown_provider_with_api_cls_route_kind=non_ctp`, `unknown_provider_unavailable_actor_gate=allowed`, `unknown_provider_factory_calls=1`. Integration must use an explicit code-owned non-CTP registry and classify every unknown/injected client as ambiguous/fail-closed.
2. For `provider="btapi"` with an injected object, route classification reads `api.exchange_kwargs` before rejecting the unavailable actor; a custom property ran twice in the independent probe. Reject caller `api`/`api_cls` before any introspection and never inspect an untrusted/native object during route classification. This cannot undo construction that occurred before Store entry.

The typed fake port must remain non-authorizing. Its `QUEUED` receipt is only an actor queue disposition; neither `actor_epoch` nor a matching command ID is proof of provider acceptance or active authority. A future transport must bind principal/account/session/action from authenticated server context and expose no local native callback/handle.

## Short actionable acceptance path

### A. Source-only integration gate (offline; no SDK/provider/network)

1. Integrate an optional **code-owned** actor client with `UnavailableCtpAccountActorPort` as default. Resolve the exact immutable route before `_resolve_provider`, env overrides, secret extraction, SDK import, API/gateway factory, autostart or connect. No config flag/env fallback may re-enable local CTP. Reject all raw `api`/`api_cls`, unknown providers, CTP route maps, legacy direct/gateway modes and private fallback calls before side effects.
2. Add counters proving zero credential resolver, SDK import, native client/API/gateway factory, connect/start, `ReqOrderInsert` and `ReqOrderAction` calls on every denial path. With a trusted actor client, prove only exact typed submit/cancel reaches that port, never the Store's native queue/legacy callback. Reject CTP mixed routes even when another venue is primary. Keep actor read projections separate from write receipt semantics.
3. Fake-authority tests: exact account/runtime/mode/config/artifact/session/day/generation/action/approval/cancel-target binding; trust pin/audience/key and nonce/replay/expiry/revocation failures; complete four-set same-version snapshot and pagination; incomplete/foreign-order/mutated-version failures; competing epochs; revoke-vs-dispatch barriers; UNKNOWN crash cuts/restart with no resend or new owner. Every rejection asserts zero fake-native dispatch.
4. Re-run static writer inventory/disposition review and add an explicit zero-reachable-local-CTP-dispatch result. Existing static inventory is candidate enumeration only; it must not be treated as runtime reachability proof.

Commands for current offline contracts after integration (not run as part of this source review):

```powershell
python -m pytest -q tests/unit/runtime/test_ctp_f14_external_admission.py tests/unit/runtime/test_ctp_f14_signed_receipt_contract.py tests/unit/runtime/test_ctp_f14_shared_runtime_guard.py
python -m pytest -q tests/unit/stores/test_managed_ctp_store_adapter.py tests/unit/stores/test_ctp_managed_projection_bridge.py tests/integration/test_iteration41_gateway_store_composition.py
python scripts/collect_iteration41_writer_inventory.py --source-root . --output D:\temp\g6p-writer-inventory.json
python scripts/verify_iteration41_writer_dispositions.py --source-root . --checklist docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\live-execution-writer-dispositions.json
```

### B. External service / deployment gate

Use two isolated host identities and the deployed actor, not two threads or two clients in one process. Race acquire, restart, revoke/transfer, stale A dispatch, and B dispatch. Pause A between snapshot/claim and final dispatch; transfer to B; resume A and prove the actor's provider-call counter stays zero for A. If A is already `DISPATCHING`, B must remain blocked until exact terminal reconciliation; if outcome is ambiguous, persist `UNKNOWN`, prevent resend and deny takeover. Repeat with gateway crash/lost callback/restart. Exercise expired/revoked certs, old service build, another OS user, another host, direct terminal/client and alternate SDK/API paths; capture independent secret-store, OS ACL and network-egress denials. A Python handler rejection alone is not enough.

### C. Snapshot/provider gate and limited positive test

Obtain the vendor/service contract for a common account revision or a trusted event-ledger watermark covering funds, all open orders, trades and positions. Demonstrate completeness, pagination, loss/replay detection, foreign/manual order inclusion, and coherent behavior while account state mutates. If only separate public CTP query responses are available, stop here: mark snapshot unsupported and keep strict F14 closed. Only after G0-G5, service deployment pins, cross-host exclusion, close/recovery, account/risk approvals and independent QA pass may a separately approved, one-action positive test be requested. Keep provider return/queue disposition `RETURNED_UNVERIFIED` until correlated callbacks and exact account reconciliation prove terminal outcome.

## ADR and decision dependency

ADR-41-16 is still `PROPOSED`. Its Option B is an unapproved, explicitly residual-risk **SimNow operational-attestation** candidate; it cannot be called strict F14 or account-wide cross-host exclusion, and production never inherits it. Matrix ordering is G0-G5, then G6-S→G7-S for a narrowly approved SimNow operational test; G7-S does not close G6-P. Strict SimNow F14/production need G6-P; G8-P is separately `NOT_RUN`. No current evidence authorizes an order/cancel.

There is no logical cycle if a trusted service and a versioned snapshot source exist: the same service can own credentials, epoch, snapshot and final dispatch. There is a hard capability blocker if the provider offers neither a common versioned snapshot nor a trustworthy equivalent ledger/watermark. A local gateway cannot infer that version from independent CTP terminal callbacks. The right outcome then is continued `BLOCKED`, not another local adapter.

## Evidence references

Main source hashes and tracked-dirty count: `main-source-evidence.json`; inspected gateway source hashes/tree state: `gateway-source-evidence.json`. Candidate manifest verification and all replay logs are in this directory, including `independent-manifest-check.json`, `independent-unittest.log`, `independent-pycompile.log`, `independent-ruff.log`, and two QA-only adversarial probes. Reviewed normative evidence: `ctp-current-acceptance-matrix.md`, `ADR-41-16-simnow-f14-writer-fence-proposal.md`, `ctp-g6p-account-actor-architecture-audit-2026-09-27.md`, `ctp-g6p-g8p-external-account-control-service-contract-review-2026-09-26.md`, and `ctp-g6p-g8p-production-path-audit-2026-09-27.md`.



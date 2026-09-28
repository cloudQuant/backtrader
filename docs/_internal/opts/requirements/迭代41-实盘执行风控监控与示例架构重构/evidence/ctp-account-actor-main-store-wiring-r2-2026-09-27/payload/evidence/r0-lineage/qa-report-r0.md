# QA report: AccountActorPort Store wiring candidate

## Verdict

The isolated wiring candidate passes the focused offline checks. The copied main checkout is unchanged. This is a local DTO/port plumbing candidate only; it is not production account authority, an authenticated actor service, an accepted CTP route, or evidence of a live broker/gateway session. Default runtime/CLI no-write behavior remains intact. The actor methods are invoked only when a caller explicitly supplies a typed port; this isolated candidate must not be used with a live port.

For real production acceptance, an externally authenticated and authoritative AccountActorPort service is indispensable. A generic broker/gateway is insufficient unless it supplies that command contract, current per-action authority checks, durable idempotency, account-wide cross-host fencing, and a read/callback snapshot bound to the same session. None is available here.

## Frozen inputs and source identity

- Main Store input snapshot: `input-sources/btapistore.py`, 780,123 bytes, SHA-256 `dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826`.
- The current main checkout Store had the same SHA-256 at QA completion. No main production source was modified.
- Frozen r4 manifest: SHA-256 `8f793cc85754f6fa447925bd0ad40570dd7f10480773f45500b56fd0933591a8`.
- Frozen r4 `account_actor_port.py`: SHA-256 `e0d3147ec7ce867ec96f29e5dc3e8c4a9343b6ef2845b03e712a7676c9c55a48`; copied byte-for-byte to the candidate Store package.
- The r4 manifest's nine payload entries were checked against the frozen r4 source directory. Its `classify_store_route`, `require_account_actor_before_local_client`, `_collect_config_routes`, `_collect_symbol_routes`, `_collect_nested_selector_fields`, `_selector`, and `_venue` AST nodes equal the copied r3-r1 contract.
- Candidate runtime `runner.py`, `registry.py`, `cli.py` and `test_runtime_live_dispatch_guard.py` retain their copied baseline hashes; the live dispatch guard passes in candidate tests.

## Gate ordering and negative probes

The candidate builds a route-only detached descriptor from raw arguments and relevant environment selectors, then classifies and gates before `_resolve_provider`, `_apply_env_gateway_overrides`, secret string conversion, raw `api.exchange_kwargs` access, SDK resolver/import, wrapper/client construction, or `autostart`. CTP route classification takes priority over the forwarding backend label and nested selector evidence. Unknown backend values and unknown/unrelated provider families cannot become actor routes just by carrying CTP selectors. Raw `api` and `api_cls` injection is rejected by identity without inspecting attributes.

Negative tests verified these exact cases:

1. `provider="ctp", backend="forwarding", api=<property trap>, config.execution_authorization_secret=<str/bool trap>, BT_STORE_PROVIDER=ib_web_gateway, autostart=True` rejects in the first route gate. `_resolve_provider`, `_apply_env_gateway_overrides`, and the SDK resolver counters remain zero; API attributes and credential conversion are not invoked.
2. Raw API injection to an otherwise explicit `okx` route and raw class injection to an unknown provider reject without touching the injected object.
3. CTP nested in `exchange_kwargs`/`symbol_routes` and CTP selected by `BT_GATEWAY_EXCHANGE_TYPE` reject before SDK/forwarding construction.
4. Unknown and unrelated provider labels cannot be upgraded into actor routes by nested CTP evidence, even when an explicit fake actor port is supplied.
5. Mutating caller-owned nested route maps after Store construction does not retarget the Store. Mutating the Store's private route map or effective backend to CTP/forwarding causes `start`, `_ensure_api_ready`, or the forwarding construction seam to reject before constructing a client.
6. V2 submit/cancel tests reach only the explicitly supplied fake actor port. Corrupt receipt digest and duplicate command id reject without retry/fallback. Actor-only `start`, `autostart`, local legacy methods, SDK queues, SDK client construction, and forwarding construction reject; actor-only `stop()` is inert.

## Test results

- Candidate Store boundary tests + copied default live dispatch guard: **11 passed**.
- Main-tree existing managed Store/execution/live dispatch tests: **30 passed**; pytest emitted the existing unknown `asyncio_default_fixture_loop_scope` option warning.
- `py_compile`: pass.
- Ruff using `D:\source_code\backtrader\pyproject.toml` for candidate Store, copied r4 port, and new tests: pass.

Raw commands and outputs are under `evidence/*-log`; frozen r4 payload checks and AST comparison are recorded in `evidence/upstream-r4-verification.log`.

## Limits and blockers

- The actor port, context, intent digest, and `actor_epoch` can be chosen by the local caller. The digest is unkeyed and the required replay ledger is process-local memory.
- Receipt validation binds one result to one command. It does not make a previous receipt current, does not cache an authorization, and cannot authorize `start()` or another command. The r4 state enum contains `QUEUED`, `UNKNOWN`, and `REJECTED`, not an authorization state. The r4 port contract has no fresh authorization/version query; a future service must revalidate authoritative current session/actor epoch on every action. This candidate does not consume a local stale `AUTHORIZED` receipt because it has no such state.
- No current external actor identity, cryptographic receipt, authoritative session/epoch lookup, current per-action reauthorization, durable replay store, account-wide cross-host fence, common provider snapshot, callback/read feed, or handoff is implemented.
- The candidate deliberately rejects raw injected clients and generic/unknown selectors. This narrows historical Store compatibility and requires separate design review before merging.
- `backtrader_runtime` registration/CLI is unchanged, so this candidate exposes no default CTP route. `start()` stays unavailable for the actor slice until the same-session read/callback feed contract exists.
- No provider, credentials, CTP/native API, network, real broker, or real gateway was used. No real action or production acceptance was tested.

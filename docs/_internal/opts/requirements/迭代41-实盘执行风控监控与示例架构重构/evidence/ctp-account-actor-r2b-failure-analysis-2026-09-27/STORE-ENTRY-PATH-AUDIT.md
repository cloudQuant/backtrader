# r2b Store public-entry path audit

**Scope:** read-only static call-path review of the r2b candidate and main-tree `btapistore.py`. No candidate or main source edits, imports, tests, SDK/native access, private config reads, or network activity. This is a path inventory, not a runtime gate or security acceptance.

## Source identities

| Source | SHA-256 |
|---|---|
| `D:\temp\iteration41-ctp-account-actor-main-store-wiring-candidate-20260927-r2b\backtrader\stores\btapistore.py` | `24F8199E199BBE84BBB113C3EDBBEE9E71D4736FDD8573297E24EAD3298F2518` |
| `D:\source_code\backtrader\backtrader\stores\btapistore.py` | `DBA2989252DB76FE010FBEE7CAACDCDBA34A9B951E3702724156482B67FAE826` |

## Candidate paths that a deferred CTP gate must cover

- **Construction and connection:** constructor and early CTP classification are at 3634, 3689–3705; actor-only setup is 3767–3819 and rejects `autostart=True` at 3805–3806. A normal constructor with `autostart=True` calls `start()` at 4118. `start()` (4707) calls `_ensure_api_ready()` (4761); the bounded metadata probe also calls `start()` at 4972. `_ensure_api_ready()` (16870) resolves/constructs the local client at 16921–16940, connects/starts it at 16962–16966, then calls `get_balance()` at 17001. Public account, position, readiness, metadata, settlement, and baseline reads also reach `_ensure_api_ready()`.
- **Submit and cancel:** `submit_order()` (8139) can use a managed adapter or `_submit_order_legacy()` (8348); managed CTP dispatch is at 8205. `enqueue_order()` (7570) reaches `_enqueue_order_command()` (7636), which calls `_ensure_api_ready()` at 7662. Cancel paths are `cancel_order()` (8436), `cancel_order_ref()` (8523), `_cancel_managed()` (8537), `_cancel_order_ref_legacy()` (8689), and public `enqueue_cancel()` (7731; ensure at 7748). Queued SDK dispatch maps submit/cancel to `async_make_order`/`async_cancel_order` in `_invoke_sdk_command()` (7054–7077); static review found no route recheck there after queueing.
- **Other controls:** query/reconcile/recovery/risk queue entrypoints include `enqueue_query()` 7873, `enqueue_reconcile()` 7891, `enqueue_ctp_reconciliation()` 7901, recovery completion 7920, and risk refresh 8053. Additional execution/settlement controls are `arm_registered_sim_execution()` 8476, settlement prepare/verify 12030/12091, authorization configuration 13386, recovery prepare/abort/arm/cancel/complete 13513/13606/13699/13762/13827, `arm_sdk_execution()` 13940, and `initialize_account_risk_baseline()` 15359.
- **Close and API access:** Store shutdown is `stop()` (5731), which may call the local API's `disconnect()`/`stop()` at 5826–5829. `sdk_api` (4160–4168) returns the underlying API object, so Store entry checks cannot constrain methods invoked through that object.
- **Direct CTP wrapper:** `_resolve_bt_api_client()`/`_create_ctp_wrapper_class()` are at 1930–1980; direct `connect()` creates and starts MD/Trader clients (2120–2186), `start/stop` delegate to connect/disconnect (2188–2204), and order methods are `submit_order/create_order/cancel_order` (2708, 2801, 2805). Native insert/action helpers retain a raw API fallback when the typed capability is absent (2104–2118).
- **Gateway wrapper:** `_create_ctp_gateway_wrapper_class()` is at 3243. `submit_order/create_order/cancel_order` are 3495–3532 and call the attached route guard. `connect/start/disconnect/stop` at 3281–3295 do not. The Store attaches the guard only to its default-created gateway wrapper (16926–16938), after constructor entry; `_ensure_api_ready()` checks route before constructing it.

## Main-tree comparison

The main Store exposes `start/stop` at 4297/5315, enqueue submit/cancel at 7151/7309, submit/cancel at 7714/7991/8062, and `_ensure_api_ready()` at 16395. Static search found no `_candidate_require_route`, `_candidate_actor_only`, or gateway `_store_route_guard` equivalents in the main file; its local CTP API path remains reachable through Store start/ensure and the wrapper methods.

## Minimum fake probes for r2c

1. Use trap `api`/`api_cls` and GatewayClient fakes with counters for construct, connect/start, balance/position queries, submit/cancel, arm/settlement, disconnect/stop. Cover CTP from provider, config/API kwargs, and route environment; also `autostart=True`, Store `start()`, first read, and `sdk_api` access. Assert rejection before local construction, connection, or write.
2. Cover every public path above, especially direct `enqueue_order/cancel`, settlement confirmation, recovery cancellation, and the gateway wrapper lifecycle methods. Verify actor-only construction keeps local `_api` absent and only dispatches typed intents through its explicitly injected port; its local fake ledger is not external actor authority.
3. Pause the fake command worker after enqueue, mutate route inputs before dispatch, then prove `_invoke_sdk_command` revalidates the sealed route before calling the SDK async submit/cancel method. A submit-entry-only gate or enqueue-time check does not close this asynchronous path.

**Conclusion:** Moving only the constructor rejection to `submit_order`/`cancel_order` is insufficient. The smallest safe gate surface must include local client construction/connect (`start` and `_ensure_api_ready` before any API work), every direct and queued submit/cancel/control path, worker dispatch, lifecycle close, and any exposed underlying API/wrapper path. If those routes are not supported, keep the CTP route fail-closed before local API creation.

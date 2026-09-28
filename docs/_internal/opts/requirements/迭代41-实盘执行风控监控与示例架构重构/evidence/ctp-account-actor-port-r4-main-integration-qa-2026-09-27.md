# CTP AccountActorPort r4 — independent candidate QA and main Store call-surface audit

Date: 2026-09-27. This evidence contains static source review and offline fake-only tests; no real Store, SDK, native call, provider, credential, network, private config, or account was accessed.

## Frozen input and isolated test

- Frozen candidate: `D:\temp\iteration41-ctp-account-actor-port-freeze-20260927-r4`
- Frozen manifest SHA-256: `8f793cc85754f6fa447925bd0ad40570dd7f10480773f45500b56fd0933591a8`
- Independent source copy: `D:\temp\iteration41-ctp-account-actor-port-r4-qa-independent-20260927`; all 9 manifest-listed payload files matched exact size and SHA-256 (`payload-verification.json`). Module origins resolve to that copy (`module-origins.txt`).
- Independent focus: `python -B -m unittest discover -s tests -v` → 34 passed, 0 failed, exit 0. Raw stdout/stderr and exit marker are preserved in the raw packet.
- Independent packet manifest SHA-256: `4ed88a1708a889565dc960dead22c0155a6cef0d2e98ef65c68ae033d96733a7`.

Supplemental fake-only probes show: missing actor rejects before credential/API/gateway factories; stale epoch/account mismatches against the local expected context reject before actor call; duplicate command ID is claimed once. Caller-supplied, self-consistent `actor_context` and intent values with epoch 999 or an arbitrary account reference are accepted by the fake actor. This is the candidate's documented authority limit: values are unauthenticated local expectations, digest is unkeyed, replay ledger is in-memory.

A new candidate-local route snapshot issue was reproduced: `StoreRouteDescriptor` is frozen only shallowly. A harness classified as `NON_CTP` for an OKX config retains that classification after the underlying config dict is mutated to CTP, and its fake legacy path remains callable. This is not a demonstrated main-Store bypass; the candidate is not wired into the main Store. It must be fixed or sealed before integration.

The candidate exposes no callback inbox or callback replay API; the tested replay control is only duplicate command-ID rejection in one process.

## Main Store static call-surface

Reviewed `backtrader/stores/btapistore.py`, SHA-256 `DBA2989252DB76FE010FBEE7CAACDCDBA34A9B951E3702724156482B67FAE826`. No AccountActorPort integration symbol was found in `backtrader/` or `backtrader_runtime/`.

| Surface | Source facts |
| --- | --- |
| Provider resolution and constructor ordering | `_resolve_provider` at 3768–72 can replace requested `ctp` from `BT_STORE_PROVIDER`; it runs from `__init__` at 3500. `_resolve_backend` at 3435 accepts `forwarding`. `__init__` reads injected `api.exchange_kwargs` at 3538 and may autostart at 3765–66. |
| Public submit/cancel | `submit_order` at 7714–27 calls `_submit_order_legacy` when no managed adapter. `cancel_order` at 7991–8008 and `cancel_order_ref` at 8062–68 do the same. |
| Legacy direct calls | `_submit_order_legacy` at 7906–14 and `_cancel_order_ref_legacy` at 8219–27 reject CTP only when a managed adapter is already attached and `_is_ctp_session_provider()` is true; otherwise they can instantiate and use the local API. |
| Generic SDK queue | `enqueue_order` at 7151–58 and `enqueue_cancel` at 7309–18 reject only the managed CTP case. Worker dispatch `_invoke_sdk_command` at 6635–49 calls `async_make_order` / `async_cancel_order`. |
| Forwarding path | `_is_ctp_session_provider` at 8363–65 returns false for every forwarding backend. `_ensure_api_ready` at 16395–16421 creates the forwarding client for that backend; `_create_forwarding_client` starts at 16541 and passes the configured exchange through. Static example: CTP plus forwarding is not caught by the CTP-specific adapter predicates. No forwarding request was made. |
| Direct CTP SDK path | `CtpClientWrapper._send_native_order_insert/_action` at 1933–49 uses the typed gate only if both method and capability exist; fallback calls raw `ReqOrderInsert` / `ReqOrderAction`. |
| Old gateway path | CTP gateway wrapper creation starts at 3074; wrapper `submit_order` at 3318 and `cancel_order` at 3343 forward to `GatewayClient`. |

These source paths prove only that legacy dispatch callsites remain reachable in source absent a new preconstruction actor gate. This review did not instantiate BtApiStore or establish runtime/deployment reachability of any particular caller configuration.

## Required fail-closed integration tests

1. Gate raw requested selectors before environment rewriting, private credential reads, injected API getter access, SDK/gateway imports, construction, autostart, or connect. Missing actor must leave every such counter at zero.
2. Cover direct CTP, CTP gateway, generic gateway default CTP, `btapi` CTP exchange kwargs and nested routes, CTP forwarding, environment downgrade, unknown/ambiguous providers, and raw `api` / `api_cls` injection.
3. Exercise all public and private submit/cancel aliases, generic queue entrypoints and worker dispatch, direct CTP raw sender fallback, and old gateway wrapper. Assert no local fallback, queue publish, SDK call, or `Req*` invocation when actor admission is absent or rejected.
4. Bind typed intents to authoritative sealed account/config/session/epoch facts (not caller-selected context). Receipt, request identity, idempotency, and current actor epoch need a durable authenticated external contract; local matching alone is insufficient.
5. Make route selectors immutable snapshots or revalidate them before dispatch; add a test for post-construction nested config mutation.

## Result boundary

Accepted: the frozen r4 offline candidate's narrow local test result only (34/34), with the route-mutation issue and expected authority limitations recorded. Not accepted: main Store integration, durable/authenticated actor authority, callback deduplication, external account fencing, CTP/provider execution, G6-P, or live operation. Default routing and production code were not changed.

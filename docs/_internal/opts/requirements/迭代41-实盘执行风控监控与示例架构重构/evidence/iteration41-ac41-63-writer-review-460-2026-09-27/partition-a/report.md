# AC41-63 static writer review — partition A

- Inventory SHA-256: 03658257D97E31C2D8F8BFD48685441533552B32674F5D63810141E3038AB456
- Assigned indices: 0–120 inclusive (121 candidates)
- Mode: source-only; no provider/native/network execution
- Every candidate remains REVIEW_REQUIRED / NOT_AVAILABLE.

## High-priority finding: mutable CTP gateway wrapper gate

A-019 through A-021 are CtpGatewayClientWrapper.submit_order/create_order/cancel_order in backtrader/stores/btapistore.py.

1. Constructor classification sets _direct_ctp_writes_disabled=True for CTP: Store marker/provider decision at 3055–3075, CTP/non-CTP test at 3077–3089. BtApiStore creates this wrapper and passes its CTP-session marker at 16500–16510.
2. Guard at 3321–3326 checks only the mutable instance field. The direct wrapper methods then invoke _client.submit_order/cancel_order at 3328–3366.
3. _client returns _gateway_client or lazily constructs GatewayClient from _kwargs at 3101–3105.
4. BtApiStore retains its API object in private self._api (assignment at 3518). Public sdk_api returns None for gateway/forwarding or CTP at 3820–3828, but the private raw object remains accessible in the same process. A caller with store._api can clear _direct_ctp_writes_disabled and invoke the wrapper directly.
5. Store-owned CTP paths have separate current fail-close checks: submit_order at 7753–7758; managed CTP submit at 7800–7804; legacy submit at 7943–7954; cancel_order at 8021–8043; legacy cancellation at 8218–8228. A raw-wrapper call bypasses those Store methods.

### Default registration reachability

This private/reflection path is not part of the reviewed default bt-runtime CTP writer route. Current registered 013_3 managed execution is simulation/replay with a local fake provider and socket denial (managed_013_3.py:1–9); the 013_3 private CTP binding is read-only. Normal Store CTP order methods remain fail-closed. The residual requires custom same-process code with a private/reflection handle or explicit low-level wrapper construction.

### Isolated source reproduction

source_fake_sink_probe.py parses current source with Python AST, extracts only actual wrapper constructor/guard/_client/write method nodes, and invokes those methods on an isolated object with a local recording fake. It imports no Backtrader/provider/native module and performs no network or native call. It confirms CTP construction sets the field true and leaves the real client lazy; all three methods reject while true; after setting the mutable flag false, the fake records submit, create-through-submit, and cancel sink calls. This demonstrates conditional current-source control flow only, not real provider behavior. See source_fake_sink_probe-result.json.

## Other conditional routes and gaps

- A-002/A-003: BtApiBroker shutdown/reconciliation generates reduce-only close orders through self.buy/self.sell. Custom broker/store composition; Store CTP guards apply, while non-CTP/custom providers can dispatch.
- A-004/A-005/A-006: broker submit/cancel and remote-open-order reconciliation invoke self.store methods. A-006 uses hasattr then a dynamically resolved cancel_order_ref. Default runtime does not construct this provider Broker; Store CTP legacy routes reject, while custom Stores/non-CTP providers can dispatch.
- A-018: legacy CtpClientWrapper create_order routes into submit_order, but native insert/action helpers unconditionally raise at 1896–1917, 2507–2602, and 2604–2645. Current source also rejects direct registered-sim arming.
- A-022–A-026: Store managed/legacy routes use injected adapters and provider methods. CTP direct submit and legacy cancel reject; managed CTP submit says native Store writes are closed. Typed CTP cancellation queue remains a separate unaccepted candidate, with no default runner command channel.
- A-027–A-034: exact managed_013_3 replay registration uses local fake provider only and denies sockets. These real framework buy/cancel calls do not reach external order methods.
- A-035–A-040: registered mechanical fixture routes through a fake broker/provider. MechanicalCycle checks _require_dispatch_authority before dynamic buy/sell lookup at mechanical_cycle.py:232–261. Current project notes say the registered fake L2 positive acceptance remains unverified; same-process custom broker calls are not sandboxed.
- A-091–A-095: cleanup calls are in CtpManagedAccountRuntimeCandidate. Its start path can compose a CTP session through injected client/lifecycle ports at ctp_managed_account_runtime_candidate.py:308–412. The module is explicitly unregistered and documents the missing external service-owned fence/final native-handle boundary at lines 1–8 and 117–126. Keep unaccepted.
- A-115–A-120: cleanup forwards through the unregistered shared CTP/SimNow managed execution composition. The underlying SimNow root can own an explicitly injected managed execution session, but the module documents no CLI registration/default provider client; these candidate lines are close/cleanup, not order dispatch.

## Lower-risk remainder

A-000/A-001, A-007, A-010–A-017 are local backtest, matching, or ledger operations. A-041–A-120 are descriptor, stream, local lease, SQLite, read-only probe, config setup, or diagnostic cleanup; A-059/A-060 are the isolated local fake actor harness. A-115–A-120 specifically close an unregistered managed CTP execution-session composition. Exact source line and hash for every candidate appear in writer-review-a.json.

## Limits

This artifact covers only inventory indices 0–120. It does not close the full inventory, certify writer closure, prove real provider behavior, authorize any route, or change NO_WRITE / LIVE_NO_GO.

### AST fake-sink result

{
  "backtrader_or_provider_imported": false,
  "constructor_exchange_type": "CTP",
  "constructor_sets_direct_writes_disabled": true,
  "fake_sink_calls_after_clearing_mutable_flag": [
    "submit_order",
    "submit_order",
    "cancel_order"
  ],
  "gateway_client_remains_lazy_at_ctp_construction": true,
  "interpretation": "Conditional reachability of current extracted wrapper methods only; no real provider/native/network behavior or default runtime reachability established.",
  "method_nodes_extracted_from_current_source": [
    "__init__",
    "_client",
    "_ensure_direct_writes_allowed",
    "_is_supported_non_ctp_exchange",
    "cancel_order",
    "create_order",
    "submit_order"
  ],
  "native_or_network_call_performed": false,
  "operations_rejected_before_fake_sink_with_default_flag": [
    "submit_order",
    "create_order",
    "cancel_order"
  ],
  "source_sha256": "A0393FC4F0B7212C6EE4B4F32DE2AA9E6E9A0ECFC5FE976F72160E2EC11F6ABE"
}

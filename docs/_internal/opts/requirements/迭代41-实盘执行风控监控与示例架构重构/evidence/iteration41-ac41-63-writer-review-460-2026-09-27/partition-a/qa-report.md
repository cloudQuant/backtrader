# Independent QA — AC41-63 writer inventory partition A

- Result: **PASS for static partition integrity and the bounded fake-sink probe**.
- Candidate range: A-000–A-120 (121 records), matched in order against `writer_candidates[0:121]` from the current inventory.
- Inventory SHA-256: `03658257D97E31C2D8F8BFD48685441533552B32674F5D63810141E3038AB456`.
- Author artifact SHA-256: `134EAD5F01D73F99BC705E356562AA3607A84DDF3F2B2901981E3A884A21B2E5`.
- Source-map verification: all 30 distinct source files matched the artifact hash map; all 121 candidate hashes and exact line text matched current source.
- Dispositions: all 121 remain `REVIEW_REQUIRED / NOT_AVAILABLE`.

## A-019–A-021

The current CTP gateway wrapper constructor sets `_direct_ctp_writes_disabled` for the Store-marked CTP session. The direct wrapper methods check only that mutable instance field before calling their client sink. `BtApiStore` assigns its client to private `self._api`; its public `sdk_api` property hides that raw value for gateway/forwarding/CTP backends. The default gateway factory path passes the Store CTP marker. Store-owned direct CTP submit/cancel methods retain separate fail-closed guards.

The independent AST probe extracted the current wrapper methods and used a local recording fake. All three operations rejected before the fake sink with the default CTP flag. After the probe deliberately mutated the ordinary flag to `False`, submit, create-through-submit, and cancel reached the fake sink. No Backtrader/provider module, native code, network, credentials, or private configuration was used. This confirms a conditional same-process mutation path through the low-level wrapper; it does not establish real provider behavior or default registered route reachability.

The registered 013_3 CTP binding is explicitly read-only. Its separate managed replay fixture is marked `offline_managed_execution`, routes through a local fake provider, and documents socket denial. The shared CTP managed runtime is absent from the default runtime inventory. These registration facts distinguish the conditional raw-wrapper residual from the reviewed default route.

## A-115–A-120

All six exact inventory locators are `close` calls. They forward cleanup through `CtpSharedManagedRuntime` and `CtpSimNowManagedRuntime` or close a runtime during unwind. Both managed roots document unregistered status and use explicitly supplied adapters/dependencies; the SimNow runtime can own an execution session when deliberately composed. The accurate classification is therefore cleanup in an unregistered, potentially execution-capable composition—not a read-only route. These candidate lines themselves do not dispatch orders or cancels.

## Limits

This review checks only indices 0–120. It does not establish full writer closure, account isolation, real provider behavior, or route authorization. Official dispositions and `NO_WRITE / LIVE_NO_GO` remain unchanged. All source inspection was static; the sole dynamic check was the AST-extracted local fake sink described above.

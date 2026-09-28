# External CTP Account Actor Port — offline candidate r4

This independent candidate models a fail-closed composition boundary, a small code-owned provider registry, and a locally checked V2 intent/receipt binding. It does not edit or import the main Backtrader package, does not implement a remote service, and must not be treated as a CTP write route. Unknown providers, ambiguous gateway selectors, and all raw `api`/`api_cls` injection are rejected without introspection.

Run the isolated fake harness with:

    python -m unittest discover -s tests -v

The required result is zero API-class/gateway construction, connect, or ReqOrderInsert/ReqOrderAction calls for missing/default actor routes. The tests also cover CTP environment-downgrade attempts, nested route maps, unknown providers, and injected API objects with trap properties. `ActorCommandContextV1`, `CtpSubmitIntentV2`, `CtpCancelIntentV2`, `ActorCommandReceiptV2`, and `FakeLocalActorReplayLedger` exercise exact local binding and one-shot behavior. These are test contracts, not authenticated or durable external authority.

See INTEGRATION_CONTRACT.md for the precise main Store call points, existing seam differences, and public-compatibility limitations.

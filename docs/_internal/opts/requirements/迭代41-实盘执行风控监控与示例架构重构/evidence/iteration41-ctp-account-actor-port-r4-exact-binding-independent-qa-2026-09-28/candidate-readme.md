# External CTP Account Actor Port — offline candidate r4

This independent candidate models a fail-closed composition boundary, a small code-owned provider registry, and locally checked intent/receipt bindings. It does not edit or import the main Backtrader package, implement a remote service, or enable a CTP write route. Unknown providers, ambiguous gateway selectors, and raw API/API-class injection remain rejected without client introspection.

Run the isolated fake harness with:

    python -B -m unittest discover -s tests -v

The tests cover nested CTP routing, unknown providers, environment downgrade attempts, and trap properties on injected clients. Stale account/epoch intents and replay IDs stop before the fake actor call. Returned receipts are checked before an optional downstream fake sink can consume them; a bad receipt is necessarily detected after the actor-port response. These are local test contracts, not authenticated or durable external authority.

See INTEGRATION_CONTRACT.md for the main Store call points, compatibility limits, and authority boundary.

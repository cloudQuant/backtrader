# Store hidden-route candidate: negative QA

**Disposition: NO_MERGE / NO_WRITE / LIVE_NO_GO.** This is local fake-only evidence. It grants no route authority and does not establish account-level writer closure, CTP/provider acceptance, native behavior, or live execution.

## Frozen source and candidate

- Exact Store preimage: SHA-256 `CE04ECBADDD3D3EA01C707313EA9B144650C47E322D0BDFC915000C0110094CA` (`backtrader/stores/btapistore.py`, 791,606 bytes; frozen copy and manifest in `D:\temp\ac41-hidden-route-ce04-2fa27cb6263f4ebdb913275843e822f0\preimage`).
- Existing route identity test preimage: SHA-256 `4AD2A69E10B918708D01113C0D2748A692167F96EF481C17A1ED31F57B73C45A`.
- Unmerged isolated candidate Store: SHA-256 `32C72D50A860960BDE0602CA83D9742FA1794C0B5BE047BC80DF25DD5595EA9E`.
- The isolated candidate added a fail-close check only for an empty Store snapshot with no static `exchange_kwargs` and a custom `__getattribute__`. It retained the explicit CTP path's existing direct-dispatch error.

## Fake-only evidence

- Independent QA ran the candidate against the frozen route identity tests and adversarial compatibility probes: **21 passed**, one existing Quandl deprecation warning.
- Those tests denied the original hidden-route/empty-snapshot fake submit and cancel before writer method lookup, while preserving the tested ordinary no-route non-CTP direct sink and explicit CTP rejection behavior.
- Independent QA then found a stronger same-process counterexample: the API's raw instance dictionary and Store snapshot both contain `BINANCE`, but its overridden `__getattribute__('exchange_kwargs')` returns `CTP___TEST`. Under the isolated candidate, both local fake submit and cancel sinks were reached with `CTP___TEST`. The archived `probes/test_snapshot_spoof_counterexample.py` reproduces it; its focused run reported **1 passed** because it asserts the counterexample.
- A blanket rejection of every overridden `__getattribute__` would also reject the existing matching non-CTP `FakeApi` route contract. Calling the override during the write-time check would execute arbitrary caller code and cannot establish a trusted route identity for an in-process mutable object.

## Decision

The candidate closes only the narrower empty-snapshot reproduction and does not close the spoofed-static-snapshot case. There is no safe, compatible route-identity proof for arbitrary injected in-process APIs here. Do not integrate this candidate or describe it as a general hidden-route fix. A stronger fix needs a separate trusted API boundary or explicit product-contract change.

The guarded broad Store subset was not run after the independent counterexample made this candidate unsuitable for integration. No provider, CTP SDK/native module, credentials, or external network was used. The only submit/cancel calls were method invocations on in-memory fake API objects; no provider order or cancel was issued.
# CTP MD subscription request/ACK source audit

**Status: no caller-correlated native request ID is exposed by the current pinned `bt_api_ctp` child.** This is a static source audit only; it is not G6-S acceptance and does not establish provider behavior.

## Scope

Audited the current pinned child source under `D:\bt_api_py\bt_api\bt_api_ctp\src\bt_api_ctp\ctp`, including the 6.7.7 Windows API header and generated SWIG wrapper. The inspected high-level `client.py` SHA-256 is `B61B32F9A2A2E61035BF88BCB7ACF669C8C7EE8E5BF5D7E1F6E375E69F053EAB`.

No private config or credential file was read. No SDK/native module was imported or loaded. No network, provider session, query, or write was invoked. This report describes the pinned child package only; it does not attribute behavior from the older top-level `bt_api_py` package.

## Request and callback surfaces

- The native callback is `CThostFtdcMdSpi::OnRspSubMarketData(pSpecificInstrument, pRspInfo, nRequestID, bIsLast)` in `ctp/api/6.7.7/windows/ThostFtdcMdApi.h:62`. The instrument response row and callback `nRequestID`/`bIsLast` are separate callback arguments.
- The matching native request is `CThostFtdcMdApi::SubscribeMarketData(char *ppInstrumentID[], int nCount)` in the same header at line 135. It accepts the instrument array and count; there is no caller-supplied request ID.
- `ctp/ctp_md_api.py:42-45` forwards the four callback values through SWIG. At `:139-140`, `SubscribeMarketData` forwards only the instrument-list argument.
- Generated `ctp/ctp_wrap.cpp:472904` requires exactly the API object and one Python list. It builds the C array/count and calls native `SubscribeMarketData(arg2, arg3)` at `:472942`; `:472962` converts the native integer return to a Python `int`. This exposes the native integer return value, but these sources do not document it as a caller request ID or an ACK-correlation key.
- The callback wrapper at `ctp/ctp_wrap.cpp:471607` unpacks the API object plus the callback's four native values, and calls the C++ SPI callback at `:471639`. It does not add a caller token.
- High-level `ctp/client.py:1940-1947` submits the full list; `:1949-1984` submits batches. Login-time auto-resubscribe calls `SubscribeMarketData` at `:1703-1704`. `OnRspSubMarketData` at `:1718-1725` checks only that the SPI/API is current, then forwards `(pSpecificInstrument, pRspInfo)`; it discards `nRequestID` and `bIsLast`.

Thus there is no explicit native request-ID echo contract visible in the request API. The callback's `nRequestID` must not be described as matching a caller-chosen subscription ID based on these sources alone. The return value is only an integer status, and the existing high-level wrapper does not retain callback request provenance.

## Generation and stale-callback limitation

`_MdSpi._is_current_locked` (`ctp/client.py:1500-1504`) binds an SPI to the currently installed API/SPI object. `OnFrontConnected` increments the mutable client `_connection_generation` at `:1510-1515`; the `_MdSpi` object is created once per `MdClient.start()` at `:2002` and remains associated with that API. The native callback signature carries no connection generation.

Consequently, a callback delivered by the same current SPI after a reconnect can only observe the client's current generation. Static code cannot prove that the native callback originated in that generation. A local generation captured when handling the callback is not a native callback-generation proof and cannot, by itself, reject every delayed prior-connection ACK.

## Restricted Python-side association option

A future SDK-local contract could mint an opaque local subscription epoch and submit exactly one instrument per call. It would have to enforce one outstanding typed call per instrument, reject collisions with legacy/batched/automatic resubscribe paths, accept an ACK only when its instrument matches the unique pending call and its terminal `bIsLast` is valid, and preserve the native `nRequestID` as an observed field without treating it as caller correlation. Disconnect must revoke the pending epoch. The instrument must not be reused for another typed call while an older native session can still callback; safe reuse requires a proven per-connection SPI/API retirement and completed Join/close.

This would create a **restricted SDK-local association by uniqueness**, not provider-authenticated request identity. The current client does not implement these invariants. Direct access to the private native API would also bypass a high-level guard.

For an actual provider-level request ID, the vendor API would need to accept/return a request token and echo it in the callback, or the vendor must provide a verifiable contract for how callback `nRequestID` is generated and tied to each call. The current header and wrapper expose neither proof. Do not enable readiness on a synthetic local epoch alone.

## Acceptance disposition

No isolated code or test changes were made for this audit because the current native interface has no explicit caller-ID mechanism to test as a positive contract. A local one-symbol serialization test can verify SDK policy, but cannot establish native request-to-ACK identity. G6-S remains closed pending SDK-local uniqueness enforcement and negative tests, lifecycle/generation fencing, and real native verification of callback fields, request behavior, late ACK rejection, and Join/close quiescence. This audit does not enable a route or change any default.


# G6-S settlement attestation candidate

This isolated candidate combines a selected SimNow scope, a current read-only
TD session snapshot, one current-day settlement-confirmation row, and a typed
injected query-provenance receipt. It makes no filesystem access, SDK import,
network call, native call, credential read, or write request. It is not
registered or connected to the Backtrader runtime.

The attestation means only that the local contract observed one exact current
account/day confirmation row from a terminal query whose injected verifier
claims same-source seal, retained-history equality, payload digest, and
freshness checks. It records the exact config/registration/pair/account/day/
generation and request ID. Request-counter deltas must show one settlement
query and zero settlement/order/cancel writes. It hard-codes no atomic snapshot,
no external writer fence, no execution-gate arming, and no write authority.
The pair is supplied by the explicit current config selection; this candidate
does not pick a replacement by time or set. A missing current-day row or pair
mismatch rejects with zero write calls. `CurrentTdSession` describes the native
TD connection generation. It does not describe a Windows/OS session or grant a
snapshot authority; those identities and controls remain separate.

## Main-tree integration blocker

The main tree's `ctp_simnow_td_trading_readiness.py` already checks account,
TradingDay, generation, exact selected pair, terminal flags, one matching row,
request counts, and zero settlement/order/cancel writes. However, it trusts
the SDK's promoted `verify_settlement_confirmation()` result and does not
independently verify the result's sealed source, retained query-history result,
record digest, or freshness.

The inspected SDK query source does retain private issuer/source seals and
current query history. But `query_settlement_confirmation_result()` currently
calls `_execute_query()` without `request_filters`; its source therefore does
not bind the submitted `BrokerID`/`InvestorID` values. The seven-query
`CtpNativeQueryCertificateBuilder` explicitly accepts account, positions,
orders, trades, instruments, margin-rate and commission-rate queries, and omits
settlement confirmation. A real verifier integration therefore needs an SDK
source contract change (record exact account filters on the settlement query),
a settlement-aware verifier that checks the exact SDK `QueryResult` type,
source seal, issuer, current retained request/result metadata, record digest,
terminal marker, and freshness, and independent review of that bridge. Until then, this
candidate's verifier is only a typed test seam.

The acceptance matrix remains `LOCAL_OFFLINE_CONTRACTS / NO_WRITE / LIVE_NO_GO`.
ADR-41-16 remains `PROPOSED`; option B is not approved. No test in this folder
is provider, account, F14, operational-attestation, or trading authorization.

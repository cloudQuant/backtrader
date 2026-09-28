# G6-S settlement attestation candidate receipt

**Frozen candidate:** `D:\temp\simnow-settlement-g6s-20260927`  
**Disposition:** `LOCAL_FAKE_ONLY / NO_WRITE / NOT_REGISTERED`  
**Tests:** `python -m pytest -q -p no:cacheprovider .` → **75 passed** in 0.52s on CPython 3.11.5.

## Contract delivered

`settlement_attestation.py` accepts an explicit configured pair, current native TD session scope, a terminal settlement query, request-counter deltas, and a typed injected provenance result. It binds config/registration/pair digest and index, exact MD/TD fronts, exact broker/investor fingerprints, current TradingDay and connection generation. It requires exactly one matching settlement confirmation row, terminal status, exact account filters, same query/session issuer, matching record digest, and injected source-seal/history/terminal/freshness checks. Counter deltas require one settlement read and zero settlement-confirm/order-insert/order-action writes. The receipt hard-codes no execution gate, no write authority, no atomic snapshot, and no external writer fence.

The pair comes from explicit config selection. The candidate has no pair-selection or fallback logic. A missing/unprovable settlement row for the selected official 7×24 pair rejects with zero write counters; it never switches by address, time, or set. `CurrentTdSession` records the native TD connection generation, not the Windows/OS session, and it does not carry snapshot authority.

The explicit correct-looking-row negative is in `test_settlement_attestation.py:295-326`. It rejects missing `request_filters`, unverified source seal, retained-history mismatch, and record-digest mismatch; each case asserts one query and zero settlement/order/cancel writes. Related fail-closed tests cover other account/day, pair/generation, terminal flags, missing/multiple rows, source issuer mismatch, stale evidence, and mutation during verification.

## Exact reviewed source lines

- Main readiness result/counter contract: `backtrader_runtime/ctp_simnow_td_trading_readiness.py:297-346`; query invocation and final state binding: `:399-433`. It validates result status, a single matching account/day row, selected fronts and zero writes, but does not inspect the result's sealed query source, retained result digest, or freshness.
- SDK settlement query: `D:/bt_api_py/bt_api/bt_api_ctp/src/bt_api_ctp/ctp/client.py:6171-6184` sets the native BrokerID/InvestorID but calls `_execute_query()` without `request_filters`; promoted session readiness is `:6186-6248`.
- Seven-query native certificate: `D:/bt_api_py/bt_api/bt_api_ctp/src/bt_api_ctp/containers/ctp/ctp_native_query_certificate.py:34-42,250-304,659-665` excludes settlement confirmation.

## Limits

The candidate's verifier is a fake-only seam, not an SDK integration. A reviewed settlement-aware SDK verifier still needs exact request filters recorded in the source plus exact SDK result/source seal, issuer, current retained result, record digest, terminal callback, and freshness verification. The inspected SDK source checkout was dirty at `d3674e19`; these hashes identify the inspected files but do not constitute a release pin.

The matrix remains `LOCAL_OFFLINE_CONTRACTS / NO_WRITE / LIVE_NO_GO`. The 7×24 environment is documented as lacking settlement service. ADR-41-16 option B remains proposed and unapproved. Strict F14 still lacks an accepted external account writer fence and coherent shared snapshot. This candidate does not advance G6-S/G7-S acceptance. No provider, native, credential, protected-config, or network access occurred; no main-tree production files were changed.

`manifest.json` SHA-256: `126ace8778f4c679a491f3a76c8bbccd6f13bc3503dffa2848445829b6a88dc1`

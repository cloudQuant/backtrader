# G6-S settlement consumer contract candidate (2026-09-27)

**Disposition: `FAKE_ONLY / NO_RELEASE / G6-S CLOSED / G7-S CLOSED`.** This is an isolated, unregistered consumer-contract overlay. No production source, default inventory, CLI, pin, or route was modified. It makes no provider-origin claim and grants no trading/write authority.

## Candidate change

`ctp_simnow_settlement_consumer.py` defines a typed expected scope, an injected `CtpSimNowSettlementAttestor` protocol, a source-query attestation, and `consume_current_settlement_readiness()`. Missing attestor rejects by default. A returned attestation must bind all of the following before the consumer emits a shape-only receipt:

- exact selected MD/TD pair and exact account, bound to the existing `CtpSimNowNativeReadiness` and `CtpSimNowManagedScopeSelection`;
- exact disposable `bt_api_ctp` probe identity: version `2.0.4+g4r2.settlement.probe.20260927`, wheel SHA-256 `857b06c914cfc4f58bc04a77f11b77ad5dc3c47dc2be4d9d18b8e2fc805b264d`, and clean G4-r2 settlement source-manifest SHA-256 `da9d20d35d0b5680267f1a95c5b7fff54f25e9f57f0dfda270b55eb7f251ebe9`;
- terminal `settlement_confirmation` request, exact BrokerID/InvestorID request intent and native filter getter readback, no explicit extra filters, query-source seal/history digests, callback source `OnRspQrySettlementInfoConfirm`, and terminal callback digests;
- same current account, connection generation, and SDK-session TradingDay for the query source and current session; exactly one account-matching confirmation row whose **ConfirmDate** equals that TradingDay.

CTP's `CThostFtdcSettlementInfoConfirmField` carries `ConfirmDate`; it does not carry `TradingDay`. The candidate therefore requires TradingDay from the current SDK query/session scope and compares the distinct `ConfirmDate` row field to it. If an optional row `TradingDay` happens to be present, it must also match.

The only successful case is synthetic. Its receipt sets `provider_source_trusted=false` and `execution_authorized=false`. The consumer has no writer API, performs no pair selection, and never falls back by date, set label, or reachability. It consumes only the already selected pair; absent exact attestation must be treated as zero write. Snapshot consistency and OS/account-session writer exclusion are separate and remain unproved.

## Main-source finding

The isolated source snapshots and their hashes are in `input-snapshots/` and `source-inputs.json`.

- Main `backtrader_runtime/ctp_simnow_managed_runtime.py`: `CtpSimNowNativeReadiness` (lines 232–275) is TD/MD-only and its `td_trading_ready` is always false. `_require_current_td_trading_readiness` (lines 398–497) checks a promoted SDK readiness/result and public state (`settlement_proof_source`, `settlement_readback_verified`, request count, day/generation), but does not consume the settlement helper's source-sealed query evidence or bind it to an exact installed SDK wheel/source pin.
- Main `backtrader_runtime/ctp_simnow_native_readiness.py`: the success return at lines 607–615 proves TD/MD startup only; it does not issue or consume settlement confirmation evidence. The native-start adapter remains unchanged.
- Main `backtrader_runtime/ctp_simulation_query_evidence.py` provides provenance validation for its existing query set; this candidate does not extend its query kinds or certificate builder.

This module is **not wired** into `open_ctp_simnow_managed_runtime`, default inventory, or CLI. Therefore the existing promoted-result trust gap remains open. Use of the candidate function would make this settlement consumer boundary reject unless its exact injected contract is present; it does not change current runtime behavior by itself.

## SDK lineage distinction

The inspected clean G4-r2 source-a `client.py` already supplies `request_filter_field=field` and `request_intent_filters=intent_filters` to settlement query execution (`query_settlement_confirmation_result`, lines 8021–8051); `_execute_query` reads native filter getters before submission (lines 7491–7547). The no-filter finding was specific to the separate dirty `d3674e19` checkout and does **not** apply to clean G4-r2 source-a. The clean source candidate is the one represented by source manifest `DA9D20D35D0B5680267F1A95C5B7FFF54F25E9F57F0DFDA270B55EB7F251EBE9`; the unified-wheelhouse probe wheel has the distinct exact hash listed above.

The clean G4-r2 `CtpSettlementConfirmationEvidence` exposes terminal/result, account, generation, TradingDay, filter-name/hash, callback-record/history digests, row count, ConfirmDate, and an in-process evidence digest. It does not expose the callback source name, selected-pair binding, exact wheel/source pin, or an attestor-issued runtime pin seal. The query history digest is in-process evidence, not a durable provider-origin proof. The candidate's extra fields are a future consumer contract; no real SDK adapter here issues them.

## Verification

Run from the frozen candidate directory with the wheelhouse disposable consumer interpreter:

```powershell
& 'D:\temp\iteration41-unified-offline-wheelhouse-settlement-20260927-r1\consumer-venv\Scripts\python.exe' -m pytest -q -p no:cacheprovider 'D:\temp\iteration41-g6s-settlement-consumer-contract-candidate-20260927\tests\test_ctp_simnow_settlement_consumer.py'
```

Result: **35 passed**. The raw pytest output and exit status are frozen beside the candidate. Tests are pure fake/offline; import guard confirms no `bt_api_ctp` or `_ctp` module was loaded. The fake cases include a correct-looking ConfirmDate/account row with omitted filter readback/source/history evidence; that case rejects. No credentials, private config, native library, provider, network, order, cancel, or settlement-confirmation write was used.

This is an interface/consumer contract only. The SDK producer must bind callback source + source seal/history to the exact installed pinned artifact, and the managed-runtime caller must pass that verifier through the same selected-pair/session scope before any TD trading-readiness promotion. Independent review is pending.



`source-inputs.json` records the read-only provenance references. `source-snapshot-verification.json` confirms all 9 included source, manifest, and lock snapshots match their originals byte-for-byte. `candidate-manifest.json` and `candidate-evidence.zip` are produced by `freeze_candidate.py`; generated cache files are excluded.

The shared main worktree reported the three inspected runtime files as untracked at candidate capture (`evidence/main-source-git-status.txt`). Their frozen snapshots matched the observed source bytes; this candidate wrote only under the isolated D:\temp directory and does not infer who created those pre-existing untracked files.
`source-reference-verification.json` reports 10/10 external read-only references still match their recorded hashes at freeze time, including the exact disposable wheel.

# G4-r2 settlement query evidence candidate

Status: isolated SDK source/fake-only candidate. This is not a wheel, production admission, settlement readiness approval, or native/provider acceptance. G4 remains closed.

## Lineage

The candidate was copied from G4-r2 disposable probe `D:\temp\iteration41-g4-lifecycle-r2-repro-probe-20260927\source-a`, based on clean SDK repository `D:\q\e` HEAD `29f8ff171f61a71038328a7067e0909bf44774b2`. The probe source manifest SHA-256 is `10AA5DAE8464DCCCFF6AC831FF7E6E63106EFEF6ADCAE81C00EAC38618D45B9A`; its frozen evidence manifest SHA-256 is `D579EF460D9FD1B9E03364F7E96F9C58CF1AFC78B72EAA326BCB7225829C9DC7`. The G4-r2 source-a `client.py` is SHA-256 `C217BE3E064272327535DA7EDF4B4ED4D587845F03AA11C4669699417C14E6FF` and is unchanged here. The added evidence builder uses existing G4-r2 query request-field readback; it does not edit the client lifecycle or query methods.

Three candidate changes are in scope: `src/bt_api_ctp/containers/ctp/ctp_native_query_certificate.py`, top-level `src/bt_api_ctp/__init__.py` exports, and `tests/test_ctp_settlement_query_evidence.py`. The candidate package metadata and default pins were not changed. No wheel was built.

## Settlement evidence contract

`CtpSettlementConfirmationEvidenceBuilder` accepts only a typed, successful, terminal `settlement_confirmation` result with a current SDK-issued query source. It requires request intent and actual native getter readback to be exactly the bound BrokerID/InvestorID pair, no explicit or typed parameter filters, current request/source/history readback equality, unchanged session/account/generation/trading-day scope, and exactly one matching native row. The row must match BrokerID, InvestorID, and `ConfirmDate` to the query source TradingDay; if a row provides TradingDay, it must also match. Missing date/identity, multiple rows, late callbacks, stale or changed source, request mismatch, submit error, and incomplete results fail closed. The digest-only evidence says `execution_authorized: false`; raw account strings and rows are not returned.

The generated request/response struct surface is statically checked in tests. The response row's supported date is `ConfirmDate`; TradingDay comes from the sealed query source, not a synthesized response field. Existing `CtpNativeQueryCertificateBuilder` still requires its original seven query types and does not include settlement confirmation.

## Source-lineage correction

The earlier missing-filter observation belongs to dirty checkout `D:\bt_api_py` HEAD `d3674e19a11b9f35f19ae756899bcf18854c8c46`, CTP submodule HEAD `ce1edd60785eb4c66fefa16a994a66946a1e068f`, not this G4-r2 source-a. Dirty `client.py` SHA-256 is `B61B32F9A2A2E61035BF88BCB7ACF669C8C7EE8E5BF5D7E1F6E375E69F053EAB`; there, `query_settlement_confirmation_result` at lines 6171-6184 calls `_execute_query` without `request_filter_field` or request filters, and `_execute_query` at lines 5753 onward only accepts caller `request_filters`. Dirty certificate SHA-256 is `A76E4E1245E84C782FFB9A92B4A804C377FC58C7F3672FD33265E3260E059FBE` and its required seven-query list excludes settlement.

By contrast, this candidate's unchanged G4-r2 `client.py` defines `query_settlement_confirmation_result` at lines 8021-8051 and passes both `request_filter_field=field` and `request_intent_filters=intent_filters` (8049-8050). `_execute_query` at lines 7491-7547 reads native request getters before submit and records actual filters separately from intent; the generic settlement callback entry is `OnRspQrySettlementInfoConfirm` at line 4019. Thus this candidate does not claim to repair that dirty-checkout gap; it adds a separate evidence verifier over G4-r2's existing source seam.

## Verification and limitations

Focused fake suite: 48 passed, 2 warnings (unknown pytest asyncio config option; expected fallback warning because this interpreter has no matching Windows `_ctp` extension). `sitecustomize.py` at the G4 probe's native guard blocks `_ctp`; the guard log records two blocked imports during pytest. A separate origin smoke resolved the package and evidence module from this candidate `src`, with `_ctp` absent from `sys.modules`.

Static checks: `py_compile` passed; Ruff 0.16.2 passed on the three touched files; Black check passed using the host executable (it reports version 0.0) on the new test and top-level export file. Black was not run on the existing large certificate module because whole-file formatting would rewrite unrelated baseline lines. No live CTP API, provider, account, credential, network, or order was used.

This is SDK-side evidence only. The main readiness validator at `D:\source_code\backtrader\backtrader_runtime\ctp_simnow_td_trading_readiness.py` is unchanged and does not consume this evidence type or independently verify sealed query history/freshness. No main readiness gate, G2/G6-S acceptance, default route, or real native settlement verification is claimed.


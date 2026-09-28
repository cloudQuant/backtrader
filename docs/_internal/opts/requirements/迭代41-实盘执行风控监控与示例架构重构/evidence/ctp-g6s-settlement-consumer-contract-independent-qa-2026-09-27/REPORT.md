# Independent QA: G6-S settlement consumer contract

**Disposition: `PARTIAL_CONSUMER_CONTRACT_ONLY / G6-S CLOSED / G7-S CLOSED`.** The exact candidate freeze was reproduced and its focused suite passed. The candidate remains an unregistered, injected-attestor shape consumer. Independent probes found that two boolean fields pass integer/value checks and can produce `consumer_contract_satisfied=true`; the receipt still correctly hard-codes `provider_source_trusted=false` and `execution_authorized=false`. This strict-input gap should be corrected before relying on the consumer receipt even as a complete shape contract.

## Frozen artifact verification

- Candidate directory: `D:\temp\iteration41-g6s-settlement-consumer-contract-candidate-20260927`.
- Candidate manifest SHA-256: `d39dbfa40185bd8f12704cd158c59a35d6737ef6a8d58d0a0aa165a144128486` (matched).
- Candidate ZIP SHA-256: `9f4e2f169384c56dd2b95e755074c4035684c0140946d7dba623114c1236e8bb` (matched).
- Independent verifier run from the extracted QA copy: all checks passed; 24 payload entries, 26 ZIP members, CRC okay, 9 source snapshots and 10 source references matched their recorded hashes.

## Independent tests

The frozen 35-test target passed from the extracted copy: `35 passed in 1.69s`. A startup `sitecustomize` import hook blocked `bt_api_ctp` and `_ctp`; the hook was active, no forbidden module was loaded, and the candidate's own import-guard test passed. The test fixture temporarily disables the private-config ACL validator only for generated `tmp_path` synthetic config. No protected/private config was opened.

A separate QA-only adversarial target passed 21 checks. It confirmed rejection for missing attestor/request-filter readback, wrong wheel/source/pin binding, missing or wrong callback/source/history evidence, wrong selected pair/account, stale TradingDay/generation values, and wrong ConfirmDate. A ConfirmDate-only row is accepted as shape-only, consistent with the native confirmation field having `ConfirmDate` but no `TradingDay` member; an optional row TradingDay is separately checked when present. The QA-only positive assertions verified that accepted receipts still say `provider_source_trusted=false` and `execution_authorized=false`.

## Finding: Python bool passes the integer equality gate

The candidate compares evidence generation fields to the expected generation without requiring exact `int` types. For a scope with `connection_generation == 1`, evidence with both `query_connection_generation=True` and `current_connection_generation=True` passes and returns `consumer_contract_satisfied=true`. The optional native `error_code` and `submit_code` allowlist similarly accepts `False` as zero (`False == 0`). These are malformed typed attestations accepted at the contract boundary. QA-only tests preserve both counterexamples. The receipt remains non-authorizing, but callers must not treat `consumer_contract_satisfied` as evidence authenticity or execution readiness.

## Provenance and integration limits

The successful attestation is supplied by an injected protocol object. This consumer validates fixed identifiers and digest shape; it does not itself authenticate the attestor, recompute the source/history digests, or prove provider origin. The recorded query-history evidence is in-process and is not durable provider provenance. Static search of `backtrader_runtime` found no reference to `ctp_simnow_settlement_consumer` or `consume_current_settlement_readiness`; the candidate is not wired to the managed runtime/default inventory/CLI. The copied main-source snapshots match the frozen 9-file source check, but that does not close the live integration boundary.

No SDK, `_ctp`, native library, provider, credentials, private config, network, order, or settlement write was used. This QA establishes only a local fake consumer contract and does not accept G6-S or G7-S.

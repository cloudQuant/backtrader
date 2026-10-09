# Binance TH01 account_full R2 independent descriptor-liveness review

Date: 2026-10-09  
Disposition: **GO_SOURCE_FAKE_COMPONENT_ONLY**  
Evidence class: **SOURCE_FAKE_COMPONENT_ONLY**

## Reviewed pins

| Public source | Bytes | SHA-256 |
|---|---:|---|
| examples/000_live_certification/binance_penetration/_certification/th01_account_full_snapshot_r2.py | 83,891 | 8524d5fa9934e1c119a5bd7c57f34480311eb9e1d18efb1edc8c8a4792d7d141 |
| tests/unit/live_certification/test_binance_th01_account_full_snapshot_r2.py | 34,381 | 839d0a25d8efbffe0417503f9474ede3a963777deb019ee7306539e28416692a |

The following public dependencies had matching pre/post-run byte pins:

| Public dependency | Bytes | SHA-256 |
|---|---:|---|
| examples/000_live_certification/binance_penetration/_certification/th01_account_full_snapshot_r1.py | 60,349 | 049ef44814d2131b53a5b32dfdd5519b5c4607cb3db9922d330c1282c01d93c5 |
| examples/000_live_certification/binance_penetration/_certification/th01_force_orders_transport_r9.py | 73,002 | c937a07671a6df7991fb29e131d895c0eca21644d28140542fab7c8b0db1b944 |
| examples/000_live_certification/binance_penetration/_certification/th01_root_protected_owner_r1.py | 92,566 | 290f8316e46eb9434b818faaaee9dfd1bfa224a34409ba00b2e39dfd28a2c95f |
| scripts/iteration41_binance_th01_root_account_window_call_r1.py | 132,886 | ba0360ecc5ed99b37196e3d077e25a78cd771facec8e224ab1371635cf9be021 |
| scripts/iteration41_binance_th01_account_window_candidate_r2.py | 11,391 | 698d607e6abce0f5595470c5207a4e065b11200df5b895db35fb6af816364cd6 |

The guarded process loaded the R1 module, R2 module, and R2 test from their exact repository origins. The test's exact-source loader checked the owner, R9 extension, Root wrapper, and account-window candidate pins above. All listed source/test/dependency pins were identical before and after the run.

## Review findings

The three previously held behaviors remain corrected:

1. **History reconciliation.** Baseline equality covers current-state fields. Before-cleanup and after-cleanup also compare the complete fills and ledger history. The positive-history regression passed with one fill in the ready after-cleanup candidate.

2. **UM/CM collisions.** A symbol appearing in both catalog families produces catalog_cross_family_symbol_collision and makes the catalog unusable; producer creation rejects it. Row classification explicitly returns UNKNOWN/UNKNOWN/product_family_ambiguous for an ambiguous symbol. The collision regression passed.

3. **R2 implementation binding.** The full module snapshot includes non-dunder module globals, function code/default/closure shapes, and class members. The new descriptor handling recursively snapshots property fget/fset/fdel and staticmethod/classmethod __func__ shapes. The regression changes InstrumentCatalogReceiptV2.usable.fget.__code__ while a producer is held and requires r2_producer_api_binding_invalid; it restores the original code and confirms the producer verifies live. The internal _classify_pages_and_snapshot rebinding regression also remains and passed.

No remaining defect was found in the reviewed sourcefake scope.

## Guarded fake test run

A fresh python -B process installed network, subprocess, Pipe, and native-call guards before importing pytest or collecting candidate tests. Plugin autoload was disabled. The runner invoked pytest.main for only the R2 test file with -p no:asyncio, -p no:capture, -p no:terminal, and -p no:cacheprovider. Capture and terminal plugins were disabled because pytest's Windows colorama workaround attempted a native DLL load; no native operation was allowed.

Result: **9 passed, 0 failed, 0 skipped; exit 0**. One existing PytestConfigWarning was recorded: Unknown config option: asyncio_default_fixture_loop_scope.

The candidate-module pre-guard check was false. Network, subprocess, Pipe, and native guard self-checks were all denied as intended. There were **zero blocked operation attempts during the tests**.

## Scope and limits

This is an independent public-source and fake-only component review. Synthetic catalog HTTP, account pages, writer references, Root hook, and R9 ticket/callback fixtures were used. No provider/account read, credentials/private capture, native API, network operation, real subprocess, or real Pipe operation occurred.

The Root wrapper remains frozen and unintegrated with R2. This review does not establish an actual account_full read, provider/account acceptance, or formal TH01 PASS. No candidate, dependency, staging index, or commit was changed. The original R1 HOLD review and the two earlier R2 HOLD records remain preserved separately.
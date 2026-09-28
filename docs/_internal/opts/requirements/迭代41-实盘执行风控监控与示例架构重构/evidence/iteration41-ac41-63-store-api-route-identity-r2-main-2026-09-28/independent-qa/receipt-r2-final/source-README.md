# Store/API route identity follow-on candidate — R2

Status: `ISOLATED_FOLLOW_ON_CANDIDATE / PENDING FINAL INDEPENDENT QA RECEIPT / NO_WRITE / LIVE_NO_GO`.
No shared checkout source, tests, docs, or AGENTS files were edited. The candidate patch, Store source, and test source remain frozen; this evidence correction changes only README/manifest/checksum metadata and the verification summary.

## Exact patch lineage

- Base Store SHA-256: `A0393FC4F0B7212C6EE4B4F32DE2AA9E6E9A0ECFC5FE976F72160E2EC11F6ABE` (accepted r4 target).
- R2 Store SHA-256: `CE04ECBADDD3D3EA01C707313EA9B144650C47E322D0BDFC915000C0110094CA`.
- Patch SHA-256: `AEF2BD46AA261576F936580502DF53C7FDC669856E3A7A59812CE43655493E59`.
- New route-contract test SHA-256: `4AD2A69E10B918708D01113C0D2748A692167F96EF481C17A1ED31F57B73C45A`.
- `manifest.json` records exact preimage/target sizes and hashes. Its SHA changes for this evidence-only correction; it does not alter code identity.

The patch is based on exact A039 Store bytes. In `exact-replay-final2`, `git -c core.autocrlf=false apply --check` and `apply` succeeded. Replayed Store and test hashes match the candidate byte-for-byte. The explicit Git setting preserves this source file's mixed line endings.

## Behavior covered

R2 compares the Store provider with its route snapshot and statically discoverable API `exchange_kwargs` mappings. It detects observable route changes before direct, generic SDK, typed queue, managed worker, and synchronous writer handoffs. It does not evaluate property or slot descriptors. Malformed route containers/conversions fail with a controlled unavailable-identity error.

When a recovery-exit order encounters an identity error, the Store aborts/disarms recovery before re-raising. For synchronous legacy submit/cancel, R2 checks again after lazy API readiness and before writer-method lookup. If the Store has no route snapshot and the newly constructed API has no usable static route source, that operation fails closed.

The frozen contracts cover historical fake bypass shapes, a slotted property route that is never evaluated, lazy submit/cancel construction, recovery-exit mismatch disarm, malformed route inputs, matching non-CTP compatibility, and the normal CTP direct-enqueue negative.

## Verification and evidence classification

### Focused inert checks

- Route identity contracts: 16 passed.
- R4 recovery-exit matrix: 4 passed across `market_data_only` × managed-adapter present/absent.
- P3 independently exercised four additional fake-only cases: both historical fake route-mismatch bypasses were blocked; the known hidden `__getattribute__` route residual was reproduced; and no-route injected non-CTP compatibility remained positive.
- Ruff: passed.
- `py_compile`: passed.
- Exact A039 patch replay: passed, with replayed Store/test hashes matching the frozen candidate.

These focused checks use inert fakes. They do not exercise a real provider, credentials, network, order, or cancel.

### Compatibility runs: do not conflate these results

The author's broad run is preserved as `461 passed, 1 skipped` in `focused-junit.xml`, but it is **contaminated for fake-only / no-SDK / no-native claims**. `run_candidate.py` installed no import guard or SDK stub. The scope includes 18 explicit calls to `optional_sdk("bt_api_ctp.ctp.client")`; `optional_sdk` imports the module whenever the distribution is installed. The local environment had the CTP distribution installed, and this run imported `bt_api_ctp.ctp.client` and its bundled `_ctp` extension. Treat this as a mixed local compatibility run only, not guarded offline evidence. Preserve the original count and JUnit hash; do not claim no SDK/native module was loaded.

P3's independent guarded compatibility run reported **443 passed, 1 skipped, 18 import-tripwire-blocked**. Its tripwire rejected the CTP imports before the root `bt_api_ctp` package loader; P3 reported that no native module loaded in that run. The 18 blocked cases are not passes. P3's final immutable-identity receipt is pending and must bind the corrected manifest/checksum identity before this result is treated as final independent QA.

The 18 blocked test nodes were:

1. `test_native_ctp_wrapper_rejects_market_before_req_order_insert`
2. `test_native_ctp_wrapper_defaults_to_read_only_and_rejects_implicit_settlement_write`
3. `test_create_ctp_wrapper_patches_missing_spi_callbacks`
4. `test_ctp_wrapper_accepts_dict_snapshots_from_trader_client`
5. `test_ctp_wrapper_positions_accept_float_string_ctp_codes`
6. `test_ctp_wrapper_positions_use_contract_multiplier_and_exchange_fields`
7. `test_ctp_wrapper_polls_order_insert_error_events_with_order_ref`
8. `test_ctp_wrapper_order_submit_reject_status_overrides_unknown_order_status`
9. `test_ctp_wrapper_trade_callback_accepts_float_string_ctp_codes`
10. `test_ctp_wrapper_fetch_open_orders_converts_ctp_rows`
11. `test_ctp_wrapper_fetch_open_orders_accepts_float_string_ctp_codes`
12. `test_ctp_wrapper_submit_order_rejects_caller_forged_store_capability`
13. `test_ctp_wrapper_submit_order_rejects_raw_only_client_before_api_access`
14. `test_ctp_wrapper_cancel_rejects_without_raw_action_access[missing-capability]`
15. `test_ctp_wrapper_cancel_rejects_without_raw_action_access[caller-forged-capability]`
16. `test_ctp_wrapper_submit_order_rejects_non_integer_lots[0]`
17. `test_ctp_wrapper_submit_order_rejects_non_integer_lots[1.5]`
18. `test_ctp_wrapper_submit_order_rejects_non_integer_lots[bad]`

The broad run emitted the existing unsupported pytest option warning for `asyncio_default_fixture_loop_scope`.

## Limits

Route metadata is mutable caller-controlled metadata, not trusted provider authority. This patch is not a same-process sandbox and does not prove writer closure. To preserve established injected-API positives, an already-present API with no statically visible route mapping and an empty Store snapshot is not universally rejected. P3 reproduced a residual where route information hidden behind custom `__getattribute__` remains unobservable. The lazy synchronous path with no snapshot fails closed after construction when no static route source exists. No G4, live, CTP write, or provider acceptance is claimed.
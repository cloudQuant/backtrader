# Normalized Store test migration R3 — frozen candidate

**Status:** test-only candidate frozen; independent QA requested. R2 is superseded after QA identified loss of public read-side polling coverage in its fee/source-state test. Nothing was applied to the shared checkout.

## Bound files and hashes

| Artifact | SHA-256 |
|---|---|
| Source `backtrader/stores/btapistore.py` | `B9E1BCD3EFA6CF57BF8D3029D60AE89A7158D5332B313EE8DFE12A4A0CA557FF` |
| Test preimage `tests/unit/stores/test_btapistore_normalized.py` | `84C570A2EA1DDC03A3AE3560E30177CD695B5720BC05225256BC7F6D1016D397` |
| Test target `test_btapistore_normalized.py` | `C3004A537AED8DF41B106F2A8D03287B02F54720B468E12C423BE2A82A5994F5` |
| Patch `TEST-MIGRATION-R3.diff` | `56E0EEEC9D7F9764E6516CB6ECFCA4AF33FDF351CA19630F8DF32AF9A490D56F` |
| Focused JUnit `focused.junit.xml` | `D62BC3D9AE2DA444BC44B5B50E10302DA7D0C4EA1602829F4B2A843869032D3E` |
| Focused stdout `focused.stdout.txt` | `8BAED0EB12E44D4799432E6F515494561D0DE20F02F3602B61DF804D061C369E` |
| Guard report `guard-report.json` | `10665BBC87EE603079935C6554A35769E5EE3B668E271AC31EC40CB88EB38C20` |
| Guard plugin `normalized_guard_plugin.py` | `E18961E7A362FA74E336415BA3F58B24ACCCB7585F665ABEC1E169D9DCBD1876` |

The mixed-EOL test file remains mixed-EOL. The unified patch modifies exactly one path, with 130 additions and 69 removals according to `git apply --stat`. A fresh scratch replay of the exact preimage produced target SHA `C3004A537AED8DF41B106F2A8D03287B02F54720B468E12C423BE2A82A5994F5`.

## R3 change

R3 restores `store.poll_broker_update()` in `test_framework_retains_sdk_trade_source_state_and_canonical_fee_without_interpretation`. The test asserts each public poll returns a non-`None` update, then retains all order/trade event source, fee, currency and framework-reference assertions. It still attempts a public CTP submit only to assert fail-closed rejection and zero FakeSdk order/cancel calls.

The three non-CTP parameter cases remain end-to-end FakeSdk positives. The remaining CTP order/cancel tests preserve the request identity projections and zero-dispatch rejections. Request-shaped stand-ins and FakeSdk only are used; the optional provider/native packages are import-blocked.

## Focused verification

From `D:\source_code\backtrader`, with `PYTHONPATH` set only to this R3 package directory:

```powershell
python -m pytest -p normalized_guard_plugin `
  "D:\temp\iteration41-store-r5-main-integration-20260927\normalized-test-migration-r3\test_btapistore_normalized.py::test_order_conversion_preserves_native_units_and_all_position_fields" `
  "D:\temp\iteration41-store-r5-main-integration-20260927\normalized-test-migration-r3\test_btapistore_normalized.py::test_ctp_order_ref_session_and_front_are_preserved_for_cancel_without_exchange_id" `
  "D:\temp\iteration41-store-r5-main-integration-20260927\normalized-test-migration-r3\test_btapistore_normalized.py::test_framework_retains_sdk_trade_source_state_and_canonical_fee_without_interpretation" `
  "D:\temp\iteration41-store-r5-main-integration-20260927\normalized-test-migration-r3\test_btapistore_normalized.py::test_open_order_identity_supports_native_cancellation_without_local_order" `
  -q --tb=short --junitxml="D:\temp\iteration41-store-r5-main-integration-20260927\normalized-test-migration-r3\focused.junit.xml"
```

Result: **7 passed**, one existing Quandl deprecation warning, 4.65 seconds. Exact nodeids:

- `test_order_conversion_preserves_native_units_and_all_position_fields[MT5___FOREX-EURUSD-0.2-lots]`
- `test_order_conversion_preserves_native_units_and_all_position_fields[CTP___FUTURE-IF2609-2-contracts]`
- `test_order_conversion_preserves_native_units_and_all_position_fields[BINANCE___SWAP-BTCUSDT-0.02-base]`
- `test_order_conversion_preserves_native_units_and_all_position_fields[OKX___SWAP-BTC-USDT-SWAP-2-contracts]`
- `test_ctp_order_ref_session_and_front_are_preserved_for_cancel_without_exchange_id`
- `test_framework_retains_sdk_trade_source_state_and_canonical_fee_without_interpretation`
- `test_open_order_identity_supports_native_cancellation_without_local_order`

Guard result: zero provider import attempts; zero external socket attempts; three loopback-only connections used by the Windows asyncio event-loop socketpair in fake async tests. No external endpoint was permitted or contacted.

## Patch replay

- `git -C D:\source_code\backtrader apply --check D:\temp\iteration41-store-r5-main-integration-20260927\normalized-test-migration-r3\TEST-MIGRATION-R3.diff` passed against the bound test preimage.
- A fresh scratch tree passed `git apply --check` and `git apply`; resulting file SHA matched the target above.
- After checks, shared checkout hashes remained Store `B9E1BCD3EFA6CF57BF8D3029D60AE89A7158D5332B313EE8DFE12A4A0CA557FF` and test preimage `84C570A2EA1DDC03A3AE3560E30177CD695B5720BC05225256BC7F6D1016D397`.

This narrow test migration is not a full Store/Runtime regression or writer-closure acceptance. Root integration should still run the broad lane after independent R3 QA.

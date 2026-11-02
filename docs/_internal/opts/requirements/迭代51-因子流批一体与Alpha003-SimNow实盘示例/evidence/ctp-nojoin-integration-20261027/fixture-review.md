# I51 no-Join environment-fixture delta review

**Disposition: GO_FIXTURE_DELTA_ONLY.** In `_source_bars`, the offline tape's ISO trading day is converted at the synthetic CTP boundary to the compact `%Y%m%d` representation used by the planned member. The fixture resolves that member by the matched planned close and product, then asserts both the normalized trading day and session ID before emitting a bar. This addresses the observed fixture mismatch (ISO `2026-10-21` versus CTP `20261021`) while checking that the bar still matches its planned member. No production guard or runner source changed.

The other four reviewed source pins are unchanged. The earlier author-reported 8/8 focused run applies to its earlier five-source pins; it was not repeated after this fixture edit. The author reports the previously failing environment node passed 1/1 at the final fixture pin, with one existing pytest configuration warning. I performed a static diff review only and ran no tests or imports. The change provides synthetic fixture evidence only, not native, provider, credential, account, or formal acceptance.

Final source pins (SHA-256):

| File | Bytes | SHA-256 |
|---|---:|---|
| `backtrader/stores/btapistore.py` | 862375 | `7e0d35fbf4f24d11b739a7a61cab2c2a30810bcac0f0a8f421f2e0dab9cc8491` |
| `examples/unified/028_alpha003_simnow_minute/run.py` | 250434 | `3373140b1e68f3f4871ce821220117883edb0af85640bb723de19c75a1012e62` |
| `tests/unit/test_ctp_nojoin_wrapper.py` | 7208 | `0a75d2be5edbcc387b3472c5cbc63bf54eeb5cf4e4ad0df759c18b80d50dcfba` |
| `tests/integration/test_alpha003_refresh_dispatch_recovery.py` | 45288 | `71481247a32eb02367238f96678c39908eb0f22eab0c4e1d9ab800233805e634` |
| `tests/integration/test_alpha003_main_contract_rollover_execution.py` | 85040 | `89936270e90ca2193926e2ecb3cc5ed482579d574d17641e53c7ced40eecf187` |

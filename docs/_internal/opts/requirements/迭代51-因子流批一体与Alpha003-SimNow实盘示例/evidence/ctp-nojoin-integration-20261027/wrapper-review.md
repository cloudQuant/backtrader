# I51 no-Join wrapper integration review

**Disposition: GO_SOURCE_FAKE_WRAPPER_AND_RUNNER_ONLY.** The reviewed wrapper checks the CTP SDK's market-data and trader `start` signatures before either client is constructed when `ctp_join_observer=False`. It requires explicit `block` and `join_observer` parameters, so a `**kwargs`-only method fails closed. The option must be an exact `bool`. With the default `True`, startup retains the previous `start(block=False)` calls; with `False`, both clients receive `start(block=False, join_observer=False)`.

The live runner copies `api_kwargs` and overwrites only the copy with `ctp_join_observer=False` in its common `create_store` path. That path follows either the environment configuration or the protected in-process override. The unit regression now covers the kwargs-only SDK signature and asserts rejection before client construction, connect, and auth events. The two integration fixtures provide `True` from their respective environment and protected-override routes and use strict fake start signatures that require `False` for both clients. The protected helper itself was outside the authorized source set and was not opened; this review confirms only the runner handoff and its fake coverage.

The author reports the frozen focused run passed **8/8** with exit 0 and one existing pytest configuration warning. I did not execute tests or import candidate code. This is source and fake-fixture evidence only; no native SDK, provider, credential, account, or formal acceptance is established.

Reviewed source pins (SHA-256):

| File | Bytes | SHA-256 |
|---|---:|---|
| `backtrader/stores/btapistore.py` | 862375 | `7e0d35fbf4f24d11b739a7a61cab2c2a30810bcac0f0a8f421f2e0dab9cc8491` |
| `examples/unified/028_alpha003_simnow_minute/run.py` | 250434 | `3373140b1e68f3f4871ce821220117883edb0af85640bb723de19c75a1012e62` |
| `tests/unit/test_ctp_nojoin_wrapper.py` | 7208 | `0a75d2be5edbcc387b3472c5cbc63bf54eeb5cf4e4ad0df759c18b80d50dcfba` |
| `tests/integration/test_alpha003_refresh_dispatch_recovery.py` | 44647 | `5396b51b845506eedfbbed4609882bb0edcd87a798fe2c04a1497b00d9546f13` |
| `tests/integration/test_alpha003_main_contract_rollover_execution.py` | 85040 | `89936270e90ca2193926e2ecb3cc5ed482579d574d17641e53c7ced40eecf187` |

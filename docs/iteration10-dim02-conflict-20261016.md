# Iteration 10 DIM02 live-conflict consumer acceptance — 2026-10-16

## Formal clause and ruling

The formal plan defines DIM02 as: “同合约多频道/周期、回补切实时、bar 修正、稀疏期权链、组合腿时间偏差”，with the evidence boundary “真实订阅/投影链 + 确定性数据；无重复上游或伪造新鲜度” ([formal plan, DIM02 row](D:/bt_api_py/docs/迭代计划/迭代10-可选组件与可配置通信/正式迭代计划.md)). The acceptance summary defines formal PASS as having all evidence required by that case; real-account, cross-machine, and load evidence apply only where the case requires them ([acceptance summary, PASS definition](D:/bt_api_py/docs/迭代计划/迭代10-可选组件与可配置通信/迭代10验收状态汇总.md)). DIM02 does not require a real venue account or real provider data.

**Root formal ruling: DIM02 PASS.** Round 176 accepted the multi-key/shared-upstream and sparse-chain, history-to-live seam/correction-policy, and leg-time-skew increments, but explicitly deferred the formal DIM02 ruling ([R176 root adjudication](D:/bt_api_py/docs/迭代计划/迭代10-可选组件与可配置通信/evidence/dim02-increments-20261016/root-adjudication.md)). The independent clause audit then held DIM02 because it could not find a production `ServiceReadProxy` consumer receiving a conflicting live bar; the SDK seam test used a test-local fail-closed projection, while the existing Backtrader integration only covered duplicate live bars. The new node below closes that precise gap with the actual synthetic SDK stream and production Backtrader consumer path. No extra provider-account, cross-machine, aggregate-chain, or full-matrix requirement is added.

The prior audit is preserved at `D:\bt_api_py\.codex-tmp\resume-dim02-arb03-independent-20261016.md` (9,488 bytes, SHA-256 `577a059db372cd2ef395186081cd568a11066a3bd7d09fc64e68464dae7bfd05`). The independent incremental source review by `resume_pass_audit_reg_risk_cfg` returned GO for the lifecycle correction: `Cerebro.adddata()` binds the environment, and `feed._start()` invokes the normal `start()` plus `_start_finish()` initialization, including `_tzinput`; the conflict and cleanup assertions were unchanged. Root then accepted the fixed node in the r2 run recorded below.

## Accepted node and evidence boundary

The single new node is [`tests/test_service_read_proxy_dim02_conflict_integration.py`](../tests/test_service_read_proxy_dim02_conflict_integration.py), 13,111 bytes, SHA-256 `21eedae40e122c2977e4f3a01b563274f11f29291f6d32106e0d6d31d3e1f2b9`. It reuses the accepted spawned synthetic account/market ServiceHost fixture. A deterministic market provider publishes a live bar whose `open_time` matches the final history bar but whose close differs. The normal SDK runtime/client and authenticated market stream deliver that event to the production `ServiceReadProxy`, injected into the real `BtApiStore` and `BtApiFeed`; the feed is registered with a real Cerebro before its standard `_start()` initialization.

The consumer raises `ServiceReadProxyError` with code `HISTORY_LIVE_CONFLICT`. After rejection, the test checks the Feed’s OHLCV/time lines and length, the proxy’s `history_by_open`, last-emitted open/identity and pending bars are unchanged. The ordered stream cursor advances by exactly one because it consumed the event; that cursor movement does not mutate the projected bar. These checks exercise the SDK-to-Backtrader subscription and projection path with deterministic data, not a test-local conflict oracle.

The normal-close assertions are part of the accepted node. On the passing path it stops Feed and Store, verifies the proxy is disconnected and both SDK facades are unhealthy, closes the runtime with zero cleanup failures and unregister uncertainties, and verifies zero active upstreams/registrations and exactly one market source start/stop. `_close_host_normally` requires both Hosts to report closed, join within the bound, and exit code zero. The final bounded reaper returns immediately for normally closed processes; any forced cleanup or recorded cleanup failure fails the test. Root’s one passing test therefore traversed these assertions.

Evidence is `REAL_SDK_HOST_STORE_FEED_LIVE_BAR_CONFLICT_REJECTION_LOCAL_SYNTHETIC`: local spawned service processes, actual SDK/CURVE transport and production Store/Feed consumer, deterministic synthetic providers. It is not venue-account evidence.

## Root r2 result

Root’s fixed r2 run used `C:/Anaconda3/python.exe -m pytest -q --noconftest` from `D:\source_code\backtrader`, selected only `tests/test_service_read_proxy_dim02_conflict_integration.py`, and wrote to `D:\temp\iteration10-dim02-conflict-root-20261016-r2`. The exact argv and environment are in that output’s `command.json` and `spec.json`.

Result: pytest exit 0; 1 test passed in 13.436 seconds (the console summary rounds this to 13.43 seconds); one existing Quandl `DeprecationWarning`; no pytest failures, errors, or skips. `stderr.log` is empty. The Root result reports 834 fixed source pins unchanged and all six repository heads unchanged:

| Repository | HEAD before = after |
|---|---|
| Backtrader | `223d5b68a55bb167e2d310f9565b511093b01742` |
| bt_api_py | `e75ef358134df0069f2873625ff69313133c9a0c` |
| bt_api_base | `b4aabd1e17b9c7252fa7b4d266932087d99b5517` |
| bt_api_execution | `f5c030644dea06ce91afbaacf94e11e353538186` |
| bt_api_transport_zmq | `a397fdb460d2deb22e67ceb4963992ef63dbbb0e` |
| bt_api_gateway | `59b164ab7f89c6428ae6546103aad6058dab4c16` |

The run pin manifest fixes 25 relevant files. This is the focused dependency set; the Root’s before/after source manifests independently cover all 834 inputs.

| Repository-relative path | Bytes | SHA-256 |
|---|---:|---|
| Backtrader `tests/test_service_read_proxy_dim02_conflict_integration.py` | 13,111 | `21eedae40e122c2977e4f3a01b563274f11f29291f6d32106e0d6d31d3e1f2b9` |
| Backtrader `tests/test_service_read_proxy_integration.py` | 43,463 | `f32471d6b189b765229017e5dd490361b91e0419c5fc320f51777bfa32972967` |
| Backtrader `tests/test_service_read_proxy.py` | 24,238 | `6d23844b7007e04c27bbf281faa79a027ded103be4c29355c9f61e89503fb276` |
| Backtrader `backtrader/stores/service_read_proxy.py` | 36,951 | `00b31eba5962a39651fdb034088c19a20d4a95a230642dbad425761f38ddc9b4` |
| Backtrader `backtrader/stores/btapistore.py` | 796,405 | `451b488fe1f6b1fad0a034dd6fb40e4c8f95829f0cdba3c190ed2c593392c19a` |
| Backtrader `backtrader/feeds/btapifeed.py` | 77,300 | `960e023cc1c3b7f6671b8af3b50a775b1dd7de5e9213509d207a15070001a0e2` |
| Backtrader `backtrader/feed.py` | 57,844 | `cb43784e877fb73ca7747c415a00a22454a46cf60fb1b6295657d6a8f96f6503` |
| Backtrader `docs/source/developer-guide/optional-service-read-proxy.md` | 6,462 | `b5b9191c91bdc7cce4cdae3c6ca198fb9525a0191d99068377009406716ac30c` |
| SDK `bt_api_py/service_market.py` | 51,773 | `5b7a357693ef4ddc50ef397f4bfc67ca7116ab2809850c03ee07f05a18bc75b6` |
| SDK `bt_api_py/service_runtime.py` | 79,363 | `7f5abce5edac96b3b93dac4c636770add1e757b3337f440912759c69289ce5f0` |
| SDK `bt_api_py/service_host.py` | 66,489 | `07e95f92b5782dd18412b0397ab1c50e3ecf8482c720392314d93f4cbf9d0be1` |
| SDK `bt_api_py/service_config.py` | 48,243 | `5d436d933e9b0367eddd29c41d011e68338ce90762fe635865274195e7fa78af` |
| SDK `bt_api_py/service_components.py` | 101,891 | `2af780d16feb59603e88015e9ff54f8afc97e7476049e02513b4becb272885ac` |
| SDK `bt_api_py/service_account.py` | 18,534 | `d7aee3c00d1d9fe2bd8219f8e35898d0f7620df2999ca4de6082a23544e8008f` |
| SDK `bt_api_py/service_registry.py` | 102,773 | `7c708a434397287117545a144bd7264cd4aa0741dd21e0a990c022f915cd2280` |
| SDK `bt_api/bt_api_gateway/src/bt_api_gateway/__init__.py` | 2,141 | `d807f831efed22e4f041cbdb1d87fe767ebe7c6c2fba8a64460db05c4fe0ac7c` |
| SDK `bt_api/bt_api_gateway/src/bt_api_gateway/market_hub.py` | 53,018 | `68066602191877afc24c72623eb8f81d4defe7f093fbdb53d104cc68153675d3` |
| SDK `bt_api/bt_api_gateway/src/bt_api_gateway/service_component.py` | 35,467 | `d5e3d4e7814413885672484a11c666dd1603ebfeeb39e412916bab430821fc0c` |
| SDK `bt_api/bt_api_gateway/src/bt_api_gateway/session_guard.py` | 22,894 | `8910462b67ace265577b8ab6fb2ac3c68d9d841e0c5499cf652f4c74f75ad682` |
| SDK `bt_api/bt_api_gateway/src/bt_api_gateway/account_session_worker.py` | 41,127 | `0006b8a9cfe014d881e8bd8efabebe943ae301af2d5f167211d29cf4cc8545e1` |
| SDK `bt_api/bt_api_gateway/src/bt_api_gateway/event_journal.py` | 104,463 | `69c97df8b49b19c96b5819fbe06170e19509b2c50cd47ab2513c3c1bf2998c4d` |
| SDK `bt_api/bt_api_base/src/bt_api_base/account_protocol.py` | 28,973 | `dc25caae8cb3a7e2ac8851958a60a15a2a6c264f4b3419a3d5f50a5d76fa116c` |
| SDK `bt_api/bt_api_base/src/bt_api_base/market_protocol.py` | 5,880 | `9ad1a16842dfee03587a815ecf4a9915559287c9ce995f6cff8df15c00309108` |
| SDK `bt_api/bt_api_base/src/bt_api_base/market_history_protocol.py` | 11,394 | `21096e58d14ebfb05554cf76012793de25846e9f2474b1c42d149edaf6b469ae` |
| SDK `bt_api/bt_api_base/src/bt_api_base/service_protocol.py` | 26,174 | `f0ed739ac98cda400bed07bf8487b79ee0a5ebe6842b9d0711b4b12e8af6b15a` |

The acceptance run was performed on Backtrader `dev` at HEAD `223d5b68a55bb167e2d310f9565b511093b01742`. The accepted-delivery commit hash is intentionally left to Git history after Root’s scoped commit; it is not inferred here.

## Preserved r1 failure

The first Root attempt remains unchanged at `D:\temp\iteration10-dim02-conflict-root-20261016-r1`: 1 failed / 13.829 seconds, at the first `feed.load()` with `AttributeError: 'BtApiFeed' object has no attribute '_tzinput'`. The fixture had called `feed.start()` without binding it to a Cerebro environment and without running the normal DataBase `_start()` wrapper. This was a test lifecycle omission, not evidence of a production conflict-path defect. The follow-up adds the real Cerebro registration and standard Feed initialization. R1’s result, JUnit and logs remain preserved; r2 is the accepted corrected run.

This document records the supplemental DIM02 ruling and does not rewrite R176/R194 history or modify the SDK acceptance tracker. The tracker/progress update remains with Root.

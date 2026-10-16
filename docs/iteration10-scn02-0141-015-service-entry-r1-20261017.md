# Iteration 10 SCN02 014_1 and 015 normal service-entry round

Date: 2026-10-17. Repository: `D:/source_code/backtrader`, branch `dev`, base HEAD `1ec36358ea0f15608ac613e429fd1fca70e81f8d`.

This round wires the existing 014_1 and 015 public live selectors to their explicit read-only service backends while retaining the direct path as the default and rejecting unsupported backend values. Both backends now accept the ordinary Backtrader `Cerebro.run()` result (`list[Strategy]`) as well as the nested optimization result shape. The service path holds the session open through the actual Store/Feed/Broker/Cerebro run and uses the normal example strategy.

## Acceptance evidence

The focused local-host integration node passed four parametrized checks on CPython 3.11.5:

```text
C:/anaconda3/python.exe -m pytest -p no:asyncio tests/integration/test_scn02_0141_015_service_entry.py -q
4 passed, 1 warning in 10.23s
```

The warning is the existing `asyncio_default_fixture_loop_scope` pytest configuration warning. After a failure-message-only assertion detail was added, the same focused node also passed 4/4 in 8.40s; Ruff and `py_compile` passed on the final selected source/test bytes. This delivery reuses those results and does not rerun the Host node.

The test uses local `GatewayOperatorDeployment` ServiceHosts/CURVE endpoints, the SDK service runtime and account/market clients, the real `ServiceReadProxy`, `BtApiStore`, normal example Feed/Broker/Cerebro/strategy, and synthetic account/provider/CTP event leaves. It asserts account snapshot and metadata reads, three market subscriptions with ticks consumed for all legs, zero order writes, provider and Host cleanup, and the expected blocked research outcome: 014_1 remains `NOT_QUALIFIED` with zero bar cohorts; 015 remains `TRUSTED_NOW_INVALID`, cohort count zero, and HFT `NOT_ADMITTED`. This is local synthetic service-entry evidence only; it does not qualify clocks, authorize writes, establish HFT, or add a formal SCN02 case PASS.

Independent static review returned `GO_STATIC` for the selectors, backends, and integration assertions. The inherited fixture `tests/integration/test_0142_service_backend_ctp_host.py` is present at committed blob `2db19c05f9049d1fabe26f16522f8668524c20e8` and checkout SHA-256 `c75ae2d6499c8ccb941d754b9271b5208ca68c354cdc73c563b2a0494f927030`.

The shared helper and proxy are separate inherited dependencies, not part of this round: `backtrader_runtime/service_observation.py` is from the 7cda685 commit and `backtrader/stores/service_read_proxy.py` from b69cf008. The exact helper/proxy bytes used by the 4/4 Host runs were not recorded, so those runs do not independently validate the exact helper/proxy bytes at the current HEAD. Their current committed SHA-256 values are `8032adf807cf9adec8c59091730954ca5d82ff66717db94049fbdb0f9eaff284` and `809f01eb3ccf5e653247e255145170a6ab4b4360e0b060cc6bdd461df18ddb41`, respectively. This delivery makes no stronger compatibility claim and does not repeat the Host run.

## Exact source scope

The selected payloads are the two public `run.py` selectors, their two service backend modules, this focused integration test, and this record. The exact containing commit is authoritative in Git history because a commit cannot embed its own object ID.

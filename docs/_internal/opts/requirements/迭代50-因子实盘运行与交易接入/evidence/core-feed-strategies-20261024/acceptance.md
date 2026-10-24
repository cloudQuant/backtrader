# Core/feed and strategy regression evidence — 2026-10-24

This archive records the final regression runs for AC50-14. Both ran from Backtrader `dev` at launch commit `7f58ca31f5438e56623eb98a44be89647012d2bf`. Other independent repository commits occurred during the broader delivery window; this record makes no whole-worktree-unchanged claim. The two source files listed below were hash-checked before and after these runs and matched.

The runs cover local source regressions only. They do not extend real-account, provider, SDK, or live-trading acceptance.

## Core and feed regression

Environment: `PYTHONUTF8=1`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`.

Exact pytest invocation:

```text
C:/anaconda3/python.exe -m pytest -p no:asyncio -q --tb=short --junitxml=.codex-tmp/i5051_final_core_feed_20261024.xml tests/unit/core/test_cerebro.py tests/unit/core/test_cerebro_iter28_compatibility.py tests/unit/core/test_cerebro_loop_features.py tests/unit/core/test_cerebro_resampledata_clone.py tests/unit/core/test_cerebro_runstop_thread_safety.py tests/unit/feeds/test_btapifeed.py tests/unit/feeds/test_btapifeed_arbitrage.py tests/unit/feeds/test_btapifeed_iteration22.py tests/unit/feeds/test_btapifeed_recovery_quote_alignment.py tests/unit/stores/test_btapistore.py tests/unit/stores/test_btapistore_edge_cases.py tests/unit/stores/test_btapistore_iteration21.py tests/unit/stores/test_btapistore_iteration22.py tests/unit/stores/test_btapistore_normalized.py tests/unit/stores/test_btapistore_notifications.py tests/unit/test_cerebro_idle_notifications.py tests/unit/feeds/test_btapifeed_cohort_runnext.py tests/integration/test_live_cohort_prepare_budget.py tests/integration/test_live_factor_cohort_pending_wait.py tests/integration/test_iteration50_cohort_off_engine_compatibility.py
```

Process window: `2026-10-24 23:43:54.2335308 +08:00` to `2026-10-24 23:44:23.9346369 +08:00`. Pytest reported **727 passed**, zero failures, exit code **0**, in 29.12 seconds. It emitted one existing `PytestConfigWarning`: unknown option `asyncio_default_fixture_loop_scope`.

Raw JUnit XML: [i5051_final_core_feed_20261024.xml](i5051_final_core_feed_20261024.xml), 118,797 bytes, SHA-256 `841080BA8CA07FD4D194DD62EC5F6C1C12882303617CCFEBD63651589D7DC674`.

## Full strategy regression

Environment: `PYTHONUTF8=1`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`.

Exact pytest invocation:

```text
C:/anaconda3/python.exe -m pytest -p xdist.plugin -n 8 -p no:asyncio -q --tb=short --junitxml=.codex-tmp/i5051_final_strategies_20261024.xml tests/functional/strategies
```

Process window: `2026-10-24 23:44:33.7161615 +08:00` to `2026-10-24 23:50:06.7615396 +08:00`. Pytest reported **1,286 passed**, zero failures, exit code **0**, in 332.56 seconds. It emitted 16 warnings: nine repeated `asyncio_default_fixture_loop_scope` unknown-config warnings, three pandas `fillna` downcasting `FutureWarning`s in strategy tests, and four joblib physical-core detection `UserWarning`s (`WinError 2`, with fallback to logical-core count).

Raw JUnit XML: [i5051_final_strategies_20261024.xml](i5051_final_strategies_20261024.xml), 194,129 bytes, SHA-256 `01500119914DD37886C681BC86ED82C114F43710AABC1E630870DCB6BDEF1D19`.

## Source pins

The following SHA-256 values matched at the start and end of both runs:

| Path | SHA-256 |
| --- | --- |
| `backtrader/feeds/btapifeed.py` | `CBFC755C934E8B5DC091A19F42E5E989CBBEE2BF4EAF5E3178642705E3A8A229` |
| `backtrader/_cerebro/runnext.py` | `D0A12A6558F3418249CC0FF9D9F35336698B5BE7330929C05D02C2D1921511B9` |

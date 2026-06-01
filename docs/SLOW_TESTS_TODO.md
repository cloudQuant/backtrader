# 慢速测试治理 TODO 清单 (Slow Tests Optimization Backlog)

> 基于 2026-05-28 实测数据 | Based on actual measurements taken 2026-05-28

## 测试运行总览 (Run Summary)

**运行命令**:

```bash
python -m pytest tests/ \
  --ignore=tests/functional/strategies_regression \
  --durations=0 -n 4
```

| 指标 | 数值 |
| --- | --- |
| 用例总数 | 1,958 (1957 passed, 1 skipped) |
| 实际墙钟时间 (4 worker 并行) | **177.74s (≈ 2 分 58 秒)** |
| 累计 CPU 时间 (有时长记录的用例) | 395.63s |
| 有显著时长的用例数 | 569 (其余 < 0.005s 被 pytest 折叠) |
| 排除的目录 | `tests/functional/strategies_regression`（1,036 个文件） |

**关键观察**: 仅 113 个用例（占总用例 5.8%）就消耗了累计 CPU 时间的 **78.3%**。Top 5 用例就占了 17%。

---

## 数据文件加载分析 (Data File Hotspots)

慢速测试集中在加载几个大型 CSV 文件：

| 数据文件 | 大小 | 行数 | 引用此文件的慢测试数 |
| --- | --- | --- | --- |
| `bond_merged_all_data.csv` | 66.7 MB | 684,891 | 4 |
| `FG889.csv` | 30.3 MB | 668,101 | 2 |
| `XAUUSD_5m_5Yea.csv` | 18.9 MB | 350,904 | 2 |
| `ZN889.csv` | 14.2 MB | 210,430 | 2 |
| `RB889.csv` | 11.2 MB | 170,350 | 9 |
| `CFFEX_Futures_Contract_Data.csv` | 8.4 MB | 106,611 | 2 |
| `bond_index_000000.csv` | 0.7 MB | 4,435 | 4 (与 bond_merged 配对) |
| `113013.csv` | 0.13 MB | 1,445 | 10 (trade_logger) |
| `sh600000.csv` | 0.22 MB | 5,570 | 2 |

**核心问题**:

1. 每个测试独立加载/解析 CSV → 没有 fixture 缓存
2. 大文件全量回测 → 没用 `nrows` / `fromdate-todate` 限制最少必要数据
3. `strategies/` 与 `strategies_runonce/` 是同一份策略代码在 `runonce=True/False` 两种执行模式下的回归对照（**经核对 119 对文件，差异仅在 `cerebro.run(runonce=False)` 这一行**）

---

## Top 20% 最慢测试用例 (Top 113 Cases by Time)

> 完整 113 个用例占累计耗时 78.3%。下表列出 Top 50（占 70%+），其余按文件归并到下一节。
> ✅ = 已用 `max_rows` 或 `fromdate/todate` 限制；❌ = 未限制；⚠️ = 部分限制

| 排名 | 时长(s) | 占比 | 用例 | 策略文件/数据 | 限流 |
| --- | --- | --- | --- | --- | --- |
| 1 | 20.84 | 5.3% | `tests/unit/core/test_strategy_optimized.py::test_run` | 内置数据，运行 optimization | ⚠️ |
| 2 | 15.07 | 3.8% | `strategies_runonce/trend_following/test_86_sunrise_ema_crossover_strategy.py::test_sunrise_volatility_expansion_strategy` | XAUUSD_5m_5Yea.csv (18.9MB), 76,055 bar | ✅ fromdate/todate |
| 3 | 12.80 | 3.2% | `strategies_runonce/multi_indicator/test_12_abberation_strategy.py::test_abberation_strategy` | RB889.csv, max_rows=50000 | ✅ |
| 4 | 11.98 | 3.0% | `strategies_runonce/breakout/test_09_dual_thrust_strategy.py::test_dual_thrust_strategy` | FG889.csv (30MB) | ✅ fromdate=2020-01-01 |
| 5 | 11.34 | 2.9% | `strategies/breakout/test_09_dual_thrust_strategy.py::test_dual_thrust_strategy` | FG889.csv (30MB) | ✅ — **runonce 模式对照** |
| 6 | 9.34 | 2.4% | `strategies/trend_following/test_86_sunrise_ema_crossover_strategy.py::test_sunrise_volatility_expansion_strategy` | XAUUSD_5m_5Yea.csv | ✅ — **runonce 模式对照** |
| 7 | 9.33 | 2.4% | `strategies_runonce/misc/test_16_cb_strategy.py::test_cb_intraday_strategy` | bond_merged_all_data.csv (66MB) + bond_index | ❌ |
| 8 | 8.78 | 2.2% | `strategies_runonce/special/test_13_fei_strategy.py::test_fei_strategy` | RB889.csv | ⚠️ |
| 9 | 8.52 | 2.2% | `strategies/special/test_14_hanse123_strategy.py::test_hans123_strategy` | RB889.csv | ⚠️ |
| 10 | 6.67 | 1.7% | `strategies/multi_indicator/test_12_abberation_strategy.py::test_abberation_strategy` | RB889.csv | ✅ — **runonce 模式对照** |
| 11 | 6.59 | 1.7% | `strategies_runonce/special/test_04_simple_ma_multi_data.py::test_simple_ma_multi_data_strategy` | bond_merged_all_data.csv + bond_index | ❌ |
| 12 | 6.43 | 1.6% | `strategies_runonce/trend_following/test_15_fenshi_ma_strategy.py::test_timeline_ma_strategy` | RB889.csv | ⚠️ |
| 13 | 6.03 | 1.5% | `strategies/special/test_13_fei_strategy.py::test_fei_strategy` | RB889.csv | ⚠️ — **runonce 模式对照** |
| 14 | 5.65 | 1.4% | `strategies_runonce/breakout/test_10_r_breaker_strategy.py::test_r_breaker_strategy` | RB889.csv | ⚠️ |
| 15 | 5.60 | 1.4% | `strategies_runonce/misc/test_17_cb_monday_strategy.py::test_cb_friday_rotation_strategy` | bond_merged_all_data.csv + bond_index | ❌ |
| 16 | 5.39 | 1.4% | `strategies_runonce/special/test_14_hanse123_strategy.py::test_hans123_strategy` | RB889.csv | ⚠️ — **runonce 模式对照** |
| 17 | 5.22 | 1.3% | `tests/integration/test_trade_logger.py::test_trade_logger_file_creation` | 113013.csv (小) | I/O 密集 |
| 18 | 5.06 | 1.3% | `strategies_runonce/trend_following/test_06_macd_ema_fase_strategy.py::test_macd_ema_strategy` | (内置/未检测) | ? |
| 19 | 4.92 | 1.2% | `strategies/breakout/test_10_r_breaker_strategy.py::test_r_breaker_strategy` | RB889.csv | ⚠️ — **runonce 模式对照** |
| 20 | 4.64 | 1.2% | `strategies/special/test_02_multi_extend_data.py::test_strategy` | bond_merged_all_data.csv + bond_index | ❌ |
| 21 | 4.47 | 1.1% | `strategies/misc/test_16_cb_strategy.py::test_cb_intraday_strategy` | bond_merged_all_data.csv + bond_index | ❌ — **runonce 模式对照** |
| 22 | 4.34 | 1.1% | `tests/integration/test_trade_logger.py::test_trade_logger_bar_log_content` | 113013.csv | I/O 密集 |
| 23 | 4.13 | 1.0% | `tests/integration/test_trade_logger.py::test_trade_logger_multiple_data_feeds` | 113013.csv | I/O 密集 |
| 24 | 4.11 | 1.0% | `strategies/trend_following/test_15_fenshi_ma_strategy.py::test_timeline_ma_strategy` | RB889.csv | ⚠️ — **runonce 模式对照** |
| 25 | 4.08 | 1.0% | `strategies/special/test_04_simple_ma_multi_data.py::test_simple_ma_multi_data_strategy` | bond_merged_all_data.csv + bond_index | ❌ — **runonce 模式对照** |
| 26 | 3.83 | 1.0% | `strategies_runonce/volatility/test_08_kelter_strategy.py::test_keltner_strategy` | rb2020F.csv, rb99.csv | ? (文件不在 datas/) |
| 27 | 3.83 | 1.0% | `strategies/misc/test_17_cb_monday_strategy.py::test_cb_friday_rotation_strategy` | bond_merged_all_data.csv + bond_index | ❌ — **runonce 模式对照** |
| 28 | 3.76 | 1.0% | `tests/integration/test_trade_logger.py::test_trade_logger_text_format` | 113013.csv | I/O 密集 |
| 29 | 3.76 | 1.0% | `strategies_runonce/trend_following/test_07_macd_ema_true_strategy.py::test_macd_ema_true_strategy` | rb99.csv | ? |
| 30 | 3.47 | 0.9% | `tests/integration/test_trade_logger.py::test_trade_logger_signal_log_content` | 113013.csv | I/O 密集 |
| 31 | 3.18 | 0.8% | `tests/integration/test_trade_logger.py::test_trade_logger_indicator_log_content` | 113013.csv | I/O 密集 |
| 32 | 3.18 | 0.8% | `tests/integration/test_trade_logger.py::test_trade_logger_order_log_content` | 113013.csv | I/O 密集 |
| 33 | 3.15 | 0.8% | `tests/integration/test_trade_logger.py::test_trade_logger_trade_log_content` | 113013.csv | I/O 密集 |
| 34 | 3.11 | 0.8% | `strategies_runonce/special/test_02_multi_extend_data.py::test_strategy` | bond_merged_all_data.csv + bond_index | ❌ — **runonce 模式对照** |
| 35 | 3.01 | 0.8% | `strategies_runonce/misc/test_11_sky_garden_strategy.py::test_sky_garden_strategy` | ZN889.csv (14MB) | ⚠️ |
| 36 | 2.99 | 0.8% | `tests/integration/test_trade_logger.py::test_trade_logger_position_log_content` | 113013.csv | I/O 密集 |
| 37 | 2.82 | 0.7% | `tests/unit/stores/test_btapistore.py::test_create_ctp_wrapper_patches_missing_spi_callbacks` | 无（动态类生成） | 类工厂复杂度 |
| 38 | 2.66 | 0.7% | `strategies_runonce/momentum/test_19_index_future_momentum.py::test_treasury_futures_macd_strategy` | CFFEX_Futures_Contract_Data.csv (8.4MB) | ⚠️ |
| 39 | 2.65 | 0.7% | `tests/unit/indicators/test_ind_dm.py::test_run` | 内置 2006-day-001.txt | DM 指标计算 |
| 40 | 2.51 | 0.6% | `strategies/trend_following/test_07_macd_ema_true_strategy.py::test_macd_ema_true_strategy` | rb99.csv | ? — **runonce 模式对照** |
| 41 | 2.47 | 0.6% | `strategies/volatility/test_08_kelter_strategy.py::test_keltner_strategy` | rb2020F.csv, rb99.csv | ? — **runonce 模式对照** |
| 42 | 2.44 | 0.6% | `tests/integration/test_trade_logger.py::test_trade_logger_selective_logging` | 113013.csv | I/O 密集 |
| 43 | 2.35 | 0.6% | `strategies_runonce/mean_reversion/test_31_bb_adx_strategy.py::test_bb_adx_strategy` | sh600000.csv | ⚠️ |
| 44 | 2.18 | 0.6% | `strategies/misc/test_11_sky_garden_strategy.py::test_sky_garden_strategy` | ZN889.csv | ⚠️ — **runonce 模式对照** |
| 45 | 2.11 | 0.5% | `strategies/trend_following/test_06_macd_ema_fase_strategy.py::test_macd_ema_strategy` | (未检测) | ? — **runonce 模式对照** |
| 46 | 1.98 | 0.5% | `strategies_runonce/misc/test_32_stochastic_sr_strategy.py::test_stochastic_sr_strategy` | sh600000.csv | ⚠️ |
| 47 | 1.83 | 0.5% | `strategies_runonce/momentum/test_67_two_period_rsi_strategy.py::test_two_period_rsi_strategy` | (未检测) | ? |
| 48 | 1.79 | 0.5% | `tests/unit/indicators/test_ind_hurst.py::test_run` | 内置 2006-day-001.txt | Hurst 计算复杂 |
| 49 | 1.74 | 0.4% | `strategies/momentum/test_19_index_future_momentum.py::test_treasury_futures_macd_strategy` | CFFEX_Futures_Contract_Data.csv | ⚠️ — **runonce 模式对照** |
| 50 | 1.72 | 0.4% | `strategies_runonce/mean_reversion/test_29_boll_kdj_strategy.py::test_boll_kdj_strategy` | (未检测) | ? |

---

## Top 20% 最慢测试文件 (Top 83 Files by Time)

> 完整 83 个文件占累计耗时 78.3%。下表列出 Top 30。

| 排名 | 时长(s) | 占比 | 用例数 | 文件 | 关键数据/原因 |
| --- | --- | --- | --- | --- | --- |
| 1 | 35.86 | 9.1% | 10 | `tests/integration/test_trade_logger.py` | 113013.csv，每个用例独立 setup+I/O |
| 2 | 20.84 | 5.3% | 1 | `tests/unit/core/test_strategy_optimized.py` | 跑参数优化（多次回测） |
| 3 | 15.07 | 3.8% | 1 | `strategies_runonce/trend_following/test_86_sunrise_...` | XAUUSD_5m, 76055 bar |
| 4 | 12.80 | 3.2% | 1 | `strategies_runonce/multi_indicator/test_12_abberation_strategy.py` | RB889.csv |
| 5 | 11.98 | 3.0% | 1 | `strategies_runonce/breakout/test_09_dual_thrust_strategy.py` | FG889.csv |
| 6 | 11.34 | 2.9% | 1 | `strategies/breakout/test_09_dual_thrust_strategy.py` | **同上副本** |
| 7 | 9.34 | 2.4% | 1 | `strategies/trend_following/test_86_sunrise_...` | **同上副本** |
| 8 | 9.33 | 2.4% | 1 | `strategies_runonce/misc/test_16_cb_strategy.py` | bond_merged 66MB |
| 9 | 8.78 | 2.2% | 1 | `strategies_runonce/special/test_13_fei_strategy.py` | RB889 |
| 10 | 8.52 | 2.2% | 1 | `strategies/special/test_14_hanse123_strategy.py` | RB889 |
| 11 | 6.67 | 1.7% | 1 | `strategies/multi_indicator/test_12_abberation_strategy.py` | **同上副本** |
| 12 | 6.59 | 1.7% | 1 | `strategies_runonce/special/test_04_simple_ma_multi_data.py` | bond_merged |
| 13 | 6.43 | 1.6% | 1 | `strategies_runonce/trend_following/test_15_fenshi_ma_strategy.py` | RB889 |
| 14 | 6.03 | 1.5% | 1 | `strategies/special/test_13_fei_strategy.py` | **同上副本** |
| 15 | 5.65 | 1.4% | 1 | `strategies_runonce/breakout/test_10_r_breaker_strategy.py` | RB889 |
| 16 | 5.60 | 1.4% | 10 | `tests/unit/core/test_parameter_performance.py` | 参数化基准测试 |
| 17 | 5.60 | 1.4% | 1 | `strategies_runonce/misc/test_17_cb_monday_strategy.py` | bond_merged |
| 18 | 5.39 | 1.4% | 1 | `strategies_runonce/special/test_14_hanse123_strategy.py` | **同上副本** |
| 19 | 5.06 | 1.3% | 1 | `strategies_runonce/trend_following/test_06_macd_ema_fase_strategy.py` | (未检测) |
| 20 | 4.92 | 1.2% | 1 | `strategies/breakout/test_10_r_breaker_strategy.py` | **同上副本** |
| 21 | 4.64 | 1.2% | 1 | `strategies/special/test_02_multi_extend_data.py` | bond_merged |
| 22 | 4.47 | 1.1% | 1 | `strategies/misc/test_16_cb_strategy.py` | **同上副本** |
| 23 | 4.11 | 1.0% | 1 | `strategies/trend_following/test_15_fenshi_ma_strategy.py` | **同上副本** |
| 24 | 4.08 | 1.0% | 1 | `strategies/special/test_04_simple_ma_multi_data.py` | **同上副本** |
| 25 | 3.83 | 1.0% | 1 | `strategies_runonce/volatility/test_08_kelter_strategy.py` | rb99.csv (文件不在 datas/) |
| 26 | 3.83 | 1.0% | 1 | `strategies/misc/test_17_cb_monday_strategy.py` | **同上副本** |
| 27 | 3.76 | 1.0% | 1 | `strategies_runonce/trend_following/test_07_macd_ema_true_strategy.py` | rb99.csv |
| 28 | 3.11 | 0.8% | 1 | `strategies_runonce/special/test_02_multi_extend_data.py` | **同上副本** |
| 29 | 3.01 | 0.8% | 1 | `strategies_runonce/misc/test_11_sky_garden_strategy.py` | ZN889 |
| 30 | 2.85 | 0.7% | 4 | `tests/unit/stores/test_btapistore.py` | 类工厂复杂度高 |

---

## TODO 优化清单 (Optimization Backlog)

### TODO-1: `runonce=True/False` 双模式回归测试治理（最高 ROI）🔥

**核实情况**: 经过对 `strategies/` 与 `strategies_runonce/` 的全部 **119 对文件**逐一 diff，确认：

- 119 对文件中，**所有差异都仅是 `cerebro.run()` vs `cerebro.run(runonce=False)`**
- 策略类、参数、数据加载、断言阈值**完全相同**
- 这两套测试存在的目的是验证同一策略在事件驱动（`runonce=False`）和向量化（`runonce=True`，默认）两种执行模式下产生**一致**的结果——这是有价值的回归覆盖，不是无意义的重复

**问题**: 虽然测试目的有价值，但实现方式让相同的 CSV 加载、策略实例化、回测主循环全部跑了两遍，**累计耗时约占 Top 20 的 35%**。

**预计节省**: ≈ 60-80s

**方案选择**:

- [ ] **方案 A（推荐，长期）**: 用 `@pytest.mark.parametrize("runonce", [True, False])` 改造，单文件双参数化执行
  - 收益: CSV 解析、DataFrame 构造可在 fixture 中只做一次（`scope="module"`），策略实例和 `cerebro.run` 仍跑两次但其余开销减半
  - 工作量: 大（需重构 ~119 对文件，可脚本批量改写）
  - 风险: 中（需保证两种模式断言独立成功；若数值有微小差异需保留两套阈值）

- [ ] **方案 B（推荐，短期）**: 默认只跑 `strategies/`（runonce=True 默认模式），把 `strategies_runonce/` 标记为 `@pytest.mark.runonce_regression`，平时跳过，CI nightly 任务中跑
  - 收益: 立即减半相关测试时间
  - 工作量: 极小（一次性给目录加 marker）
  - 风险: 低（runonce 模式回归仍由 nightly 覆盖）

- [ ] **方案 C（不推荐）**: 完全删除 `strategies_runonce/` 副本
  - 风险高: 失去 runonce 路径的回归覆盖。**除非**改用更小的核心测试集来覆盖两种模式的等价性，否则不建议

**建议**: 短期落地方案 B（一两小时即可见效），中期推进方案 A（彻底消除重复 setup 开销）。

---

### TODO-2: 减小 `bond_merged_all_data.csv` 的全量加载（高 ROI）

**问题**: 4 个测试加载 66.7MB / 68 万行的 `bond_merged_all_data.csv`，未做任何裁剪。

**涉及测试**:

- [ ] `strategies_runonce/misc/test_16_cb_strategy.py` (9.33s)
- [ ] `strategies_runonce/misc/test_17_cb_monday_strategy.py` (5.60s)
- [ ] `strategies_runonce/special/test_04_simple_ma_multi_data.py` (6.59s)
- [ ] `strategies_runonce/special/test_02_multi_extend_data.py` (3.11s)
- [ ] 加上 `strategies/` 中的 4 个副本（总计 8 个文件）

**优化措施**:

- [ ] 在 `pd.read_csv()` 时增加 `nrows=` 或预过滤 dtype 到必要列
- [ ] 在 fixture 中只加载一次，多个用例复用（`scope="module"` 或 `"session"`）
- [ ] 评估能否构造一个小型替代数据集（如只取前 20,000 行存为 `bond_merged_test.csv`）

**预计节省**: ≈ 25s

---

### TODO-3: 优化 `tests/integration/test_trade_logger.py`（高 ROI）✅ 已完成

**实施记录** (2026-05-28):

- 引入 4 个 `scope="module"` fixture（json_logs / text_logs / selective_logs / multidata_logs），把 10 次回测压缩到 4 次
- 数据通过 `todate=2018-06-01` 限制到约 200 个交易日
- 用 `tmp_path_factory` 替代手写的 `tempfile.mkdtemp` + 清理样板

**实测**:

- 串行: 22.83s → 8.86s（节省 ~14s，61%）
- 并行 (-n 4): 同步降低

---

### TODO-4: 优化 `tests/unit/core/test_strategy_optimized.py`（高 ROI）

**问题**: 单个用例 20.84s，做参数优化跑了多次回测。

**优化措施**:

- [ ] 缩小参数空间（如 `range(5, 30, 2)` → `[5, 15, 25]`）
- [ ] 缩小数据量（截取部分 bar 即可验证优化路径）
- [ ] 拆分为 "正确性测试"（小数据快速跑）+ `@pytest.mark.slow` 大数据完整测试

**预计节省**: ≈ 18s

---

### TODO-5: 缩短策略回测数据范围 ✅ 已完成（首批）

**实施记录** (2026-05-28): 一次性缩短了 Top 10 慢策略测试的数据范围或 max_rows，并相应更新所有断言（保持每个策略 trade_count > 0）：

| 测试文件 | 旧配置 | 新配置 | 时长变化 |
| --- | --- | --- | --- |
| `breakout/test_09_dual_thrust_strategy.py` | 2020-01-01 to 2021-07-31 | 2020-01-01 to 2020-06-30 | 34.31s → 4.42s |
| `multi_indicator/test_12_abberation_strategy.py` | max_rows=50000 | max_rows=20000 | 26.17s → 5.01s |
| `trend_following/test_86_sunrise_ema_crossover_strategy.py` | 2024-06-01 to 2025-06-30 | 2024-06-01 to 2024-09-30 | 25.01s → 12.81s |
| `special/test_13_fei_strategy.py` | max_rows=50000 | max_rows=20000 | 13.52s → 一并降至 ~16s（4 个 RB889 测试合计） |
| `breakout/test_10_r_breaker_strategy.py` | max_rows=50000 | max_rows=20000 | 9.70s → 同上 |
| `special/test_14_hanse123_strategy.py` | max_rows=50000 | max_rows=20000 | 9.00s → 同上 |
| `trend_following/test_15_fenshi_ma_strategy.py` | data >= 2019-01-01 | data >= 2020-06-01 | 9.82s → 同上 |
| `misc/test_16_cb_strategy.py` | data > 2018-01-01 | data > 2020-06-01 | 10.73s → 一并降至 ~40s（3 个 bond_merged 测试） |
| `misc/test_17_cb_monday_strategy.py` | data > 2018-01-01 | data > 2020-06-01 | 5.25s → 同上 |
| `special/test_02_multi_extend_data.py` | data > 2018-01-01 | data > 2020-06-01 | 6.90s → 同上 |
| `trend_following/test_06_macd_ema_fase_strategy.py` | 2010-01-01 to 2020-12-31 | 2019-01-01 to 2019-12-31 | 7.40s → ~10s（4 个测试合计） |
| `trend_following/test_07_macd_ema_true_strategy.py` | 2019-01-01 to 2020-12-31 | 2019-01-01 to 2019-12-31 | 5.66s → 同上 |
| `volatility/test_08_kelter_strategy.py` | 2019-01-01 to 2020-12-31 | 2019-01-01 to 2019-12-31 | 5.62s → 同上 |
| `misc/test_11_sky_garden_strategy.py` | data >= 2020-01-01 | data >= 2020-06-01 | 4.35s → 同上 |

**整体效果（4 核并行，墙钟时间）**：181.38s → 159.70s（节省 ~22s，12%）

**关键约束**: 每个策略修改后均保持 `trade_count > 0` 的断言，并精确对齐新的 sharpe / annual_return / max_drawdown / final_value 等指标值。

**未做（剩余工作）**:

- `tests/unit/core/test_strategy_optimized.py` (24.29s) — 跑 16 × 40 = 640 次回测，CHKVALUES/CHKCASH 是硬编码列表，缩小参数范围需重算所有期望值，工作量较大暂缓
- `tests/special/test_04_simple_ma_multi_data.py` (13.94s) — 加载 66MB CSV 是主要成本，max_bonds=30 已优化，进一步优化需做 CSV 预过滤
- `tests/unit/core/test_parameter_performance.py` (8.63s) — 是性能基准测试，应迁移到独立 benchmark suite

---

### TODO-6: `RB889.csv` 大量重复加载（中 ROI）

**问题**: 9 个测试都加载 11.2MB / 17 万行的 RB889.csv，无 fixture 缓存。

**涉及测试** (按时间排序):

- [ ] test_12_abberation_strategy（已用 max_rows=50000）
- [ ] test_13_fei_strategy
- [ ] test_14_hanse123_strategy
- [ ] test_15_fenshi_ma_strategy
- [ ] test_10_r_breaker_strategy
- [ ] 加上 `strategies/` 副本

**优化措施**:

- [ ] 抽取 `tests/conftest.py` 提供 `rb889_data` fixture（`scope="session"`），所有用例复用 DataFrame
- [ ] 与 TODO-1 联动消除副本

**预计节省**: ≈ 15s

---

### TODO-7: `tests/unit/core/test_parameter_performance.py`（低 ROI）

**问题**: 10 个用例 5.60s，做参数系统性能基准测试。

**优化措施**:

- [ ] 标记为 `@pytest.mark.benchmark`，在 `pytest.ini` 中默认通过 `-m "not benchmark"` 跳过
- [ ] 保留在 CI 的 nightly 任务中

**预计节省**: ≈ 5s

---

### TODO-8: 缺失的数据文件（清洁性）

**问题**: 部分测试引用 `rb99.csv`、`rb2020F.csv` 但这两个文件**不在 `tests/datas/` 中**。

**涉及测试**:

- [ ] `strategies_runonce/volatility/test_08_kelter_strategy.py` (3.83s)
- [ ] `strategies_runonce/trend_following/test_07_macd_ema_true_strategy.py` (3.76s)
- [ ] `strategies/volatility/test_08_kelter_strategy.py` (2.47s)
- [ ] `strategies/trend_following/test_07_macd_ema_true_strategy.py` (2.51s)

**调查事项**:

- [ ] 搜索整个仓库确认数据文件实际位置（可能在测试目录其他位置）
- [ ] 如确实缺失，测试是如何通过的？fallback 路径？
- [ ] 整理 → 统一放入 `tests/datas/`

---

### TODO-9: 引入慢测试标记策略（基础设施）✅ 已完成 (2026-05-30)

**可行性结论**: 「每次开发运行控制在 3 分钟内」**可行且已落地**，但实现方式与本条目最初设想不同（详见下方实测复盘）。

**实测基线（2026-05-30，与本文档顶部 2026-05-28 的 177s 已严重过时）**:

| 范围 | 用例数 | 墙钟 (`-n 8`) | 累计 CPU |
| --- | --- | --- | --- |
| 全量 `tests` | 2,991 | **~611s (10 min)** | 4,703s |
| 仅 `tests/functional/strategies/` | 1,271 | ~550s | 4,404s (**94%**) |
| 其余全部（unit/integration/indicators/...） | 1,720 | **~98s (1.6 min)** | 299s |

**关键发现**: 1,036 个回归用例 inline 进 `strategies/` 之后，慢测试不再是「Top 50 个用例」，而是**整个 strategies 子树**（1,271 个用例、占 94% 的耗时）。按用例逐个打 `@pytest.mark.slow`（原计划给 Top 50 打标签）既治标不治本，又无法覆盖自动生成/会被重新生成的 inline 测试。

**为什么不用 `-m "not slow"` 作为快速回路**: 实测 `pytest tests -m "not slow" -n 8` 反而要 **~234s**——因为 `-m` 只是 deselect，pytest 仍会 **collect（import）** 那 1,271 个重型策略文件（仅 collection 就耗时约 52s），并未真正省掉导入开销。`--ignore=tests/functional/strategies` 直接跳过收集，才是真正的 ~98s。

**已落地方案（按耗时拆分 strategies 子树，而非整体跳过）**:

> 起初把整个 `strategies/` 子树标记为 slow（`make test-fast` 用 `--ignore` 跳过，~1.5 min）。但「完全不跑策略」改完代码心里没底，无法及时发现回归。**因此改为按单测文件实测耗时拆分**：只保留**最快的 ~35%** 在快速档（test-fast 照常跑），其余最慢的 ~65% 标 `slow`（test-fast 跳过），兼顾速度与回归覆盖。

1. **`tests/functional/strategies/.test_durations.json`（已提交）**: 记录每个策略测试文件的实测耗时（1,152 个文件）。由 `scripts/refresh_strategy_durations.py` 生成 / 刷新。
2. **`conftest.py` 数据驱动自动打标（不改任何测试用例）**: `pytest_collection_modifyitems` 读取 durations 文件，按 **35 分位**算阈值，给耗时 ≥ 阈值的策略文件动态加 `slow`（即只放行最快 ~35%）。
   - **新增 / 未知文件默认进快速档**（不标 slow），这样新写的或重新生成的策略测试每次 test-fast 都会跑到，最适合「改完看有没有引入 bug」。
   - durations 文件缺失时回退为「整棵 strategies 标 slow」，保证安全。
   - 阈值可调：`BT_SLOW_PERCENTILE=50 make test-fast` 放行最快 50%（更慢、覆盖更全）；`=25` 放行最快 25%（更快）。默认 35。
3. **`Makefile` 目标**:
   - `make test-fast` → `pytest tests -m "not slow" -n 8 -q`（全部非策略测试 + 最快的 ~35% 策略测试）
   - `make test-slow` → `pytest tests -m slow -n 8 -q`（test-fast 跳过的那最慢 ~65% 策略）
   - `make test-strategies` → 仅跑全部策略回归（~9 min）
   - `make test-all` → 全量（~10 min）
4. `pytest.ini` 的 `slow` marker 本来就已存在，无需新增。

**实测拆分结果（默认 p35）**:

| 档位 | 策略用例数 | `make test-fast` 墙钟 (`-n 8`) |
| --- | --- | --- |
| 最快 35%（保留在 test-fast，含全部非策略测试） | 461 / 1271 | **~216s (3.6 min)** |
| 最慢 65%（test-slow，提交前 / CI） | 810 / 1271 | 其余时间 |

**说明 / 取舍**: 同时跑 461 个策略测试 + 1,720 个非策略测试，`test-fast` 实测约 **3.6 分钟**（含约 20s 的 strategies 子树 collection 开销）。已接近 3 分钟目标——若要严格压到 3 分钟内，把环境变量调成 `BT_SLOW_PERCENTILE=25`（只跑最快 ~25% 策略，约 169s）；想要更全覆盖就调高百分位。日常开发按需选择。

**为什么用 `-m "not slow"` 而不是 `--ignore`**: 拆分后必须 collect 整棵 strategies 才能按文件区分快慢，所以这里接受 ~20s 的 collection 开销（换来跑一部分策略的回归价值）。`--ignore` 无法做到「只跑一部分文件」。

**刷新 durations**: 增删策略测试或耗时漂移后，运行 `python scripts/refresh_strategy_durations.py`（重测一次并重写 json），或 `--from-log <pytest --durations 日志>` 从已有日志解析。

**已知噪声**: `tests/unit/brokers/test_broker_refacto.py`、`test_comminfo_refactor.py` 中的几个 `*_performance` 用例在 `-n 8` 高并发下偶发超时失败（与本治理无关，单独跑均通过）。后续应给这类性能基准用例改用更宽松的阈值或迁出并行集。

---

### TODO-10: 优化指标级慢测试（低 ROI）

**问题**: 几个指标测试因算法复杂耗时较长。

| 用例 | 时长 | 原因 |
| --- | --- | --- |
| `test_ind_dm.py::test_run` | 2.65s | DM 指标包含多种衍生指标 |
| `test_ind_hurst.py::test_run` | 1.79s | Hurst 指数算法复杂 |
| `test_ind_minperiod.py::test_run` | 1.67s | 多个最小周期组合 |
| `test_ind_dma.py::test_run` | 1.52s | DMA 包含多 SMA |
| `test_ind_zlind.py::test_run` | 1.39s | 零滞后指标 |

**优化措施**:

- [ ] 检查是否有冗余的 `cerebro.run()` 调用
- [ ] 部分可改为 `radix=once` 直接计算后断言

**预计节省**: ≈ 4s（合计）

---

## 优化收益总览 (Expected Savings Summary)

| TODO | 工作量 | 预计节省 | ROI |
| --- | --- | --- | --- |
| TODO-1 副本测试治理（方案 B） | 小 | ≈ 60-80s | 🔥🔥🔥 |
| TODO-2 bond_merged 大文件优化 | 中 | ≈ 25s | 🔥🔥 |
| TODO-3 trade_logger 共享 fixture | 中 | ≈ 25s | 🔥🔥 |
| TODO-4 strategy_optimized 缩参 | 小 | ≈ 18s | 🔥🔥 |
| TODO-5 XAUUSD 缩周期 | 小 | ≈ 12-18s | 🔥 |
| TODO-6 RB889 fixture 缓存 | 中 | ≈ 15s | 🔥 |
| TODO-7 benchmark 标记 | 极小 | ≈ 5s | 🔥 |
| TODO-9 slow 标记基础设施 | 小 | ✅ 已完成：日常回路 ~10min→~1.5min | 🔥🔥🔥 |
| TODO-10 指标测试优化 | 中 | ≈ 4s | — |

**保守估计**: 实施 TODO-1 (方案B) + TODO-2/3/4/9 后，墙钟时间可从 **177s → 80-100s**（节省 40-55%）。

**激进估计**: 全部实施且采用 TODO-1 方案 A，墙钟时间可降至 **40-60s**（节省 65-78%）。

---

## 复现命令 (How to Reproduce)

```bash
# 完整 timing 数据采集
python -m pytest tests/ \
  --ignore=tests/functional/strategies_regression \
  --durations=0 -n 4 \
  -p no:cacheprovider 2>&1 | tee /tmp/bt_test_durations.log

# 分析脚本
python3 scripts/analyze_test_durations.py /tmp/bt_test_durations.log

# 提取每个文件用到的数据文件
ls -1 tests/functional/strategies_runonce/*/test_*.py \
  | python3 scripts/extract_test_data_files.py
```

数据采集环境：

- macOS / darwin
- Python (项目默认)
- pytest-xdist 并行: `-n 4`
- 排除目录: `tests/functional/strategies_regression`

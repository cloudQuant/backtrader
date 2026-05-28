# Official Backtrader Regression Failures

更新日期: 2026-05-28

## 当前状态

数据来源: `scripts/run_official_backtrader_strategy_regression.py --workers 8 --timeout 120`

| 指标 | 数量 |
| --- | ---: |
| 回归总数 | 1036 |
| 通过 | 1010 |
| 失败 | 26 |
| 通过率 | 97.5% |

## 失败类别分布

| 类别 | 数量 |
| --- | ---: |
| `mean_reversion` | 14 |
| `trend_following` | 7 |
| `forecasting` | 1 |
| `multi_indicator_system` | 1 |
| `options` | 1 |
| `pivot_fibonacci_system` | 1 |
| `volatility_systems` | 1 |

## 失败字段分布

| 字段 | 数量 |
| --- | ---: |
| `buy_count` | 8 |
| `final_value` | 7 |
| `rows` | 5 |
| `sell_count` | 2 |
| `win_count` | 2 |
| `sum_profit` | 1 |
| `unknown` | 1 |

## 失败症状分析

| 症状簇 | 数量 | 说明 |
| --- | ---: | --- |
| `trade_drift` | 8 | `buy_count`/`sell_count` 有交易但数量偏移 |
| `final_value_63` | 4 | `final_value` 精确相差约 63.0 |
| `final_value_other` | 3 | `final_value` 非 63.0 差异 |
| `rows_mismatch` | 5 | 输出行数不一致 |
| `win_count` | 2 | 胜利交易数差异 |
| `sell_count` | 2 | 卖出次数差异 |
| `sum_profit` | 1 | 盈亏汇总差异 |
| `trade_collapse` | 1 | `buy_count` 从 0 变为有交易 |

## 当前失败的 26 个策略

| 类别 | 策略目录 | 断言信息 |
| --- | --- | --- |
| `forecasting` | `0002_1003_forecastoscilator` | `final_value: expected=999233.0, got=999479.5` |
| `mean_reversion` | `0112_0352_exp_blautvi_tm` | `sell_count: expected=11, got=12` |
| `mean_reversion` | `0114_0354_exp_colorx2ma_x2` | `buy_count: expected=61, got=63` |
| `mean_reversion` | `0126_0401_exp_kwan_nrp` | `buy_count: expected=125, got=60` |
| `mean_reversion` | `0197_0990_i_amma` | `final_value: expected=1001516.1, got=1001579.1` |
| `mean_reversion` | `0200_1005_finetuningma` | `sum_profit: expected=-912.5, got=-849.5` |
| `mean_reversion` | `0231_rsi2_double_returns` | `buy_count: expected=145, got=115` |
| `mean_reversion` | `0255_0788_center_of_gravity_candle` | `rows: expected=242, got=253` |
| `mean_reversion` | `0268_0925_cci_histogram` | `rows: expected=5692, got=5892` |
| `mean_reversion` | `0273_1004_force_diversign` | `win_count: expected=13, got=12` |
| `mean_reversion` | `0302_1111_blau_ts_stochastic` | `sell_count: expected=82, got=81` |
| `mean_reversion` | `0303_1112_blau_tstochi` | `win_count: expected=92, got=91` |
| `mean_reversion` | `0304_1113_blau_ergodic_mdi` | `final_value: expected=1004361.6, got=1004424.6` |
| `mean_reversion` | `0305_1114_blau_csi` | `final_value: expected=1010690.5, got=1010753.5` |
| `mean_reversion` | `0320_1296_center_of_gravity` | `rows: expected=6101, got=6112` |
| `multi_indicator_system` | `0029_binary_wave` | `rows: expected=6090, got=6057` |
| `options` | `0005_gld_put_write_strategy` | `final_value: expected=1156220.0, got=1156314.7` |
| `pivot_fibonacci_system` | `0001_mostashar15_pivot` | `buy_count: expected=385, got=413` |
| `trend_following` | `0096_0976_laguerre_adx` | `buy_count: expected=11, got=9` |
| `trend_following` | `0100_0991_colorzerolaghlr` | `final_value: expected=1001432.3, got=1001369.3` |
| `trend_following` | `0101_0995_i_trend` | `final_value: expected=999754.7, got=999691.7` |
| `trend_following` | `0151_1292_candles_xsmoothed` | `rows: expected=6069, got=6098` |
| `trend_following` | `0196_0455_umnick_trader` | `final_value: expected=979840.1, got=979856.6` |
| `trend_following` | `0238_0740_adx_system` | `buy_count: expected=0, got=8` |
| `trend_following` | `0276_1106_t3_trix` | `buy_count: expected=403, got=227` |
| `volatility_systems` | `0033_1295_color_bb_candles` | `rows: expected=5926, got=6025` |

## 备注

- 部分 `final_value` 差异精确为 63.0，可能与 minperiod 计算或 prenext/next 边界处理有关
- `rows_mismatch` 类型的失败通常与 minperiod 不同导致输出行数变化有关
- `trade_drift` 类型的失败表明指标计算存在细微差异，导致信号触发时机偏移
- 已通过 master 分支验证，部分期望值可能需要根据 master 分支结果重新校准

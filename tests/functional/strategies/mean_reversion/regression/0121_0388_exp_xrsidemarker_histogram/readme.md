# 0388 Exp_XRSIDeMarker_Histogram — Backtrader 迁移

## 原始 EA
- 文件：`ea/0388_Exp_XRSIDeMarker_Histogram/Exp_XRSIDeMarker_Histogram.mq5`
- 指标：`ea/0388_Exp_XRSIDeMarker_Histogram/XRSIDeMarker_Histogram.mq5`
- 交易框架：`TradeAlgorithms.mqh` 单仓开/平模板

## 策略逻辑
1. 在 `H4` 信号周期上计算 `XRSIDeMarker_Histogram`
2. 指标主值为 `(RSI(IndPeriod) + 100 × DeMarker(IndPeriod)) / 2`
3. 对主值进行 `XMA` 平滑，得到用于交易决策的直方图主序列
4. 当 `TrendValue[1] < TrendValue[2]` 且 `TrendValue[0] >= TrendValue[1]` 时，触发做多并关闭空头
5. 当 `TrendValue[1] > TrendValue[2]` 且 `TrendValue[0] <= TrendValue[1]` 时，触发做空并关闭多头
6. 执行层维持单仓模型，并使用固定 `SL/TP`

## 参数映射

| MQL5 参数 | Backtrader 参数 | 默认值 | 说明 |
|-----------|----------------|--------|------|
| `MM` | `mm` | 0.1 | 手数/资金比例 |
| `MMMode` | `mm_mode` | LOT | 固定手数模式 |
| `StopLoss_` | `stop_loss_points` | 1000 | 止损点数 |
| `TakeProfit_` | `take_profit_points` | 2000 | 止盈点数 |
| `BuyPosOpen` | `buy_pos_open` | true | 允许做多 |
| `SellPosOpen` | `sell_pos_open` | true | 允许做空 |
| `BuyPosClose` | `buy_pos_close` | true | 允许平多 |
| `SellPosClose` | `sell_pos_close` | true | 允许平空 |
| `InpInd_Timeframe` | `signal_timeframe` | `H4` | 信号周期 |
| `IndPeriod` | `ind_period` | 14 | RSI / DeMarker 周期 |
| `HighLevel` | `high_level` | 60 | 高位阈值 |
| `LowLevel` | `low_level` | 40 | 低位阈值 |
| `XMA_Method` | `xma_method` | `SMA` | 平滑方法 |
| `XLength` | `x_length` | 5 | 平滑深度 |
| `XPhase` | `x_phase` | 15 | 平滑参数 |
| `SignalBar` | `signal_bar` | 1 | 信号偏移柱数 |

## 当前简化
- `TradeAlgorithms.mqh` 未直接引入，交易执行按单净仓语义本地实现
- `SmoothAlgorithms.mqh` 缺失；当前对 `MODE_SMA_` 直接实现，其他 `XMA` 方法使用低滞后递推平滑近似
- 原指标的彩色直方图缓冲未逐色复刻，当前仅保留 EA 实际使用的主值序列与三点转折判定

## 回测数据
- 品种：XAUUSD
- 执行周期：M15
- 信号周期：H4
- 数据文件：`examples/../../../datas/XAUUSD_M15.csv`

## 运行
```bash
cd examples/0388_exp_xrsidemarker_histogram
python run.py
```

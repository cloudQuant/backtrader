# 0378 Exp_ATR_Normalize_Histogram — Backtrader 迁移

## 原始 EA
- 文件：`ea/0378_Exp_ATR_Normalize_Histogram/Exp_ATR_Normalize_Histogram.mq5`
- 指标：`ea/0378_Exp_ATR_Normalize_Histogram/ATR_Normalize_Histogram.mq5`
- 交易框架：`TradeAlgorithms.mqh` 单仓开/平模板

## 策略逻辑
1. 在 `H4` 信号周期上计算 `ATR_Normalize_Histogram`
2. 指标主值为 `100 × XMA(close - low) / max(XMA(true range like range), point)`
3. 按主值与 `High/Middle/Low` 阈值关系生成颜色状态 `0/1/2/3/4`
4. 当上一信号柱颜色为 `0` 且当前不再为 `0` 时，触发做多并关闭空头
5. 当上一信号柱颜色为 `4` 且当前不再为 `4` 时，触发做空并关闭多头
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
| `MA_Method1` | `ma_method1` | `SMA` | 第一层平滑 |
| `Length1` | `length1` | 14 | 第一层长度 |
| `Phase1` | `phase1` | 15 | 第一层相位 |
| `MA_Method2` | `ma_method2` | `SMA` | 第二层平滑 |
| `Length2` | `length2` | 14 | 第二层长度 |
| `Phase2` | `phase2` | 15 | 第二层相位 |
| `inHighLevel` | `high_level` | 60 | 高位阈值 |
| `inMiddleLevel` | `middle_level` | 50 | 中位阈值 |
| `inLowLevel` | `low_level` | 40 | 低位阈值 |
| `SignalBar` | `signal_bar` | 1 | 信号偏移柱数 |

## 当前简化
- `TradeAlgorithms.mqh` 未直接引入，交易执行按单净仓语义本地实现
- `SmoothAlgorithms.mqh` 缺失；当前对 `SMA/LWMA` 直接实现，其余平滑方法使用低滞后递推平滑近似
- 当前保留指标实际供 EA 使用的主值和颜色状态，不复刻原始绘图缓冲细节

## 回测数据
- 品种：XAUUSD
- 执行周期：M15
- 信号周期：H4
- 数据文件：`examples/../../../datas/XAUUSD_M15.csv`

## 运行
```bash
cd examples/0378_exp_atr_normalize_histogram
python run.py
```

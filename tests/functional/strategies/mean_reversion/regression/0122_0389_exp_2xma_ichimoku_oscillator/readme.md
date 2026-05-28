# 0389 Exp_2XMA_Ichimoku_Oscillator — Backtrader 迁移

## 原始 EA
- 文件：`ea/0389_Exp_2XMA_Ichimoku_Oscillator/Exp_2XMA_Ichimoku_Oscillator.mq5`
- 指标：`indicators/1505_2XMA_Ichimoku_Oscillator/2XMA_Ichimoku_Oscillator.mq5`
- 辅助指标：`indicators/1505_2XMA_Ichimoku_Oscillator/XMA_Ichimoku.mq5`
- 交易框架：`TradeAlgorithms.mqh` 单仓开/平模板

## 策略逻辑
1. 在 `H4` 信号周期上计算 `2XMA_Ichimoku_Oscillator`
2. 子指标 `XMA_Ichimoku` 用最近 `Up_period / Dn_period` 的极值均值作为原始值，再做 `XMA` 平滑
3. 主指标取两条 `XMA_Ichimoku` 的差值，并根据正负区间内的升降方向生成颜色状态
4. 当颜色从 `3/0` 切到 `4/1` 时，触发做多并关闭空头
5. 当颜色从 `1/4` 切到 `0/3` 时，触发做空并关闭多头
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
| `Up_period1/Dn_period1` | `up_period1/dn_period1` | `6/6` | 第一条 XMA Ichimoku 周期 |
| `Up_period2/Dn_period2` | `up_period2/dn_period2` | `9/9` | 第二条 XMA Ichimoku 周期 |
| `XMA1_Method/XMA2_Method` | `xma1_method/xma2_method` | `SMA` | 平滑方法 |
| `XLength1/XLength2` | `x_length1/x_length2` | `25/80` | 平滑深度 |
| `XPhase` | `x_phase` | 15 | 平滑参数 |
| `SignalBar` | `signal_bar` | 1 | 信号偏移柱数 |

## 当前简化
- `TradeAlgorithms.mqh` 未直接引入，交易执行按单净仓语义本地实现
- `SmoothAlgorithms.mqh` 缺失；当前对 `MODE_SMA_` 直接实现，其他 `XMA` 方法使用低滞后递推平滑近似
- `XMA_Ichimoku` 的 `PriceShift/Shift` 绘图属性未保留，只保留信号生成所需核心数值

## 回测数据
- 品种：XAUUSD
- 执行周期：M15
- 信号周期：H4
- 数据文件：`examples/../../../datas/XAUUSD_M15.csv`

## 运行
```bash
cd examples/0389_exp_2xma_ichimoku_oscillator
python run.py
```

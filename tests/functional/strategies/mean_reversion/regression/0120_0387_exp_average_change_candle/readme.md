# 0387 Exp_AverageChangeCandle — Backtrader 迁移

## 原始 EA
- 文件：`ea/0387_Exp_AverageChangeCandle/Exp_AverageChangeCandle.mq5`
- 指标：`indicators/1498_AverageChangeCandle/AverageChangeCandle.mq5`
- 交易框架：`TradeAlgorithms.mqh` 单仓开/平模板

## 策略逻辑
1. 在 `H4` 信号周期上计算 `AverageChangeCandle`
2. 先对价格常量 `IPC1` 做第一层均线平滑，得到基准 `xma`
3. 再分别计算 `open/xma`、`high/xma`、`low/xma`、`close/xma` 的 `Pow` 次幂，并做第二层平滑
4. 由平滑后的四个值构造“变化蜡烛”，并用 `open/close` 关系生成颜色状态：`2` 看涨、`0` 看跌、`1` 中性
5. 当上一信号柱颜色为 `2` 且当前不再为 `2` 时，触发做多并关闭空头
6. 当上一信号柱颜色为 `0` 且当前不再为 `0` 时，触发做空并关闭多头
7. 执行层维持单仓模型，并使用固定 `SL/TP`

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
| `MA_Method1` | `ma_method1` | `LWMA` | 第一层平滑方法 |
| `Length1` | `length1` | 12 | 第一层平滑长度 |
| `Phase1` | `phase1` | 15 | 第一层平滑相位 |
| `IPC1` | `ipc1` | `PRICE_MEDIAN_` | 价格常量 |
| `MA_Method2` | `ma_method2` | `JJMA` | 第二层平滑方法 |
| `Length2` | `length2` | 5 | 第二层平滑长度 |
| `Phase2` | `phase2` | 100 | 第二层平滑相位 |
| `Pow` | `pow_value` | 5 | 幂次变换 |
| `SignalBar` | `signal_bar` | 1 | 信号偏移柱数 |

## 当前简化
- `TradeAlgorithms.mqh` 未直接引入，交易执行按单净仓语义本地实现
- `SmoothAlgorithms.mqh` 缺失；当前对 `LWMA/SMA` 直接实现，其余平滑方法使用低滞后递推平滑近似
- 当前保留指标实际供 EA 使用的颜色状态和变化蜡烛核心值，不复刻原始绘图属性

## 回测数据
- 品种：XAUUSD
- 执行周期：M15
- 信号周期：H4
- 数据文件：`examples/../../../datas/XAUUSD_M15.csv`

## 运行
```bash
cd examples/0387_exp_average_change_candle
python run.py
```

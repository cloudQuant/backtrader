# 0451 MACD_EA

## 策略来源
- MT5 EA: `ea/0451_MACD_EA/macd_ea.mq5`
- Backtrader 实现: `examples/0451_macd_ea/strategy_macd_ea.py`
- 运行脚本: `examples/0451_macd_ea/run.py`

## 核心逻辑
- 使用 `MACD(120, 260, 90)` 的交叉作为唯一开仓触发。
- 多单开仓条件：`MACD_MAIN[2] > MACD_SIGNAL[2]` 且 `MACD_MAIN[4] < MACD_SIGNAL[4]`。
- 空单开仓条件：`MACD_MAIN[2] < MACD_SIGNAL[2]` 且 `MACD_MAIN[4] > MACD_SIGNAL[4]`。
- 持仓后保留固定止损、固定止盈、半仓止盈和保本位逻辑；当出现反向 MACD 交叉时平仓。
- MT5 源码中虽然初始化了 `MAFast`、`MASlow`、`MAFilter`，但实际开平仓判断使用的是 `MACD` 信号，本迁移按源码实际执行路径实现。

## 参数映射
- `InpLots=1.0`
- `InpStopLoss=80`
- `InpTakeProfit=500`
- `InpProfitOne=70`
- `InpBreakeven=0`
- `MACDfast_ema_period=120`
- `MACDslow_ema_period=260`
- `MACDsignal_period=90`

## 回测数据
- 数据：`examples/../../../datas/XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` -> `2026-03-10 09:00:00`
- Bar shift：`15` 分钟

## 回测结果
- 初始资金：`100000.00`
- 期末权益：`105991.00`
- 净收益：`5991.00`
- 收益率：`5.99%`
- 平仓交易数：`37`
- 胜率：`54.05%`
- Profit Factor：`1.46`
- 最大回撤：`6.57%`
- Sharpe：`5.13`

## 对齐说明
- 使用单品种、单净仓的 Backtrader 仓位语义重建 MT5 逻辑。
- 半仓止盈通过 `self.close(size=half_size)` 实现，保留 MT5 中 `PositionClosePartial` 的核心效果。
- 止损/止盈/保本均按 K 线高低点触发，属于 Backtrader 常见的 bar-based 近似。

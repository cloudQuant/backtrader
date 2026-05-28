# 0445 Ichimoku

## 策略来源
- MT5 EA: `ea/0445_Ichimoku/ichimoku.mq5`
- Backtrader 实现: `examples/0445_ichimoku/strategy_ichimoku.py`
- 运行脚本: `examples/0445_ichimoku/run.py`

## 核心逻辑
- 使用 `Ichimoku` 指标的 `Tenkan-sen` / `Kijun-sen` 交叉判断方向。
- 当 `Tenkan[1] < Kijun[0]` 且 `Tenkan[0] >= Kijun[0]`，同时当前收盘价高于 `Senkou Span B` 时触发做多信号。
- 当 `Tenkan[1] > Kijun[0]` 且 `Tenkan[0] <= Kijun[0]`，同时当前收盘价低于 `Senkou Span A` 时触发做空信号。
- 始终只保留单一净头寸；反向信号出现时仅平掉对手仓，不叠加新仓。
- 迁移版保留分方向 `SL/TP` 与 `trailing stop`，并保留可选交易时段过滤参数。

## 参数映射
- `Lots=0.10`
- `StopLossBuy=100`
- `TakeProfitBuy=300`
- `StopLossSell=100`
- `TakeProfitSell=300`
- `TrailingStopBuy=50`
- `TrailingStopSell=50`
- `TrailingStep=5`
- `TenkanSen=9`
- `KijunSen=26`
- `SenkouSpanB=52`

## 回测数据
- 数据：`examples/../../../datas/XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` -> `2026-03-10 09:00:00`
- Bar shift：`15` 分钟

## 首轮回测结果
- 期初权益：`100000.00`
- 期末权益：`102184.80`
- 净收益：`2184.80`
- 平仓笔数：`294`
- 胜率：`51.36%`
- Profit Factor：`1.18`
- 最大回撤：`1.51%`

## 对齐说明
- MT5 源码通过 `CalculateAllPositions()==0` 约束单品种单仓；迁移版直接使用 Backtrader 单净仓语义实现同等约束。
- MT5 以指标值和当前 bar 时间判断开仓，并在反向信号时只平对手仓；迁移版保留同一流程。
- MT5 的固定止损止盈由交易服务器处理；迁移版在 `next()` 中按 bar 高低点近似执行，并保留源码中的分方向 trailing 规则。
- 默认 `lFlagUseHourTrade=false`，因此交易时段过滤默认不生效；迁移版仍保留对应参数。

## 验证状态
- 当前已完成可运行迁移目录、主逻辑映射与非 `python` 类命令方式的运行验证。
- 首轮回测已通过 `bash run_example_backtest.sh 0445` 完成结果回写。

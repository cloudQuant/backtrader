# 0406 Exp_Sar_Tm_Plus

## 策略来源
- MT5 EA: `ea/0406_Exp_Sar_Tm_Plus/exp_sar_tm_plus.mq5`
- Backtrader 实现: `examples/0406_exp_sar_tm_plus/strategy_exp_sar_tm_plus.py`
- 运行脚本: `examples/0406_exp_sar_tm_plus/run.py`

## 核心逻辑
- 使用 `H4` 级别 `Parabolic SAR` 作为信号层，基础回测数据仍为 `M15`。
- 当 `SAR` 从下向上翻转时触发多头开仓并关闭空头；从上向下翻转时触发空头开仓并关闭多头。
- 支持按持仓时长 `nTime=240` 分钟强制平仓。
- 保留固定 `SL/TP`。
- 当前迁移版以单仓语义实现，不复现外部 `TradeAlgorithms.mqh` 的账户级手数与执行细节。

## 参数映射
- `MM=0.1`
- `MMMode=LOT`
- `StopLoss_=1000`
- `TakeProfit_=2000`
- `Deviation_=10`
- `BuyPosOpen=true`
- `SellPosOpen=true`
- `BuyPosClose=true`
- `SellPosClose=true`
- `TimeTrade=true`
- `nTime=240`
- `InpInd_Timeframe=PERIOD_H4`
- `SarStep=0.02`
- `SarMaximum=0.2`
- `SignalBar=1`
- 迁移版额外固定：`lot=0.10`

## 回测数据
- 数据：`examples/../../../datas/XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` -> `2026-03-10 09:00:00`
- Base bar shift：`15` 分钟
- 信号层：`M15 -> H4` 重采样

## 对齐说明
- 原版通过外部 `TradeAlgorithms.mqh` 封装 `BuyPositionOpen / SellPositionOpen / BuyPositionClose / SellPositionClose`；仓库内未包含该库源码，因此迁移版按 `OnTick()` 暴露出的显式信号流做最小可运行复现。
- 原版 `MM/MMMode` 会动态决定手数；迁移版固定使用配置里的 `lot`。
- 当前目录已完成可运行迁移，详细回测结果待后续通过非 `python` 类命令补录。

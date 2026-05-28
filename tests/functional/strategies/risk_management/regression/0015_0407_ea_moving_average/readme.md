# 0407 EA_移动平均。

## 策略来源
- MT5 EA: `ea/0407_EA_移动平均。/ea_moving_average.mq5`
- Backtrader 实现: `examples/0407_ea_moving_average/strategy_ea_moving_average.py`
- 运行脚本: `examples/0407_ea_moving_average/run.py`

## 核心逻辑
- 主流程为标准单仓切换：`有仓 -> CheckForClose()`，`无仓 -> CheckForOpen()`。
- 开仓使用两组均线：
  - 多头开仓：K 线实体向上穿越 `Buy Open MA`
  - 空头开仓：K 线实体向下穿越 `Sell Open MA`
- 平仓使用两组独立均线：
  - 多头平仓：K 线实体向下穿越 `Buy Close MA`
  - 空头平仓：K 线实体向上穿越 `Sell Close MA`
- `ConsiderPriceLastOut=true` 时，要求最新入场价格相对上次离场价满足方向约束。
- 原版支持基于 `MaximumRisk` / `DecreaseFactor` 的动态手数；迁移版为了保持样例一致性，固定用 `lot` 近似。

## 参数映射
- `MaximumRisk=0.02`
- `DecreaseFactor=3`
- `MovingPeriodBuyOpen=30`
- `MovingShiftBuyOpen=3`
- `MovingPeriodBuyClose=14`
- `MovingShiftBuyClose=3`
- `MovingPeriodSellOpen=30`
- `MovingShiftSellOpen=0`
- `MovingPeriodSellClose=20`
- `MovingShiftSellClose=2`
- `UseBuy=true`
- `UseSell=true`
- `ConsiderPriceLastOut=true`
- `m_magic=15489`
- 迁移版额外固定：`lot=0.10`

## 回测数据
- 数据：`examples/../../../datas/XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` -> `2026-03-10 09:00:00`
- Base bar shift：`15` 分钟

## 对齐说明
- 原版 `SelectPosition()` 仅在 `hedging/netting` 差异上切换取仓方式，但整体仍保持同品种同 magic 单仓；迁移版保持同样单仓语义。
- 原版 `TradeSizeOptimized()` 会根据可用保证金、连续亏损次数和 `DecreaseFactor` 动态调整手数；迁移版暂用固定 `lot` 近似，不复现账户级风险管理。
- 当前目录已完成可运行迁移，详细回测结果待后续通过非 `python` 类命令补录。

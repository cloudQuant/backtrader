# 0535 MACD_Stochastic

## 策略概述

该策略是对 MT5 EA `0535_MACD_Stochastic` 的 Backtrader 迁移版本。

- 使用 `MACD` 金叉/死叉作为主信号
- 可选 `Stochastic` 过滤
- 只在预设的三个时间窗口内允许开仓
- 支持最大持仓数与保本/追踪止损

## 核心逻辑

1. 当 `MACD` 金叉发生在零轴下方时，若 `Stochastic` 过滤通过，则做多。
2. 当 `MACD` 死叉发生在零轴上方时，若 `Stochastic` 过滤通过，则做空。
3. 开仓只允许发生在三个固定时间窗口内。
4. 持仓达到指定盈利后，可把止损推进到 no-loss 区域，并继续 trailing。

## 迁移说明

- 原版允许同方向多仓，迁移版保留 `max_positions` 参数，但当前实现以单净头寸近似。
- 原版时间窗口比较基于时分；迁移版保留相同粒度逻辑。

## 运行方式

```bash
python run.py
```

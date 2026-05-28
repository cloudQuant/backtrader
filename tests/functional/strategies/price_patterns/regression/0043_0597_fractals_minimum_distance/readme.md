# 0597 分形最小距离

## 策略概述

该策略是对 MT5 EA `0597_分形最小距离` 的 Backtrader 迁移版本。

- 使用 `signal_bar` 位置上的分形作为信号来源
- 上分形出现时平多并尝试做空
- 下分形出现时平空并尝试做多
- 仅当最近上下分形距离达到最小阈值时入场

## 核心逻辑

1. 检测 `signal_bar` 位置是否形成上分形或下分形。
2. 记录最近 `PrevUpper / PrevLower`。
3. 只有当 `abs(PrevUpper - PrevLower) >= distance` 时才允许开仓。
4. 出现相反分形时先平旧方向，再切换到新方向。

## 迁移说明

- 原 EA 使用 `MoneyFixedMargin` 按风险计算手数；迁移版简化为固定手数。
- 原版无固定 `SL/TP`；迁移版保留无固定保护价的原始行为。

## 运行方式

```bash
python run.py
```

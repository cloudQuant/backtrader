# 0560 Trade_in_Channel

## 策略概述

该策略是对 MT5 EA `0560_Trade_in_Channel` 的 Backtrader 迁移版本。

- 基于固定长度价格通道的反转交易
- 使用 ATR 作为初始保护止损参考
- 持仓期间使用 trailing stop

## 核心逻辑

1. 计算最近 `r_channel` 根 K 线的上轨、下轨以及 `pivot`。
2. 若前一根 K 线触碰上轨或位于上轨下方但高于 `pivot`，则视作通道上边界反转卖出信号。
3. 若前一根 K 线触碰下轨或位于下轨上方但低于 `pivot`，则视作通道下边界反转买入信号。
4. 持仓后若再次触碰相反边界则平仓，否则按 trailing stop 管理。

## 迁移说明

- 原版含有基于历史连续亏损的动态手数缩减与风险模型；迁移版保留了一个简化的 `lots_on_history` 近似版本。
- 原版函数名 `isOpenBuy()` 实际触发的是卖出反转，迁移版保留了这一行为语义。

## 运行方式

```bash
python run.py
```

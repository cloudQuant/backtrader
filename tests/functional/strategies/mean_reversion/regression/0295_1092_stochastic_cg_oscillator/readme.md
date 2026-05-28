# 1092 Exp_StochasticCGOscillator

## 策略概述

该示例是对 MT5 EA `1092_Exp_StochasticCGOscillator` 的 Backtrader 迁移版本。
EA 在 `H8` 周期上读取 `StochasticCGOscillator` 主线与其触发线，并依据原始 EA 的交叉规则执行开平仓。

## 原始信号逻辑

1. 指标主线为 `Stochastic CG Oscillator`
2. 信号线为 `Trigger = 0.96 * (StocCG[bar-1] + 0.02)`
3. 若上一根 `Ind > Sign` 且当前根 `Ind <= Sign`，则触发做多并允许空头平仓
4. 若上一根 `Ind < Sign` 且当前根 `Ind >= Sign`，则触发做空并允许多头平仓
5. 默认使用固定止损与止盈

## 指标迁移说明

`StochasticCGOscillator` 直接按源码重建：

- 先以 `HL2` 计算重心 `CG`
- 再对最近 `Length` 个 `CG` 做归一化
- 对最近 4 个归一化值做加权平均
- 将结果线性映射到 `[-1, 1]`
- 触发线使用上一根主线值构造

## 主要参数

- `length`
- `signal_bar`
- `stop_loss`
- `take_profit`
- `size`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H8`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 回测结果

- 样本区间：`2025-12-03 01:15:00` - `2026-03-10 09:00:00`
- 成交笔数：`26`
- 净收益：`626.70`
- 胜率：`61.54%`
- 最大回撤：`3.63%`

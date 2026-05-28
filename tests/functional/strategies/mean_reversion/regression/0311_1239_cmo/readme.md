# 1239 CMO

## 策略概述

该策略是对 MT5 EA `1239_Exp_CMO` 的 Backtrader 迁移版本。
原 EA 调用 `CMO` 指标，并依据 `CMO` 在零轴上下的翻转来执行反手交易。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 对选定价格先计算一次 `MA(Length, Method)`
3. 对相邻 `MA` 差分拆出 `Bulls` 与 `Bears`
4. 在 `Length` 窗口内分别累加正负动量
5. 计算 `CMO = (SumBulls - SumBears) / (SumBulls + SumBears) * 100`
6. 当 `CMO` 从负转正时做多；从正转负时做空

## 主要参数

- `indicator_minutes`
- `length`
- `method`
- `price`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

原指标虽然以云带形式绘制，但 EA 实际只读取主数值 buffer。
本迁移版直接重建该主 buffer，并按零轴翻转规则执行交易。

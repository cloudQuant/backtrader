# 1233 MAMA

## 策略概述

该策略是对 MT5 EA `1233_Exp_MAMA` 的 Backtrader 迁移版本。
原 EA 使用 `MAMA_Optim` 指标，并在 `MAMA` 与 `FAMA` 交叉时执行反手交易。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 按原 `MAMA_Optim` 公式计算 `MAMA`
3. 基于同一自适应系数递推 `FAMA`
4. 当 `MAMA` 自下向上穿越 `FAMA` 时做多
5. 当 `MAMA` 自上向下穿越 `FAMA` 时做空

## 主要参数

- `indicator_minutes`
- `fast_limit`
- `slow_limit`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

本迁移版优先复用了仓内 `MAMA/FAMA` 参考实现的 Hilbert 递推思路，
并按原 EA 的双线交叉逻辑执行交易。

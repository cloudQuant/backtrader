# 1226 ADX_Smoothed

## 策略概述

该策略是对 MT5 EA `1226_Exp_ADX_Smoothed` 的 Backtrader 迁移版本。
原 EA 使用 `ADX_Smoothed` 指标，并在平滑后的 `DI+` 与 `DI-` 交叉时执行反手交易。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 先计算标准 `+DI / -DI / ADX`
3. 按原指标的两级平滑公式继续平滑 `DI+ / DI- / ADX`
4. 当平滑后的 `DI+` 自下向上穿越 `DI-` 时做多
5. 当平滑后的 `DI+` 自上向下跌破 `DI-` 时做空

## 主要参数

- `indicator_minutes`
- `adx_period`
- `alpha1`
- `alpha2`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

原 EA 实际交易只依赖平滑后的 `DI+` 与 `DI-` 两条线，
虽然指标还会输出 `ADX` 主线，但它不参与开平仓判定。

# 1227 DSSBressert

## 策略概述

该策略是对 MT5 EA `1227_Exp_DSSBressert` 的 Backtrader 迁移版本。
原 EA 使用 `DSSBressert` 指标，并在随机云颜色切换时执行反手交易。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 先计算价格在 `Sto_period` 窗口中的随机位置并做 EMA 平滑，得到 `MIT`
3. 再对 `MIT` 做一次同类随机归一化与 EMA 平滑，得到 `DSS`
4. 当 `DSS` 自下向上穿越 `MIT` 时做多
5. 当 `DSS` 自上向下穿越 `MIT` 时做空

## 主要参数

- `indicator_minutes`
- `ema_period`
- `sto_period`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

云颜色切换在原 EA 中本质上等价于 `DSS` 与 `MIT` 两条线的交叉。
本迁移版直接重建这两条核心 buffer 后再按原规则交易。

# 1228 AnchoredMomentum

## 策略概述

该策略是对 MT5 EA `1228_Exp_AnchoredMomentum` 的 Backtrader 迁移版本。
原 EA 直接读取 `AnchoredMomentum` 主线，并在突破上下阈值时执行交易。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 按原指标公式计算 `SMA` 与 `EMA`
3. 构建动量主线：`100 * (EMA / SMA - 1)`
4. 主线向上突破 `UpLevel` 时做多
5. 主线向下跌破 `DnLevel` 时做空

## 主要参数

- `indicator_minutes`
- `mom_period`
- `smooth_period`
- `applied_price`
- `up_level`
- `dn_level`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

原始 `AnchoredMomentum.mq5` 源码中 `SmoothPeriod` 虽然对外暴露，
但实际 `EMA_Handle` 仍然使用 `MomPeriod`，本迁移版保持这一行为以对齐原 EA。

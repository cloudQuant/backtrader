# 1223 ColorMETRO

## 策略概述

该策略是对 MT5 EA `1223_Exp_ColorMETRO` 的 Backtrader 迁移版本。
原 EA 使用 `ColorMETRO` 指标，并在云颜色切换时执行反手交易。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 计算 `RSI`
3. 用 `StepSizeFast` 与 `StepSizeSlow` 分别构造两条阶梯带状线
4. 当快线 `MPlus` 上穿慢线 `MMinus` 时做多
5. 当快线 `MPlus` 下穿慢线 `MMinus` 时做空

## 主要参数

- `indicator_minutes`
- `period_rsi`
- `step_size_fast`
- `step_size_slow`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

原 EA 实际交易只读取 `ColorMETRO` 的前两条云边界线，
本迁移版按原指标公式重建 `MPlus/MMinus` 后执行同样的交叉交易。

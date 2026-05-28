# 1225 AML

## 策略概述

该策略是对 MT5 EA `1225_Exp_AML` 的 Backtrader 迁移版本。
原 EA 使用 `ColorAML` 指标，并在线方向变化导致颜色状态切换时执行反手交易。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 基于分形区间范围估算 `dim`
3. 用 `dim` 生成自适应平滑系数 `alpha`
4. 递推 `AML` 主线并在变化不足阈值时保持原值
5. 当颜色状态切换到 `2` 时做多
6. 当颜色状态切换到 `0` 时做空

## 主要参数

- `indicator_minutes`
- `fractal`
- `lag`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

原 EA 实际交易只读取 `ColorAML` 的颜色索引 buffer。
本迁移版先完整重建 `AML` 主线，再导出与原 EA 一致的颜色状态进行交易。

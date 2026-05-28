# 1214 TMA

## 策略概述

该策略是对 MT5 EA `1214_Exp_TMA` 的 Backtrader 迁移版本。
原 EA 使用 `TMA` 三角均线，并在收盘价越过 `TMA ± 突破级别` 后、下一根确认回穿时开仓。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 计算三角加权移动平均 `TMA`
3. 为多空方向分别叠加 `up_level_points / dn_level_points`
4. 当上一根收盘价已突破阈值而当前收盘价回到阈值内时触发交易

## 主要参数

- `indicator_minutes`
- `length`
- `up_level_points`
- `dn_level_points`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

这里不是简单的价格上穿/下穿均线，而是对 `TMA` 通道外突破后的回归进行判定。
本迁移版按原 EA 的 `Close[1]` 与 `Close[0]` 相对阈值的位置关系实现。

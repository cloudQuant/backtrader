# 1209 FigurelliSeries

## 策略概述

该策略是对 MT5 EA `1209_Exp_FigurelliSeries` 的 Backtrader 迁移版本。
原 EA 只在固定开仓时刻入场，并在固定平仓时刻或越界时间平仓，方向由 `FigurelliSeries` 直方图相对零轴的位置决定。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `M30`
2. 构建一组不同周期的移动平均
3. 统计收盘价高于/低于各 MA 的数量差，得到 `FigurelliSeries`
4. 在固定 `start_hour:start_minute` 依据直方图正负开仓
5. 在 `stop_hour:stop_minute` 及其后，或时间回到开仓小时前时平仓

## 主要参数

- `start_period`
- `step`
- `total`
- `start_hour`
- `start_minute`
- `stop_hour`
- `stop_minute`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

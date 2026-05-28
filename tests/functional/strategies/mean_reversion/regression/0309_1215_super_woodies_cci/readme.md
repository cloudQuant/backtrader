# 1215 SuperWoodiesCCI

## 策略概述

该策略是对 MT5 EA `1215_Exp_SuperWoodiesCCI` 的 Backtrader 迁移版本。
原 EA 使用 `SuperWoodiesCCI` 指标直方图在零轴上下的切换作为交易信号。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 计算 `CCI` 与 `TCCI`
3. 将主 `CCI` 复制到 `HistBuffer`
4. 按连续 6 根同号柱构造 `ColorHistBuffer`
5. 当 `HistBuffer` 穿越零轴时开平仓

## 主要参数

- `indicator_minutes`
- `cci_period`
- `tcci_period`
- `applied_price`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

虽然指标同时输出 `CCI`、`TCCI` 与颜色直方图，但原 EA 实际只读取 `buffer 2` 的直方图值做零轴突破判定。
本迁移版保留这一行为。

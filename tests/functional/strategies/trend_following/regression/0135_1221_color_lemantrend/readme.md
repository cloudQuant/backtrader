# 1221 ColorLeManTrend

## 策略概述

该策略是对 MT5 EA `1221_Exp_ColorLeManTrend` 的 Backtrader 迁移版本。
原 EA 使用 `ColorLeManTrend` 指标，在多空趋势带发生颜色切换时执行反手交易。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 分别计算 `Min / Midle / Max` 三个窗口的最高价与最低价
3. 构造 `HH = 3 * High - (maxMin + maxMid + maxMax)` 与 `LL = (minMin + minMid + minMax) - 3 * Low`
4. 对 `HH/LL` 使用 `EMA(PeriodEMA)` 平滑，得到 `Bulls/Bears`
5. 当 `Bulls` 与 `Bears` 相对位置切换时生成买卖信号

## 主要参数

- `indicator_minutes`
- `min_period`
- `middle_period`
- `max_period`
- `ema_period`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

原 EA 只读取指标前两个 buffer 并检测其交叉。
本迁移版按原始 `HH/LL + EMA` 公式重建两条线后执行等价交易规则。

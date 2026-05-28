# 1217 TrendEnvelopes

## 策略概述

该策略是对 MT5 EA `1217_Exp_TrendEnvelopes` 的 Backtrader 迁移版本。
原 EA 使用 `TrendEnvelopes` 趋势包络线指标，在彩色点出现时开仓，并在仅剩趋势线时执行反向仓平仓。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 计算 `MA` 与 `ATR`
3. 构造上/下趋势带 `UpTrend/DownTrend`
4. 在趋势翻转时生成 `UpSignal/DownSignal` 箭头
5. 若存在箭头则开仓；若无箭头但存在反向趋势线，则只执行平仓

## 主要参数

- `indicator_minutes`
- `ma_period`
- `ma_method`
- `deviation_pct`
- `atr_period`
- `atr_sensitivity`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

该 EA 与简单交叉类不同，除了箭头开仓外，还包含“只有趋势线时关闭反向仓位”的逻辑。
本迁移版保留了这一行为。

# 1230 MACD_Xtr

## 策略概述

该策略是对 MT5 EA `1230_Exp_MACD_Xtr` 的 Backtrader 迁移版本。
原 EA 直接读取 `MACD_Xtr` 的颜色状态 buffer，
绿色柱出现时做多，红色柱出现时做空，中性颜色时平仓。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 计算 `MACD(fast, slow, signal=5)` 主线
3. 按 `ATR/StDev/Volume` 构建波动率阈值并做前沿/阻尼平滑
4. 当 `MACD > +level` 时状态记为 `2`
5. 当 `MACD < -level` 时状态记为 `0`
6. 其余为 `1`，表示中性并触发平仓

## 主要参数

- `indicator_minutes`
- `fast_ma`
- `slow_ma`
- `source`
- `source_period`
- `front_period`
- `back_period`
- `x_volatility`
- `sens`
- `volume_type`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

默认配置保持原 EA 的 `ATR` 波动率源。
本迁移版直接重建 EA 实际读取的颜色状态 buffer，而不是仅依据普通 MACD 交叉交易。

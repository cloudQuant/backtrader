# 1231 TrendValue

## 策略概述

该策略是对 MT5 EA `1231_Exp_TrendValue` 的 Backtrader 迁移版本。
原 EA 使用 `TrendValue` 指标的彩色钻石箭头作为开仓信号，
并使用上下趋势轨道 buffer 辅助平掉反向仓位。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 基于 `EMA(high)`、`EMA(low)` 与 `ATR` 构建上下趋势带
3. 当价格突破上一根趋势带时切换趋势方向
4. 当新一段上行趋势首次出现时产生买入钻石
5. 当新一段下行趋势首次出现时产生卖出钻石

## 主要参数

- `indicator_minutes`
- `ma_period`
- `shift_percent`
- `atr_period`
- `atr_sensitivity`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

本迁移版直接重建 EA 实际读取的四个 buffer：
`up_trend`、`dn_trend`、`up_signal`、`dn_signal`，
因此交易逻辑与原 MT5 EA 的开平仓判定保持一致。

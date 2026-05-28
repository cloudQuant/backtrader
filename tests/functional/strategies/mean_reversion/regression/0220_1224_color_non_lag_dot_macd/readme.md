# 1224 ColorNonLagDotMACD

## 策略概述

该策略是对 MT5 EA `1224_Exp_ColorNonLagDotMACD` 的 Backtrader 迁移版本。
原 EA 使用 `ColorNonLagDotMACD` 指标，默认按 `MACD` 与 `Signal` 的相对位置切换交易。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 分别构建快线与慢线 `NonLagDot`
3. 用二者差值得到 `MACD`
4. 对 `MACD` 再做信号线平滑
5. 按 `mode` 执行零轴突破、直方图扭转、信号线扭转或 `MACD/Signal` 交叉交易

## 主要参数

- `mode`
- `indicator_minutes`
- `price`
- `filter_value`
- `deviation`
- `fast_type`
- `fast_length`
- `slow_type`
- `slow_length`
- `signal_ma`
- `signal_method`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

本迁移版优先对齐原 EA 默认配置 `mode=3 (MACDdisposition)`，
并保留其余三种模式的等价交易判定。

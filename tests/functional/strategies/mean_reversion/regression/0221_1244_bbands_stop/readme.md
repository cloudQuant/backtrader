# 1244 BBands Stop

## 策略概述

该策略是对 MT5 EA `1244_Exp_BBands_Stop` 的 Backtrader 迁移版本。
原 EA 调用 `BBands_Stop_v1` 指标，在主线收盘且指标方向发生切换时执行反手/开仓。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 在重采样后的收盘价上计算 `Bollinger Bands`
3. 按 `BBands_Stop_v1` 的 `MRisk = 0.5 * (MoneyRisk - 1)` 规则重建上下 stop buffer
4. 当最近一个已完成指标柱由空头 buffer 切换到多头 buffer 时做多
5. 当最近一个已完成指标柱由多头 buffer 切换到空头 buffer 时做空
6. 保留固定止损止盈参数，以保持与现有示例一致的回测接口

## 主要参数

- `indicator_minutes`
- `length`
- `deviation`
- `money_risk`
- `signal_bar`
- `stop_loss_points`
- `take_profit_points`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

原 MT5 版本依赖 `BBands_Stop_v1.ex5` 自定义指标，并通过读取其 `UpTrendBuffer/DownTrendBuffer` 的前后状态变化来确认信号。
本迁移版直接在 Python 中等价重建 `BBands_Stop_v1` 的核心 stop 线与方向切换逻辑，以便在 Backtrader 中独立运行。

# 1218 StepSto_v1

## 策略概述

该策略是对 MT5 EA `1218_Exp_StepSto_v1` 的 Backtrader 迁移版本。
原 EA 使用 `StepSto_v1` 的 `Fast/Slow` 两条随机振荡线，并用 `Slow` 线相对 50 轴的位置过滤方向。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 计算 `ATR`
3. 按原始递推逻辑构造 `linemin / linemax / linemid`
4. 将结果映射为 `Fast` 与 `Slow` 两条 `0-100` 随机线
5. 当 `Slow > 50` 且 `Fast` 下穿 `Slow` 时做多；当 `Slow < 50` 且 `Fast` 上穿 `Slow` 时做空

## 主要参数

- `indicator_minutes`
- `kfast`
- `kslow`
- `period_atr`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

原 EA 的交易规则以紫色 `Slow` 线为方向过滤器，橙色 `Fast` 线对其突破作为触发条件。
本迁移版按原始 ATR 自适应 step 递推重建 `Fast/Slow`。

# 1234 AdaptiveRenko

## 策略概述

该策略是对 MT5 EA `1234_Exp_AdaptiveRenko` 的 Backtrader 迁移版本。
原 EA 基于 `AdaptiveRenko` 指标的 `Support/Resistance` 趋势 buffer，
在趋势方向切换时执行反手交易。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 用 `ATR` 或 `StdDev` 计算自适应砖块宽度
3. 递推更新 `Up/Dn` Renko 通道边界
4. 当 `UpTrendBuffer` 新出现时做多
5. 当 `DnTrendBuffer` 新出现时做空

## 主要参数

- `indicator_minutes`
- `k`
- `indicator_mode`
- `vlt_period`
- `price_mode`
- `wide_min`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

默认配置保持原 EA 的 `ATR + Close` 组合。
如果需要测试 `HighLow` 或 `StdDev` 版本，可直接修改 `config.yaml`。

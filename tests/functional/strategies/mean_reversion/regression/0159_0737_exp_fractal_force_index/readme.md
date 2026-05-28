# 0737 Exp_Fractal_Force_Index

## 策略概述

该策略是对 MT5 EA `0737_Exp_Fractal_Force_Index` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 重建 `Fractal_Force_Index` 指标
- 仅在指标时间框架新 bar 收盘后判断信号
- 指标上穿零轴做多，下穿零轴做空
- 反向穿越时平掉相反持仓
- 固定 `SL/TP`

## 核心逻辑

1. 在 `indicator_timeframe_minutes` 上重建 `Fractal_Force_Index`。
2. 指标从 `<= high_level` 上穿到 `> high_level` 时产生多头信号。
3. 指标从 `>= low_level` 下穿到 `< low_level` 时产生空头信号。
4. `trend=direct` 时顺势交易；如需要，可切换 `trend=against` 做反向解释。
5. 进场后按固定止损止盈管理仓位。

## 指标重建说明

- 先对选定价格序列计算分形维度相关的自适应速度 `speed`
- 再按 `speed` 对价格序列做均线平滑
- 最后使用 `volume * (Fractal_MA - Fractal_MA_prev)` 得到 `Force_Index`

## 主要参数

- `e_period`
- `normal_speed`
- `ma_method`
- `price_type`
- `volume_type`
- `trend`
- `high_level`
- `low_level`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。

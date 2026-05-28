# 1102 BW-wiseMan-1

## 策略概述

该示例是对 MT5 EA `1102_Exp_BW-wiseMan-1` 的 Backtrader 迁移版本。
当前版本沿用仓库标准验证数据 `XAUUSD_M15.csv`，复刻 `BW-wiseMan-1` 指标输出的彩色菱形信号，以及 `retrogradely` 对交易方向的翻转逻辑。

## 核心逻辑

1. 使用 `Alligator` 的 `jaw / teeth / lips` 三条线作为趋势结构参考
2. 使用 `ATR(15)` 生成信号标记偏移量
3. 当 K 线整体位于三条线之上且满足局部高点条件时生成原始卖出信号
4. 当 K 线整体位于三条线之下且满足局部低点条件时生成原始买入信号
5. `retrogradely=false` 时按原始信号交易，`retrogradely=true` 时反向交易
6. 反向信号出现时先平仓再反手
7. 下单后附加固定 `SL / TP`

## 主要参数

- `signal_bar`
- `retrogradely`
- `back`
- `jaw_period`
- `jaw_shift`
- `teeth_period`
- `teeth_shift`
- `lips_period`
- `lips_shift`
- `stop_loss_points`
- `take_profit_points`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 迁移说明

- 原始 MT5 指标直接调用 `iAlligator` 与 `iATR`，Backtrader 版本使用等价内建指标组合复刻
- 原始 EA 的核心差异点在于 `retrogradely` 会翻转两个 buffer 的交易方向，该逻辑已保留
- 如果后续需要更严格对齐 MT5 `Alligator` 的位移绘制行为，可以继续细调 shift 对齐边界

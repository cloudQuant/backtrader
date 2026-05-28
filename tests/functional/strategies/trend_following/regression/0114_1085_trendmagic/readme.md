# 1085 Exp_TrendMagic

## 策略概述

该示例是 MT5 EA `1085_Exp_TrendMagic` 的 Backtrader 迁移版本。
EA 在 `H4` 周期上读取 `TrendMagic` 指标，并在颜色缓冲区翻转时执行开平仓。

## 原始信号逻辑

EA 只读取指标的颜色缓冲区 `buffer1`：

- 若上一根颜色为 `0`，且当前颜色变为 `1`，则开多并平空
- 若上一根颜色为 `1`，且当前颜色变为 `0`，则开空并平多

## 指标迁移说明

`TrendMagic` 的核心逻辑是：

- 先计算 `CCI(CCI_Period)` 与 `ATR(ATR_Period)`
- 当 `CCI >= 0` 时，指标线取 `low - ATR`
- 当 `CCI < 0` 时，指标线取 `high + ATR`
- 指标会沿着前一根数值做单向延展，避免方向未变时线条反向跳动
- 颜色缓冲区 `0/1` 对应两种方向状态

## 主要参数

- `cci_period`
- `atr_period`
- `signal_bar`
- `stop_loss`
- `take_profit`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 回测结果

- 样本区间：`2025-12-03 01:15:00` - `2026-03-10 09:00:00`
- 成交笔数：`14`
- 净收益：`-151.50`
- 胜率：`64.29%`
- 最大回撤：`1.35%`

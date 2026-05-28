# 1097 Exp_FisherCGOscillator

## 策略概述

该示例是对 MT5 EA `1097_Exp_FisherCGOscillator` 的 Backtrader 迁移版本。
EA 在 `H8` 周期上读取 `FisherCGOscillator` 主线与其触发线，并依据交叉开平仓。

## 原始信号逻辑

1. 指标主线为 `FCGBuffer`
2. 信号线为 `TriggerBuffer = FCGBuffer[bar-1]`
3. 主线向上穿越信号线时产生做多信号，并允许空头平仓
4. 主线向下穿越信号线时产生做空信号，并允许多头平仓
5. 默认使用固定止损与止盈

## 指标迁移说明

`FisherCGOscillator` 可直接按源码重建：

- 先以 `HL2` 计算重心 `CG`
- 再对最近 `Length` 个 `CG` 做归一化
- 对最近 4 个归一化值做加权平均
- 最后进行 Fisher 变换得到主线
- 信号线为主线滞后 1 根

## 主要参数

- `length`
- `signal_bar`
- `stop_loss`
- `take_profit`
- `size`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H8`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

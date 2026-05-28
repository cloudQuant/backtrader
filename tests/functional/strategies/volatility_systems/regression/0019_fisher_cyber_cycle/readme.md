# 1055 Exp_FisherCyberCycle

## 策略概述

该示例是对 MT5 EA `1055_Exp_FisherCyberCycle` 的 Backtrader 迁移版本。
EA 在 `H8` 周期上读取 `FisherCyberCycle` 主线与触发线，并依据交叉进行开平仓。

## 原始信号逻辑

1. 指标主线为 `FishCCBuffer`
2. 信号线为 `TriggerBuffer = FishCCBuffer[bar-1]`
3. 主线向上穿越信号线时产生做多信号，并允许空头平仓
4. 主线向下穿越信号线时产生做空信号，并允许多头平仓
5. 默认使用固定止损与止盈

## 指标迁移说明

`FisherCyberCycle` 已按源码重建：

- 先以 `HL2` 构造平滑价格
- 再按 `alpha` 与递推系数计算 `Cyber Cycle`
- 对最近 `Length` 个周期值做区间归一化
- 对最近 4 个归一化值做加权平均后执行 Fisher 变换
- 触发线取主线滞后 1 根

## 主要参数

- `alpha`
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

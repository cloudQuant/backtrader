# 1047 Exp_Simple_Trading_System

## 策略概述

该示例是对 MT5 EA `1047_Exp_Simple_Trading_System` 的 Backtrader 迁移版本。
EA 在 `H6` 周期上读取 `simple_trading_system` 指标的买卖箭头，并在柱线收盘时按箭头信号执行开平仓。

## 原始信号逻辑

1. 指标输出 `BuyBuffer` 与 `SellBuffer` 箭头
2. 当前 `SignalBar` 上出现买入箭头时，允许做多并关闭空头
3. 当前 `SignalBar` 上出现卖出箭头时，允许做空并关闭多头
4. 当开仓和平仓同时启用但当前柱没有直接平仓信号时，EA 会向更早的柱回溯寻找最近一次反向箭头，作为辅助平仓条件
5. 默认使用固定止损与止盈

## 指标迁移说明

- 按原指标重建 `EMA(MAPeriod)` 与 `MAShift` 位移比较条件
- 结合 `close` 相对 `close[shift]` 与 `close[MAPeriod + MAShift]` 的位置关系形成箭头
- 箭头绘制位置按源码使用 `ATR(15) * 3 / 8` 偏移

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H6`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

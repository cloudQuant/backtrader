# 1049 Exp_HLRSign

## 策略概述

该示例是对 MT5 EA `1049_Exp_HLRSign` 的 Backtrader 迁移版本。
EA 在 `H1` 周期上读取 `HLRSign` 的买卖箭头，并按 `MODE_IN/MODE_OUT` 的区间进出语义开平仓。

## 原始信号逻辑

1. 指标输出 `BuyBuffer` 与 `SellBuffer` 箭头信号
2. 当前 `SignalBar` 上出现买入箭头时，允许做多并关闭空头
3. 当前 `SignalBar` 上出现卖出箭头时，允许做空并关闭多头
4. 当开仓/平仓同时启用但当前柱没有直接平仓信号时，EA 会向更早的柱回溯寻找最近一次反向箭头，作为辅助平仓条件
5. 默认使用固定止损与止盈

## 指标迁移说明

- 以最近 `HLR_Range` 根柱的最高/最低区间位置计算 `HLR`
- `MODE_IN` 表示进入超买/超卖区域时发信号
- `MODE_OUT` 表示离开超买/超卖区域时发信号
- 箭头绘制位置按源码使用 `ATR(100) * 3 / 8` 偏移

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H1`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

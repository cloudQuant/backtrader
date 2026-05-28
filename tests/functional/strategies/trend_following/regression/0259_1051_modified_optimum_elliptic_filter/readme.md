# 1051 Exp_Modified_Optimum_Elliptic_Filter

## 策略概述

该示例是对 MT5 EA `1051_Exp_Modified_Optimum_Elliptic_Filter` 的 Backtrader 迁移版本。
EA 在 `H4` 周期上读取 `Modified_Optimum_Elliptic_Filter` 单线，并在拐点方向反转时进行开平仓。

## 原始信号逻辑

1. 指标主线为 `Modified_Optimum_Elliptic_Filter`
2. 若上一段方向向下，且最新已完成柱重新向上，则产生做多信号
3. 若上一段方向向上，且最新已完成柱重新向下，则产生做空信号
4. 出现反向信号时允许平掉已有反向仓位
5. 默认使用固定止损与止盈

## 指标迁移说明

已按源码重建原指标递推滤波器：

- 输入价格使用 `HL2`
- 前几根柱直接回填价格本身
- 稳定后按原始系数递推 `0.13785 / 0.0007 / 1.2103 / -0.4867`
- EA 根据最近三根已完成柱的方向拐点识别反转信号

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

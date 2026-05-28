# 1068 Exp_TSI_WPR

## 策略概述

该示例是 MT5 EA `1068_Exp_TSI_WPR` 的 Backtrader 迁移版本。
EA 的入场信号来自 `TSI_WPR` 振荡器，交易在主线与信号线于已完成信号柱发生交叉时触发。

## 原始信号逻辑

EA 读取 `TSI_WPR` 指标的两条线：

- `Ind`：基于 `WPR` 动量构建的 `TSI`
- `Sign`：`TSI` 的平滑信号线

交易条件：

- 若上一根 `Ind > Sign`，且当前 `Ind <= Sign`，则开多并平空
- 若上一根 `Ind < Sign`，且当前 `Ind >= Sign`，则开空并平多

默认参数：

- `InpInd_Timeframe = H4`
- `XMA_Method = MODE_EMA`
- `WPRPeriod = 25`
- `MomPeriod = 1`
- `XLength1 = 5`
- `XLength2 = 8`
- `XLength3 = 20`
- `XPhase = 15`
- `SignalBar = 1`

## 指标迁移说明

`TSI_WPR` 的计算步骤为：

- 先计算 `WPR(25)`
- 再对 `WPR` 计算 `Momentum(1)` 与其绝对值
- 分别对动量与绝对动量做两层平滑
- 用二者比值形成 `TSI`
- 最后对 `TSI` 再做一层平滑形成信号线

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 回测结果

- 样本区间：`2025-12-03 01:15:00` - `2026-03-10 09:00:00`
- 成交笔数：`44`
- 净收益：`720.20`
- 胜率：`56.82%`
- 最大回撤：`1.68%`

# 1070 Exp_BlauHLM

## 策略概述

该示例是 MT5 EA `1070_Exp_BlauHLM` 的 Backtrader 迁移版本。
EA 的入场信号来自 `BlauHLM` 振荡器，支持三种原始模式：直方图零轴突破、直方图方向反转、以及信号云颜色变化。

## 原始信号逻辑

原始 EA 提供三种 `Mode`：

- `breakdown`：当直方图穿越零轴时开仓/反向平仓
- `twist`：当直方图方向由降转升或由升转降时开仓/反向平仓
- `cloudtwist`：当主线与信号线的相对位置翻转时开仓/反向平仓

默认参数：

- `Mode = twist`
- `InpInd_Timeframe = H4`
- `XMA_Method = MODE_EMA`
- `XLength = 2`
- `XLength1 = 20`
- `XLength2 = 5`
- `XLength3 = 3`
- `XLength4 = 3`
- `SignalBar = 1`

## 指标迁移说明

`BlauHLM` 的计算步骤为：

- 计算 `HMU = max(high_t - high_(t-XLength+1), 0)`
- 计算 `LMD = max(-(low_t - low_(t-XLength+1)), 0)`
- 得到 `HLM = (HMU - LMD) / _Point`
- 依次对 `HLM` 做四层平滑，生成主线与信号线
- 同时根据主线所处正负区间及与前值的方向关系生成直方图颜色状态

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 回测结果

- 样本区间：`2025-12-03 01:15:00` - `2026-03-10 09:00:00`
- 成交笔数：`53`
- 净收益：`1924.70`
- 胜率：`47.17%`
- 最大回撤：`1.71%`

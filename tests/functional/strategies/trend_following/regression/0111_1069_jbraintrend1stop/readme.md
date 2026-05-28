# 1069 Exp_JBrainTrend1Stop

## 策略概述

该示例是 MT5 EA `1069_Exp_JBrainTrend1Stop` 的 Backtrader 迁移版本。
EA 基于 `JBrainTrend1Stop` 的颜色变化信号，在趋势止损带由空头切换到多头或由多头切换到空头时触发交易。

## 原始信号逻辑

EA 在新信号柱确认后读取指标的两条趋势缓冲区：

- `UpTrend`：多头止损带
- `DnTrend`：空头止损带

交易条件如下：

- 若当前 `UpTrend` 有值且前一根 `DnTrend` 有值，则开多并平空
- 若当前 `DnTrend` 有值且前一根 `UpTrend` 有值，则开空并平多

这等价于使用指标颜色/方向切换作为开平仓依据。

## 指标迁移说明

`JBrainTrend1Stop` 的计算步骤为：

- 用 `ATR(7)` 与 `ATR(10)` 计算两组波动率范围
- 用 `Stochastic(9, 9, 1)` 与阈值 `53 / 47` 决定趋势方向切换
- 对 `high/low/close` 分别做 `JMA` 平滑，生成趋势参考价格
- 在满足波动阈值后生成 `BuyStop/SellStop`，并在趋势延续时继续抬高或压低止损带

默认参数：

- `InpInd_Timeframe = H4`
- `ATR_Period = 7`
- `STO_Period = 9`
- `MA_Method = MODE_SMA`
- `STO_Price = STO_LOWHIGH`
- `Stop_dPeriod = 3`
- `Length_ = 7`
- `Phase_ = 100`
- `SignalBar = 1`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 回测结果

- 样本区间：`2025-12-03 01:15:00` - `2026-03-10 09:00:00`
- 成交笔数：`10`
- 净收益：`-3944.20`
- 胜率：`30.00%`
- 最大回撤：`6.65%`

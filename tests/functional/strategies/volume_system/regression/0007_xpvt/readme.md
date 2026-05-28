# 1071 Exp_XPVT

## 策略概述

该示例是 MT5 EA `1071_Exp_XPVT` 的 Backtrader 迁移版本。
EA 的入场信号来自 `XPVT` 振荡器，核心是 `PVT` 主线与其平滑信号线的交叉。

## 原始信号逻辑

EA 在新信号柱确认后读取两条缓冲区：

- `Ind`：XPVT 主线（Price and Volume Trend）
- `Sign`：对 `Ind` 进行平滑后的信号线

交易条件如下：

- 若 `Ind[1] > Sign[1]` 且 `Ind[0] <= Sign[0]`，则开多并平空
- 若 `Ind[1] < Sign[1]` 且 `Ind[0] >= Sign[0]`，则开空并平多

对应到 Backtrader 中，即使用上一根已完成 `H4` 信号柱发生的主线/信号线交叉作为入场依据。

## 指标迁移说明

`XPVT` 的计算步骤为：

- 根据所选价格源计算当前价格与上一根价格差
- 以 `Vol * (Price_t - Price_t-1) / Price_t-1` 累加形成 `PVT`
- 对 `PVT` 做一次 `XMA` 平滑，得到 `Sign`
- 默认参数为 `VolumeType = VOLUME_TICK`、`XMA_Method = MODE_EMA`、`XLength = 5`、`IPC = PRICE_CLOSE`

默认参数：

- `InpInd_Timeframe = H4`
- `VolumeType = VOLUME_TICK`
- `XMA_Method = MODE_EMA`
- `XLength = 5`
- `XPhase = 15`
- `IPC = PRICE_CLOSE`
- `SignalBar = 1`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 回测结果

- 样本区间：`2025-12-03 01:15:00` - `2026-03-10 09:00:00`
- 成交笔数：`49`
- 净收益：`15722.30`
- 胜率：`48.98%`
- 最大回撤：`1.82%`

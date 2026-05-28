# 1073 Exp_CronexMFI

## 策略概述

该示例是 MT5 EA `1073_Exp_CronexMFI` 的 Backtrader 迁移版本。
EA 的入场信号来自 `CronexMFI` 振荡器云层颜色变化，本质上是快速平滑线与慢速平滑线的交叉信号。

## 原始信号逻辑

EA 在新信号柱确认后读取两条缓冲区：

- `Ind`：CronexMFI 快线
- `Sign`：CronexMFI 慢线

交易条件如下：

- 若 `Ind[1] > Sign[1]` 且 `Ind[0] <= Sign[0]`，则开多并平空
- 若 `Ind[1] < Sign[1]` 且 `Ind[0] >= Sign[0]`，则开空并平多

对应到 Backtrader 中，即使用上一根已完成 `H4` 信号柱发生的快慢线交叉作为入场依据。

## 指标迁移说明

`CronexMFI` 的计算步骤为：

- 先计算 `MFI(MFIPeriod=25)`
- 对 `MFI` 做一次 `FastPeriod=14` 平滑，得到 `Ind`
- 再对 `Ind` 做一次 `SlowPeriod=25` 平滑，得到 `Sign`
- 默认平滑方法为 `MODE_SMA`

默认参数：

- `InpInd_Timeframe = H4`
- `MFIPeriod = 25`
- `XMA_Method = MODE_SMA`
- `FastPeriod = 14`
- `SlowPeriod = 25`
- `VolumeType = VOLUME_TICK`
- `SignalBar = 1`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 回测结果

- 样本区间：`2025-12-03 01:15:00` - `2026-03-10 09:00:00`
- 成交笔数：`8`
- 净收益：`5090.90`
- 胜率：`75.00%`
- 最大回撤：`2.19%`

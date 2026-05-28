# 1072 Exp_CronexRSI

## 策略概述

该示例是 MT5 EA `1072_Exp_CronexRSI` 的 Backtrader 迁移版本。
EA 的入场信号来自 `CronexRSI` 振荡器云层颜色变化，本质上是快速平滑线与慢速平滑线的交叉信号。

## 原始信号逻辑

EA 在新信号柱确认后读取两条缓冲区：

- `Ind`：CronexRSI 快线
- `Sign`：CronexRSI 慢线

交易条件如下：

- 若 `Ind[1] > Sign[1]` 且 `Ind[0] <= Sign[0]`，则开多并平空
- 若 `Ind[1] < Sign[1]` 且 `Ind[0] >= Sign[0]`，则开空并平多

对应到 Backtrader 中，即使用上一根已完成 `H4` 信号柱发生的快慢线交叉作为入场依据。

## 指标迁移说明

`CronexRSI` 的计算步骤为：

- 先计算 `RSI(RSIPeriod=25, RSIPrice=PRICE_CLOSE)`
- 对 `RSI` 做一次 `FastPeriod=14` 平滑，得到 `Ind`
- 再对 `Ind` 做一次 `SlowPeriod=25` 平滑，得到 `Sign`
- 默认平滑方法为 `MODE_SMA`

默认参数：

- `InpInd_Timeframe = H4`
- `RSIPeriod = 25`
- `RSIPrice = PRICE_CLOSE`
- `XMA_Method = MODE_SMA`
- `FastPeriod = 14`
- `SlowPeriod = 25`
- `SignalBar = 1`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 回测结果

- 样本区间：`2025-12-03 01:15:00` - `2026-03-10 09:00:00`
- 成交笔数：`9`
- 净收益：`3719.60`
- 胜率：`55.56%`
- 最大回撤：`3.98%`

# 1087 Exp_CronexDeMarker

## 策略概述

该示例是 MT5 EA `1087_Exp_CronexDeMarker` 的 Backtrader 迁移版本。
EA 在 `H4` 周期上读取 `CronexDeMarker` 的两条平滑 DeMarker 线，并在云图颜色切换对应的双线交叉处执行开平仓。

## 原始信号逻辑

EA 从指标读取两个缓冲区：

- `buffer0`: 快线 `Ind`
- `buffer1`: 慢线 `Sign`

交易判断直接按源码执行：

- 若上一根 `Ind > Sign`，且当前 `Ind <= Sign`，则开多并平空
- 若上一根 `Ind < Sign`，且当前 `Ind >= Sign`，则开空并平多

## 指标迁移说明

`CronexDeMarker` 的核心逻辑是：

- 先计算标准 `DeMarker` 指标
- 再对 `DeMarker` 做一层 `FastPeriod` 平滑，得到 `Ind`
- 再对 `Ind` 做一层 `SlowPeriod` 平滑，得到 `Sign`
- 图表中的云图颜色由 `Ind` 与 `Sign` 的相对位置决定

## 主要参数

- `demarker_period`
- `xma_method`
- `fast_period`
- `slow_period`
- `signal_bar`
- `stop_loss`
- `take_profit`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 回测结果

- 样本区间：`2025-12-03 01:15:00` - `2026-03-10 09:00:00`
- 成交笔数：`10`
- 净收益：`-382.00`
- 胜率：`60.00%`
- 最大回撤：`1.95%`

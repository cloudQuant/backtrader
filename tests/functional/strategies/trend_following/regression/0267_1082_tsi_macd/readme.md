# 1082 Exp_TSI_MACD

## 策略概述

该示例是 MT5 EA `1082_Exp_TSI_MACD` 的 Backtrader 迁移版本。
EA 在 `H4` 周期上读取 `TSI_MACD` 指标，并在主线与信号线交叉时执行开平仓。

## 原始信号逻辑

EA 从指标读取两个缓冲区：

- `buffer0`: `Ind`
- `buffer1`: `Sign`

交易判断与源码一致：

- 若上一根 `Ind > Sign`，且当前 `Ind <= Sign`，则开多并平空
- 若上一根 `Ind < Sign`，且当前 `Ind >= Sign`，则开空并平多

## 指标迁移说明

`TSI_MACD` 的核心逻辑是：

- 先对指定价格做快慢均线，得到 `MACD = fast - slow`
- 对 `MACD` 做 `momentum` 与 `abs(momentum)` 计算
- 分别对二者进行两层平滑，形成双重平滑动量与绝对动量
- 计算 `TSI = 100 * smoothed_momentum / smoothed_abs_momentum`
- 再对 `TSI` 做一次平滑，得到信号线
- 默认参数使用 `EMA` 平滑，和原 EA 缺省设置保持一致

## 主要参数

- `xfast`
- `xslow`
- `mom_period`
- `xlength1`
- `xlength2`
- `xlength3`
- `xma_method`
- `signal_bar`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 回测结果

- 样本区间：`2025-12-03 01:15:00` - `2026-03-10 09:00:00`
- 成交笔数：`27`
- 净收益：`-3652.00`
- 胜率：`40.74%`
- 最大回撤：`4.61%`

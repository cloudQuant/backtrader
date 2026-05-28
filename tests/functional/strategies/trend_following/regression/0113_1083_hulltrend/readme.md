# 1083 Exp_HullTrend

## 策略概述

该示例是 MT5 EA `1083_Exp_HullTrend` 的 Backtrader 迁移版本。
EA 在 `H4` 周期上读取 `HullTrend` 指标，并在云图颜色切换对应的双线交叉时执行开平仓。

## 原始信号逻辑

EA 从指标读取两个缓冲区：

- `buffer0`: `Ind`
- `buffer1`: `Sign`

交易判断与源码一致：

- 若上一根 `Ind > Sign`，且当前 `Ind <= Sign`，则开多并平空
- 若上一根 `Ind < Sign`，且当前 `Ind >= Sign`，则开空并平多

## 指标迁移说明

`HullTrend` 的核心逻辑是：

- 先对指定价格序列分别计算 `MA(XLength/2)` 与 `MA(XLength)`
- 计算 `hma = 2 * MA(XLength/2) - MA(XLength)`
- 再对 `hma` 以 `sqrt(XLength)` 做一次平滑，得到 `xhma`
- 指标输出 `ExtABuffer=hma` 与 `ExtBBuffer=xhma`，云图颜色随两线相对位置变化
- 默认参数使用 `MODE_LWMA`，与原 EA 缺省设置保持一致

## 主要参数

- `xlength`
- `ipc`
- `xma_method`
- `xphase`
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
- 成交笔数：`45`
- 净收益：`-145.70`
- 胜率：`55.56%`
- 最大回撤：`2.97%`

# 1079 Exp_BvsB

## 策略概述

该示例是 MT5 EA `1079_Exp_BvsB` 的 Backtrader 迁移版本。
EA 在 `H4` 周期上读取 `BvsB` 指标，并在两条距离缓冲区交叉时执行开平仓。

## 原始信号逻辑

EA 从指标读取两个缓冲区：

- `buffer0`: `Ind`
- `buffer1`: `Sign`

交易判断与源码一致：

- 若上一根 `Ind > Sign`，且当前 `Ind <= Sign`，则开多并平空
- 若上一根 `Ind < Sign`，且当前 `Ind >= Sign`，则开空并平多

## 指标迁移说明

`BvsB` 的核心逻辑是：

- 先选取价格序列 `IPC`
- 对该价格做一条平滑中轴 `x1xma`
- 计算 `ExtABuffer = (high - x1xma) / _Point`
- 计算 `ExtBBuffer = (x1xma - low) / _Point`
- EA 根据两条距离缓冲区的交叉来判断云图颜色变化
- 默认参数使用 `SMA(12)`，和原 EA 缺省设置保持一致

## 主要参数

- `bvsb_method`
- `xlength`
- `xphase`
- `ipc`
- `signal_bar`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 回测结果

- 样本区间：`2025-12-03 01:15:00` - `2026-03-10 09:00:00`
- 成交笔数：`43`
- 净收益：`-3896.20`
- 胜率：`53.49%`
- 最大回撤：`5.36%`

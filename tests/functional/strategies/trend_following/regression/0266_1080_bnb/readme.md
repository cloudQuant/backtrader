# 1080 Exp_BnB

## 策略概述

该示例是 MT5 EA `1080_Exp_BnB` 的 Backtrader 迁移版本。
EA 在 `H4` 周期上读取 `BnB` 指标，并在两条平滑多空强度线交叉时执行开平仓。

## 原始信号逻辑

EA 从指标读取两个缓冲区：

- `buffer1`: `Ind`
- `buffer0`: `Sign`

交易判断与源码一致：

- 若上一根 `Ind > Sign`，且当前 `Ind <= Sign`，则开多并平空
- 若上一根 `Ind < Sign`，且当前 `Ind >= Sign`，则开空并平多

## 指标迁移说明

`BnB` 的核心逻辑是：

- 按单根 K 线的高低点范围与成交量，估算单位价格跳动 `tic`
- 基于实体方向和上下影线，分别构造 `bulls` 与 `bears`
- 对 `bulls` 与 `bears` 各自做平滑，得到两条趋势强度线
- EA 通过两条缓冲区的交叉来判定云图颜色切换
- 默认参数使用 `MODE_T3` 平滑，和原 EA 缺省设置保持一致

## 主要参数

- `xma_method`
- `xlength`
- `xphase`
- `volume_type`
- `signal_bar`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 回测结果

- 样本区间：`2025-12-03 01:15:00` - `2026-03-10 09:00:00`
- 成交笔数：`0`
- 净收益：`0.00`
- 胜率：`0.00%`
- 最大回撤：`0.00%`

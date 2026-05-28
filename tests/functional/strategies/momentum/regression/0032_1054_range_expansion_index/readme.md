# 1054 Exp_RangeExpansionIndex

## 策略概述

该示例是对 MT5 EA `1054_Exp_RangeExpansionIndex` 的 Backtrader 迁移版本。
EA 在 `H8` 周期上读取 `RangeExpansionIndex` 指标，并按阈值穿越与离开超买/超卖区间执行开平仓。

## 原始信号逻辑

1. 指标主线为 `REI`
2. 当上一根仍位于阈值内侧、当前柱穿越 `dn_indicator_level` 时允许做多
3. 当上一根仍位于阈值内侧、当前柱穿越 `up_indicator_level` 时允许做空
4. 若指标离开对应条件区间，则关闭已有同向仓位
5. 默认使用固定止损与止盈

## 指标迁移说明

`RangeExpansionIndex` 已按源码重建：

- 使用原始 `SubValue` / `AbsValue` 条件组合
- 对最近 `REI_Period` 根柱线累加后归一化为百分比
- 保留原始颜色缓冲的上升/下降分类，便于后续对照

## 主要参数

- `rei_period`
- `up_indicator_level`
- `dn_indicator_level`
- `signal_bar`
- `stop_loss`
- `take_profit`
- `size`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H8`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

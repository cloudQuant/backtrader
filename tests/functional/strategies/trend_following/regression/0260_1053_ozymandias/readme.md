# 1053 Exp_Ozymandias

## 策略概述

该示例是对 MT5 EA `1053_Exp_Ozymandias` 的 Backtrader 迁移版本。
EA 在 `H4` 周期上读取 `Ozymandias` 指标的中线颜色变化，并在颜色翻转时执行开平仓。

## 原始信号逻辑

1. EA 读取 `Ozymandias` 指标的颜色缓冲
2. 当颜色由 `1 -> 0` 时产生做多信号，并允许空头平仓
3. 当颜色由 `0 -> 1` 时产生做空信号，并允许多头平仓
4. 默认使用固定止损与止盈

## 指标迁移说明

`Ozymandias` 已按源码核心结构重建：

- 使用 `ATR(100) / 2` 形成上下带
- 分别对 `High` / `Low` 做指定类型移动平均
- 结合最近 `Length` 根柱的高低点、`nexttrend/trend` 状态机与突破条件生成中线
- 复现中线颜色翻转，用于 EA 的入场与反向平仓判断

## 主要参数

- `length`
- `ma_type`
- `signal_bar`
- `stop_loss`
- `take_profit`
- `size`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

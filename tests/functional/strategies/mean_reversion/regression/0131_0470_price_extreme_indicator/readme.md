# 0470 基于 Price_Extreme_Indicator 的 EA 交易

## 策略概述

该策略是对 MT5 EA `0470_基于_Price_Extreme_Indicator_的_EA_交易` 的 backtrader 迁移版本。
原 EA 使用 `Price_Extreme_Indicator` 通道边界：若 `signal_bar` 的收盘价高于上边界则做多，低于下边界则做空。若出现反向信号，则先关闭反向仓位，再开新仓。可通过参数关闭多头/空头，或反转信号方向。

## 核心逻辑

1. 使用 `multiplier` 长度的价格极值通道作为上下边界
2. 在每根新 K 线上读取 `signal_bar` 对应的收盘价与通道边界
3. 收盘价突破上边界则做多，跌破下边界则做空
4. 若已有反向仓位则先平仓，再在后续可执行点位反手
5. 支持固定手数和可选固定止损/止盈

## 主要参数

- `multiplier`
- `signal_bar`
- `enable_buy`
- `enable_sell`
- `reverse_trade`
- `volume`
- `stop_loss_points`
- `take_profit_points`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- 数据区间：`2025-12-03 01:15:00` → `2026-03-10 09:00:00`
- K线数量：`6129`
- 买入次数：`963`
- 卖出次数：`674`
- 平仓交易数：`416`
- 期末权益：`131088.00`
- 净收益：`31088.00`
- 总收益率：`31.09%`
- 胜率：`25.42%`
- Profit Factor：`1.32`
- 最大回撤：`14.26%`

## 对齐说明

- 原 EA 依赖仓库内自带的 `price_extreme_indicator.mq5`，当前版本用 backtrader 内部的价格极值通道近似复现
- 原 EA 在新 bar 上按通道突破做反手；当前版本保留该单品种、反向平仓再入场的核心结构
- 原 EA 若信号持续可重复同向开仓；当前版本保留该行为，并在 Backtrader 净头寸模型下体现为同向加仓

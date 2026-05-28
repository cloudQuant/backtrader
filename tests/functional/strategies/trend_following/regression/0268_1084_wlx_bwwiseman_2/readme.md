# 1084 Exp_wlxBWWiseMan-2

## 策略概述

该示例是 MT5 EA `1084_Exp_wlxBWWiseMan-2` 的 Backtrader 迁移版本。
EA 在 `H4` 周期上读取 `wlxBWWiseMan-2` 指标的买卖箭头缓冲区，并在箭头出现时执行开平仓。

## 原始信号逻辑

EA 从指标读取两个缓冲区：

- `buffer0`: `DnValue`，卖出箭头
- `buffer1`: `UpValue`，买入箭头

交易判断直接按源码执行：

- 若当前 `UpValue` 非空，则开多并平空
- 若当前 `DnValue` 非空，则开空并平多
- 若当前柱没有直接平仓信号，则向更早历史回溯最近的反向箭头，用于触发对应平仓

## 指标迁移说明

`wlxBWWiseMan-2` 的核心逻辑是：

- 先计算 `ATR(15)` 与 `Awesome Oscillator`
- 当 `AO` 连续 5 根递增且整体位于零轴上方时，在 `low - ATR * 3/8` 位置绘制买入箭头
- 当 `AO` 连续 5 根递减且整体位于零轴下方时，在 `high + ATR * 3/8` 位置绘制卖出箭头
- 源码中 `updown` 输入参数被传入 EA/指标，但在当前指标计算中未实际参与公式

## 主要参数

- `updown`
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
- 成交笔数：`0`
- 净收益：`0.00`
- 胜率：`0.00%`
- 最大回撤：`0.00%`

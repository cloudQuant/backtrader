# 1091 Exp_HighsLowsSignal

## 策略概述

该示例是 MT5 EA `1091_Exp_HighsLowsSignal` 的 Backtrader 迁移版本。
EA 在 `H4` 周期上读取 `HighsLowsSignal` 箭头缓冲区，并在出现多头或空头星形信号时执行开平仓。

## 原始信号逻辑

EA 从指标读取两个缓冲区：

- `buffer1`: 买入箭头
- `buffer0`: 卖出箭头

交易规则：

- 若当前 `SignalBar` 上出现买入箭头，则允许开多并平空
- 若当前 `SignalBar` 上出现卖出箭头，则允许开空并平多
- 若当前 bar 无直接平仓信号，EA 还会向更早的历史回溯最近一次反向箭头，用于生成平仓信号

## 指标迁移说明

`HighsLowsSignal` 的核心逻辑是：

- 连续 `HowManyCandles` 根 bar 形成更高高点且更高低点，则画出买入箭头
- 连续 `HowManyCandles` 根 bar 形成更低高点且更低低点，则画出卖出箭头
- 箭头位置使用 `ATR(15)` 做上下偏移，仅用于显示

## 主要参数

- `how_many_candles`
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
- 成交笔数：`18`
- 净收益：`502.10`
- 胜率：`27.78%`
- 最大回撤：`7.33%`

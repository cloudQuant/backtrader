# 0495 DojiTrader

## 策略概述

该策略是对 MT5 EA `0495_DojiTrader` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为在限定交易时段内识别最近三根已完成 K 线中的 `Doji`，并在随后的突破方向上建立单仓头寸。

## 核心逻辑

1. 仅在设定交易时段内执行
2. 在最近三根已完成 K 线中寻找实体高度不超过阈值的 `Doji`
3. 只接受出现在 `bar[2]` 或 `bar[3]` 的 Doji，并使用 `bar[1]` 收盘价确认突破方向
4. 若 `bar[1].close > doji_high` 则做多；若 `bar[1].close < doji_low` 则做空
5. 仅保留单仓，并使用固定 `SL/TP` 管理

## 主要参数

- `lot`
- `stop_loss_pips`
- `take_profit_pips`
- `start_hour`
- `end_hour`
- `maximum_doji_height`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

 ## 当前回测结果

 - Trades: `3`
 - Net P&L: `+11.70`
 - Win Rate: `33.33%`
 - Profit Factor: `1.10`
 - Max Drawdown: `0.11%`

## 对齐说明

- 原 EA 若异常出现多于一笔仓位会全部平掉；当前 Backtrader 迁移版本天然采用单净头寸模型
- 原源码在反向信号分支里存在一处 `else if(eDirection==1)` 的明显笔误；当前迁移按策略意图解释为 `eDirection==-1` 的反向开空分支
- 原 EA 在新 bar 首个 tick 上执行；当前版本基于 bar 级回放做近似实现

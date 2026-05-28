# 0151 Precipice

## 策略概述

该样例是对 MT5 EA `0151_Precipice` 的 Backtrader 迁移版。
原 EA 没有指标驱动信号，而是在空仓时按随机数结果开多或开空，并使用固定的止损/止盈距离管理单仓位。

## 迁移思路

1. 使用 `random_seed` 固定随机序列，保证回测结果可复现
2. 在每根新 bar 且无持仓时执行一次随机方向决策
3. 保留 `Use Buy / Use Sell` 开关
4. 采用固定 `SL=TP` 距离复刻原 EA 的出场结构

## 主要参数

- `fixed_lot`
- `sltp_pips`
- `use_buy`
- `use_sell`
- `random_seed`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`./run.py`
- 绘图：`./run.py --plot`

## 当前回测结果

- Trades: `1501`
- Net P&L: `-137841.00`
- Win Rate: `32.51%`
- Profit Factor: `0.70`
- Max Drawdown: `178.90%`

## 对齐说明

- 原 EA 在 tick 级别通过 `MathRand()` 随机决定是否买入或卖出；Backtrader 版本改为每根 bar 做一次可复现随机抽样，这是针对离线回测环境的必要近似
- 当前版本保持“同一时间只持有一个仓位、固定 SL/TP”的核心约束
- 该策略本质上是随机基线，不代表可交易优势，仅作为源码迁移样例

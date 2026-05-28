# 1202 RKD EA

## 策略概述

该策略是对 MT5 EA `1202_一款简单_RKD_EA,_基于指定的自定义_RKD_指标` 的 Backtrader 迁移版本。
原 EA 使用仓库内自带的 `RKD.mq5` 指标，核心是 `RSV -> K -> D` 链式平滑，并基于 `K/D` 交叉进行开平仓。

## 核心逻辑

1. 用 `KDPeriod` 计算滚动最高价/最低价并生成 `RSV`
2. 对 `RSV` 做 `M1` 周期简单平滑得到 `K`
3. 对 `K` 做 `M2` 周期简单平滑得到 `D`
4. `K` 上穿 `D` 时：空仓开多，若当前有空单则仅平空
5. `K` 下穿 `D` 时：空仓开空，若当前有多单则仅平多

## 主要参数

- `kd_period`
- `m1`
- `m2`
- `lots`
- `stop_loss_points`
- `take_profit_points`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `1034`
- Net P&L: `-7219.80`
- Win Rate: `42.36%`
- Profit Factor: `0.91`
- Max Drawdown: `13.79%`

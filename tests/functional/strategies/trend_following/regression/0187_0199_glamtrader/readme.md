# 0199 GlamTrader

## 策略概述

该策略是对 MT5 EA `0199_GlamTrader` 的 backtrader 迁移版本。
原 EA 使用 `LWMA + AO + Laguerre` 的三重过滤做入场判断，只允许同一时间存在一笔仓位，并给买卖单分别设置固定止损止盈以及统一 trailing stop。
当前版本使用 `XAUUSD_M15.csv` 回测，并在 Python 中直接重建了 `Laguerre` 指标和 `Awesome Oscillator`。

## 核心逻辑

1. 用 `Weighted Price = (High + Low + 2 * Close) / 4` 计算 `LWMA(14)`
2. 计算 `AO = SMA(median, 5) - SMA(median, 34)`
3. 计算 `Laguerre(gamma=0.7)`
4. 当 `MA > Close`、`Laguerre > 0.15` 且 `AO` 上升时做多
5. 当 `MA < Close`、`Laguerre < 0.75` 且 `AO` 下降时做空
6. 持仓后使用固定 `SL/TP` 和源码等价的 trailing stop 规则管理风险
7. 任一时刻只保留单仓位，不做网格和对冲

## 主要参数

- `lot`
- `stop_loss_buy`
- `take_profit_buy`
- `stop_loss_sell`
- `take_profit_sell`
- `trailing_stop`
- `trailing_step`
- `ma_period`
- `ma_shift`
- `laguerre_gamma`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `345`
- Net P&L: `-8734.00`
- Win Rate: `51.59%`
- Profit Factor: `0.91`
- Max Drawdown: `22.96%`

## 对齐说明

- 原 MT5 EA 注释提到曾尝试跨周期组合，但当前源码实际使用的是 `Period()` 上的 `iMA`、`iAO` 与 `laguerre`
- 当前 backtrader 版本按源码主流程实现了单仓位、固定 `SL/TP` 和 trailing 逻辑
- Backtrader 无法逐 tick 完全模拟 MT5 的实际成交、点差与修改单限制，因此结果应视为可运行的逻辑迁移样例

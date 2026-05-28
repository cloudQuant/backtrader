# 0146 RSI_EA_v2

## 策略概述

该样例是对 MT5 EA `0146_RSI_EA_v2` 的 Backtrader 迁移版。
原 EA 基于 RSI 穿越超卖/超买阈值开仓，支持仅多、仅空或双向交易，并带有时间控制、可选信号平仓以及 trailing stop。

## 迁移思路

1. 在 `M15` 数据上计算 `RSI(period=14)`
2. RSI 自下向上穿越 `RsiBuyLevel` 时做多
3. RSI 自上向下穿越 `RsiSellLevel` 时做空
4. 当 `CloseBySignal=true` 时，反向阈值穿越触发市价平仓
5. 保留固定止损、止盈与 trailing stop 的主流程近似
6. 保留跨日时间窗口控制逻辑

## 主要参数

- `open_buy`
- `open_sell`
- `close_by_signal`
- `stop_loss_pips`
- `take_profit_pips`
- `trailing_stop_pips`
- `trailing_step_pips`
- `rsi_period`
- `rsi_buy_level`
- `rsi_sell_level`
- `time_control_enabled`
- `start_hour`
- `end_hour`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`./run.py`
- 绘图：`./run.py --plot`

## 当前回测结果

- Trades: `128`
- Net P&L: `-17301.00`
- Win Rate: `21.88%`
- Profit Factor: `0.68`
- Max Drawdown: `23.72%`

## 对齐说明

- 原 EA 在逐 tick 上执行，当前版本按 bar close 近似执行 RSI 穿越判断
- 原 EA 的 `Trailing` 基于最新价格与已开仓浮盈更新止损，当前版本保留同方向逻辑并按 bar close 近似
- 原 EA 通过账户与订单接口同时兼容净持与对冲账户；当前版本按单净头寸近似迁移

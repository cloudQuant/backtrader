# 0131 Cidomo

## 策略概述

该样例是对 MT5 EA `0131_Cidomo` 的 Backtrader 迁移版。
原 EA 在工作周期上寻找最近 `N` 根 K 线的最高点和最低点，并分别在其上方/下方布置 `Buy Stop` 与 `Sell Stop` 突破挂单；若任一挂单触发，则删除另一侧未触发挂单，之后仅通过 trailing stop 管理仓位。

## 迁移思路

1. 使用现有 `M15` 数据重采样到默认 `H4` 工作周期
2. 在每根新工作周期 bar 上统计最近 `number_of_bars` 的最高价和最低价
3. 以 `indent_pips` 为偏移同时布置 `buy stop / sell stop`
4. 一侧挂单成交后取消另一侧挂单
5. 持仓阶段保留固定 `SL/TP` 与 trailing stop 主流程

## 主要参数

- `fixed_lot`
- `stop_loss_pips`
- `take_profit_pips`
- `trailing_stop_pips`
- `trailing_step_pips`
- `use_time_control`
- `indent_pips`
- `number_of_bars`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`（内部重采样到 `H4`）
- 运行：`./run.py`
- 绘图：`./run.py --plot`

## 当前回测结果

- Trades: `39`
- Net P&L: `-8715.00`
- Win Rate: `35.90%`
- Profit Factor: `0.85`
- Max Drawdown: `28.77%`

## 对齐说明

- 原 EA 使用突破型 `Buy Stop / Sell Stop` 双向挂单，当前版本保留同样的挂单入场结构
- 原 EA 在有持仓时只执行 trailing，不再重复布置挂单；当前版本保留这一主流程
- 原 EA 支持日内时间窗口控制；当前版本同样提供 `use_time_control / start_hour / start_minute` 参数

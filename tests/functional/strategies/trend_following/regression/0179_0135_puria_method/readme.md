# 0135 Puria Method

## 策略概述

该样例是对 MT5 EA `0135_普里亚（Puria）方法` 的 Backtrader 迁移版。
原 EA 在 `M30` 周期上运行，结合三条不同配置的移动平均线与 `MACD MAIN_LINE` 多 bar 趋势确认决定开仓方向；策略同一时间只保留一笔仓位，并在盈利达到阈值后执行部分平仓，同时继续使用 trailing stop 管理剩余仓位。

## 迁移思路

1. 使用 `M15` 数据重采样到 `M30`
2. 重建三条原始参数下的 MA：`SMMA(69, PRICE_HIGH)`、`SMMA(74, PRICE_HIGH)`、`EMA(19, PRICE_OPEN)`
3. 使用 `MACD(17, 38, 1)` 主线，并保留“最近 N 根 bar 持续同向”趋势确认
4. 仅在无持仓时依据固定信号开仓，保持单净头寸
5. 保留默认参数下的 trailing stop 与达到最小利润后的部分平仓近似

## 主要参数

- `fixed_lot`
- `stop_loss_pips`
- `trailing_stop_pips`
- `trailing_step_pips`
- `min_profit_step_pips`
- `min_profit_percent`
- `macd_number_bars`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`（内部重采样到 `M30`）
- 运行：`./run.py`
- 绘图：`./run.py --plot`

## 当前回测结果

- Trades: `75`
- Net P&L: `3221.81`
- Win Rate: `33.33%`
- Profit Factor: `1.08`
- Max Drawdown: `23.42%`

## 对齐说明

- 原 EA 默认在 `M30` 上测试；当前版本使用现有 `M15` 数据重采样来对齐执行周期
- 原 EA 在已有持仓时不会按反向信号直接平仓，而是继续做 trailing 与达到利润阈值后的部分平仓；当前版本保留这一主流程
- 原 EA 支持风险手数；当前版本先覆盖固定手数下的核心策略逻辑

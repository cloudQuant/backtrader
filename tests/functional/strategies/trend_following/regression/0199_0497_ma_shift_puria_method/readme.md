# 0497 ma-shift_Puria_method

## 策略概述

该策略是对 MT5 EA `0497_ma-shift_Puria_method` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为 `EMA 快慢线同向推进` + `MACD 主线穿越零轴` + `最小位移阈值` 的 Puria 变体，并保留固定止损、止盈及传统/分形尾随控制。

## 核心逻辑

1. 计算快速 `EMA`、慢速 `EMA` 与 `MACD main line`
2. 多头要求：快线在慢线上方、慢线继续上行、快线继续上行，且 `MACD main` 从负值区穿越到正值区
3. 空头要求：快线在慢线下方、慢线继续下行、快线继续下行，且 `MACD main` 从正值区穿越到负值区
4. 额外要求快线最近两段斜率满足最小位移阈值 `shift_min_pips`
5. 持仓使用固定 `SL/TP` 管理，可选传统 trailing 或 fractal trailing

## 主要参数

- `manual_lot`
- `lot`
- `stop_loss_pips`
- `take_profit_pips`
- `trailing_stop_pips`
- `trailing_step_pips`
- `risk_percent`
- `max_positions`
- `fractal_trailing`
- `ma_fast`
- `ma_slow`
- `shift_min_pips`
- `macd_fast`
- `macd_slow`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

 ## 当前回测结果

 - Trades: `63`
 - Net P&L: `-312.50`
 - Win Rate: `42.86%`
 - Profit Factor: `0.87`
 - Max Drawdown: `1.47%`

## 对齐说明

- 原 EA 在 MT5 对冲模式下可按方向分别统计并持有多笔仓位；当前迁移版本在 Backtrader 中按净头寸模型近似
- 原 EA 默认使用基于保证金风险的下单量；当前版本保留近似的风险仓位换算，但示例配置默认改为固定手数，以避免在 `XAUUSD M15` 上产生失真的放大量化结果
- 原 EA 的 trailing 与 fractal trailing 基于逐 tick 更新；当前版本基于 bar 级 `OHLC` 做近似回放

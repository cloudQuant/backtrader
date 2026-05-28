# 1172 EA_MARSI

## 策略概述

该策略是对 MT5 EA `1172_EA_MARSI` 的 Backtrader 迁移版本。
原 EA 使用两个 `EMA_RSI_VA` 指标实例：一组慢线，一组快线；在两条自适应线发生交叉时进行开仓或反手。

## 核心逻辑

1. 在当前交易周期上分别计算慢速与快速 `EMA_RSI_VA`
2. `EMA_RSI_VA` 本质上是以 RSI 偏离 `50` 的幅度动态调整平滑周期的自适应 EMA
3. 若上一根完成 K 线满足 `slow > fast`，而最近完成 K 线变为 `slow <= fast`，则视为多头交叉，开多或空翻多
4. 若上一根完成 K 线满足 `slow < fast`，而最近完成 K 线变为 `slow >= fast`，则视为空头交叉，开空或多翻空
5. 若启用 `use_multpl`，则按 `lots * balance / max_drawdown` 计算新的下单手数
6. 若配置了 `sl_points` 或 `tp_points`，则在持仓期间按固定点数执行离场

## 主要参数

- `lots`
- `tp_points`
- `sl_points`
- `use_multpl`
- `max_drawdown`
- `slow_rsi_period`
- `slow_ema_periods`
- `slow_price`
- `fast_rsi_period`
- `fast_ema_periods`
- `fast_price`
- `signal_bar`
- `point`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 对齐说明

迁移版本按 EA 源码中的真实执行方式实现：
它读取两个 `EMA_RSI_VA` buffer 的最近两根已完成柱值，基于慢线与快线的交叉方向开仓或反手，而不是仅根据文档中的口语化描述直接下结论。

## 回测结果

- 周期：`2025-12-03 01:15:00` 至 `2026-03-10 09:00:00`
- Bars：`6129`
- Signal count：`53`
- Buy entries：`26`
- Sell entries：`27`
- Closed trades：`52`
- Analyzer total trades：`53`
- Wins：`31`
- Losses：`21`
- Win rate：`58.49%`
- Initial cash：`100000.00`
- Final value：`89849.00`
- Net PnL：`-10151.00`
- Total return：`-10.15%`
- Profit factor：`0.55`
- Sharpe ratio：`-8.47`
- Annual return：`-99.82%`
- Max drawdown：`12.49%`
- SQN：`-1.35`

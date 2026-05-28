# 1189 ytg_ADX_V1

## 策略概述

该策略是对 MT5 EA `1189_ytg_ADX_V1` 的 Backtrader 迁移版本。
原 EA 使用 `ADX Wilder` 的 `+DI/-DI` 与固定阈值比较，只在空仓时开仓；持仓期间不响应新信号，出场仅依赖固定止损和止盈。

## 核心逻辑

1. 计算 `ADX Wilder` 的 `+DI` 和 `-DI`
2. 当 `+DI` 自下向上穿越 `level_p` 时开多
3. 当 `-DI` 自下向上穿越 `level_m` 时开空
4. 同一时间仅允许一笔持仓
5. 持仓仅通过固定 `SL/TP` 平仓

## 主要参数

- `adx_period`
- `shift`
- `level_p`
- `level_m`
- `stop_loss_points`
- `take_profit_points`
- `lots`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `0`
- Net P&L: `0.00`
- Win Rate: `0.00%`
- Profit Factor: `N/A`
- Max Drawdown: `0.00%`

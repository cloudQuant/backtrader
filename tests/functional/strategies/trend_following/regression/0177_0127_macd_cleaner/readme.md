# 0127 MACD_清洁工

## 策略概述

该样例是对 MT5 EA `0127_MACD_清洁工` 的 Backtrader 迁移版。
原 EA 使用 `MACD MAIN_LINE` 连续三段单向变化作为入场信号，并采用单净头寸管理：先平反向仓，再开新仓；持仓阶段可附加 trailing stop。

## 迁移思路

1. 使用现有 `M15` 数据重采样到默认 `D1` MACD 周期
2. 重建 `MACD(15, 33, 11)` 主线
3. 当 `macd[3] >= macd[2] >= macd[1]` 时做多
4. 当 `macd[3] <= macd[2] <= macd[1]` 时做空
5. 保留单净头寸、固定 `SL/TP` 与可选 trailing 的主流程

## 主要参数

- `fixed_lot`
- `stop_loss_pips`
- `take_profit_pips`
- `trailing_stop_pips`
- `trailing_step_pips`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`（内部重采样到 `D1`）
- 运行：`./run.py`
- 绘图：`./run.py --plot`

## 当前回测结果

- Trades: `10`
- Net P&L: `12557.00`
- Win Rate: `30.00%`
- Profit Factor: `1.29`
- Max Drawdown: `27.97%`

## 对齐说明

- 原 EA 通过 `iMACD` 的主线连续变化方向生成信号；当前版本保留同样的三段单向判定
- 原 EA 采用反向信号先平仓再开仓的方式管理单仓位；当前版本保持一致
- 原 EA 的 trailing 仅在启用时生效；当前版本也按同样方式处理

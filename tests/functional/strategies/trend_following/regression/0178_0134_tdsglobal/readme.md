# 0134 TDSGlobal

## 策略概述

该样例是对 MT5 EA `0134_TDSGlobal` 的 Backtrader 迁移版。
原 EA 在工作周期上分析上一根 bar 的高低点，并结合 `H4` 上的 `OsMA` 与 `Force Index` 方向来放置 `buy limit / sell limit` 挂单；同一时间只维护单一挂单和单一持仓，并在已有持仓后用 trailing stop 管理。

## 迁移思路

1. 使用 `M15` 作为工作周期，并额外构造 `H4` 指标周期
2. 在 `H4` 上重建 `MACD`、`OsMA` 与 `Force Index EMA`
3. 当 `OsMA` 上行且 `Force` 为负时，按上一根工作 bar 高点附近布置 `sell limit`
4. 当 `OsMA` 下行且 `Force` 为正时，按上一根工作 bar 低点附近布置 `buy limit`
5. 保留单挂单 / 单持仓、挂单失效删除，以及开仓后 `SL/TP/trailing` 的主流程近似

## 主要参数

- `fixed_lot`
- `stop_loss_pips`
- `take_profit_pips`
- `trailing_stop_pips`
- `trailing_step_pips`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`./run.py`
- 绘图：`./run.py --plot`

## 当前回测结果

- Trades: `213`
- Net P&L: `-24541.00`
- Win Rate: `28.17%`
- Profit Factor: `0.62`
- Max Drawdown: `25.46%`

## 对齐说明

- 原 EA 的信号指标固定在 `H4`，当前版本保留该高周期信号过滤
- 原 EA 通过 `buy limit / sell limit` 处理回撤入场，当前版本继续使用 Backtrader 限价单近似
- 源码中存在一条较少触发的买限价 fallback 分支，当前版本保留原始方向，不主动重写其语义

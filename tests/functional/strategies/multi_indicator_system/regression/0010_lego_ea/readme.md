# 0198 Lego EA

## 策略概述

该策略是对 MT5 EA `0198_Lego_EA` 的 backtrader 迁移版本。
原 EA 支持 `CCI`、`MA`、`Stochastic`、`AC`、`DeMarker`、`AO` 的自由组合，并允许用一组指标开仓、另一组指标平仓；同时还带有“上一笔亏损则下一笔放大手数”的 lot 管理。
当前迁移版本优先对齐源码默认参数，也就是只启用 `MA` 作为开仓和平仓信号，并保留固定 `SL/TP` 与亏损后 `lot × 2` 的规则。

## 核心逻辑

1. 计算 `SMA(14)` 与 `SMA(67)`，并按源码参数保留 `ma_shift=1`
2. 当 `MA1 > MA2` 时产生开多信号
3. 当 `MA1 < MA2` 时产生开空信号
4. 持有多单时，若 `MA1 < MA2` 则平多
5. 持有空单时，若 `MA1 > MA2` 则平空
6. 每笔订单带固定 `SL/TP`
7. 若上一笔交易亏损，则下一笔 lot 使用 `上一笔 lot × 2`

## 主要参数

- `lot`
- `stop_loss_points`
- `take_profit_points`
- `lot_multiply`
- `ma_fast_period`
- `ma_slow_period`
- `ma_shift`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `2973`
- Net P&L: `511254.00`
- Win Rate: `51.66%`
- Profit Factor: `1.17`
- Max Drawdown: `83.10%`

## 对齐说明

- 原 MT5 EA 是一个多指标组合框架，但源码默认只启用了 `MA` 开仓与平仓
- 当前 backtrader 版本优先实现默认参数路径，以保证样例可运行并与默认 EA 行为对齐
- 其它可选指标组合（CCI、STO、AC、DeM、AO）尚未在该样例中展开，后续可继续扩展
- Backtrader 无法逐 tick 完全复刻 MT5 的实际成交、点差与交易冻结限制，因此结果应视为逻辑迁移样例

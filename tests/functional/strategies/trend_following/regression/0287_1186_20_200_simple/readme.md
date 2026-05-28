# 1186 20/200 点 - 简单可盈利 EA

## 策略概述

该策略是对 MT5 EA `1186_20_200_点_-_简单可盈利_EA` 的 Backtrader 迁移版本。
原 EA 在指定交易小时检查 `H1` 周期上两根历史开盘价的差值，若差值超过阈值则开仓；每次只持有一笔仓位，出场仅依赖固定止损和止盈。

## 核心逻辑

1. 读取 `H1` 上 `Open[t1]` 与 `Open[t2]`
2. 若 `Open[t1] > Open[t2] + delta * Point`，则做空
3. 若 `Open[t1] + delta * Point < Open[t2]`，则做多
4. 仅在 `trade_hour` 对应小时允许开新仓
5. 每天最多触发一次开仓尝试
6. 持仓仅通过固定 `SL/TP` 平仓

## 主要参数

- `take_profit_points`
- `stop_loss_points`
- `trade_hour`
- `t1`
- `t2`
- `delta`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `64`
- Buy Entries: `31`
- Sell Entries: `33`
- Net P&L: `-506.20`
- Win Rate: `71.88%`
- Profit Factor: `0.89`
- Max Drawdown: `2.56%`
- Sharpe Ratio: `-2.02`

## 对齐说明

- 原 EA 文档明确推荐用于 `EURUSD H1`
- 当前统一验收环境为 `XAUUSD M15`，但策略内部仍按原逻辑取 `H1` 开盘价信号
- 当前迁移重点是保留其固定时刻、固定阈值和固定 `SL/TP` 的原始结构，而不是重新优化参数

# 0786 Exp_TimesDirection

## 策略概述

该策略是对 MT5 EA `0786_Exp_TimesDirection` 的 Backtrader 迁移版本。
当前版本保留了原 EA 的时间驱动核心：在指定时间窗口开仓，在指定时间窗口平仓，并支持只做多或只做空以及固定 `SL/TP`。

## 核心逻辑

1. 在 `open_time ~ open_time + trade_interval` 的时间窗口内寻找开仓机会
2. 在 `close_time ~ close_time + trade_interval` 的时间窗口内执行平仓
3. `trade_direction=buy` 时只做多，`sell` 时只做空
4. 开仓后使用固定 `StopLoss/TakeProfit`
5. 每天只触发一次开仓和一次平仓窗口

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `open_time`
- `close_time`
- `trade_interval_minutes`
- `trade_direction`
- `stop_loss`
- `take_profit`

## 当前数据与运行方式

当前使用数据：

- `../../../datas/XAUUSD_M15.csv`

运行命令：

```bash
python run.py
```

如果需要绘图：

```bash
python run.py --plot
```

## 当前回测结果

当前参数下的回测结果：

- Trades: `67`
- Net P&L: `-1,079.20`
- Win Rate: `31.34%`
- Profit Factor: `0.78`
- Max Drawdown: `2.12%`

## 对齐说明

- 原 EA 的 `OpenTime` / `CloseTime` 为绝对 `datetime`，在统一历史回测框架下这里按“每日固定时刻”解释，以便在整段样本上可重复验证
- 原 EA 使用 `TradeAlgorithms.mqh` 执行固定方向的开平仓；当前版本用 Backtrader 单仓位调度逻辑等价实现
- 原 EA 允许在开仓时直接附带 `SL/TP`；当前版本用策略内价格监控实现相同风控效果

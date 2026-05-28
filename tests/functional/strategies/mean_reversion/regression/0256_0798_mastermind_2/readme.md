# 0798 MasterMind 2

## 策略概述

该策略是对 MT5 EA `0798_MasterMind_2` 的 Backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，保留了原 EA 的核心结构：

- `Stochastic(signal)` 与 `Williams %R` 的极端阈值共振入场
- 反向信号触发平仓
- 固定 `SL/TP`
- `BreakEven` 与 `TrailingStop/TrailingStep` 风控

## 核心逻辑

1. 计算 `Stochastic(100, 3, 3)` 的 signal 线
2. 计算 `Williams %R(100)`
3. 当 `Stochastic signal < 3` 且上一根 `%R < -99.9` 时做多
4. 当 `Stochastic signal > 97` 且上一根 `%R > -0.1` 时做空
5. 持仓后遇到反向信号平仓
6. 同时应用固定止损、止盈、保本与跟踪止损逻辑

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `lots`
- `stop_loss`
- `take_profit`
- `trailing_stop`
- `trailing_step`
- `break_even`
- `stochastic_period`
- `stochastic_period_d`
- `stochastic_period_slow`
- `wpr_period`

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

- Trades: `6`
- Net P&L: `-44.60`
- Win Rate: `33.33%`
- Profit Factor: `0.69`
- Max Drawdown: `0.12%`

## 对齐说明

- 原 EA 默认测试环境为 `EURUSD M5`，当前统一验收环境为 `XAUUSD M15`
- 原 EA 中 `sig_buy/sig_sell` 都读取 `Stochastic signal[0]`，`sig_high/sig_low` 都读取 `WPR[1]`，当前版本保留这一取值方式
- 原 EA 有较多提示音、告警、邮件等终端交互逻辑，当前迁移仅保留交易与风控核心流程

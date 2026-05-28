# 0793 RobotPowerM5 meta4V12

## 策略概述

该策略是对 MT5 EA `0793_RobotPowerM5_meta4V12` 的 Backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，保留了原 EA 的核心结构：

- 使用 `Bulls Power` 与 `Bears Power` 计算方向信号
- 以 `bull + bear` 的正负作为多空开仓依据
- 固定 `SL/TP`
- 盈利后按固定步长推进 trailing stop
- 单仓位运行

## 核心逻辑

1. 计算 `EMA(period=5)`
2. `bull = high - ema`，`bear = low - ema`
3. `bull + bear > 0` 时做多，`bull + bear < 0` 时做空
4. 入场后使用固定止损、止盈
5. 当价格与当前止损的距离超过 `2 * trailing_step` 后，按 `trailing_step` 推进止损

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `bull_bear_period`
- `lot`
- `trailing_step`
- `take_profit`
- `stop_loss`

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

- Trades: `2963`
- Net P&L: `156.13`
- Win Rate: `50.25%`
- Profit Factor: `1.02`
- Max Drawdown: `0.67%`

## 对齐说明

- 原 EA 说明建议运行在 `M5`；当前统一验证环境为 `XAUUSD M15`
- 原 EA 中 `iATR` 句柄创建后并未真正参与有效交易决策；当前迁移只保留实际使用的 `Bulls/Bears Power + trailing` 核心逻辑
- 原 EA 会在信号持续为正/负时尝试开仓；当前版本同样在空仓时依据最新完成 bar 的 `bull + bear` 符号开仓

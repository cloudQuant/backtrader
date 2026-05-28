# 1323 Hammer / Hanging Man + RSI

## 策略概述

该策略是对 MT5 EA `1323_MQL5_向导_-_基于_锤头_上吊线形态的交易信号_+_RSI` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为锤头 / 上吊线形态配合 RSI 确认。

## 核心逻辑

1. 识别 `Hammer` 与 `Hanging Man`
2. 当出现锤头且 `RSI < 40` 时做多
3. 当出现上吊线且 `RSI > 60` 时做空
4. 持仓后根据 RSI 在 `30 / 70` 区域的变化离场

## 主要参数

- `rsi_period`
- `rsi_entry_long`
- `rsi_entry_short`
- `rsi_exit_upper`
- `rsi_exit_lower`
- `ma_period`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

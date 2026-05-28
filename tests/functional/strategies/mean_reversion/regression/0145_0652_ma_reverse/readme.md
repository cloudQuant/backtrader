# 0652 MA Reverse

## 策略概述

该策略是对 MT5 EA `0652_MA_Reverse` 的 Backtrader 迁移版本。

- 使用 SMA(14) 计算均线
- 统计价格连续在均线上方/下方的 bar 数
- 连续超过 150 根在上方时做空（均值回归）
- 连续超过 150 根在下方时做多
- 固定 TP，无 SL

## 核心逻辑

1. `count` 计数器追踪价格连续偏离 MA 的方向和根数。
2. 当 `count > 150` 且 `price > MA` 时卖出。
3. 当 `count < -150` 且 `price < MA` 时买入。
4. 持仓使用固定 `take_profit` 管理。

## 迁移说明

- 原 EA 在满足条件时会在每根新 bar 重复开仓；迁移版按单净仓限制。
- 示例使用 `XAUUSD_M15.csv` 并按 `M30` 压缩运行。

## 主要参数

- `ma_period`
- `count_threshold`
- `take_profit`
- `lots`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与首版可运行脚手架已建立。
- 待后续补做本地回测校验。

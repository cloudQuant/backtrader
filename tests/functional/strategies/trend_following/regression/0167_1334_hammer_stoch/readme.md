# 1334 Hammer / Hanging Man + Stochastic

## 策略概述

该策略是对 MT5 EA `1334_MQL5_向导_-_基于_锤头_上吊线形态的交易信号_+_Stochastic` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为锤头 / 上吊线形态配合 Stochastic 确认。

## 核心逻辑

1. 识别 `Hammer` 与 `Hanging Man`
2. 当出现锤头且 `%D` 处于低位时做多
3. 当出现上吊线且 `%D` 处于高位时做空
4. 持仓后根据 Stochastic 状态变化离场

## 主要参数

- `stoch_k`
- `stoch_d`
- `stoch_slow`
- `ma_period`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 对齐说明

- 当前版本保留了锤头 / 上吊线 + Stochastic 的主流程
- `1325` 是同一形态家族的 CCI 版本

# 1343 Three Crows / Three Soldiers + RSI

## 策略概述

该策略是对 MT5 EA `1343_MQL5_向导_-_基于_3_乌鸦_3_白兵_+_RSI_的交易信号` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为三乌鸦 / 三白兵反转形态配合 RSI 确认。

## 核心逻辑

1. 识别 `Three White Soldiers` / `Three Black Crows`
2. 看涨形态出现且 RSI 支持反转时做多
3. 看跌形态出现且 RSI 支持反转时做空
4. 持仓后根据 RSI 区域变化离场

## 主要参数

- `rsi_period`
- `ma_period`
- `lot`
- `point`
- `price_digits`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 对齐说明

- 当前版本保留了三兵/三鸦形态 + RSI 过滤的主体结构
- 与 1346/1345/1344 同属一个蜡烛形态家族

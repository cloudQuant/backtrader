# 1338 Harami + Stochastic

## 策略概述

该策略是对 MT5 EA `1338_MQL5_向导_-_基于_牛市孕育_熊市孕育形态的交易信号_+_Stochastic` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为 Harami 反转形态配合 Stochastic 确认。

## 核心逻辑

1. 识别 `Bullish Harami` 与 `Bearish Harami`
2. 当出现牛市孕育且 `%D` 处于低位时做多
3. 当出现熊市孕育且 `%D` 处于高位时做空
4. 持仓后依据 Stochastic 的超买/超卖反向变化离场

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

- 当前版本保留了 Harami 形态 + Stochastic 过滤框架
- 属于 MQL5 Wizard 标准蜡烛反转模块的一部分

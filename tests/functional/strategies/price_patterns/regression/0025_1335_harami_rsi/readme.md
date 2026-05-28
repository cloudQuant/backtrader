# 1335 Harami + RSI

## 策略概述

该策略是对 MT5 EA `1335_MQL5_向导_-_基于_牛市孕育_熊市孕育形态的交易信号_+_RSI` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为 Harami 反转形态配合 RSI 确认。

## 核心逻辑

1. 识别 `Bullish Harami` 与 `Bearish Harami`
2. 当出现牛市孕育且 `RSI < 40` 时做多
3. 当出现熊市孕育且 `RSI > 60` 时做空
4. 持仓后当 RSI 穿越 `30/70` 关键阈值时离场

## 主要参数

- `rsi_period=37`
- `ma_period=7`
- `lot`
- `point`
- `price_digits`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 对齐说明

- 该版本参照原始 MQL5 文档中的 `PeriodRSI=37`、`MA_period=7`
- 开仓阈值保持 `40/60`，平仓阈值保持 `30/70`
- 与 `1338/1337/1336` 同属 Harami 形态家族，仅将确认器替换为 RSI

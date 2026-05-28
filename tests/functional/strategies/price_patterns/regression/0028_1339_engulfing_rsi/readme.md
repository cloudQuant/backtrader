# 1339 Engulfing + RSI

## 策略概述

该策略是对 MT5 EA `1339_MQL5_向导_-_基于_牛市_熊市_吞噬形态的交易信号_+_RSI` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为吞噬形态配合 RSI 确认。

## 核心逻辑

1. 识别 `Bullish Engulfing` 与 `Bearish Engulfing`
2. 当出现牛市吞噬且 `RSI < 40` 时做多
3. 当出现熊市吞噬且 `RSI > 60` 时做空
4. 持仓后当 RSI 穿越 `30/70` 关键阈值时离场

## 主要参数

- `rsi_period=11`
- `ma_period=5`
- `lot`
- `point`
- `price_digits`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 对齐说明

- 该版本参照原始 MQL5 文档中的 `PeriodRSI=11`、`MA_period=5`
- 开仓阈值保持 `40/60`，平仓阈值保持 `30/70`
- 与 `1340` 同属吞噬形态家族，仅将确认器由 MFI 替换为 RSI

# 1340 Engulfing + MFI

## 策略概述

该策略是对 MT5 EA `1340_MQL5_向导_-_基于_牛市_熊市_吞噬形态的交易信号_+_MFI` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为吞噬形态配合 MFI 确认。

## 核心逻辑

1. 识别 `Bullish Engulfing` 与 `Bearish Engulfing`
2. 当出现牛市吞噬且 MFI 支持超卖反转时做多
3. 当出现熊市吞噬且 MFI 支持超买反转时做空
4. 持仓后根据 MFI 状态变化离场

## 主要参数

- `mfi_period`
- `ma_period`
- `lot`
- `point`
- `price_digits`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 对齐说明

- 当前版本保留了吞噬形态 + MFI 过滤的 MQL5 Wizard 结构
- 该策略属于反转 K 线 + 振荡器确认系列

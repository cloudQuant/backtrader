# 0751 布林带

## 策略概述

该策略是对 MT5 EA `0751_布林带` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的主要结构：

- 以 `PRICE_OPEN` 计算布林带
- 收盘价突破上轨外扩距离时做空
- 收盘价跌破下轨外扩距离时做多
- 持仓后按固定盈利/亏损阈值平仓

## 核心逻辑

1. 计算 `BB(period=4, deviation=2)`。
2. 若 `close > upper + distance`，则产生做空信号。
3. 若 `close < lower - distance`，则产生做多信号。
4. 若开启 `LotIncrease`，手数按 `balance / StartingBalance` 递增。
5. 持仓后，当浮盈达到 `ProfitMade` 或浮亏达到 `LossLimit` 时平仓。

## 主要参数

- `profit_made`
- `loss_limit`
- `bb_period`
- `bb_deviation`
- `b_distance`
- `lots`
- `lot_increase`

## 对齐说明

- 原 EA 使用 `PRICE_OPEN` 作为布林带价格源，当前迁移保持这一点。
- 原实现同时给新仓附加了 `SL/TP`，随后又按浮盈/浮亏阈值主动平仓；当前版本保留“阈值平仓”为主逻辑。
- 当前仍保持 `OneOrderOnly` 默认开启。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。

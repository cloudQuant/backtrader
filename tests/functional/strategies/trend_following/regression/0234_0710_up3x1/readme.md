# 0710 up3x1

## 策略概述

该策略是对 MT5 EA `0710_up3x1` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 三条 EMA 排列与拐头作为入场条件
- 单仓开平
- 固定 `SL/TP`
- 趋势延续时使用 trailing
- 均线结构破坏时提前离场

## 核心逻辑

1. 三条 EMA 在上一 bar 呈顺序排列。
2. 当前 bar 出现中快线拐头并保持相对慢线位置时入场。
3. 持仓后若均线结构被破坏，则提前平仓。
4. 盈利达到阈值后启动 trailing。

## 迁移说明

- 原 EA 带有 `hedging only` 检查，但实际交易结构为单仓模型。
- 迁移版聚焦其三均线结构交易逻辑与持仓管理。

## 主要参数

- `take_profit`
- `stop_loss`
- `trailing_stop`
- `ma_period_one`
- `ma_period_two`
- `ma_period_three`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。

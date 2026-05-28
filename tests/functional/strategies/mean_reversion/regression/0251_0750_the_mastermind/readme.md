# 0750 大师观念

## 策略概述

该策略是对 MT5 EA `0750_大师观念` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的主要结构：

- 使用 `Stochastic` 与 `Williams %R`
- `Stochastic signal < 3` 且 `%R < -99.9` 时做多
- `Stochastic signal > 97` 且 `%R > -0.1` 时做空
- 反向信号平仓，并支持 `BreakEven` 与 `TrailingStop`

## 核心逻辑

1. 从 `Stochastic signal` 与 `WPR` 读取极端超买/超卖信号。
2. 出现买入条件时开多，出现卖出条件时开空。
3. 若持有多单且出现卖出条件，则平多；空单对称处理。
4. 新仓附带固定 `SL/TP`。
5. 浮盈超过 `BreakEven` 后先把止损抬到开仓价；超过 `TrailingStop` 后开始移动保护止损。

## 主要参数

- `lots`
- `stop_loss`
- `take_profit`
- `trade_at_close_bar`
- `trailing_stop`
- `trailing_step`
- `break_even`

## 对齐说明

- 原 EA 里的声音、图表文字、日志与邮件提醒属于附属输出，当前迁移不包含。
- 原实现支持 `TradeAtCloseBar` 与新 bar 节奏控制；当前版本在 bar 级 `next()` 中运行，等价于按 bar 收盘处理。
- 原源码里 `ExtTrailingStep` 赋值时直接取了 `InpTrailingStop`，当前迁移按参数语义使用 `trailing_step`。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
